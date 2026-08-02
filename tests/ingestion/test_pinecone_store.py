from types import SimpleNamespace

import pytest

from app.config import Settings
from app.ingestion.content_store import StoredDocument
from app.ingestion.legal_text import DocumentMetadata
from app.ingestion.pinecone_store import (
    FastSparseEncoder,
    SparseValues,
    build_record,
    scale_hybrid_query,
    upload_record_batch,
)


def _stored_document() -> StoredDocument:
    return StoredDocument(
        metadata=DocumentMetadata(
            document_id=42,
            document_number="12/2026/NĐ-CP",
            title="Nghị định thử nghiệm",
            source_url="https://example.invalid/42",
            legal_type="Nghị định",
            legal_sectors="Hành chính",
            issuing_authority="Chính phủ",
            issuance_date="2026-01-02",
        ),
        content="Điều 1. Nội dung đầy đủ không được đưa vào Pinecone.",
        content_sha256="a" * 64,
        content_store_key="42",
        quality_flags=(),
    )


def test_record_is_capacity_bounded_and_resolves_local_content() -> None:
    settings = Settings(_env_file=None)
    record = build_record(
        document=_stored_document(),
        dense_vector=[0.0] * settings.DENSE_VECTOR_SIZE,
        sparse_vector=SparseValues(indices=[1, 2], values=[1.0, 0.5]),
        settings=settings,
    )

    assert len(record["values"]) == 384
    assert isinstance(record["id"], str)
    assert len(record["sparse_values"]["indices"]) == 2
    assert record["metadata"]["content_store_key"] == "42"
    assert "content" not in record["metadata"]
    assert "title" not in record["metadata"]


def test_fast_sparse_encoder_caps_storage_and_is_deterministic() -> None:
    encoder = FastSparseEncoder(
        average_document_length=100.0,
        max_nonzero_terms=4,
    )
    first = encoder.encode_document(
        "Điều 12 nghị định thuế thu nhập cá nhân doanh nghiệp"
    )
    second = encoder.encode_document(
        "Điều 12 nghị định thuế thu nhập cá nhân doanh nghiệp"
    )

    assert first == second
    assert len(first.indices) == 4
    assert first.indices == sorted(first.indices)


def test_hybrid_query_weights_dense_and_sparse_once() -> None:
    dense, sparse = scale_hybrid_query(
        [1.0, 0.5],
        SparseValues(indices=[7], values=[2.0]),
        alpha=0.75,
    )

    assert dense == [0.75, 0.375]
    assert sparse == {"indices": [7], "values": [0.5]}

    with pytest.raises(ValueError, match="alpha"):
        scale_hybrid_query([], SparseValues([], []), alpha=1.1)


def test_upload_uses_one_namespace_and_one_batch_call() -> None:
    calls: list[dict] = []
    index = SimpleNamespace(upsert=lambda **kwargs: calls.append(kwargs))
    settings = Settings(_env_file=None)

    upload_record_batch(index, settings, [{"id": "1", "values": [0.0]}])

    assert calls == [
        {
            "vectors": [{"id": "1", "values": [0.0]}],
            "namespace": settings.PINECONE_NAMESPACE,
            "max_concurrency": 1,
            "show_progress": False,
        }
    ]
