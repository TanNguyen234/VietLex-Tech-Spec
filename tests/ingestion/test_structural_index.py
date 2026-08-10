from __future__ import annotations

import hashlib
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

import app.ingestion.structural_index as structural_index
from app.ingestion.content_store import StoredDocument
from app.ingestion.legal_text import DocumentMetadata
from app.ingestion.structural_index import (
    PRIMARY_LEGAL_TYPES,
    StructuralIndexError,
    build_structural_manifest,
    build_structural_records,
    select_structural_document_ids,
)


def _document(
    document_id: int,
    *,
    legal_type: str = "Luật",
    content: str | None = None,
    issuing_authority: str = "Quốc hội",
) -> StoredDocument:
    text = content or (
        "Điều 1. Phạm vi điều chỉnh\n"
        "1. Văn bản này quy định về hoạt động thử nghiệm.\n"
        "Điều 2. Đối tượng áp dụng\n"
        "1. Cơ quan, tổ chức và cá nhân có liên quan."
    )
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return StoredDocument(
        metadata=DocumentMetadata(
            document_id=document_id,
            document_number=f"{document_id}/2026/QH15",
            title=f"Luật thử nghiệm {document_id}",
            source_url=f"https://example.invalid/{document_id}",
            legal_type=legal_type,
            legal_sectors="Lĩnh vực khác",
            issuing_authority=issuing_authority,
            issuance_date="01/01/2026",
        ),
        content=text,
        content_sha256=digest,
        content_store_key=str(document_id),
        quality_flags=(),
    )


class FakeStore:
    def __init__(self, documents: dict[int, StoredDocument]) -> None:
        self.documents = documents
        self.requested_types: list[tuple[str, ...]] = []

    def iter_document_ids_by_legal_types(
        self,
        legal_types,
        *,
        after_id: int,
        limit: int,
    ) -> list[int]:
        requested = tuple(legal_types)
        self.requested_types.append(requested)
        return [
            document_id
            for document_id, document in sorted(self.documents.items())
            if document_id > after_id
            and document.metadata.legal_type in requested
        ][:limit]

    def get_many(self, document_ids: list[int]) -> dict[int, StoredDocument]:
        return {
            document_id: self.documents[document_id]
            for document_id in document_ids
            if document_id in self.documents
        }


def test_primary_scope_is_type_based_sorted_and_gold_agnostic() -> None:
    store = FakeStore(
        {
            3: _document(3, legal_type="Luật"),
            1: _document(1, legal_type="Công văn"),
            2: _document(2, legal_type="Hiến pháp"),
            4: _document(4, legal_type="Pháp lệnh"),
        }
    )

    assert select_structural_document_ids(store, page_size=2) == [2, 3, 4]
    assert store.requested_types
    assert set(store.requested_types) == {PRIMARY_LEGAL_TYPES}


def test_structural_records_are_stable_hashed_and_body_bounded() -> None:
    store = FakeStore({10: _document(10)})

    first = build_structural_records(
        store,
        [10],
        repository="owner/legal-corpus",
        revision="revision-1",
        max_tokens=24,
        overlap_tokens=4,
    )
    second = build_structural_records(
        store,
        [10],
        repository="owner/legal-corpus",
        revision="revision-1",
        max_tokens=24,
        overlap_tokens=4,
    )

    assert first
    assert [row.record_id for row in first] == [row.record_id for row in second]
    assert len({row.record_id for row in first}) == len(first)
    assert all(row.document_id == 10 for row in first)
    assert all(row.dataset_revision == "revision-1" for row in first)
    assert all(row.token_count <= 24 for row in first)
    assert all(
        row.chunk_sha256 == hashlib.sha256(row.body.encode("utf-8")).hexdigest()
        for row in first
    )
    assert all(row.embedding is None for row in first)


