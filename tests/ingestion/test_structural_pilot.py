from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from qdrant_client import models

import run_structural_index_pilot
from app.config import Settings
from app.evaluation.provenance import GitProvenance
from app.ingestion.content_store import StoredDocument
from app.ingestion.legal_text import DocumentMetadata
from app.ingestion.structural_index import (
    iter_structural_records,
    select_structural_document_ids,
)
from app.ingestion.structural_pilot import (
    CapacityEnvelope,
    CollectionFinalizeReceipt,
    RemoteWriteAuthorization,
    StructuralPilotError,
    audit_structural_corpus,
    build_structural_pilot_plan,
    create_structural_collection,
    estimate_capacity,
    finalize_structural_collection,
    load_bound_plan,
    validate_remote_write_authorization,
    verify_structural_collection,
)
from app.ingestion.structural_qdrant import point_payload


def _document(document_id: int, legal_type: str = "Luật") -> StoredDocument:
    body = (
        "Điều 1. Phạm vi điều chỉnh\n"
        f"1. Quy định thử nghiệm cho văn bản {document_id}."
    )
    return StoredDocument(
        metadata=DocumentMetadata(
            document_id=document_id,
            document_number=f"{document_id}/2026/QH15",
            title=f"Luật thử nghiệm {document_id}",
            source_url=f"https://example.invalid/{document_id}",
            legal_type=legal_type,
            legal_sectors="Lĩnh vực khác",
            issuing_authority="Quốc hội",
            issuance_date="01/01/2026",
        ),
        content=body,
        content_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        content_store_key=str(document_id),
        quality_flags=(),
    )


class FakeStore:
    def __init__(self) -> None:
        self.documents = {
            3: _document(3, "Luật"),
            2: _document(2, "Hiến pháp"),
            9: _document(9, "Công văn"),
        }

    def iter_document_ids_by_legal_types(
        self,
        legal_types,
        *,
        after_id: int,
        limit: int,
    ) -> list[int]:
        allowed = set(legal_types)
        return [
            document_id
            for document_id, document in sorted(self.documents.items())
            if document_id > after_id
            and document.metadata.legal_type in allowed
        ][:limit]

    def get_many(self, document_ids: list[int]) -> dict[int, StoredDocument]:
        return {
            document_id: self.documents[document_id]
            for document_id in document_ids
            if document_id in self.documents
        }


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        DATASET_REPOSITORY="owner/legal-corpus",
        DATASET_REVISION="revision-1",
    )


def _provenance(*, source: str = "b" * 64, dirty: bool = False) -> GitProvenance:
    return GitProvenance(
        status="ok",
        repository_root="D:/repo",
        git_sha="a" * 40,
        git_dirty=dirty,
        git_tracked_dirty=dirty,
        git_staged_dirty=False,
        git_untracked_dirty=False,
        git_diff_sha256="c" * 64 if dirty else None,
        git_diff_status="ok" if dirty else "clean",
        source_state_sha256=source,
    )


def _capacity(**overrides: object) -> CapacityEnvelope:
    values: dict[str, object] = {
        "disk_bytes": 10 * 1024**3,
        "ram_bytes": 1024**3,
        "vcpu": 0.5,
        "existing_disk_bytes": 0,
        "shard_count": 1,
    }
    values.update(overrides)
    return CapacityEnvelope(**values)


def test_audit_streams_exact_sorted_scope_without_provider_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.ingestion.structural_qdrant as structural_qdrant

    monkeypatch.setattr(
        structural_qdrant,
        "create_structural_qdrant_client",
        lambda *_args, **_kwargs: pytest.fail("provider client constructed"),
    )

    audit = audit_structural_corpus(FakeStore(), settings=_settings())

    assert audit.selected_document_ids == (2, 3)
    assert audit.manifest.document_count == 2
    assert audit.manifest.record_count > 0
    assert audit.manifest.provider_calls == 0
    assert audit.metadata_json_bytes > 0
    assert "Quy định thử nghiệm" not in audit.model_dump_json()


def test_capacity_includes_every_declared_conservative_component() -> None:
    manifest = audit_structural_corpus(
        FakeStore(), settings=_settings()
    ).manifest

    estimate = estimate_capacity(
        manifest,
        metadata_json_bytes=1_000,
        capacity=_capacity(disk_bytes=10_000_000),
    )

    assert estimate.estimation_method == "explicit_conservative_v1"
    assert set(estimate.components) == {
        "dense_float32",
        "body_utf8",
        "metadata_json",
        "sparse_budget",
        "hnsw_edges",
        "wal_segments",
        "safety_headroom",
    }
    base = (
        estimate.components["dense_float32"]
        + estimate.components["body_utf8"]
        + estimate.components["metadata_json"]
        + estimate.components["sparse_budget"]
        + estimate.components["hnsw_edges"]
    )
    assert estimate.components["wal_segments"] == pytest.approx(
        base * 0.20, abs=1
    )
    assert estimate.safety_headroom_ratio == 0.25
    assert estimate.projected_total_bytes == sum(estimate.components.values())
    assert estimate.status == "PASS_CAPACITY"
    with pytest.raises(TypeError):
        estimate.components["body_utf8"] = 0


