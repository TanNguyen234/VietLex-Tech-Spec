"""Provider-free audit and immutable planning for the Qdrant structural pilot."""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_serializer,
    model_validator,
)
from qdrant_client import QdrantClient, models

from app.config import Settings
from app.evaluation.artifact_io import canonical_json_bytes, write_immutable_json
from app.evaluation.provenance import GitProvenance, collect_git_provenance
from app.evaluation.run_manifest import generate_unique_run_id, prepare_run_directory
from app.ingestion.content_store import ContentStore
from app.ingestion.structural_index import (
    StructuralCorpusManifest,
    StructuralManifestBuilder,
    StructuralRecord,
    iter_structural_records,
    select_structural_document_ids,
)
from app.ingestion.structural_qdrant import (
    StructuralQdrantContract,
    point_payload,
)


_PositiveInt = Annotated[StrictInt, Field(gt=0)]
_NonnegativeInt = Annotated[StrictInt, Field(ge=0)]
_CAPACITY_INPUTS = (
    "disk_bytes",
    "ram_bytes",
    "vcpu",
    "existing_disk_bytes",
    "shard_count",
)
_CAPACITY_COMPONENTS = (
    "dense_float32",
    "body_utf8",
    "metadata_json",
    "sparse_budget",
    "hnsw_edges",
    "wal_segments",
    "safety_headroom",
)
_PILOT_COLLECTION = "vietlex-legal-rag-v2-pilot-384"


class StructuralPilotError(RuntimeError):
    """Raised when the local pilot evidence is incomplete or inconsistent."""


class CapacityEnvelope(BaseModel):
    """Explicit cluster evidence; unknown inputs remain unknown."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    disk_bytes: _PositiveInt | None = None
    ram_bytes: _PositiveInt | None = None
    vcpu: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    existing_disk_bytes: _NonnegativeInt | None = None
    shard_count: _PositiveInt | None = None

    @model_validator(mode="after")
    def validate_disk_evidence(self) -> Self:
        if (
            self.disk_bytes is not None
            and self.existing_disk_bytes is not None
            and self.existing_disk_bytes > self.disk_bytes
        ):
            raise ValueError("existing_disk_bytes exceeds disk_bytes")
        return self


class StructuralCapacityEstimate(BaseModel):
    """Conservative formula output, not observed provider storage usage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    estimation_method: Literal["explicit_conservative_v1"]
    dense_dimension: Literal[384]
    hnsw_m: int = Field(gt=0)
    sparse_body_multiplier: Literal[2]
    hnsw_bidirectional_edge_multiplier: Literal[2]
    float32_bytes: Literal[4]
    wal_ratio: Literal[0.2]
    safety_headroom_ratio: Literal[0.25]
    components: Mapping[str, int]
    projected_total_bytes: int = Field(gt=0)
    cluster_disk_bytes: int | None = Field(default=None, gt=0)
    cluster_ram_bytes: int | None = Field(default=None, gt=0)
    cluster_vcpu: float | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
    )
    existing_disk_bytes: int | None = Field(default=None, ge=0)
    available_disk_bytes: int | None = Field(default=None, ge=0)
    shard_count: int | None = Field(default=None, gt=0)
    missing_capacity_inputs: tuple[str, ...]
    status: Literal["PASS_CAPACITY", "BLOCKED_CAPACITY"]
    measurement_status: Literal["estimated_pending_post_finalize_measurement"]

    @model_validator(mode="after")
    def validate_estimate(self) -> Self:
        if set(self.components) != set(_CAPACITY_COMPONENTS) or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in self.components.values()
        ):
            raise ValueError("capacity components do not match the contract")
        if self.projected_total_bytes != sum(self.components.values()):
            raise ValueError("projected capacity total is inconsistent")
        if self.missing_capacity_inputs and self.status != "BLOCKED_CAPACITY":
            raise ValueError("missing capacity evidence must be blocked")
        object.__setattr__(
            self,
            "components",
            MappingProxyType(dict(self.components)),
        )
        return self

    @field_serializer("components")
    def serialize_components(self, value: Mapping[str, int]) -> dict[str, int]:
        return dict(value)


class StructuralCorpusAudit(BaseModel):
    """Body-free local audit evidence used to construct a plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: StructuralCorpusManifest
    selected_document_ids: tuple[int, ...]
    metadata_json_bytes: int = Field(gt=0)
    provider_calls: Literal[0] = 0


class StructuralPilotPlan(BaseModel):
    """Immutable source, corpus, capacity, and command binding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: str = Field(min_length=1)
    created_at_utc: datetime
    manifest: StructuralCorpusManifest
    contract: StructuralQdrantContract
    capacity: StructuralCapacityEstimate
    source_git_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_git_dirty: bool
    command: str = Field(min_length=1)
    command_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_calls: Literal[0] = 0
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        expected_command_hash = hashlib.sha256(
            self.command.encode("utf-8")
        ).hexdigest()
        if self.command_sha256 != expected_command_hash:
            raise ValueError("command SHA-256 mismatch")
        if self.contract.collection_name != _PILOT_COLLECTION:
            raise ValueError("plan targets an unsafe collection")
        return self


class RemoteWriteAuthorization(BaseModel):
    """Exact, explicit authorization envelope for later remote phases."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allow_remote_write: Literal[True]
    collection_name: Literal["vietlex-legal-rag-v2-pilot-384"]
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CollectionSchemaReceipt(BaseModel):
    """Exact public schema observed after collection creation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dense_vector_name: Literal["dense"]
    dense_size: Literal[384]
    dense_distance: Literal["Cosine"]
    dense_on_disk: Literal[True]
    sparse_vector_name: Literal["bm25"]
    sparse_modifier: Literal["idf"]
    sparse_on_disk: Literal[True]
    hnsw_m: Literal[0]
    hnsw_on_disk: Literal[True]
    shard_number: int = Field(gt=0)
    on_disk_payload: Literal[True]