def test_structural_records_preserve_missing_issuing_authority_as_null() -> None:
    store = FakeStore({72_273: _document(72_273, issuing_authority="")})

    rows = build_structural_records(
        store,
        [72_273],
        repository="owner/legal-corpus",
        revision="revision-1",
    )

    assert rows
    assert {row.issuing_authority for row in rows} == {None}


def test_structural_record_rejects_blank_normalized_issuing_authority() -> None:
    row = build_structural_records(
        FakeStore({1: _document(1)}),
        [1],
        repository="owner/legal-corpus",
        revision="revision-1",
    )[0]

    with pytest.raises(ValidationError, match="issuing_authority"):
        type(row).model_validate(
            {**row.model_dump(), "issuing_authority": ""}
        )


def test_structural_record_stream_reads_bounded_document_batches(
    monkeypatch,
) -> None:
    documents = {document_id: _document(document_id) for document_id in range(1, 258)}
    store = FakeStore(documents)
    requested: list[list[int]] = []
    original_get_many = store.get_many

    def recording_get_many(document_ids: list[int]) -> dict[int, StoredDocument]:
        requested.append(list(document_ids))
        return original_get_many(document_ids)

    store.get_many = recording_get_many

    rows = list(
        structural_index.iter_structural_records(
            store,
            sorted(documents),
            repository="owner/legal-corpus",
            revision="revision-1",
        )
    )

    assert rows
    assert [len(batch) for batch in requested] == [128, 128, 1]


def test_manifest_binds_scope_records_and_document_level_counts() -> None:
    documents = {
        2: _document(2, legal_type="Hiến pháp"),
        3: _document(3, legal_type="Luật"),
    }
    store = FakeStore(documents)
    records = build_structural_records(
        store,
        [2, 3],
        repository="owner/legal-corpus",
        revision="revision-1",
    )

    manifest = build_structural_manifest(
        records,
        selected_document_ids=[2, 3],
        repository="owner/legal-corpus",
        revision="revision-1",
        max_tokens=420,
        overlap_tokens=48,
    )

    assert manifest.schema_version == "2.0.0"
    assert manifest.document_count == 2
    assert manifest.record_count == len(records)
    assert manifest.per_legal_type_counts == {"Hiến pháp": 1, "Luật": 1}
    assert manifest.body_bytes == sum(
        len(record.body.encode("utf-8")) for record in records
    )
    assert manifest.approximate_token_count == sum(
        record.token_count for record in records
    )
    assert manifest.provider_calls == 0
    assert len(manifest.selected_document_ids_sha256) == 64
    assert len(manifest.ordered_record_ids_sha256) == 64
    assert "Văn bản này quy định" not in manifest.model_dump_json()


def test_streaming_manifest_matches_sequence_wrapper() -> None:
    store = FakeStore({1: _document(1), 2: _document(2)})
    rows = build_structural_records(
        store,
        [1, 2],
        repository="owner/legal-corpus",
        revision="revision-1",
    )
    builder = structural_index.StructuralManifestBuilder(
        selected_document_ids=[1, 2],
        repository="owner/legal-corpus",
        revision="revision-1",
        max_tokens=420,
        overlap_tokens=48,
    )

    for row in rows:
        builder.add(row)

    streamed = builder.build()
    wrapped = build_structural_manifest(
        rows,
        selected_document_ids=[1, 2],
        repository="owner/legal-corpus",
        revision="revision-1",
        max_tokens=420,
        overlap_tokens=48,
    )
    assert streamed == wrapped
    assert streamed.body_bytes == sum(len(row.body.encode("utf-8")) for row in rows)
    assert streamed.approximate_token_count == sum(row.token_count for row in rows)


@pytest.mark.parametrize(
    ("ids", "message"),
    [
        ([10, 10], "unique"),
        ([10, 9], "sorted"),
        ([0], "positive"),
        ([True], "positive integer"),
    ],
)
def test_build_records_rejects_invalid_document_id_sets(ids, message) -> None:
    with pytest.raises(StructuralIndexError, match=message):
        build_structural_records(
            FakeStore({10: _document(10)}),
            ids,
            repository="owner/legal-corpus",
            revision="revision-1",
        )