def test_missing_capacity_evidence_is_honestly_blocked() -> None:
    audit = audit_structural_corpus(FakeStore(), settings=_settings())

    estimate = estimate_capacity(
        audit.manifest,
        metadata_json_bytes=audit.metadata_json_bytes,
        capacity=CapacityEnvelope(disk_bytes=4 * 1024**3),
    )

    assert estimate.status == "BLOCKED_CAPACITY"
    assert estimate.available_disk_bytes is None
    assert estimate.missing_capacity_inputs == (
        "ram_bytes",
        "vcpu",
        "existing_disk_bytes",
        "shard_count",
    )


def test_insufficient_explicit_disk_capacity_is_blocked() -> None:
    audit = audit_structural_corpus(FakeStore(), settings=_settings())

    estimate = estimate_capacity(
        audit.manifest,
        metadata_json_bytes=audit.metadata_json_bytes,
        capacity=_capacity(disk_bytes=1, existing_disk_bytes=0),
    )

    assert estimate.missing_capacity_inputs == ()
    assert estimate.available_disk_bytes == 1
    assert estimate.status == "BLOCKED_CAPACITY"


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_capacity_rejects_nonfinite_vcpu(value: float) -> None:
    with pytest.raises(ValidationError):
        CapacityEnvelope(vcpu=value)


def test_capacity_rejects_existing_usage_above_cluster_disk() -> None:
    with pytest.raises(ValidationError, match="exceeds"):
        CapacityEnvelope(disk_bytes=10, existing_disk_bytes=11)


def test_plan_writes_body_free_immutable_bound_artifacts(tmp_path: Path) -> None:
    plan = build_structural_pilot_plan(
        store=FakeStore(),
        settings=_settings(),
        output_root=tmp_path,
        capacity=_capacity(),
        provenance=_provenance(),
        run_id="pilot-001",
        command="python run_structural_index_pilot.py plan",
    )

    run_dir = tmp_path / plan.run_id
    assert plan.capacity.status == "PASS_CAPACITY"
    assert plan.source_state_sha256 == "b" * 64
    assert len(plan.plan_sha256) == 64
    assert load_bound_plan(run_dir) == plan
    assert {path.name for path in run_dir.iterdir()} == {
        "manifest.json",
        "plan.json",
        "report.md",
        "scope.json",
    }
    for name in ("manifest.json", "plan.json", "scope.json", "report.md"):
        text = (run_dir / name).read_text(encoding="utf-8")
        assert "Quy định thử nghiệm" not in text
        assert "api_key" not in text.casefold()
    scope = json.loads((run_dir / "scope.json").read_text(encoding="utf-8"))
    assert scope["selected_document_ids"] == [2, 3]
    assert scope["selected_document_ids_sha256"] == (
        plan.manifest.selected_document_ids_sha256
    )

    with pytest.raises(FileExistsError, match="already exists"):
        build_structural_pilot_plan(
            store=FakeStore(),
            settings=_settings(),
            output_root=tmp_path,
            capacity=_capacity(),
            provenance=_provenance(),
            run_id="pilot-001",
        )


def test_load_bound_plan_rejects_canonical_hash_tampering(
    tmp_path: Path,
) -> None:
    plan = build_structural_pilot_plan(
        store=FakeStore(),
        settings=_settings(),
        output_root=tmp_path,
        capacity=_capacity(),
        provenance=_provenance(),
        run_id="pilot-tamper",
    )
    path = tmp_path / plan.run_id / "plan.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source_git_dirty"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(StructuralPilotError, match="plan SHA-256 mismatch"):
        load_bound_plan(path)


@pytest.mark.parametrize(
    ("authorization_override", "provenance", "message"),
    [
        ({"source_state_sha256": "0" * 64}, _provenance(), "source state"),
        ({"plan_sha256": "0" * 64}, _provenance(), "plan authorization"),
        ({}, _provenance(source="0" * 64), "source state"),
    ],
)
def test_authorization_rejects_mismatched_binding(
    tmp_path: Path,
    authorization_override: dict[str, object],
    provenance: GitProvenance,
    message: str,
) -> None:
    plan = build_structural_pilot_plan(
        store=FakeStore(),
        settings=_settings(),
        output_root=tmp_path,
        capacity=_capacity(),
        provenance=_provenance(),
        run_id="pilot-auth",
    )
    values: dict[str, object] = {
        "allow_remote_write": True,
        "collection_name": "vietlex-legal-rag-v2-pilot-384",
        "plan_sha256": plan.plan_sha256,
        "source_state_sha256": plan.source_state_sha256,
    }
    values.update(authorization_override)
    authorization = RemoteWriteAuthorization(**values)

    with pytest.raises(StructuralPilotError, match=message):
        validate_remote_write_authorization(plan, authorization, provenance)