class CollectionCreationReceipt(BaseModel):
    """Immutable, credential-free evidence for the create phase."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["CREATED", "ADOPTED_EMPTY"] = "CREATED"
    collection_name: Literal["vietlex-legal-rag-v2-pilot-384"]
    started_at_utc: datetime
    verified_at_utc: datetime
    source_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_readback: CollectionSchemaReceipt
    payload_indexes: tuple[str, ...]
    points_count: Literal[0]
    provider_calls: Literal[2, 6]
    inference_calls: Literal[0]

    @model_validator(mode="after")
    def validate_operation_count(self) -> Self:
        expected_calls = 6 if self.status == "CREATED" else 2
        if self.provider_calls != expected_calls:
            raise ValueError("creation status/provider call count mismatch")
        return self


class FinalizedCollectionSchemaReceipt(BaseModel):
    """Exact structural collection schema after HNSW activation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dense_vector_name: Literal["dense"]
    dense_size: Literal[384]
    dense_distance: Literal["Cosine"]
    dense_on_disk: Literal[True]
    sparse_vector_name: Literal["bm25"]
    sparse_modifier: Literal["idf"]
    sparse_on_disk: Literal[True]
    hnsw_m: Literal[16]
    hnsw_on_disk: Literal[True]
    shard_number: int = Field(gt=0)
    on_disk_payload: Literal[True]


class CollectionFinalizeReceipt(BaseModel):
    """Immutable result of bounded HNSW finalization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["PASS_FINALIZE", "BLOCKED_TECHNICAL"]
    collection_name: Literal["vietlex-legal-rag-v2-pilot-384"]
    created_at_utc: datetime
    source_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    creation_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    upload_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    points_count: _NonnegativeInt
    indexed_vectors_count: _NonnegativeInt | None = None
    collection_status: str = Field(min_length=1)
    optimizer_status: str = Field(min_length=1)
    schema_readback: FinalizedCollectionSchemaReceipt | None
    provider_usage: dict[str, StrictInt]
    provider_calls: _NonnegativeInt
    technical_errors: dict[str, str]
    remote_cleanup_calls: Literal[0] = 0

    @model_validator(mode="after")
    def validate_finalize_result(self) -> Self:
        if self.created_at_utc.utcoffset() is None:
            raise ValueError("finalize timestamp must be timezone-aware")
        if set(self.provider_usage) != {
            "intfloat/multilingual-e5-small"
        } or any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            for value in self.provider_usage.values()
        ):
            raise ValueError("finalize provider usage is incomplete")
        if self.status == "PASS_FINALIZE":
            if self.technical_errors or self.schema_readback is None:
                raise ValueError("successful finalize evidence is incomplete")
            if self.collection_status != "green" or self.optimizer_status != "ok":
                raise ValueError("successful finalize health is incomplete")
        elif not self.technical_errors:
            raise ValueError("blocked finalize requires typed errors")
        return self


class CollectionVerificationReceipt(BaseModel):
    """Immutable exact sample and schema verification evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["PASS_VERIFY", "BLOCKED_TECHNICAL"]
    collection_name: Literal["vietlex-legal-rag-v2-pilot-384"]
    created_at_utc: datetime
    source_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    creation_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    upload_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    finalize_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_revision: str = Field(min_length=1)
    ordered_record_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    points_count: _NonnegativeInt
    sample_record_ids: tuple[str, ...]
    sample_record_hashes: dict[str, str]
    sample_payload_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    retrieved_sample_count: _NonnegativeInt
    dense_vectors_validated: _NonnegativeInt
    sparse_vectors_validated: _NonnegativeInt
    schema_readback: FinalizedCollectionSchemaReceipt | None
    provider_usage: dict[str, StrictInt]
    provider_calls: _NonnegativeInt
    technical_errors: dict[str, str]
    remote_cleanup_calls: Literal[0] = 0

    @model_validator(mode="after")
    def validate_verification_result(self) -> Self:
        if self.created_at_utc.utcoffset() is None:
            raise ValueError("verification timestamp must be timezone-aware")
        if (
            len(self.sample_record_ids) != len(set(self.sample_record_ids))
            or set(self.sample_record_hashes) != set(self.sample_record_ids)
            or any(
                not isinstance(value, str)
                or len(value) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in value
                )
                for value in self.sample_record_hashes.values()
            )
        ):
            raise ValueError("verification sample identity mismatch")
        if set(self.provider_usage) != {
            "intfloat/multilingual-e5-small"
        } or any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            for value in self.provider_usage.values()
        ):
            raise ValueError("verification provider usage is incomplete")
        if self.status == "PASS_VERIFY":
            expected = len(self.sample_record_ids)
            if (
                self.technical_errors
                or self.schema_readback is None
                or self.sample_payload_sha256 is None
                or self.retrieved_sample_count != expected
                or self.dense_vectors_validated != expected
                or self.sparse_vectors_validated != expected
            ):
                raise ValueError("successful verification evidence is incomplete")
        elif not self.technical_errors:
            raise ValueError("blocked verification requires typed errors")
        return self


