import hashlib
import os
import stat
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
    build_run_configuration,
    calculate_configuration_fingerprint,
    calculate_dataset_sha256,
    create_run_manifest,
)


def test_dataset_sha256_is_stable_across_checkout_line_endings(
    tmp_path: Path,
) -> None:
    lf_dataset = tmp_path / "lf.json"
    crlf_dataset = tmp_path / "crlf.json"
    lf_dataset.write_bytes(b"[\n]\n")
    crlf_dataset.write_bytes(b"[\r\n]\r\n")

    assert calculate_dataset_sha256(lf_dataset) == (
        "3fbbd4c6d76130399b0c79cdf41758669224a91e05b7b216953f0c9728750865"
    )
    assert calculate_dataset_sha256(crlf_dataset) == (
        "3fbbd4c6d76130399b0c79cdf41758669224a91e05b7b216953f0c9728750865"
    )


def test_structural_run_configuration_records_effective_backend() -> None:
    configured = build_run_configuration(
        profile_name="separated_intent",
        profile={},
        eval_mode="retrieval-only",
        judge_mode="none",
        guardrail_mode="off",
        rewrite_mode="off",
        reranker_provider="current",
        gold_policy="all-required-verified",
        selected_case_ids=[],
        selected_case_ids_sha256=hashlib.sha256(b"[]").hexdigest(),
        settings=SimpleNamespace(
            STRUCTURAL_BACKEND_ENABLED=True,
            CROSS_LANE_FINAL_RERANK_ENABLED=False,
            STRUCTURAL_COLLECTION_NAME="vietlex-legal-rag-v2-pilot-384",
            STRUCTURAL_DENSE_MODEL="intfloat/multilingual-e5-small",
            STRUCTURAL_SPARSE_MODEL="qdrant/bm25",
            STRUCTURAL_RERANKER_MODE="pinecone-only",
            STRUCTURAL_DENSE_TOP_K=48,
            STRUCTURAL_BM25_TOP_K=48,
            STRUCTURAL_FUSED_LIMIT=64,
            STRUCTURAL_RERANK_INPUT_LIMIT=64,
            STRUCTURAL_RERANK_RETURN_LIMIT=6,
            STRUCTURAL_FINAL_EVIDENCE_LIMIT=5,
            DENSE_INFERENCE_MODEL="intfloat/multilingual-e5-small",
            QDRANT_RERANK_MODEL="answerdotai/answerai-colbert-small-v1",
            PINECONE_RERANK_MODEL="bge-reranker-v2-m3",
            VERTEX_LLM_MODEL="gemini-3.5-flash",
        ),
    )

    assert configured["retrieval_runtime"] == {
        "backend": "qdrant_structural_v2",
        "collection": "vietlex-legal-rag-v2-pilot-384",
        "dense_model": "intfloat/multilingual-e5-small",
        "sparse_model": "qdrant/bm25",
        "reranker_mode": "pinecone-only",
        "dense_top_k": 48,
        "bm25_top_k": 48,
        "fused_limit": 64,
        "rerank_input_limit": 64,
        "rerank_return_limit": 6,
        "final_evidence_limit": 5,
        "cross_lane_final_rerank_enabled": False,
        "cross_lane_final_reranker": "pinecone:bge-reranker-v2-m3",
        "fallback_backend": "pinecone_v1",
    }
    assert configured["configured_provider_models"]["dense"] == {
        "provider": "qdrant-structural-collection",
        "model": "intfloat/multilingual-e5-small",
    }
    assert configured["configured_provider_models"]["reranker_primary"] == {
        "provider": "pinecone",
        "model": "bge-reranker-v2-m3",
    }
    assert configured["configured_provider_models"]["reranker_fallback"] == {
        "provider": "qdrant-via-pinecone-v1-fallback",
        "model": "answerdotai/answerai-colbert-small-v1",
    }


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


def create_symlink_or_skip(
    link: Path,
    target: Path,
    *,
    target_is_directory: bool = False,
) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"symlink creation is unavailable: {error}")


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


