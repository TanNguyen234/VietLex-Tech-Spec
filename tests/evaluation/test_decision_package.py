from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from app.evaluation.artifact_io import ArtifactCollisionError, canonical_json_bytes
from app.evaluation.decision_package import (
    DecisionPackageBuilder,
    build_decision_package,
    load_production_benchmark,
    load_online_snapshot,
    evaluate_production_readiness,
)
from app.evaluation.gold_sidecar import load_gold_sidecar
from app.evaluation.case_selection import build_cases, select_evaluation_cases


APPROVED_DATASET_PATH = Path("app/data/namsyntax_legal_qa_420_curated_v1.json")
APPROVED_SIDECAR_PATH = Path(
    "docs/evaluation/adjudication/promotions/gold-adjudication-promotion-curated-v4_20260809_151015_227377/labels_v2.json"
)


def _create_minimal_dataset(tmp_path: Path) -> Path:
    dataset_file = tmp_path / "dataset.json"
    data = [
        {
            "case_id": "case_001",
            "question": "Câu hỏi số 1?",
            "question_type": "factoid",
            "ground_truth_answer": "Đáp án 1",
            "ground_truth_context": ["Context 1"],
        },
        {
            "case_id": "case_002",
            "question": "Câu hỏi số 2?",
            "question_type": "factoid",
            "ground_truth_answer": "Đáp án 2",
            "ground_truth_context": ["Context 2"],
        },
    ]
    dataset_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return dataset_file


def _create_minimal_sidecar(tmp_path: Path) -> Path:
    sidecar_file = tmp_path / "sidecar.json"
    data = {
        "schema_version": "2.0.0",
        "dataset_name": "test_dataset",
        "total_cases": 2,
        "total_evidence_items": 2,
        "labels": [
            {
                "evidence_item_id": "ev_001",
                "case_id": "case_001",
                "document_id": 101,
                "document_number": "01/2024/ND-CP",
                "article": "Điều 1",
                "clause": "Khoản 1",
                "required": True,
                "required_level": "clause",
                "status": "verified",
            },
            {
                "evidence_item_id": "ev_002",
                "case_id": "case_002",
                "document_id": 102,
                "document_number": "02/2024/ND-CP",
                "article": "Điều 2",
                "clause": "Khoản 2",
                "required": True,
                "required_level": "clause",
                "status": "verified",
            },
        ],
    }
    sidecar_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return sidecar_file


