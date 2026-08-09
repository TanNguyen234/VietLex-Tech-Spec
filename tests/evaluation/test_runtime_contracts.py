from dataclasses import FrozenInstanceError, fields
from types import SimpleNamespace
from unittest.mock import AsyncMock, create_autospec, patch

import pytest

from app.evaluation.profiles import EvaluationProfile, get_evaluation_profile
from app.evaluation.schemas import (
    CandidateChunk,
    GoldenCase,
    RetrievalCaseResult,
    RetrievalStageTrace,
)
from app.ingestion.legal_text import EvidenceChunk
from app.services.retrieval import LegalRetriever, RetrievalOutcome
from run_answer_eval import run_stage_a_online, run_stage_b_offline
from run_retrieval_eval import (
    document_recall_at,
    evaluate_single_retrieval_case,
    parse_golden_case,
)


def make_case() -> GoldenCase:
    return GoldenCase(
        case_id="case_001",
        question="What are the tax deduction conditions?",
        question_type="factoid",
        answerable=True,
        reference_answer="",
    )


def make_settings() -> SimpleNamespace:
    return SimpleNamespace(LEGAL_FTS_RESULT_LIMIT=12)


def test_legacy_case_parser_uses_the_shared_legal_citation_contract() -> None:
    case = parse_golden_case(
        {
            "question": "Điều kiện áp dụng là gì?",
            "question_type": "factoid",
            "ground_truth_answer": "Có căn cứ pháp luật.",
            "ground_truth_context": [
                "Khoản 1 Điều 2 Nghị định 12/2026/NĐ-CP quy định nội dung này."
            ],
        },
        0,
    )

    assert len(case.gold_evidence) == 1
    assert case.gold_evidence[0].document_number == "12/2026/NĐ-CP"
    assert case.gold_evidence[0].article == "Điều 2"
    assert case.gold_evidence[0].clause == "Khoản 1"


def test_legacy_case_parser_preserves_every_citation_unit() -> None:
    case = parse_golden_case(
        {
            "question": "Các căn cứ là gì?",
            "question_type": "multi-hop",
            "ground_truth_answer": "Có hai căn cứ.",
            "ground_truth_context": [
                "Điều 2 văn bản 12/2026/NĐ-CP và "
                "Điều 5 văn bản 13/2026/NĐ-CP."
            ],
        },
        0,
    )

    assert [item.evidence_item_id for item in case.gold_evidence] == [
        "case_001_ctx01_cit01",
        "case_001_ctx01_cit02",
    ]
    assert [item.document_number for item in case.gold_evidence] == [
        "12/2026/NĐ-CP",
        "13/2026/NĐ-CP",
    ]


def test_progress_metric_reads_v3_integer_or_json_object_keys() -> None:
    metric = {"value": 0.75}

    assert document_recall_at({"document_recall": {1: metric}}, 1) == 0.75
    assert document_recall_at({"document_recall": {"1": metric}}, 1) == 0.75
    assert document_recall_at({"document_recall": {}}, 1) is None


def rewrite_profile(name: str) -> EvaluationProfile:
    return EvaluationProfile(
        name=name,
        retrieval_document_limit=24,
        resolved_document_limit=16,
        local_chunks_per_document=4,
        rerank_input_limit=24,
        rerank_return_limit=3,
        final_evidence_limit=3,
        final_context_token_limit=720,
        intent_scoring_enabled=True,
        rewrite_mode="on",
        reranker_mode="current",
    )


def test_evaluation_profile_is_frozen_and_has_all_runtime_fields() -> None:
    profile = get_evaluation_profile("separated_intent")
    assert {field.name for field in fields(profile)} == {
        "name",
        "retrieval_document_limit",
        "resolved_document_limit",
        "local_chunks_per_document",
        "rerank_input_limit",
        "rerank_return_limit",
        "final_evidence_limit",
        "final_context_token_limit",
        "intent_scoring_enabled",
        "rewrite_mode",
        "reranker_mode",
    }
    with pytest.raises(FrozenInstanceError):
        profile.rerank_input_limit = 99