def test_authorization_accepts_artifact_only_dirty_provenance(
    tmp_path: Path,
) -> None:
    plan = build_structural_pilot_plan(
        store=FakeStore(),
        settings=_settings(),
        output_root=tmp_path,
        capacity=_capacity(),
        provenance=_provenance(),
        run_id="pilot-dirty",
    )
    authorization = RemoteWriteAuthorization(
        allow_remote_write=True,
        collection_name="vietlex-legal-rag-v2-pilot-384",
        plan_sha256=plan.plan_sha256,
        source_state_sha256=plan.source_state_sha256,
    )

    validate_remote_write_authorization(
        plan,
        authorization,
        _provenance(dirty=True),
    )


def test_blocked_plan_cannot_authorize_remote_write(tmp_path: Path) -> None:
    plan = build_structural_pilot_plan(
        store=FakeStore(),
        settings=_settings(),
        output_root=tmp_path,
        capacity=CapacityEnvelope(),
        provenance=_provenance(),
        run_id="pilot-blocked",
    )
    authorization = RemoteWriteAuthorization(
        allow_remote_write=True,
        collection_name="vietlex-legal-rag-v2-pilot-384",
        plan_sha256=plan.plan_sha256,
        source_state_sha256=plan.source_state_sha256,
    )

    with pytest.raises(StructuralPilotError, match="BLOCKED_CAPACITY"):
        validate_remote_write_authorization(
            plan,
            authorization,
            _provenance(),
        )


@pytest.mark.parametrize(
    "values",
    [
        {"allow_remote_write": False},
        {"collection_name": "vietlex-legal-rag-v1"},
        {"collection_name": "vietlex-embedding-staging"},
    ],
)
def test_authorization_schema_rejects_unsafe_targets(
    values: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "allow_remote_write": True,
        "collection_name": "vietlex-legal-rag-v2-pilot-384",
        "plan_sha256": "a" * 64,
        "source_state_sha256": "b" * 64,
    }
    payload.update(values)
    with pytest.raises(ValidationError):
        RemoteWriteAuthorization(**payload)