def _create_valid_production_benchmark(
    tmp_path: Path,
    dataset_path: Path,
    sidecar_path: Path,
    selected_case_ids: List[str],
    selected_case_ids_sha256: str,
    git_sha: str,
    *,
    pass_all_thresholds: bool = True,
    entrypoint: str = "run_retrieval_eval.py",
    command: Optional[str] = None,
    eval_mode: str = "retrieval-only",
    judge_mode: str = "none",
    gold_policy: str = "all-required-verified",
    provenance_status: str = "ok",
    git_dirty: bool = False,
    manifest_selected_case_ids: Optional[List[str]] = None,
    manifest_selected_case_ids_sha: Optional[str] = None,
    case_results: Optional[List[Dict[str, Any]]] = None,
    include_k24: bool = True,
    missing_recall_key: bool = False,
    override_article_recall: Optional[Dict[Any, Any]] = None,
    override_clause_recall: Optional[Dict[Any, Any]] = None,
    override_all_required: Optional[Dict[str, Any]] = None,
    override_no_candidate: Optional[Dict[str, Any]] = None,
    override_retrieval_error: Optional[Dict[str, Any]] = None,
    override_reranker_error: Optional[Dict[str, Any]] = None,
) -> Path:
    benchmark_dir = tmp_path / "benchmark_run"
    benchmark_dir.mkdir(parents=True, exist_ok=True)

    dataset_sha = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    sidecar_sha = hashlib.sha256(sidecar_path.read_bytes()).hexdigest()

    m_case_ids = manifest_selected_case_ids if manifest_selected_case_ids is not None else selected_case_ids
    m_case_sha = (
        manifest_selected_case_ids_sha
        if manifest_selected_case_ids_sha is not None
        else selected_case_ids_sha256
    )
    cmd_str = (
        command
        if command is not None
        else f"python {entrypoint} --dataset {dataset_path} --sidecar {sidecar_path} --verified-only"
    )

    manifest_data = {
        "run_id": "benchmark-test-run-001",
        "utc_timestamp": "2026-08-18T12:00:00Z",
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "git_tracked_dirty": False,
        "git_staged_dirty": False,
        "git_untracked_dirty": False,
        "git_diff_sha256": None,
        "git_diff_status": "clean" if not git_dirty else "dirty",
        "source_state_sha256": "abcdef" * 10 + "1234",
        "provenance_status": provenance_status,
        "dataset_revision": "v1.0.0",
        "dataset_sha256": dataset_sha,
        "evaluation_dataset_sha256": dataset_sha,
        "gold_label_sidecar_sha256": sidecar_sha,
        "gold_policy": gold_policy,
        "selected_case_count": len(m_case_ids),
        "selected_case_ids": m_case_ids,
        "selected_case_ids_sha256": m_case_sha,
        "configuration_fingerprint": "fp123456",
        "command": cmd_str,
        "eval_mode": eval_mode,
        "judge_mode": judge_mode,
        "guardrail_mode": "off",
        "rewrite_mode": "off",
        "reranker_provider": "current",
        "profile_name": "separated_intent",
        "configuration": {
            "configured_provider_models": {
                "dense": {"provider": "qdrant-cloud-staging", "model": "intfloat/multilingual-e5-small"},
                "reranker_primary": {"provider": "qdrant", "model": "answerdotai/answerai-colbert-small-v1"},
                "reranker_fallback": {"provider": "pinecone", "model": "bge-reranker-v2-m3"},
            }
        },
        "configured_provider_models": {
            "dense": {"provider": "qdrant-cloud-staging", "model": "intfloat/multilingual-e5-small"},
            "reranker_primary": {"provider": "qdrant", "model": "answerdotai/answerai-colbert-small-v1"},
            "reranker_fallback": {"provider": "pinecone", "model": "bge-reranker-v2-m3"},
        },
    }
    (benchmark_dir / "manifest.json").write_text(
        json.dumps(manifest_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if case_results is not None:
        (benchmark_dir / "results.json").write_text(
            json.dumps(case_results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return benchmark_dir

    # Build case results using canonical calculate_case_retrieval_metrics
    from app.evaluation.retrieval_metrics import calculate_case_retrieval_metrics
    from app.evaluation.schemas import CandidateChunk, EvidenceStatus, GoldEvidence, RequiredLevel

    built_results = []
    for idx, cid in enumerate(selected_case_ids, start=1):
        gold_item = GoldEvidence(
            evidence_item_id=f"ev_{idx:03d}",
            case_id=cid,
            document_id=100 + idx,
            document_number=f"0{idx}/2024/ND-CP",
            article=f"Điều {idx}",
            clause=f"Khoản {idx}",
            required=True,
            required_level=RequiredLevel.CLAUSE,
            status=EvidenceStatus.VERIFIED,
        )
        if pass_all_thresholds:
            chunks = [
                CandidateChunk(
                    document_id=100 + idx,
                    document_number=f"0{idx}/2024/ND-CP",
                    title=f"Văn bản {idx}",
                    source_url=f"https://example.test/{idx}",
                    citation=f"Khoản {idx}, Điều {idx}, 0{idx}/2024/ND-CP",
                    article=f"Điều {idx}",
                    clause=f"Khoản {idx}",
                    text=f"Nội dung văn bản {idx}",
                    token_count=10,
                )
            ]
        else:
            chunks = []

        metrics_dict = calculate_case_retrieval_metrics([gold_item], chunks, status="ok")

        if include_k24 and not missing_recall_key:
            if "article_recall" in metrics_dict and 24 not in metrics_dict["article_recall"]:
                metrics_dict["article_recall"][24] = {
                    "numerator": 1 if pass_all_thresholds else 0,
                    "denominator": 1,
                    "value": 1.0 if pass_all_thresholds else 0.0,
                    "reason": None,
                }
            if "clause_recall" in metrics_dict and 24 not in metrics_dict["clause_recall"]:
                metrics_dict["clause_recall"][24] = {
                    "numerator": 1 if pass_all_thresholds else 0,
                    "denominator": 1,
                    "value": 1.0 if pass_all_thresholds else 0.0,
                    "reason": None,
                }

        if missing_recall_key:
            if 24 in metrics_dict.get("document_recall", {}):
                del metrics_dict["document_recall"][24]
            if "24" in metrics_dict.get("document_recall", {}):
                del metrics_dict["document_recall"]["24"]

        if override_article_recall is not None:
            metrics_dict["article_recall"] = (
                override_article_recall
                if override_article_recall != {}
                else {24: {"numerator": None, "denominator": None, "value": None, "reason": "unsupported"}}
            )
        if override_clause_recall is not None:
            metrics_dict["clause_recall"] = (
                override_clause_recall
                if override_clause_recall != {}
                else {24: {"numerator": None, "denominator": None, "value": None, "reason": "unsupported"}}
            )
        if override_all_required is not None:
            metrics_dict["multi_hop_all_required"] = (
                override_all_required
                if override_all_required != {}
                else {"numerator": None, "denominator": None, "value": None, "reason": "unsupported"}
            )
        if override_no_candidate is not None:
            metrics_dict["no_candidate_rate"] = (
                override_no_candidate
                if override_no_candidate != {}
                else {"numerator": None, "denominator": None, "value": None, "reason": "unsupported"}
            )
        if override_retrieval_error is not None:
            metrics_dict["retrieval_technical_error_rate"] = (
                override_retrieval_error
                if override_retrieval_error != {}
                else {"numerator": None, "denominator": None, "value": None, "reason": "unsupported"}
            )
        if override_reranker_error is not None:
            metrics_dict["reranker_technical_error_rate"] = (
                override_reranker_error
                if override_reranker_error != {}
                else {"numerator": None, "denominator": None, "value": None, "reason": "unsupported"}
            )

        built_results.append({
            "case_id": cid,
            "status": "ok",
            "metrics": metrics_dict,
        })

    (benchmark_dir / "results.json").write_text(
        json.dumps(built_results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return benchmark_dir


# ==============================================================================
# A. Layer Separation Tests
# ==============================================================================

def test_ragas_proxy_cannot_populate_offline_golden_metrics(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    snapshot_file = tmp_path / "online_snapshot.json"
    snapshot_data = [
        {
            "trace_id": "tr-001",
            "request_status": "ok",
            "latency": {"t_total": 0.5},
            "context_count": 2,
            "citation_count": 1,
            "no_evidence": False,
            "observed_provider": "openrouter",
            "observed_model": "google/gemini-2.5-flash",
            "ragas_mode": "all",
            "ragas_selected": True,
            "ragas_executed": True,
            "ragas_status": "executed",
            "ragas_proxy_faithfulness": 0.99,
            "ragas_proxy_answer_relevance": 0.98,
        }
    ]
    snapshot_file.write_text(json.dumps(snapshot_data), encoding="utf-8")

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        online_snapshot_path=snapshot_file,
        output_dir=out_dir,
    )

    decision = pkg.decision_dict
    offline_layer = decision["layers"]["offline_golden_quality"]
    online_layer = decision["layers"]["online_no_gold_proxy"]

    # Ragas scores must only appear in online_no_gold_proxy layer
    assert online_layer["faithfulness"]["mean"] == 0.99
    assert online_layer["answer_relevance"]["mean"] == 0.98
    assert online_layer["proxy_designation"] == "NON_GOLD_NON_GATING_PROXY"

    # Offline golden quality must not contain ragas metrics
    offline_json_str = json.dumps(offline_layer).lower()
    assert "ragas" not in offline_json_str
    assert "faithfulness" not in offline_json_str
    assert "answer_relevance" not in offline_json_str


def test_decision_artifact_contains_no_composite_quality_score(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        output_dir=out_dir,
    )
    decision = pkg.decision_dict

    forbidden_fields = [
        "overall_score",
        "quality_score",
        "readiness_score",
        "weighted_score",
        "combined_score",
    ]

    def _check_no_forbidden(d: Any) -> None:
        if isinstance(d, dict):
            for k, v in d.items():
                for forbidden in forbidden_fields:
                    assert forbidden not in k.lower(), f"Forbidden field '{forbidden}' found in key '{k}'"
                _check_no_forbidden(v)
        elif isinstance(d, list):
            for item in d:
                _check_no_forbidden(item)

    _check_no_forbidden(decision)


# ==============================================================================
# B. Missing-Data Semantics Tests
# ==============================================================================

def test_missing_benchmark_is_not_run_not_zero(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=None,
        output_dir=out_dir,
    )
    benchmark_layer = pkg.decision_dict["layers"]["offline_golden_quality"]["production_retrieval_benchmark"]

    assert benchmark_layer["status"] == "NOT_RUN"
    assert benchmark_layer["metrics"] is None


def test_missing_online_snapshot_is_not_available_not_zero(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        online_snapshot_path=None,
        output_dir=out_dir,
    )
    decision = pkg.decision_dict
    online_proxy = decision["layers"]["online_no_gold_proxy"]
    op_rel = decision["layers"]["operational_reliability"]
    user_fb = decision["layers"]["human_feedback"]["user_feedback"]

    assert online_proxy["status"] == "NOT_AVAILABLE"
    assert op_rel["status"] == "NOT_AVAILABLE"
    assert user_fb["status"] == "NOT_AVAILABLE"

    # Must NOT be represented as numeric zero
    assert online_proxy.get("record_count") is None or online_proxy.get("record_count") == 0
    assert user_fb.get("positive_rate") is None


def test_missing_ragas_score_remains_null(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    snapshot_file = tmp_path / "online_snapshot.json"
    snapshot_data = [
        {
            "trace_id": "tr-001",
            "request_status": "ok",
            "latency": {"t_total": 0.5},
            "ragas_mode": "off",
            "ragas_selected": False,
            "ragas_executed": False,
            "ragas_status": "disabled",
            "ragas_proxy_faithfulness": None,
            "ragas_proxy_answer_relevance": None,
        }
    ]
    snapshot_file.write_text(json.dumps(snapshot_data), encoding="utf-8")

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        online_snapshot_path=snapshot_file,
        output_dir=out_dir,
    )
    online_proxy = pkg.decision_dict["layers"]["online_no_gold_proxy"]

    assert online_proxy["faithfulness"]["observed_count"] == 0
    assert online_proxy["faithfulness"]["mean"] is None
    assert online_proxy["answer_relevance"]["observed_count"] == 0
    assert online_proxy["answer_relevance"]["mean"] is None


def test_missing_human_feedback_remains_not_available(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    snapshot_file = tmp_path / "online_snapshot.json"
    snapshot_data = [
        {
            "trace_id": "tr-001",
            "request_status": "ok",
            # No feedback key
        }
    ]
    snapshot_file.write_text(json.dumps(snapshot_data), encoding="utf-8")

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        online_snapshot_path=snapshot_file,
        output_dir=out_dir,
    )
    user_fb = pkg.decision_dict["layers"]["human_feedback"]["user_feedback"]

    assert user_fb["feedback_observed_count"] == 0
    assert user_fb["positive_rate"] is None


# ==============================================================================
# C. Verdict Fail-Closed Tests
# ==============================================================================

def test_no_production_benchmark_means_not_production_ready(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=None,
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]

    assert readiness["status"] == "NOT_PRODUCTION_READY"
    assert "missing_production_retrieval_benchmark" in readiness["blockers"]


def test_stale_production_benchmark_means_not_production_ready(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    benchmark_dir = _create_valid_production_benchmark(
        tmp_path,
        dataset_file,
        sidecar_file,
        ["case_001", "case_002"],
        hashlib.sha256(json.dumps(["case_001", "case_002"], separators=(",", ":")).encode()).hexdigest(),
        git_sha="stale_sha_9999999999",
        pass_all_thresholds=True,
    )

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=benchmark_dir,
        target_git_sha="current_sha_1111111111",
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]

    assert readiness["status"] == "NOT_PRODUCTION_READY"
    benchmark_gate = readiness["gates"]["production_benchmark_quality_gate"]
    assert benchmark_gate["status"] == "STALE_SOURCE"
    assert "benchmark_git_sha_mismatch" in readiness["blockers"]


# ==============================================================================
# D. P3 and Structural Pilot Exclusion Tests
# ==============================================================================

def test_p3_partial_evidence_cannot_satisfy_production_gate(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    benchmark_dir = _create_valid_production_benchmark(
        tmp_path,
        dataset_file,
        sidecar_file,
        ["case_001", "case_002"],
        hashlib.sha256(json.dumps(["case_001", "case_002"], separators=(",", ":")).encode()).hexdigest(),
        git_sha="current_sha",
        entrypoint="run_pinecone_structural_eval.py",  # P3 / structural runner
        pass_all_thresholds=True,
    )

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=benchmark_dir,
        target_git_sha="current_sha",
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]

    assert readiness["status"] == "NOT_PRODUCTION_READY"
    benchmark_gate = readiness["gates"]["production_benchmark_quality_gate"]
    assert benchmark_gate["status"] == "NON_PRODUCTION"
    assert "non_production_benchmark_route" in readiness["blockers"]


def test_structural_pilot_pass_cannot_satisfy_production_gate(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    benchmark_dir = _create_valid_production_benchmark(
        tmp_path,
        dataset_file,
        sidecar_file,
        ["case_001", "case_002"],
        hashlib.sha256(json.dumps(["case_001", "case_002"], separators=(",", ":")).encode()).hexdigest(),
        git_sha="current_sha",
        entrypoint="run_structural_retrieval_eval.py",  # Structural pilot runner
        pass_all_thresholds=True,
    )

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=benchmark_dir,
        target_git_sha="current_sha",
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]

    assert readiness["status"] == "NOT_PRODUCTION_READY"
    benchmark_gate = readiness["gates"]["production_benchmark_quality_gate"]
    assert benchmark_gate["status"] == "NON_PRODUCTION"


# ==============================================================================
# E. Operational != Quality Isolation Test
# ==============================================================================

def test_100_percent_operational_success_cannot_mark_ready(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    # Construct snapshot with 100% operational success
    snapshot_file = tmp_path / "online_snapshot.json"
    snapshot_data = [
        {
            "trace_id": f"tr-{idx}",
            "request_status": "ok",
            "latency": {"t_total": 0.1},
            "context_count": 3,
            "citation_count": 2,
            "no_evidence": False,
            "observed_provider": "openrouter",
            "observed_model": "google/gemini-2.5-flash",
        }
        for idx in range(50)
    ]
    snapshot_file.write_text(json.dumps(snapshot_data), encoding="utf-8")

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=None,
        online_snapshot_path=snapshot_file,
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]

    # Even with 100% operational success, without quality evidence, status MUST be NOT_PRODUCTION_READY
    assert readiness["status"] == "NOT_PRODUCTION_READY"


# ==============================================================================
# F. Human Feedback Isolation Test
# ==============================================================================

def test_100_percent_positive_feedback_cannot_mark_ready(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    snapshot_file = tmp_path / "online_snapshot.json"
    snapshot_data = [
        {
            "trace_id": f"tr-{idx}",
            "request_status": "ok",
            "feedback": {"rating": "up"},
        }
        for idx in range(20)
    ]
    snapshot_file.write_text(json.dumps(snapshot_data), encoding="utf-8")

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=None,
        online_snapshot_path=snapshot_file,
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]

    assert readiness["status"] == "NOT_PRODUCTION_READY"


# ==============================================================================
# G. Actual Production Benchmark Gate Tests
# ==============================================================================

def test_actual_production_route_benchmark_may_satisfy_quality_gate(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    selected_ids = ["case_001", "case_002"]
    selected_sha = hashlib.sha256(json.dumps(selected_ids, separators=(",", ":")).encode()).hexdigest()

    benchmark_dir = _create_valid_production_benchmark(
        tmp_path,
        dataset_file,
        sidecar_file,
        selected_ids,
        selected_sha,
        git_sha="target_sha_123",
        pass_all_thresholds=True,
    )

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=benchmark_dir,
        target_git_sha="target_sha_123",
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]
    benchmark_gate = readiness["gates"]["production_benchmark_quality_gate"]

    # Benchmark quality gate satisfies PASS
    assert benchmark_gate["status"] == "PASS"

    # But overall production readiness remains NOT_PRODUCTION_READY due to verified-gold coverage governance blocker
    assert readiness["status"] == "NOT_PRODUCTION_READY"
    assert "insufficient_verified_gold_coverage_governance" in readiness["blockers"]


def test_production_benchmark_fails_when_any_required_threshold_fails(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    selected_ids = ["case_001", "case_002"]
    selected_sha = hashlib.sha256(json.dumps(selected_ids, separators=(",", ":")).encode()).hexdigest()

    benchmark_dir = _create_valid_production_benchmark(
        tmp_path,
        dataset_file,
        sidecar_file,
        selected_ids,
        selected_sha,
        git_sha="target_sha_123",
        pass_all_thresholds=False,  # Fails recall thresholds
    )

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=benchmark_dir,
        target_git_sha="target_sha_123",
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]
    benchmark_gate = readiness["gates"]["production_benchmark_quality_gate"]

    assert benchmark_gate["status"] == "FAIL"
    assert "retrieval_quality_thresholds_failed" in readiness["blockers"]


def test_production_benchmark_with_unsupported_metric_does_not_pass(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    selected_ids = ["case_001", "case_002"]
    selected_sha = hashlib.sha256(json.dumps(selected_ids, separators=(",", ":")).encode()).hexdigest()

    benchmark_dir = _create_valid_production_benchmark(
        tmp_path,
        dataset_file,
        sidecar_file,
        selected_ids,
        selected_sha,
        git_sha="target_sha_123",
        pass_all_thresholds=True,
        missing_recall_key=True,
    )

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=benchmark_dir,
        target_git_sha="target_sha_123",
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]
    benchmark_gate = readiness["gates"]["production_benchmark_quality_gate"]

    assert benchmark_gate["status"] in ("FAIL", "UNSUPPORTED")


def test_benchmark_case_set_mismatch_is_not_readiness_eligible(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    # Only case_001 in benchmark, while selection has case_001 and case_002
    benchmark_dir = _create_valid_production_benchmark(
        tmp_path,
        dataset_file,
        sidecar_file,
        ["case_001"],
        hashlib.sha256(json.dumps(["case_001"], separators=(",", ":")).encode()).hexdigest(),
        git_sha="target_sha_123",
        pass_all_thresholds=True,
    )

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=benchmark_dir,
        target_git_sha="target_sha_123",
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]
    benchmark_gate = readiness["gates"]["production_benchmark_quality_gate"]

    assert benchmark_gate["status"] == "INSUFFICIENT_EVIDENCE"
    assert (
        "benchmark_manifest_case_set_mismatch" in readiness["blockers"]
        or "benchmark_case_set_mismatch" in readiness["blockers"]
    )


# ==============================================================================
# H. Provenance & Determinism Tests
# ==============================================================================

def test_artifact_contains_builder_and_input_hash_provenance(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        output_dir=out_dir,
    )
    provenance = pkg.decision_dict["provenance"]

    assert "builder_git_sha" in provenance
    assert "dataset_sha256" in provenance
    assert "sidecar_sha256" in provenance
    assert "gold_policy" in provenance
    assert "selected_case_count" in provenance
    assert "selected_case_ids_sha256" in provenance
    assert provenance["dataset_sha256"] == hashlib.sha256(dataset_file.read_bytes()).hexdigest()
    assert provenance["sidecar_sha256"] == hashlib.sha256(sidecar_file.read_bytes()).hexdigest()


def test_same_inputs_produce_byte_identical_decision_artifacts(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir1 = tmp_path / "out1"
    out_dir2 = tmp_path / "out2"

    pkg1 = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        output_dir=out_dir1,
        package_id="deterministic_pkg_001",
    )
    pkg2 = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        output_dir=out_dir2,
        package_id="deterministic_pkg_001",
    )

    json_bytes1 = (out_dir1 / "deterministic_pkg_001" / "decision.json").read_bytes()
    json_bytes2 = (out_dir2 / "deterministic_pkg_001" / "decision.json").read_bytes()
    assert json_bytes1 == json_bytes2

    md_bytes1 = (out_dir1 / "deterministic_pkg_001" / "report.md").read_bytes()
    md_bytes2 = (out_dir2 / "deterministic_pkg_001" / "report.md").read_bytes()
    assert md_bytes1 == md_bytes2


def test_builder_does_not_modify_dataset_sidecar_benchmark_or_snapshot(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    d_hash_before = hashlib.sha256(dataset_file.read_bytes()).hexdigest()
    s_hash_before = hashlib.sha256(sidecar_file.read_bytes()).hexdigest()

    build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        output_dir=out_dir,
    )

    assert hashlib.sha256(dataset_file.read_bytes()).hexdigest() == d_hash_before
    assert hashlib.sha256(sidecar_file.read_bytes()).hexdigest() == s_hash_before


def test_different_bytes_at_same_package_path_fail_collision(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    target_pkg_dir = out_dir / "collision_pkg"
    target_pkg_dir.mkdir(parents=True, exist_ok=True)
    (target_pkg_dir / "decision.json").write_text('{"tampered": true}\n', encoding="utf-8")

    with pytest.raises(ArtifactCollisionError):
        build_decision_package(
            dataset_path=dataset_file,
            sidecar_path=sidecar_file,
            output_dir=out_dir,
            package_id="collision_pkg",
        )


# ==============================================================================
# K. No Provider / Database Side Effects Test
# ==============================================================================

def test_decision_build_does_not_call_provider_retrieval_ragas_or_database(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    with patch("app.database.get_db", side_effect=RuntimeError("FORBIDDEN_DATABASE_CALL")), \
         patch("app.services.evaluator.run_llm_as_judge", side_effect=RuntimeError("FORBIDDEN_JUDGE_CALL")), \
         patch("app.services.retrieval.get_legal_retriever", side_effect=RuntimeError("FORBIDDEN_RETRIEVER_CALL")):

        pkg = build_decision_package(
            dataset_path=dataset_file,
            sidecar_path=sidecar_file,
            output_dir=out_dir,
        )
        assert pkg.decision_dict["production_readiness"]["status"] == "NOT_PRODUCTION_READY"


# ==============================================================================
# L. Current Approved Baseline Sanity Test
# ==============================================================================

def test_current_approved_baseline_sanity() -> None:
    assert APPROVED_DATASET_PATH.exists(), f"Approved dataset missing: {APPROVED_DATASET_PATH}"
    assert APPROVED_SIDECAR_PATH.exists(), f"Approved sidecar missing: {APPROVED_SIDECAR_PATH}"

    raw_dataset = json.loads(APPROVED_DATASET_PATH.read_bytes().decode("utf-8"))
    raw_dataset_case_ids = [f"case_{idx:03d}" for idx in range(1, len(raw_dataset) + 1)]
    sidecar = load_gold_sidecar(APPROVED_SIDECAR_PATH, dataset_case_ids=raw_dataset_case_ids)

    cases = build_cases(raw_dataset, sidecar.labels_by_case_id)
    selection = select_evaluation_cases(cases, "all-required-verified", include_unanswerable=False)

    total_cases = len(raw_dataset)
    total_evidence = len(sidecar.labels)
    verified_evidence = sum(1 for g in sidecar.labels if g.status == "verified")
    all_req_verified_cases = len(selection.selected_cases)

    assert total_cases == 420
    assert total_evidence == 484
    assert verified_evidence == 53
    assert all_req_verified_cases == 40


# ==============================================================================
# M. F1 Case Set Binding Tests
# ==============================================================================

def test_benchmark_results_case_ids_must_match_manifest_and_target(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    selected_ids = ["case_001", "case_002"]
    selected_sha = hashlib.sha256(json.dumps(selected_ids, separators=(",", ":")).encode()).hexdigest()

    bad_results = [
        {"case_id": "case_001", "status": "ok", "metrics": {}},
        {"case_id": "case_999", "status": "ok", "metrics": {}},
    ]

    benchmark_dir = _create_valid_production_benchmark(
        tmp_path,
        dataset_file,
        sidecar_file,
        selected_ids,
        selected_sha,
        git_sha="target_sha_123",
        case_results=bad_results,
    )

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=benchmark_dir,
        target_git_sha="target_sha_123",
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]
    benchmark_gate = readiness["gates"]["production_benchmark_quality_gate"]

    assert benchmark_gate["status"] == "INSUFFICIENT_EVIDENCE"
    assert benchmark_gate["readiness_eligible"] is False
    assert "benchmark_results_case_set_mismatch" in readiness["blockers"]
    assert pkg.decision_dict["layers"]["offline_golden_quality"]["production_retrieval_benchmark"]["metrics"] is None


def test_benchmark_results_duplicate_case_ids_fail_closed(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    selected_ids = ["case_001", "case_002"]
    selected_sha = hashlib.sha256(json.dumps(selected_ids, separators=(",", ":")).encode()).hexdigest()

    dup_results = [
        {"case_id": "case_001", "status": "ok", "metrics": {}},
        {"case_id": "case_001", "status": "ok", "metrics": {}},
    ]

    benchmark_dir = _create_valid_production_benchmark(
        tmp_path,
        dataset_file,
        sidecar_file,
        selected_ids,
        selected_sha,
        git_sha="target_sha_123",
        case_results=dup_results,
    )

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=benchmark_dir,
        target_git_sha="target_sha_123",
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]
    benchmark_gate = readiness["gates"]["production_benchmark_quality_gate"]

    assert benchmark_gate["status"] == "INSUFFICIENT_EVIDENCE"
    assert benchmark_gate["readiness_eligible"] is False
    assert "benchmark_results_duplicate_case_ids" in readiness["blockers"]
    assert pkg.decision_dict["layers"]["offline_golden_quality"]["production_retrieval_benchmark"]["metrics"] is None


def test_manifest_selected_case_ids_hash_is_recomputed_not_trusted(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    selected_ids = ["case_001", "case_002"]
    selected_sha = hashlib.sha256(json.dumps(selected_ids, separators=(",", ":")).encode()).hexdigest()

    benchmark_dir = _create_valid_production_benchmark(
        tmp_path,
        dataset_file,
        sidecar_file,
        selected_ids,
        selected_sha,
        git_sha="target_sha_123",
        manifest_selected_case_ids=selected_ids,
        manifest_selected_case_ids_sha="tampered_fake_sha_99999999",
        pass_all_thresholds=True,
    )

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=benchmark_dir,
        target_git_sha="target_sha_123",
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]
    benchmark_gate = readiness["gates"]["production_benchmark_quality_gate"]

    assert benchmark_gate["status"] == "INSUFFICIENT_EVIDENCE"
    assert benchmark_gate["readiness_eligible"] is False
    assert "benchmark_manifest_case_set_hash_invalid" in readiness["blockers"]


# ==============================================================================
# N. F2 Missing -> Numeric Fallback Removal Tests
# ==============================================================================

def test_missing_article_metric_cannot_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    selected_ids = ["case_001", "case_002"]
    selected_sha = hashlib.sha256(json.dumps(selected_ids, separators=(",", ":")).encode()).hexdigest()

    benchmark_dir = _create_valid_production_benchmark(
        tmp_path,
        dataset_file,
        sidecar_file,
        selected_ids,
        selected_sha,
        git_sha="target_sha_123",
        pass_all_thresholds=True,
    )

    from app.evaluation import decision_package
    orig_aggregate = decision_package.aggregate_retrieval_metrics

    def patched_aggregate(case_results):
        res = orig_aggregate(case_results)
        res["article_recall"] = {}
        return res

    monkeypatch.setattr(decision_package, "aggregate_retrieval_metrics", patched_aggregate)

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=benchmark_dir,
        target_git_sha="target_sha_123",
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]
    benchmark_gate = readiness["gates"]["production_benchmark_quality_gate"]

    assert benchmark_gate["status"] in ("FAIL", "UNSUPPORTED")
    assert benchmark_gate["details"]["threshold_evaluations"]["article_recall_at_24"]["observed"] is None
    assert benchmark_gate["details"]["threshold_evaluations"]["article_recall_at_24"]["status"] == "UNSUPPORTED"
    assert benchmark_gate["readiness_eligible"] is False


def test_missing_clause_metric_cannot_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    selected_ids = ["case_001", "case_002"]
    selected_sha = hashlib.sha256(json.dumps(selected_ids, separators=(",", ":")).encode()).hexdigest()

    benchmark_dir = _create_valid_production_benchmark(
        tmp_path,
        dataset_file,
        sidecar_file,
        selected_ids,
        selected_sha,
        git_sha="target_sha_123",
        pass_all_thresholds=True,
    )

    from app.evaluation import decision_package
    orig_aggregate = decision_package.aggregate_retrieval_metrics

    def patched_aggregate(case_results):
        res = orig_aggregate(case_results)
        res["clause_recall"] = {}
        return res

    monkeypatch.setattr(decision_package, "aggregate_retrieval_metrics", patched_aggregate)

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=benchmark_dir,
        target_git_sha="target_sha_123",
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]
    benchmark_gate = readiness["gates"]["production_benchmark_quality_gate"]

    assert benchmark_gate["status"] in ("FAIL", "UNSUPPORTED")
    assert benchmark_gate["details"]["threshold_evaluations"]["clause_recall_at_24"]["observed"] is None
    assert benchmark_gate["details"]["threshold_evaluations"]["clause_recall_at_24"]["status"] == "UNSUPPORTED"
    assert benchmark_gate["readiness_eligible"] is False


def test_missing_all_required_metric_cannot_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    selected_ids = ["case_001", "case_002"]
    selected_sha = hashlib.sha256(json.dumps(selected_ids, separators=(",", ":")).encode()).hexdigest()

    benchmark_dir = _create_valid_production_benchmark(
        tmp_path,
        dataset_file,
        sidecar_file,
        selected_ids,
        selected_sha,
        git_sha="target_sha_123",
        pass_all_thresholds=True,
    )

    from app.evaluation import decision_package
    orig_aggregate = decision_package.aggregate_retrieval_metrics

    def patched_aggregate(case_results):
        res = orig_aggregate(case_results)
        res["multi_hop_all_required"] = {"micro": None, "macro": None, "denominator": 0.0}
        return res

    monkeypatch.setattr(decision_package, "aggregate_retrieval_metrics", patched_aggregate)

    pkg = build_decision_package(
        dataset_path=dataset_path if 'dataset_path' in locals() else dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=benchmark_dir,
        target_git_sha="target_sha_123",
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]
    benchmark_gate = readiness["gates"]["production_benchmark_quality_gate"]

    assert benchmark_gate["status"] in ("FAIL", "UNSUPPORTED")
    assert benchmark_gate["details"]["threshold_evaluations"]["multi_hop_all_required"]["observed"] is None
    assert benchmark_gate["details"]["threshold_evaluations"]["multi_hop_all_required"]["status"] == "UNSUPPORTED"
    assert benchmark_gate["readiness_eligible"] is False


def test_missing_no_candidate_rate_cannot_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    selected_ids = ["case_001", "case_002"]
    selected_sha = hashlib.sha256(json.dumps(selected_ids, separators=(",", ":")).encode()).hexdigest()

    benchmark_dir = _create_valid_production_benchmark(
        tmp_path,
        dataset_file,
        sidecar_file,
        selected_ids,
        selected_sha,
        git_sha="target_sha_123",
        pass_all_thresholds=True,
    )

    from app.evaluation import decision_package
    orig_aggregate = decision_package.aggregate_retrieval_metrics

    def patched_aggregate(case_results):
        res = orig_aggregate(case_results)
        res["no_candidate_rate"] = None
        return res

    monkeypatch.setattr(decision_package, "aggregate_retrieval_metrics", patched_aggregate)

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=benchmark_dir,
        target_git_sha="target_sha_123",
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]
    benchmark_gate = readiness["gates"]["production_benchmark_quality_gate"]

    assert benchmark_gate["status"] in ("FAIL", "UNSUPPORTED")
    assert benchmark_gate["details"]["threshold_evaluations"]["no_candidate_rate"]["observed"] is None
    assert benchmark_gate["details"]["threshold_evaluations"]["no_candidate_rate"]["status"] == "UNSUPPORTED"
    assert benchmark_gate["readiness_eligible"] is False


def test_missing_retrieval_error_rate_cannot_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    selected_ids = ["case_001", "case_002"]
    selected_sha = hashlib.sha256(json.dumps(selected_ids, separators=(",", ":")).encode()).hexdigest()

    benchmark_dir = _create_valid_production_benchmark(
        tmp_path,
        dataset_file,
        sidecar_file,
        selected_ids,
        selected_sha,
        git_sha="target_sha_123",
        pass_all_thresholds=True,
    )

    from app.evaluation import decision_package
    orig_aggregate = decision_package.aggregate_retrieval_metrics

    def patched_aggregate(case_results):
        res = orig_aggregate(case_results)
        res["retrieval_technical_error_rate"] = None
        return res

    monkeypatch.setattr(decision_package, "aggregate_retrieval_metrics", patched_aggregate)

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=benchmark_dir,
        target_git_sha="target_sha_123",
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]
    benchmark_gate = readiness["gates"]["production_benchmark_quality_gate"]

    assert benchmark_gate["status"] in ("FAIL", "UNSUPPORTED")
    assert benchmark_gate["details"]["threshold_evaluations"]["retrieval_technical_error_rate"]["observed"] is None
    assert benchmark_gate["details"]["threshold_evaluations"]["retrieval_technical_error_rate"]["status"] == "UNSUPPORTED"
    assert benchmark_gate["readiness_eligible"] is False


def test_missing_reranker_error_rate_cannot_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    selected_ids = ["case_001", "case_002"]
    selected_sha = hashlib.sha256(json.dumps(selected_ids, separators=(",", ":")).encode()).hexdigest()

    benchmark_dir = _create_valid_production_benchmark(
        tmp_path,
        dataset_file,
        sidecar_file,
        selected_ids,
        selected_sha,
        git_sha="target_sha_123",
        pass_all_thresholds=True,
    )

    from app.evaluation import decision_package
    orig_aggregate = decision_package.aggregate_retrieval_metrics

    def patched_aggregate(case_results):
        res = orig_aggregate(case_results)
        res["reranker_technical_error_rate"] = None
        return res

    monkeypatch.setattr(decision_package, "aggregate_retrieval_metrics", patched_aggregate)

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=benchmark_dir,
        target_git_sha="target_sha_123",
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]
    benchmark_gate = readiness["gates"]["production_benchmark_quality_gate"]

    assert benchmark_gate["status"] in ("FAIL", "UNSUPPORTED")
    assert benchmark_gate["details"]["threshold_evaluations"]["reranker_technical_error_rate"]["observed"] is None
    assert benchmark_gate["details"]["threshold_evaluations"]["reranker_technical_error_rate"]["status"] == "UNSUPPORTED"
    assert benchmark_gate["readiness_eligible"] is False


# ==============================================================================
# O. F3 Exact K Semantics Tests
# ==============================================================================

def test_article_recall_at_6_cannot_substitute_for_required_at_24(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    selected_ids = ["case_001", "case_002"]
    selected_sha = hashlib.sha256(json.dumps(selected_ids, separators=(",", ":")).encode()).hexdigest()

    benchmark_dir = _create_valid_production_benchmark(
        tmp_path,
        dataset_file,
        sidecar_file,
        selected_ids,
        selected_sha,
        git_sha="target_sha_123",
        pass_all_thresholds=True,
        override_article_recall={
            6: {"numerator": 1, "denominator": 1, "value": 1.0, "reason": None}
        },
    )

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=benchmark_dir,
        target_git_sha="target_sha_123",
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]
    benchmark_gate = readiness["gates"]["production_benchmark_quality_gate"]

    assert benchmark_gate["status"] == "UNSUPPORTED"
    assert benchmark_gate["details"]["threshold_evaluations"]["article_recall_at_24"]["status"] == "UNSUPPORTED"
    assert benchmark_gate["details"]["threshold_evaluations"]["article_recall_at_24"]["observed"] is None
    assert benchmark_gate["readiness_eligible"] is False


def test_clause_recall_at_6_cannot_substitute_for_required_at_24(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    selected_ids = ["case_001", "case_002"]
    selected_sha = hashlib.sha256(json.dumps(selected_ids, separators=(",", ":")).encode()).hexdigest()

    benchmark_dir = _create_valid_production_benchmark(
        tmp_path,
        dataset_file,
        sidecar_file,
        selected_ids,
        selected_sha,
        git_sha="target_sha_123",
        pass_all_thresholds=True,
        override_clause_recall={
            6: {"numerator": 1, "denominator": 1, "value": 1.0, "reason": None}
        },
    )

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=benchmark_dir,
        target_git_sha="target_sha_123",
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]
    benchmark_gate = readiness["gates"]["production_benchmark_quality_gate"]

    assert benchmark_gate["status"] == "UNSUPPORTED"
    assert benchmark_gate["details"]["threshold_evaluations"]["clause_recall_at_24"]["status"] == "UNSUPPORTED"
    assert benchmark_gate["details"]["threshold_evaluations"]["clause_recall_at_24"]["observed"] is None
    assert benchmark_gate["readiness_eligible"] is False


# ==============================================================================
# P. F4 Strict Production Entrypoint + Provenance Tests
# ==============================================================================

def test_command_substring_spoof_cannot_classify_as_production_route(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    selected_ids = ["case_001", "case_002"]
    selected_sha = hashlib.sha256(json.dumps(selected_ids, separators=(",", ":")).encode()).hexdigest()

    benchmark_dir = _create_valid_production_benchmark(
        tmp_path,
        dataset_file,
        sidecar_file,
        selected_ids,
        selected_sha,
        git_sha="target_sha_123",
        command="python fake_runner.py --note run_retrieval_eval.py",
        pass_all_thresholds=True,
    )

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=benchmark_dir,
        target_git_sha="target_sha_123",
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]
    benchmark_gate = readiness["gates"]["production_benchmark_quality_gate"]

    assert benchmark_gate["status"] == "NON_PRODUCTION"
    assert benchmark_gate["readiness_eligible"] is False


def test_unavailable_benchmark_provenance_is_not_readiness_eligible(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    selected_ids = ["case_001", "case_002"]
    selected_sha = hashlib.sha256(json.dumps(selected_ids, separators=(",", ":")).encode()).hexdigest()

    benchmark_dir = _create_valid_production_benchmark(
        tmp_path,
        dataset_file,
        sidecar_file,
        selected_ids,
        selected_sha,
        git_sha="target_sha_123",
        provenance_status="unavailable",
        git_dirty=True,
        pass_all_thresholds=True,
    )

    pkg = build_decision_package(
        dataset_path=dataset_file,
        sidecar_path=sidecar_file,
        production_benchmark_dir=benchmark_dir,
        target_git_sha="target_sha_123",
        output_dir=out_dir,
    )
    readiness = pkg.decision_dict["production_readiness"]
    benchmark_gate = readiness["gates"]["production_benchmark_quality_gate"]

    assert benchmark_gate["status"] == "INSUFFICIENT_EVIDENCE"
    assert benchmark_gate["readiness_eligible"] is False


# ==============================================================================
# Q. F5 Package ID Containment Tests
# ==============================================================================

def test_package_id_cannot_escape_output_directory(tmp_path: Path) -> None:
    dataset_file = _create_minimal_dataset(tmp_path)
    sidecar_file = _create_minimal_sidecar(tmp_path)
    out_dir = tmp_path / "out"

    escape_ids = [
        "../escaped_dir",
        "../../etc",
        "nested/subpkg",
        "nested\\subpkg",
        "C:\\absolute_path",
        "/absolute/path",
        "-bad_start",
        ".bad_start",
        "bad spaces",
        "",
        "a" * 150,
    ]

    for bad_id in escape_ids:
        with pytest.raises(ValueError):
            build_decision_package(
                dataset_path=dataset_file,
                sidecar_path=sidecar_file,
                output_dir=out_dir,
                package_id=bad_id,
            )