def audit_structural_corpus(
    store: ContentStore,
    *,
    settings: Settings,
) -> StructuralCorpusAudit:
    """Stream and hash the exact local primary-legislation scope."""
    contract = StructuralQdrantContract.from_settings(settings)
    document_ids = select_structural_document_ids(store)
    if not document_ids:
        raise StructuralPilotError("structural corpus scope is empty")
    builder = StructuralManifestBuilder(
        selected_document_ids=document_ids,
        repository=settings.DATASET_REPOSITORY,
        revision=settings.DATASET_REVISION,
        max_tokens=contract.chunk_max_tokens,
        overlap_tokens=contract.chunk_overlap_tokens,
    )
    metadata_json_bytes = 0
    for record in iter_structural_records(
        store,
        document_ids,
        repository=settings.DATASET_REPOSITORY,
        revision=settings.DATASET_REVISION,
        max_tokens=contract.chunk_max_tokens,
        overlap_tokens=contract.chunk_overlap_tokens,
    ):
        builder.add(record)
        metadata = point_payload(record)
        metadata.pop("body")
        metadata_json_bytes += len(
            json.dumps(
                metadata,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    return StructuralCorpusAudit(
        manifest=builder.build(),
        selected_document_ids=tuple(document_ids),
        metadata_json_bytes=metadata_json_bytes,
    )


def estimate_capacity(
    manifest: StructuralCorpusManifest,
    *,
    metadata_json_bytes: int,
    capacity: CapacityEnvelope,
    hnsw_m: int = 16,
) -> StructuralCapacityEstimate:
    """Apply the recorded conservative formula without invented telemetry."""
    if (
        isinstance(metadata_json_bytes, bool)
        or not isinstance(metadata_json_bytes, int)
        or metadata_json_bytes <= 0
    ):
        raise StructuralPilotError("metadata_json_bytes must be positive")
    if isinstance(hnsw_m, bool) or not isinstance(hnsw_m, int) or hnsw_m <= 0:
        raise StructuralPilotError("hnsw_m must be positive")

    dense = manifest.record_count * 384 * 4
    body = manifest.body_bytes
    sparse_budget = body * 2
    hnsw_edges = manifest.record_count * hnsw_m * 2 * 4
    base = dense + body + metadata_json_bytes + sparse_budget + hnsw_edges
    wal_segments = math.ceil(base * 0.20)
    before_safety = base + wal_segments
    safety_headroom = math.ceil(before_safety * 0.25)
    components = {
        "dense_float32": dense,
        "body_utf8": body,
        "metadata_json": metadata_json_bytes,
        "sparse_budget": sparse_budget,
        "hnsw_edges": hnsw_edges,
        "wal_segments": wal_segments,
        "safety_headroom": safety_headroom,
    }
    projected = sum(components.values())
    missing = tuple(
        field_name
        for field_name in _CAPACITY_INPUTS
        if getattr(capacity, field_name) is None
    )
    available = (
        capacity.disk_bytes - capacity.existing_disk_bytes
        if capacity.disk_bytes is not None
        and capacity.existing_disk_bytes is not None
        else None
    )
    passed = not missing and available is not None and projected <= available
    return StructuralCapacityEstimate(
        estimation_method="explicit_conservative_v1",
        dense_dimension=384,
        hnsw_m=hnsw_m,
        sparse_body_multiplier=2,
        hnsw_bidirectional_edge_multiplier=2,
        float32_bytes=4,
        wal_ratio=0.2,
        safety_headroom_ratio=0.25,
        components=components,
        projected_total_bytes=projected,
        cluster_disk_bytes=capacity.disk_bytes,
        cluster_ram_bytes=capacity.ram_bytes,
        cluster_vcpu=capacity.vcpu,
        existing_disk_bytes=capacity.existing_disk_bytes,
        available_disk_bytes=available,
        shard_count=capacity.shard_count,
        missing_capacity_inputs=missing,
        status="PASS_CAPACITY" if passed else "BLOCKED_CAPACITY",
        measurement_status="estimated_pending_post_finalize_measurement",
    )


def build_structural_pilot_plan(
    *,
    store: ContentStore,
    settings: Settings,
    output_root: Path,
    capacity: CapacityEnvelope,
    provenance: GitProvenance | None = None,
    run_id: str | None = None,
    command: str = "programmatic structural pilot plan",
) -> StructuralPilotPlan:
    """Audit locally, bind all evidence, then write a unique plan directory."""
    provenance = provenance or collect_git_provenance()
    if provenance.status != "ok" or provenance.source_state_sha256 is None:
        raise StructuralPilotError(
            "planning requires available Git source provenance"
        )
    contract = StructuralQdrantContract.from_settings(settings)
    audit = audit_structural_corpus(store, settings=settings)
    estimate = estimate_capacity(
        audit.manifest,
        metadata_json_bytes=audit.metadata_json_bytes,
        capacity=capacity,
    )
    resolved_run_id = run_id or generate_unique_run_id("structural-pilot")
    created_at = datetime.now(timezone.utc)
    command = command.strip()
    if not command:
        raise StructuralPilotError("command must be nonblank")
    plan_data = {
        "schema_version": "1.0.0",
        "run_id": resolved_run_id,
        "created_at_utc": created_at,
        "manifest": audit.manifest,
        "contract": contract,
        "capacity": estimate,
        "source_git_sha": provenance.git_sha,
        "source_state_sha256": provenance.source_state_sha256,
        "source_git_dirty": provenance.git_dirty,
        "command": command,
        "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
        "provider_calls": 0,
    }
    plan_hash = _canonical_model_sha256(plan_data)
    plan = StructuralPilotPlan(**plan_data, plan_sha256=plan_hash)

    run_dir = prepare_run_directory(output_root, resolved_run_id)
    write_immutable_json(
        run_dir / "manifest.json",
        audit.manifest.model_dump(mode="json"),
    )
    write_immutable_json(
        run_dir / "scope.json",
        {
            "dataset_repository": audit.manifest.dataset_repository,
            "dataset_revision": audit.manifest.dataset_revision,
            "legal_types": list(audit.manifest.legal_types),
            "document_count": audit.manifest.document_count,
            "record_count": audit.manifest.record_count,
            "selected_document_ids": list(audit.selected_document_ids),
            "selected_document_ids_sha256": (
                audit.manifest.selected_document_ids_sha256
            ),
            "ordered_record_ids_sha256": (
                audit.manifest.ordered_record_ids_sha256
            ),
            "provider_calls": 0,
        },
    )
    write_immutable_json(run_dir / "plan.json", plan.model_dump(mode="json"))
    _write_immutable_report(run_dir / "report.md", plan)
    return plan


def load_bound_plan(path: Path) -> StructuralPilotPlan:
    """Load a plan and independently verify its canonical hash binding."""
    target = Path(path)
    if target.is_dir():
        target = target / "plan.json"
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StructuralPilotError(f"unable to load plan: {type(error).__name__}") from error
    try:
        plan = StructuralPilotPlan.model_validate(payload)
    except ValueError as error:
        raise StructuralPilotError("plan schema validation failed") from error
    actual_hash = _plan_sha256(plan)
    if actual_hash != plan.plan_sha256:
        raise StructuralPilotError("plan SHA-256 mismatch")
    return plan


def validate_remote_write_authorization(
    plan: StructuralPilotPlan,
    authorization: RemoteWriteAuthorization,
    provenance: GitProvenance,
) -> None:
    """Fail closed unless current source and every authorized target match."""
    if provenance.status != "ok" or provenance.source_state_sha256 is None:
        raise StructuralPilotError(
            "remote writes require available Git source provenance"
        )
    if (
        plan.source_state_sha256 != authorization.source_state_sha256
        or provenance.source_state_sha256 != authorization.source_state_sha256
    ):
        raise StructuralPilotError("source state authorization mismatch")
    if (
        _plan_sha256(plan) != plan.plan_sha256
        or plan.plan_sha256 != authorization.plan_sha256
    ):
        raise StructuralPilotError("plan authorization mismatch")
    if (
        plan.contract.collection_name != authorization.collection_name
        or authorization.collection_name != _PILOT_COLLECTION
    ):
        raise StructuralPilotError("collection authorization mismatch")
    if plan.capacity.status != "PASS_CAPACITY":
        raise StructuralPilotError("BLOCKED_CAPACITY")


def create_structural_collection(
    client: QdrantClient,
    plan: StructuralPilotPlan,
    authorization: RemoteWriteAuthorization,
    provenance: GitProvenance,
    *,
    receipt_path: Path | None = None,
) -> CollectionCreationReceipt:
    """Create the one exact empty pilot collection; never delete or recreate."""
    validate_remote_write_authorization(plan, authorization, provenance)
    if receipt_path is not None and Path(receipt_path).exists():
        raise StructuralPilotError("create receipt already exists")

    contract = plan.contract
    try:
        exists = client.collection_exists(contract.collection_name)
    except Exception as error:
        raise StructuralPilotError(
            "Qdrant collection existence check failed "
            f"({type(error).__name__})"
        ) from error
    started_at = datetime.now(timezone.utc)
    index_contract = (
        ("dataset_revision", models.PayloadSchemaType.KEYWORD),
        ("legal_type", models.PayloadSchemaType.KEYWORD),
        ("document_id", models.PayloadSchemaType.INTEGER),
    )
    if exists:
        try:
            readback = client.get_collection(contract.collection_name)
        except Exception as error:
            raise StructuralPilotError(
                f"Qdrant collection readback failed ({type(error).__name__})"
            ) from error
        schema_receipt = _validate_collection_readback(
            readback,
            contract=contract,
            shard_number=plan.capacity.shard_count,
        )
        receipt = CollectionCreationReceipt(
            status="ADOPTED_EMPTY",
            collection_name=contract.collection_name,
            started_at_utc=started_at,
            verified_at_utc=datetime.now(timezone.utc),
            source_state_sha256=plan.source_state_sha256,
            plan_sha256=plan.plan_sha256,
            schema_readback=schema_receipt,
            payload_indexes=tuple(
                sorted(field for field, _schema in index_contract)
            ),
            points_count=0,
            provider_calls=2,
            inference_calls=0,
        )
        if receipt_path is not None:
            write_immutable_json(receipt_path, receipt.model_dump(mode="json"))
        return receipt

    try:
        created = client.create_collection(
            collection_name=contract.collection_name,
            vectors_config={
                contract.dense_vector_name: models.VectorParams(
                    size=contract.dense_size,
                    distance=models.Distance.COSINE,
                    on_disk=True,
                )
            },
            sparse_vectors_config={
                contract.sparse_vector_name: models.SparseVectorParams(
                    index=models.SparseIndexParams(on_disk=True),
                    modifier=models.Modifier.IDF,
                )
            },
            shard_number=plan.capacity.shard_count,
            on_disk_payload=True,
            hnsw_config=models.HnswConfigDiff(m=0, on_disk=True),
            timeout=int(contract.timeout_seconds),
        )
    except Exception as error:
        raise StructuralPilotError(
            f"Qdrant collection creation failed ({type(error).__name__})"
        ) from error
    if created is not True:
        raise StructuralPilotError(
            "Qdrant did not acknowledge collection creation"
        )

    for field_name, field_schema in index_contract:
        try:
            result = client.create_payload_index(
                collection_name=contract.collection_name,
                field_name=field_name,
                field_schema=field_schema,
                wait=True,
                timeout=int(contract.timeout_seconds),
            )
        except Exception as error:
            raise StructuralPilotError(
                f"Qdrant payload index creation failed ({type(error).__name__})"
            ) from error
        if getattr(result, "status", None) not in {
            models.UpdateStatus.ACKNOWLEDGED,
            models.UpdateStatus.COMPLETED,
        }:
            raise StructuralPilotError(
                "Qdrant did not acknowledge payload index creation"
            )

    try:
        readback = client.get_collection(contract.collection_name)
    except Exception as error:
        raise StructuralPilotError(
            f"Qdrant collection readback failed ({type(error).__name__})"
        ) from error
    schema_receipt = _validate_collection_readback(
        readback,
        contract=contract,
        shard_number=plan.capacity.shard_count,
    )
    receipt = CollectionCreationReceipt(
        collection_name=contract.collection_name,
        started_at_utc=started_at,
        verified_at_utc=datetime.now(timezone.utc),
        source_state_sha256=plan.source_state_sha256,
        plan_sha256=plan.plan_sha256,
        schema_readback=schema_receipt,
        payload_indexes=tuple(sorted(field for field, _schema in index_contract)),
        points_count=0,
        provider_calls=6,
        inference_calls=0,
    )
    if receipt_path is not None:
        write_immutable_json(
            receipt_path,
            receipt.model_dump(mode="json"),
        )
    return receipt


def _validate_collection_readback(
    readback: object,
    *,
    contract: StructuralQdrantContract,
    shard_number: int | None,
    expected_points_count: int | None = 0,
) -> CollectionSchemaReceipt:
    if shard_number is None:
        raise StructuralPilotError("collection shard count is unavailable")
    try:
        params = readback.config.params
        vectors = params.vectors
        dense = vectors[contract.dense_vector_name]
        sparse_vectors = params.sparse_vectors
        sparse = sparse_vectors[contract.sparse_vector_name]
        hnsw = readback.config.hnsw_config
        payload_schema = readback.payload_schema
    except (AttributeError, KeyError, TypeError) as error:
        raise StructuralPilotError("Qdrant collection readback is incomplete") from error
    if set(vectors) != {contract.dense_vector_name} or (
        dense.size != contract.dense_size
        or dense.distance != models.Distance.COSINE
        or dense.on_disk is not True
    ):
        raise StructuralPilotError("Qdrant dense vector readback mismatch")
    if set(sparse_vectors) != {contract.sparse_vector_name} or (
        sparse.modifier != models.Modifier.IDF
        or sparse.index is None
        or sparse.index.on_disk is not True
    ):
        raise StructuralPilotError("Qdrant sparse vector readback mismatch")
    if hnsw.m != 0 or hnsw.on_disk is not True:
        raise StructuralPilotError("Qdrant HNSW readback mismatch")
    if (
        params.shard_number != shard_number
        or params.on_disk_payload is not True
    ):
        raise StructuralPilotError("Qdrant collection storage readback mismatch")
    expected_payload = {
        "dataset_revision": models.PayloadSchemaType.KEYWORD,
        "legal_type": models.PayloadSchemaType.KEYWORD,
        "document_id": models.PayloadSchemaType.INTEGER,
    }
    if set(payload_schema) != set(expected_payload) or any(
        payload_schema[field].data_type != schema
        for field, schema in expected_payload.items()
    ):
        raise StructuralPilotError("Qdrant payload indexes readback mismatch")
    if (
        expected_points_count is not None
        and readback.points_count != expected_points_count
    ):
        raise StructuralPilotError(
            "Qdrant collection is not empty after creation"
            if expected_points_count == 0
            else "Qdrant collection point count readback mismatch"
        )
    return CollectionSchemaReceipt(
        dense_vector_name=contract.dense_vector_name,
        dense_size=dense.size,
        dense_distance=dense.distance.value,
        dense_on_disk=dense.on_disk,
        sparse_vector_name=contract.sparse_vector_name,
        sparse_modifier=sparse.modifier.value,
        sparse_on_disk=sparse.index.on_disk,
        hnsw_m=hnsw.m,
        hnsw_on_disk=hnsw.on_disk,
        shard_number=params.shard_number,
        on_disk_payload=params.on_disk_payload,
    )


def _validate_finalized_collection_readback(
    readback: object,
    *,
    contract: StructuralQdrantContract,
    shard_number: int | None,
    expected_points_count: int,
) -> FinalizedCollectionSchemaReceipt:
    """Validate the exact post-finalize schema and count."""
    if shard_number is None:
        raise StructuralPilotError("collection shard count is unavailable")
    try:
        params = readback.config.params
        vectors = params.vectors
        dense = vectors[contract.dense_vector_name]
        sparse_vectors = params.sparse_vectors
        sparse = sparse_vectors[contract.sparse_vector_name]
        hnsw = readback.config.hnsw_config
        payload_schema = readback.payload_schema
    except (AttributeError, KeyError, TypeError) as error:
        raise StructuralPilotError(
            "Qdrant finalized collection readback is incomplete"
        ) from error
    if set(vectors) != {contract.dense_vector_name} or (
        dense.size != contract.dense_size
        or dense.distance != models.Distance.COSINE
        or dense.on_disk is not True
    ):
        raise StructuralPilotError("Qdrant dense vector readback mismatch")
    if set(sparse_vectors) != {contract.sparse_vector_name} or (
        sparse.modifier != models.Modifier.IDF
        or sparse.index is None
        or sparse.index.on_disk is not True
    ):
        raise StructuralPilotError("Qdrant sparse vector readback mismatch")
    if hnsw.m != 16 or hnsw.on_disk is not True:
        raise StructuralPilotError("Qdrant finalized HNSW readback mismatch")
    if (
        params.shard_number != shard_number
        or params.on_disk_payload is not True
    ):
        raise StructuralPilotError("Qdrant collection storage readback mismatch")
    expected_payload = {
        "dataset_revision": models.PayloadSchemaType.KEYWORD,
        "legal_type": models.PayloadSchemaType.KEYWORD,
        "document_id": models.PayloadSchemaType.INTEGER,
    }
    if set(payload_schema) != set(expected_payload) or any(
        payload_schema[field].data_type != schema
        for field, schema in expected_payload.items()
    ):
        raise StructuralPilotError("Qdrant payload indexes readback mismatch")
    if readback.points_count != expected_points_count:
        raise StructuralPilotError(
            "Qdrant collection point count readback mismatch"
        )
    return FinalizedCollectionSchemaReceipt(
        dense_vector_name=contract.dense_vector_name,
        dense_size=dense.size,
        dense_distance=dense.distance.value,
        dense_on_disk=dense.on_disk,
        sparse_vector_name=contract.sparse_vector_name,
        sparse_modifier=sparse.modifier.value,
        sparse_on_disk=sparse.index.on_disk,
        hnsw_m=hnsw.m,
        hnsw_on_disk=hnsw.on_disk,
        shard_number=params.shard_number,
        on_disk_payload=params.on_disk_payload,
    )


def finalize_structural_collection(
    client: QdrantClient,
    plan: StructuralPilotPlan,
    authorization: RemoteWriteAuthorization,
    provenance: GitProvenance,
    *,
    creation_receipt: CollectionCreationReceipt,
    creation_receipt_sha256: str,
    probe_report: object,
    probe_report_sha256: str,
    upload_report: object,
    upload_report_sha256: str,
    receipt_path: Path | None = None,
    max_polls: int = 60,
    poll_interval_seconds: float = 5.0,
    sleep: Callable[[float], None] = time.sleep,
) -> CollectionFinalizeReceipt:
    """Activate HNSW only after the exact upload chain is complete."""
    _ensure_new_artifact(receipt_path, "finalize receipt")
    validate_remote_write_authorization(plan, authorization, provenance)
    _validate_pre_finalize_chain(
        plan,
        creation_receipt=creation_receipt,
        creation_receipt_sha256=creation_receipt_sha256,
        probe_report=probe_report,
        probe_report_sha256=probe_report_sha256,
        upload_report=upload_report,
        upload_report_sha256=upload_report_sha256,
    )
    if (
        isinstance(max_polls, bool)
        or not isinstance(max_polls, int)
        or max_polls <= 0
        or not math.isfinite(poll_interval_seconds)
        or poll_interval_seconds < 0
    ):
        raise StructuralPilotError("finalize polling limits are invalid")

    contract = plan.contract
    provider_calls = 0
    readback: object | None = None
    schema: FinalizedCollectionSchemaReceipt | None = None
    technical_errors: dict[str, str] = {}
    try:
        provider_calls += 1
        readback = client.get_collection(contract.collection_name)
        try:
            hnsw_m = readback.config.hnsw_config.m
        except AttributeError as error:
            raise StructuralPilotError(
                "Qdrant collection readback is incomplete"
            ) from error
        if hnsw_m == 0:
            _validate_collection_readback(
                readback,
                contract=contract,
                shard_number=plan.capacity.shard_count,
                expected_points_count=plan.manifest.record_count,
            )
            provider_calls += 1
            updated = client.update_collection(
                collection_name=contract.collection_name,
                hnsw_config=models.HnswConfigDiff(m=16, on_disk=True),
                timeout=int(contract.timeout_seconds),
            )
            if updated is not True:
                raise StructuralPilotError(
                    "Qdrant did not acknowledge HNSW finalize"
                )
        elif hnsw_m != 16:
            raise StructuralPilotError(
                "Qdrant collection has an unauthorized HNSW state"
            )

        last_validation_error: StructuralPilotError | None = None
        for poll_index in range(max_polls):
            provider_calls += 1
            readback = client.get_collection(contract.collection_name)
            try:
                schema = _validate_finalized_collection_readback(
                    readback,
                    contract=contract,
                    shard_number=plan.capacity.shard_count,
                    expected_points_count=plan.manifest.record_count,
                )
                last_validation_error = None
            except StructuralPilotError as error:
                last_validation_error = error
                schema = None
            status = _enum_text(getattr(readback, "status", None))
            optimizer = _enum_text(
                getattr(readback, "optimizer_status", None)
            )
            indexed = getattr(readback, "indexed_vectors_count", None)
            indexed_ready = indexed is None or (
                isinstance(indexed, int)
                and not isinstance(indexed, bool)
                and indexed >= plan.manifest.record_count
            )
            if (
                schema is not None
                and status == "green"
                and optimizer == "ok"
                and indexed_ready
            ):
                break
            if poll_index + 1 < max_polls:
                sleep(poll_interval_seconds)
        else:
            message = (
                str(last_validation_error)
                if last_validation_error is not None
                else "Qdrant finalize health poll timed out"
            )
            technical_errors["finalize"] = message
    except Exception as error:
        technical_errors["finalize"] = _safe_structural_error(error)

    collection_status = _enum_text(
        getattr(readback, "status", None)
    ) or "unavailable"
    optimizer_status = _enum_text(
        getattr(readback, "optimizer_status", None)
    ) or "unavailable"
    raw_points_count = getattr(readback, "points_count", 0)
    points_count = (
        raw_points_count
        if isinstance(raw_points_count, int)
        and not isinstance(raw_points_count, bool)
        and raw_points_count >= 0
        else 0
    )
    raw_indexed = getattr(readback, "indexed_vectors_count", None)
    indexed_vectors_count = (
        raw_indexed
        if isinstance(raw_indexed, int)
        and not isinstance(raw_indexed, bool)
        and raw_indexed >= 0
        else None
    )
    if schema is None and not technical_errors:
        technical_errors["finalize"] = "finalized schema was not observed"
    receipt = CollectionFinalizeReceipt(
        status=(
            "BLOCKED_TECHNICAL"
            if technical_errors
            else "PASS_FINALIZE"
        ),
        collection_name=contract.collection_name,
        created_at_utc=datetime.now(timezone.utc),
        source_state_sha256=plan.source_state_sha256,
        plan_sha256=plan.plan_sha256,
        creation_receipt_sha256=creation_receipt_sha256,
        probe_report_sha256=probe_report_sha256,
        upload_report_sha256=upload_report_sha256,
        points_count=points_count,
        indexed_vectors_count=indexed_vectors_count,
        collection_status=collection_status,
        optimizer_status=optimizer_status,
        schema_readback=schema,
        provider_usage=dict(getattr(upload_report, "provider_usage")),
        provider_calls=provider_calls,
        technical_errors=technical_errors,
    )
    if receipt_path is not None:
        write_immutable_json(receipt_path, receipt.model_dump(mode="json"))
    return receipt


def verify_structural_collection(
    client: QdrantClient,
    plan: StructuralPilotPlan,
    authorization: RemoteWriteAuthorization,
    provenance: GitProvenance,
    records: Iterable[StructuralRecord],
    *,
    creation_receipt: CollectionCreationReceipt,
    creation_receipt_sha256: str,
    probe_report: object,
    probe_report_sha256: str,
    upload_report: object,
    upload_report_sha256: str,
    finalize_receipt: CollectionFinalizeReceipt,
    finalize_receipt_sha256: str,
    receipt_path: Path | None = None,
    derived_sample_count: int = 16,
) -> CollectionVerificationReceipt:
    """Verify schema, exact count/hash chain, and deterministic real points."""
    _ensure_new_artifact(receipt_path, "verification receipt")
    validate_remote_write_authorization(plan, authorization, provenance)
    _validate_pre_finalize_chain(
        plan,
        creation_receipt=creation_receipt,
        creation_receipt_sha256=creation_receipt_sha256,
        probe_report=probe_report,
        probe_report_sha256=probe_report_sha256,
        upload_report=upload_report,
        upload_report_sha256=upload_report_sha256,
    )
    _require_sha256(finalize_receipt_sha256, "finalize receipt")
    if (
        finalize_receipt.status != "PASS_FINALIZE"
        or finalize_receipt.collection_name != plan.contract.collection_name
        or finalize_receipt.source_state_sha256 != plan.source_state_sha256
        or finalize_receipt.plan_sha256 != plan.plan_sha256
        or finalize_receipt.creation_receipt_sha256
        != creation_receipt_sha256
        or finalize_receipt.probe_report_sha256 != probe_report_sha256
        or finalize_receipt.upload_report_sha256 != upload_report_sha256
    ):
        raise StructuralPilotError("finalize receipt binding mismatch")
    if (
        isinstance(derived_sample_count, bool)
        or not isinstance(derived_sample_count, int)
        or derived_sample_count <= 0
    ):
        raise StructuralPilotError("verification sample count is invalid")

    try:
        sample_indices = _verification_sample_indices(
            plan.plan_sha256,
            plan.manifest.record_count,
            derived_sample_count,
        )
        expected_by_index: dict[int, StructuralRecord] = {}
        ordered_hash = hashlib.sha256(b"[")
        observed_count = 0
        for index, record in enumerate(records):
            if observed_count:
                ordered_hash.update(b",")
            ordered_hash.update(
                json.dumps(
                    record.record_id,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            if index in sample_indices:
                expected_by_index[index] = record
            observed_count += 1
        ordered_hash.update(b"]")
        if observed_count != plan.manifest.record_count:
            raise StructuralPilotError("verification record count mismatch")
        if ordered_hash.hexdigest() != plan.manifest.ordered_record_ids_sha256:
            raise StructuralPilotError(
                "verification ordered record hash mismatch"
            )
        if set(expected_by_index) != sample_indices:
            raise StructuralPilotError(
                "verification sample could not be resolved"
            )
        expected_records = tuple(
            expected_by_index[index] for index in sorted(expected_by_index)
        )
        sample_ids = tuple(record.record_id for record in expected_records)
        sample_hashes = {
            record.record_id: record.chunk_sha256
            for record in expected_records
        }
    except Exception as error:
        receipt = CollectionVerificationReceipt(
            status="BLOCKED_TECHNICAL",
            collection_name=plan.contract.collection_name,
            created_at_utc=datetime.now(timezone.utc),
            source_state_sha256=plan.source_state_sha256,
            plan_sha256=plan.plan_sha256,
            creation_receipt_sha256=creation_receipt_sha256,
            probe_report_sha256=probe_report_sha256,
            upload_report_sha256=upload_report_sha256,
            finalize_receipt_sha256=finalize_receipt_sha256,
            dataset_revision=plan.manifest.dataset_revision,
            ordered_record_ids_sha256=(
                plan.manifest.ordered_record_ids_sha256
            ),
            points_count=0,
            sample_record_ids=(),
            sample_record_hashes={},
            sample_payload_sha256=None,
            retrieved_sample_count=0,
            dense_vectors_validated=0,
            sparse_vectors_validated=0,
            schema_readback=None,
            provider_usage=dict(getattr(upload_report, "provider_usage")),
            provider_calls=0,
            technical_errors={
                "local_source": _safe_structural_error(error)
            },
        )
        if receipt_path is not None:
            write_immutable_json(
                receipt_path,
                receipt.model_dump(mode="json"),
            )
        return receipt

    provider_calls = 0
    technical_errors: dict[str, str] = {}
    schema: FinalizedCollectionSchemaReceipt | None = None
    retrieved_count = 0
    dense_validated = 0
    sparse_validated = 0
    sample_payload_sha256: str | None = None
    points_count = 0
    try:
        provider_calls += 1
        readback = client.get_collection(plan.contract.collection_name)
        raw_points_count = getattr(readback, "points_count", 0)
        points_count = (
            raw_points_count
            if isinstance(raw_points_count, int)
            and not isinstance(raw_points_count, bool)
            and raw_points_count >= 0
            else 0
        )
        schema = _validate_finalized_collection_readback(
            readback,
            contract=plan.contract,
            shard_number=plan.capacity.shard_count,
            expected_points_count=plan.manifest.record_count,
        )
        if (
            _enum_text(getattr(readback, "status", None)) != "green"
            or _enum_text(getattr(readback, "optimizer_status", None)) != "ok"
        ):
            raise StructuralPilotError(
                "Qdrant verification collection health mismatch"
            )
        indexed = getattr(readback, "indexed_vectors_count", None)
        if indexed is not None and (
            isinstance(indexed, bool)
            or not isinstance(indexed, int)
            or indexed < plan.manifest.record_count
        ):
            raise StructuralPilotError(
                "Qdrant verification indexed vector count mismatch"
            )
        provider_calls += 1
        retrieved = client.retrieve(
            collection_name=plan.contract.collection_name,
            ids=list(sample_ids),
            with_payload=True,
            with_vectors=True,
            timeout=int(plan.contract.timeout_seconds),
        )
        observed = {str(point.id): point for point in retrieved}
        if len(observed) != len(retrieved) or set(observed) != set(sample_ids):
            raise StructuralPilotError(
                "Qdrant verification sample identity mismatch"
            )
        for record in expected_records:
            point = observed[record.record_id]
            if getattr(point, "payload", None) != point_payload(record):
                raise StructuralPilotError(
                    "Qdrant verification sample payload mismatch"
                )
            vector = getattr(point, "vector", None)
            if not isinstance(vector, Mapping):
                raise StructuralPilotError(
                    "Qdrant verification sample vector is missing"
                )
            _validate_dense_sample_vector(
                vector.get(plan.contract.dense_vector_name),
                plan.contract.dense_size,
            )
            dense_validated += 1
            _validate_sparse_sample_vector(
                vector.get(plan.contract.sparse_vector_name)
            )
            sparse_validated += 1
        retrieved_count = len(observed)
        sample_payload_sha256 = _canonical_model_sha256(
            [
                {
                    "record_id": record.record_id,
                    "payload": point_payload(record),
                }
                for record in expected_records
            ]
        )
    except Exception as error:
        technical_errors["verify"] = _safe_structural_error(error)

    receipt = CollectionVerificationReceipt(
        status="BLOCKED_TECHNICAL" if technical_errors else "PASS_VERIFY",
        collection_name=plan.contract.collection_name,
        created_at_utc=datetime.now(timezone.utc),
        source_state_sha256=plan.source_state_sha256,
        plan_sha256=plan.plan_sha256,
        creation_receipt_sha256=creation_receipt_sha256,
        probe_report_sha256=probe_report_sha256,
        upload_report_sha256=upload_report_sha256,
        finalize_receipt_sha256=finalize_receipt_sha256,
        dataset_revision=plan.manifest.dataset_revision,
        ordered_record_ids_sha256=plan.manifest.ordered_record_ids_sha256,
        points_count=points_count,
        sample_record_ids=sample_ids,
        sample_record_hashes=sample_hashes,
        sample_payload_sha256=sample_payload_sha256,
        retrieved_sample_count=retrieved_count,
        dense_vectors_validated=dense_validated,
        sparse_vectors_validated=sparse_validated,
        schema_readback=schema,
        provider_usage=dict(getattr(upload_report, "provider_usage")),
        provider_calls=provider_calls,
        technical_errors=technical_errors,
    )
    if receipt_path is not None:
        write_immutable_json(receipt_path, receipt.model_dump(mode="json"))
    return receipt


def _validate_pre_finalize_chain(
    plan: StructuralPilotPlan,
    *,
    creation_receipt: CollectionCreationReceipt,
    creation_receipt_sha256: str,
    probe_report: object,
    probe_report_sha256: str,
    upload_report: object,
    upload_report_sha256: str,
) -> None:
    for label, digest in (
        ("creation receipt", creation_receipt_sha256),
        ("probe report", probe_report_sha256),
        ("upload report", upload_report_sha256),
    ):
        _require_sha256(digest, label)
    if (
        creation_receipt.status not in {"CREATED", "ADOPTED_EMPTY"}
        or creation_receipt.collection_name != plan.contract.collection_name
        or creation_receipt.source_state_sha256 != plan.source_state_sha256
        or creation_receipt.plan_sha256 != plan.plan_sha256
    ):
        raise StructuralPilotError("creation receipt binding mismatch")
    expected_probe = {
        "acceptance": "PASS_MODEL_PROBE",
        "collection_name": plan.contract.collection_name,
        "source_state_sha256": plan.source_state_sha256,
        "plan_sha256": plan.plan_sha256,
        "creation_receipt_sha256": creation_receipt_sha256,
        "dataset_revision": plan.manifest.dataset_revision,
        "candidate_dense_model": plan.contract.dense_model,
        "candidate_sparse_model": plan.contract.sparse_model,
    }
    if any(
        getattr(probe_report, field_name, None) != expected_value
        for field_name, expected_value in expected_probe.items()
    ):
        raise StructuralPilotError("model probe binding mismatch")
    expected_upload = {
        "status": "UPLOAD_COMPLETE",
        "collection_name": plan.contract.collection_name,
        "source_state_sha256": plan.source_state_sha256,
        "plan_sha256": plan.plan_sha256,
        "creation_receipt_sha256": creation_receipt_sha256,
        "probe_report_sha256": probe_report_sha256,
        "dataset_revision": plan.manifest.dataset_revision,
        "ordered_record_ids_sha256": plan.manifest.ordered_record_ids_sha256,
        "manifest_record_count": plan.manifest.record_count,
        "committed_total": plan.manifest.record_count,
        "remaining_count": 0,
    }
    if any(
        getattr(upload_report, field_name, None) != expected_value
        for field_name, expected_value in expected_upload.items()
    ):
        raise StructuralPilotError("upload report binding mismatch")
    usage = getattr(upload_report, "provider_usage", None)
    if not isinstance(usage, Mapping) or set(usage) != {
        plan.contract.dense_model
    } or any(
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        for value in usage.values()
    ):
        raise StructuralPilotError("upload provider usage mismatch")


def _verification_sample_indices(
    plan_sha256: str,
    record_count: int,
    derived_count: int,
) -> set[int]:
    indices = {0, record_count - 1}
    for index in range(derived_count):
        digest = hashlib.sha256(
            f"{plan_sha256}{index}".encode("utf-8")
        ).digest()
        indices.add(int.from_bytes(digest, "big") % record_count)
    return indices


def _validate_dense_sample_vector(vector: object, size: int) -> None:
    if (
        not isinstance(vector, Sequence)
        or isinstance(vector, (str, bytes))
        or len(vector) != size
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in vector
        )
    ):
        raise StructuralPilotError(
            "Qdrant verification dense vector mismatch"
        )


def _validate_sparse_sample_vector(vector: object) -> None:
    indices = getattr(vector, "indices", None)
    values = getattr(vector, "values", None)
    if isinstance(vector, Mapping):
        indices = vector.get("indices")
        values = vector.get("values")
    if (
        not isinstance(indices, Sequence)
        or isinstance(indices, (str, bytes))
        or not indices
        or not isinstance(values, Sequence)
        or isinstance(values, (str, bytes))
        or len(indices) != len(values)
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in values
        )
    ):
        raise StructuralPilotError(
            "Qdrant verification sparse vector mismatch"
        )


def _enum_text(value: object) -> str:
    if getattr(value, "error", None) is not None:
        return "error"
    return str(getattr(value, "value", value) or "").strip().casefold()


def _require_sha256(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise StructuralPilotError(f"{label} SHA-256 is malformed")


def _ensure_new_artifact(path: Path | None, label: str) -> None:
    if path is not None and Path(path).exists():
        raise StructuralPilotError(f"{label} already exists")


def _safe_structural_error(error: Exception) -> str:
    if isinstance(error, StructuralPilotError):
        return str(error)
    return type(error).__name__


def _plan_sha256(plan: StructuralPilotPlan) -> str:
    return _canonical_model_sha256(
        plan.model_dump(mode="json", exclude={"plan_sha256"})
    )


def _canonical_model_sha256(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    else:
        value = _jsonable(value)
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _write_immutable_report(path: Path, plan: StructuralPilotPlan) -> None:
    lines = [
        "# Qdrant structural pilot plan",
        "",
        f"- Run ID: `{plan.run_id}`",
        f"- Dataset: `{plan.manifest.dataset_repository}@{plan.manifest.dataset_revision}`",
        f"- Documents: {plan.manifest.document_count}",
        f"- Structural records: {plan.manifest.record_count}",
        f"- Source state SHA-256: `{plan.source_state_sha256}`",
        f"- Plan SHA-256: `{plan.plan_sha256}`",
        f"- Capacity status: `{plan.capacity.status}`",
        f"- Capacity method: `{plan.capacity.estimation_method}`",
        f"- Projected bytes: {plan.capacity.projected_total_bytes}",
        f"- Available bytes: {plan.capacity.available_disk_bytes}",
        "- Provider calls: 0",
        "",
        "Sparse, HNSW, WAL, and safety values are conservative estimates; "
        "post-finalize provider measurement is still required.",
        "",
    ]
    if plan.capacity.missing_capacity_inputs:
        lines.insert(
            -2,
            "Missing capacity inputs: "
            + ", ".join(plan.capacity.missing_capacity_inputs),
        )
    payload = "\n".join(lines).encode("utf-8")
    target = Path(path).resolve()
    try:
        file = target.open("xb")
    except FileExistsError as error:
        raise StructuralPilotError("report artifact collision") from error
    try:
        with file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise
