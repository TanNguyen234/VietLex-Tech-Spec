from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.evaluation.schemas import EvaluationRunManifest


def get_git_provenance() -> Tuple[str, bool, bool, bool, bool, Optional[str], str]:
    git_sha = "unknown_git_sha"
    git_dirty = False
    git_tracked_dirty = False
    git_staged_dirty = False
    git_untracked_dirty = False
    git_diff_sha256 = None
    repo_root = str(Path.cwd().resolve())

    try:
        completed_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        if completed_sha.returncode == 0:
            git_sha = completed_sha.stdout.strip()

        completed_root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        if completed_root.returncode == 0:
            repo_root = completed_root.stdout.strip()

        status_res = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        untracked_files: list[str] = []
        def _is_excluded(path_str: str) -> bool:
            if path_str.startswith(".env"):
                return True
            if path_str.startswith("docs/evaluation/preflight/"):
                return True
            if path_str.startswith("docs/evaluation/runs/"):
                return True
            if path_str.startswith("docs/evaluation/evaluation_framework_") and path_str.endswith("_report.md"):
                return True
            if path_str.endswith(".tmp"):
                return True
            if "__pycache__/" in path_str:
                return True
            if ".pytest_cache/" in path_str:
                return True
            return False

        if status_res.returncode == 0 and status_res.stdout.strip():
            for line in status_res.stdout.splitlines():
                if not line.strip():
                    continue
                code = line[:2]
                filepath = line[3:].strip()
                
                if _is_excluded(filepath):
                    continue

                if code.startswith("??"):
                    git_untracked_dirty = True
                    untracked_files.append(filepath)
                else:
                    if code[0] in "MADRCU":
                        git_staged_dirty = True
                    if code[1] in "MADRCU":
                        git_tracked_dirty = True

        git_dirty = git_tracked_dirty or git_staged_dirty or git_untracked_dirty

        if git_dirty:
            diff_args = [
                "git", "diff", "HEAD", "--", ".",
                ":!docs/evaluation/preflight",
                ":!docs/evaluation/runs",
                ":!docs/evaluation/evaluation_framework_*_report.md",
                ":!*.tmp",
                ":!__pycache__",
                ":!.pytest_cache"
            ]
            diff_res = subprocess.run(
                diff_args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
            tracked_diff = diff_res.stdout if diff_res.returncode == 0 else ""

            staged_args = [
                "git", "diff", "--cached", "--", ".",
                ":!docs/evaluation/preflight",
                ":!docs/evaluation/runs",
                ":!docs/evaluation/evaluation_framework_*_report.md",
                ":!*.tmp",
                ":!__pycache__",
                ":!.pytest_cache"
            ]
            staged_res = subprocess.run(
                staged_args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
            staged_diff = staged_res.stdout if staged_res.returncode == 0 else ""

            payload_parts = [
                "=== TRACKED DIFF ===",
                tracked_diff,
                "=== STAGED DIFF ===",
                staged_diff,
                "=== UNTRACKED FILES ===",
            ]
            for ufile in sorted(untracked_files):
                upath = Path(repo_root) / ufile
                u_hash = "missing"
                if upath.exists() and upath.is_file():
                    try:
                        u_hash = hashlib.sha256(upath.read_bytes()).hexdigest()
                    except Exception:
                        u_hash = "read_error"
                payload_parts.append(f"{ufile}:{u_hash}")

            canonical_payload = "\n".join(payload_parts)
            git_diff_sha256 = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

    except Exception:
        pass

    return (
        git_sha,
        git_dirty,
        git_tracked_dirty,
        git_staged_dirty,
        git_untracked_dirty,
        git_diff_sha256,
        repo_root,
    )


def get_git_commit_sha() -> str:
    sha, _, _, _, _, _, _ = get_git_provenance()
    return sha


def calculate_dataset_sha256(dataset_path: Optional[Path]) -> Optional[str]:
    if not dataset_path:
        return None
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
    profile_name: str = "separated_intent",
    gold_sidecar_path: Optional[Path] = None,
    profile_obj: Any = None,
    gold_policy: str = "all-required-verified",
    selected_case_ids: Optional[List[str]] = None,
) -> EvaluationRunManifest:
    (
        git_sha,
        git_dirty,
        git_tracked_dirty,
        git_staged_dirty,
        git_untracked_dirty,
        git_diff_sha,
        repo_root,
    ) = get_git_provenance()
    dataset_sha = calculate_dataset_sha256(dataset_path) or "missing"
    sidecar_sha = calculate_dataset_sha256(gold_sidecar_path)

    profile_dict = profile_obj.to_dict() if profile_obj and hasattr(profile_obj, "to_dict") else {}
    selected_ids = selected_case_ids or []
    selected_ids_sha = hashlib.sha256(json.dumps(selected_ids).encode("utf-8")).hexdigest() if selected_ids else None

    config_dict = {
        "profile_name": profile_name,
        "profile": profile_dict,
        "eval_mode": eval_mode,
        "judge_mode": judge_mode,
        "guardrail_mode": guardrail_mode,
        "rewrite_mode": rewrite_mode,
        "reranker_provider": reranker_provider,
        "gold_policy": gold_policy,
        "selected_case_count": len(selected_ids),
        "selected_case_ids_sha256": selected_ids_sha,
    }

    fp = calculate_configuration_fingerprint(config_dict)

    return EvaluationRunManifest(
        run_id=run_id,
        utc_timestamp=datetime.now(timezone.utc).isoformat(),
        git_sha=git_sha,
        git_dirty=git_dirty,
        git_tracked_dirty=git_tracked_dirty,
        git_staged_dirty=git_staged_dirty,
        git_untracked_dirty=git_untracked_dirty,
        git_diff_sha256=git_diff_sha,
        repository_root=repo_root,
        dataset_revision=getattr(settings, "DATASET_REVISION", "v1.0.0"),
        dataset_sha256=dataset_sha,
        evaluation_dataset_sha256=dataset_sha,
        gold_label_sidecar_sha256=sidecar_sha,
        gold_policy=gold_policy,
        selected_case_count=len(selected_ids),
        selected_case_ids=selected_ids,
        selected_case_ids_sha256=selected_ids_sha,
        configuration_fingerprint=fp,
        command=command_str,
        eval_mode=eval_mode,
        judge_mode=judge_mode,
        guardrail_mode=guardrail_mode,
        rewrite_mode=rewrite_mode,
        reranker_provider=reranker_provider,
        profile_name=profile_name,
        configuration=config_dict,
        code_metric_version="2.0.0",
    )
