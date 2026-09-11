from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from contextlib import closing
import sqlite3
import time
from typing import Any

import httpx

from app.config import system_ssl_context
from app.ingestion.content_store import ContentStore, StoredDocument
from app.ingestion.legal_fts import LegalFtsIndex
from app.ingestion.legal_text import DocumentMetadata


@dataclass(frozen=True)
class LegalSearchResult:
    document_id: int
    document_number: str
    title: str
    source_url: str
    legal_type: str
    issuing_authority: str
    issuance_date: str | None


@dataclass(frozen=True)
class SearchFilters:
    legal_type: str = ""
    authority: str = ""
    issued_from: str = ""
    issued_to: str = ""
    sort: str = "default"

    def __post_init__(self):
        for value in (self.issued_from, self.issued_to):
            if value and date.fromisoformat(value).isoformat() != value:
                raise ValueError("invalid_date")
        if self.issued_from and self.issued_to and self.issued_from > self.issued_to:
            raise ValueError("invalid_date_range")
        if self.sort not in {"default", "newest", "oldest"}:
            raise ValueError("invalid_sort")

    @property
    def active(self):
        return bool(self.legal_type or self.authority or self.issued_from or self.issued_to or self.sort != "default")


class LegalBrowserBackendError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SupabaseLegalStore:
    _METADATA_FIELDS = (
        "document_id,document_number,title,source_url,legal_type,"
        "legal_sectors,issuing_authority,issuance_date"
    )
    _DOCUMENT_FIELDS = (
        f"{_METADATA_FIELDS},content,content_sha256,content_store_key,quality_flags"
    )

    def __init__(
        self,
        *,
        url: str,
        publishable_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        normalized_url = url.rstrip("/")
        if not normalized_url or not publishable_key:
            raise ValueError("Supabase URL and publishable key are required")
        self._endpoint = f"{normalized_url}/rest/v1/legal_documents"
        self._client = client or httpx.Client(
            headers={
                "apikey": publishable_key,
                "authorization": f"Bearer {publishable_key}",
            },
            verify=system_ssl_context(),
            timeout=httpx.Timeout(10.0),
        )
        if client is not None:
            self._client.headers.update(
                {
                    "apikey": publishable_key,
                    "authorization": f"Bearer {publishable_key}",
                }
            )

    def _get(self, params: dict[str, str]) -> list[dict[str, Any]]:
        try:
            response = self._client.get(self._endpoint, params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as error:
            raise LegalBrowserBackendError(
                "Supabase legal-document request failed.",
                status_code=error.response.status_code,
            ) from error
        except (httpx.HTTPError, ValueError) as error:
            raise LegalBrowserBackendError(
                "Supabase legal-document request failed."
            ) from error
        if not isinstance(payload, list):
            raise LegalBrowserBackendError(
                "Supabase legal-document response was not a row list."
            )
        return payload

    @staticmethod
    def _metadata(row: dict[str, Any]) -> DocumentMetadata:
        return DocumentMetadata(
            document_id=int(row["document_id"]),
            document_number=str(row["document_number"]),
            title=str(row["title"]),
            source_url=str(row["source_url"]),
            legal_type=str(row["legal_type"]),
            legal_sectors=str(row["legal_sectors"]),
            issuing_authority=str(row["issuing_authority"]),
            issuance_date=(
                str(row["issuance_date"])
                if row.get("issuance_date") is not None
                else None
            ),
        )

    def search(self, query: str, *, limit: int, filters: SearchFilters | None = None) -> list[int]:
        safe_query = " ".join(
            query.replace("*", " ")
            .replace(",", " ")
            .replace("(", " ")
            .replace(")", " ")
            .replace('"', " ")
            .split()
        )
        if not safe_query and not (filters and filters.active):
            return []
        params = {
                "select": "document_id",
                "or": (
                    f"(document_number.ilike.*{safe_query}*,"
                    f"title.ilike.*{safe_query}*)"
                ),
                "order": "document_id.asc",
                "limit": str(limit),
            }
        if not safe_query:
            params.pop("or")
        if filters:
            if filters.legal_type:
                params["legal_type"] = "eq." + filters.legal_type
            if filters.authority:
                params["issuing_authority"] = "eq." + filters.authority
            dates = []
            if filters.issued_from:
                dates.append("issuance_date.gte." + filters.issued_from)
            if filters.issued_to:
                dates.append("issuance_date.lte." + filters.issued_to)
            if dates:
                params["and"] = "(" + ",".join(dates) + ")"
            if filters.sort != "default":
                direction = "desc" if filters.sort == "newest" else "asc"
                params["order"] = f"issuance_date.{direction}.nullslast,document_id.asc"
        rows = self._get(params)
        return [int(row["document_id"]) for row in rows]

    def get_metadata_many(
        self, document_ids: list[int]
    ) -> dict[int, DocumentMetadata]:
        if not document_ids:
            return {}
        rows = self._get(
            {
                "select": self._METADATA_FIELDS,
                "document_id": f"in.({','.join(map(str, document_ids))})",
            }
        )
        metadata = [self._metadata(row) for row in rows]
        return {item.document_id: item for item in metadata}

    def get_many(self, document_ids: list[int]) -> dict[int, StoredDocument]:
        if not document_ids:
            return {}
        rows = self._get(
            {
                "select": self._DOCUMENT_FIELDS,
                "document_id": f"in.({','.join(map(str, document_ids))})",
            }
        )
        documents = [
            StoredDocument(
                metadata=self._metadata(row),
                content=str(row["content"]),
                content_sha256=str(row["content_sha256"]),
                content_store_key=str(row["content_store_key"]),
                quality_flags=tuple(row.get("quality_flags") or ()),
            )
            for row in rows
        ]
        return {item.metadata.document_id: item for item in documents}


class LegalBrowser:
    def __init__(self, *, store: Any, index: Any) -> None:
        self._store = store
        self._index = index

    @classmethod
    def from_settings(cls, settings: Any) -> "LegalBrowser":
        if getattr(settings, "SERVERLESS_ONLINE_ONLY", False):
            store = SupabaseLegalStore(
                url=(getattr(settings, "SUPABASE_URL", None) or "").strip(),
                publishable_key=(
                    getattr(settings, "SUPABASE_PUBLISHABLE_KEY", None) or ""
                ).strip(),
            )
            return cls(store=store, index=store)
        use_v3 = getattr(settings, "USE_LEGACY_FREE_PIPELINE", None) is False
        content_path = (
            settings.V3_CONTENT_STORE_PATH
            if use_v3
            else settings.CONTENT_STORE_PATH
        )
        fts_path = (
            settings.V3_LEGAL_FTS_PATH
            if use_v3
            else settings.LEGAL_FTS_PATH
        )
        store = ContentStore(content_path)
        return cls(
            store=store,
            index=LegalFtsIndex(
                store=store,
                path=fts_path,
                dataset_revision=settings.DATASET_REVISION,
            ),
        )

    def search(self, query: str, limit: int = 20, *, filters: SearchFilters | None = None) -> list[LegalSearchResult]:
        normalized = query.strip()
        bounded_limit = max(1, min(int(limit), 50))
        if not normalized and not (filters and filters.active):
            return []
        if filters and filters.active:
            document_ids = self._index.search(normalized, limit=bounded_limit, filters=filters) if isinstance(self._index, SupabaseLegalStore) else self._filtered_local_ids(normalized, filters, bounded_limit)
        else:
            document_ids = self._index.search(normalized, limit=bounded_limit)
        metadata = self._store.get_metadata_many(document_ids)
        return [
            LegalSearchResult(
                document_id=item.document_id,
                document_number=item.document_number,
                title=item.title,
                source_url=item.source_url,
                legal_type=item.legal_type,
                issuing_authority=item.issuing_authority,
                issuance_date=item.issuance_date,
            )
            for document_id in document_ids
            if (item := metadata.get(document_id)) is not None
        ]

    def get_document(self, document_id: int):
        return self._store.get_many([document_id]).get(document_id)

    def quality_queue(self, issue: str, *, offset: int = 0):
        if issue not in {"missing_date", "missing_source"} or not 0 <= offset <= 100_000:
            raise ValueError("invalid_quality_filter")
        if isinstance(self._store, SupabaseLegalStore):
            params = {"select": self._store._METADATA_FIELDS, "order": "document_id.asc", "limit": "50", "offset": str(offset)}
            if issue == "missing_date":
                params["issuance_date"] = "is.null"
            else:
                params["or"] = "(source_url.is.null,source_url.eq.)"
            return [self._store._metadata(row) for row in self._store._get(params)]
        condition = "issuance_date IS NULL OR issuance_date = ''" if issue == "missing_date" else "source_url IS NULL OR source_url = ''"
        try:
            with closing(sqlite3.connect(self._store.path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
                deadline = time.monotonic() + 3.0
                connection.set_progress_handler(lambda: time.monotonic() > deadline, 10_000)
                ids = [row[0] for row in connection.execute("SELECT document_id FROM metadata WHERE " + condition + " ORDER BY document_id LIMIT 50 OFFSET ?", (offset,))]
            metadata = self._store.get_metadata_many(ids)
            return [metadata[value] for value in ids if value in metadata]
        except sqlite3.Error as error:
            raise LegalBrowserBackendError("Local quality queue unavailable.") from error

    def _filtered_local_ids(self, query: str, filters: SearchFilters, limit: int) -> list[int]:
        # Filter the metadata relation before LIMIT; never scan/decompress bodies.
        clauses, values = [], []
        if query:
            phrase = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            clauses.append("(document_number LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\')")
            values.extend([phrase, phrase])
        for column, operator, value in [("legal_type", "=", filters.legal_type), ("issuing_authority", "=", filters.authority), ("issuance_date", ">=", filters.issued_from), ("issuance_date", "<=", filters.issued_to)]:
            if value:
                clauses.append(f"{column} {operator} ?")
                values.append(value)
        order = {"default": "document_id ASC", "newest": "issuance_date IS NULL, issuance_date DESC, document_id ASC", "oldest": "issuance_date IS NULL, issuance_date ASC, document_id ASC"}[filters.sort]
        sql = "SELECT document_id FROM metadata WHERE " + (" AND ".join(clauses) or "1") + f" ORDER BY {order} LIMIT ?"
        try:
            with closing(sqlite3.connect(self._store.path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
                deadline = time.monotonic() + 3.0
                connection.set_progress_handler(lambda: time.monotonic() > deadline, 10_000)
                return [row[0] for row in connection.execute(sql, [*values, limit])]
        except sqlite3.Error as error:
            raise LegalBrowserBackendError("Local filtered search failed.") from error
