import json
from pathlib import Path

import pytest

from app.evaluation.retrieval_metrics import calculate_case_retrieval_metrics
from app.evaluation.run_manifest import calculate_configuration_fingerprint
from app.evaluation.schemas import (
    EvaluationRunManifest,
    GoldEvidence,
    RetrievalCaseResult,
    RetrievalStageCapacities,
    RetrievalStageTrace,
)
from run_retrieval_comparison import build_retrieval_comparison


SELECTED_CASE_SHA256 = (
    "e4bc9a58dfec82a28686be72ec9119a60d8dc78506a3eb186e91215486e60375"
)
PROFILES = ("legacy", "separated_no_intent", "separated_intent")


def _write_run(
    root: Path,
    profile_name: str,
    *,
    source_state_sha256: str = "b" * 64,
    result_case_id: str = "case_001",
) -> Path:
    run_dir = root / f"run-{profile_name}"
    run_dir.mkdir()
    configuration = {
        "profile_name": profile_name,
        "profile": {"name": profile_name},
        "selected_case_count": 1,
        "selected_case_ids_sha256": SELECTED_CASE_SHA256,
        "configured_provider_models": {
            "dense": {"provider": "qdrant", "model": "dense-model"},
            "reranker_primary": {
                "provider": "qdrant",
                "model": "rerank-model",
            },
        },
    }
    manifest = EvaluationRunManifest(
        run_id=run_dir.name,
        utc_timestamp="2026-08-09T00:00:00+00:00",
        git_sha="a" * 40,
        git_dirty=False,
        source_state_sha256=source_state_sha256,
        dataset_revision="corpus-revision",
        dataset_sha256="c" * 64,
        evaluation_dataset_sha256="c" * 64,
        gold_label_sidecar_sha256="d" * 64,
        gold_policy="all-required-verified",
        selected_case_count=1,
        selected_case_ids=["case_001"],
        selected_case_ids_sha256=SELECTED_CASE_SHA256,
        configuration_fingerprint=calculate_configuration_fingerprint(
            configuration
        ),
        command=f"python run_retrieval_eval.py --profile {profile_name}",
        eval_mode="retrieval-only",
        judge_mode="none",
        guardrail_mode="off",
        rewrite_mode="off",
        reranker_provider="current",
        profile_name=profile_name,
        configuration=configuration,
        configured_provider_models=configuration["configured_provider_models"],
        code_metric_version="3.0.0",
    )
    gold = GoldEvidence(
        evidence_item_id="case_001_ev_01",
        case_id="case_001",
        document_id=1,
        required=True,
        required_level="document",
        status="verified",
    )
    trace = RetrievalStageTrace()
    metrics = calculate_case_retrieval_metrics(
        [gold],
        [],
        stage_trace=trace,
        capacities=RetrievalStageCapacities(),
        status="ok",
    )
    result = RetrievalCaseResult(
        case_id=result_case_id,
        question="Câu hỏi?",
        question_type="factoid",
        answerable=True,
        query_used="Câu hỏi?",
        original_query="Câu hỏi?",
        status="ok",
        stage_trace=trace,
        latency={"t_retrieval": 1.0, "t_total": 1.0, "t_rewrite": 0.0},
        metrics=metrics,
    )
    payloads = {
        "manifest.json": manifest.model_dump(),
        "configuration.json": configuration,
        "evaluation_case_set.json": {
            "selected_case_count": 1,
            "selected_case_ids": ["case_001"],
            "selected_case_ids_sha256": SELECTED_CASE_SHA256,
        },
        "retrieval_results.json": [result.model_dump()],
    }
    for name, payload in payloads.items():
        (run_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    return run_dir


def test_comparison_recomputes_metrics_and_reports_initial_source_loss(
    tmp_path: Path,
) -> None:
    comparison = build_retrieval_comparison(
        [_write_run(tmp_path, profile) for profile in PROFILES]
    )

    assert comparison["status"] == "COMPLETED"
    assert comparison["decision_status"] == "NO_WINNER_ZERO_RECALL"
    assert comparison["recommended_profile"] is None
    assert comparison["shared_provenance"]["selected_case_count"] == 1
    assert set(comparison["profiles"]) == set(PROFILES)
    for profile in comparison["profiles"].values():
        recall = profile["aggregate_metrics"]["document_recall"]["1"]
        assert recall["numerator"] == 0.0
        assert recall["denominator"] == 1.0
        assert profile["initial_source_miss_evidence_count"] == 1
        assert profile["status_counts"] == {"ok": 1}
        assert profile["reranker_contribution"]["interpretation"] == (
            "not_measurable_no_verified_gold_at_reranker_input"
        )


def test_comparison_rejects_mixed_source_states(tmp_path: Path) -> None:
    run_dirs = [_write_run(tmp_path, profile) for profile in PROFILES]
    manifest_path = run_dirs[-1] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_state_sha256"] = "e" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="source_state_sha256"):
        build_retrieval_comparison(run_dirs)


def test_comparison_rejects_result_case_set_drift(tmp_path: Path) -> None:
    run_dirs = [
        _write_run(
            tmp_path,
            profile,
            result_case_id="case_999" if profile == "legacy" else "case_001",
        )
        for profile in PROFILES
    ]

    with pytest.raises(ValueError, match="result case IDs"):
        build_retrieval_comparison(run_dirs)
