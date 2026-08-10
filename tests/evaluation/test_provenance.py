import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.evaluation.profiles import get_evaluation_profile
from app.evaluation.provenance import GitProvenance, collect_git_provenance
from app.evaluation.provider_catalog import (
    GENERATION_PROVIDER_MODELS,
    JUDGE_PROVIDER_MODELS,
)
from app.evaluation.run_manifest import (
    calculate_configuration_fingerprint,
    create_run_manifest,
)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def initialized_repo(tmp_path: Path) -> Path:
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "Test User")
    empty_excludes = tmp_path / ".git" / "empty-excludes"
    empty_excludes.write_text("", encoding="utf-8")
    git(tmp_path, "config", "core.excludesFile", str(empty_excludes))
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "docs/evaluation/preflight").mkdir(parents=True)
    (tmp_path / "docs/evaluation/preflight/result.json").write_text(
        "{}\n", encoding="utf-8"
    )
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "baseline")
    return tmp_path


def test_clean_repo_has_stable_source_state(tmp_path: Path) -> None:
    repo = initialized_repo(tmp_path)

    first = collect_git_provenance(repo)
    second = collect_git_provenance(repo)

    assert first.status == "ok"
    assert first.git_dirty is False
    assert first.source_state_sha256 == second.source_state_sha256


def test_generated_artifact_is_dirty_but_not_source_state(
    tmp_path: Path,
) -> None:
    repo = initialized_repo(tmp_path)
    clean = collect_git_provenance(repo)
    artifact = repo / "docs/evaluation/preflight/result.json"
    artifact.write_text('{"changed": true}\n', encoding="utf-8")

    dirty = collect_git_provenance(repo)

    assert dirty.git_dirty is True
    assert dirty.git_tracked_dirty is True
    assert dirty.git_diff_sha256 != clean.git_diff_sha256
    assert dirty.source_state_sha256 == clean.source_state_sha256


def test_index_pilot_artifact_is_dirty_but_not_source_state(
    tmp_path: Path,
) -> None:
    repo = initialized_repo(tmp_path)
    clean = collect_git_provenance(repo)
    artifact = repo / "docs/evaluation/index-pilots/run-001/plan.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"status": "planned"}\n', encoding="utf-8")

    dirty = collect_git_provenance(repo)

    assert dirty.git_dirty is True
    assert dirty.git_untracked_dirty is True
    assert dirty.git_diff_sha256 != clean.git_diff_sha256
    assert dirty.source_state_sha256 == clean.source_state_sha256


def test_status_ledger_is_dirty_but_not_self_referential_source_state(
    tmp_path: Path,
) -> None:
    repo = initialized_repo(tmp_path)
    status = repo / "docs/evaluation/CURRENT_STATUS.md"
    status.write_text("source: pending\n", encoding="utf-8")
    git(repo, "add", "docs/evaluation/CURRENT_STATUS.md")
    git(repo, "commit", "-m", "add status ledger")
    clean = collect_git_provenance(repo)

    status.write_text("source: abc123\n", encoding="utf-8")
    ledger_dirty = collect_git_provenance(repo)

    assert ledger_dirty.git_dirty is True
    assert ledger_dirty.source_state_sha256 == clean.source_state_sha256

    (repo / "README.md").write_text("runtime docs changed\n", encoding="utf-8")
    source_dirty = collect_git_provenance(repo)
    assert source_dirty.source_state_sha256 != clean.source_state_sha256


def test_untracked_env_is_dirty_but_secret_content_is_never_hashed(
    tmp_path: Path,
) -> None:
    repo = initialized_repo(tmp_path)
    clean = collect_git_provenance(repo)
    (repo / ".env.local").write_text(
        "API_KEY=do-not-read-or-hash\n", encoding="utf-8"
    )

    dirty = collect_git_provenance(repo)

    assert dirty.git_dirty is True
    assert dirty.git_untracked_dirty is True
    assert dirty.source_state_sha256 == clean.source_state_sha256
    assert dirty.git_diff_sha256 is None
    assert dirty.git_diff_status == "redacted"
    assert dirty.git_diff_reason == "sensitive_content_not_hashed"
    assert "do-not-read-or-hash" not in dirty.model_dump_json()


