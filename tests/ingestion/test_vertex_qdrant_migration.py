from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from app.ingestion.legal_text import EvidenceChunk


def _chunk(index: int) -> EvidenceChunk:
    return EvidenceChunk(
        document_id=10,
        document_number="10/2026/QH15",
        title="Luật thử nghiệm",
        source_url="https://example.test/10",
        heading_path=f"Điều {index}",
        article=f"Điều {index}",
        clause=None,
        citation=f"10/2026/QH15, Điều {index}",
        text=f"Điều {index}. Nội dung pháp luật {index}.",
        token_count=6,
    )


def test_contract_rejects_active_or_low_dimension_targets() -> None:
    from app.ingestion.vertex_qdrant_migration import VertexQdrantContract

    with pytest.raises(ValueError, match="protected"):
        VertexQdrantContract(collection_name="vietlex-legal-rag-v2-pilot-384")
    with pytest.raises(ValueError, match="at least 768"):
        VertexQdrantContract(vector_size=384)


def test_long_documents_keep_even_structural_coverage() -> None:
    from app.ingestion.vertex_qdrant_migration import select_evenly_spaced_chunks

    selected = select_evenly_spaced_chunks(
        [_chunk(index) for index in range(1, 11)],
        limit=4,
    )

    assert [chunk.article for chunk in selected] == [
        "Điều 1",
        "Điều 4",
        "Điều 7",
        "Điều 10",
    ]


def test_document_selection_round_robins_legal_types() -> None:
    from app.ingestion.vertex_qdrant_migration import select_diverse_document_ids

    class Store:
        def iter_document_ids_by_legal_types(self, legal_types, *, after_id, limit):
            assert after_id == -1
            values = {"Luật": [1, 4, 7], "Nghị định": [2, 5], "Thông tư": [3, 6]}
            return values[legal_types[0]][:limit]

    selected = select_diverse_document_ids(
        Store(),
        legal_types=("Luật", "Nghị định", "Thông tư"),
        limit=7,
    )

    assert selected == [1, 2, 3, 4, 5, 6, 7]


def test_document_selection_fills_limit_when_one_legal_type_is_sparse() -> None:
    from app.ingestion.vertex_qdrant_migration import select_diverse_document_ids

    class Store:
        def iter_document_ids_by_legal_types(self, legal_types, *, after_id, limit):
            values = {"Luật": [1], "Nghị định": [2, 3, 4, 5]}
            return values[legal_types[0]][:limit]

    selected = select_diverse_document_ids(
        Store(),
        legal_types=("Luật", "Nghị định"),
        limit=5,
    )

    assert selected == [1, 2, 3, 4, 5]


def test_build_records_applies_per_document_structural_budget() -> None:
    from app.ingestion.content_store import StoredDocument
    from app.ingestion.legal_text import DocumentMetadata
    from app.ingestion.vertex_qdrant_migration import build_vertex_records

    content = "\n".join(
        f"Điều {index}. Nội dung điều {index}." for index in range(1, 11)
    )
    document = StoredDocument(
        metadata=DocumentMetadata(
            document_id=10,
            document_number="10/2026/QH15",
            title="Luật thử nghiệm",
            source_url="https://example.test/10",
            legal_type="Luật",
            legal_sectors="Thử nghiệm",
            issuing_authority="Quốc hội",
            issuance_date="2026-01-01",
        ),
        content=content,
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        content_store_key="10",
        quality_flags=(),
    )

    class Store:
        def get_many(self, document_ids):
            assert document_ids == [10]
            return {10: document}

    records = build_vertex_records(
        Store(),
        [10],
        repository="repo",
        revision="revision",
        max_tokens=64,
        overlap_tokens=8,
        max_chunks_per_document=4,
    )

    assert [record.article for record in records] == [
        "Điều 1",
        "Điều 4",
        "Điều 7",
        "Điều 10",
    ]


def test_build_records_reads_content_store_in_bounded_batches() -> None:
    from app.ingestion.vertex_qdrant_migration import build_vertex_records

    class Store:
        def __init__(self) -> None:
            self.calls = []

        def get_many(self, document_ids):
            self.calls.append(list(document_ids))
            return {}

    store = Store()
    records = build_vertex_records(
        store,
        list(range(1, 131)),
        repository="repo",
        revision="revision",
        max_tokens=64,
        overlap_tokens=8,
        max_chunks_per_document=4,
    )

    assert records == []
    assert [len(call) for call in store.calls] == [64, 64, 2]