def test_missing_tracked_source_is_skipped_while_deletion_stays_dirty(
    tmp_path: Path,
) -> None:
    repo = initialized_repo(tmp_path)
    (repo / "app.py").unlink()

    provenance = collect_git_provenance(repo)

    assert provenance.status == "ok"
    assert provenance.git_dirty is True
    assert provenance.git_tracked_dirty is True
    assert provenance.git_diff_status == "ok"
    assert provenance.git_diff_sha256 is not None
    assert provenance.source_state_sha256 is not None


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


def test_tracked_env_example_is_a_hashable_template(tmp_path: Path) -> None:
    repo = initialized_repo(tmp_path)
    template = repo / ".env.example"
    template.write_text("PROJECT=placeholder\n", encoding="utf-8")
    git(repo, "add", ".env.example")
    git(repo, "commit", "-m", "add environment template")
    template.write_text("PROJECT=example-project\n", encoding="utf-8")

    dirty = collect_git_provenance(repo)

    assert dirty.git_dirty is True
    assert dirty.git_diff_status == "ok"
    assert dirty.git_diff_sha256 is not None
    assert dirty.git_diff_reason is None


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


def test_source_state_is_content_stable_across_git_index_transitions(
    tmp_path: Path,
) -> None:
    repo = initialized_repo(tmp_path)
    baseline = collect_git_provenance(repo)
    source = repo / "new_source.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")

    untracked = collect_git_provenance(repo)
    git(repo, "add", "new_source.py")
    staged = collect_git_provenance(repo)
    git(repo, "commit", "-m", "add equivalent source")
    committed = collect_git_provenance(repo)

    assert untracked.source_state_sha256 != baseline.source_state_sha256
    assert untracked.source_state_sha256 == staged.source_state_sha256
    assert staged.source_state_sha256 == committed.source_state_sha256


def test_symlink_hashes_target_name_without_reading_target_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    repo = initialized_repo(repo)
    target = tmp_path / "private-payload.txt"
    target.write_text("secret payload one\n", encoding="utf-8")
    alternate_target = tmp_path / "other-private-payload.txt"
    alternate_target.write_text("secret payload one\n", encoding="utf-8")
    link = repo / "linked_source.py"
    create_symlink_or_skip(link, target)

    original_read_bytes = Path.read_bytes
    original_open = Path.open

    def forbid_link_and_target_reads(path: Path) -> bytes:
        if path in {link, target, alternate_target}:
            raise AssertionError("provenance must not read a link target payload")
        return original_read_bytes(path)

    def forbid_link_and_target_open(path: Path, *args, **kwargs):
        if path in {link, target, alternate_target}:
            raise AssertionError("provenance must not open a link target payload")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", forbid_link_and_target_reads)
    monkeypatch.setattr(Path, "open", forbid_link_and_target_open)
    first = collect_git_provenance(repo)
    with original_open(target, "w", encoding="utf-8") as target_file:
        target_file.write("secret payload two\n")
    after_payload_change = collect_git_provenance(repo)

    assert first.status == "ok"
    assert after_payload_change.status == "ok"
    assert first.git_diff_sha256 == after_payload_change.git_diff_sha256
    assert first.source_state_sha256 == after_payload_change.source_state_sha256

    link.unlink()
    create_symlink_or_skip(link, alternate_target)
    after_target_change = collect_git_provenance(repo)

    assert after_target_change.status == "ok"
    assert after_target_change.git_diff_sha256 != first.git_diff_sha256
    assert after_target_change.source_state_sha256 != first.source_state_sha256


def test_regular_file_and_symlink_with_same_bytes_have_distinct_hashes(
    tmp_path: Path,
) -> None:
    repo = initialized_repo(tmp_path)
    target = Path("payload.txt")
    (repo / target).write_text("target payload\n", encoding="utf-8")
    link = repo / "entry.py"
    target_bytes = os.fsencode(target.as_posix())
    link.write_bytes(target_bytes)

    regular_file = collect_git_provenance(repo)
    link.unlink()
    create_symlink_or_skip(link, target)
    assert os.fsencode(os.readlink(link)) == target_bytes

    symlink = collect_git_provenance(repo)

    assert regular_file.status == "ok"
    assert symlink.status == "ok"
    assert regular_file.source_state_sha256 != symlink.source_state_sha256
    assert regular_file.git_diff_sha256 != symlink.git_diff_sha256


