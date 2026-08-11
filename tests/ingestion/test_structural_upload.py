from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from qdrant_client import grpc, models

from app.config import Settings
from app.ingestion.structural_checkpoint import (
    CheckpointBinding,
    StructuralCheckpointStore,
)
from app.ingestion.structural_index import StructuralRecord
from app.ingestion.structural_qdrant import (
    InferenceUsageReceipt,
    StructuralProviderError,
    StructuralQdrantContract,
)
from app.ingestion.structural_upload import (
    AdaptiveUploadController,
    GrpcCompatibilityError,
    StructuralGrpcUploadTransport,
    UploadWaveResult,
    retry_transient,
    select_upload_transport,
    upload_structural_records,
)


def _record(index: int) -> StructuralRecord:
    body = f"Điều 1. Nội dung {index}"
    return StructuralRecord(
        record_id=f"00000000-0000-0000-0000-{index:012d}",
        body=body,
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
        token_count=4,
        dataset_revision="revision-1",
        content_sha256="a" * 64,
        chunk_sha256=hashlib.sha256(body.encode()).hexdigest(),
    )


def _contract() -> StructuralQdrantContract:
    return StructuralQdrantContract.from_settings(Settings(_env_file=None))


def _binding() -> CheckpointBinding:
    return CheckpointBinding(
        collection_name="vietlex-legal-rag-v2-pilot",
        source_state_sha256="a" * 64,
        plan_sha256="b" * 64,
        creation_receipt_sha256="c" * 64,
        probe_report_sha256="d" * 64,
        dataset_revision="revision-1",
        ordered_record_ids_sha256="e" * 64,
        manifest_record_count=134_334,
        dense_model="Qwen/Qwen3-Embedding-0.6B",
        sparse_model="qdrant/bm25",
        document_text_version="vietlex-structural-document-v2",
    )


def test_controller_increases_only_after_three_healthy_waves() -> None:
    controller = AdaptiveUploadController(
        batch_size=64,
        workers=1,
        min_batch=64,
        max_batch=256,
        max_workers=4,
        shard_count=2,
    )

    for _ in range(2):
        controller.observe(
            UploadWaveResult(
                success=True,
                transient_errors=0,
                p95_seconds=4.0,
                rate_limited=False,
            )
        )
    assert (controller.batch_size, controller.workers) == (64, 1)

    controller.observe(
        UploadWaveResult(
            success=True,
            transient_errors=0,
            p95_seconds=4.0,
            rate_limited=False,
        )
    )
    assert (controller.batch_size, controller.workers) == (128, 2)


def test_controller_halves_pressure_after_repeated_transient_errors() -> None:
    controller = AdaptiveUploadController(
        batch_size=256,
        workers=4,
        min_batch=64,
        max_batch=256,
        max_workers=4,
        shard_count=4,
    )

    controller.observe(
        UploadWaveResult(
            success=False,
            transient_errors=2,
            p95_seconds=120.0,
            rate_limited=True,
        )
    )

    assert (controller.batch_size, controller.workers) == (128, 2)


def test_retry_delays_are_bounded_and_permanent_error_is_not_retried() -> None:
    attempts = 0
    delays: list[float] = []

    def transient():
        nonlocal attempts
        attempts += 1
        if attempts < 7:
            raise StructuralProviderError(
                stage="upsert",
                category="rate_limit",
                message="typed",
                transient=True,
            )
        return "ok"

    assert retry_transient(
        transient,
        max_attempts=7,
        base_seconds=1,
        max_seconds=30,
        sleep=delays.append,
    ) == ("ok", 7)
    assert delays == [1, 2, 4, 8, 16, 30]

    permanent_attempts = 0

    def permanent():
        nonlocal permanent_attempts
        permanent_attempts += 1
        raise StructuralProviderError(
            stage="upsert",
            category="schema",
            message="typed",
            transient=False,
        )

    with pytest.raises(StructuralProviderError):
        retry_transient(
            permanent,
            max_attempts=7,
            base_seconds=1,
            max_seconds=30,
            sleep=delays.append,
        )
    assert permanent_attempts == 1


class FakeTransport:
    def __init__(self, contract, *, fail: bool = False) -> None:
        self.contract = contract
        self.fail = fail
        self.batch_ids: list[list[str]] = []

    def upsert_with_usage(self, points):
        self.batch_ids.append([str(point.id) for point in points])
        if self.fail:
            raise StructuralProviderError(
                stage="upsert",
                category="permanent",
                message="typed",
                transient=False,
            )
        return InferenceUsageReceipt(
            status="completed",
            elapsed_seconds=0.1,
            model_tokens={
                self.contract.dense_model: len(points) * 10,
                self.contract.sparse_model: len(points) * 11,
            },
        )


def test_upload_streams_batches_checkpoints_only_acknowledged_records(
    tmp_path: Path,
) -> None:
    contract = _contract()
    checkpoint = StructuralCheckpointStore(
        tmp_path / "state.sqlite3", _binding()
    )
    controller = AdaptiveUploadController.from_contract(
        contract,
        shard_count=1,
    )
    transport = FakeTransport(contract)
    records = [_record(index) for index in range(1, 131)]

    report = upload_structural_records(
        transport,
        iter(records),
        checkpoint,
        controller,
        manifest_record_count=134_334,
    )

    assert [len(batch) for batch in transport.batch_ids] == [64, 64, 2]
    assert checkpoint.committed_count() == 130
    assert report.committed_this_run == 130
    assert report.committed_total == 130
    assert report.remaining_count == 134_204
    assert report.provider_usage == {
        contract.dense_model: 1300,
        contract.sparse_model: 1430,
    }
    assert report.records_per_second > 0


