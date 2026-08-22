import pytest

from app.evaluation.reporting import generate_markdown_report
from app.evaluation.retrieval_metrics import aggregate_retrieval_metrics
from app.evaluation.schemas import (
    EvaluationRunManifest,
    EvaluationSchemaError,
    RetrievalAggregateMetrics,
    RetrievalCaseMetricsV3,
)


def r(
    numerator: float,
    denominator: float,
    value: float | None,
    reason: str | None = None,
) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": value,
        "reason": reason,
    }


def scored_row(
    case_id: str,
    candidate_count: int,
    *,
    first_loss: bool = False,
) -> dict:
    document_ratio = r(1, 1, 1.0)
    not_applicable = r(0, 0, None, "no_applicable_gold")
    stage = {
        "configured_capacity": 3,
        "candidate_count": candidate_count,
        "scored_case_count": 1,
        "applicable_gold_counts": {
            "document": 1,
            "article": 0,
            "clause": 0,
        },
        "matched_gold_counts": {
            "document": 1,
            "article": 0,
            "clause": 0,
        },
        "recall": {
            "document": {3: document_ratio},
            "article": {},
            "clause": {},
        },
        "mrr": {
            "document": document_ratio,
            "article": not_applicable,
            "clause": not_applicable,
        },
        "null_reason_counts": {},
    }
    metrics = RetrievalCaseMetricsV3(
        status="ok",
        applicable=True,
        applicable_gold_counts={
            "document": 1,
            "article": 0,
            "clause": 0,
        },
        matched_gold_counts={
            "document": 1,
            "article": 0,
            "clause": 0,
        },
        document_recall={3: document_ratio},
        article_recall={},
        clause_recall={},
        mrr={
            "document": document_ratio,
            "article": not_applicable,
            "clause": not_applicable,
        },
        ndcg_at_10=document_ratio,
        exact_reference_hit=document_ratio,
        multi_hop={
            "all_required": True,
            "matched_required_items": 1,
            "required_items": 1,
            "all_required_metric": document_ratio,
            "partial_metric": document_ratio,
        },
        stages={
            "local_selection_metrics": {
                **stage,
                "candidate_count": 1,
            },
            "final_evidence_metrics": stage,
        },
        first_loss_by_evidence=(
            {f"{case_id}_ev_01": "local_selection_metrics"}
            if first_loss
            else {}
        ),
    )
    return {
        "case_id": case_id,
        "status": "ok",
        "metrics": metrics.model_dump(mode="json"),
    }


def skipped_row() -> dict:
    unavailable = r(0, 0, None, "no_verified_gold_label")
    metrics = RetrievalCaseMetricsV3(
        status="ok",
        applicable=False,
        skip_reason="no_verified_gold_label",
        applicable_gold_counts={
            "document": 0,
            "article": 0,
            "clause": 0,
        },
        matched_gold_counts={
            "document": 0,
            "article": 0,
            "clause": 0,
        },
        document_recall={},
        article_recall={},
        clause_recall={},
        mrr={
            "document": unavailable,
            "article": unavailable,
            "clause": unavailable,
        },
        ndcg_at_10=unavailable,
        exact_reference_hit=unavailable,
        multi_hop={
            "all_required": False,
            "matched_required_items": 0,
            "required_items": 0,
            "all_required_metric": unavailable,
            "partial_metric": unavailable,
        },
        stages={},
    )
    return {
        "case_id": "case_003",
        "status": "ok",
        "metrics": metrics.model_dump(mode="json"),
    }


def aggregate_fixture() -> list[dict]:
    return [
        scored_row("case_001", 1, first_loss=True),
        scored_row("case_002", 3),
        skipped_row(),
    ]


def test_aggregate_has_known_denominators_and_candidate_distribution() -> None:
    summary = RetrievalAggregateMetrics.model_validate(
        aggregate_retrieval_metrics(aggregate_fixture())
    )

    assert summary.total_cases == 3
    assert summary.scored_cases == 2
    assert summary.skipped_cases == 1
    assert summary.coverage.numerator == 2
    assert summary.coverage.denominator == 3
    assert summary.coverage.micro == pytest.approx(2 / 3, abs=1e-4)
    assert summary.skip_reason_counts == {"no_verified_gold_label": 1}
    assert summary.stages[
        "final_evidence_metrics"
    ].candidates.model_dump() == {
        "count": 2,
        "min": 1.0,
        "mean": 2.0,
        "p50": 2.0,
        "p95": 2.9,
        "max": 3.0,
    }
    assert summary.stages[
        "local_selection_metrics"
    ].first_loss_evidence_count == 1


def test_partial_retrieval_error_counts_without_skipping_quality() -> None:
    row = scored_row("case_001", 1)
    row["status"] = "partial_retrieval_error"
    row["metrics"]["status"] = "partial_retrieval_error"
    row["metrics"]["retrieval_technical_error"] = True

    summary = RetrievalAggregateMetrics.model_validate(
        aggregate_retrieval_metrics([row])
    )

    assert summary.scored_cases == 1
    assert summary.retrieval_technical_error_rate.numerator == 1
    assert summary.retrieval_technical_error_rate.denominator == 1


