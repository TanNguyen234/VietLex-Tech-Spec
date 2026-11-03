from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.evaluation.profiles import get_evaluation_profile
from app.evaluation.schemas import CandidateChunk, GoldenCase, RetrievalCaseResult
from app.ingestion.legal_text import EvidenceChunk
from app.services.direct_llm import LLMGenerationResult
from app.services.retrieval import RetrievalOutcome


def case():
    return GoldenCase(case_id="case_001", question="Điều kiện nộp thuế được quy định thế nào?",
                      question_type="factoid", answerable=True, reference_answer="Căn cứ thuế.")


def evidence():
    return EvidenceChunk(1, "12/2026/NĐ-CP", "Quy định thuế", "https://example.invalid/1",
                         "", "Điều 1", "1", "12/2026/NĐ-CP, Điều 1, Khoản 1", "Căn cứ thuế.", 3)


@pytest.mark.asyncio
async def test_v3_keeps_original_candidates_for_later_expansion(monkeypatch):
    from app.evaluation import retrieval_backends
    first = evidence()
    second = replace(first, article="Điều 2", text="Căn cứ thứ hai.")
    retriever = SimpleNamespace(retrieve_detailed=AsyncMock(return_value=RetrievalOutcome(
        evidence=[first, second], latency={}, status="ok")))
    monkeypatch.setattr(retrieval_backends, "get_vertex_qdrant_retriever", lambda: retriever)
    outcome = await retrieval_backends.retrieve_for_evaluation(
        "vertex-qdrant-v3", dense_query="câu hỏi", sparse_query="câu hỏi",
        profile=replace(get_evaluation_profile("separated_intent"), final_evidence_limit=1))
    assert outcome.evidence == [first]
    assert outcome.candidate_evidence == [first, second]


@pytest.mark.asyncio
async def test_chat_expansion_receives_pool_before_top_three_cut(monkeypatch):
    from app.services import rag_pipeline as pipeline
    first = evidence()
    pool = [first, replace(first, article="Điều 2", text="Căn cứ thứ hai.")]
    outcome = SimpleNamespace(evidence=[first], candidate_evidence=pool, diagnostics={}, latency={}, status="ok")
    monkeypatch.setattr(pipeline, "retrieve_configured_legal_evidence", AsyncMock(return_value=outcome))
    monkeypatch.setattr(pipeline, "get_settings", lambda: Settings(_env_file=None, APP_ENV="test", CHAT_OFFICIAL_DEEP_READING_ENABLED=False))
    expansion = AsyncMock(return_value=SimpleNamespace(selected_evidence=[first], status="not_found", diagnostics={}))
    monkeypatch.setattr(pipeline, "expand_v3_evidence", expansion)
    monkeypatch.setattr(pipeline, "rescue_primary_law_evidence", AsyncMock(return_value=SimpleNamespace(evidence=[], diagnostics={})))
    monkeypatch.setattr(pipeline, "corpus_evidence_covers_topic", lambda *_: True)
    monkeypatch.setattr(pipeline, "generate_response_with_metadata", AsyncMock(return_value=LLMGenerationResult("Câu trả lời", "test", "test")))
    await pipeline.run_advanced_rag(case().question)
    assert expansion.await_args.args[1] == pool
    assert expansion.await_args.args[2] == [first]


