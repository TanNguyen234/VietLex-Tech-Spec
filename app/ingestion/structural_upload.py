"""Bounded, resumable upload for the structural Qdrant pilot."""

from __future__ import annotations

import math
import statistics
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol, Self, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from qdrant_client import grpc, models
from qdrant_client.conversions.conversion import RestToGrpc

from app.evaluation.artifact_io import write_immutable_json
from app.ingestion.structural_checkpoint import (
    AcknowledgedRecord,
    BatchReceipt,
    StructuralCheckpointStore,
    batch_identity_sha256,
)
from app.ingestion.structural_index import StructuralRecord
from app.ingestion.structural_qdrant import (
    InferenceUsageReceipt,
    StructuralProviderError,
    StructuralQdrantContract,
    StructuralQdrantError,
    point_from_record,
    structural_inference_text_sha256,
)


_PositiveInt = Annotated[StrictInt, Field(gt=0)]
_NonnegativeInt = Annotated[StrictInt, Field(ge=0)]


class GrpcCompatibilityError(RuntimeError):
    """The deployed Qdrant endpoint cannot use the required gRPC operation."""


class UsagePreservingTransport(Protocol):
    contract: StructuralQdrantContract

    def upsert_with_usage(
        self,
        points: Sequence[models.PointStruct],
    ) -> InferenceUsageReceipt: ...


@dataclass(frozen=True)
class UploadWaveResult:
    success: bool
    transient_errors: int
    p95_seconds: float
    rate_limited: bool