def test_dangling_symlink_hashes_link_target_without_following_it(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    repo = initialized_repo(repo)
    link = repo / "dangling_source.py"
    create_symlink_or_skip(link, tmp_path / "missing-private-source.py")

    provenance = collect_git_provenance(repo)

    assert provenance.status == "ok"
    assert provenance.git_dirty is True
    assert provenance.git_untracked_dirty is True
    assert provenance.git_diff_sha256 is not None
    assert provenance.source_state_sha256 is not None


def test_windows_reparse_point_is_hashed_as_link_target_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = initialized_repo(tmp_path)
    junction = repo / "external_junction"
    junction.write_text("placeholder must not be read", encoding="utf-8")
    reparse_stat = SimpleNamespace(
        st_mode=stat.S_IFDIR,
        st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
        st_reparse_tag=getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003),
    )
    original_lstat = Path.lstat

    def fake_lstat(path: Path, *args, **kwargs):
        if path == junction:
            return reparse_stat
        return original_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    monkeypatch.setattr(os, "readlink", lambda _path: r"D:\external\legal-source")
    original_read_bytes = Path.read_bytes
    original_open = Path.open

    def forbid_junction_payload_read(path: Path) -> bytes:
        if path == junction:
            raise AssertionError("provenance must not read a reparse-point target")
        return original_read_bytes(path)

    def forbid_junction_open(path: Path, *args, **kwargs):
        if path == junction:
            raise AssertionError("provenance must not open a reparse-point target")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", forbid_junction_payload_read)
    monkeypatch.setattr(Path, "open", forbid_junction_open)

    provenance = collect_git_provenance(repo)

    assert provenance.status == "ok"
    assert provenance.git_untracked_dirty is True
    assert provenance.git_diff_sha256 is not None
    assert provenance.source_state_sha256 is not None


def test_unreadable_regular_source_remains_typed_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = initialized_repo(tmp_path)
    source = repo / "app.py"
    original_open = Path.open

    def reject_source_open(path: Path, *args, **kwargs):
        if path == source:
            raise PermissionError("source access denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_source_open)

    provenance = collect_git_provenance(repo)

    assert provenance.status == "unavailable"
    assert provenance.error == "PermissionError: source access denied"
    assert provenance.git_diff_status == "unavailable"
    assert provenance.source_state_sha256 is None


def test_non_git_directory_is_typed_unavailable(tmp_path: Path, monkeypatch) -> None:
    # --basetemp may be inside the checkout. Do not discover its parent repo.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
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
        ("Groq", "qwen/qwen3.8-27b"),
        ("OpenRouter", "meta-llama/llama-3.3-70b-instruct"),
        ("Gemini", "gemini-1.5-flash"),
        ("Groq", "llama3-8b-8192"),
    ]
    assert [
        (item.provider, item.model) for item in JUDGE_PROVIDER_MODELS
    ] == [
        ("Gemini", "gemini-2.0-flash"),
        ("NVIDIA NIM", "meta/llama-3.3-70b-instruct"),
        ("Groq", "qwen/qwen3.8-27b"),
        ("OpenRouter", "meta-llama/llama-3.3-70b-instruct"),
        ("OmniGate", "legal-core-model"),
    ]


def settings() -> SimpleNamespace:
    return SimpleNamespace(
        DATASET_REVISION="namsyntax-420-v1",
        DENSE_INFERENCE_MODEL="intfloat/multilingual-e5-small",
        QDRANT_RERANK_MODEL="answerdotai/answerai-colbert-small-v1",
        PINECONE_RERANK_MODEL="bge-reranker-v2-m3",
        VERTEX_LLM_MODEL="gemini-3.5-flash",
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
            {"provider": "Google Vertex AI", "model": "gemini-3.5-flash"},
            *[
                {"provider": item.provider, "model": item.model}
                for item in GENERATION_PROVIDER_MODELS
            ],
        ],
    }
    assert manifest.configured_provider_models["judge"] == {
        "mode": "ragas",
        "candidates": [
            {"provider": "Google Vertex AI", "model": "gemini-3.5-flash"},
            *[
                {"provider": item.provider, "model": item.model}
                for item in JUDGE_PROVIDER_MODELS
            ],
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
