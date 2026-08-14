from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ingestion.structural_index import StructuralRecord
from app.ingestion.structural_pinecone import (
    PineconeCheckpointBinding,
    PineconeStructuralCheckpoint,
    PineconeStructuralContract,
    PineconeStructuralError,
    pinecone_structural_record,
    upload_pinecone_structural_records,
    verify_pinecone_structural_namespace,
    validate_pinecone_structural_index,
)


def _record(record_id: str = "record-1") -> StructuralRecord:
    body = "Khoản 1 quy định nội dung thử nghiệm."
    import hashlib

    return StructuralRecord(
        record_id=record_id,
        body=body,
        document_id=42,
        document_number="01/2024/QH15",
        title="Luật thử nghiệm",
        source_url="https://example.test/42",
        legal_type="Luật",
        issuing_authority="Quốc hội",
        issuance_date="2024-01-01",
        article="Điều 1",
        clause="Khoản 1",
        heading_path="Điều 1 > Khoản 1",
        citation="Điều 1 khoản 1 Luật thử nghiệm",
        token_count=7,
        dataset_revision="revision-1",
        content_sha256="a" * 64,
        chunk_sha256=hashlib.sha256(body.encode()).hexdigest(),
    )


def _description(*, ready: bool = True, dimension: int = 1024):
    return SimpleNamespace(
        name="llama-text-embed-v2-index",
        metric="cosine",
        dimension=dimension,
        status=SimpleNamespace(ready=ready, state="Ready" if ready else "Scaling"),
        embed=SimpleNamespace(
            model="llama-text-embed-v2",
            dimension=1024,
            metric="cosine",
            field_map={"text": "text"},
            read_parameters={
                "dimension": 1024,
                "input_type": "query",
                "truncate": "END",
            },
            write_parameters={
                "dimension": 1024,
                "input_type": "passage",
                "truncate": "END",
            },
        ),
    )


def _binding() -> PineconeCheckpointBinding:
    return PineconeCheckpointBinding(
        manifest_sha256="a" * 64,
        dataset_revision="revision-1",
        ordered_record_ids_sha256="b" * 64,
        manifest_record_count=2,
    )


def test_contract_is_exact_and_index_description_must_match() -> None:
    contract = PineconeStructuralContract()

    validate_pinecone_structural_index(_description(), contract)

    with pytest.raises(PineconeStructuralError, match="dimension"):
        validate_pinecone_structural_index(
            _description(dimension=384),
            contract,
        )
    with pytest.raises(PineconeStructuralError, match="not ready"):
        validate_pinecone_structural_index(
            _description(ready=False),
            contract,
        )


def test_record_mapping_preserves_identity_and_exact_inference_text() -> None:
    record = _record()

    payload = pinecone_structural_record(record)

    assert payload["_id"] == record.record_id
    assert payload["text"].endswith(f"Nội dung:\n{record.body}")
    assert payload["document_id"] == 42
    assert payload["chunk_sha256"] == record.chunk_sha256
    assert len(payload["inference_text_sha256"]) == 64
    assert "embedding" not in payload

    nullable = pinecone_structural_record(
        record.model_copy(update={"issuing_authority": None, "clause": None})
    )
    assert "issuing_authority" not in nullable
    assert "clause" not in nullable


def test_checkpoint_resume_is_idempotent_and_hash_strict(tmp_path: Path) -> None:
    checkpoint = PineconeStructuralCheckpoint(
        tmp_path / "resume.sqlite3",
        _binding(),
    )
    first = _record("record-1")
    second = _record("record-2")

    checkpoint.commit([first])

    assert checkpoint.committed_count() == 1
    assert [row.record_id for row in checkpoint.pending([first, second])] == [
        "record-2"
    ]
    assert checkpoint.commit([first]) == 0

    changed = first.model_copy(update={"chunk_sha256": "c" * 64})
    with pytest.raises(PineconeStructuralError, match="hash mismatch"):
        checkpoint.pending([changed])


def test_checkpoint_rejects_changed_binding(tmp_path: Path) -> None:
    path = tmp_path / "resume.sqlite3"
    PineconeStructuralCheckpoint(path, _binding())

    with pytest.raises(PineconeStructuralError, match="binding mismatch"):
        PineconeStructuralCheckpoint(
            path,
            _binding().model_copy(update={"manifest_sha256": "c" * 64}),
        )


