from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.evaluation.schemas import EvaluationRunManifest


def get_git_commit_sha() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if completed.returncode == 0:
            return completed.stdout.strip()
    except Exception:
        pass
    return "unknown_git_sha"


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
    timestamp_str = utc_now.strftime("%Y%m%d_%H%M%S")
    short_fp = config_fingerprint[:8] if config_fingerprint else "00000000"
    return f"{prefix}_{timestamp_str}_{short_fp}"


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
) -> EvaluationRunManifest:
    git_sha = get_git_commit_sha()
    dataset_sha = calculate_dataset_sha256(dataset_path)

    config_fields = (
        "DATASET_REVISION",
        "PINECONE_INDEX_NAME",
        "PINECONE_NAMESPACE",
        "DENSE_INFERENCE_MODEL",
        "PINECONE_HYBRID_ALPHA",
        "RETRIEVAL_DOCUMENT_LIMIT",
        "RESOLVED_DOCUMENT_LIMIT",
        "QUERY_CHUNK_MAX_TOKENS",
        "QUERY_CHUNK_OVERLAP_TOKENS",
        "RERANK_CANDIDATE_LIMIT",
        "RERANK_PER_DOCUMENT_LIMIT",
        "RERANK_RETURN_LIMIT",
        "RERANK_MIN_SCORE",
        "RERANK_TOP_K",
        "QDRANT_RERANK_MODEL",
        "PINECONE_RERANK_MODEL",
        "LEGAL_FTS_RESULT_LIMIT",
        "LLM_CONTEXT_MAX_TOKENS",
        "LLM_MAX_OUTPUT_TOKENS",
    )
    config_dict = {
        field: getattr(settings, field, None)
        for field in config_fields
        if hasattr(settings, field)
    }
    config_dict["eval_mode"] = eval_mode
    config_dict["judge_mode"] = judge_mode
    config_dict["guardrail_mode"] = guardrail_mode
    config_dict["rewrite_mode"] = rewrite_mode
    config_dict["reranker_provider"] = reranker_provider

    fp = calculate_configuration_fingerprint(config_dict)

    return EvaluationRunManifest(
        run_id=run_id,
        utc_timestamp=datetime.now(timezone.utc).isoformat(),
        git_sha=git_sha,
        dataset_revision=getattr(settings, "DATASET_REVISION", "v1.0.0"),
        dataset_sha256=dataset_sha,
        configuration_fingerprint=fp,
        command=command_str,
        eval_mode=eval_mode,
        judge_mode=judge_mode,
        guardrail_mode=guardrail_mode,
        rewrite_mode=rewrite_mode,
        reranker_provider=reranker_provider,
        configuration=config_dict,
        code_metric_version="1.0.0",
    )
