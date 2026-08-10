"""Provider-free audit and immutable planning for the Qdrant structural pilot."""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping
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
_PILOT_COLLECTION = "vietlex-legal-rag-v2-pilot"


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
    dense_dimension: Literal[1024]
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
    collection_name: Literal["vietlex-legal-rag-v2-pilot"]
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CollectionSchemaReceipt(BaseModel):
    """Exact public schema observed after collection creation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dense_vector_name: Literal["dense"]
    dense_size: Literal[1024]
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
    status: Literal["CREATED"] = "CREATED"
    collection_name: Literal["vietlex-legal-rag-v2-pilot"]
    started_at_utc: datetime
    verified_at_utc: datetime
    source_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_readback: CollectionSchemaReceipt
    payload_indexes: tuple[str, ...]
    points_count: Literal[0]
    provider_calls: Literal[6]
    inference_calls: Literal[0]


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

    dense = manifest.record_count * 1024 * 4
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
        dense_dimension=1024,
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
    if exists:
        raise StructuralPilotError("Qdrant pilot collection already exists")

    started_at = datetime.now(timezone.utc)
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

    index_contract = (
        ("dataset_revision", models.PayloadSchemaType.KEYWORD),
        ("legal_type", models.PayloadSchemaType.KEYWORD),
        ("document_id", models.PayloadSchemaType.INTEGER),
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
