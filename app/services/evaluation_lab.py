from __future__ import annotations

import json
import math
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any
from app.evaluation.online_metrics import sanitize_error_message


_BOUNDARY = (
    "Đây là benchmark có giới hạn; không chứng minh độ chính xác pháp lý "
    "whole-corpus hoặc production readiness."
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=2)
def _read_immutable_run(run_path: Path) -> tuple[Any, Any]:
    return _read_json(run_path / "manifest.json"), _read_json(
        run_path / "answer_results.json"
    )


def _project_case(item: dict[str, Any]) -> dict[str, Any]:
    retrieval = item.get("retrieval_result") or {}
    if not isinstance(retrieval, dict):
        raise ValueError("invalid retrieval result")
    for key in ("metrics", "ragas_metrics", "technical_errors"):
        if item.get(key) is not None and not isinstance(item[key], dict):
            raise ValueError("invalid case field")
    retrieval_metrics = retrieval.get("metrics") or {}
    evidence = []
    for row in (retrieval.get("retrieved_evidence") or [])[:10]:
        if not isinstance(row, dict):
            continue
        evidence.append(
            {
                "document_id": row.get("document_id"),
                "citation": str(row.get("citation") or "")[:500],
                "text": str(row.get("text") or "")[:4_000],
                "rank": len(evidence) + 1,
            }
        )
    return {
        "case_id": str(item.get("case_id") or "")[:100],
        "question": str(item.get("question") or "")[:2_000],
        "status": str(item.get("status") or "unobserved")[:50],
        "answer": str(item.get("final_response") or "")[:12_000],
        "metrics": dict(item.get("metrics") or {}),
        "ragas_metrics": {
            str(key)[:80]: value
            for key, value in (item.get("ragas_metrics") or {}).items()
            if not str(key).startswith("_")
            and isinstance(value, (int, float, type(None)))
        },
        "evidence": evidence,
        "technical_errors": {
            str(key)[:80]: sanitize_error_message(value)
            for key, value in (item.get("technical_errors") or {}).items()
        },
        "retrieval_metrics": retrieval_metrics
        if isinstance(retrieval_metrics, dict)
        else {},
    }


def _metric_value(source: dict[str, Any], *path: str) -> float | None:
    value: Any = source
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(value) else None
    return None


_RETRIEVAL_METRICS = {
    "retrieval.document_recall_at_3": ("document_recall", "3"),
    "retrieval.article_recall_at_3": ("article_recall", "3"),
    "retrieval.clause_recall_at_3": ("clause_recall", "3"),
    "retrieval.document_mrr": ("mrr", "document"),
    "retrieval.article_mrr": ("mrr", "article"),
    "retrieval.clause_mrr": ("mrr", "clause"),
    "retrieval.ndcg_at_10": ("ndcg_at_10",),
    "retrieval.exact_reference_hit": ("exact_reference_hit",),
    "retrieval.multi_hop_all_required": ("multi_hop", "all_required_metric"),
    "retrieval.multi_hop_partial": ("multi_hop", "partial_metric"),
}


def _summary(cases: list[dict], key: str, section: str) -> dict:
    values = []
    skipped: Counter[str] = Counter()
    for case in cases:
        source = case[section]
        path = _RETRIEVAL_METRICS.get(key, (key,))
        value = _metric_value(source, *path)
        if value is not None:
            values.append(value)
            continue
        leaf = source
        for part in path:
            leaf = leaf.get(part) if isinstance(leaf, dict) else None
        reason = leaf.get("reason") if isinstance(leaf, dict) else None
        skipped[str(reason or source.get("skip_reason") or "not_recorded")] += 1
    return {
        "mean": sum(values) / len(values) if values else None,
        "numerator": sum(values),
        "denominator": len(values),
        "coverage": len(values),
        "total": len(cases),
        "skipped": sum(skipped.values()),
        "skip_reasons": dict(skipped),
    }


def load_evaluation_lab(
    run_path: Path, *, case_id: str | None = None
) -> dict[str, Any]:
    manifest_path = run_path / "manifest.json"
    results_path = run_path / "answer_results.json"
    if not manifest_path.is_file():
        return {"status": "unavailable", "boundary": _BOUNDARY, "cases": []}
    try:
        manifest, raw_results = _read_immutable_run(run_path)
        if not results_path.is_file():
            raise ValueError("missing answer results")
        if not isinstance(manifest, dict) or not isinstance(raw_results, list):
            raise ValueError("invalid artifact shape")
        cases = [
            _project_case(row) for row in raw_results[:100] if isinstance(row, dict)
        ]
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        return {"status": "invalid", "boundary": _BOUNDARY, "cases": []}

    selected = next((row for row in cases if row["case_id"] == case_id), None)
    numeric_metrics: dict[str, list[float]] = {}
    ragas_metrics: dict[str, list[float]] = {}
    for row in cases:
        for key, value in row["metrics"].items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numeric_metrics.setdefault(str(key), []).append(float(value))
        for key, value in row["ragas_metrics"].items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                ragas_metrics.setdefault(str(key), []).append(float(value))
    return {
        "status": "available",
        "boundary": _BOUNDARY,
        "provenance": {
            key: manifest.get(key)
            for key in (
                "run_id",
                "utc_timestamp",
                "git_sha",
                "git_dirty",
                "git_diff_sha256",
                "dataset_revision",
                "dataset_sha256",
                "configuration_fingerprint",
                "judge_mode",
                "selected_case_count",
                "provenance_status",
            )
        },
        "deterministic_metrics": {
            key: _summary(
                cases,
                key,
                "retrieval_metrics" if key in _RETRIEVAL_METRICS else "metrics",
            )
            for key in (*numeric_metrics, *_RETRIEVAL_METRICS)
        },
        "ragas_metrics": {
            key: _summary(cases, key, "ragas_metrics") for key in ragas_metrics
        },
        "cases": [
            {
                "case_id": row["case_id"],
                "question": row["question"],
                "status": row["status"],
            }
            for row in cases[:50]
        ],
        "case": selected,
    }
