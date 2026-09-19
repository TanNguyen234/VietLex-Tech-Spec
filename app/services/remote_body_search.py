"""Opt-in read-only adapter for the separately provisioned PostgreSQL body index."""

import re
from datetime import datetime
import httpx
from app.config import system_ssl_context
from app.services.body_search import BodySearchUnavailable, _parts


class SupabaseBodySearch:
    def __init__(self, *, url, publishable_key, client=None):
        self.endpoint = url.rstrip("/") + "/rest/v1/rpc/"
        self.client = client or httpx.Client(verify=system_ssl_context(), timeout=10.0)
        self.client.headers.update(
            {"apikey": publishable_key, "authorization": "Bearer " + publishable_key}
        )

    def _rpc(self, name, payload):
        try:
            response = self.client.post(self.endpoint + name, json=payload)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise BodySearchUnavailable("remote_body_rpc_failed") from error

    def coverage(self):
        value = self._rpc("legal_body_coverage", {})
        try:
            if not isinstance(value, dict) or any(
                type(value.get(key)) is not int or value[key] <= 0
                for key in ("document_count", "passage_count")
            ):
                raise ValueError("not_ready")
            datetime.fromisoformat(value["built_at"].replace("Z", "+00:00"))
            if not re.fullmatch(r"[0-9a-f]{64}", value["source_sha256"]):
                raise ValueError("invalid_hash")
        except (KeyError, TypeError, AttributeError, ValueError) as error:
            raise BodySearchUnavailable("remote_body_not_ready") from error
        return value

    def search(self, query, *, filters=None, limit=20, offset=0):
        self.coverage()
        payload = dict(
            query_text=query[:200],
            limit_count=max(1, min(int(limit), 51)),
            offset_count=max(0, min(int(offset), 1000)),
        )
        for name, field in [
            ("type_filter", "legal_type"),
            ("authority_filter", "authority"),
            ("issued_from", "issued_from"),
            ("issued_to", "issued_to"),
            ("sort_order", "sort"),
        ]:
            payload[name] = getattr(
                filters, field, "default" if name == "sort_order" else ""
            )
        rows = self._rpc("search_legal_body", payload)
        if not isinstance(rows, list) or len(rows) > payload["limit_count"]:
            raise BodySearchUnavailable("remote_body_invalid_rows")
        for row in rows:
            if (
                not isinstance(row, dict)
                or type(row.get("document_id")) is not int
                or not isinstance(row.get("marked"), str)
                or not re.fullmatch(
                    r"section-[0-9]+|preamble|full-text", str(row.get("section_id", ""))
                )
            ):
                raise BodySearchUnavailable("remote_body_invalid_row")
        return [{**row, "snippet_parts": _parts(row["marked"])} for row in rows]
