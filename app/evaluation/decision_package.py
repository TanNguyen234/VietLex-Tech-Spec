import hashlib
import json
import math
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from app.evaluation.artifact_io import (
    ArtifactCollisionError,
    canonical_json_bytes,
    write_immutable_json,
)
from app.evaluation.case_selection import (
    CaseSelectionResult,
    build_cases,
    select_evaluation_cases,
)
from app.evaluation.gold_sidecar import GoldSidecar, load_gold_sidecar
from app.evaluation.provenance import GitProvenance, collect_git_provenance
from app.evaluation.retrieval_metrics import aggregate_retrieval_metrics
from app.evaluation.schemas import EvidenceStatus, GoldenCase


SCHEMA_VERSION = "task3-production-light-v1"
METRIC_VERSION = "3.0.0"

PROHIBITED_METRIC_SUBSTRINGS = (
    "overall_score",
    "quality_score",
    "readiness_score",
    "weighted_score",
    "combined_score",
)

NON_PRODUCTION_RUNNERS = (
    "run_structural_retrieval_eval.py",
    "run_pinecone_structural_eval.py",
    "run_structural_index_pilot.py",
)

PACKAGE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# Quality Floors for Production Retrieval Gate
DOCUMENT_RECALL_FLOOR = 1.00
ARTICLE_RECALL_FLOOR = 0.95
CLAUSE_RECALL_FLOOR = 0.90
ALL_REQUIRED_COVERAGE_FLOOR = 0.95
NO_CANDIDATE_RATE_CEILING = 0.00
RETRIEVAL_ERROR_RATE_CEILING = 0.00
RERANKER_ERROR_RATE_CEILING = 0.00


def validate_package_id(package_id: str, output_dir: Path) -> Path:
    if not isinstance(package_id, str) or not PACKAGE_ID_PATTERN.match(package_id):
        raise ValueError(
            f"Invalid package_id: '{package_id}'. Must match regex ^[A-Za-z0-9][A-Za-z0-9._-]{{0,127}}$ "
            f"and not contain path separators or parent directory references."
        )
    resolved_out = Path(output_dir).resolve()
    target_pkg_dir = (resolved_out / package_id).resolve()
    if target_pkg_dir.parent != resolved_out:
        raise ValueError(
            f"Directory escape detected for package_id: '{package_id}'. "
            f"Resolved directory {target_pkg_dir} parent must equal {resolved_out}."
        )
    return target_pkg_dir


def _extract_script_target(command_str: str) -> Optional[str]:
    if not command_str:
        return None
    try:
        tokens = shlex.split(command_str, posix=False)
    except Exception:
        tokens = command_str.split()

    clean_tokens = [t.strip("\"'") for t in tokens if t.strip("\"'")]
    idx = 0
    while idx < len(clean_tokens):
        token = clean_tokens[idx]
        token_name = PurePath(token.replace("\\", "/")).name.lower()
        if token_name in ("python", "python.exe", "python3", "python3.exe", "py", "py.exe"):
            idx += 1
            while idx < len(clean_tokens) and clean_tokens[idx].startswith("-"):
                if clean_tokens[idx] == "-m" and idx + 1 < len(clean_tokens):
                    return clean_tokens[idx + 1]
                idx += 1
            continue
        return token
    return None


