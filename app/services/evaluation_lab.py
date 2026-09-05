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
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("artifact_size_limit")
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=2)
def _read_immutable_run(run_path: Path, kind: str = "answer") -> tuple[Any, Any]:
    return _read_json(run_path / "manifest.json"), _read_json(
        run_path / f"{kind}_results.json"
    )


def _project_case(item: dict[str, Any]) -> dict[str, Any]:
    retrieval = item.get("retrieval_result") or {}
    if not isinstance(retrieval, dict):
        raise ValueError("invalid retrieval result")
    for key in ("metrics", "ragas_metrics", "technical_errors", "latency"):
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
        "latency": item.get("latency") or {},
    }


def _metric_value(source: dict[str, Any], *path: str) -> float | None:
    value: Any = source
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    if isinstance(value, dict):
        value = value.get("value")
    if (
        path
        and path[-1]
        in {"no_candidate", "retrieval_technical_error", "reranker_technical_error"}
        and isinstance(value, bool)
    ):
        return float(value)
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
    "retrieval.no_candidate": ("no_candidate",),
    "retrieval.technical_error": ("retrieval_technical_error",),
    "retrieval.reranker_error": ("reranker_technical_error",),
}


def _summary(
    cases: list[dict], key: str, section: str, path: tuple[str, ...] | None = None
) -> dict:
    values = []
    skipped: Counter[str] = Counter()
    path = path or _RETRIEVAL_METRICS.get(key, (key,))
    for case in cases:
        source = case[section]
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


def _recorded_retrieval_paths(cases: list[dict]) -> tuple[dict, dict]:
    retrieval = dict(_RETRIEVAL_METRICS)
    stages = {}
    for case in cases:
        metrics = case["retrieval_metrics"]
        for level in ("document", "article", "clause"):
            recalls = metrics.get(f"{level}_recall")
            if isinstance(recalls, dict):
                for k in recalls:
                    if str(k).isdigit():
                        retrieval[f"retrieval.{level}_recall_at_{k}"] = (
                            f"{level}_recall",
                            k,
                        )
        stage_rows = metrics.get("stages")
        if not isinstance(stage_rows, dict):
            continue
        for name, stage in stage_rows.items():
            if not isinstance(stage, dict):
                continue
            recalls = stage.get("recall")
            if not isinstance(recalls, dict):
                continue
            for level in ("document", "article", "clause"):
                if isinstance(recalls.get(level), dict):
                    for k in recalls[level]:
                        if str(k).isdigit():
                            stages[f"{name}.{level}_recall_at_{k}"] = (
                                "stages",
                                name,
                                "recall",
                                level,
                                k,
                            )
    return retrieval, stages


def load_evaluation_lab(
    run_path: Path, *, case_id: str | None = None
) -> dict[str, Any]:
    manifest_path = run_path / "manifest.json"
    kind = "answer" if (run_path / "answer_results.json").is_file() else "retrieval"
    if not manifest_path.is_file():
        return {"status": "unavailable", "boundary": _BOUNDARY, "cases": []}
    try:
        manifest, raw_results = _read_immutable_run(run_path, kind)
        if not isinstance(manifest, dict) or not isinstance(raw_results, list):
            raise ValueError("invalid artifact shape")
        if any(not isinstance(row, dict) for row in raw_results):
            raise ValueError("invalid case shape")
        cases = [
            _project_case(
                row
                if kind == "answer"
                else {
                    **row,
                    "metrics": {},
                    "retrieval_result": row,
                }
            )
            for row in raw_results[:100]
        ]
        gate_path = run_path / "quality_gate.json"
        gate = _read_json(gate_path) if gate_path.is_file() else None
        if gate is not None and (
            not isinstance(gate, dict) or type(gate.get("passed")) is not bool
        ):
            raise ValueError("invalid quality gate")
        if gate is not None and (
            not isinstance(gate.get("failures", []), list)
            or any(not isinstance(value, str) for value in gate.get("failures", []))
        ):
            raise ValueError("invalid quality gate failures")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        return {
            "status": "invalid",
            "boundary": _BOUNDARY,
            "cases": [],
            "error_kind": "artifact_size_limit"
            if str(exc) == "artifact_size_limit"
            else "artifact_read_or_schema_error",
        }

    selected = next((row for row in cases if row["case_id"] == case_id), None)
    numeric_metrics: set[str] = set()
    ragas_metrics: set[str] = set()
    for row in cases:
        for key, value in row["metrics"].items():
            if value is None or (
                isinstance(value, (int, float)) and not isinstance(value, bool)
            ):
                if key != "skip_reason":
                    numeric_metrics.add(str(key))
        for key, value in row["ragas_metrics"].items():
            if value is None or (
                isinstance(value, (int, float)) and not isinstance(value, bool)
            ):
                ragas_metrics.add(str(key))
    retrieval_paths, stage_paths = _recorded_retrieval_paths(cases)
    answer_summaries = {
        key: _summary(cases, key, "metrics") for key in sorted(numeric_metrics)
    }
    retrieval_summaries = {
        key: _summary(cases, key, "retrieval_metrics", path)
        for key, path in retrieval_paths.items()
    }
    return {
        "status": "available",
        "run_kind": kind,
        "record_count": len(raw_results),
        "displayed_count": len(cases),
        "truncated": len(raw_results) > len(cases),
        "quality_gate": gate,
        "status_counts": dict(Counter(row["status"] for row in cases)),
        "stage_metrics": {
            key: _summary(cases, key, "retrieval_metrics", path)
            for key, path in stage_paths.items()
        },
        "metric_groups": {
            "Chất lượng câu trả lời": answer_summaries,
            "Truy xuất và lỗi kỹ thuật": retrieval_summaries,
        },
        "latency": {
            key: _summary(cases, key, "latency")
            for key in sorted({key for row in cases for key in row["latency"]})
        },
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
                "command",
                "code_metric_version",
                "configured_provider_models",
            )
        },
        "deterministic_metrics": {**answer_summaries, **retrieval_summaries},
        "ragas_metrics": {
            key: _summary(cases, key, "ragas_metrics") for key in sorted(ragas_metrics)
        },
        "cases": [
            {
                "case_id": row["case_id"],
                "question": row["question"],
                "status": row["status"],
            }
            for row in cases
        ],
        "case": selected,
    }