def test_build_records_rejects_missing_or_out_of_scope_documents() -> None:
    with pytest.raises(StructuralIndexError, match="missing document 11"):
        build_structural_records(
            FakeStore({}),
            [11],
            repository="owner/legal-corpus",
            revision="revision-1",
        )

    with pytest.raises(StructuralIndexError, match="outside structural scope"):
        build_structural_records(
            FakeStore({11: _document(11, legal_type="Công văn")}),
            [11],
            repository="owner/legal-corpus",
            revision="revision-1",
        )


def test_build_records_rejects_content_hash_mismatch() -> None:
    document = _document(10)
    damaged = StoredDocument(
        **{**document.__dict__, "content_sha256": "0" * 64}
    )

    with pytest.raises(StructuralIndexError, match="content SHA-256"):
        build_structural_records(
            FakeStore({10: damaged}),
            [10],
            repository="owner/legal-corpus",
            revision="revision-1",
        )


def test_selector_rejects_invalid_corpus_page() -> None:
    class BrokenStore:
        def iter_document_ids_by_legal_types(self, *args, **kwargs):
            return [2, 1]

    with pytest.raises(StructuralIndexError, match="corpus page"):
        select_structural_document_ids(BrokenStore())


def test_manifest_rejects_missing_selected_document() -> None:
    store = FakeStore({10: _document(10)})
    records = build_structural_records(
        store,
        [10],
        repository="owner/legal-corpus",
        revision="revision-1",
    )

    with pytest.raises(StructuralIndexError, match="selected document set"):
        build_structural_manifest(
            records,
            selected_document_ids=[10, 11],
            repository="owner/legal-corpus",
            revision="revision-1",
        )


@pytest.mark.parametrize(
    ("max_tokens", "overlap_tokens"),
    [
        (0, 0),
        (True, 0),
        (20, -1),
        (20, 20),
        (20, True),
    ],
)
def test_build_records_rejects_invalid_chunk_contract(
    max_tokens,
    overlap_tokens,
) -> None:
    with pytest.raises(StructuralIndexError, match="tokens"):
        build_structural_records(
            FakeStore({10: _document(10)}),
            [10],
            repository="owner/legal-corpus",
            revision="revision-1",
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )


def test_build_records_rejects_blank_structural_chunk(monkeypatch) -> None:
    monkeypatch.setattr(
        structural_index,
        "chunk_document",
        lambda *args, **kwargs: [
            SimpleNamespace(
                text=" ",
                token_count=1,
                article="Điều 1",
                clause="1",
                heading_path="Điều 1",
                citation="10/2026/QH15, Điều 1, Khoản 1",
            )
        ],
    )

    with pytest.raises(StructuralIndexError, match="must not be blank"):
        build_structural_records(
            FakeStore({10: _document(10)}),
            [10],
            repository="owner/legal-corpus",
            revision="revision-1",
        )


def test_build_records_rejects_record_id_collision(monkeypatch) -> None:
    monkeypatch.setattr(
        structural_index,
        "uuid5",
        lambda *args, **kwargs: UUID(int=0),
    )
    chunks = [
        SimpleNamespace(
            text=f"Nội dung {index}",
            token_count=2,
            article=f"Điều {index}",
            clause=None,
            heading_path=f"Điều {index}",
            citation=f"10/2026/QH15, Điều {index}",
        )
        for index in (1, 2)
    ]
    monkeypatch.setattr(
        structural_index,
        "chunk_document",
        lambda *args, **kwargs: chunks,
    )

    with pytest.raises(StructuralIndexError, match="record ID collision"):
        build_structural_records(
            FakeStore({10: _document(10)}),
            [10],
            repository="owner/legal-corpus",
            revision="revision-1",
        )
