from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.evaluation.provider_catalog import (
    GENERATION_PROVIDER_MODELS,
    JUDGE_PROVIDER_MODELS,
    ProviderModel,
)
from app.evaluation.provenance import collect_git_provenance
from app.evaluation.schemas import EvaluationArtifactFile, EvaluationRunManifest


def get_git_provenance() -> Tuple[str, bool, bool, bool, bool, Optional[str], str]:
    provenance = collect_git_provenance()
    return (
        provenance.git_sha,
        provenance.git_dirty,
        provenance.git_tracked_dirty,
        provenance.git_staged_dirty,
        provenance.git_untracked_dirty,
        provenance.git_diff_sha256,
        provenance.repository_root,
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
    pending_carriage_return = False
    with path.open("rb") as f:
        while chunk := f.read(65536):
            if pending_carriage_return:
                chunk = b"\r" + chunk
            pending_carriage_return = chunk.endswith(b"\r")
            if pending_carriage_return:
                chunk = chunk[:-1]
            hasher.update(chunk.replace(b"\r\n", b"\n"))
    if pending_carriage_return:
        hasher.update(b"\r")
    return hasher.hexdigest()


def calculate_configuration_fingerprint(config_dict: Dict[str, Any]) -> str:
    payload = json.dumps(config_dict, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _public_candidates(
    items: Sequence[ProviderModel],
) -> List[Dict[str, str]]:
    return [
        {"provider": item.provider, "model": item.model}
        for item in items
    ]


def build_configured_provider_models(
    *,
    settings: Any,
    eval_mode: str,
    judge_mode: str,
    requested_backend: str = "production",
) -> Dict[str, Any]:
    structural_enabled = getattr(
        settings,
        "STRUCTURAL_BACKEND_ENABLED",
        False,
    )
    structural_for_run = requested_backend == "qdrant-v2-parallel" or (
        requested_backend == "production" and structural_enabled
    )
    reranker_mode = getattr(settings, "STRUCTURAL_RERANKER_MODE", "current")
    if requested_backend == "vertex-qdrant-v3":
        dense = {
            "provider": "Google Vertex AI",
            "model": settings.VERTEX_EMBEDDING_MODEL,
        }
    elif structural_for_run:
        dense = {
            "provider": "qdrant-structural-collection",
            "model": settings.STRUCTURAL_DENSE_MODEL,
        }
    else:
        dense = {
            "provider": "qdrant-cloud-staging",
            "model": settings.DENSE_INFERENCE_MODEL,
        }
    if structural_for_run and reranker_mode == "pinecone-only":
        reranker_primary = {
            "provider": "pinecone",
            "model": settings.PINECONE_RERANK_MODEL,
        }
        reranker_fallback = {
            "provider": "qdrant-via-pinecone-v1-fallback",
            "model": settings.QDRANT_RERANK_MODEL,
        }
    else:
        reranker_primary = {
            "provider": "qdrant",
            "model": settings.QDRANT_RERANK_MODEL,
        }
        reranker_fallback = {
            "provider": "pinecone",
            "model": settings.PINECONE_RERANK_MODEL,
        }
    return {
        "dense": dense,
        "reranker_primary": reranker_primary,
        "reranker_fallback": reranker_fallback,
        "generation": {
            "mode": (
                "configured_fallback_chain"
                if eval_mode == "answer"
                else "not_applicable"
            ),
            "candidates": (
                [
                    {
                        "provider": "Google Vertex AI",
                        "model": settings.VERTEX_LLM_MODEL,
                    },
                    *_public_candidates(GENERATION_PROVIDER_MODELS),
                ]
                if eval_mode == "answer"
                else []
            ),
        },
        "judge": {
            "mode": judge_mode,
            "candidates": (
                [
                    {
                        "provider": "Google Vertex AI",
                        "model": settings.VERTEX_LLM_MODEL,
                    },
                    *_public_candidates(JUDGE_PROVIDER_MODELS),
                ]
                if judge_mode == "ragas"
                else []
            ),
        },
    }


def build_run_configuration(
    *,
    profile_name: str,
    profile: Dict[str, Any],
    eval_mode: str,
    judge_mode: str,
    guardrail_mode: str,
    rewrite_mode: str,
    reranker_provider: str,
    gold_policy: str,
    selected_case_ids: List[str],
    selected_case_ids_sha256: str,
    settings: Any,
    requested_backend: str = "production",
    ranking_mode: str = "raw-rrf",
    candidate_pool_source: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    expected_selected_ids_sha = hashlib.sha256(
        json.dumps(
            selected_case_ids,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if selected_case_ids_sha256 != expected_selected_ids_sha:
        raise ValueError(
            "selected_case_ids_sha256 does not match selected_case_ids"
        )
    provider_models = build_configured_provider_models(
        settings=settings,
        eval_mode=eval_mode,
        judge_mode=judge_mode,
        requested_backend=requested_backend,
    )
    if requested_backend == "vertex-qdrant-v3":
        retrieval_runtime = {
            "backend": "vertex-qdrant-v3",
            "collection": settings.VERTEX_QDRANT_COLLECTION_NAME,
            "dense_model": settings.VERTEX_EMBEDDING_MODEL,
            "dense_dimension": settings.VERTEX_QDRANT_VECTOR_SIZE,
            "sparse_model": "FastSparseEncoder",
            "fallback_backend": None,
        }
    elif requested_backend == "qdrant-v2-parallel" or (
        requested_backend == "production"
        and getattr(settings, "STRUCTURAL_BACKEND_ENABLED", False)
    ):
        retrieval_runtime = {
            "backend": "qdrant_structural_v2",
            "collection": settings.STRUCTURAL_COLLECTION_NAME,
            "dense_model": settings.STRUCTURAL_DENSE_MODEL,
            "sparse_model": settings.STRUCTURAL_SPARSE_MODEL,
            "reranker_mode": settings.STRUCTURAL_RERANKER_MODE,
            "dense_top_k": settings.STRUCTURAL_DENSE_TOP_K,
            "bm25_top_k": settings.STRUCTURAL_BM25_TOP_K,
            "fused_limit": settings.STRUCTURAL_FUSED_LIMIT,
            "rerank_input_limit": settings.STRUCTURAL_RERANK_INPUT_LIMIT,
            "rerank_return_limit": settings.STRUCTURAL_RERANK_RETURN_LIMIT,
            "final_evidence_limit": settings.STRUCTURAL_FINAL_EVIDENCE_LIMIT,
            "cross_lane_final_rerank_enabled": bool(
                getattr(
                    settings,
                    "CROSS_LANE_FINAL_RERANK_ENABLED",
                    False,
                )
            ),
            "cross_lane_final_reranker": (
                f"pinecone:{settings.PINECONE_RERANK_MODEL}"
            ),
            "fallback_backend": "pinecone_v1",
        }
    else:
        retrieval_runtime = {
            "backend": "pinecone_v1",
            "fallback_backend": "sqlite_fts",
        }
    return {
        "requested_backend": requested_backend,
        "effective_backend": retrieval_runtime["backend"],
        "ranking_mode": ranking_mode,
        "candidate_pool_source": candidate_pool_source,
        "profile_name": profile_name,
        "profile": profile,
        "eval_mode": eval_mode,
        "judge_mode": judge_mode,
        "guardrail_mode": guardrail_mode,
        "rewrite_mode": rewrite_mode,
        "reranker_provider": reranker_provider,
        "gold_policy": gold_policy,
        "selected_case_count": len(selected_case_ids),
        "selected_case_ids_sha256": selected_case_ids_sha256,
        "retrieval_runtime": retrieval_runtime,
        "configured_provider_models": provider_models,
    }


def generate_unique_run_id(prefix: str = "eval", config_fingerprint: str = "") -> str:
    utc_now = datetime.now(timezone.utc)
    timestamp_str = utc_now.strftime("%Y%m%d_%H%M%S_%f")
    short_fp = config_fingerprint[:8] if config_fingerprint else "00000000"
    return f"{prefix}_{timestamp_str}_{short_fp}"


RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def prepare_run_directory(base_dir: Path, run_id: str) -> Path:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError(
            "invalid run_id: use 1-128 safe filename characters"
        )
    resolved_base = Path(base_dir).resolve()
    run_dir = (resolved_base / run_id).resolve()
    if run_dir.parent != resolved_base:
        raise ValueError(
            "invalid run_id: resolved path escapes base directory"
        )
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


def collect_artifact_files(run_dir: Path) -> list[EvaluationArtifactFile]:
    artifacts: list[EvaluationArtifactFile] = []
    for path in sorted(run_dir.iterdir()):
        if not path.is_file() or path.name == "manifest.json":
            continue
        size = path.stat().st_size
        hasher = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(65536):
                hasher.update(chunk)
        artifacts.append(
            EvaluationArtifactFile(
                path=path.name,
                sha256=hasher.hexdigest(),
                bytes=size,
                storage="git" if size <= 20_000_000 else "external",
            )
        )
    return artifacts


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
    selected_case_ids_sha256: str,
    profile_name: str = "separated_intent",
    gold_sidecar_path: Optional[Path] = None,
    profile_obj: Any = None,
    gold_policy: str = "all-required-verified",
    selected_case_ids: Optional[List[str]] = None,
    requested_backend: str = "production",
    ranking_mode: str = "raw-rrf",
    candidate_pool_source: Optional[Dict[str, Any]] = None,
) -> EvaluationRunManifest:
    provenance = collect_git_provenance()
    dataset_sha = calculate_dataset_sha256(dataset_path) or "missing"
    sidecar_sha = calculate_dataset_sha256(gold_sidecar_path)

    profile_dict = profile_obj.to_dict() if profile_obj and hasattr(profile_obj, "to_dict") else {}
    selected_ids = selected_case_ids or []
    config_dict = build_run_configuration(
        profile_name=profile_name,
        profile=profile_dict,
        eval_mode=eval_mode,
        judge_mode=judge_mode,
        guardrail_mode=guardrail_mode,
        rewrite_mode=rewrite_mode,
        reranker_provider=reranker_provider,
        gold_policy=gold_policy,
        selected_case_ids=selected_ids,
        selected_case_ids_sha256=selected_case_ids_sha256,
        settings=settings,
        requested_backend=requested_backend,
        ranking_mode=ranking_mode,
        candidate_pool_source=candidate_pool_source,
    )

    fp = calculate_configuration_fingerprint(config_dict)
    provider_models = config_dict["configured_provider_models"]

    return EvaluationRunManifest(
        run_id=run_id,
        utc_timestamp=datetime.now(timezone.utc).isoformat(),
        git_sha=provenance.git_sha,
        git_dirty=provenance.git_dirty,
        git_tracked_dirty=provenance.git_tracked_dirty,
        git_staged_dirty=provenance.git_staged_dirty,
        git_untracked_dirty=provenance.git_untracked_dirty,
        git_diff_sha256=provenance.git_diff_sha256,
        git_diff_status=provenance.git_diff_status,
        git_diff_reason=provenance.git_diff_reason,
        source_state_sha256=provenance.source_state_sha256,
        provenance_status=provenance.status,
        provenance_error=provenance.error,
        repository_root=provenance.repository_root,
        dataset_revision=getattr(settings, "DATASET_REVISION", "v1.0.0"),
        dataset_sha256=dataset_sha,
        evaluation_dataset_sha256=dataset_sha,
        gold_label_sidecar_sha256=sidecar_sha,
        gold_policy=gold_policy,
        selected_case_count=len(selected_ids),
        selected_case_ids=selected_ids,
        selected_case_ids_sha256=selected_case_ids_sha256,
        configuration_fingerprint=fp,
        command=command_str,
        eval_mode=eval_mode,
        judge_mode=judge_mode,
        guardrail_mode=guardrail_mode,
        rewrite_mode=rewrite_mode,
        reranker_provider=reranker_provider,
        profile_name=profile_name,
        configuration=config_dict,
        configured_provider_models=provider_models,
    )