@pytest.mark.asyncio
@pytest.mark.parametrize("guardrails_mode", ["off", "enforce"])
async def test_production_answer_uses_chat_service_once_and_defers_metrics(monkeypatch, guardrails_mode):
    import run_answer_eval as evaluation
    from app.services import rag_pipeline as pipeline
    from app.services.official_search_plan import ProfiledContexts, DEEP_READING
    chunk = evidence()
    contexts = ProfiledContexts([chunk.formatted_context(), "Nguồn bổ sung"], DEEP_READING)
    metadata = {"retrieval_outcome": RetrievalOutcome([chunk], {}, diagnostics={}),
                "retrieval_status": "ok", "generation_status": "success", "rewritten_query": case().question,
                "t_total": 0.2, "t_retrieval": 0.1,
                "provider_usage": {"answer_generation": {"provider": "google_vertex_ai", "model": "test", "observed": True, "status": "success"}},
                "retrieval_diagnostics": {"context_stages": [{"stage": "prompt", "count": 2}]}}
    service = AsyncMock(return_value=("Căn cứ thuế.", contexts, metadata))
    monkeypatch.setattr(pipeline, "run_advanced_rag", service)
    monkeypatch.setattr(evaluation, "evaluate_single_retrieval_case", AsyncMock(side_effect=AssertionError("duplicate/adapter retrieval")))
    monkeypatch.setattr(evaluation, "calculate_case_retrieval_metrics", lambda *_a, **_k: pytest.fail("offline metrics under online semaphore"))
    monkeypatch.setattr("app.services.serverless_guardrails.check_input_guardrails", AsyncMock(return_value=(True, "")))
    output = AsyncMock(return_value=(True, ""))
    monkeypatch.setattr("app.services.serverless_guardrails.check_output_guardrails", output)
    monkeypatch.setattr("app.services.guardrails.check_input_guardrails", AsyncMock(side_effect=AssertionError("wrong guardrail engine")))
    settings = Settings(_env_file=None, APP_ENV="test", SERVERLESS_ONLINE_ONLY=True)
    result = await evaluation.run_stage_a_online(case(), settings, guardrails_mode, get_evaluation_profile("separated_intent"))
    service.assert_awaited_once_with(case().question, rewrite_mode="off", profile=get_evaluation_profile("separated_intent"))
    assert result["contexts"] is contexts
    assert result["generation_metadata"]["observed"] is True
    assert len(result["prompt_evidence"]) == 2
    assert result["pipeline_diagnostics"]["context_stages"][-1]["count"] == 2
    if guardrails_mode == "enforce":
        assert output.await_args.args[1] is contexts
    from app.evaluation.retrieval_metrics import calculate_case_retrieval_metrics
    monkeypatch.setattr(evaluation, "calculate_case_retrieval_metrics", calculate_case_retrieval_metrics)
    final = await evaluation.run_stage_b_offline(case(), result, settings, "none")
    assert final.prompt_evidence == result["prompt_evidence"]
    assert final.prompt_contexts == list(contexts)
    restored = type(final).model_validate_json(final.model_dump_json())
    assert restored.prompt_contexts == list(contexts)
    assert final.pipeline_diagnostics["pipeline"] == "chat_service_v1"
    assert "Nguồn bổ sung" not in str(final.prompt_evidence)


@pytest.mark.asyncio
async def test_adapter_packs_identical_contexts_for_generation_and_guardrail(monkeypatch):
    import run_answer_eval as evaluation
    from app.services import rag_pipeline as pipeline
    chunks = [CandidateChunk(document_id=i, document_number="12/2026/NĐ-CP", title="Thuế", source_url="https://example.invalid",
               citation=f"Điều {i}", text="từ " * length, token_count=length) for i, length in [(1, 3), (2, 100), (3, 3)]]
    retrieval = RetrievalCaseResult(case_id=case().case_id, question=case().question, question_type="factoid", answerable=True,
                                    query_used=case().question, original_query=case().question, status="ok", retrieved_evidence=chunks)
    generator = AsyncMock(return_value=LLMGenerationResult("Căn cứ thuế.", "test", "test"))
    output = AsyncMock(return_value=(True, ""))
    monkeypatch.setattr(evaluation, "evaluate_single_retrieval_case", AsyncMock(return_value=retrieval))
    monkeypatch.setattr(pipeline, "generate_response_with_metadata", generator)
    monkeypatch.setattr("app.services.guardrails.check_input_guardrails", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr("app.services.guardrails.check_output_guardrails", output)
    result = await evaluation.run_stage_a_online(case(), SimpleNamespace(LLM_CONTEXT_MAX_TOKENS=60), "enforce", get_evaluation_profile("separated_intent"))
    actual = result["contexts"]
    assert len(actual) == 2
    assert generator.await_args.args[2] is actual
    assert output.await_args.args[1] is actual
    assert len(pipeline.build_bounded_context(actual, max_tokens=60).split()) <= 60


def test_manifest_records_pipeline_and_source_environment():
    from app.evaluation.run_manifest import build_run_configuration, calculate_configuration_fingerprint
    import hashlib
    kwargs = dict(profile_name="separated_intent", profile={}, eval_mode="answer", judge_mode="none", guardrail_mode="enforce",
                  rewrite_mode="off", reranker_provider="current", gold_policy="none", selected_case_ids=[],
                  selected_case_ids_sha256=hashlib.sha256(b"[]").hexdigest())
    local = build_run_configuration(**kwargs, settings=Settings(_env_file=None, APP_ENV="test"))
    online = build_run_configuration(**kwargs, settings=Settings(_env_file=None, APP_ENV="production", SERVERLESS_ONLINE_ONLY=True))
    assert online["answer_pipeline"] == "chat_service_v1"
    assert online["runtime_environment"] == {"app_env": "production", "serverless_online_only": True}
    assert calculate_configuration_fingerprint(local) != calculate_configuration_fingerprint(online)


def test_eia_procedure_keeps_existing_current_law_policy():
    from app.services.chat_official_supplement import _current_applicability_intent
    query = "Khi có yêu cầu chỉnh sửa báo cáo đánh giá tác động môi trường, cơ quan thẩm định phải thực hiện thủ tục gì?"
    assert _current_applicability_intent(query) is False
    assert _current_applicability_intent("Theo quy định hiện nay, " + query) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["retrieval", "generation"])
