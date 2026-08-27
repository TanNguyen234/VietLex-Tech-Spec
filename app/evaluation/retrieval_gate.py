from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _micro(metric: dict[str, Any] | None) -> float | None:
    if not metric:
        return None
    value = metric.get("micro")
    return float(value) if value is not None else None


def evaluate_retrieval_gate(
    summary: dict[str, Any],
    *,
    k: int,
) -> dict[str, Any]:
    thresholds = {
        f"document_recall@{k}": 1.0,
        f"article_recall@{k}": 0.95,
        f"clause_recall@{k}": 0.90,
        "multi_hop_all_required": 0.95,
    }
    observed = {
        f"document_recall@{k}": _micro(
            summary.get("document_recall", {}).get(k)
            or summary.get("document_recall", {}).get(str(k))
        ),
        f"article_recall@{k}": _micro(
            summary.get("article_recall", {}).get(k)
            or summary.get("article_recall", {}).get(str(k))
        ),
        f"clause_recall@{k}": _micro(
            summary.get("clause_recall", {}).get(k)
            or summary.get("clause_recall", {}).get(str(k))
        ),
        "multi_hop_all_required": _micro(
            summary.get("multi_hop_all_required")
        ),
        "no_candidate_rate": _micro(summary.get("no_candidate_rate")),
        "retrieval_technical_error_rate": _micro(
            summary.get("retrieval_technical_error_rate")
        ),
        "reranker_technical_error_rate": _micro(
            summary.get("reranker_technical_error_rate")
        ),
    }
    failures = [
        name
        for name, threshold in thresholds.items()
        if observed[name] is None or observed[name] < threshold
    ]
    for name in (
        "no_candidate_rate",
        "retrieval_technical_error_rate",
        "reranker_technical_error_rate",
    ):
        if observed[name] is None or observed[name] > 0:
            failures.append(name)
    return {
        "passed": not failures,
        "k": k,
        "thresholds": thresholds,
        "observed": observed,
        "failures": failures,
    }


def validate_retrieval_run(
    run_dir: Path,
    *,
    expected_backend: str,
    expected_ranking: str,
    expected_dataset_sha256: str,
    expected_selected_case_ids_sha256: str,
    k: int,
) -> dict[str, Any]:
    from app.evaluation.retrieval_metrics import aggregate_retrieval_metrics

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    results = json.loads(
        (run_dir / "retrieval_results.json").read_text(encoding="utf-8")
    )
    configuration = manifest.get("configuration") or {}
    if configuration.get("requested_backend") != expected_backend:
        raise ValueError("retrieval run backend does not match answer evaluation")
    if configuration.get("ranking_mode") != expected_ranking:
        raise ValueError("retrieval run ranking does not match answer evaluation")
    if manifest.get("dataset_sha256") != expected_dataset_sha256:
        raise ValueError("retrieval run dataset SHA-256 mismatch")
    if (
        manifest.get("selected_case_ids_sha256")
        != expected_selected_case_ids_sha256
    ):
        raise ValueError("retrieval run selected-case SHA-256 mismatch")
    if not isinstance(results, list):
        raise ValueError("retrieval run results must use the canonical case list schema")
    gate = evaluate_retrieval_gate(aggregate_retrieval_metrics(results), k=k)
    if not gate["passed"]:
        raise ValueError(
            "retrieval quality gate failed: " + ", ".join(gate["failures"])
        )
    return {"gate": gate, "results": results, "manifest": manifest}