class RecordingQdrantClient:
    def __init__(
        self,
        *,
        exists: bool = False,
        points_count: int = 0,
        mutate_readback: str | None = None,
        fail_stage: str | None = None,
        healthy: bool = True,
    ) -> None:
        self.exists = exists
        self.points_count = points_count
        self.mutate_readback = mutate_readback
        self.fail_stage = fail_stage
        self.healthy = healthy
        self.finalized = False
        self.records: dict[str, object] = {}
        self.create_calls: list[dict[str, object]] = []
        self.payload_index_calls: list[dict[str, object]] = []
        self.update_calls: list[dict[str, object]] = []
        self.retrieve_calls: list[dict[str, object]] = []
        self.get_calls: list[str] = []
        self.delete_calls: list[object] = []
        self.exists_calls: list[str] = []

    def collection_exists(self, collection_name: str) -> bool:
        self.exists_calls.append(collection_name)
        if self.fail_stage == "exists":
            raise RuntimeError("secret endpoint detail")
        return self.exists

    def create_collection(self, **kwargs) -> bool:
        self.create_calls.append(kwargs)
        if self.fail_stage == "create":
            raise RuntimeError("secret endpoint detail")
        return self.fail_stage != "create_ack"

    def create_payload_index(self, **kwargs):
        self.payload_index_calls.append(kwargs)
        if self.fail_stage == "payload_index":
            raise RuntimeError("secret endpoint detail")
        return type(
            "UpdateResult",
            (),
            {"status": models.UpdateStatus.COMPLETED},
        )()

    def get_collection(self, collection_name: str):
        self.get_calls.append(collection_name)
        if self.fail_stage == "readback":
            raise RuntimeError("secret endpoint detail")
        call = (
            self.create_calls[0]
            if self.create_calls
            else {
                "vectors_config": {
                    "dense": models.VectorParams(
                        size=384,
                        distance=models.Distance.COSINE,
                        on_disk=True,
                    )
                },
                "sparse_vectors_config": {
                    "bm25": models.SparseVectorParams(
                        index=models.SparseIndexParams(on_disk=True),
                        modifier=models.Modifier.IDF,
                    )
                },
                "hnsw_config": models.HnswConfigDiff(m=0, on_disk=True),
                "shard_number": 1,
                "on_disk_payload": True,
            }
        )
        vectors = dict(call["vectors_config"])
        sparse_vectors = dict(call["sparse_vectors_config"])
        hnsw_config = (
            models.HnswConfigDiff(m=16, on_disk=True)
            if self.finalized
            else call["hnsw_config"]
        )
        index_items = self.payload_index_calls or [
            {
                "field_name": "dataset_revision",
                "field_schema": models.PayloadSchemaType.KEYWORD,
            },
            {
                "field_name": "legal_type",
                "field_schema": models.PayloadSchemaType.KEYWORD,
            },
            {
                "field_name": "document_id",
                "field_schema": models.PayloadSchemaType.INTEGER,
            },
        ]
        payload_schema = {
            item["field_name"]: type(
                "PayloadInfo",
                (),
                {"data_type": item["field_schema"]},
            )()
            for item in index_items
        }
        if self.mutate_readback == "vector_size":
            vectors["dense"] = models.VectorParams(
                size=1024,
                distance=models.Distance.COSINE,
                on_disk=True,
            )
        elif self.mutate_readback == "sparse_on_disk":
            sparse_vectors["bm25"] = models.SparseVectorParams(
                index=models.SparseIndexParams(on_disk=False),
                modifier=models.Modifier.IDF,
            )
        elif self.mutate_readback == "hnsw_m":
            hnsw_config = models.HnswConfigDiff(m=16, on_disk=True)
        elif self.mutate_readback == "payload_schema":
            payload_schema.pop("document_id")
        return type(
            "CollectionInfo",
            (),
            {
                "status": (
                    models.CollectionStatus.GREEN
                    if self.healthy
                    else models.CollectionStatus.YELLOW
                ),
                "optimizer_status": models.OptimizersStatusOneOf.OK,
                "indexed_vectors_count": (
                    self.points_count if self.healthy else 0
                ),
                "points_count": self.points_count,
                "payload_schema": payload_schema,
                "config": type(
                    "CollectionConfig",
                    (),
                    {
                        "params": type(
                            "CollectionParams",
                            (),
                            {
                                "vectors": vectors,
                                "sparse_vectors": sparse_vectors,
                                "shard_number": call["shard_number"],
                                "on_disk_payload": call["on_disk_payload"],
                            },
                        )(),
                        "hnsw_config": hnsw_config,
                    },
                )(),
            },
        )()

    def update_collection(self, **kwargs) -> bool:
        self.update_calls.append(kwargs)
        if self.fail_stage == "finalize":
            raise RuntimeError("secret endpoint detail")
        if self.fail_stage == "finalize_ack":
            return False
        self.finalized = True
        return True

    def retrieve(self, **kwargs):
        self.retrieve_calls.append(kwargs)
        if self.fail_stage == "retrieve":
            raise RuntimeError("secret endpoint detail")
        result = []
        for record_id in kwargs["ids"]:
            record = self.records[record_id]
            payload = point_payload(record)
            if self.mutate_readback == "sample_payload":
                payload = {**payload, "dataset_revision": "wrong"}
            dense = [0.1] * 384
            if self.mutate_readback == "sample_dense":
                dense = [0.1] * 1024
            result.append(
                SimpleNamespace(
                    id=record_id,
                    payload=payload,
                    vector={
                        "dense": dense,
                        "bm25": models.SparseVector(
                            indices=[1],
                            values=[1.0],
                        ),
                    },
                )
            )
        return result

    def delete_collection(self, *args, **kwargs) -> None:
        self.delete_calls.append((args, kwargs))


def _bound_plan(tmp_path: Path, *, capacity=None):
    return build_structural_pilot_plan(
        store=FakeStore(),
        settings=_settings(),
        output_root=tmp_path,
        capacity=capacity if capacity is not None else _capacity(),
        provenance=_provenance(),
        run_id="pilot-create",
    )


def _authorization(plan) -> RemoteWriteAuthorization:
    return RemoteWriteAuthorization(
        allow_remote_write=True,
        collection_name="vietlex-legal-rag-v2-pilot-384",
        plan_sha256=plan.plan_sha256,
        source_state_sha256=plan.source_state_sha256,
    )