def test_failed_batch_is_not_checkpointed(tmp_path: Path) -> None:
    contract = _contract()
    checkpoint = StructuralCheckpointStore(
        tmp_path / "state.sqlite3", _binding()
    )
    transport = FakeTransport(contract, fail=True)

    with pytest.raises(StructuralProviderError):
        upload_structural_records(
            transport,
            iter([_record(1)]),
            checkpoint,
            AdaptiveUploadController.from_contract(contract, shard_count=1),
            manifest_record_count=134_334,
        )

    assert checkpoint.committed_record_hashes() == {}


def test_successful_peer_batch_is_checkpointed_when_wave_peer_fails(
    tmp_path: Path,
) -> None:
    contract = _contract()
    checkpoint = StructuralCheckpointStore(
        tmp_path / "state.sqlite3", _binding()
    )

    class SelectiveTransport(FakeTransport):
        def upsert_with_usage(self, points):
            if str(points[0].id).endswith("000000000001"):
                raise StructuralProviderError(
                    stage="upsert",
                    category="permanent",
                    message="typed",
                    transient=False,
                )
            return super().upsert_with_usage(points)

    with pytest.raises(StructuralProviderError):
        upload_structural_records(
            SelectiveTransport(contract),
            iter([_record(index) for index in range(1, 129)]),
            checkpoint,
            AdaptiveUploadController.from_contract(contract, shard_count=2),
            manifest_record_count=134_334,
        )

    assert checkpoint.committed_count() == 64
    assert _record(65).record_id in checkpoint.committed_record_hashes()
    assert _record(1).record_id not in checkpoint.committed_record_hashes()


def test_resume_skips_matching_ids_without_embedding_again(tmp_path: Path) -> None:
    contract = _contract()
    checkpoint = StructuralCheckpointStore(
        tmp_path / "state.sqlite3", _binding()
    )
    first = FakeTransport(contract)
    controller = AdaptiveUploadController.from_contract(contract, shard_count=1)
    upload_structural_records(
        first,
        iter([_record(1)]),
        checkpoint,
        controller,
        manifest_record_count=134_334,
    )
    resumed = FakeTransport(contract)

    report = upload_structural_records(
        resumed,
        iter([_record(1), _record(2)]),
        checkpoint,
        AdaptiveUploadController.from_contract(contract, shard_count=1),
        manifest_record_count=134_334,
    )

    assert resumed.batch_ids == [[_record(2).record_id]]
    assert report.committed_this_run == 1


def _grpc_response(contract, *, include_sparse: bool = True):
    usage = {
        contract.dense_model: SimpleNamespace(tokens=10),
    }
    if include_sparse:
        usage[contract.sparse_model] = SimpleNamespace(tokens=11)
    return SimpleNamespace(
        result=SimpleNamespace(status=2),
        time=0.1,
        usage=SimpleNamespace(
            inference=SimpleNamespace(models=usage)
        ),
    )


def test_grpc_transport_preserves_exact_inference_usage() -> None:
    contract = _contract()
    response = _grpc_response(contract)
    stub = SimpleNamespace(Upsert=lambda request, timeout: response)
    client = SimpleNamespace(grpc_points=stub)
    transport = StructuralGrpcUploadTransport(client, contract)

    receipt = transport.upsert_with_usage(
        [
            SimpleNamespace(
                id=_record(1).record_id,
                vector={},
                payload={},
            )
        ]
    )

    assert receipt.model_tokens == {
        contract.dense_model: 10,
        contract.sparse_model: 11,
    }


def test_grpc_transport_uses_generated_request_and_protobuf_usage() -> None:
    contract = _contract()
    requests: list[tuple[object, float]] = []
    response = grpc.PointsOperationResponse(
        result=grpc.UpdateResult(status=2),
        time=0.1,
        usage=grpc.Usage(
            inference=grpc.InferenceUsage(
                models={
                    contract.dense_model: grpc.ModelUsage(tokens=10),
                    contract.sparse_model: grpc.ModelUsage(tokens=11),
                }
            )
        ),
    )

    def upsert(request, timeout):
        requests.append((request, timeout))
        return response

    transport = StructuralGrpcUploadTransport(
        SimpleNamespace(grpc_points=SimpleNamespace(Upsert=upsert)),
        contract,
    )
    receipt = transport.upsert_with_usage(
        [models.PointStruct(id=_record(1).record_id, vector={}, payload={})]
    )

    request, timeout = requests[0]
    assert isinstance(request, grpc.UpsertPoints)
    assert request.collection_name == contract.collection_name
    assert request.wait is True
    assert request.timeout == int(contract.timeout_seconds)
    assert timeout == contract.timeout_seconds
    assert receipt.model_tokens == {
        contract.dense_model: 10,
        contract.sparse_model: 11,
    }


def test_transport_falls_back_only_for_typed_grpc_incompatibility() -> None:
    calls: list[str] = []
    grpc_transport = SimpleNamespace(
        upsert_with_usage=lambda _points: (_ for _ in ()).throw(
            GrpcCompatibilityError("unsupported")
        )
    )
    rest_transport = SimpleNamespace(
        upsert_with_usage=lambda _points: calls.append("rest") or "receipt"
    )

    selected, receipt, reason = select_upload_transport(
        grpc_transport,
        rest_transport,
        [SimpleNamespace(id="probe")],
    )

    assert selected is rest_transport
    assert receipt == "receipt"
    assert reason == "grpc_protocol_incompatible"
    assert calls == ["rest"]

    grpc_transport.upsert_with_usage = lambda _points: (_ for _ in ()).throw(
        StructuralProviderError(
            stage="upsert",
            category="timeout",
            message="typed",
            transient=True,
        )
    )
    with pytest.raises(StructuralProviderError):
        select_upload_transport(
            grpc_transport,
            rest_transport,
            [SimpleNamespace(id="probe")],
        )
