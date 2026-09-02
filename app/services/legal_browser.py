from __future__ import annotations

from dataclasses import dataclass
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

    def search(self, query: str, *, limit: int) -> list[int]:
        safe_query = " ".join(
            query.replace("*", " ")
            .replace(",", " ")
            .replace("(", " ")
            .replace(")", " ")
            .replace('"', " ")
            .split()
        )
        if not safe_query:
            return []
        rows = self._get(
            {
                "select": "document_id",
                "or": (
                    f"(document_number.ilike.*{safe_query}*,"
                    f"title.ilike.*{safe_query}*)"
                ),
                "order": "document_id.asc",
                "limit": str(limit),
            }
        )
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

    def search(self, query: str, limit: int = 20) -> list[LegalSearchResult]:
        normalized = query.strip()
        bounded_limit = max(1, min(int(limit), 50))
        if not normalized:
            return []
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