def test_create_uses_exact_empty_collection_schema(tmp_path: Path) -> None:
    plan = _bound_plan(tmp_path)
    client = RecordingQdrantClient()
    receipt_path = tmp_path / plan.run_id / "create-receipt.json"

    receipt = create_structural_collection(
        client,
        plan,
        _authorization(plan),
        _provenance(),
        receipt_path=receipt_path,
    )

    assert len(client.create_calls) == 1
    call = client.create_calls[0]
    assert call["collection_name"] == "vietlex-legal-rag-v2-pilot-384"
    assert call["vectors_config"]["dense"] == models.VectorParams(
        size=384,
        distance=models.Distance.COSINE,
        on_disk=True,
    )
    assert call["sparse_vectors_config"]["bm25"] == (
        models.SparseVectorParams(
            index=models.SparseIndexParams(on_disk=True),
            modifier=models.Modifier.IDF,
        )
    )
    assert call["hnsw_config"] == models.HnswConfigDiff(m=0, on_disk=True)
    assert call["shard_number"] == 1
    assert call["on_disk_payload"] is True
    assert {item["field_name"] for item in client.payload_index_calls} == {
        "dataset_revision",
        "legal_type",
        "document_id",
    }
    assert receipt.points_count == 0
    assert receipt.provider_calls == 6
    assert receipt.inference_calls == 0
    assert receipt.payload_indexes == (
        "dataset_revision",
        "document_id",
        "legal_type",
    )
    assert receipt_path.is_file()
    assert "secret" not in receipt_path.read_text(encoding="utf-8").casefold()


def test_create_adopts_only_an_exact_empty_existing_target(tmp_path: Path) -> None:
    plan = _bound_plan(tmp_path)
    client = RecordingQdrantClient(exists=True)

    receipt = create_structural_collection(
        client,
        plan,
        _authorization(plan),
        _provenance(),
    )

    assert receipt.status == "ADOPTED_EMPTY"
    assert receipt.points_count == 0
    assert receipt.provider_calls == 2
    assert client.create_calls == []
    assert client.payload_index_calls == []
    assert client.exists_calls == ["vietlex-legal-rag-v2-pilot-384"]


def test_create_rejects_blocked_capacity_before_any_provider_call(
    tmp_path: Path,
) -> None:
    plan = _bound_plan(tmp_path, capacity=CapacityEnvelope())
    client = RecordingQdrantClient()

    with pytest.raises(StructuralPilotError, match="BLOCKED_CAPACITY"):
        create_structural_collection(
            client,
            plan,
            _authorization(plan),
            _provenance(),
        )

    assert client.exists_calls == []
    assert client.create_calls == []
    assert client.delete_calls == []


@pytest.mark.parametrize(
    ("client_kwargs", "message"),
    [
        ({"fail_stage": "exists"}, "collection existence check"),
        ({"fail_stage": "create"}, "collection creation"),
        ({"fail_stage": "create_ack"}, "acknowledge"),
        ({"fail_stage": "payload_index"}, "payload index"),
        ({"fail_stage": "readback"}, "readback"),
        ({"points_count": 1}, "empty"),
        ({"mutate_readback": "vector_size"}, "dense vector"),
        ({"mutate_readback": "sparse_on_disk"}, "sparse vector"),
        ({"mutate_readback": "hnsw_m"}, "HNSW"),
        ({"mutate_readback": "payload_schema"}, "payload indexes"),
    ],
)
def test_create_fails_closed_without_cleanup(
    tmp_path: Path,
    client_kwargs: dict[str, object],
    message: str,
) -> None:
    plan = _bound_plan(tmp_path)
    client = RecordingQdrantClient(**client_kwargs)

    with pytest.raises(StructuralPilotError, match=message) as caught:
        create_structural_collection(
            client,
            plan,
            _authorization(plan),
            _provenance(),
        )

    assert "secret endpoint detail" not in str(caught.value)
    assert client.delete_calls == []


def test_create_rejects_authorization_before_any_provider_call(
    tmp_path: Path,
) -> None:
    plan = _bound_plan(tmp_path)
    client = RecordingQdrantClient()
    authorization = _authorization(plan).model_copy(
        update={"source_state_sha256": "0" * 64}
    )

    with pytest.raises(StructuralPilotError, match="source state"):
        create_structural_collection(
            client,
            plan,
            authorization,
            _provenance(),
        )

    assert client.create_calls == []
    assert client.payload_index_calls == []
    assert client.exists_calls == []


def test_create_rejects_receipt_collision_before_provider_call(
    tmp_path: Path,
) -> None:
    plan = _bound_plan(tmp_path)
    receipt_path = tmp_path / plan.run_id / "create-receipt.json"
    receipt_path.write_text("owned", encoding="utf-8")
    client = RecordingQdrantClient()

    with pytest.raises(StructuralPilotError, match="already exists"):
        create_structural_collection(
            client,
            plan,
            _authorization(plan),
            _provenance(),
            receipt_path=receipt_path,
        )

    assert client.create_calls == []