def hash_file_sha256(path: Path | str) -> str:
    resolved = Path(path).resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"File not found for hashing: {resolved}")
    hasher = hashlib.sha256()
    with resolved.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def compute_percentile(values: List[float], quantile: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    idx = (len(ordered) - 1) * quantile
    low = math.floor(idx)
    high = math.ceil(idx)
    if low == high:
        return round(float(ordered[low]), 4)
    weight = idx - low
    return round(ordered[low] * (1.0 - weight) + ordered[high] * weight, 4)


@dataclass(frozen=True)
class DecisionPackageResult:
    package_id: str
    package_dir: Path
    decision_file: Path
    report_file: Path
    decision_dict: Dict[str, Any]
    report_content: str
    write_status: Literal["created", "reused"]


def load_and_evaluate_offline_golden_quality(
    dataset_path: Path,
    sidecar_path: Path,
    gold_policy: str = "all-required-verified",
) -> Tuple[Dict[str, Any], CaseSelectionResult, GoldSidecar]:
    raw_dataset = json.loads(dataset_path.read_bytes().decode("utf-8"))
    raw_dataset_case_ids = [f"case_{idx:03d}" for idx in range(1, len(raw_dataset) + 1)]

    sidecar = load_gold_sidecar(sidecar_path, dataset_case_ids=raw_dataset_case_ids)
    all_cases = build_cases(raw_dataset, sidecar.labels_by_case_id)
    selection = select_evaluation_cases(
        all_cases,
        gold_policy=gold_policy,
        include_unanswerable=False,
    )

    total_cases = len(raw_dataset)
    answerable_cases = sum(1 for c in all_cases if c.answerable)
    unanswerable_cases = total_cases - answerable_cases

    total_evidence = len(sidecar.labels)
    status_breakdown: Dict[str, int] = {}
    verified_evidence = 0
    unresolved_required = 0

    for label in sidecar.labels:
        st = label.status if isinstance(label.status, str) else label.status.value
        status_breakdown[st] = status_breakdown.get(st, 0) + 1
        if st == EvidenceStatus.VERIFIED or st == "verified":
            verified_evidence += 1
        elif label.required:
            unresolved_required += 1

    ev_cov_val = round(verified_evidence / total_evidence, 4) if total_evidence > 0 else None
    all_req_cases = len(selection.selected_cases)
    case_cov_val = round(all_req_cases / total_cases, 4) if total_cases > 0 else None

    offline_quality_data = {
        "dataset_coverage": {
            "total_cases": total_cases,
            "answerable_cases": answerable_cases,
            "unanswerable_cases": unanswerable_cases,
        },
        "evidence_verification_coverage": {
            "total_evidence_items": total_evidence,
            "verified_evidence_items": verified_evidence,
            "verified_evidence_coverage": {
                "numerator": verified_evidence,
                "denominator": total_evidence,
                "value": ev_cov_val,
            },
            "all_required_verified_case_count": all_req_cases,
            "total_dataset_case_count": total_cases,
            "all_required_verified_case_coverage": {
                "numerator": all_req_cases,
                "denominator": total_cases,
                "value": case_cov_val,
            },
            "status_breakdown": status_breakdown,
            "unresolved_required_evidence_count": unresolved_required,
        },
    }

    return offline_quality_data, selection, sidecar


def load_production_benchmark(
    benchmark_dir: Optional[Path],
    *,
    target_git_sha: str,
    target_dataset_sha: str,
    target_sidecar_sha: str,
    target_selected_case_ids: List[str],
    target_selected_case_ids_sha: str,
) -> Dict[str, Any]:
    if benchmark_dir is None:
        return {
            "status": "NOT_RUN",
            "readiness_eligible": False,
            "ineligibility_reasons": ["missing_production_retrieval_benchmark"],
            "benchmark_dir": None,
            "manifest_sha256": None,
            "results_sha256": None,
            "manifest": None,
            "metrics": None,
            "threshold_evaluations": {},
        }

    bench_path = Path(benchmark_dir).resolve()
    manifest_file = bench_path / "manifest.json"
    results_file = bench_path / "results.json"
    if not results_file.exists():
        results_file = bench_path / "retrieval_results.json"

    if not manifest_file.exists() or not results_file.exists():
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "readiness_eligible": False,
            "ineligibility_reasons": ["benchmark_files_missing_or_incomplete"],
            "benchmark_dir": str(bench_path),
            "manifest_sha256": hash_file_sha256(manifest_file) if manifest_file.exists() else None,
            "results_sha256": hash_file_sha256(results_file) if results_file.exists() else None,
            "manifest": None,
            "metrics": None,
            "threshold_evaluations": {},
        }

    manifest_sha = hash_file_sha256(manifest_file)
    results_sha = hash_file_sha256(results_file)

    try:
        manifest_data = json.loads(manifest_file.read_bytes().decode("utf-8"))
        case_results_data = json.loads(results_file.read_bytes().decode("utf-8"))
    except Exception as err:
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "readiness_eligible": False,
            "ineligibility_reasons": [f"benchmark_json_parsing_failed: {err}"],
            "benchmark_dir": str(bench_path),
            "manifest_sha256": manifest_sha,
            "results_sha256": results_sha,
            "manifest": None,
            "metrics": None,
            "threshold_evaluations": {},
        }

    ineligibility_reasons: List[str] = []
    status = "PASS"

    command = str(manifest_data.get("command", ""))
    eval_mode = manifest_data.get("eval_mode")
    judge_mode = manifest_data.get("judge_mode")
    gold_policy = manifest_data.get("gold_policy")

    # 1. Non-production runner check via token parsing
    script_target = _extract_script_target(command)
    if script_target is None:
        ineligibility_reasons.append("non_standard_retrieval_entrypoint")
        status = "NON_PRODUCTION"
    else:
        script_basename = PurePath(script_target.replace("\\", "/")).name
        if script_basename in NON_PRODUCTION_RUNNERS:
            ineligibility_reasons.append("non_production_benchmark_route")
            status = "NON_PRODUCTION"
        elif script_basename != "run_retrieval_eval.py":
            ineligibility_reasons.append("non_standard_retrieval_entrypoint")
            status = "NON_PRODUCTION"

    if status != "NON_PRODUCTION":
        for non_prod in NON_PRODUCTION_RUNNERS:
            if non_prod in command:
                ineligibility_reasons.append("non_production_benchmark_route")
                status = "NON_PRODUCTION"
                break

    if eval_mode != "retrieval-only":
        ineligibility_reasons.append("invalid_eval_mode")
        status = "NON_PRODUCTION"

    if judge_mode != "none":
        ineligibility_reasons.append("judge_mode_not_none")
        status = "NON_PRODUCTION"

    if gold_policy != "all-required-verified":
        ineligibility_reasons.append("gold_policy_mismatch")
        status = "NON_PRODUCTION"

    # 2. Provenance binding to current target
    bench_git_sha = manifest_data.get("git_sha", "")
    if target_git_sha and bench_git_sha != target_git_sha:
        ineligibility_reasons.append("benchmark_git_sha_mismatch")
        if status not in ("NON_PRODUCTION", "FAIL"):
            status = "STALE_SOURCE"

    bench_dataset_sha = manifest_data.get("dataset_sha256") or manifest_data.get("evaluation_dataset_sha256")
    if bench_dataset_sha != target_dataset_sha:
        ineligibility_reasons.append("benchmark_dataset_sha_mismatch")
        if status not in ("NON_PRODUCTION", "FAIL"):
            status = "STALE_SOURCE"

    bench_sidecar_sha = manifest_data.get("gold_label_sidecar_sha256")
    if bench_sidecar_sha != target_sidecar_sha:
        ineligibility_reasons.append("benchmark_sidecar_sha_mismatch")
        if status not in ("NON_PRODUCTION", "FAIL"):
            status = "STALE_SOURCE"

    if manifest_data.get("provenance_status") != "ok":
        ineligibility_reasons.append("benchmark_provenance_unavailable")
        if status not in ("NON_PRODUCTION", "FAIL", "STALE_SOURCE"):
            status = "INSUFFICIENT_EVIDENCE"

    git_dirty_val = manifest_data.get("git_dirty")
    if git_dirty_val is True:
        ineligibility_reasons.append("benchmark_source_dirty")
        if status not in ("NON_PRODUCTION", "FAIL", "STALE_SOURCE"):
            status = "INSUFFICIENT_EVIDENCE"
    elif git_dirty_val is not False or not isinstance(git_dirty_val, bool):
        ineligibility_reasons.append("benchmark_source_cleanliness_unproven")
        if status not in ("NON_PRODUCTION", "FAIL", "STALE_SOURCE"):
            status = "INSUFFICIENT_EVIDENCE"

    # 3. Exact Case Set Integrity Validation (F1)
    manifest_selected = manifest_data.get("selected_case_ids")
    manifest_case_sha = manifest_data.get("selected_case_ids_sha256")
    manifest_case_count = manifest_data.get("selected_case_count")

    case_set_valid = True

    if manifest_selected is None or not isinstance(manifest_selected, list):
        ineligibility_reasons.append("benchmark_manifest_case_set_mismatch")
        if status not in ("NON_PRODUCTION", "FAIL", "STALE_SOURCE"):
            status = "INSUFFICIENT_EVIDENCE"
        case_set_valid = False
    else:
        if len(manifest_selected) != len(set(manifest_selected)):
            ineligibility_reasons.append("benchmark_manifest_case_set_mismatch")
            if status not in ("NON_PRODUCTION", "FAIL", "STALE_SOURCE"):
                status = "INSUFFICIENT_EVIDENCE"
            case_set_valid = False

        recomputed_manifest_sha = hashlib.sha256(
            json.dumps(manifest_selected, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        if recomputed_manifest_sha != manifest_case_sha:
            ineligibility_reasons.append("benchmark_manifest_case_set_hash_invalid")
            if status not in ("NON_PRODUCTION", "FAIL", "STALE_SOURCE"):
                status = "INSUFFICIENT_EVIDENCE"
            case_set_valid = False

        if manifest_selected != target_selected_case_ids or manifest_case_count != len(target_selected_case_ids):
            ineligibility_reasons.append("benchmark_manifest_case_set_mismatch")
            if status not in ("NON_PRODUCTION", "FAIL", "STALE_SOURCE"):
                status = "INSUFFICIENT_EVIDENCE"
            case_set_valid = False

    if not isinstance(case_results_data, list):
        ineligibility_reasons.append("benchmark_results_case_set_mismatch")
        if status not in ("NON_PRODUCTION", "FAIL", "STALE_SOURCE"):
            status = "INSUFFICIENT_EVIDENCE"
        case_set_valid = False
    else:
        result_case_ids = [r.get("case_id") for r in case_results_data if isinstance(r, dict)]
        if len(result_case_ids) != len(set(result_case_ids)):
            ineligibility_reasons.append("benchmark_results_duplicate_case_ids")
            if status not in ("NON_PRODUCTION", "FAIL", "STALE_SOURCE"):
                status = "INSUFFICIENT_EVIDENCE"
            case_set_valid = False

        expected_ids = (
            manifest_selected
            if (manifest_selected is not None and isinstance(manifest_selected, list))
            else target_selected_case_ids
        )
        if result_case_ids != expected_ids:
            ineligibility_reasons.append("benchmark_results_case_set_mismatch")
            if status not in ("NON_PRODUCTION", "FAIL", "STALE_SOURCE"):
                status = "INSUFFICIENT_EVIDENCE"
            case_set_valid = False

    if not case_set_valid:
        return {
            "status": status,
            "readiness_eligible": False,
            "ineligibility_reasons": ineligibility_reasons,
            "benchmark_dir": str(bench_path),
            "manifest_sha256": manifest_sha,
            "results_sha256": results_sha,
            "manifest": manifest_data,
            "metrics": None,
            "threshold_evaluations": {},
        }

    # 4. Deterministic Metric Recomputation
    try:
        recomputed_metrics = aggregate_retrieval_metrics(case_results_data)
    except Exception as err:
        return {
            "status": "UNSUPPORTED",
            "readiness_eligible": False,
            "ineligibility_reasons": [f"metric_aggregation_error: {err}"],
            "benchmark_dir": str(bench_path),
            "manifest_sha256": manifest_sha,
            "results_sha256": results_sha,
            "manifest": manifest_data,
            "metrics": None,
            "threshold_evaluations": {},
        }

    # 5. Threshold evaluations (F2 & F3 fail-closed)
    thresholds: Dict[str, Dict[str, Any]] = {}
    thresholds_passed = True

    def _eval_threshold(
        metric_name: str,
        metric_data: Optional[Dict[str, Any]],
        required_val: float,
        op: Literal["gte", "lte", "eq"],
    ) -> None:
        nonlocal thresholds_passed
        if metric_data is None or not isinstance(metric_data, dict):
            thresholds[metric_name] = {
                "required": required_val,
                "observed": None,
                "status": "UNSUPPORTED",
                "reason": "metric_unavailable",
            }
            thresholds_passed = False
            return

        val = metric_data.get("micro") if metric_data.get("micro") is not None else metric_data.get("macro")
        denom = metric_data.get("denominator")

        # Validate denominator: must be numeric, finite, and > 0
        if denom is None or isinstance(denom, bool) or not isinstance(denom, (int, float)):
            thresholds[metric_name] = {
                "required": required_val,
                "observed": None,
                "status": "UNSUPPORTED",
                "reason": metric_data.get("reason") or "invalid_or_missing_denominator",
            }
            thresholds_passed = False
            return

        try:
            denom_float = float(denom)
        except (ValueError, TypeError):
            thresholds[metric_name] = {
                "required": required_val,
                "observed": None,
                "status": "UNSUPPORTED",
                "reason": metric_data.get("reason") or "invalid_denominator",
            }
            thresholds_passed = False
            return

        if not math.isfinite(denom_float) or denom_float <= 0:
            thresholds[metric_name] = {
                "required": required_val,
                "observed": None,
                "status": "UNSUPPORTED",
                "reason": metric_data.get("reason") or "zero_or_non_finite_denominator",
            }
            thresholds_passed = False
            return

        # Validate observed value: must be numeric and finite
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            thresholds[metric_name] = {
                "required": required_val,
                "observed": None,
                "status": "UNSUPPORTED",
                "reason": metric_data.get("reason") or "invalid_or_missing_observed_value",
            }
            thresholds_passed = False
            return

        try:
            val_float = float(val)
        except (ValueError, TypeError):
            thresholds[metric_name] = {
                "required": required_val,
                "observed": None,
                "status": "UNSUPPORTED",
                "reason": metric_data.get("reason") or "invalid_observed_value",
            }
            thresholds_passed = False
            return

        if not math.isfinite(val_float):
            thresholds[metric_name] = {
                "required": required_val,
                "observed": None,
                "status": "UNSUPPORTED",
                "reason": metric_data.get("reason") or "non_finite_observed_value",
            }
            thresholds_passed = False
            return

        if op == "eq":
            passed = (val_float == required_val)
        elif op == "gte":
            passed = (val_float >= required_val)
        else:
            passed = (val_float <= required_val)

        thresholds[metric_name] = {
            "required": required_val,
            "observed": val_float,
            "status": "PASS" if passed else "FAIL",
        }
        if not passed:
            thresholds_passed = False

    # Document Recall @ 24
    doc_rec_dict = recomputed_metrics.get("document_recall", {})
    doc_rec_24 = doc_rec_dict.get(24) if 24 in doc_rec_dict else doc_rec_dict.get("24")
    _eval_threshold("document_recall_at_24", doc_rec_24, DOCUMENT_RECALL_FLOOR, "eq")

    # Article Recall @ 24 (STRICT @ 24, never @ 6)
    art_rec_dict = recomputed_metrics.get("article_recall", {})
    art_rec_24 = art_rec_dict.get(24) if 24 in art_rec_dict else art_rec_dict.get("24")
    _eval_threshold("article_recall_at_24", art_rec_24, ARTICLE_RECALL_FLOOR, "gte")

    # Clause Recall @ 24 (STRICT @ 24, never @ 6)
    cl_rec_dict = recomputed_metrics.get("clause_recall", {})
    cl_rec_24 = cl_rec_dict.get(24) if 24 in cl_rec_dict else cl_rec_dict.get("24")
    _eval_threshold("clause_recall_at_24", cl_rec_24, CLAUSE_RECALL_FLOOR, "gte")

    # Multi-hop all required coverage
    all_req = recomputed_metrics.get("multi_hop_all_required")
    _eval_threshold("multi_hop_all_required", all_req, ALL_REQUIRED_COVERAGE_FLOOR, "gte")

    # Operational rates in benchmark
    no_cand = recomputed_metrics.get("no_candidate_rate")
    _eval_threshold("no_candidate_rate", no_cand, NO_CANDIDATE_RATE_CEILING, "eq")

    ret_err = recomputed_metrics.get("retrieval_technical_error_rate")
    _eval_threshold("retrieval_technical_error_rate", ret_err, RETRIEVAL_ERROR_RATE_CEILING, "eq")

    rer_err = recomputed_metrics.get("reranker_technical_error_rate")
    _eval_threshold("reranker_technical_error_rate", rer_err, RERANKER_ERROR_RATE_CEILING, "eq")

    has_unsupported = any(t.get("status") == "UNSUPPORTED" for t in thresholds.values())
    has_fail = any(t.get("status") == "FAIL" for t in thresholds.values())

    if has_unsupported:
        if status not in ("NON_PRODUCTION", "STALE_SOURCE", "INSUFFICIENT_EVIDENCE"):
            status = "UNSUPPORTED"
        ineligibility_reasons.append("unsupported_or_missing_benchmark_metrics")

    if has_fail:
        if status not in ("NON_PRODUCTION", "STALE_SOURCE", "INSUFFICIENT_EVIDENCE", "UNSUPPORTED"):
            status = "FAIL"
        ineligibility_reasons.append("retrieval_quality_thresholds_failed")

    readiness_eligible = (status == "PASS" and not ineligibility_reasons)

    return {
        "status": status,
        "readiness_eligible": readiness_eligible,
        "ineligibility_reasons": ineligibility_reasons,
        "benchmark_dir": str(bench_path),
        "manifest_sha256": manifest_sha,
        "results_sha256": results_sha,
        "manifest": manifest_data,
        "metrics": recomputed_metrics,
        "threshold_evaluations": thresholds,
    }


def load_online_snapshot(snapshot_path: Optional[Path]) -> Dict[str, Any]:
    if snapshot_path is None:
        return {
            "status": "NOT_AVAILABLE",
            "snapshot_path": None,
            "snapshot_sha256": None,
            "record_count": 0,
            "online_proxy": {
                "status": "NOT_AVAILABLE",
                "proxy_designation": "NON_GOLD_NON_GATING_PROXY",
                "record_count": 0,
                "ragas_mode_breakdown": {},
                "ragas_selected_count": 0,
                "ragas_executed_count": 0,
                "ragas_status_breakdown": {},
                "faithfulness": {"observed_count": 0, "missing_count": 0, "mean": None},
                "answer_relevance": {"observed_count": 0, "missing_count": 0, "mean": None},
                "ragas_error_count": 0,
            },
            "operational_reliability": {
                "status": "NOT_AVAILABLE",
                "request_count": 0,
                "request_status_breakdown": {},
                "technical_error": {"count": 0, "rate": None},
                "no_evidence": {"count": 0, "rate": None},
                "context_present": {"count": 0, "rate": None},
                "latency_summary": {
                    "count": 0,
                    "mean": None,
                    "p50": None,
                    "p95": None,
                    "min": None,
                    "max": None,
                },
                "observed_provider_breakdown": {},
                "observed_model_breakdown": {},
                "telemetry_completeness": {"complete_records": 0, "completeness_rate": None},
                "fallback_usage_observed": None,
            },
            "user_feedback": {
                "status": "NOT_AVAILABLE",
                "feedback_observed_count": 0,
                "positive_count": 0,
                "negative_count": 0,
                "response_rate": None,
                "positive_rate": None,
            },
        }

    p = Path(snapshot_path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Online snapshot file not found: {p}")

    snapshot_sha = hash_file_sha256(p)
    raw_content = json.loads(p.read_bytes().decode("utf-8"))
    records: List[Dict[str, Any]] = raw_content if isinstance(raw_content, list) else raw_content.get("records", [])

    total_records = len(records)
    if total_records == 0:
        return {
            "status": "NOT_AVAILABLE",
            "snapshot_path": str(p),
            "snapshot_sha256": snapshot_sha,
            "record_count": 0,
            "online_proxy": {
                "status": "NOT_AVAILABLE",
                "proxy_designation": "NON_GOLD_NON_GATING_PROXY",
                "record_count": 0,
                "ragas_mode_breakdown": {},
                "ragas_selected_count": 0,
                "ragas_executed_count": 0,
                "ragas_status_breakdown": {},
                "faithfulness": {"observed_count": 0, "missing_count": 0, "mean": None},
                "answer_relevance": {"observed_count": 0, "missing_count": 0, "mean": None},
                "ragas_error_count": 0,
            },
            "operational_reliability": {
                "status": "NOT_AVAILABLE",
                "request_count": 0,
                "request_status_breakdown": {},
                "technical_error": {"count": 0, "rate": None},
                "no_evidence": {"count": 0, "rate": None},
                "context_present": {"count": 0, "rate": None},
                "latency_summary": {"count": 0, "mean": None, "p50": None, "p95": None, "min": None, "max": None},
                "observed_provider_breakdown": {},
                "observed_model_breakdown": {},
                "telemetry_completeness": {"complete_records": 0, "completeness_rate": None},
                "fallback_usage_observed": None,
            },
            "user_feedback": {
                "status": "NOT_AVAILABLE",
                "feedback_observed_count": 0,
                "positive_count": 0,
                "negative_count": 0,
                "response_rate": None,
                "positive_rate": None,
            },
        }

    # Aggregate Operational Reliability
    status_counts: Dict[str, int] = {}
    tech_err_count = 0
    no_ev_count = 0
    context_present_count = 0
    latencies: List[float] = []
    provider_counts: Dict[str, int] = {}
    model_counts: Dict[str, int] = {}
    complete_telemetry_count = 0

    # Aggregate Ragas Proxy
    ragas_modes: Dict[str, int] = {}
    ragas_selected_cnt = 0
    ragas_executed_cnt = 0
    ragas_status_counts: Dict[str, int] = {}
    faithfulness_scores: List[float] = []
    relevance_scores: List[float] = []
    ragas_error_count = 0

    # Aggregate User Feedback
    feedback_count = 0
    positive_count = 0
    negative_count = 0

    for rec in records:
        # Check if record has top-level fields or nested metrics
        metrics = rec.get("metrics", rec)
        fb = rec.get("feedback", {})

        req_status = metrics.get("request_status", "unknown")
        status_counts[req_status] = status_counts.get(req_status, 0) + 1

        if req_status in ("technical_error", "retrieval_error", "reranker_error") or metrics.get("technical_error"):
            tech_err_count += 1

        if metrics.get("no_evidence") is True or req_status == "no_evidence":
            no_ev_count += 1

        ctx_cnt = metrics.get("context_count", 0)
        if ctx_cnt > 0:
            context_present_count += 1

        lat_info = metrics.get("latency", {})
        if isinstance(lat_info, dict):
            tot_lat = lat_info.get("t_total") or lat_info.get("total")
            if isinstance(tot_lat, (int, float)):
                latencies.append(float(tot_lat))
        elif isinstance(lat_info, (int, float)):
            latencies.append(float(lat_info))

        prov = str(metrics.get("observed_provider", "unobserved"))
        provider_counts[prov] = provider_counts.get(prov, 0) + 1

        mod = str(metrics.get("observed_model", "unobserved"))
        model_counts[mod] = model_counts.get(mod, 0) + 1

        if rec.get("trace_id") and "request_status" in metrics:
            complete_telemetry_count += 1

        # Ragas
        rmode = metrics.get("ragas_mode", "off")
        ragas_modes[rmode] = ragas_modes.get(rmode, 0) + 1

        if metrics.get("ragas_selected") is True:
            ragas_selected_cnt += 1
        if metrics.get("ragas_executed") is True:
            ragas_executed_cnt += 1

        rstatus = metrics.get("ragas_status", "disabled")
        ragas_status_counts[rstatus] = ragas_status_counts.get(rstatus, 0) + 1

        if metrics.get("ragas_error") or metrics.get("ragas_proxy_error") or rstatus == "failed":
            ragas_error_count += 1

        f_score = metrics.get("ragas_proxy_faithfulness")
        if isinstance(f_score, (int, float)):
            faithfulness_scores.append(float(f_score))

        r_score = metrics.get("ragas_proxy_answer_relevance")
        if isinstance(r_score, (int, float)):
            relevance_scores.append(float(r_score))

        # Feedback
        rating = fb.get("rating") if isinstance(fb, dict) else None
        if rating is not None:
            feedback_count += 1
            if rating in ("up", "positive", 1, True, "1"):
                positive_count += 1
            elif rating in ("down", "negative", -1, False, "0", "-1"):
                negative_count += 1

    # Summarize Latency
    lat_summary = {
        "count": len(latencies),
        "mean": round(sum(latencies) / len(latencies), 4) if latencies else None,
        "p50": compute_percentile(latencies, 0.50),
        "p95": compute_percentile(latencies, 0.95),
        "min": round(min(latencies), 4) if latencies else None,
        "max": round(max(latencies), 4) if latencies else None,
    }

    op_rel = {
        "status": "AVAILABLE",
        "request_count": total_records,
        "request_status_breakdown": status_counts,
        "technical_error": {
            "count": tech_err_count,
            "rate": round(tech_err_count / total_records, 4) if total_records else None,
        },
        "no_evidence": {
            "count": no_ev_count,
            "rate": round(no_ev_count / total_records, 4) if total_records else None,
        },
        "context_present": {
            "count": context_present_count,
            "rate": round(context_present_count / total_records, 4) if total_records else None,
        },
        "latency_summary": lat_summary,
        "observed_provider_breakdown": provider_counts,
        "observed_model_breakdown": model_counts,
        "telemetry_completeness": {
            "complete_records": complete_telemetry_count,
            "completeness_rate": round(complete_telemetry_count / total_records, 4) if total_records else None,
        },
        "fallback_usage_observed": None,
    }

    online_proxy = {
        "status": "AVAILABLE",
        "proxy_designation": "NON_GOLD_NON_GATING_PROXY",
        "record_count": total_records,
        "ragas_mode_breakdown": ragas_modes,
        "ragas_selected_count": ragas_selected_cnt,
        "ragas_executed_count": ragas_executed_cnt,
        "ragas_status_breakdown": ragas_status_counts,
        "faithfulness": {
            "observed_count": len(faithfulness_scores),
            "missing_count": total_records - len(faithfulness_scores),
            "mean": round(sum(faithfulness_scores) / len(faithfulness_scores), 4) if faithfulness_scores else None,
        },
        "answer_relevance": {
            "observed_count": len(relevance_scores),
            "missing_count": total_records - len(relevance_scores),
            "mean": round(sum(relevance_scores) / len(relevance_scores), 4) if relevance_scores else None,
        },
        "ragas_error_count": ragas_error_count,
    }

    user_feedback = {
        "status": "AVAILABLE" if feedback_count > 0 else "NOT_AVAILABLE",
        "feedback_observed_count": feedback_count,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "response_rate": round(feedback_count / total_records, 4) if total_records else None,
        "positive_rate": round(positive_count / feedback_count, 4) if feedback_count > 0 else None,
    }

    return {
        "status": "AVAILABLE",
        "snapshot_path": str(p),
        "snapshot_sha256": snapshot_sha,
        "record_count": total_records,
        "online_proxy": online_proxy,
        "operational_reliability": op_rel,
        "user_feedback": user_feedback,
    }


def evaluate_production_readiness(
    offline_quality: Dict[str, Any],
    benchmark_data: Dict[str, Any],
    operational_data: Dict[str, Any],
    online_proxy_data: Dict[str, Any],
    feedback_data: Dict[str, Any],
) -> Dict[str, Any]:
    blockers: List[str] = []

    # 1. Benchmark Gate
    bench_status = benchmark_data.get("status", "NOT_RUN")
    bench_reasons = benchmark_data.get("ineligibility_reasons", [])
    bench_eligible = benchmark_data.get("readiness_eligible", False)

    for r in bench_reasons:
        if r not in blockers:
            blockers.append(r)

    benchmark_gate = {
        "status": bench_status,
        "readiness_eligible": bench_eligible,
        "details": {
            "threshold_evaluations": benchmark_data.get("threshold_evaluations", {}),
            "ineligibility_reasons": bench_reasons,
        },
    }

    # 2. Verified Gold Coverage Gate (Always fail-closed / governance blocker unless separately approved)
    ev_cov = offline_quality.get("evidence_verification_coverage", {})
    verified_cases = ev_cov.get("all_required_verified_case_count", 0)
    total_cases = ev_cov.get("total_dataset_case_count", 0)
    case_cov_pct = round((verified_cases / total_cases) * 100, 2) if total_cases > 0 else 0.0

    verified_ev = ev_cov.get("verified_evidence_items", 0)
    total_ev = ev_cov.get("total_evidence_items", 0)
    ev_cov_pct = round((verified_ev / total_ev) * 100, 2) if total_ev > 0 else 0.0

    coverage_gate = {
        "status": "INSUFFICIENT_EVIDENCE",
        "governance_status": "UNRESOLVED_GOVERNANCE_BLOCKER",
        "verified_case_count": verified_cases,
        "total_case_count": total_cases,
        "case_coverage_pct": case_cov_pct,
        "verified_evidence_count": verified_ev,
        "total_evidence_count": total_ev,
        "evidence_coverage_pct": ev_cov_pct,
        "details": (
            f"Current verified slice covers {verified_cases}/{total_cases} ({case_cov_pct}%) cases "
            f"and {verified_ev}/{total_ev} ({ev_cov_pct}%) evidence items. Whole-production cutover "
            "requires approved verified coverage governance."
        ),
    }
    blockers.append("insufficient_verified_gold_coverage_governance")

    # 3. Observational Gates
    op_gate = {
        "status": "NON_GATING",
        "note": "Operational success does not prove answer correctness.",
        "request_count": operational_data.get("request_count", 0),
    }

    proxy_gate = {
        "status": "NON_GATING",
        "note": "Ragas is a non-gold, non-gating proxy.",
        "faithfulness_mean": online_proxy_data.get("faithfulness", {}).get("mean"),
        "answer_relevance_mean": online_proxy_data.get("answer_relevance", {}).get("mean"),
    }

    feedback_gate = {
        "status": "NON_GATING",
        "note": "Human sentiment does not prove retrieval correctness.",
        "positive_rate": feedback_data.get("positive_rate"),
    }

    # Deterministically order and deduplicate blockers
    sorted_blockers = sorted(list(dict.fromkeys(blockers)))

    final_status = "READY" if (bench_eligible and not sorted_blockers) else "NOT_PRODUCTION_READY"

    return {
        "status": final_status,
        "gates": {
            "production_benchmark_quality_gate": benchmark_gate,
            "verified_gold_coverage_gate": coverage_gate,
            "operational_reliability_gate": op_gate,
            "online_ragas_proxy_gate": proxy_gate,
            "human_feedback_gate": feedback_gate,
        },
        "blockers": sorted_blockers,
    }


def generate_markdown_decision_report(decision: Dict[str, Any]) -> str:
    prov = decision.get("provenance", {})
    layers = decision.get("layers", {})
    off = layers.get("offline_golden_quality", {})
    on = layers.get("online_no_gold_proxy", {})
    op = layers.get("operational_reliability", {})
    fb = layers.get("human_feedback", {})
    readiness = decision.get("production_readiness", {})

    status_str = readiness.get("status", "NOT_PRODUCTION_READY")

    lines: List[str] = [
        "# VIETLEX PRODUCTION-LIGHT DECISION PACKAGE",
        "",
        "## Executive Verdict",
        "",
        f"**PRODUCTION READINESS: `{status_str}`**  ",
        f"**Package ID**: `{decision.get('package_id')}`  ",
        f"**Schema Version**: `{decision.get('schema_version')}`  ",
        "",
        "## Evidence Provenance",
        "",
        "| Attribute | Value |",
        "| :--- | :--- |",
        f"| Builder Git SHA | `{prov.get('builder_git_sha')}` |",
        f"| Builder Source State SHA-256 | `{prov.get('builder_source_state_sha256') or 'unavailable'}` |",
        f"| Builder Git Dirty | `{prov.get('builder_git_dirty')}` |",
        f"| Dataset Path | `{prov.get('dataset_path')}` |",
        f"| Dataset SHA-256 | `{prov.get('dataset_sha256')}` |",
        f"| Sidecar Path | `{prov.get('sidecar_path')}` |",
        f"| Sidecar SHA-256 | `{prov.get('sidecar_sha256')}` |",
        f"| Selected Case Count | `{prov.get('selected_case_count')}` |",
        f"| Selected Case IDs SHA-256 | `{prov.get('selected_case_ids_sha256')}` |",
        f"| Production Benchmark Directory | `{prov.get('production_benchmark_path') or 'none'}` |",
        f"| Benchmark Manifest SHA-256 | `{prov.get('benchmark_manifest_sha256') or 'none'}` |",
        f"| Benchmark Results SHA-256 | `{prov.get('benchmark_results_sha256') or 'none'}` |",
        f"| Online Snapshot Path | `{prov.get('online_snapshot_path') or 'none'}` |",
        f"| Online Snapshot SHA-256 | `{prov.get('online_snapshot_sha256') or 'none'}` |",
        "",
        "## 1. Offline Golden Quality",
        "",
        "### Dataset Coverage",
        "",
        f"- Total cases: `{off.get('dataset_coverage', {}).get('total_cases', 0)}`",
        f"- Answerable cases: `{off.get('dataset_coverage', {}).get('answerable_cases', 0)}`",
        f"- Unanswerable cases: `{off.get('dataset_coverage', {}).get('unanswerable_cases', 0)}`",
        "",
        "### Evidence Verification Coverage",
        "",
        f"- Total evidence items: `{off.get('evidence_verification_coverage', {}).get('total_evidence_items', 0)}`",
        f"- Verified evidence items: `{off.get('evidence_verification_coverage', {}).get('verified_evidence_items', 0)}`",
        f"- Verified evidence coverage: `{off.get('evidence_verification_coverage', {}).get('verified_evidence_coverage', {}).get('value')}`",
        f"- All-required-verified cases: `{off.get('evidence_verification_coverage', {}).get('all_required_verified_case_count', 0)}`",
        f"- All-required-verified coverage: `{off.get('evidence_verification_coverage', {}).get('all_required_verified_case_coverage', {}).get('value')}`",
        f"- Unresolved required evidence: `{off.get('evidence_verification_coverage', {}).get('unresolved_required_evidence_count', 0)}`",
        "",
        "### Production Retrieval Benchmark",
        "",
        f"- Benchmark Status: `{off.get('production_retrieval_benchmark', {}).get('status')}`",
        f"- Readiness Eligible: `{off.get('production_retrieval_benchmark', {}).get('readiness_eligible')}`",
    ]

    bench_evals = off.get("production_retrieval_benchmark", {}).get("threshold_evaluations", {})
    if bench_evals:
        lines.extend(
            [
                "",
                "| Quality Gate Metric | Required Floor/Ceiling | Observed Value | Status |",
                "| :--- | :---: | :---: | :---: |",
            ]
        )
        for k, v in bench_evals.items():
            lines.append(f"| `{k}` | `{v.get('required')}` | `{v.get('observed')}` | `{v.get('status')}` |")

    lines.extend(
        [
            "",
            "## 2. Online No-Gold Proxy",
            "",
            f"- Status: `{on.get('status')}`",
            f"- Designation: `{on.get('proxy_designation')}`",
            f"- Record Count: `{on.get('record_count', 0)}`",
            f"- Ragas Selected / Executed: `{on.get('ragas_selected_count', 0)} / {on.get('ragas_executed_count', 0)}`",
            f"- Faithfulness (mean): `{on.get('faithfulness', {}).get('mean')}` (observed `{on.get('faithfulness', {}).get('observed_count', 0)}` / missing `{on.get('faithfulness', {}).get('missing_count', 0)}`)",
            f"- Answer Relevance (mean): `{on.get('answer_relevance', {}).get('mean')}` (observed `{on.get('answer_relevance', {}).get('observed_count', 0)}` / missing `{on.get('answer_relevance', {}).get('missing_count', 0)}`)",
            f"- Ragas Error Count: `{on.get('ragas_error_count', 0)}`",
            "",
            "## 3. Operational Reliability",
            "",
            f"- Status: `{op.get('status')}`",
            f"- Total Requests: `{op.get('request_count', 0)}`",
            f"- Technical Error Count / Rate: `{op.get('technical_error', {}).get('count', 0)}` / `{op.get('technical_error', {}).get('rate')}`",
            f"- No-Evidence Count / Rate: `{op.get('no_evidence', {}).get('count', 0)}` / `{op.get('no_evidence', {}).get('rate')}`",
            f"- Context Present Count / Rate: `{op.get('context_present', {}).get('count', 0)}` / `{op.get('context_present', {}).get('rate')}`",
            f"- Latency Mean / p50 / p95: `{op.get('latency_summary', {}).get('mean')}` / `{op.get('latency_summary', {}).get('p50')}` / `{op.get('latency_summary', {}).get('p95')}` s",
            f"- Telemetry Completeness Rate: `{op.get('telemetry_completeness', {}).get('completeness_rate')}`",
            "",
            "## 4. Human Feedback",
            "",
            "### Human Adjudication",
            "",
            f"- Total Evidence Count: `{fb.get('human_adjudication', {}).get('total_evidence_count', 0)}`",
            f"- Verified Evidence Count: `{fb.get('human_adjudication', {}).get('verified_evidence_count', 0)}`",
            f"- Required Unresolved Count: `{fb.get('human_adjudication', {}).get('required_unresolved_count', 0)}`",
            f"- All-Required-Verified Cases: `{fb.get('human_adjudication', {}).get('all_required_verified_case_count', 0)}`",
            "",
            "### User Feedback",
            "",
            f"- Status: `{fb.get('user_feedback', {}).get('status')}`",
            f"- Feedback Observed Count: `{fb.get('user_feedback', {}).get('feedback_observed_count', 0)}`",
            f"- Positive / Negative Counts: `{fb.get('user_feedback', {}).get('positive_count', 0)}` / `{fb.get('user_feedback', {}).get('negative_count', 0)}`",
            f"- Positive Rate: `{fb.get('user_feedback', {}).get('positive_rate')}`",
            "",
            "## 5. Production Readiness Gates",
            "",
            "| Gate | Status | Notes / Blockers |",
            "| :--- | :---: | :--- |",
        ]
    )

    gates = readiness.get("gates", {})
    for gname, ginfo in sorted(gates.items()):
        gst = ginfo.get("status")
        gnote = ginfo.get("note") or ginfo.get("details") or ""
        lines.append(f"| `{gname}` | `{gst}` | {gnote} |")

    lines.extend(
        [
            "",
            "## 6. Blockers / Missing Evidence",
            "",
        ]
    )

    blockers = readiness.get("blockers", [])
    if not blockers:
        lines.append("None.")
    else:
        for idx, b in enumerate(blockers, start=1):
            lines.append(f"{idx}. `{b}`")

    lines.extend(
        [
            "",
            "## Interpretation Boundaries",
            "",
            "- Operational success does not prove answer correctness.",
            "- Ragas is a non-gold, non-gating proxy.",
            "- Human sentiment does not prove retrieval correctness.",
            "- P3 partial evidence is excluded from production readiness.",
            "- Missing evidence is not represented as zero.",
            "- No composite quality score is produced.",
            "",
        ]
    )

    return "\n".join(lines)


class DecisionPackageBuilder:
    def __init__(
        self,
        dataset_path: Path,
        sidecar_path: Path,
        output_dir: Path,
        production_benchmark_dir: Optional[Path] = None,
        online_snapshot_path: Optional[Path] = None,
        package_id: Optional[str] = None,
        target_git_sha: Optional[str] = None,
        gold_policy: str = "all-required-verified",
    ) -> None:
        self.dataset_path = Path(dataset_path).resolve()
        self.sidecar_path = Path(sidecar_path).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.production_benchmark_dir = Path(production_benchmark_dir).resolve() if production_benchmark_dir else None
        self.online_snapshot_path = Path(online_snapshot_path).resolve() if online_snapshot_path else None
        if package_id is not None:
            validate_package_id(package_id, self.output_dir)
        self.package_id = package_id
        self.target_git_sha = target_git_sha
        self.gold_policy = gold_policy

    def build(self) -> DecisionPackageResult:
        provenance = collect_git_provenance()
        effective_git_sha = self.target_git_sha or provenance.git_sha

        dataset_sha = hash_file_sha256(self.dataset_path)
        sidecar_sha = hash_file_sha256(self.sidecar_path)

        # 1. Offline Golden Quality & Selection
        offline_quality, selection, sidecar = load_and_evaluate_offline_golden_quality(
            self.dataset_path,
            self.sidecar_path,
            gold_policy=self.gold_policy,
        )

        # 2. Production Benchmark Evaluation
        benchmark_data = load_production_benchmark(
            self.production_benchmark_dir,
            target_git_sha=effective_git_sha,
            target_dataset_sha=dataset_sha,
            target_sidecar_sha=sidecar_sha,
            target_selected_case_ids=selection.selected_case_ids,
            target_selected_case_ids_sha=selection.selected_case_ids_sha256,
        )
        offline_quality["production_retrieval_benchmark"] = benchmark_data

        # 3. Online Snapshot Loading & Aggregation
        snapshot_agg = load_online_snapshot(self.online_snapshot_path)
        online_proxy = snapshot_agg["online_proxy"]
        operational_rel = snapshot_agg["operational_reliability"]
        user_feedback = snapshot_agg["user_feedback"]

        # 4. Human Feedback Layer
        ev_cov = offline_quality["evidence_verification_coverage"]
        human_adjudication = {
            "total_evidence_count": ev_cov["total_evidence_items"],
            "verified_evidence_count": ev_cov["verified_evidence_items"],
            "status_breakdown": ev_cov["status_breakdown"],
            "required_unresolved_count": ev_cov["unresolved_required_evidence_count"],
            "all_required_verified_case_count": ev_cov["all_required_verified_case_count"],
        }
        human_feedback_layer = {
            "human_adjudication": human_adjudication,
            "user_feedback": user_feedback,
        }

        # 5. Production Readiness Evaluation
        readiness = evaluate_production_readiness(
            offline_quality,
            benchmark_data,
            operational_rel,
            online_proxy,
            user_feedback,
        )

        # 6. Package Identity & Directory Resolution
        if self.package_id:
            pkg_id = self.package_id
            pkg_dir = validate_package_id(pkg_id, self.output_dir)
        else:
            seed_data = {
                "dataset_sha256": dataset_sha,
                "sidecar_sha256": sidecar_sha,
                "benchmark_manifest_sha256": benchmark_data.get("manifest_sha256"),
                "online_snapshot_sha256": snapshot_agg.get("snapshot_sha256"),
                "builder_git_sha": effective_git_sha,
                "gold_policy": self.gold_policy,
                "selected_case_ids_sha256": selection.selected_case_ids_sha256,
            }
            seed_bytes = canonical_json_bytes(seed_data)
            seed_hash = hashlib.sha256(seed_bytes).hexdigest()[:16]
            pkg_id = f"pkg_{seed_hash}"
            pkg_dir = validate_package_id(pkg_id, self.output_dir)

        # 7. Assemble Document
        decision_doc: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "package_id": pkg_id,
            "provenance": {
                "builder_git_sha": provenance.git_sha,
                "builder_source_state_sha256": provenance.source_state_sha256,
                "builder_git_dirty": provenance.git_dirty,
                "dataset_path": str(self.dataset_path),
                "dataset_sha256": dataset_sha,
                "sidecar_path": str(self.sidecar_path),
                "sidecar_sha256": sidecar_sha,
                "production_benchmark_path": str(self.production_benchmark_dir) if self.production_benchmark_dir else None,
                "benchmark_manifest_sha256": benchmark_data.get("manifest_sha256"),
                "benchmark_results_sha256": benchmark_data.get("results_sha256"),
                "online_snapshot_path": str(self.online_snapshot_path) if self.online_snapshot_path else None,
                "online_snapshot_sha256": snapshot_agg.get("snapshot_sha256"),
                "gold_policy": self.gold_policy,
                "selected_case_count": len(selection.selected_case_ids),
                "selected_case_ids_sha256": selection.selected_case_ids_sha256,
                "metric_version": METRIC_VERSION,
            },
            "layers": {
                "offline_golden_quality": offline_quality,
                "online_no_gold_proxy": online_proxy,
                "operational_reliability": operational_rel,
                "human_feedback": human_feedback_layer,
            },
            "production_readiness": readiness,
        }

        # 8. Write immutable artifacts
        pkg_dir.mkdir(parents=True, exist_ok=True)

        decision_file = pkg_dir / "decision.json"
        report_file = pkg_dir / "report.md"

        write_status = write_immutable_json(decision_file, decision_doc)

        report_content = generate_markdown_decision_report(decision_doc)
        report_bytes = (report_content + "\n").encode("utf-8")

        if report_file.exists():
            if report_file.read_bytes() != report_bytes:
                raise ArtifactCollisionError(
                    f"Report artifact already exists with different bytes: {report_file}"
                )
        else:
            temp_report = report_file.with_suffix(".tmp")
            with temp_report.open("wb") as f:
                f.write(report_bytes)
                f.flush()
                os.fsync(f.fileno())
            temp_report.replace(report_file)

        return DecisionPackageResult(
            package_id=pkg_id,
            package_dir=pkg_dir,
            decision_file=decision_file,
            report_file=report_file,
            decision_dict=decision_doc,
            report_content=report_content,
            write_status=write_status,
        )


def build_decision_package(
    dataset_path: Path,
    sidecar_path: Path,
    output_dir: Path,
    production_benchmark_dir: Optional[Path] = None,
    online_snapshot_path: Optional[Path] = None,
    package_id: Optional[str] = None,
    target_git_sha: Optional[str] = None,
    gold_policy: str = "all-required-verified",
) -> DecisionPackageResult:
    builder = DecisionPackageBuilder(
        dataset_path=dataset_path,
        sidecar_path=sidecar_path,
        output_dir=output_dir,
        production_benchmark_dir=production_benchmark_dir,
        online_snapshot_path=online_snapshot_path,
        package_id=package_id,
        target_git_sha=target_git_sha,
        gold_policy=gold_policy,
    )
    return builder.build()
