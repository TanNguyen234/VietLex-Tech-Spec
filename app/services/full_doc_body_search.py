"""Search existing Supabase full documents and resolve reader-owned section anchors."""

import hashlib
import re
import unicodedata

import httpx

from app.config import system_ssl_context
from app.services.body_search import BodySearchUnavailable, _parts
from app.services.document_structure import document_sections


_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def _fold(value: str) -> str:
    return "".join(
        character for character in unicodedata.normalize("NFKD", value.casefold().replace("đ", "d"))
        if not unicodedata.combining(character)
    )


def _match_span(body: str, wanted: list[str]) -> tuple[int, int] | None:
    words = [(_fold(match.group()), match.start(), match.end()) for match in _WORD.finditer(body)]
    for start in range(len(words) - len(wanted) + 1):
        if words[start][0] == wanted[0] and all(
            words[start + offset][0] == word for offset, word in enumerate(wanted[1:], 1)
        ):
            return words[start][1], words[start + len(wanted) - 1][2]
    return None


def _marked_section(content: str, query: str) -> tuple[str, str, str] | None:
    wanted = [_fold(match.group()) for match in _WORD.finditer(query)]
    if not wanted:
        return None
    sections = document_sections(content)
    for section in sections:
        body = section["text"]
        span = _match_span(body, wanted)
        if span is not None:
            first, last = span
            left, right = max(0, first - 100), min(len(body), last + 100)
            marked = body[left:first] + "\ue000" + body[first:last] + "\ue001" + body[last:right]
            return section["id"], section["title"], marked
    # A phrase can cross the reader's heading boundary. Keep the full-document
    # match and link to the section containing its first word.
    span = _match_span(content, wanted)
    if span is None:
        return None
    first, last = span
    offset = 0
    section = sections[0]
    for candidate in sections:
        if first < offset + len(candidate["text"]):
            section = candidate
            break
        offset += len(candidate["text"])
    left, right = max(0, first - 100), min(len(content), last + 100)
    marked = content[left:first] + "\ue000" + content[first:last] + "\ue001" + content[last:right]
    return section["id"], section["title"], marked


class SupabaseFullDocBodySearch:
    def __init__(self, *, url: str, publishable_key: str, client: httpx.Client | None = None):
        self.endpoint = url.rstrip("/") + "/rest/v1/rpc/"
        self.client = client or httpx.Client(verify=system_ssl_context(), timeout=10.0)
        self.client.headers.update({"apikey": publishable_key, "authorization": "Bearer " + publishable_key})

    def _rpc(self, name: str, payload: dict):
        try:
            response = self.client.post(self.endpoint + name, json=payload)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise BodySearchUnavailable("full_doc_rpc_failed") from error

    def coverage(self):
        value = self._rpc("legal_full_doc_coverage", {})
        if (
            not isinstance(value, dict)
            or type(value.get("document_count")) is not int
            or value["document_count"] <= 0
            or value.get("index_version") != 1
        ):
            raise BodySearchUnavailable("full_doc_index_not_ready")
        return value

    def search(self, query, *, filters=None, limit=20, offset=0):
        self.coverage()
        if not _WORD.search(query):
            return []
        payload = {
            "query_text": query[:200],
            "limit_count": max(1, min(int(limit), 51)),
            "offset_count": max(0, min(int(offset), 1000)),
            "type_filter": getattr(filters, "legal_type", ""),
            "authority_filter": getattr(filters, "authority", ""),
            "issued_from": getattr(filters, "issued_from", ""),
            "issued_to": getattr(filters, "issued_to", ""),
            "sort_order": getattr(filters, "sort", "default"),
        }
        rows = self._rpc("search_legal_full_doc", payload)
        if not isinstance(rows, list) or len(rows) > payload["limit_count"]:
            raise BodySearchUnavailable("full_doc_invalid_rows")
        results = []
        for row in rows:
            required = ("document_number", "title", "source_url", "legal_type", "issuing_authority")
            if (
                not isinstance(row, dict)
                or type(row.get("document_id")) is not int
                or any(not isinstance(row.get(key), str) for key in required)
                or (row.get("issuance_date") is not None and not isinstance(row["issuance_date"], str))
            ):
                raise BodySearchUnavailable("full_doc_invalid_row")
            content, digest = row.get("content"), row.get("content_sha256")
            if not isinstance(content, str) or not isinstance(digest, str) or len(content) > 2_000_000:
                raise BodySearchUnavailable("full_doc_invalid_row")
            if hashlib.sha256(content.encode()).hexdigest() != digest:
                raise BodySearchUnavailable("full_doc_source_mismatch")
            section = _marked_section(content, query)
            if section is None:
                raise BodySearchUnavailable("full_doc_match_unresolved")
            section_id, section_title, marked = section
            results.append({
                key: row[key] for key in (
                    "document_id", "document_number", "title", "source_url", "legal_type",
                    "issuing_authority", "issuance_date",
                )
            } | {
                "section_id": section_id, "section_title": section_title,
                "marked": marked, "snippet_parts": _parts(marked),
            })
        return results