def test_vertex_point_binds_dense_sparse_and_provenance() -> None:
    from app.ingestion.structural_index import StructuralRecord
    from app.ingestion.vertex_qdrant_migration import (
        VertexQdrantContract,
        build_vertex_point,
    )

    contract = VertexQdrantContract()
    record = StructuralRecord(
        record_id="12345678-1234-5678-1234-567812345678",
        body="Điều 25. Thời gian thử việc không quá 60 ngày.",
        document_id=333670,
        document_number="45/2019/QH14",
        title="Bộ luật Lao động 2019",
        source_url="https://example.test/333670",
        legal_type="Luật",
        issuing_authority="Quốc hội",
        issuance_date="2019-11-20",
        article="Điều 25",
        clause="2",
        heading_path="Chương III > Điều 25",
        citation="45/2019/QH14, Điều 25, Khoản 2",
        token_count=10,
        dataset_revision="revision",
        content_sha256="a" * 64,
        chunk_sha256="b" * 64,
    )
    sparse = SimpleNamespace(indices=[1, 9], values=[0.5, 1.25])

    point = build_vertex_point(
        record,
        dense_vector=[0.0] * contract.vector_size,
        sparse_vector=sparse,
        contract=contract,
    )

    assert len(point.vector[contract.dense_vector_name]) == 1024
    assert point.vector[contract.sparse_vector_name].indices == [1, 9]
    assert point.payload["embedding_model"] == "gemini-embedding-2"
    assert point.payload["citation"] == "45/2019/QH14, Điều 25, Khoản 2"


@pytest.mark.asyncio
async def test_collection_creation_requires_explicit_flag() -> None:
    from app.ingestion.vertex_qdrant_migration import (
        VertexQdrantContract,
        ensure_migration_collection,
    )

    class Client:
        def __init__(self) -> None:
            self.create_calls = []

        async def collection_exists(self, _name):
            return False

        async def create_collection(self, **kwargs):
            self.create_calls.append(kwargs)

    client = Client()
    contract = VertexQdrantContract()

    with pytest.raises(PermissionError, match="allow_create"):
        await ensure_migration_collection(client, contract, allow_create=False)
    await ensure_migration_collection(client, contract, allow_create=True)

    assert client.create_calls[0]["collection_name"] == contract.collection_name
    assert client.create_calls[0]["vectors_config"]["dense"].size == 1024
    assert "sparse" in client.create_calls[0]["sparse_vectors_config"]


@pytest.mark.asyncio
async def test_upload_is_resumable_after_acknowledged_batch(tmp_path) -> None:
    from app.ingestion.structural_index import StructuralRecord
    from app.ingestion.vertex_qdrant_migration import (
        MigrationCheckpoint,
        VertexQdrantContract,
        upload_vertex_records,
    )

    def record(index: int) -> StructuralRecord:
        return StructuralRecord(
            record_id=f"12345678-1234-5678-1234-{index:012d}",
            body=f"Điều {index}. Nội dung.",
            document_id=index,
            document_number=f"{index}/2026/QH15",
            title="Luật thử nghiệm",
            source_url=f"https://example.test/{index}",
            legal_type="Luật",
            issuing_authority="Quốc hội",
            issuance_date="2026-01-01",
            article=f"Điều {index}",
            clause=None,
            heading_path=f"Điều {index}",
            citation=f"{index}/2026/QH15, Điều {index}",
            token_count=4,
            dataset_revision="revision",
            content_sha256="a" * 64,
            chunk_sha256=f"{index:064x}",
        )

    class Provider:
        def __init__(self) -> None:
            self.calls = []

        async def embed_document(self, text, *, title, output_dimensionality):
            self.calls.append((text, title, output_dimensionality))
            return SimpleNamespace(values=(0.0,) * output_dimensionality)

    class Encoder:
        def encode_document(self, _text):
            return SimpleNamespace(indices=[1], values=[1.0])

    class Client:
        def __init__(self) -> None:
            self.upserts = []

        async def upsert(self, **kwargs):
            self.upserts.append(kwargs)

    records = [record(1), record(2)]
    provider = Provider()
    client = Client()
    contract = VertexQdrantContract()
    checkpoint = MigrationCheckpoint(tmp_path / "checkpoint.sqlite3", contract)

    first = await upload_vertex_records(
        records,
        provider=provider,
        client=client,
        sparse_encoder=Encoder(),
        checkpoint=checkpoint,
        contract=contract,
        batch_size=2,
        concurrency=2,
        allow_remote_write=True,
    )
    second = await upload_vertex_records(
        records,
        provider=provider,
        client=client,
        sparse_encoder=Encoder(),
        checkpoint=checkpoint,
        contract=contract,
        batch_size=2,
        concurrency=2,
        allow_remote_write=True,
    )

    assert first == {"attempted": 2, "uploaded": 2, "skipped": 0}
    assert second == {"attempted": 2, "uploaded": 0, "skipped": 2}
    assert len(provider.calls) == 2
    assert len(client.upserts) == 1


