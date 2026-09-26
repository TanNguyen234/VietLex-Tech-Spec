"""Exact phrase lookup over complete legal documents indexed as Qdrant payloads."""

import hashlib

import httpx

from app.config import system_ssl_context
from app.services.body_search import BodySearchUnavailable, _parts
from app.services.full_doc_body_search import _marked_section, _WORD


class QdrantFullDocBodySearch:
    def __init__(self, *, url: str, api_key: str, collection: str, store,
                 client: httpx.Client | None = None):
        if not url or not api_key or not collection:
            raise ValueError("qdrant_body_search_config_missing")
        self.endpoint = url.rstrip("/") + "/collections/" + collection
        self.store = store
        self.client = client or httpx.Client(verify=system_ssl_context(), timeout=10.0)
        self.client.headers.update({"api-key": api_key})

    def _request(self, method: str, suffix: str, *, payload: dict | None = None):
        try:
            response = self.client.request(method, self.endpoint + suffix, json=payload)
            response.raise_for_status()
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError("invalid_qdrant_response")
            return value
        except (httpx.HTTPError, ValueError) as error:
            raise BodySearchUnavailable("qdrant_body_rpc_failed") from error

    def coverage(self):
        result = self._request("GET", "").get("result", {})
        if not isinstance(result, dict):
            raise BodySearchUnavailable("qdrant_invalid_coverage")
        schema = result.get("payload_schema", {}).get("body", {})
        if not isinstance(schema, dict):
            raise BodySearchUnavailable("qdrant_invalid_coverage")
        params = schema.get("params", {})
        try:
            source_count = self.store.count_documents()
        except RuntimeError as error:
            raise BodySearchUnavailable("body_source_unavailable") from error
        if (result.get("status") != "green" or type(source_count) is not int or source_count <= 0
                or result.get("points_count") != source_count or schema.get("points") != source_count
                or params.get("type") != "text" or params.get("phrase_matching") is not True
                or params.get("ascii_folding") is not True):
            raise BodySearchUnavailable("full_doc_index_not_ready")
        return {"document_count": source_count, "index_version": 1}

    def search(self, query, *, filters=None, limit=20, offset=0):
        self.coverage()
        if not isinstance(query, str) or not _WORD.search(query):
            return []
        if len(query) > 200 or not 1 <= int(limit) <= 51 or not 0 <= int(offset) <= 1000:
            raise ValueError("invalid_body_query")
        conditions = [{"key": "body", "match": {"phrase": query}}]
        for attr, field in (("legal_type", "legal_type"), ("authority", "issuing_authority")):
            value = getattr(filters, attr, "")
            if value:
                conditions.append({"key": field, "match": {"value": value}})
        date_range = {}
        for attr, key in (("issued_from", "gte"), ("issued_to", "lte")):
            value = getattr(filters, attr, "")
            if value:
                date_range[key] = value
        if date_range:
            conditions.append({"key": "issuance_date", "range": date_range})
        request = {
            "limit": offset + limit,
            "with_payload": ["document_id", "content_sha256"],
            "with_vector": False,
            "filter": {"must": conditions},
        }
        sort = getattr(filters, "sort", "default")
        if sort in ("newest", "oldest"):
            request["order_by"] = {"key": "issuance_date", "direction": "desc" if sort == "newest" else "asc"}
        elif sort != "default":
            raise ValueError("invalid_body_sort")
        result = self._request("POST", "/points/scroll", payload=request).get("result", {})
        if not isinstance(result, dict):
            raise BodySearchUnavailable("qdrant_invalid_rows")
        points = result.get("points")
        if not isinstance(points, list) or len(points) > offset + limit:
            raise BodySearchUnavailable("qdrant_invalid_rows")
        page = points[offset:offset + limit]
        ids = []
        for point in page:
            if not isinstance(point, dict) or type(point.get("id")) is not int or point["id"] <= 0:
                raise BodySearchUnavailable("qdrant_invalid_row")
            payload = point.get("payload")
            if (not isinstance(payload, dict) or payload.get("document_id") != point["id"]
                    or not isinstance(payload.get("content_sha256"), str)):
                raise BodySearchUnavailable("qdrant_invalid_row")
            ids.append(point["id"])
        if len(set(ids)) != len(ids):
            raise BodySearchUnavailable("qdrant_duplicate_rows")
        try:
            documents = self.store.get_many(ids)
        except RuntimeError as error:
            raise BodySearchUnavailable("body_source_unavailable") from error
        rows = []
        for point in page:
            document_id = point["id"]
            document = documents.get(document_id)
            if document is None:
                raise BodySearchUnavailable("body_index_stale")
            content = document.content
            digest = point["payload"]["content_sha256"]
            if (not isinstance(content, str) or len(content) > 2_000_000
                    or hashlib.sha256(content.encode("utf-8")).hexdigest() != digest
                    or document.content_sha256 != digest):
                raise BodySearchUnavailable("body_index_stale")
            section = _marked_section(content, query)
            if section is None:
                raise BodySearchUnavailable("full_doc_match_unresolved")
            section_id, section_title, marked = section
            meta = document.metadata
            rows.append({
                "document_id": document_id,
                "document_number": meta.document_number,
                "title": meta.title,
                "source_url": meta.source_url,
                "legal_type": meta.legal_type,
                "issuing_authority": meta.issuing_authority,
                "issuance_date": meta.issuance_date,
                "section_id": section_id,
                "section_title": section_title,
                "marked": marked,
                "snippet_parts": _parts(marked),
            })
        return rows
