from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.ingestion.content_store import ContentStore
from app.ingestion.legal_fts import LegalFtsIndex


@dataclass(frozen=True)
class LegalSearchResult:
    document_id: int
    document_number: str
    title: str
    source_url: str
    legal_type: str
    issuing_authority: str
    issuance_date: str | None


class LegalBrowser:
    def __init__(self, *, store: Any, index: Any) -> None:
        self._store = store
        self._index = index

    @classmethod
    def from_settings(cls, settings: Any) -> "LegalBrowser":
        store = ContentStore(settings.CONTENT_STORE_PATH)
        return cls(
            store=store,
            index=LegalFtsIndex(
                store=store,
                path=settings.LEGAL_FTS_PATH,
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
