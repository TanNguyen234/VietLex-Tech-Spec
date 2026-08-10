from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import run_structural_index_pilot
from app.config import Settings
from app.evaluation.provenance import GitProvenance
from app.ingestion.content_store import StoredDocument
from app.ingestion.legal_text import DocumentMetadata
from app.ingestion.structural_pilot import (
    CapacityEnvelope,
    RemoteWriteAuthorization,
    StructuralPilotError,
    audit_structural_corpus,
    build_structural_pilot_plan,
    estimate_capacity,
    load_bound_plan,
    validate_remote_write_authorization,
)


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
        "collection_name": "vietlex-legal-rag-v2-pilot",
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
        collection_name="vietlex-legal-rag-v2-pilot",
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
        collection_name="vietlex-legal-rag-v2-pilot",
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
        "collection_name": "vietlex-legal-rag-v2-pilot",
        "plan_sha256": "a" * 64,
        "source_state_sha256": "b" * 64,
    }
    payload.update(values)
    with pytest.raises(ValidationError):
        RemoteWriteAuthorization(**payload)


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
