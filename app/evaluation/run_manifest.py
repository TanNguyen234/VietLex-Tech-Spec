from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.evaluation.schemas import EvaluationRunManifest


def get_git_provenance() -> Tuple[str, bool, Optional[str], str]:
    git_sha = "unknown_git_sha"
    git_dirty = False
    git_diff_sha256 = None
    repo_root = str(Path.cwd().resolve())

    try:
        completed_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if completed_sha.returncode == 0:
            git_sha = completed_sha.stdout.strip()

        completed_status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if completed_status.returncode == 0 and completed_status.stdout.strip():
            git_dirty = True
            completed_diff = subprocess.run(
                ["git", "diff", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            diff_text = completed_diff.stdout if completed_diff.returncode == 0 else completed_status.stdout
            git_diff_sha256 = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()

        completed_root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if completed_root.returncode == 0:
            repo_root = completed_root.stdout.strip()
    except Exception:
        pass

    return git_sha, git_dirty, git_diff_sha256, repo_root


def get_git_commit_sha() -> str:
    sha, _, _, _ = get_git_provenance()
    return sha



def calculate_dataset_sha256(dataset_path: Path) -> str:
    path = Path(dataset_path).resolve()
    if not path.exists():
        return "missing_dataset"
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def calculate_configuration_fingerprint(config_dict: Dict[str, Any]) -> str:
    payload = json.dumps(config_dict, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_unique_run_id(prefix: str = "eval", config_fingerprint: str = "") -> str:
    utc_now = datetime.now(timezone.utc)
    timestamp_str = utc_now.strftime("%Y%m%d_%H%M%S_%f")
    short_fp = config_fingerprint[:8] if config_fingerprint else "00000000"
    return f"{prefix}_{timestamp_str}_{short_fp}"


def prepare_run_directory(base_dir: Path, run_id: str) -> Path:
    run_dir = (base_dir / run_id).resolve()
    if run_dir.exists():
        raise FileExistsError(f"Run directory already exists and cannot be overwritten: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def atomic_write_json(file_path: Path, data: Any) -> None:
    file_path = Path(file_path).resolve()
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = file_path.with_suffix(file_path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, file_path)


def create_run_manifest(
    run_id: str,
    eval_mode: str,
    judge_mode: str,
    guardrail_mode: str,
    rewrite_mode: str,
    reranker_provider: str,
    dataset_path: Path,
    settings: Any,
    command_str: str,
    profile_name: str = "custom",
    gold_sidecar_path: Optional[Path] = None,
) -> EvaluationRunManifest:
    git_sha, git_dirty, git_diff_sha, repo_root = get_git_provenance()
    dataset_sha = calculate_dataset_sha256(dataset_path)
    sidecar_sha = calculate_dataset_sha256(gold_sidecar_path) if gold_sidecar_path else None

    config_dict = {
        "profile_name": profile_name,
        "RETRIEVAL_DOCUMENT_LIMIT": getattr(settings, "RETRIEVAL_DOCUMENT_LIMIT", 24),
        "RESOLVED_DOCUMENT_LIMIT": getattr(settings, "RESOLVED_DOCUMENT_LIMIT", 16),
        "LOCAL_CHUNKS_PER_DOCUMENT": getattr(settings, "LOCAL_CHUNKS_PER_DOCUMENT", 4),
        "RERANK_INPUT_LIMIT": getattr(settings, "RERANK_INPUT_LIMIT", 24),
        "FINAL_EVIDENCE_LIMIT": getattr(settings, "FINAL_EVIDENCE_LIMIT", 3),
        "INTENT_SCORING_ENABLED": getattr(settings, "INTENT_SCORING_ENABLED", True),
        "eval_mode": eval_mode,
        "judge_mode": judge_mode,
        "guardrail_mode": guardrail_mode,
        "rewrite_mode": rewrite_mode,
        "reranker_provider": reranker_provider,
    }

    fp = calculate_configuration_fingerprint(config_dict)

    return EvaluationRunManifest(
        run_id=run_id,
        utc_timestamp=datetime.now(timezone.utc).isoformat(),
        git_sha=git_sha,
        git_dirty=git_dirty,
        git_diff_sha256=git_diff_sha,
        repository_root=repo_root,
        dataset_revision=getattr(settings, "DATASET_REVISION", "v1.0.0"),
        dataset_sha256=dataset_sha,
        evaluation_dataset_sha256=dataset_sha,
        gold_label_sidecar_sha256=sidecar_sha,
        configuration_fingerprint=fp,
        command=command_str,
        eval_mode=eval_mode,
        judge_mode=judge_mode,
        guardrail_mode=guardrail_mode,
        rewrite_mode=rewrite_mode,
        reranker_provider=reranker_provider,
        profile_name=profile_name,
        configuration=config_dict,
        code_metric_version="1.1.0",
    )