@pytest.mark.asyncio
async def test_upload_reports_progress_after_each_batch(tmp_path) -> None:
    from app.ingestion.structural_index import StructuralRecord
    from app.ingestion.vertex_qdrant_migration import (
        MigrationCheckpoint,
        VertexQdrantContract,
        upload_vertex_records,
    )

    def record(index: int) -> StructuralRecord:
        return StructuralRecord(
            record_id=f"12345678-1234-5678-1234-{index:012d}",
            body=f"Dieu {index}. Noi dung.",
            document_id=index,
            document_number=f"{index}/2026/QH15",
            title="Luat thu nghiem",
            source_url=f"https://example.test/{index}",
            legal_type="Luat",
            issuing_authority="Quoc hoi",
            issuance_date="2026-01-01",
            article=f"Dieu {index}",
            clause=None,
            heading_path=f"Dieu {index}",
            citation=f"{index}/2026/QH15, Dieu {index}",
            token_count=4,
            dataset_revision="revision",
            content_sha256="a" * 64,
            chunk_sha256=f"{index:064x}",
        )

    class Provider:
        async def embed_document(self, _text, *, title, output_dimensionality):
            assert title == "Luat thu nghiem"
            return SimpleNamespace(values=(0.0,) * output_dimensionality)

    class Encoder:
        def encode_document(self, _text):
            return SimpleNamespace(indices=[1], values=[1.0])

    class Client:
        async def upsert(self, **_kwargs):
            return None

    progress: list[dict[str, int]] = []
    records = [record(1), record(2), record(3)]
    contract = VertexQdrantContract()

    report = await upload_vertex_records(
        records,
        provider=Provider(),
        client=Client(),
        sparse_encoder=Encoder(),
        checkpoint=MigrationCheckpoint(tmp_path / "checkpoint.sqlite3", contract),
        contract=contract,
        batch_size=2,
        concurrency=2,
        allow_remote_write=True,
        progress_callback=progress.append,
    )

    assert report == {"attempted": 3, "uploaded": 3, "skipped": 0}
    assert progress == [
        {"attempted": 3, "pending": 3, "uploaded": 2, "skipped": 0},
        {"attempted": 3, "pending": 3, "uploaded": 3, "skipped": 0},
    ]


@pytest.mark.asyncio
async def test_migration_rejects_nonpositive_progress_interval() -> None:
    from run_vertex_qdrant_migration import _run

    args = SimpleNamespace(
        max_documents=1,
        max_points=1,
        batch_size=1,
        concurrency=1,
        progress_every=0,
        allow_create=False,
        allow_remote_write=False,
    )

    with pytest.raises(ValueError, match="progress interval"):
        await _run(args)


def test_checkpoint_rejects_changed_remote_contract(tmp_path) -> None:
    from app.ingestion.vertex_qdrant_migration import (
        MigrationCheckpoint,
        VertexQdrantContract,
    )

    path = tmp_path / "checkpoint.sqlite3"
    MigrationCheckpoint(path, VertexQdrantContract())

    with pytest.raises(ValueError, match="different migration contract"):
        MigrationCheckpoint(
            path,
            VertexQdrantContract(collection_name="vietlex-other-vertex-1024"),
        )


def test_checkpoint_filters_missing_record_ids_in_bulk(tmp_path) -> None:
    from app.ingestion.vertex_qdrant_migration import (
        MigrationCheckpoint,
        VertexQdrantContract,
    )

    checkpoint = MigrationCheckpoint(
        tmp_path / "checkpoint.sqlite3",
        VertexQdrantContract(),
    )
    checkpoint.acknowledge(["record-2", "record-4"])

    assert checkpoint.missing_record_ids(
        ["record-1", "record-2", "record-3", "record-4"]
    ) == {"record-1", "record-3"}


@pytest.mark.asyncio
async def test_vertex_query_uses_dense_sparse_rrf() -> None:
    from app.ingestion.vertex_qdrant_migration import (
        VertexQdrantContract,
        query_vertex_records,
    )

    class Provider:
        async def embed_query(self, query, *, output_dimensionality, task):
            assert query == "thời gian thử việc"
            assert output_dimensionality == 1024
            assert task == "question_answering"
            return SimpleNamespace(values=(0.0,) * output_dimensionality)

    class Encoder:
        def encode_query(self, query):
            assert query == "thời gian thử việc"
            return SimpleNamespace(indices=[1, 7], values=[1.0, 0.5])

    class Client:
        async def query_points(self, **kwargs):
            self.call = kwargs
            return SimpleNamespace(points=[SimpleNamespace(id="hit")])

    client = Client()
    result = await query_vertex_records(
        "thời gian thử việc",
        provider=Provider(),
        client=client,
        sparse_encoder=Encoder(),
        contract=VertexQdrantContract(),
        limit=5,
    )

    assert result[0].id == "hit"
    assert len(client.call["prefetch"]) == 2
    assert client.call["prefetch"][0].using == "dense"
    assert client.call["prefetch"][1].using == "sparse"
    assert client.call["query"].fusion.value == "rrf"