@dataclass
class AdaptiveUploadController:
    """Conservative additive growth and multiplicative pressure reduction."""

    batch_size: int
    workers: int
    min_batch: int
    max_batch: int
    max_workers: int
    shard_count: int
    healthy_waves: int = 0
    changes: list[dict[str, int | str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not (
            64 <= self.min_batch <= self.batch_size <= self.max_batch <= 256
        ):
            raise ValueError("upload batch range must stay within 64-256")
        if min(self.workers, self.max_workers, self.shard_count) <= 0:
            raise ValueError("upload worker and shard counts must be positive")
        if self.workers > min(self.max_workers, self.shard_count):
            raise ValueError("upload workers exceed the bounded concurrency")

    @classmethod
    def from_contract(
        cls,
        contract: StructuralQdrantContract,
        *,
        shard_count: int,
    ) -> AdaptiveUploadController:
        return cls(
            batch_size=contract.upload_batch_min,
            workers=min(shard_count, contract.upload_max_workers),
            min_batch=contract.upload_batch_min,
            max_batch=contract.upload_batch_max,
            max_workers=contract.upload_max_workers,
            shard_count=shard_count,
        )

    def observe(self, result: UploadWaveResult) -> None:
        if (
            not result.success
            or result.transient_errors >= 2
            or result.rate_limited
        ):
            previous_batch = self.batch_size
            previous_workers = self.workers
            self.batch_size = max(self.min_batch, self.batch_size // 2)
            self.workers = max(1, self.workers // 2)
            self.healthy_waves = 0
            self._record_change(
                "decrease",
                previous_batch,
                previous_workers,
            )
            return

        self.healthy_waves += 1
        if self.healthy_waves < 3:
            return
        previous_batch = self.batch_size
        previous_workers = self.workers
        self.batch_size = min(self.max_batch, self.batch_size * 2)
        self.workers = min(
            self.max_workers,
            self.shard_count,
            self.workers + 1,
        )
        self.healthy_waves = 0
        self._record_change("increase", previous_batch, previous_workers)

    def _record_change(
        self,
        reason: str,
        previous_batch: int,
        previous_workers: int,
    ) -> None:
        if (previous_batch, previous_workers) == (self.batch_size, self.workers):
            return
        self.changes.append(
            {
                "reason": reason,
                "previous_batch_size": previous_batch,
                "batch_size": self.batch_size,
                "previous_workers": previous_workers,
                "workers": self.workers,
            }
        )


_T = TypeVar("_T")


def retry_transient(
    operation: Callable[[], _T],
    *,
    max_attempts: int,
    base_seconds: float,
    max_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    retry_categories: Counter[str] | None = None,
) -> tuple[_T, int]:
    """Retry typed transient provider failures with bounded exponential delay."""
    if max_attempts <= 0 or base_seconds <= 0 or max_seconds <= 0:
        raise ValueError("retry limits must be positive")
    for attempt in range(1, max_attempts + 1):
        try:
            return operation(), attempt
        except StructuralProviderError as error:
            if not error.transient or attempt == max_attempts:
                error.attempts = attempt
                raise
            if retry_categories is not None:
                retry_categories[error.category] += 1
            sleep(min(max_seconds, base_seconds * (2 ** (attempt - 1))))
    raise AssertionError("unreachable retry loop")


def _grpc_status(value: object) -> str:
    raw = getattr(value, "value", value)
    if raw in {1, "1"}:
        return "acknowledged"
    if raw in {2, "2"}:
        return "completed"
    normalized = str(raw).strip().casefold()
    if normalized.endswith("acknowledged"):
        return "acknowledged"
    if normalized.endswith("completed") or normalized == "ok":
        return "completed"
    return normalized


def _grpc_usage_receipt(
    response: Any,
    contract: StructuralQdrantContract,
) -> InferenceUsageReceipt:
    status = _grpc_status(getattr(getattr(response, "result", None), "status", None))
    if status not in {"acknowledged", "completed"}:
        raise StructuralProviderError(
            stage="upsert",
            category="invalid_status",
            message=f"Qdrant upsert status is not acknowledged: {status or 'missing'}",
            transient=False,
        )
    raw_models = getattr(
        getattr(getattr(response, "usage", None), "inference", None),
        "models",
        None,
    )
    if not isinstance(raw_models, Mapping):
        raise StructuralProviderError(
            stage="upsert",
            category="missing_inference_usage",
            message="Qdrant upsert inference usage is missing",
            transient=False,
        )
    usage: dict[str, int] = {}
    for model_name, raw_usage in raw_models.items():
        tokens = getattr(raw_usage, "tokens", None)
        if (
            not isinstance(model_name, str)
            or not model_name
            or isinstance(tokens, bool)
            or not isinstance(tokens, int)
            or tokens <= 0
        ):
            raise StructuralProviderError(
                stage="upsert",
                category="invalid_inference_usage",
                message="Qdrant upsert inference usage is malformed",
                transient=False,
            )
        usage[model_name] = tokens
    if set(usage) != {contract.dense_model, contract.sparse_model}:
        raise StructuralProviderError(
            stage="upsert",
            category="model_usage_mismatch",
            message="Qdrant upsert inference model usage mismatch",
            transient=False,
        )
    elapsed = getattr(response, "time", None)
    if elapsed is not None and (
        isinstance(elapsed, bool)
        or not isinstance(elapsed, (int, float))
        or not math.isfinite(elapsed)
        or elapsed < 0
    ):
        raise StructuralProviderError(
            stage="upsert",
            category="invalid_response",
            message="Qdrant upsert elapsed time is malformed",
            transient=False,
        )
    return InferenceUsageReceipt(
        status=status,
        elapsed_seconds=None if elapsed is None else float(elapsed),
        model_tokens=usage,
    )


def _grpc_error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    try:
        value = code() if callable(code) else code
    except Exception:
        return ""
    return str(getattr(value, "name", value)).strip().upper()


class StructuralGrpcUploadTransport:
    """Generated gRPC upsert retaining raw Cloud Inference token usage."""

    def __init__(self, client: Any, contract: StructuralQdrantContract) -> None:
        self.client = client
        self.contract = contract

    def upsert_with_usage(
        self,
        points: Sequence[models.PointStruct],
    ) -> InferenceUsageReceipt:
        normalized = list(points)
        if not normalized:
            raise StructuralQdrantError("upsert points must not be empty")
        try:
            response = self.client.grpc_points.Upsert(
                grpc.UpsertPoints(
                    collection_name=self.contract.collection_name,
                    wait=True,
                    points=[
                        RestToGrpc.convert_point_struct(point)
                        for point in normalized
                    ],
                    timeout=int(self.contract.timeout_seconds),
                ),
                timeout=self.contract.timeout_seconds,
            )
            return _grpc_usage_receipt(response, self.contract)
        except StructuralProviderError:
            raise
        except (AttributeError, NotImplementedError) as error:
            raise GrpcCompatibilityError(
                "Qdrant gRPC upsert endpoint is unavailable"
            ) from error
        except Exception as error:
            code = _grpc_error_code(error)
            if code == "UNIMPLEMENTED":
                raise GrpcCompatibilityError(
                    "Qdrant gRPC upsert protocol is unsupported"
                ) from error
            transient = code in {
                "ABORTED",
                "DEADLINE_EXCEEDED",
                "RESOURCE_EXHAUSTED",
                "UNAVAILABLE",
            } or isinstance(error, TimeoutError)
            raise StructuralProviderError(
                stage="upsert",
                category=code or type(error).__name__,
                message=f"Qdrant gRPC upsert failed: {code or type(error).__name__}",
                transient=transient,
            ) from error


def select_upload_transport(
    grpc_transport: UsagePreservingTransport,
    rest_transport: UsagePreservingTransport,
    probe_points: Sequence[models.PointStruct],
) -> tuple[UsagePreservingTransport, InferenceUsageReceipt, str | None]:
    """Select one transport for the run; only incompatibility permits REST."""
    try:
        receipt = grpc_transport.upsert_with_usage(probe_points)
        return grpc_transport, receipt, None
    except GrpcCompatibilityError:
        receipt = rest_transport.upsert_with_usage(probe_points)
        return rest_transport, receipt, "grpc_protocol_incompatible"


class StructuralUploadReport(BaseModel):
    """Auditable throughput and usage evidence for one resumable run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["UPLOAD_COMPLETE", "UPLOAD_INCOMPLETE"]
    collection_name: Literal["vietlex-legal-rag-v2-pilot-384"]
    created_at_utc: datetime
    source_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    creation_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_revision: str = Field(min_length=1)
    ordered_record_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_record_count: _PositiveInt
    transport: str = Field(min_length=1)
    transport_fallback_reason: str | None = None
    committed_this_run: _NonnegativeInt
    committed_total: _NonnegativeInt
    remaining_count: _NonnegativeInt
    batch_count: _NonnegativeInt
    batch_sizes: tuple[_PositiveInt, ...]
    provider_usage: dict[str, StrictInt]
    provider_calls: _NonnegativeInt
    retries_by_category: dict[str, _NonnegativeInt]
    p50_batch_seconds: float = Field(ge=0, allow_inf_nan=False)
    p95_batch_seconds: float = Field(ge=0, allow_inf_nan=False)
    records_per_second: float = Field(ge=0, allow_inf_nan=False)
    approximate_tokens_per_second: float = Field(
        ge=0,
        allow_inf_nan=False,
    )
    adaptive_changes: tuple[dict[str, int | str], ...]

    @property
    def completed(self) -> bool:
        return self.status == "UPLOAD_COMPLETE"

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        if self.created_at_utc.utcoffset() is None:
            raise ValueError("upload report timestamp must be timezone-aware")
        if self.committed_total + self.remaining_count != self.manifest_record_count:
            raise ValueError("upload report count binding mismatch")
        if (self.remaining_count == 0) != self.completed:
            raise ValueError("upload report status mismatch")
        if self.batch_count != len(self.batch_sizes) or any(
            size <= 0 or size > 256 for size in self.batch_sizes
        ):
            raise ValueError("upload report batch evidence mismatch")
        if set(self.provider_usage) != {
            "intfloat/multilingual-e5-small",
            "qdrant/bm25",
        } or any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            for value in self.provider_usage.values()
        ):
            raise ValueError("upload report provider usage mismatch")
        return self


def upload_one_batch(
    transport: UsagePreservingTransport,
    records: Sequence[StructuralRecord],
    *,
    sleep: Callable[[float], None] = time.sleep,
    retry_categories: Counter[str] | None = None,
) -> BatchReceipt:
    normalized = sorted(records, key=lambda record: record.record_id)
    if not normalized:
        raise ValueError("upload batch must not be empty")
    contract = transport.contract
    started = time.monotonic()
    points = [point_from_record(record, contract) for record in normalized]
    receipt, attempts = retry_transient(
        lambda: transport.upsert_with_usage(points),
        max_attempts=contract.max_retries,
        base_seconds=contract.retry_base_seconds,
        max_seconds=contract.retry_max_seconds,
        sleep=sleep,
        retry_categories=retry_categories,
    )
    acknowledged = tuple(
        AcknowledgedRecord(
            record_id=record.record_id,
            chunk_sha256=record.chunk_sha256,
            inference_text_sha256=structural_inference_text_sha256(record),
        )
        for record in normalized
    )
    elapsed = time.monotonic() - started
    return BatchReceipt(
        batch_sha256=batch_identity_sha256(acknowledged),
        records=acknowledged,
        usage=dict(receipt.model_tokens),
        attempts=attempts,
        elapsed_seconds=elapsed,
    )


def _next_wave(
    records: Iterable[StructuralRecord],
    *,
    batch_size: int,
    workers: int,
) -> list[list[StructuralRecord]]:
    selected = list(islice(records, batch_size * workers))
    return [
        selected[start : start + batch_size]
        for start in range(0, len(selected), batch_size)
    ]


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return float(ordered[index])


def upload_structural_records(
    transport: UsagePreservingTransport,
    records: Iterable[StructuralRecord],
    checkpoint: StructuralCheckpointStore,
    controller: AdaptiveUploadController,
    *,
    manifest_record_count: int,
    sleep: Callable[[float], None] = time.sleep,
    transport_name: str | None = None,
    transport_fallback_reason: str | None = None,
    preflight_usage: Mapping[str, int] | None = None,
    report_path: Path | None = None,
) -> StructuralUploadReport:
    """Stream uncommitted records through bounded concurrent waves."""
    if manifest_record_count != checkpoint.binding.manifest_record_count:
        raise ValueError("manifest record count does not match checkpoint binding")
    if transport.contract.collection_name != checkpoint.binding.collection_name:
        raise ValueError("transport collection does not match checkpoint binding")

    started = time.monotonic()
    pending = checkpoint.iter_pending(records)
    batch_sizes: list[int] = []
    latencies: list[float] = []
    retry_categories: Counter[str] = Counter()
    committed_this_run = 0
    approximate_tokens = 0
    provider_calls = 1 if preflight_usage else 0

    while True:
        wave = _next_wave(
            pending,
            batch_size=controller.batch_size,
            workers=controller.workers,
        )
        if not wave:
            break
        wave_receipts: list[BatchReceipt] = []
        wave_error: Exception | None = None
        wave_retry_categories: Counter[str] = Counter()
        with ThreadPoolExecutor(max_workers=controller.workers) as executor:
            futures = {}
            for batch in wave:
                batch_retry_categories: Counter[str] = Counter()
                future = executor.submit(
                    upload_one_batch,
                    transport,
                    batch,
                    sleep=sleep,
                    retry_categories=batch_retry_categories,
                )
                futures[future] = batch_retry_categories
            for future in as_completed(futures):
                try:
                    wave_receipts.append(future.result())
                except Exception as error:
                    if wave_error is None:
                        wave_error = error
                finally:
                    wave_retry_categories.update(futures[future])
        retry_categories.update(wave_retry_categories)

        for receipt in sorted(
            wave_receipts,
            key=lambda item: item.records[0].record_id,
        ):
            committed_this_run += checkpoint.commit_receipt(receipt)
            batch_sizes.append(len(receipt.records))
            latencies.append(receipt.elapsed_seconds or 0.0)
            provider_calls += receipt.attempts
        if wave_error is not None:
            controller.observe(
                UploadWaveResult(
                    success=False,
                    transient_errors=sum(wave_retry_categories.values()),
                    p95_seconds=_percentile(latencies, 0.95),
                    rate_limited=bool(
                        {"rate_limit", "RESOURCE_EXHAUSTED"}
                        & wave_retry_categories.keys()
                    ),
                )
            )
            raise wave_error
        for batch in wave:
            approximate_tokens += sum(record.token_count for record in batch)
        controller.observe(
            UploadWaveResult(
                success=True,
                transient_errors=sum(wave_retry_categories.values()),
                p95_seconds=_percentile(
                    [receipt.elapsed_seconds or 0.0 for receipt in wave_receipts],
                    0.95,
                ),
                rate_limited=False,
            )
        )

    committed_total = checkpoint.committed_count()
    if committed_total > manifest_record_count:
        raise ValueError("checkpoint exceeds manifest record count")
    elapsed = max(time.monotonic() - started, 1e-9)
    usage = checkpoint.usage_totals()
    if preflight_usage is not None:
        if set(preflight_usage) != set(usage) or any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            for value in preflight_usage.values()
        ):
            raise ValueError("upload preflight usage mismatch")
        usage = {
            model_name: usage[model_name] + preflight_usage[model_name]
            for model_name in usage
        }
    report = StructuralUploadReport(
        status=(
            "UPLOAD_COMPLETE"
            if committed_total == manifest_record_count
            else "UPLOAD_INCOMPLETE"
        ),
        collection_name=checkpoint.binding.collection_name,
        created_at_utc=datetime.now(timezone.utc),
        source_state_sha256=checkpoint.binding.source_state_sha256,
        plan_sha256=checkpoint.binding.plan_sha256,
        creation_receipt_sha256=(
            checkpoint.binding.creation_receipt_sha256
        ),
        probe_report_sha256=checkpoint.binding.probe_report_sha256,
        dataset_revision=checkpoint.binding.dataset_revision,
        ordered_record_ids_sha256=(
            checkpoint.binding.ordered_record_ids_sha256
        ),
        manifest_record_count=checkpoint.binding.manifest_record_count,
        transport=transport_name or type(transport).__name__,
        transport_fallback_reason=transport_fallback_reason,
        committed_this_run=committed_this_run,
        committed_total=committed_total,
        remaining_count=manifest_record_count - committed_total,
        batch_count=len(batch_sizes),
        batch_sizes=tuple(batch_sizes),
        provider_usage=usage,
        provider_calls=provider_calls,
        retries_by_category=dict(sorted(retry_categories.items())),
        p50_batch_seconds=float(statistics.median(latencies)) if latencies else 0.0,
        p95_batch_seconds=_percentile(latencies, 0.95),
        records_per_second=committed_this_run / elapsed,
        approximate_tokens_per_second=approximate_tokens / elapsed,
        adaptive_changes=tuple(controller.changes),
    )
    if report_path is not None:
        write_immutable_json(report_path, report.model_dump(mode="json"))
    return report
