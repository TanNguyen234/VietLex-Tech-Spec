"""Incremental Vertex AI embedding lane for a separate Qdrant collection."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path
from typing import Callable, Protocol, Sequence
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import models

from app.ingestion.legal_text import EvidenceChunk, chunk_document
from app.ingestion.structural_index import StructuralRecord
from app.ingestion.structural_qdrant import (
    build_structural_inference_text,
    point_payload,
)


PROTECTED_COLLECTIONS = frozenset(
    {
        "vietlex-embedding-staging",
        "vietlex-rerank-staging",
        "vietlex-legal-rag-v2-pilot-384",
    }
)

DEFAULT_MIGRATION_LEGAL_TYPES = (
    "Luật",
    "Pháp lệnh",
    "Nghị định",
    "Nghị quyết",
    "Thông tư",
    "Thông tư liên tịch",
    "Văn bản hợp nhất",
    "Quyết định",
    "Chỉ thị",
    "Công văn",
    "Hướng dẫn",
    "Điều ước quốc tế",
)


class DocumentIdStore(Protocol):
    def iter_document_ids_by_legal_types(
        self,
        legal_types: Sequence[str],
        *,
        after_id: int,
        limit: int,
    ) -> list[int]: ...


@dataclass(frozen=True)
class VertexQdrantContract:
    collection_name: str = "vietlex-legal-rag-v3-vertex-1024"
    dense_vector_name: str = "dense"
    sparse_vector_name: str = "sparse"
    embedding_model: str = "gemini-embedding-2"
    vector_size: int = 1024
    distance: models.Distance = models.Distance.COSINE

    def __post_init__(self) -> None:
        if not self.collection_name.strip():
            raise ValueError("collection_name must be nonblank")
        if self.collection_name in PROTECTED_COLLECTIONS:
            raise ValueError("protected Qdrant collections cannot be migration targets")
        if self.vector_size < 768:
            raise ValueError("Vertex migration vector size must be at least 768")
        if self.dense_vector_name == self.sparse_vector_name:
            raise ValueError("dense and sparse vector names must differ")


def select_evenly_spaced_chunks(
    chunks: Sequence[EvidenceChunk],
    *,
    limit: int,
) -> list[EvidenceChunk]:
    """Keep structural coverage across a long document under a point budget."""
    if limit <= 0:
        raise ValueError("chunk limit must be positive")
    values = list(chunks)
    if len(values) <= limit:
        return values
    if limit == 1:
        return [values[0]]
    indexes = [
        round(position * (len(values) - 1) / (limit - 1))
        for position in range(limit)
    ]
    return [values[index] for index in indexes]


def select_diverse_document_ids(
    store: DocumentIdStore,
    *,
    legal_types: Sequence[str] = DEFAULT_MIGRATION_LEGAL_TYPES,
    limit: int,
) -> list[int]:
    """Select a deterministic, balanced prefix across legal document types."""
    if limit <= 0:
        raise ValueError("document limit must be positive")
    types = tuple(dict.fromkeys(item.strip() for item in legal_types if item.strip()))
    if not types:
        raise ValueError("at least one legal type is required")
    pages = [
        store.iter_document_ids_by_legal_types(
            [legal_type],
            after_id=-1,
            limit=limit,
        )
        for legal_type in types
    ]
    selected: list[int] = []
    for row in zip_longest(*pages):
        for document_id in row:
            if document_id is None or document_id in selected:
                continue
            selected.append(document_id)
            if len(selected) >= limit:
                return sorted(selected)
    return sorted(selected)


def build_vertex_records(
    store: object,
    document_ids: Sequence[int],
    *,
    repository: str,
    revision: str,
    max_tokens: int,
    overlap_tokens: int,
    max_chunks_per_document: int,
) -> list[StructuralRecord]:
    """Build deterministic, quality-filtered structural records for a pilot."""
    ordered_ids = list(document_ids)
    if ordered_ids != sorted(set(ordered_ids)) or any(item <= 0 for item in ordered_ids):
        raise ValueError("document IDs must be unique, positive, and sorted")
    if max_tokens <= 0 or overlap_tokens < 0 or overlap_tokens >= max_tokens:
        raise ValueError("invalid chunk limits")
    if max_chunks_per_document <= 0:
        raise ValueError("max_chunks_per_document must be positive")
    records: list[StructuralRecord] = []
    excluded_flags = {
        "empty_content",
        "encoding_damage",
        "missing_document_number",
        "missing_title",
        "missing_source_url",
    }
    for offset in range(0, len(ordered_ids), 64):
        batch_ids = ordered_ids[offset : offset + 64]
        documents = store.get_many(batch_ids)
        for document_id in batch_ids:
            document = documents.get(document_id)
            if document is None or excluded_flags.intersection(document.quality_flags):
                continue
            chunks = chunk_document(
                document.metadata,
                document.content,
                max_tokens=max_tokens,
                overlap_tokens=overlap_tokens,
            )
            selected = select_evenly_spaced_chunks(
                chunks,
                limit=max_chunks_per_document,
            )
            for chunk_index, chunk in enumerate(selected):
                body = chunk.text.strip()
                chunk_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
                identity = (
                    "vietlex-vertex-qdrant-v1:"
                    f"{repository}@{revision}#{document_id}:"
                    f"{chunk_index}:{chunk_sha256}"
                )
                metadata = document.metadata
                records.append(
                    StructuralRecord(
                        record_id=str(uuid5(NAMESPACE_URL, identity)),
                        body=body,
                        document_id=document_id,
                        document_number=metadata.document_number.strip(),
                        title=metadata.title.strip(),
                        source_url=metadata.source_url.strip(),
                        legal_type=metadata.legal_type.strip(),
                        issuing_authority=metadata.issuing_authority.strip() or None,
                        issuance_date=metadata.issuance_date,
                        article=chunk.article,
                        clause=chunk.clause,
                        heading_path=chunk.heading_path,
                        citation=chunk.citation,
                        token_count=chunk.token_count,
                        dataset_revision=revision,
                        content_sha256=document.content_sha256,
                        chunk_sha256=chunk_sha256,
                    )
                )
    return records


def build_vertex_point(
    record: StructuralRecord,
    *,
    dense_vector: Sequence[float],
    sparse_vector: object,
    contract: VertexQdrantContract,
) -> models.PointStruct:
    if len(dense_vector) != contract.vector_size:
        raise ValueError("dense vector dimension does not match migration contract")
    indices = list(getattr(sparse_vector, "indices"))
    values = list(getattr(sparse_vector, "values"))
    if len(indices) != len(values) or not indices:
        raise ValueError("sparse vector must contain aligned nonzero values")
    payload = point_payload(record)
    payload.update(
        {
            "embedding_provider": "google_vertex_ai",
            "embedding_model": contract.embedding_model,
            "embedding_dimension": contract.vector_size,
            "migration_schema": "vietlex-vertex-qdrant-v1",
        }
    )
    return models.PointStruct(
        id=record.record_id,
        vector={
            contract.dense_vector_name: [float(value) for value in dense_vector],
            contract.sparse_vector_name: models.SparseVector(
                indices=indices,
                values=[float(value) for value in values],
            ),
        },
        payload=payload,
    )


async def ensure_migration_collection(
    client: object,
    contract: VertexQdrantContract,
    *,
    allow_create: bool,
) -> bool:
    """Validate the target schema, creating it only with explicit authority."""
    exists = await client.collection_exists(contract.collection_name)
    if exists:
        info = await client.get_collection(contract.collection_name)
        vectors = info.config.params.vectors
        dense = vectors.get(contract.dense_vector_name) if isinstance(vectors, dict) else None
        sparse = info.config.params.sparse_vectors or {}
        if dense is None or int(dense.size) != contract.vector_size:
            raise ValueError("existing Qdrant dense vector schema does not match")
        if contract.sparse_vector_name not in sparse:
            raise ValueError("existing Qdrant sparse vector schema does not match")
        return False
    if not allow_create:
        raise PermissionError("allow_create is required to create the migration collection")
    await client.create_collection(
        collection_name=contract.collection_name,
        vectors_config={
            contract.dense_vector_name: models.VectorParams(
                size=contract.vector_size,
                distance=contract.distance,
                on_disk=True,
            )
        },
        sparse_vectors_config={
            contract.sparse_vector_name: models.SparseVectorParams(
                index=models.SparseIndexParams(on_disk=True),
                modifier=models.Modifier.IDF,
            )
        },
        on_disk_payload=True,
    )
    return True


class MigrationCheckpoint:
    """Tiny acknowledgement ledger; records are marked only after Qdrant ACK."""

    def __init__(self, path: Path, contract: VertexQdrantContract) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        binding = "|".join(
            (
                "vietlex-vertex-qdrant-v1",
                contract.collection_name,
                contract.embedding_model,
                str(contract.vector_size),
                contract.dense_vector_name,
                contract.sparse_vector_name,
            )
        )
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS uploaded_records ("
                "record_id TEXT PRIMARY KEY, uploaded_at TEXT NOT NULL "
                "DEFAULT CURRENT_TIMESTAMP)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS checkpoint_metadata ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            row = connection.execute(
                "SELECT value FROM checkpoint_metadata WHERE key = 'contract_binding'"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO checkpoint_metadata(key, value) VALUES (?, ?)",
                    ("contract_binding", binding),
                )
            elif row[0] != binding:
                raise ValueError("checkpoint belongs to a different migration contract")

    def contains(self, record_id: str) -> bool:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT 1 FROM uploaded_records WHERE record_id = ?",
                (record_id,),
            ).fetchone()
        return row is not None

    def missing_record_ids(self, record_ids: Sequence[str]) -> set[str]:
        requested = set(record_ids)
        if not requested:
            return set()
        found: set[str] = set()
        values = list(requested)
        with sqlite3.connect(self.path) as connection:
            for offset in range(0, len(values), 900):
                batch = values[offset : offset + 900]
                placeholders = ",".join("?" for _ in batch)
                rows = connection.execute(
                    "SELECT record_id FROM uploaded_records "
                    f"WHERE record_id IN ({placeholders})",
                    batch,
                ).fetchall()
                found.update(str(row[0]) for row in rows)
        return requested - found

    def acknowledge(self, record_ids: Sequence[str]) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO uploaded_records(record_id) VALUES (?)",
                ((record_id,) for record_id in record_ids),
            )


async def upload_vertex_records(
    records: Sequence[StructuralRecord],
    *,
    provider: object,
    client: object,
    sparse_encoder: object,
    checkpoint: MigrationCheckpoint,
    contract: VertexQdrantContract,
    batch_size: int,
    concurrency: int,
    allow_remote_write: bool,
    progress_callback: Callable[[dict[str, int]], None] | None = None,
) -> dict[str, int]:
    if not allow_remote_write:
        raise PermissionError("allow_remote_write is required for Qdrant upload")
    if batch_size <= 0 or concurrency <= 0:
        raise ValueError("batch size and concurrency must be positive")
    missing = checkpoint.missing_record_ids([record.record_id for record in records])
    pending = [record for record in records if record.record_id in missing]
    skipped = len(records) - len(pending)
    uploaded = 0
    semaphore = asyncio.Semaphore(concurrency)

    async def build_point(record: StructuralRecord) -> models.PointStruct:
        inference_text = build_structural_inference_text(record)
        async with semaphore:
            embedding = await provider.embed_document(
                inference_text,
                title=record.title,
                output_dimensionality=contract.vector_size,
            )
        sparse = sparse_encoder.encode_document(inference_text)
        return build_vertex_point(
            record,
            dense_vector=embedding.values,
            sparse_vector=sparse,
            contract=contract,
        )

    for offset in range(0, len(pending), batch_size):
        batch = pending[offset : offset + batch_size]
        points = await asyncio.gather(*(build_point(record) for record in batch))
        await client.upsert(
            collection_name=contract.collection_name,
            points=points,
            wait=True,
        )
        checkpoint.acknowledge([record.record_id for record in batch])
        uploaded += len(batch)
        if progress_callback is not None:
            progress_callback(
                {
                    "attempted": len(records),
                    "pending": len(pending),
                    "uploaded": uploaded,
                    "skipped": skipped,
                }
            )
    return {
        "attempted": len(records),
        "uploaded": uploaded,
        "skipped": skipped,
    }


async def query_vertex_records(
    query: str,
    *,
    provider: object,
    client: object,
    sparse_encoder: object,
    contract: VertexQdrantContract,
    limit: int,
) -> list[object]:
    from app.services.vertex_qdrant_retrieval import query_vertex_points

    return await query_vertex_points(
        query,
        sparse_query=query,
        provider=provider,
        client=client,
        sparse_encoder=sparse_encoder,
        contract=contract,
        limit=limit,
    )