def test_upload_is_bounded_resumable_and_counts_only_successes(
    tmp_path: Path,
) -> None:
    class Index:
        def __init__(self) -> None:
            self.calls: list[list[dict[str, object]]] = []

        def upsert_records(self, *, namespace, records, timeout):
            assert namespace == "national-primary-v2"
            assert timeout == 120.0
            self.calls.append(records)
            return SimpleNamespace(record_count=len(records))

    contract = PineconeStructuralContract(max_workers=2)
    checkpoint = PineconeStructuralCheckpoint(
        tmp_path / "resume.sqlite3",
        _binding().model_copy(update={"manifest_record_count": 193}),
    )
    records = [_record(f"record-{index:03d}") for index in range(193)]
    index = Index()

    report = upload_pinecone_structural_records(
        index,
        records,
        checkpoint=checkpoint,
        contract=contract,
        sleep=lambda _delay: None,
    )

    assert sorted(len(batch) for batch in index.calls) == [1, 96, 96]
    assert report.submitted_records == 193
    assert report.committed_records == 193
    assert report.provider_calls == 3
    assert checkpoint.committed_count() == 193

    resumed = upload_pinecone_structural_records(
        index,
        records,
        checkpoint=checkpoint,
        contract=contract,
        sleep=lambda _delay: None,
    )
    assert resumed.submitted_records == 0
    assert resumed.provider_calls == 0
    assert len(index.calls) == 3


def test_upload_retries_transient_failure_before_checkpoint(tmp_path: Path) -> None:
    class RateLimited(RuntimeError):
        status_code = 429

    class Index:
        calls = 0

        def upsert_records(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RateLimited("secret provider body")
            return SimpleNamespace(record_count=len(kwargs["records"]))

    checkpoint = PineconeStructuralCheckpoint(
        tmp_path / "resume.sqlite3",
        _binding().model_copy(update={"manifest_record_count": 1}),
    )
    index = Index()

    report = upload_pinecone_structural_records(
        index,
        [_record()],
        checkpoint=checkpoint,
        contract=PineconeStructuralContract(max_workers=1),
        sleep=lambda _delay: None,
    )

    assert index.calls == 2
    assert report.provider_calls == 2
    assert report.retry_count == 1
    assert checkpoint.committed_count() == 1


def test_upload_rejects_malformed_response_without_checkpoint(
    tmp_path: Path,
) -> None:
    class Index:
        def upsert_records(self, **_kwargs):
            return SimpleNamespace(record_count=0)

    checkpoint = PineconeStructuralCheckpoint(
        tmp_path / "resume.sqlite3",
        _binding().model_copy(update={"manifest_record_count": 1}),
    )

    with pytest.raises(PineconeStructuralError, match="record count mismatch"):
        upload_pinecone_structural_records(
            Index(),
            [_record()],
            checkpoint=checkpoint,
            contract=PineconeStructuralContract(max_workers=1),
            sleep=lambda _delay: None,
        )
    assert checkpoint.committed_count() == 0


def test_verify_requires_exact_count_and_sample_hashes() -> None:
    record = _record()

    class Index:
        def describe_index_stats(self):
            return SimpleNamespace(
                namespaces={
                    "national-primary-v2": SimpleNamespace(vector_count=2)
                }
            )

        def search(self, **kwargs):
            assert kwargs["id"] == record.record_id
            fields = pinecone_structural_record(record)
            fields.pop("_id")
            return SimpleNamespace(
                result=SimpleNamespace(
                    hits=[
                        SimpleNamespace(
                            _id=record.record_id,
                            fields=fields,
                        )
                    ]
                ),
                usage=SimpleNamespace(read_units=1),
            )

    report = verify_pinecone_structural_namespace(
        Index(),
        [record],
        expected_count=2,
        contract=PineconeStructuralContract(),
    )

    assert report.status == "PASS_VERIFY"
    assert report.remote_record_count == 2
    assert report.sample_count == 1
    assert report.provider_calls == 2