def test_aggregate_rejects_conflicting_stage_capacities() -> None:
    first = scored_row("case_001", 1)
    second = scored_row("case_002", 2)
    first["metrics"]["stages"]["local_selection_metrics"][
        "configured_capacity"
    ] = 4
    second["metrics"]["stages"]["local_selection_metrics"][
        "configured_capacity"
    ] = 6

    with pytest.raises(
        EvaluationSchemaError,
        match="inconsistent configured capacity for local_selection_metrics",
    ):
        aggregate_retrieval_metrics([first, second])

    first["metrics"]["stages"]["local_selection_metrics"][
        "configured_capacity"
    ] = None
    summary = RetrievalAggregateMetrics.model_validate(
        aggregate_retrieval_metrics([first, second])
    )
    assert summary.stages[
        "local_selection_metrics"
    ].configured_capacity == 6


def test_empty_aggregate_does_not_invent_quality_values() -> None:
    summary = RetrievalAggregateMetrics.model_validate(
        aggregate_retrieval_metrics([])
    )

    assert summary.total_cases == 0
    assert summary.scored_cases == 0
    assert summary.coverage.denominator == 0
    assert summary.coverage.micro is None
    assert summary.coverage.reason == "no_cases"
    assert summary.stages == {}
    assert summary.ndcg_at_10.micro is None


def report_manifest() -> EvaluationRunManifest:
    return EvaluationRunManifest(
        run_id="synthetic_v3",
        utc_timestamp="2026-08-08T00:00:00+00:00",
        git_sha="a" * 40,
        repository_root="D:/synthetic-repository",
        dataset_revision="synthetic-v1",
        dataset_sha256="d" * 64,
        evaluation_dataset_sha256="d" * 64,
        configuration_fingerprint="f" * 64,
        command="python -m synthetic",
        eval_mode="retrieval-only",
        judge_mode="none",
        guardrail_mode="off",
        rewrite_mode="off",
        reranker_provider="current",
        profile_name="separated_intent",
    )


def test_report_renders_only_valid_v3_contract() -> None:
    summary = RetrievalAggregateMetrics.model_validate(
        aggregate_retrieval_metrics(aggregate_fixture())
    )

    text = generate_markdown_report(
        report_manifest(),
        summary.model_dump(mode="json"),
        {},
        {},
    )

    for expected in (
        "Metric schema: `3.0.0`",
        "Scored / Total: `2 / 3`",
        "Skipped cases: `1`",
        "no_verified_gold_label=1",
        "Document Recall @ 3",
        "Numerator / Denominator",
        "Scored / Skipped",
        "Skip reasons",
        "Retrieval technical-error rate",
        "Candidate p50 / p95",
        "First-loss evidence count",
    ):
        assert expected in text


def test_answer_report_exposes_generation_guardrail_and_ragas_coverage() -> None:
    summary = RetrievalAggregateMetrics.model_validate(
        aggregate_retrieval_metrics(aggregate_fixture())
    )
    case_results = [
        {
            "case_id": "case_001",
            "status": "ok",
            "input_safe": True,
            "output_safe": True,
            "generation_metadata": {"finish_reason": "STOP"},
            "ragas_metrics": {
                "faithfulness": 1.0,
                "answer_accuracy": 0.9,
                "context_precision": 0.8,
                "context_recall": 1.0,
            },
            "technical_errors": {},
            "latency": {"t_total": 1.0},
        },
        {
            "case_id": "case_002",
            "status": "ok",
            "input_safe": True,
            "output_safe": True,
            "generation_metadata": {"finish_reason": "MAX_TOKENS"},
            "ragas_metrics": None,
            "technical_errors": {"judge": "structured response missing"},
            "latency": {"t_total": 1.0},
        },
    ]

    text = generate_markdown_report(
        report_manifest(),
        summary.model_dump(mode="json"),
        {},
        {},
        answer_summary={"scored_cases": 2, "total_cases": 2},
        case_results=case_results,
    )

    assert "Generation STOP / total: `1 / 2`" in text
    assert "Input safe / total: `2 / 2`" in text
    assert "Output safe / total: `2 / 2`" in text
    assert "Ragas scored / eligible: `1 / 2`" in text
    assert "Judge technical errors: `1`" in text
    assert "| `case_002` | `ok` | `MAX_TOKENS` | `no` | `judge` |" in text


def test_report_rejects_legacy_metric_keys() -> None:
    with pytest.raises(EvaluationSchemaError) as captured:
        generate_markdown_report(
            report_manifest(),
            {"doc_recall": {1: 1.0}},
            {},
            {},
        )

    assert captured.value.status == "schema_error"
