"""Pure structural-record preparation for the Pinecone v2 pilot."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Sequence
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
    issuing_authority: str = Field(min_length=1)
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

    schema_version: Literal["1.0.0"] = "1.0.0"
    dataset_repository: str = Field(min_length=1)
    dataset_revision: str = Field(min_length=1)
    legal_types: tuple[str, ...]
    document_count: int = Field(gt=0)
    record_count: int = Field(gt=0)
    per_legal_type_counts: dict[str, int]
    selected_document_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ordered_record_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_content_bytes: int = Field(gt=0)
    chunk_max_tokens: int = Field(gt=0)
    chunk_overlap_tokens: int = Field(ge=0)
    provider_calls: Literal[0] = 0


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
    ordered_ids = _validated_document_ids(document_ids)
    repository = _nonblank(repository, "repository")
    revision = _nonblank(revision, "revision")
    _validate_chunk_limits(max_tokens, overlap_tokens)

    records: list[StructuralRecord] = []
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
            records.extend(
                _records_for_document(
                    document,
                    chunks,
                    repository=repository,
                    revision=revision,
                    max_tokens=max_tokens,
                )
            )

    record_ids = [record.record_id for record in records]
    if len(record_ids) != len(set(record_ids)):
        raise StructuralIndexError("structural record ID collision")
    return records


def build_structural_manifest(
    records: Sequence[StructuralRecord],
    *,
    selected_document_ids: Sequence[int],
    repository: str,
    revision: str,
    raw_content_bytes: int,
    max_tokens: int = 420,
    overlap_tokens: int = 48,
) -> StructuralCorpusManifest:
    """Bind the ordered corpus and records without persisting legal text."""
    ordered_ids = _validated_document_ids(selected_document_ids)
    repository = _nonblank(repository, "repository")
    revision = _nonblank(revision, "revision")
    _validate_chunk_limits(max_tokens, overlap_tokens)
    if (
        isinstance(raw_content_bytes, bool)
        or not isinstance(raw_content_bytes, int)
        or raw_content_bytes <= 0
    ):
        raise StructuralIndexError("raw_content_bytes must be positive")

    normalized_records = list(records)
    if not normalized_records:
        raise StructuralIndexError("structural records must not be empty")
    record_ids = [record.record_id for record in normalized_records]
    if len(record_ids) != len(set(record_ids)):
        raise StructuralIndexError("structural record IDs must be unique")
    record_document_ids = {record.document_id for record in normalized_records}
    if record_document_ids != set(ordered_ids):
        raise StructuralIndexError(
            "record document IDs do not match the selected document set"
        )
    if any(record.dataset_revision != revision for record in normalized_records):
        raise StructuralIndexError("record dataset revision mismatch")

    document_legal_types: dict[int, str] = {}
    for record in normalized_records:
        if record.legal_type not in PRIMARY_LEGAL_TYPES:
            raise StructuralIndexError("record legal type is outside structural scope")
        existing = document_legal_types.setdefault(
            record.document_id,
            record.legal_type,
        )
        if existing != record.legal_type:
            raise StructuralIndexError("document legal type is inconsistent")
    per_type = Counter(document_legal_types.values())

    return StructuralCorpusManifest(
        dataset_repository=repository,
        dataset_revision=revision,
        legal_types=PRIMARY_LEGAL_TYPES,
        document_count=len(ordered_ids),
        record_count=len(normalized_records),
        per_legal_type_counts=dict(sorted(per_type.items())),
        selected_document_ids_sha256=_canonical_sha256(ordered_ids),
        ordered_record_ids_sha256=_canonical_sha256(record_ids),
        raw_content_bytes=raw_content_bytes,
        chunk_max_tokens=max_tokens,
        chunk_overlap_tokens=overlap_tokens,
    )


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
                issuing_authority=_nonblank(
                    metadata.issuing_authority,
                    "issuing_authority",
                ),
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