@pytest.mark.asyncio
async def test_retrieval_adapter_calls_real_contract_once() -> None:
    profile = get_evaluation_profile("separated_intent")
    trace = RetrievalStageTrace()
    retriever = create_autospec(LegalRetriever, instance=True, spec_set=True)
    retriever.retrieve_detailed.return_value = RetrievalOutcome(
        evidence=[],
        latency={},
        status="no_candidate",
        diagnostics={"stage_trace": trace},
    )
    with (
        patch(
            "app.services.retrieval.get_legal_retriever",
            autospec=True,
            return_value=retriever,
        ),
        patch(
            "run_retrieval_eval.calculate_case_retrieval_metrics",
            autospec=True,
            return_value={},
        ) as metric_call,
    ):
        result = await evaluate_single_retrieval_case(
            make_case(), make_settings(), profile
        )

    retriever.retrieve_detailed.assert_awaited_once_with(
        make_case().question,
        sparse_query=make_case().question,
        profile=profile,
    )
    assert result.status == "no_candidate"
    assert result.stage_trace == trace
    metric_call.assert_called_once()
    assert metric_call.call_args.kwargs["stage_trace"] == trace
    assert metric_call.call_args.kwargs["capacities"].model_dump() == {
        "pinecone_document_limit": 24,
        "fts_document_limit": 12,
        "merged_document_limit": 36,
        "resolved_document_limit": 16,
        "structural_chunk_limit": None,
        "local_chunks_limit": 64,
        "rerank_input_limit": 24,
        "rerank_return_limit": 3,
        "final_evidence_limit": 3,
    }


@pytest.mark.asyncio
async def test_retrieval_adapter_accepts_real_unscored_evidence_chunks() -> None:
    # Break caught: the evaluation adapter reads an undeclared `.score`
    # attribute from the production EvidenceChunk runtime contract.
    profile = get_evaluation_profile("legacy")
    evidence = EvidenceChunk(
        document_id=431147,
        document_number="72/2020/QH14",
        title="Luật Bảo vệ môi trường",
        source_url="https://example.invalid/431147",
        heading_path="Điều 1",
        article="Điều 1",
        clause=None,
        citation="Điều 1 Luật 72/2020/QH14",
        text="Nội dung chứng cứ.",
        token_count=4,
    )
    retriever = create_autospec(LegalRetriever, instance=True, spec_set=True)
    retriever.retrieve_detailed.return_value = RetrievalOutcome(
        evidence=[evidence],
        latency={"t_total": 0.1},
        status="ok",
        diagnostics={"stage_trace": RetrievalStageTrace()},
    )

    with patch(
        "app.services.retrieval.get_legal_retriever",
        autospec=True,
        return_value=retriever,
    ):
        result = await evaluate_single_retrieval_case(
            make_case(), make_settings(), profile
        )

    assert result.status == "ok"
    assert len(result.retrieved_evidence) == 1
    assert result.retrieved_evidence[0].document_id == 431147
    assert result.retrieved_evidence[0].score is None


@pytest.mark.asyncio
async def test_retrieval_adapter_returns_typed_error_on_unexpected_exception() -> None:
    profile = get_evaluation_profile("separated_intent")
    retriever = create_autospec(LegalRetriever, instance=True, spec_set=True)
    retriever.retrieve_detailed.side_effect = RuntimeError("provider exploded")
    with patch(
        "app.services.retrieval.get_legal_retriever",
        autospec=True,
        return_value=retriever,
    ):
        result = await evaluate_single_retrieval_case(
            make_case(), make_settings(), profile
        )

    assert result.status == "retrieval_error"
    assert result.error == "RuntimeError: provider exploded"
    assert result.technical_errors == {
        "retrieval": "RuntimeError: provider exploded"
    }