def test_create_cli_validates_binding_before_constructing_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _bound_plan(tmp_path)
    plan_path = tmp_path / plan.run_id / "plan.json"
    monkeypatch.setattr(
        run_structural_index_pilot,
        "create_structural_qdrant_client",
        lambda *_args, **_kwargs: pytest.fail("provider client constructed"),
        raising=False,
    )
    monkeypatch.setattr(
        run_structural_index_pilot,
        "collect_git_provenance",
        _provenance,
    )
    arguments = run_structural_index_pilot.build_parser().parse_args(
        [
            "create",
            "--plan",
            str(plan_path),
            "--plan-sha256",
            "0" * 64,
            "--source-state-sha256",
            plan.source_state_sha256,
            "--collection",
            "vietlex-legal-rag-v2-pilot-384",
            "--allow-remote-write",
        ]
    )

    with pytest.raises(StructuralPilotError, match="plan authorization"):
        run_structural_index_pilot.run(arguments)


def test_upload_cli_rejects_artifact_hash_before_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _bound_plan(tmp_path)
    create_path = tmp_path / "create.json"
    create_path.write_text("{}\n", encoding="utf-8")
    probe_path = tmp_path / "probe.json"
    probe_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(run_structural_index_pilot, "get_settings", _settings)
    monkeypatch.setattr(
        run_structural_index_pilot,
        "collect_git_provenance",
        _provenance,
    )
    monkeypatch.setattr(
        run_structural_index_pilot,
        "create_structural_qdrant_client",
        lambda *_args, **_kwargs: pytest.fail("provider client constructed"),
    )
    arguments = run_structural_index_pilot.build_parser().parse_args(
        [
            "upload",
            "--plan",
            str(tmp_path / plan.run_id / "plan.json"),
            "--create-receipt",
            str(create_path),
            "--create-receipt-sha256",
            "c" * 64,
            "--probe-report",
            str(probe_path),
            "--probe-report-sha256",
            "d" * 64,
            "--checkpoint",
            str(tmp_path / "checkpoint.sqlite3"),
            "--plan-sha256",
            plan.plan_sha256,
            "--source-state-sha256",
            plan.source_state_sha256,
            "--collection",
            plan.contract.collection_name,
            "--allow-remote-write",
        ]
    )

    with pytest.raises(StructuralPilotError, match="creation receipt SHA-256"):
        run_structural_index_pilot.run(arguments)


@pytest.mark.parametrize(
    ("command_name", "expected_exit"),
    [("audit", 0), ("plan", 3)],
)
def test_provider_free_cli_writes_audit_and_blocks_unproven_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command_name: str,
    expected_exit: int,
) -> None:
    import app.ingestion.structural_qdrant as structural_qdrant

    monkeypatch.setattr(run_structural_index_pilot, "get_settings", _settings)
    monkeypatch.setattr(
        run_structural_index_pilot,
        "ContentStore",
        lambda _path: FakeStore(),
    )
    monkeypatch.setattr(
        structural_qdrant,
        "create_structural_qdrant_client",
        lambda *_args, **_kwargs: pytest.fail("provider client constructed"),
    )
    arguments = run_structural_index_pilot.build_parser().parse_args(
        [
            command_name,
            "--output-root",
            str(tmp_path),
            "--run-id",
            f"cli-{command_name}",
        ]
    )

    assert run_structural_index_pilot.run(arguments) == expected_exit
    assert (tmp_path / f"cli-{command_name}" / "manifest.json").is_file()
    captured = capsys.readouterr()
    assert '"provider_calls": 0' in captured.out
    if command_name == "plan":
        assert "BLOCKED_CAPACITY" in captured.err


def _records():
    store = FakeStore()
    document_ids = select_structural_document_ids(store)
    return list(
        iter_structural_records(
            store,
            document_ids,
            repository="owner/legal-corpus",
            revision="revision-1",
            max_tokens=420,
            overlap_tokens=48,
        )
    )


def _completed_chain(tmp_path: Path, *, healthy: bool = True):
    plan = _bound_plan(tmp_path)
    client = RecordingQdrantClient(healthy=healthy)
    creation = create_structural_collection(
        client,
        plan,
        _authorization(plan),
        _provenance(),
    )
    client.points_count = plan.manifest.record_count
    creation_sha = "c" * 64
    probe_sha = "d" * 64
    upload_sha = "e" * 64
    probe = SimpleNamespace(
        acceptance="PASS_MODEL_PROBE",
        collection_name=plan.contract.collection_name,
        source_state_sha256=plan.source_state_sha256,
        plan_sha256=plan.plan_sha256,
        creation_receipt_sha256=creation_sha,
        dataset_revision=plan.manifest.dataset_revision,
        candidate_dense_model=plan.contract.dense_model,
        candidate_sparse_model=plan.contract.sparse_model,
    )
    upload = SimpleNamespace(
        status="UPLOAD_COMPLETE",
        collection_name=plan.contract.collection_name,
        source_state_sha256=plan.source_state_sha256,
        plan_sha256=plan.plan_sha256,
        creation_receipt_sha256=creation_sha,
        probe_report_sha256=probe_sha,
        dataset_revision=plan.manifest.dataset_revision,
        ordered_record_ids_sha256=plan.manifest.ordered_record_ids_sha256,
        manifest_record_count=plan.manifest.record_count,
        committed_total=plan.manifest.record_count,
        remaining_count=0,
        provider_usage={
            plan.contract.dense_model: 100,
        },
    )
    return (
        plan,
        client,
        creation,
        creation_sha,
        probe,
        probe_sha,
        upload,
        upload_sha,
    )


