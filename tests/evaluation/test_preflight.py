import dataclasses
import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import run_retrieval_eval
from app.evaluation.artifact_io import (
    ArtifactCollisionError,
    write_immutable_json,
)
from app.evaluation.case_selection import CaseSelectionResult
from app.evaluation.preflight import (
    build_preflight_batch,
    persist_preflight_batch,
)
from app.evaluation.profiles import get_evaluation_profile
from app.evaluation.provenance import GitProvenance


def test_immutable_json_reuses_identical_bytes(tmp_path: Path) -> None:
    target = tmp_path / "artifact.json"

    assert write_immutable_json(target, {"value": 1}) == "created"
    first = target.read_bytes()
    assert write_immutable_json(target, {"value": 1}) == "reused"
    assert target.read_bytes() == first


def test_immutable_json_rejects_different_payload(tmp_path: Path) -> None:
    target = tmp_path / "artifact.json"
    write_immutable_json(target, {"value": 1})

    with pytest.raises(ArtifactCollisionError) as captured:
        write_immutable_json(target, {"value": 2})

    assert captured.value.status == "artifact_collision"
    assert json.loads(target.read_text(encoding="utf-8")) == {"value": 1}


def zero_selection() -> CaseSelectionResult:
    return CaseSelectionResult(
        gold_policy="all-required-verified",
        selected_cases=[],
        selected_case_ids=[],
        selected_case_ids_sha256="e" * 64,
        total_candidate_cases=420,
        selected_case_count=0,
        excluded_no_verified_label_count=245,
        excluded_unanswerable_count=175,
    )


def clean_provenance(tmp_path: Path) -> GitProvenance:
    return GitProvenance(
        status="ok",
        repository_root=str(tmp_path),
        git_sha="a" * 40,
        git_dirty=False,
        git_tracked_dirty=False,
        git_staged_dirty=False,
        git_untracked_dirty=False,
        git_diff_sha256=None,
        git_diff_status="clean",
        source_state_sha256="b" * 64,
    )


def profiles(*, rewrite_mode: str = "off"):
    return [
        dataclasses.replace(
            get_evaluation_profile(name),
            rewrite_mode=rewrite_mode,
        )
        for name in (
            "legacy",
            "separated_no_intent",
            "separated_intent",
        )
    ]