@pytest.mark.asyncio
async def test_rewrite_failure_falls_back_and_is_observable() -> None:
    profile = rewrite_profile("rewrite-failure")
    case = make_case().model_copy(
        update={
            "question": (
                "What legal conditions govern corporate income tax "
                "deductions for this documented transaction today?"
            )
        }
    )
    retriever = create_autospec(LegalRetriever, instance=True, spec_set=True)
    retriever.retrieve_detailed.return_value = RetrievalOutcome(
        evidence=[],
        latency={},
        status="no_candidate",
        diagnostics={"stage_trace": RetrievalStageTrace()},
    )
    provider_call = AsyncMock(side_effect=TimeoutError("rewrite timeout"))
    rewrite_settings = SimpleNamespace(
        QUERY_REWRITE_MAX_CHARACTERS=500,
        QUERY_REWRITE_MAX_OUTPUT_TOKENS=64,
        QUERY_REWRITE_TIMEOUT_SECONDS=2.0,
    )
    with (
        patch(
            "app.services.retrieval.get_legal_retriever",
            autospec=True,
            return_value=retriever,
        ),
        patch(
            "app.services.rag_pipeline.generate_llm_response",
            new=provider_call,
        ),
        patch(
            "app.services.rag_pipeline.get_settings",
            return_value=rewrite_settings,
        ),
    ):
        result = await evaluate_single_retrieval_case(
            case, make_settings(), profile
        )

    assert result.query_used == case.question
    assert result.technical_errors == {
        "rewrite": "QueryRewriteError: TimeoutError: rewrite timeout"
    }
    provider_call.assert_awaited_once()


@pytest.mark.asyncio
async def test_successful_rewrite_is_dense_query_only_and_called_once() -> None:
    profile = rewrite_profile("rewrite-success")
    retriever = create_autospec(LegalRetriever, instance=True, spec_set=True)
    retriever.retrieve_detailed.return_value = RetrievalOutcome(
        evidence=[],
        latency={},
        status="no_candidate",
        diagnostics={"stage_trace": RetrievalStageTrace()},
    )
    rewrite_call = AsyncMock(return_value="rewritten legal query")
    with (
        patch(
            "app.services.retrieval.get_legal_retriever",
            autospec=True,
            return_value=retriever,
        ),
        patch("app.services.rag_pipeline.rewrite_query", new=rewrite_call),
    ):
        result = await evaluate_single_retrieval_case(
            make_case(), make_settings(), profile
        )

    rewrite_call.assert_awaited_once_with(
        make_case().question,
        raise_on_error=True,
    )
    retriever.retrieve_detailed.assert_awaited_once_with(
        "rewritten legal query",
        sparse_query=make_case().question,
        profile=profile,
    )
    assert result.query_used == "rewritten legal query"
    assert result.rewritten_query == "rewritten legal query"


@pytest.mark.asyncio
async def test_answer_stage_uses_one_retrieval_and_three_generation_arguments() -> None:
    profile = get_evaluation_profile("separated_intent")
    chunk = CandidateChunk(
        document_id=1,
        document_number="12/2026/ND-CP",
        title="Sample instrument",
        source_url="https://example.invalid/12",
        citation="Article 2, 12/2026/ND-CP",
        article="Article 2",
        text="Evidence text",
        token_count=2,
    )
    retrieval_result = RetrievalCaseResult(
        case_id="case_001",
        question=make_case().question,
        original_query=make_case().question,
        question_type="factoid",
        answerable=True,
        query_used="tax deduction",
        rewritten_query="tax deduction",
        status="ok",
        retrieved_evidence=[chunk],
    )
    retrieval_call = AsyncMock(return_value=retrieval_result)
    generation_call = AsyncMock(return_value="Generated answer")
    with (
        patch("run_answer_eval.evaluate_single_retrieval_case", retrieval_call),
        patch("app.services.rag_pipeline.generate_response", generation_call),
    ):
        result = await run_stage_a_online(
            make_case(), make_settings(), "off", profile
        )

    retrieval_call.assert_awaited_once_with(make_case(), make_settings(), profile)
    generation_call.assert_awaited_once_with(
        make_case().question,
        "tax deduction",
        result["contexts"],
    )


