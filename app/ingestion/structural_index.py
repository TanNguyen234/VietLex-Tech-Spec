"""Provider-free structural-record preparation for the Qdrant v2 pilot."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterator, Sequence
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field

from app.ingestion.content_store import ContentStore, StoredDocument
from app.ingestion.legal_text import EvidenceChunk, chunk_document


PRIMARY_LEGAL_TYPES = ("Hiến pháp", "Luật", "Pháp lệnh")
_DOCUMENT_PAGE_SIZE = 512
_DOCUMENT_READ_BATCH_SIZE = 128
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class StructuralIndexError(ValueError):
    """Raised when the local structural corpus contract is violated."""


class StructuralRecord(BaseModel):
    """One immutable legal-structure record before remote embedding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str = Field(min_length=1)
    body: str = Field(min_length=1)
    document_id: int = Field(gt=0)
    document_number: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    legal_type: str = Field(min_length=1)
    issuing_authority: str | None = Field(min_length=1)
    issuance_date: str | None
    article: str | None
    clause: str | None
    heading_path: str
    citation: str = Field(min_length=1)
    token_count: int = Field(gt=0)
    dataset_revision: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding: None = None


class StructuralCorpusManifest(BaseModel):
    """Body-free identity and capacity manifest for a structural build."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["2.0.0"] = "2.0.0"
    dataset_repository: str = Field(min_length=1)
    dataset_revision: str = Field(min_length=1)
    legal_types: tuple[str, ...]
    document_count: int = Field(gt=0)
    record_count: int = Field(gt=0)
    per_legal_type_counts: dict[str, int]
    selected_document_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ordered_record_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    body_bytes: int = Field(gt=0)
    approximate_token_count: int = Field(gt=0)
    chunk_max_tokens: int = Field(gt=0)
    chunk_overlap_tokens: int = Field(ge=0)
    provider_calls: Literal[0] = 0


class StructuralManifestBuilder:
    """Accumulate a body-free manifest without retaining record bodies."""

    def __init__(
        self,
        *,
        selected_document_ids: Sequence[int],
        repository: str,
        revision: str,
        max_tokens: int = 420,
        overlap_tokens: int = 48,
    ) -> None:
        self._document_ids = _validated_document_ids(selected_document_ids)
        self._document_id_set = set(self._document_ids)
        self._repository = _nonblank(repository, "repository")
        self._revision = _nonblank(revision, "revision")
        _validate_chunk_limits(max_tokens, overlap_tokens)
        self._max_tokens = max_tokens
        self._overlap_tokens = overlap_tokens
        self._seen_record_ids: set[str] = set()
        self._document_legal_types: dict[int, str] = {}
        self._ordered_record_ids_hash = hashlib.sha256(b"[")
        self._record_count = 0
        self._body_bytes = 0
        self._approximate_token_count = 0

    def add(self, record: StructuralRecord) -> None:
        if record.record_id in self._seen_record_ids:
            raise StructuralIndexError("structural record IDs must be unique")
        if record.document_id not in self._document_id_set:
            raise StructuralIndexError(
                "record document IDs do not match the selected document set"
            )
        if record.dataset_revision != self._revision:
            raise StructuralIndexError("record dataset revision mismatch")
        if record.legal_type not in PRIMARY_LEGAL_TYPES:
            raise StructuralIndexError("record legal type is outside structural scope")
        existing = self._document_legal_types.setdefault(
            record.document_id,
            record.legal_type,
        )
        if existing != record.legal_type:
            raise StructuralIndexError("document legal type is inconsistent")
        if record.token_count > self._max_tokens:
            raise StructuralIndexError("structural record exceeds the token contract")

        if self._record_count:
            self._ordered_record_ids_hash.update(b",")
        self._ordered_record_ids_hash.update(
            json.dumps(
                record.record_id,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        self._seen_record_ids.add(record.record_id)
        self._record_count += 1
        self._body_bytes += len(record.body.encode("utf-8"))
        self._approximate_token_count += record.token_count

    def build(self) -> StructuralCorpusManifest:
        if not self._record_count:
            raise StructuralIndexError("structural records must not be empty")
        if set(self._document_legal_types) != self._document_id_set:
            raise StructuralIndexError(
                "record document IDs do not match the selected document set"
            )
        ordered_hash = self._ordered_record_ids_hash.copy()
        ordered_hash.update(b"]")
        per_type = Counter(self._document_legal_types.values())
        return StructuralCorpusManifest(
            dataset_repository=self._repository,
            dataset_revision=self._revision,
            legal_types=PRIMARY_LEGAL_TYPES,
            document_count=len(self._document_ids),
            record_count=self._record_count,
            per_legal_type_counts=dict(sorted(per_type.items())),
            selected_document_ids_sha256=_canonical_sha256(self._document_ids),
            ordered_record_ids_sha256=ordered_hash.hexdigest(),
            body_bytes=self._body_bytes,
            approximate_token_count=self._approximate_token_count,
            chunk_max_tokens=self._max_tokens,
            chunk_overlap_tokens=self._overlap_tokens,
        )


def select_structural_document_ids(
    store: ContentStore,
    *,
    page_size: int = _DOCUMENT_PAGE_SIZE,
) -> list[int]:
    """Select the complete primary-legislation scope in stable ID order."""
    if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size <= 0:
        raise StructuralIndexError("page_size must be a positive integer")

    selected: list[int] = []
    after_id = -1
    while True:
        raw_page = store.iter_document_ids_by_legal_types(
            PRIMARY_LEGAL_TYPES,
            after_id=after_id,
            limit=page_size,
        )
        page = list(raw_page)
        if not page:
            return selected
        if any(
            isinstance(document_id, bool)
            or not isinstance(document_id, int)
            or document_id <= after_id
            for document_id in page
        ) or page != sorted(set(page)):
            raise StructuralIndexError("invalid structural corpus page")
        selected.extend(page)
        after_id = page[-1]


def build_structural_records(
    store: ContentStore,
    document_ids: Sequence[int],
    *,
    repository: str,
    revision: str,
    max_tokens: int = 420,
    overlap_tokens: int = 48,
) -> list[StructuralRecord]:
    """Read, validate, and structurally chunk an ordered document set."""
    return list(
        iter_structural_records(
            store,
            document_ids,
            repository=repository,
            revision=revision,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )
    )


def iter_structural_records(
    store: ContentStore,
    document_ids: Sequence[int],
    *,
    repository: str,
    revision: str,
    max_tokens: int = 420,
    overlap_tokens: int = 48,
) -> Iterator[StructuralRecord]:
    """Yield validated structural records from bounded document reads."""
    ordered_ids = _validated_document_ids(document_ids)
    repository = _nonblank(repository, "repository")
    revision = _nonblank(revision, "revision")
    _validate_chunk_limits(max_tokens, overlap_tokens)

    seen_record_ids: set[str] = set()
    for offset in range(0, len(ordered_ids), _DOCUMENT_READ_BATCH_SIZE):
        batch_ids = ordered_ids[offset : offset + _DOCUMENT_READ_BATCH_SIZE]
        documents = store.get_many(batch_ids)
        missing_ids = [
            document_id
            for document_id in batch_ids
            if document_id not in documents
        ]
        if missing_ids:
            raise StructuralIndexError(f"missing document {missing_ids[0]}")
        unexpected_ids = set(documents) - set(batch_ids)
        if unexpected_ids:
            raise StructuralIndexError("content store returned an unexpected document")

        for document_id in batch_ids:
            document = documents[document_id]
            _validate_document(document_id, document)
            chunks = chunk_document(
                document.metadata,
                document.content,
                max_tokens=max_tokens,
                overlap_tokens=overlap_tokens,
            )
            if not chunks:
                raise StructuralIndexError(
                    f"document {document_id} produced no structural chunks"
                )
            for record in _records_for_document(
                document,
                chunks,
                repository=repository,
                revision=revision,
                max_tokens=max_tokens,
            ):
                if record.record_id in seen_record_ids:
                    raise StructuralIndexError("structural record ID collision")
                seen_record_ids.add(record.record_id)
                yield record


def build_structural_manifest(
    records: Sequence[StructuralRecord],
    *,
    selected_document_ids: Sequence[int],
    repository: str,
    revision: str,
    max_tokens: int = 420,
    overlap_tokens: int = 48,
) -> StructuralCorpusManifest:
    """Bind the ordered corpus and records without persisting legal text."""
    builder = StructuralManifestBuilder(
        selected_document_ids=selected_document_ids,
        repository=repository,
        revision=revision,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
    )
    for record in records:
        builder.add(record)
    return builder.build()


def _records_for_document(
    document: StoredDocument,
    chunks: Sequence[EvidenceChunk],
    *,
    repository: str,
    revision: str,
    max_tokens: int,
) -> list[StructuralRecord]:
    metadata = document.metadata
    records: list[StructuralRecord] = []
    for chunk_index, chunk in enumerate(chunks):
        body = chunk.text.strip()
        if not body:
            raise StructuralIndexError("structural chunk body must not be blank")
        if chunk.token_count <= 0 or chunk.token_count > max_tokens:
            raise StructuralIndexError("structural chunk exceeds the token contract")
        chunk_sha256 = _text_sha256(body)
        identity = (
            f"{repository}@{revision}#{metadata.document_id}:"
            f"{chunk_index}:{chunk_sha256}"
        )
        records.append(
            StructuralRecord(
                record_id=str(uuid5(NAMESPACE_URL, identity)),
                body=body,
                document_id=metadata.document_id,
                document_number=_nonblank(
                    metadata.document_number,
                    "document_number",
                ),
                title=_nonblank(metadata.title, "title"),
                source_url=_nonblank(metadata.source_url, "source_url"),
                legal_type=_nonblank(metadata.legal_type, "legal_type"),
                issuing_authority=_nullable_nonblank(metadata.issuing_authority),
                issuance_date=metadata.issuance_date,
                article=chunk.article,
                clause=chunk.clause,
                heading_path=chunk.heading_path,
                citation=_nonblank(chunk.citation, "citation"),
                token_count=chunk.token_count,
                dataset_revision=revision,
                content_sha256=document.content_sha256,
                chunk_sha256=chunk_sha256,
            )
        )
    return records


def _validated_document_ids(document_ids: Sequence[int]) -> list[int]:
    ordered = list(document_ids)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in ordered):
        raise StructuralIndexError("document IDs must be positive integers")
    if any(value <= 0 for value in ordered):
        raise StructuralIndexError("document IDs must be positive")
    if len(ordered) != len(set(ordered)):
        raise StructuralIndexError("document IDs must be unique")
    if ordered != sorted(ordered):
        raise StructuralIndexError("document IDs must be sorted")
    return ordered


def _validate_document(document_id: int, document: StoredDocument) -> None:
    metadata = document.metadata
    if metadata.document_id != document_id:
        raise StructuralIndexError("content store document identity mismatch")
    if document.content_store_key != str(document_id):
        raise StructuralIndexError("content store key mismatch")
    if metadata.legal_type not in PRIMARY_LEGAL_TYPES:
        raise StructuralIndexError(
            f"document {document_id} is outside structural scope"
        )
    if not _SHA256_RE.fullmatch(document.content_sha256):
        raise StructuralIndexError("document content SHA-256 is malformed")
    if _text_sha256(document.content) != document.content_sha256:
        raise StructuralIndexError("document content SHA-256 mismatch")


def _validate_chunk_limits(max_tokens: int, overlap_tokens: int) -> None:
    if (
        isinstance(max_tokens, bool)
        or not isinstance(max_tokens, int)
        or max_tokens <= 0
    ):
        raise StructuralIndexError("max_tokens must be positive")
    if (
        isinstance(overlap_tokens, bool)
        or not isinstance(overlap_tokens, int)
        or overlap_tokens < 0
        or overlap_tokens >= max_tokens
    ):
        raise StructuralIndexError(
            "overlap_tokens must be nonnegative and below max_tokens"
        )


def _nonblank(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StructuralIndexError(f"{field_name} must be nonblank")
    return value.strip()


def _nullable_nonblank(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