def _write_validation_inputs(tmp_path: Path) -> tuple[Path, Path]:
    dataset_path = tmp_path / "dataset.json"
    sidecar_path = tmp_path / "promoted-sidecar.json"
    dataset_path.write_text(
        json.dumps(
            [
                {
                    "question": "Quy định áp dụng là gì?",
                    "question_type": "factoid",
                    "ground_truth_answer": "Có căn cứ pháp luật.",
                    "ground_truth_context": ["Điều 1 văn bản 1/2026/QH15."],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    sidecar_path.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "dataset_name": "promoted-test",
                "total_cases": 1,
                "total_evidence_items": 1,
                "labels": [
                    {
                        "evidence_item_id": "case_001_ctx01_cit01",
                        "case_id": "case_001",
                        "required": True,
                        "required_level": "document",
                        "status": "verified",
                        "document_id": 1,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return dataset_path, sidecar_path


def test_custom_sidecar_validation_does_not_require_unrelated_audit_summary(
    tmp_path: Path,
) -> None:
    # Break caught: a custom promoted sidecar is compared with the legacy
    # default audit summary and rejected before the live evaluation starts.
    dataset_path, sidecar_path = _write_validation_inputs(tmp_path)

    all_cases, selection, sidecar, audit_summary = (
        run_retrieval_eval.perform_pre_execution_validation(
            dataset_path=dataset_path,
            sidecar_path=sidecar_path,
            summary_path=None,
            gold_policy="all-required-verified",
            verified_only=True,
            require_clean_git=False,
        )
    )

    assert len(all_cases) == 1
    assert selection.selected_case_ids == ["case_001"]
    assert sidecar.metadata.total_evidence_items == 1
    assert audit_summary == {}


def test_explicit_audit_summary_option_remains_fail_closed(
    tmp_path: Path,
) -> None:
    # Break caught: selecting a custom sidecar silently ignores an explicitly
    # requested, mismatched audit summary.
    dataset_path, sidecar_path = _write_validation_inputs(tmp_path)
    summary_path = tmp_path / "audit-summary.json"
    summary_path.write_text(
        json.dumps({"total_evidence_items": 2}),
        encoding="utf-8",
    )
    arguments = run_retrieval_eval.build_parser().parse_args(
        ["--audit-summary", str(summary_path)]
    )

    assert arguments.audit_summary == summary_path
    with pytest.raises(ValueError, match="Counter mismatch"):
        run_retrieval_eval.perform_pre_execution_validation(
            dataset_path=dataset_path,
            sidecar_path=sidecar_path,
            summary_path=arguments.audit_summary,
            gold_policy="all-required-verified",
            verified_only=True,
            require_clean_git=False,
        )


def test_explicit_missing_audit_summary_is_rejected(tmp_path: Path) -> None:
    # Break caught: a misspelled explicit audit-summary path is silently
    # ignored, creating a false impression that its counters were checked.
    dataset_path, sidecar_path = _write_validation_inputs(tmp_path)

    with pytest.raises(FileNotFoundError, match="Audit summary file not found"):
        run_retrieval_eval.perform_pre_execution_validation(
            dataset_path=dataset_path,
            sidecar_path=sidecar_path,
            summary_path=tmp_path / "missing-summary.json",
            gold_policy="all-required-verified",
            verified_only=True,
            require_clean_git=False,
        )


def batch_payload(
    tmp_path: Path,
    *,
    rewrite_mode: str = "off",
    provenance: GitProvenance | None = None,
):
    return build_preflight_batch(
        profiles=profiles(rewrite_mode=rewrite_mode),
        selection=zero_selection(),
        provenance=provenance or clean_provenance(tmp_path),
        dataset_sha256="d" * 64,
        dataset_revision="namsyntax-420-v1",
        sidecar_sha256="s" * 64,
        gold_policy="all-required-verified",
        verified_only=True,
        artifact_prefix=PurePosixPath("docs/evaluation/preflight"),
    )


def test_preflight_batch_has_three_profiles_and_portable_paths(
    tmp_path: Path,
) -> None:
    provenance = clean_provenance(tmp_path)
    payload = batch_payload(tmp_path, provenance=provenance)

    assert set(payload["profiles"]) == {
        "legacy",
        "separated_no_intent",
        "separated_intent",
    }
    assert payload["meta"]["batch_status"] == "BLOCKED"
    assert payload["meta"]["status_code"] == "preflight_blocked"
    assert payload["meta"]["blocked_reason"] == (
        "selected_case_count_is_zero_under_verified_only"
    )
    assert "profile_name" not in payload["meta"]
    assert payload["meta"]["provider_calls"] == 0
    assert {
        profile["source_state_sha256"]
        for profile in payload["profiles"].values()
    } == {provenance.source_state_sha256}
    for profile in payload["profiles"].values():
        path = profile["canonical_artifact_path"]
        assert "\\" not in path
        assert not Path(path).is_absolute()


def test_preflight_persistence_is_complete_and_reusable(
    tmp_path: Path,
) -> None:
    payload = batch_payload(tmp_path)
    output_dir = tmp_path / "preflight"

    first = persist_preflight_batch(payload=payload, output_dir=output_dir)
    first_bytes = {path: path.read_bytes() for path, _ in first}
    second = persist_preflight_batch(payload=payload, output_dir=output_dir)

    assert len(first) == 4
    assert [status for _, status in first] == ["created"] * 4
    assert [status for _, status in second] == ["reused"] * 4
    assert {path: path.read_bytes() for path, _ in second} == first_bytes
    assert sum("comparison" in path.name for path, _ in first) == 1


def test_preflight_batch_collision_creates_no_partial_artifacts(
    tmp_path: Path,
) -> None:
    payload = batch_payload(tmp_path)
    output_dir = tmp_path / "preflight"
    output_dir.mkdir()
    first_profile = next(iter(payload["profiles"].values()))
    collision = output_dir / PurePosixPath(
        first_profile["canonical_artifact_path"]
    ).name
    collision.write_text('{"different": true}\n', encoding="utf-8")

    with pytest.raises(ArtifactCollisionError):
        persist_preflight_batch(payload=payload, output_dir=output_dir)

    assert list(output_dir.iterdir()) == [collision]


def test_preflight_configuration_change_gets_new_identity(
    tmp_path: Path,
) -> None:
    off_payload = batch_payload(tmp_path, rewrite_mode="off")
    on_payload = batch_payload(tmp_path, rewrite_mode="on")
    output_dir = tmp_path / "preflight"

    off_paths = persist_preflight_batch(
        payload=off_payload,
        output_dir=output_dir,
    )
    on_paths = persist_preflight_batch(
        payload=on_payload,
        output_dir=output_dir,
    )
    off_comparison = next(
        path for path, _ in off_paths if "comparison" in path.name
    )
    on_comparison = next(
        path for path, _ in on_paths if "comparison" in path.name
    )

    assert (
        off_payload["meta"]["batch_configuration_fingerprint"]
        != on_payload["meta"]["batch_configuration_fingerprint"]
    )
    assert off_comparison.name != on_comparison.name


def test_unavailable_provenance_builds_blocked_diagnostic_payload(
    tmp_path: Path,
) -> None:
    unavailable = GitProvenance(
        status="unavailable",
        error="RuntimeError: git unavailable",
        repository_root=str(tmp_path),
        git_sha="unknown_git_sha",
        git_dirty=False,
        git_tracked_dirty=False,
        git_staged_dirty=False,
        git_untracked_dirty=False,
        git_diff_sha256=None,
        git_diff_status="unavailable",
        git_diff_reason="git_command_failed",
        source_state_sha256=None,
    )

    payload = batch_payload(tmp_path, provenance=unavailable)
    persisted = persist_preflight_batch(
        payload=payload,
        output_dir=tmp_path / "preflight",
    )

    assert payload["meta"]["batch_status"] == "BLOCKED"
    assert payload["meta"]["blocked_reason"] == "provenance_unavailable"
    assert {
        profile["source_state_sha256"]
        for profile in payload["profiles"].values()
    } == {None}
    assert len(persisted) == 4


@pytest.mark.asyncio
async def test_cli_preflight_blocks_without_calling_providers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    dataset = tmp_path / "dataset.json"
    sidecar_path = tmp_path / "sidecar.json"
    dataset.write_text("[]\n", encoding="utf-8")
    sidecar_path.write_text("{}\n", encoding="utf-8")
    output_dir = tmp_path / "docs/evaluation/preflight"
    selection = zero_selection()
    sidecar = SimpleNamespace(
        metadata=SimpleNamespace(sidecar_sha256="s" * 64)
    )
    arguments = run_retrieval_eval.build_parser().parse_args(
        [
            "--dataset",
            str(dataset),
            "--sidecar",
            str(sidecar_path),
            "--preflight-all-profiles",
            "--verified-only",
            "--preflight-output-dir",
            str(output_dir),
        ]
    )
    monkeypatch.setattr(run_retrieval_eval, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        run_retrieval_eval,
        "get_settings",
        lambda: SimpleNamespace(DATASET_REVISION="namsyntax-420-v1"),
    )
    monkeypatch.setattr(
        run_retrieval_eval,
        "perform_pre_execution_validation",
        lambda **_kwargs: ([], selection, sidecar, {}),
    )

    with (
        patch(
            "run_retrieval_eval.collect_git_provenance",
            return_value=clean_provenance(tmp_path),
        ) as provenance_call,
        patch(
            "app.services.retrieval.get_legal_retriever",
            side_effect=AssertionError("provider called"),
        ) as provider_factory,
        pytest.raises(SystemExit) as captured,
    ):
        await run_retrieval_eval.run_retrieval_evaluation(arguments)

    assert captured.value.code == 1
    provenance_call.assert_called_once_with(tmp_path)
    provider_factory.assert_not_called()
    comparison = next(output_dir.glob("preflight_comparison_*.json"))
    data = json.loads(comparison.read_text(encoding="utf-8"))
    assert data["meta"]["provider_calls"] == 0
    assert len(data["profiles"]) == 3


@pytest.mark.asyncio
async def test_cli_preflight_rejects_output_outside_project(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    dataset = project_root / "dataset.json"
    sidecar_path = project_root / "sidecar.json"
    dataset.write_text("[]\n", encoding="utf-8")
    sidecar_path.write_text("{}\n", encoding="utf-8")
    outside = tmp_path / "outside"
    selection = zero_selection()
    sidecar = SimpleNamespace(
        metadata=SimpleNamespace(sidecar_sha256="s" * 64)
    )
    arguments = run_retrieval_eval.build_parser().parse_args(
        [
            "--dataset",
            str(dataset),
            "--sidecar",
            str(sidecar_path),
            "--preflight",
            "--verified-only",
            "--preflight-output-dir",
            str(outside),
        ]
    )
    monkeypatch.setattr(run_retrieval_eval, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(
        run_retrieval_eval,
        "get_settings",
        lambda: SimpleNamespace(DATASET_REVISION="namsyntax-420-v1"),
    )
    monkeypatch.setattr(
        run_retrieval_eval,
        "perform_pre_execution_validation",
        lambda **_kwargs: ([], selection, sidecar, {}),
    )

    with (
        patch("run_retrieval_eval.persist_preflight_batch") as persist,
        pytest.raises(
            ValueError,
            match="must remain inside the repository",
        ),
    ):
        await run_retrieval_eval.run_retrieval_evaluation(arguments)

    persist.assert_not_called()