@pytest.mark.asyncio
async def test_answer_stage_propagates_reranker_error_status() -> None:
    profile = get_evaluation_profile("separated_intent")
    retrieval_result = RetrievalCaseResult(
        case_id="case_001",
        question=make_case().question,
        original_query=make_case().question,
        question_type="factoid",
        answerable=True,
        query_used=make_case().question,
        status="reranker_error",
        retrieved_evidence=[],
        error="TimeoutError: reranker timeout",
        technical_errors={"reranker": "TimeoutError: reranker timeout"},
    )
    with (
        patch(
            "run_answer_eval.evaluate_single_retrieval_case",
            new=AsyncMock(return_value=retrieval_result),
        ),
        patch(
            "app.services.rag_pipeline.generate_response",
            new=AsyncMock(return_value="System cannot process the request."),
        ),
    ):
        result = await run_stage_a_online(
            make_case(), make_settings(), "off", profile
        )

    assert result["status"] == "reranker_error"
    assert result["technical_errors"] == {
        "reranker": "TimeoutError: reranker timeout"
    }


@pytest.mark.asyncio
async def test_answer_stage_b_skips_quality_and_judge_on_technical_status() -> None:
    case = make_case()
    retrieval_result = RetrievalCaseResult(
        case_id=case.case_id,
        question=case.question,
        original_query=case.question,
        question_type=case.question_type,
        answerable=case.answerable,
        query_used=case.question,
        status="retrieval_error",
        error="TimeoutError: retrieval timeout",
        technical_errors={"retrieval": "TimeoutError: retrieval timeout"},
    )
    stage_a_result = {
        "raw_response": "Technical fallback",
        "final_response": "Technical fallback",
        "contexts": ["Context must not trigger the judge."],
        "input_safe": True,
        "output_safe": False,
        "status": "retrieval_error",
        "technical_errors": retrieval_result.technical_errors,
        "latency": {"t_total": 0.01},
        "retrieval_result": retrieval_result,
    }

    with patch(
        "run_eval_suite.build_ragas_evaluator",
        side_effect=AssertionError("technical result must not call judge"),
    ):
        result = await run_stage_b_offline(
            case,
            stage_a_result,
            SimpleNamespace(),
            "ragas",
        )

    assert result.metrics["applicable"] is False
    assert result.metrics["skip_reason"] == "retrieval_error"
    assert result.ragas_metrics is None


@pytest.mark.asyncio
async def test_input_guardrail_error_is_typed_and_runs_zero_retrieval() -> None:
    profile = get_evaluation_profile("separated_intent")
    retrieval_call = AsyncMock()
    with (
        patch(
            "app.services.guardrails.check_input_guardrails",
            new=AsyncMock(side_effect=TimeoutError("guardrail timeout")),
        ),
        patch("run_answer_eval.evaluate_single_retrieval_case", retrieval_call),
    ):
        result = await run_stage_a_online(
            make_case(), make_settings(), "enforce", profile
        )

    retrieval_call.assert_not_awaited()
    assert result["status"] == "input_guardrail_error"
    assert result["technical_errors"] == {
        "input_guardrail": "TimeoutError: guardrail timeout"
    }
    assert result["retrieval_result"].status == "input_guardrail_error"


@pytest.mark.asyncio
async def test_output_guardrail_error_is_typed_not_a_hallucination_block() -> None:
    profile = get_evaluation_profile("separated_intent")
    retrieval_result = RetrievalCaseResult(
        case_id="case_001",
        question=make_case().question,
        original_query=make_case().question,
        question_type="factoid",
        answerable=True,
        query_used=make_case().question,
        status="ok",
        retrieved_evidence=[],
    )
    with (
        patch(
            "app.services.guardrails.check_input_guardrails",
            new=AsyncMock(return_value=(True, "")),
        ),
        patch(
            "run_answer_eval.evaluate_single_retrieval_case",
            new=AsyncMock(return_value=retrieval_result),
        ),
        patch(
            "app.services.rag_pipeline.generate_response",
            new=AsyncMock(return_value="Generated answer"),
        ),
        patch(
            "app.services.guardrails.check_output_guardrails",
            new=AsyncMock(side_effect=TimeoutError("guardrail timeout")),
        ),
    ):
        result = await run_stage_a_online(
            make_case(), make_settings(), "enforce", profile
        )

    assert result["status"] == "output_guardrail_error"
    assert result["technical_errors"] == {
        "output_guardrail": "TimeoutError: guardrail timeout"
    }
    assert result["raw_response"] == "Generated answer"
    assert result["final_response"] == "Generated answer"
    assert result["output_safe"] is False


