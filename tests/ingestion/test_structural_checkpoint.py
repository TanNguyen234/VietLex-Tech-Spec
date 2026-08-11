from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ingestion.structural_checkpoint import (
    AcknowledgedRecord,
    BatchReceipt,
    CheckpointBinding,
    StructuralCheckpointError,
    StructuralCheckpointStore,
    batch_identity_sha256,
)
from app.ingestion.structural_index import StructuralRecord


def _inference_hash(record: StructuralRecord) -> str:
    structure = record.heading_path or record.citation
    text = (
        f"Tiêu đề: {record.title}\n"
        f"Số văn bản: {record.document_number}\n"
        f"Loại văn bản: {record.legal_type}\n"
        f"Cấu trúc: {structure}\n"
        f"Trích dẫn: {record.citation}\n"
        f"Nội dung:\n{record.body}"
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _record(record_id: str, body: str | None = None) -> StructuralRecord:
    text = body or f"Điều 1. {record_id}"
    return StructuralRecord(
        record_id=record_id,
        body=text,
        document_id=1,
        document_number="1/2026/QH15",
        title="Luật thử nghiệm",
        source_url="https://example.invalid/1",
        legal_type="Luật",
        issuing_authority="Quốc hội",
        issuance_date="01/01/2026",
        article="Điều 1",
        clause=None,
        heading_path="Điều 1",
        citation="1/2026/QH15, Điều 1",
        token_count=3,
        dataset_revision="revision-1",
        content_sha256="a" * 64,
        chunk_sha256=hashlib.sha256(text.encode()).hexdigest(),
    )


def _binding(**updates: object) -> CheckpointBinding:
    values: dict[str, object] = {
        "collection_name": "vietlex-legal-rag-v2-pilot-384",
        "source_state_sha256": "a" * 64,
        "plan_sha256": "b" * 64,
        "creation_receipt_sha256": "c" * 64,
        "probe_report_sha256": "d" * 64,
        "dataset_revision": "revision-1",
        "ordered_record_ids_sha256": "e" * 64,
        "manifest_record_count": 134_334,
        "dense_model": "intfloat/multilingual-e5-small",
        "sparse_model": "qdrant/bm25",
        "document_text_version": "vietlex-structural-document-v2",
    }
    values.update(updates)
    return CheckpointBinding(**values)


def _receipt(records: list[StructuralRecord]) -> BatchReceipt:
    acknowledged = tuple(
        AcknowledgedRecord(
            record_id=record.record_id,
            chunk_sha256=record.chunk_sha256,
            inference_text_sha256=_inference_hash(record),
        )
        for record in records
    )
    return BatchReceipt(
        batch_sha256=batch_identity_sha256(acknowledged),
        records=acknowledged,
        usage={
            "intfloat/multilingual-e5-small": 10,
        },
        attempts=1,
        elapsed_seconds=0.1,
    )


def test_checkpoint_resume_is_record_id_based_not_batch_based(
    tmp_path: Path,
) -> None:
    first = _record("00000000-0000-0000-0000-000000000001")
    second = _record("00000000-0000-0000-0000-000000000002")
    third = _record("00000000-0000-0000-0000-000000000003")
    path = tmp_path / "structural.sqlite3"
    store = StructuralCheckpointStore(path, _binding())
    store.commit_receipt(_receipt([first, second]))

    reopened = StructuralCheckpointStore(path, _binding())

    assert reopened.committed_record_hashes() == {
        first.record_id: first.chunk_sha256,
        second.record_id: second.chunk_sha256,
    }
    assert reopened.pending([second, third]) == [third]


@pytest.mark.parametrize(
    "override",
    [
        {"source_state_sha256": "0" * 64},
        {"plan_sha256": "0" * 64},
        {"dense_model": "wrong-model"},
        {"collection_name": "vietlex-legal-rag-v1"},
    ],
)
def test_checkpoint_rejects_binding_drift(
    tmp_path: Path,
    override: dict[str, object],
) -> None:
    path = tmp_path / "structural.sqlite3"
    StructuralCheckpointStore(path, _binding())
    changed = _binding().model_copy(update=override)

    with pytest.raises(StructuralCheckpointError, match="binding mismatch"):
        StructuralCheckpointStore(path, changed)


def test_checkpoint_rejects_same_id_with_changed_hash(tmp_path: Path) -> None:
    first = _record("00000000-0000-0000-0000-000000000001")
    changed = _record(first.record_id, body="Điều 1. changed")
    store = StructuralCheckpointStore(tmp_path / "state.sqlite3", _binding())
    store.commit_receipt(_receipt([first]))

    with pytest.raises(StructuralCheckpointError, match="hash mismatch"):
        store.pending([changed])


def test_checkpoint_rejects_same_body_with_changed_inference_text(
    tmp_path: Path,
) -> None:
    first = _record("00000000-0000-0000-0000-000000000001")
    changed = first.model_copy(update={"title": "Luật có tiêu đề mới"})
    store = StructuralCheckpointStore(tmp_path / "state.sqlite3", _binding())
    store.commit_receipt(_receipt([first]))

    with pytest.raises(StructuralCheckpointError, match="hash mismatch"):
        store.pending([changed])


def test_invalid_batch_is_atomic_and_not_checkpointed(tmp_path: Path) -> None:
    record = _record("00000000-0000-0000-0000-000000000001")
    receipt = _receipt([record]).model_copy(
        update={"batch_sha256": "0" * 64}
    )
    store = StructuralCheckpointStore(tmp_path / "state.sqlite3", _binding())

    with pytest.raises(StructuralCheckpointError, match="batch SHA-256"):
        store.commit_receipt(receipt)

    assert store.committed_record_hashes() == {}


def test_duplicate_acknowledgement_is_idempotent_not_duplicated(
    tmp_path: Path,
) -> None:
    record = _record("00000000-0000-0000-0000-000000000001")
    receipt = _receipt([record])
    store = StructuralCheckpointStore(tmp_path / "state.sqlite3", _binding())

    assert store.commit_receipt(receipt) == 1
    assert store.commit_receipt(receipt) == 0
    assert store.committed_count() == 1
    assert store.usage_totals() == {
        "intfloat/multilingual-e5-small": 10,
    }


def test_large_probe_sized_batch_does_not_exceed_sqlite_variable_limit(
    tmp_path: Path,
) -> None:
    records = [
        _record(f"00000000-0000-0000-0000-{index:012d}")
        for index in range(1, 1_101)
    ]
    receipt = _receipt(records)
    store = StructuralCheckpointStore(tmp_path / "large.sqlite3", _binding())

    assert store.commit_receipt(receipt) == 1_100
    assert store.commit_receipt(receipt) == 0
    assert store.committed_count() == 1_100


def test_probe_receipt_seeds_only_exact_acknowledged_ids(tmp_path: Path) -> None:
    record = _record("00000000-0000-0000-0000-000000000001")
    binding = _binding()
    store = StructuralCheckpointStore(tmp_path / "state.sqlite3", binding)
    report = SimpleNamespace(
        acceptance="PASS_MODEL_PROBE",
        collection_name=binding.collection_name,
        source_state_sha256=binding.source_state_sha256,
        plan_sha256=binding.plan_sha256,
        creation_receipt_sha256=binding.creation_receipt_sha256,
        dataset_revision=binding.dataset_revision,
        candidate_dense_model=binding.dense_model,
        candidate_sparse_model=binding.sparse_model,
        record_ids=(record.record_id,),
        probe_record_hashes={record.record_id: record.chunk_sha256},
        probe_inference_text_hashes={
            record.record_id: _inference_hash(record)
        },
        provider_usage={
            binding.dense_model: 10,
            "llama-text-embed-v2": 12,
        },
        upsert_provider_usage={
            binding.dense_model: 10,
        },
        upsert_batch_sizes=(1,),
        elapsed_seconds=0.1,
    )

    assert store.import_probe_receipt(
        report,
        report_sha256=binding.probe_report_sha256,
    ) == 1
    assert store.import_probe_receipt(
        report,
        report_sha256=binding.probe_report_sha256,
    ) == 0
    assert store.committed_record_hashes() == {
        record.record_id: record.chunk_sha256
    }


def test_probe_receipt_rejects_artifact_hash_drift(tmp_path: Path) -> None:
    binding = _binding()
    store = StructuralCheckpointStore(tmp_path / "state.sqlite3", binding)

    with pytest.raises(StructuralCheckpointError, match="binding mismatch"):
        store.import_probe_receipt(
            SimpleNamespace(),
            report_sha256="0" * 64,
        )
