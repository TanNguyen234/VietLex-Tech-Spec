from __future__ import annotations

import math
import sys
import types
from datetime import datetime, timezone
from typing import List

import logfire
import httpx

from app.config import get_settings
from app.evaluation.online_metrics import is_sampled_for_ragas, sanitize_error_message
from app.services.provider_runtime import capture_provider_usage, current_provider_calls, record_provider_event, ProviderEvent

settings = get_settings()


async def capture_judge_usage(response: httpx.Response) -> None:
    """Read usage only; never retain or log request prompts or response bodies."""
    if not response.request.url.path.endswith('/chat/completions'):
        return  # Embedding accounting is explicitly outside the LLM ledger.
    await response.aread()
    try:
        body = response.json()
    except ValueError:
        body = {}
    body = body if isinstance(body, dict) else {}
    usage = body.get('usage') if isinstance(body.get('usage'), dict) else {}
    details = usage.get('completion_tokens_details') if isinstance(usage.get('completion_tokens_details'), dict) else {}
    def token(value):
        return value if type(value) is int and 0 <= value <= 10**12 else None
    record_provider_event(ProviderEvent(
        provider='omnigate', model=str(body.get('model') or 'unobserved')[:200], use_case='evaluation',
        success=response.is_success, error_kind=None if response.is_success else 'http_' + str(response.status_code),
        latency_ms=None, fallback_used=False, timestamp=datetime.now(timezone.utc).isoformat(),
        prompt_token_count=token(usage.get('prompt_tokens')), output_token_count=token(usage.get('completion_tokens')),
        thinking_token_count=token(details.get('reasoning_tokens')), total_token_count=token(usage.get('total_tokens')),
    ))


def _install_ragas_vertex_shim() -> None:
    """Satisfy a stale optional Ragas import without installing Vertex AI."""
    package_name = "langchain_community.chat_models"
    module_name = f"{package_name}.vertexai"
    if module_name in sys.modules:
        return
    package = sys.modules.get(package_name)
    if package is None:
        package = types.ModuleType(package_name)
        package.__path__ = []
        sys.modules[package_name] = package
    vertex_module = types.ModuleType(module_name)
    vertex_module.ChatVertexAI = None
    sys.modules[module_name] = vertex_module


def _numeric_score(result: object, metric_name: str) -> float:
    value = getattr(result, "value", result)
    score = float(value)
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise ValueError(f"{metric_name} returned an invalid score")
    return score


async def _score_ragas_metrics(
    user_query: str, context: List[str], bot_response: str
) -> dict[str, float]:
    """Score the reference-free public-chat metrics with Ragas 0.4.x."""
    _install_ragas_vertex_shim()
    from openai import AsyncOpenAI
    from ragas.embeddings import embedding_factory
    from ragas.llms import llm_factory
    from ragas.metrics.collections import AnswerRelevancy, Faithfulness

    client = AsyncOpenAI(
        api_key=settings.LITELLM_MASTER_KEY,
        base_url=settings.OMNIGATE_BASE_URL,
        timeout=60.0,
        max_retries=1,
        http_client=httpx.AsyncClient(event_hooks={'response': [capture_judge_usage]}),
    )
    try:
        llm = llm_factory(
            "legal-core-model", client=client, temperature=0, max_tokens=768
        )
        embeddings = embedding_factory(
            "openai", model="legal-embedding-model", client=client
        )
        faithfulness = Faithfulness(llm=llm)
        answer_relevance = AnswerRelevancy(llm=llm, embeddings=embeddings, strictness=1)
        faithfulness_result = await faithfulness.ascore(
            user_input=user_query,
            response=bot_response,
            retrieved_contexts=context,
        )
        relevance_result = await answer_relevance.ascore(
            user_input=user_query,
            response=bot_response,
        )
        return {
            "faithfulness": _numeric_score(faithfulness_result, "faithfulness"),
            "answer_relevance": _numeric_score(relevance_result, "answer_relevance"),
        }
    finally:
        await client.close()


@logfire.instrument("Chạy đánh giá chất lượng Ragas proxy (LLM-as-a-judge)")
@capture_provider_usage
async def run_llm_as_judge(
    user_query: str,
    context: List[str],
    bot_response: str,
    trace_id: str,
    *,
    force: bool = False,
) -> None:
    mode = getattr(settings, "RAGAS_EVALUATION_MODE", "off")
    if mode == "off" and not force:
        return
    if not context:
        logfire.warning("Không có context để đánh giá Ragas.", trace_id=trace_id)
        return
    if mode == "sample" and not force:
        sample_rate = getattr(settings, "RAGAS_SAMPLE_RATE", 0.1)
        if not is_sampled_for_ragas(trace_id, sample_rate):
            return

    try:
        scores = await _score_ragas_metrics(user_query, context, bot_response)
        from app.database import update_evaluation

        await update_evaluation(
            trace_id,
            faithfulness=scores["faithfulness"],
            answer_relevance=scores["answer_relevance"],
            status="ok",
            error=None,
            executed=True,
            provider_calls=current_provider_calls(),
        )
        logfire.info("Đánh giá Ragas proxy hoàn thành", trace_id=trace_id, metrics=scores)
    except Exception as error:
        safe_message = sanitize_error_message(error)
        logfire.error("Lỗi khi chạy Ragas evaluator: {error}", error=safe_message, trace_id=trace_id)
        try:
            from app.database import update_evaluation

            await update_evaluation(
                trace_id,
                faithfulness=None,
                answer_relevance=None,
                status="error",
                error={"error_type": error.__class__.__name__, "message": safe_message},
                executed=True,
                provider_calls=current_provider_calls(),
            )
        except Exception as db_error:
            logfire.error(
                "Lỗi khi ghi nhận trạng thái lỗi Ragas vào DB: {error}",
                error=sanitize_error_message(db_error),
                trace_id=trace_id,
            )