def test_run_directory_cannot_overwrite_existing_run(tmp_path) -> None:
    from app.evaluation.run_manifest import prepare_run_directory

    base = tmp_path / "runs"
    created = prepare_run_directory(base, "run_001")
    assert created.is_dir()
    with pytest.raises(FileExistsError, match="cannot be overwritten"):
        prepare_run_directory(base, "run_001")


@pytest.mark.parametrize(
    "run_id",
    ["../escape", "..\\escape", "/absolute", "C:\\absolute"],
)
def test_run_directory_rejects_path_like_run_ids(tmp_path, run_id: str) -> None:
    from app.evaluation.run_manifest import prepare_run_directory

    with pytest.raises(ValueError, match="invalid run_id"):
        prepare_run_directory(tmp_path / "runs", run_id)


def test_verified_only_selection_reports_honest_denominator() -> None:
    from app.evaluation.case_selection import select_evaluation_cases
    from app.evaluation.schemas import EvidenceStatus, GoldEvidence

    verified = make_case().model_copy(
        update={
            "case_id": "verified",
            "gold_evidence": [
                GoldEvidence(
                    evidence_item_id="verified_ev_01",
                    case_id="verified",
                    document_number="12/2026/ND-CP",
                    required=True,
                    status=EvidenceStatus.VERIFIED,
                )
            ],
        }
    )
    pending = make_case().model_copy(update={"case_id": "pending"})
    selection = select_evaluation_cases(
        [verified, pending], "all-required-verified"
    )

    assert selection.total_candidate_cases == 2
    assert selection.selected_case_count == 1
    assert selection.excluded_no_verified_label_count == 1


def test_refusal_and_text_metrics_keep_distinct_contracts() -> None:
    from app.evaluation.answer_metrics import calculate_case_answer_metrics

    metrics = calculate_case_answer_metrics(
        pred_response="Taxable income",
        ref_answer="taxable income",
        question_type="factoid",
        retrieved_contexts=["Article 1"],
    )

    assert metrics["exact_match"] == 1.0
    assert metrics["token_precision"] == 1.0
    assert metrics["token_recall"] == 1.0
    assert metrics["token_f1"] == 1.0
    assert metrics["char_f1"] == 1.0
    assert metrics["refusal_category"] == "normal_answer"


def test_technical_fallback_is_not_an_honest_refusal() -> None:
    from app.evaluation.answer_metrics import classify_response_refusal

    category, is_refusal = classify_response_refusal(
        "guardrail error: request could not be processed",
        ["Article 1"],
    )

    assert category == "technical_error"
    assert is_refusal is False


def test_answer_aggregation_excludes_technical_outcomes() -> None:
    from app.evaluation.answer_metrics import aggregate_answer_metrics

    results = [
        {
            "answerable": True,
            "status": "ok",
            "refusal_category": "normal_answer",
            "metrics": {
                "applicable": True,
                "skip_reason": None,
                "is_refusal": False,
                "token_f1": 1.0,
            },
        },
        {
            "answerable": False,
            "status": "retrieval_error",
            "refusal_category": "technical_error",
            "metrics": {
                "applicable": False,
                "skip_reason": "retrieval_error",
                "is_refusal": False,
                "token_f1": 0.0,
            },
        },
        {
            "answerable": False,
            "status": "ok",
            "refusal_category": "pure_refusal",
            "metrics": {
                "applicable": True,
                "skip_reason": None,
                "is_refusal": True,
                "token_f1": 0.0,
            },
        },
    ]

    summary = aggregate_answer_metrics(results)

    assert summary["total_cases"] == 3
    assert summary["scored_cases"] == 2
    assert summary["skipped_cases"] == 1
    assert summary["skip_reason_counts"] == {"retrieval_error": 1}
    assert summary["answerable_count"] == 1
    assert summary["unanswerable_count"] == 1
    assert summary["refusal_precision"] == 1.0
    assert summary["refusal_recall"] == 1.0
    assert summary["token_f1"] == 0.5