def test_staged_and_untracked_source_changes_affect_source_state(
    tmp_path: Path,
) -> None:
    repo = initialized_repo(tmp_path)
    clean = collect_git_provenance(repo)
    (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    git(repo, "add", "app.py")
    (repo / "new_test.py").write_text("assert True\n", encoding="utf-8")

    dirty = collect_git_provenance(repo)

    assert dirty.git_dirty is True
    assert dirty.git_staged_dirty is True
    assert dirty.git_untracked_dirty is True
    assert dirty.source_state_sha256 != clean.source_state_sha256


def test_non_git_directory_is_typed_unavailable(tmp_path: Path) -> None:
    provenance = collect_git_provenance(tmp_path)

    assert provenance.status == "unavailable"
    assert provenance.git_dirty is False
    assert provenance.source_state_sha256 is None
    assert provenance.error


def test_provider_catalog_preserves_current_fallback_orders() -> None:
    assert [
        (item.provider, item.model) for item in GENERATION_PROVIDER_MODELS
    ] == [
        ("OpenRouter", "meta-llama/llama-3.3-70b-instruct"),
        ("Gemini", "gemini-2.0-flash"),
        ("NVIDIA NIM", "meta/llama-3.3-70b-instruct"),
        ("Groq", "llama-3.3-70b-versatile"),
        ("OpenRouter", "meta-llama/llama-3.3-70b-instruct"),
        ("Gemini", "gemini-1.5-flash"),
        ("Groq", "llama3-8b-8192"),
    ]
    assert [
        (item.provider, item.model) for item in JUDGE_PROVIDER_MODELS
    ] == [
        ("Gemini", "gemini-2.0-flash"),
        ("NVIDIA NIM", "meta/llama-3.3-70b-instruct"),
        ("Groq", "llama-3.3-70b-versatile"),
        ("OpenRouter", "meta-llama/llama-3.3-70b-instruct"),
        ("OmniGate", "legal-core-model"),
    ]


def settings() -> SimpleNamespace:
    return SimpleNamespace(
        DATASET_REVISION="namsyntax-420-v1",
        DENSE_INFERENCE_MODEL="intfloat/multilingual-e5-small",
        QDRANT_RERANK_MODEL="answerdotai/answerai-colbert-small-v1",
        PINECONE_RERANK_MODEL="bge-reranker-v2-m3",
    )


def fixed_provenance(tmp_path: Path) -> GitProvenance:
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


def build_manifest(
    tmp_path: Path,
    *,
    eval_mode: str,
    judge_mode: str,
):
    dataset = tmp_path / "dataset.json"
    dataset.write_text("[]\n", encoding="utf-8")
    selected_ids_sha = hashlib.sha256(b"[]").hexdigest()
    with patch(
        "app.evaluation.run_manifest.collect_git_provenance",
        return_value=fixed_provenance(tmp_path),
    ):
        return create_run_manifest(
            run_id="run_001",
            eval_mode=eval_mode,
            judge_mode=judge_mode,
            guardrail_mode="off",
            rewrite_mode="off",
            reranker_provider="current",
            dataset_path=dataset,
            settings=settings(),
            command_str="python run_retrieval_eval.py",
            profile_name="separated_intent",
            profile_obj=get_evaluation_profile("separated_intent"),
            gold_policy="all-required-verified",
            selected_case_ids=[],
            selected_case_ids_sha256=selected_ids_sha,
        )


def assert_manifest_is_public_and_self_consistent(manifest) -> None:
    serialized = manifest.model_dump_json()
    assert "observed_provider_models" not in type(manifest).model_fields
    assert manifest.configuration_fingerprint == (
        calculate_configuration_fingerprint(manifest.configuration)
    )
    for forbidden in ("API_KEY", "api_key", "base_url", "Authorization"):
        assert forbidden not in serialized


def test_retrieval_manifest_records_only_configured_public_models(
    tmp_path: Path,
) -> None:
    manifest = build_manifest(
        tmp_path,
        eval_mode="retrieval-only",
        judge_mode="none",
    )

    assert manifest.configured_provider_models == {
        "dense": {
            "provider": "qdrant-cloud-staging",
            "model": "intfloat/multilingual-e5-small",
        },
        "reranker_primary": {
            "provider": "qdrant",
            "model": "answerdotai/answerai-colbert-small-v1",
        },
        "reranker_fallback": {
            "provider": "pinecone",
            "model": "bge-reranker-v2-m3",
        },
        "generation": {"mode": "not_applicable", "candidates": []},
        "judge": {"mode": "none", "candidates": []},
    }
    assert_manifest_is_public_and_self_consistent(manifest)


def test_answer_manifest_records_full_configured_fallback_catalog(
    tmp_path: Path,
) -> None:
    manifest = build_manifest(
        tmp_path,
        eval_mode="answer",
        judge_mode="ragas",
    )

    assert manifest.configured_provider_models["generation"] == {
        "mode": "configured_fallback_chain",
        "candidates": [
            {"provider": item.provider, "model": item.model}
            for item in GENERATION_PROVIDER_MODELS
        ],
    }
    assert manifest.configured_provider_models["judge"] == {
        "mode": "ragas",
        "candidates": [
            {"provider": item.provider, "model": item.model}
            for item in JUDGE_PROVIDER_MODELS
        ],
    }
    assert_manifest_is_public_and_self_consistent(manifest)


def test_manifest_rejects_selected_case_hash_mismatch(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text("[]\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="selected_case_ids_sha256 does not match selected_case_ids",
    ):
        create_run_manifest(
            run_id="run_001",
            eval_mode="retrieval-only",
            judge_mode="none",
            guardrail_mode="off",
            rewrite_mode="off",
            reranker_provider="current",
            dataset_path=dataset,
            settings=settings(),
            command_str="python run_retrieval_eval.py",
            profile_name="separated_intent",
            profile_obj=get_evaluation_profile("separated_intent"),
            gold_policy="all-required-verified",
            selected_case_ids=[],
            selected_case_ids_sha256="0" * 64,
        )