def test_finalize_requires_complete_hash_chain_before_provider_calls(
    tmp_path: Path,
) -> None:
    (
        plan,
        client,
        creation,
        creation_sha,
        probe,
        probe_sha,
        upload,
        upload_sha,
    ) = _completed_chain(tmp_path)
    calls_before = len(client.get_calls)

    with pytest.raises(StructuralPilotError, match="upload report binding"):
        finalize_structural_collection(
            client,
            plan,
            _authorization(plan),
            _provenance(),
            creation_receipt=creation,
            creation_receipt_sha256=creation_sha,
            probe_report=probe,
            probe_report_sha256=probe_sha,
            upload_report=SimpleNamespace(
                **{**vars(upload), "remaining_count": 1}
            ),
            upload_report_sha256=upload_sha,
        )

    assert len(client.get_calls) == calls_before
    assert client.update_calls == []


def test_finalize_activates_hnsw_and_records_exact_health(
    tmp_path: Path,
) -> None:
    (
        plan,
        client,
        creation,
        creation_sha,
        probe,
        probe_sha,
        upload,
        upload_sha,
    ) = _completed_chain(tmp_path)
    path = tmp_path / "finalize.json"

    receipt = finalize_structural_collection(
        client,
        plan,
        _authorization(plan),
        _provenance(),
        creation_receipt=creation,
        creation_receipt_sha256=creation_sha,
        probe_report=probe,
        probe_report_sha256=probe_sha,
        upload_report=upload,
        upload_report_sha256=upload_sha,
        receipt_path=path,
        poll_interval_seconds=0,
    )

    assert receipt.status == "PASS_FINALIZE"
    assert receipt.points_count == plan.manifest.record_count
    assert receipt.schema_readback is not None
    assert receipt.schema_readback.hnsw_m == 16
    assert receipt.provider_usage == upload.provider_usage
    assert client.update_calls == [
        {
            "collection_name": plan.contract.collection_name,
            "hnsw_config": models.HnswConfigDiff(m=16, on_disk=True),
            "timeout": int(plan.contract.timeout_seconds),
        }
    ]
    assert path.is_file()


def test_finalize_timeout_writes_blocked_receipt_without_cleanup(
    tmp_path: Path,
) -> None:
    (
        plan,
        client,
        creation,
        creation_sha,
        probe,
        probe_sha,
        upload,
        upload_sha,
    ) = _completed_chain(tmp_path, healthy=False)
    path = tmp_path / "blocked-finalize.json"

    receipt = finalize_structural_collection(
        client,
        plan,
        _authorization(plan),
        _provenance(),
        creation_receipt=creation,
        creation_receipt_sha256=creation_sha,
        probe_report=probe,
        probe_report_sha256=probe_sha,
        upload_report=upload,
        upload_report_sha256=upload_sha,
        receipt_path=path,
        max_polls=2,
        poll_interval_seconds=0,
    )

    assert receipt.status == "BLOCKED_TECHNICAL"
    assert receipt.technical_errors == {
        "finalize": "Qdrant finalize health poll timed out"
    }
    assert path.is_file()
    assert client.delete_calls == []


def _finalized_chain(tmp_path: Path, *, mutate_readback: str | None = None):
    chain = _completed_chain(tmp_path)
    (
        plan,
        client,
        creation,
        creation_sha,
        probe,
        probe_sha,
        upload,
        upload_sha,
    ) = chain
    finalize = finalize_structural_collection(
        client,
        plan,
        _authorization(plan),
        _provenance(),
        creation_receipt=creation,
        creation_receipt_sha256=creation_sha,
        probe_report=probe,
        probe_report_sha256=probe_sha,
        upload_report=upload,
        upload_report_sha256=upload_sha,
        poll_interval_seconds=0,
    )
    client.mutate_readback = mutate_readback
    if mutate_readback == "health":
        client.healthy = False
    client.records = {record.record_id: record for record in _records()}
    return (*chain, finalize, "f" * 64)