async def test_chat_technical_failure_is_observable_and_not_scored(monkeypatch, failure):
    import run_answer_eval as evaluation
    from app.services import rag_pipeline as pipeline
    from app.services.runtime_errors import RetrievalPipelineError
    settings = Settings(_env_file=None, APP_ENV="test")
    if failure == "retrieval":
        service = AsyncMock(side_effect=RetrievalPipelineError("retrieval_error", "private details", {}))
    else:
        service = AsyncMock(return_value=("Technical fallback", [], {
            "retrieval_outcome": RetrievalOutcome([], {}), "retrieval_status": "ok",
            "generation_status": "providers_exhausted",
        }))
    monkeypatch.setattr(pipeline, "run_advanced_rag", service)
    stage_a = await evaluation.run_stage_a_online(case(), settings, "off", get_evaluation_profile("separated_intent"))
    final = await evaluation.run_stage_b_offline(case(), stage_a, settings, "none")
    assert final.status == failure + "_error"
    assert final.metrics["applicable"] is False
    assert final.technical_errors
    assert "private details" not in str(final.technical_errors)
    assert final.ragas_metrics is None


@pytest.mark.asyncio
@pytest.mark.parametrize("serverless", [True, False])
async def test_cli_warms_only_the_selected_guardrail_engine(monkeypatch, serverless):
    import run_answer_eval as evaluation
    settings = Settings(_env_file=None, APP_ENV="test", SERVERLESS_ONLINE_ONLY=serverless)
    warm = AsyncMock()
    monkeypatch.setattr(evaluation, "get_settings", lambda: settings)
    monkeypatch.setattr("app.services.guardrails.warm_guardrails", warm)
    def stop_before_sources(**kwargs):
        raise ValueError("preflight boundary reached")
    monkeypatch.setattr(evaluation, "perform_pre_execution_validation", stop_before_sources)
    args = evaluation.build_parser().parse_args(["--guardrails", "enforce"])
    with pytest.raises(ValueError, match="preflight boundary reached"):
        await evaluation.run_answer_evaluation(args)
    assert warm.await_count == (0 if serverless else 1)


@pytest.mark.parametrize("prefix", ["", "Theo quy định hiện nay, "])
def test_statutory_deadline_anchor_is_not_a_current_law_question(prefix):
    from app.services.chat_official_supplement import corpus_evidence_covers_topic, _current_applicability_intent
    from app.services.official_search_plan import build_official_search_plan
    query = prefix + "Các cụm công nghiệp phải hoàn thành hạ tầng trong bao lâu kể từ ngày Luật này có hiệu lực?"
    context = "[72/2020/QH14, Điều 52] Cụm công nghiệp đang hoạt động phải hoàn thành công trình hạ tầng bảo vệ môi trường trong thời hạn 24 tháng kể từ ngày Luật này có hiệu lực."
    assert _current_applicability_intent(query) is bool(prefix)
    assert build_official_search_plan(query).current_required is bool(prefix)
    assert corpus_evidence_covers_topic(query, [context]) is not bool(prefix)
    assert _current_applicability_intent("Luật này có hiệu lực chưa?") is True
