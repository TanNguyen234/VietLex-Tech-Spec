from __future__ import annotations

from pathlib import Path


def test_artifact_policy_reports_large_files_and_operational_data(
    tmp_path: Path,
) -> None:
    from scripts.check_repository_artifacts import audit_repository_artifacts

    large = tmp_path / "docs/evaluation/runs/run/raw.json"
    large.parent.mkdir(parents=True)
    large.write_bytes(b"x" * 101)
    checkpoint = tmp_path / "data/migration/checkpoint.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text("{}", encoding="utf-8")

    violations = audit_repository_artifacts(
        tmp_path,
        files=[large, checkpoint],
        max_file_bytes=100,
        max_run_bytes=200,
    )

    assert [(item.kind, item.path) for item in violations] == [
        ("oversized_file", "docs/evaluation/runs/run/raw.json"),
        ("operational_data", "data/migration/checkpoint.json"),
    ]


def test_artifact_policy_detects_secret_assignments(tmp_path: Path) -> None:
    from scripts.check_repository_artifacts import audit_repository_artifacts

    source = tmp_path / "settings.txt"
    source.write_text(
        "SUPABASE_" "SERVICE_ROLE_KEY=secret-value\n"
        "Authorization: Bearer " "abcdefghijklmnopqrstuvwxyz",
        encoding="utf-8",
    )

    violations = audit_repository_artifacts(tmp_path, files=[source])

    assert [item.kind for item in violations] == ["secret", "secret"]
    assert all(item.path == "settings.txt" for item in violations)


def test_artifact_policy_allows_empty_example_assignments(tmp_path: Path) -> None:
    from scripts.check_repository_artifacts import audit_repository_artifacts

    source = tmp_path / ".env.example"
    source.write_text(
        "QDRANT_API_KEY=\nQDRANT_COLLECTION=example\n",
        encoding="utf-8",
    )

    assert audit_repository_artifacts(tmp_path, files=[source]) == []


def test_manifest_accepts_hashed_artifact_metadata() -> None:
    from app.evaluation.schemas import EvaluationRunManifest

    manifest = EvaluationRunManifest(
        run_id="run",
        utc_timestamp="2026-08-27T00:00:00Z",
        git_sha="abc",
        dataset_revision="rev",
        dataset_sha256="dataset",
        configuration_fingerprint="config",
        command="pytest",
        eval_mode="retrieval-only",
        judge_mode="none",
        guardrail_mode="off",
        rewrite_mode="off",
        reranker_provider="current",
        artifact_files=[
            {
                "path": "summary.json",
                "sha256": "a" * 64,
                "bytes": 12,
                "storage": "git",
            }
        ],
    )

    assert manifest.artifact_files[0].sha256 == "a" * 64