def test_verify_checks_exact_schema_count_hashes_payloads_and_vectors(
    tmp_path: Path,
) -> None:
    (
        plan,
        client,
        creation,
        creation_sha,
        probe,
        probe_sha,
        upload,
        upload_sha,
        finalize,
        finalize_sha,
    ) = _finalized_chain(tmp_path)
    path = tmp_path / "verify.json"

    receipt = verify_structural_collection(
        client,
        plan,
        _authorization(plan),
        _provenance(),
        iter(_records()),
        creation_receipt=creation,
        creation_receipt_sha256=creation_sha,
        probe_report=probe,
        probe_report_sha256=probe_sha,
        upload_report=upload,
        upload_report_sha256=upload_sha,
        finalize_receipt=finalize,
        finalize_receipt_sha256=finalize_sha,
        receipt_path=path,
        derived_sample_count=3,
    )

    assert receipt.status == "PASS_VERIFY"
    assert receipt.points_count == plan.manifest.record_count
    assert receipt.retrieved_sample_count == len(receipt.sample_record_ids)
    assert receipt.dense_vectors_validated == len(receipt.sample_record_ids)
    assert receipt.sparse_vectors_validated == len(receipt.sample_record_ids)
    assert receipt.sample_payload_sha256 is not None
    assert client.retrieve_calls[0]["with_payload"] is True
    assert client.retrieve_calls[0]["with_vectors"] is True
    assert path.is_file()


@pytest.mark.parametrize(
    "mutation",
    ["sample_payload", "sample_dense", "health"],
)
def test_verify_persists_typed_failure_without_remote_cleanup(
    tmp_path: Path,
    mutation: str,
) -> None:
    (
        plan,
        client,
        creation,
        creation_sha,
        probe,
        probe_sha,
        upload,
        upload_sha,
        finalize,
        finalize_sha,
    ) = _finalized_chain(tmp_path, mutate_readback=mutation)
    path = tmp_path / f"verify-{mutation}.json"

    receipt = verify_structural_collection(
        client,
        plan,
        _authorization(plan),
        _provenance(),
        iter(_records()),
        creation_receipt=creation,
        creation_receipt_sha256=creation_sha,
        probe_report=probe,
        probe_report_sha256=probe_sha,
        upload_report=upload,
        upload_report_sha256=upload_sha,
        finalize_receipt=finalize,
        finalize_receipt_sha256=finalize_sha,
        receipt_path=path,
        derived_sample_count=3,
    )

    assert receipt.status == "BLOCKED_TECHNICAL"
    assert "verify" in receipt.technical_errors
    assert "secret" not in path.read_text(encoding="utf-8").casefold()
    assert client.delete_calls == []


def test_verify_rejects_finalize_hash_chain_before_remote_read(
    tmp_path: Path,
) -> None:
    (
        plan,
        client,
        creation,
        creation_sha,
        probe,
        probe_sha,
        upload,
        upload_sha,
        finalize,
        _finalize_sha,
    ) = _finalized_chain(tmp_path)
    calls_before = len(client.get_calls)
    changed = CollectionFinalizeReceipt.model_validate(
        {
            **finalize.model_dump(mode="json"),
            "upload_report_sha256": "0" * 64,
        }
    )

    with pytest.raises(StructuralPilotError, match="finalize receipt binding"):
        verify_structural_collection(
            client,
            plan,
            _authorization(plan),
            _provenance(),
            iter(_records()),
            creation_receipt=creation,
            creation_receipt_sha256=creation_sha,
            probe_report=probe,
            probe_report_sha256=probe_sha,
            upload_report=upload,
            upload_report_sha256=upload_sha,
            finalize_receipt=changed,
            finalize_receipt_sha256="f" * 64,
        )

    assert len(client.get_calls) == calls_before


def test_verify_persists_local_source_drift_without_remote_read(
    tmp_path: Path,
) -> None:
    (
        plan,
        client,
        creation,
        creation_sha,
        probe,
        probe_sha,
        upload,
        upload_sha,
        finalize,
        finalize_sha,
    ) = _finalized_chain(tmp_path)
    calls_before = len(client.get_calls)
    path = tmp_path / "verify-source-drift.json"

    receipt = verify_structural_collection(
        client,
        plan,
        _authorization(plan),
        _provenance(),
        iter(_records()[:-1]),
        creation_receipt=creation,
        creation_receipt_sha256=creation_sha,
        probe_report=probe,
        probe_report_sha256=probe_sha,
        upload_report=upload,
        upload_report_sha256=upload_sha,
        finalize_receipt=finalize,
        finalize_receipt_sha256=finalize_sha,
        receipt_path=path,
        derived_sample_count=3,
    )

    assert receipt.status == "BLOCKED_TECHNICAL"
    assert receipt.provider_calls == 0
    assert receipt.technical_errors == {
        "local_source": "verification record count mismatch"
    }
    assert len(client.get_calls) == calls_before
    assert path.is_file()
