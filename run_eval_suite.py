import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from app.evaluation.provider_catalog import JUDGE_PROVIDER_MODELS

# Configure UTF-8 encoding for stdout to handle Vietnamese characters on Windows
sys.stdout.reconfigure(encoding="utf-8")
PROJECT_ROOT = Path(__file__).resolve().parent


DEFAULT_DATASET_PATH = PROJECT_ROOT / "app/data/namsyntax_legal_qa_420.json"
DEFAULT_CHECKPOINT_PATH = PROJECT_ROOT / "docs/eval_checkpoints.json"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "docs/system_evaluation_report.md"
EVALUATION_VERSION = "golden-v3-deterministic-1.0"
ANSWER_ACCURACY_PASS_THRESHOLD = 0.5


def get_settings():
    from app.config import get_settings as load_settings

    return load_settings()


async def check_input_guardrails(query: str):
    from app.services.guardrails import check_input_guardrails as check

    return await check(query)


async def check_output_guardrails(response: str, contexts: list[str], query: str):
    from app.services.guardrails import check_output_guardrails as check

    return await check(response, contexts, query)


async def warm_evaluation_guardrails() -> None:
    from app.services.guardrails import warm_guardrails

    await warm_guardrails()


def require_evaluation_fts(index) -> None:
    if not index.is_ready():
        raise RuntimeError(
            "Legal FTS is not ready. Run: python -u -m "
            "app.ingestion.legal_fts build --batch-size 256"
        )


async def verify_evaluation_fts(settings) -> None:
    from app.ingestion.content_store import ContentStore
    from app.ingestion.legal_fts import LegalFtsIndex

    index = LegalFtsIndex(
        store=ContentStore(settings.CONTENT_STORE_PATH),
        path=settings.LEGAL_FTS_PATH,
        dataset_revision=settings.DATASET_REVISION,
    )
    await asyncio.to_thread(require_evaluation_fts, index)


async def run_advanced_rag(query: str):
    from app.services.rag_pipeline import run_advanced_rag as run

    return await run(query)


async def check_semantic_cache(query: str):
    from app.services.semantic_cache import check_semantic_cache as check

    return await check(query)


def _evenly_spaced(items: list[dict], count: int) -> list[dict]:
    if count < 0:
        raise ValueError("Sample counts cannot be negative.")
    if count == 0:
        return []
    if count > len(items):
        raise ValueError(
            f"Requested {count} samples from a group with {len(items)} rows."
        )
    if count == 1:
        return [items[0]]
    return [
        items[index * (len(items) - 1) // (count - 1)]
        for index in range(count)
    ]


def _interleave_groups(groups: list[list[dict]]) -> list[dict]:
    result: list[dict] = []
    max_length = max((len(group) for group in groups), default=0)
    for index in range(max_length):
        for group in groups:
            if index < len(group):
                result.append(group[index])
    return result


def load_evaluation_dataset(
    dataset_path: str | Path = DEFAULT_DATASET_PATH,
    *,
    factoid_count: int = 12,
    multihop_count: int = 12,
    unanswerable_count: int = 6,
) -> list[dict]:
    path = Path(dataset_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Could not find dataset at: {path}")

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError("Golden dataset must be a JSON array.")

    grouped = {
        kind: [item for item in data if item.get("question_type") == kind]
        for kind in ("factoid", "multi-hop", "unanswerable")
    }
    sampled = _interleave_groups(
        [
            _evenly_spaced(grouped["factoid"], factoid_count),
            _evenly_spaced(grouped["multi-hop"], multihop_count),
            _evenly_spaced(grouped["unanswerable"], unanswerable_count),
        ]
    )
    selected: list[dict] = []
    for item in sampled:
        question = str(item.get("question") or "").strip()
        if not question:
            raise ValueError("Golden dataset contains an empty question.")
        kind = str(item.get("question_type") or "factoid")
        selected.append(
            {
                **item,
                "query": question,
                "group": kind.capitalize(),
                "expected": (
                    "honest_refusal"
                    if kind == "unanswerable"
                    else "grounded_answer"
                ),
                "ground_truth": str(
                    item.get("ground_truth_answer") or ""
                ).strip(),
                "reference_contexts": list(
                    item.get("ground_truth_context") or []
                ),
            }
        )
    return selected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate VietLex RAG against the 420-row golden dataset."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--factoids", type=int, default=12)
    parser.add_argument("--multihop", type=int, default=12)
    parser.add_argument("--unanswerable", type=int, default=6)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--judge-concurrency", type=int, default=4)
    parser.add_argument(
        "--judge",
        choices=["none", "ragas"],
        default="none",
        help="Optional LLM judge mode (default: none)",
    )
    parser.add_argument("--use-cache", action="store_true")
    parser.add_argument(
        "--skip-ragas",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument(
        "--checkpoint", type=Path, default=DEFAULT_CHECKPOINT_PATH
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    return parser


def judge_enabled(arguments: argparse.Namespace) -> bool:
    """Return whether the legacy runner should make optional Ragas calls."""
    return arguments.judge == "ragas" and not arguments.skip_ragas


def evaluation_fingerprint(
    cases: list[dict],
    *,
    run_ragas: bool,
    use_cache: bool = False,
    configuration: dict | None = None,
) -> str:
    identity = {
        "version": EVALUATION_VERSION,
        "run_ragas": run_ragas,
        "use_cache": use_cache,
        "configuration": configuration or {},
        "cases": [
            {
                "query": case["query"],
                "ground_truth": case.get("ground_truth", ""),
                "reference_contexts": case.get("reference_contexts", []),
            }
            for case in cases
        ],
    }
    payload = json.dumps(identity, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def runtime_evaluation_configuration(settings, *, run_ragas: bool) -> dict:
    fields = (
        "DATASET_REVISION",
        "PINECONE_INDEX_NAME",
        "PINECONE_NAMESPACE",
        "DENSE_INFERENCE_MODEL",
        "PINECONE_HYBRID_ALPHA",
        "RETRIEVAL_DOCUMENT_LIMIT",
        "QUERY_CHUNK_MAX_TOKENS",
        "QUERY_CHUNK_OVERLAP_TOKENS",
        "RERANK_CANDIDATE_LIMIT",
        "RERANK_PER_DOCUMENT_LIMIT",
        "RERANK_RETURN_LIMIT",
        "RERANK_MIN_SCORE",
        "RERANK_TOP_K",
        "QDRANT_RERANK_MODEL",
        "PINECONE_RERANK_MODEL",
        "LEGAL_FTS_RESULT_LIMIT",
        "LLM_CONTEXT_MAX_TOKENS",
        "LLM_MAX_OUTPUT_TOKENS",
    )
    configuration = {
        field: getattr(settings, field, None) for field in fields
    }
    if run_ragas:
        configuration["judge_chain"] = [
            {"name": provider["name"], "model": provider["model"]}
            for provider in configured_judge_providers(settings)
        ]
    return configuration


# Honest refusal keywords detection
REFUSAL_KEYWORDS = [
    "không biết",
    "không có thông tin",
    "chưa có dữ liệu",
    "không tìm thấy",
    "không đủ dữ liệu",
    "tài liệu không đề cập",
    "xin lỗi",
    "không thể cung cấp",
]

def is_honest_refusal(text: str) -> bool:
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in REFUSAL_KEYWORDS)


def _metric_terms(text: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[^\W_]+", text.casefold(), re.UNICODE)
        if len(term) >= 2
    }


def retrieval_metrics(
    contexts: list[str],
    reference_contexts: list[str],
) -> dict[str, float | bool | None]:
    if not reference_contexts:
        return {
            "gold_context_hit": None,
            "gold_context_recall": None,
            "reciprocal_rank": None,
        }
    matched = 0
    first_rank: int | None = None
    normalized_contexts = [" ".join(item.casefold().split()) for item in contexts]
    context_terms = [_metric_terms(item) for item in contexts]
    for reference in reference_contexts:
        normalized_reference = " ".join(reference.casefold().split())
        reference_terms = _metric_terms(reference)
        matched_rank: int | None = None
        for rank, (normalized, terms) in enumerate(
            zip(normalized_contexts, context_terms, strict=True),
            start=1,
        ):
            overlap = (
                len(reference_terms & terms) / len(reference_terms)
                if reference_terms
                else 0.0
            )
            if (
                normalized_reference
                and normalized_reference in normalized
            ) or overlap >= 0.6:
                matched_rank = rank
                break
        if matched_rank is not None:
            matched += 1
            if first_rank is None or matched_rank < first_rank:
                first_rank = matched_rank
    return {
        "gold_context_hit": matched > 0,
        "gold_context_recall": matched / len(reference_contexts),
        "reciprocal_rank": 1.0 / first_rank if first_rank else 0.0,
    }


def summarize_outcomes(results: list[dict]) -> dict[str, float | int]:
    technical_statuses = {
        "rag_error",
        "retrieval_error",
        "reranker_error",
        "Input Guardrail Error",
        "Output Guardrail Error",
    }

    def service_completed(result: dict) -> bool:
        return (
            result.get("evaluation_status") not in technical_statuses
            and result.get("retrieval_status")
            not in {"rag_error", "retrieval_error", "reranker_error"}
        )

    answerable = [
        result
        for result in results
        if result.get("expected") == "grounded_answer"
    ]
    unanswerable = [
        result
        for result in results
        if result.get("expected") == "honest_refusal"
    ]
    grounded_generations = sum(
        1
        for result in answerable
        if service_completed(result)
        if result.get("output_safe")
        and result.get("contexts")
        and not result.get("is_refusal")
        and result.get("evaluation_status") != "Blocked Output"
    )
    answerable_correct = sum(
        1
        for result in answerable
        if service_completed(result)
        and result.get("output_safe")
        and result.get("contexts")
        and not result.get("is_refusal")
        and isinstance(result.get("answer_accuracy"), (int, float))
        and result["answer_accuracy"] >= ANSWER_ACCURACY_PASS_THRESHOLD
    )
    correct_unanswerable = sum(
        1
        for result in unanswerable
        if service_completed(result)
        and result.get("evaluation_status")
        in {"Honest Refusal", "No Evidence"}
        and result.get("is_refusal")
    )
    all_refusals = sum(
        1
        for result in results
        if result.get("is_refusal") and service_completed(result)
    )
    valid_count = len(answerable) + len(unanswerable)
    return {
        "answerable_count": len(answerable),
        "unanswerable_count": len(unanswerable),
        "answerable_correct": answerable_correct,
        "grounded_generation_count": grounded_generations,
        "unanswerable_correct": correct_unanswerable,
        "answerable_accuracy": (
            answerable_correct / len(answerable) if answerable else 0.0
        ),
        "grounded_generation_rate": (
            grounded_generations / len(answerable) if answerable else 0.0
        ),
        "service_completion_rate": (
            sum(1 for result in results if service_completed(result))
            / len(results)
            if results
            else 0.0
        ),
        "unanswerable_accuracy": (
            correct_unanswerable / len(unanswerable)
            if unanswerable
            else 0.0
        ),
        "refusal_precision": (
            correct_unanswerable / all_refusals if all_refusals else 0.0
        ),
        "refusal_recall": (
            correct_unanswerable / len(unanswerable)
            if unanswerable
            else 0.0
        ),
        "overall_accuracy": (
            (answerable_correct + correct_unanswerable) / valid_count
            if valid_count
            else 0.0
        ),
    }

async def evaluate_single_query(
    case: dict,
    settings,
    ragas_evaluator,
    evaluation_fingerprint: str,
    *,
    use_cache: bool = False,
    queue_latency: float = 0.0,
) -> dict:
    query = case["query"]
    group = case["group"]
    expected = case["expected"]
    print(f"\nEvaluating: [{group}] '{query}'")

    started = time.perf_counter()
    input_guardrail_latency = 0.0
    output_guardrail_latency = 0.0
    ragas_latency = 0.0
    primary_judge = (
        getattr(ragas_evaluator, "provider", {})
        if ragas_evaluator
        else {}
    )
    judge_provider_name = primary_judge.get("name")
    judge_model_name = primary_judge.get("model")

    def elapsed() -> float:
        return queue_latency + time.perf_counter() - started

    def base_result(**overrides) -> dict:
        empty_retrieval_metrics = retrieval_metrics(
            [], case.get("reference_contexts", [])
        )
        result = {
            "query": query,
            "group": group,
            "expected": expected,
            "cache_hit": False,
            "input_safe": True,
            "output_safe": True,
            "response": "",
            "contexts": [],
            "latency": elapsed(),
            "queue_latency": queue_latency,
            "pipeline_latency": time.perf_counter() - started,
            "input_guardrail_latency": input_guardrail_latency,
            "output_guardrail_latency": output_guardrail_latency,
            "ragas_latency": ragas_latency,
            "judge_provider": judge_provider_name,
            "judge_model": judge_model_name,
            "lat_info": {},
            "retrieval_status": None,
            "retrieval_diagnostics": {},
            **empty_retrieval_metrics,
            "faithfulness": None,
            "answer_accuracy": None,
            "context_precision": None,
            "context_recall": None,
            "evaluation_status": "Eval Failed",
            "is_refusal": False,
            "evaluation_fingerprint": evaluation_fingerprint,
            "error": None,
        }
        result.update(overrides)
        return result

    cached_response = (
        await check_semantic_cache(query) if use_cache else None
    )
    cache_hit = cached_response is not None
    if cache_hit:
        latency = elapsed()
        print(f"-> Cache Hit! Latency: {latency:.2f}s")
        return base_result(
            cache_hit=True,
            response=cached_response,
            latency=latency,
            evaluation_status="Cache Hit (not scored)",
            is_refusal=is_honest_refusal(cached_response),
        )

    guardrail_started = time.perf_counter()
    try:
        input_safe, rejection_message = await check_input_guardrails(query)
        input_guardrail_latency = time.perf_counter() - guardrail_started
    except Exception as error:
        input_guardrail_latency = time.perf_counter() - guardrail_started
        print(f"-> Input Guardrails Error: {error}")
        return base_result(
            input_safe=False,
            output_safe=False,
            evaluation_status="Input Guardrail Error",
            error=str(error),
        )

    if not input_safe:
        latency = elapsed()
        print(f"-> Blocked by Input Guardrails. Latency: {latency:.2f}s")
        return base_result(
            input_safe=False,
            response=rejection_message,
            latency=latency,
            evaluation_status="Blocked Input",
            is_refusal=False,
        )

    try:
        bot_response, contexts, lat_info = await run_advanced_rag(query)
    except Exception as error:
        print(f"-> Error in RAG pipeline: {error}")
        error_latency = getattr(error, "latency", {}) or {}
        retrieval_status = getattr(error, "status", None)
        diagnostics = getattr(error, "diagnostics", {}) or {}
        return base_result(
            output_safe=False,
            lat_info=error_latency,
            retrieval_status=retrieval_status,
            retrieval_diagnostics=diagnostics,
            evaluation_status=(
                retrieval_status or "rag_error"
            ),
            error=str(error),
        )

    retrieval_status = lat_info.get("retrieval_status")
    retrieval_diagnostics = lat_info.get("retrieval_diagnostics", {})
    guardrail_started = time.perf_counter()
    try:
        output_safe, fallback_response = await check_output_guardrails(
            bot_response,
            contexts,
            query,
        )
        output_guardrail_latency = time.perf_counter() - guardrail_started
    except Exception as error:
        output_guardrail_latency = time.perf_counter() - guardrail_started
        print(f"-> Output Guardrails Error: {error}")
        direct_metrics = retrieval_metrics(
            contexts,
            case.get("reference_contexts", []),
        )
        return base_result(
            output_safe=False,
            response=bot_response,
            contexts=contexts,
            lat_info=lat_info,
            retrieval_status=retrieval_status,
            retrieval_diagnostics=retrieval_diagnostics,
            evaluation_status="Output Guardrail Error",
            error=str(error),
            **direct_metrics,
        )

    final_response = bot_response if output_safe else fallback_response
    pipeline_latency = time.perf_counter() - started
    print(
        f"-> RAG Done. Output Safe: {output_safe}. "
        f"Latency: {queue_latency + pipeline_latency:.2f}s"
    )
    is_refusal = not contexts or is_honest_refusal(final_response)
    direct_metrics = retrieval_metrics(
        contexts,
        case.get("reference_contexts", []),
    )
    faithfulness = None
    answer_accuracy = None
    context_precision = None
    context_recall = None
    ragas_error: str | None = None

    if not contexts:
        eval_status = "No Evidence"
    elif not output_safe:
        eval_status = "Blocked Output"
    elif is_refusal:
        eval_status = "Honest Refusal"
    elif ragas_evaluator is None:
        eval_status = "Generated (Ragas skipped)"
    else:
        eval_status = "Generated"
        ragas_started = time.perf_counter()
        try:
            print("-> Running Ragas Evaluator...")
            scores = await ragas_evaluator(
                query=query,
                response=final_response,
                contexts=contexts,
                reference=case.get("ground_truth", ""),
            )
            faithfulness = scores["faithfulness"]
            answer_accuracy = scores["answer_accuracy"]
            context_precision = scores["context_precision"]
            context_recall = scores["context_recall"]
            judge_provider_name = scores.get(
                "_judge_provider", judge_provider_name
            )
            judge_model_name = scores.get("_judge_model", judge_model_name)
            print(
                "   Ragas - Faithfulness: "
                f"{faithfulness:.2f}, Accuracy: {answer_accuracy:.2f}, "
                f"Precision: {context_precision:.2f}, "
                f"Recall: {context_recall:.2f}"
            )
        except Exception as error:
            print(f"   Ragas Evaluation Error: {error}")
            eval_status = "Eval Failed"
            ragas_error = str(error)
        finally:
            ragas_latency = time.perf_counter() - ragas_started

    return base_result(
        output_safe=output_safe,
        response=final_response,
        contexts=contexts,
        latency=elapsed(),
        pipeline_latency=pipeline_latency,
        ragas_latency=ragas_latency,
        lat_info=lat_info,
        retrieval_status=retrieval_status,
        retrieval_diagnostics=retrieval_diagnostics,
        judge_provider=judge_provider_name,
        judge_model=judge_model_name,
        faithfulness=faithfulness,
        answer_accuracy=answer_accuracy,
        context_precision=context_precision,
        context_recall=context_recall,
        evaluation_status=eval_status,
        is_refusal=is_refusal,
        error=ragas_error,
        **direct_metrics,
    )

def configured_judge_providers(settings) -> list[dict[str, str]]:
    runtime_mapping = (
        (
            "GEMINI_API_KEY",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        ),
        (
            "NVIDIA_API_KEY",
            "https://integrate.api.nvidia.com/v1",
        ),
        (
            "GROQ_API_KEY",
            "https://api.groq.com/openai/v1",
        ),
        (
            "OPENROUTER_API_KEY",
            "https://openrouter.ai/api/v1",
        ),
    )
    providers: list[dict[str, str]] = [
        {
            "name": "Google Vertex AI",
            "model": getattr(settings, "VERTEX_LLM_MODEL", "gemini-3.5-flash"),
            "transport": "vertex_adc",
        }
    ]
    for (field, base_url), provider_model in zip(
        runtime_mapping,
        JUDGE_PROVIDER_MODELS[:4],
        strict=True,
    ):
        api_key = getattr(settings, field, None)
        if api_key:
            providers.append(
                {
                    "name": provider_model.provider,
                    "model": provider_model.model,
                    "api_key": api_key,
                    "base_url": base_url,
                }
            )
    gateway_key = getattr(settings, "LITELLM_MASTER_KEY", None)
    if gateway_key:
        gateway_model = JUDGE_PROVIDER_MODELS[4]
        providers.append(
            {
                "name": gateway_model.provider,
                "model": gateway_model.model,
                "api_key": gateway_key,
                "base_url": settings.OMNIGATE_BASE_URL,
            }
        )
    if not providers:
        raise RuntimeError("No API key is configured for the Ragas judge.")
    return providers


def select_judge_provider(settings) -> dict[str, str]:
    return configured_judge_providers(settings)[0]


def is_transient_judge_error(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        status_code = getattr(
            getattr(error, "response", None),
            "status_code",
            None,
        )
    if status_code in {408, 409, 429, 500, 502, 503, 504}:
        return True
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return True
    message = str(error).casefold()
    if any(
        marker in message
        for marker in (
            "error code: 429",
            "quota exceeded",
            "rate limit",
            "timed out",
            "timeout",
            "connection error",
            "service unavailable",
        )
    ):
        return True
    return type(error).__name__ in {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ConnectTimeout",
        "RateLimitError",
        "ReadTimeout",
        "TimeoutException",
    }


def is_unavailable_judge_error(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        status_code = getattr(
            getattr(error, "response", None),
            "status_code",
            None,
        )
    return status_code == 404 or "error code: 404" in str(error).casefold()


async def run_with_provider_fallback(providers, operation):
    for index, provider in enumerate(providers):
        try:
            return await operation(provider), provider
        except Exception as error:
            has_fallback = index + 1 < len(providers)
            if not has_fallback or not (
                is_transient_judge_error(error)
                or is_unavailable_judge_error(error)
            ):
                raise
            next_provider = providers[index + 1]
            print(
                f"Ragas judge {provider['name']} unavailable "
                f"({type(error).__name__}); falling back to "
                f"{next_provider['name']}.",
                flush=True,
            )
    raise RuntimeError("Ragas judge fallback chain ended unexpectedly.")


def _install_ragas_vertex_shim() -> None:
    """Avoid importing the unused and very slow Vertex AI integration."""
    import types

    if "langchain_community.chat_models" not in sys.modules:
        sys.modules["langchain_community.chat_models"] = types.ModuleType(
            "langchain_community.chat_models"
        )
    module_name = "langchain_community.chat_models.vertexai"
    if module_name not in sys.modules:
        vertex_module = types.ModuleType(module_name)
        vertex_module.ChatVertexAI = None
        sys.modules[module_name] = vertex_module


def _build_vertex_ragas_llm():
    from ragas.llms.base import InstructorBaseRagasLLM

    from app.services.vertex_ai import get_vertex_provider

    class VertexRagasLLM(InstructorBaseRagasLLM):
        async def agenerate(
            self,
            prompt: str,
            response_model,
        ):
            return await get_vertex_provider().generate_structured(
                prompt,
                response_model=response_model,
                max_output_tokens=768,
            )

        def generate(
            self,
            prompt: str,
            response_model,
        ):
            return asyncio.run(
                self.agenerate(prompt, response_model)
            )

    return VertexRagasLLM()


def build_ragas_evaluator(settings, *, judge_concurrency: int):
    if judge_concurrency <= 0:
        raise ValueError("judge_concurrency must be positive.")
    _install_ragas_vertex_shim()

    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.metrics.collections import (
        AnswerAccuracy,
        ContextPrecision,
        ContextRecall,
        Faithfulness,
    )

    providers = configured_judge_providers(settings)
    metrics_by_provider: dict[str, dict] = {}

    def provider_metrics(provider: dict[str, str]) -> dict:
        key = f"{provider['name']}:{provider['model']}"
        if key not in metrics_by_provider:
            if provider.get("transport") == "vertex_adc":
                llm = _build_vertex_ragas_llm()
            else:
                client = AsyncOpenAI(
                    api_key=provider["api_key"],
                    base_url=provider["base_url"],
                    timeout=60.0,
                    max_retries=1,
                )
                llm = llm_factory(
                    provider["model"],
                    client=client,
                    temperature=0,
                    max_tokens=768,
                )
            metrics_by_provider[key] = {
                "faithfulness": Faithfulness(llm=llm),
                "answer_accuracy": AnswerAccuracy(llm=llm),
                "context_precision": ContextPrecision(llm=llm),
                "context_recall": ContextRecall(llm=llm),
            }
        return metrics_by_provider[key]
    semaphore = asyncio.Semaphore(judge_concurrency)

    async def score(name: str, operation) -> tuple[str, float]:
        async with semaphore:
            result = await operation()
        value = float(result.value)
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"Ragas {name} returned invalid score {value}.")
        return name, value

    async def evaluate_with_provider(
        provider: dict[str, str],
        *,
        query: str,
        response: str,
        contexts: list[str],
        reference: str,
    ) -> dict[str, float]:
        metrics = provider_metrics(provider)
        scored = [
            await score(
                "faithfulness",
                lambda: metrics["faithfulness"].ascore(
                    user_input=query,
                    response=response,
                    retrieved_contexts=contexts,
                ),
            ),
            await score(
                "answer_accuracy",
                lambda: metrics["answer_accuracy"].ascore(
                    user_input=query,
                    response=response,
                    reference=reference,
                ),
            ),
            await score(
                "context_precision",
                lambda: metrics["context_precision"].ascore(
                    user_input=query,
                    reference=reference,
                    retrieved_contexts=contexts,
                ),
            ),
            await score(
                "context_recall",
                lambda: metrics["context_recall"].ascore(
                    user_input=query,
                    reference=reference,
                    retrieved_contexts=contexts,
                ),
            ),
        ]
        return dict(scored)

    async def evaluate_case(
        *,
        query: str,
        response: str,
        contexts: list[str],
        reference: str,
    ) -> dict[str, float]:
        if not reference:
            raise ValueError("Golden reference answer is empty.")
        scores, used_provider = await run_with_provider_fallback(
            providers,
            lambda provider: evaluate_with_provider(
                provider,
                query=query,
                response=response,
                contexts=contexts,
                reference=reference,
            ),
        )
        return {
            **scores,
            "_judge_provider": used_provider["name"],
            "_judge_model": used_provider["model"],
        }

    print(
        "Using Ragas judge chain: "
        + " -> ".join(
            f"{provider['name']} {provider['model']}"
            for provider in providers
        )
    )
    evaluate_case.provider = providers[0]
    evaluate_case.providers = providers
    return evaluate_case

def is_valid_checkpoint(r: dict, fingerprint: str) -> bool:
    if not isinstance(r, dict):
        return False
    if r.get("evaluation_fingerprint") != fingerprint:
        return False
    if r.get("evaluation_status") == "Eval Failed":
        return False
    if r.get("error"):
        return False
    resp = r.get("response", "")
    if "Hệ thống chưa thể xử lý" in resp or "Đã xảy ra lỗi" in resp:
        return False
    if (
        r.get("evaluation_status") != "Generated (Ragas skipped)"
        and r.get("input_safe")
        and r.get("output_safe")
        and not r.get("is_refusal")
        and not r.get("cache_hit")
    ):
        for metric in (
            "faithfulness",
            "answer_accuracy",
            "context_precision",
            "context_recall",
        ):
            score = r.get(metric)
            if score is None or (
                isinstance(score, float) and score != score
            ):
                return False
    return True

def _write_checkpoint(path: Path, results: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(results, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


def _average(results: list[dict], field: str) -> float | None:
    values = [
        float(result[field])
        for result in results
        if result.get(field) is not None
    ]
    return sum(values) / len(values) if values else None


def _score_text(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def write_report(path: Path, results: list[dict], *, use_cache: bool) -> None:
    total = len(results)
    errors = sum(1 for result in results if result.get("error"))
    cache_hits = sum(1 for result in results if result["cache_hit"])
    output_blocked = sum(
        1
        for result in results
        if result["evaluation_status"] == "Blocked Output"
    )
    valid_inputs = [result for result in results if not result.get("error")]
    legal_input_pass_rate = (
        100.0
        * sum(1 for result in valid_inputs if result["input_safe"])
        / len(valid_inputs)
        if valid_inputs
        else 0.0
    )
    outcomes = summarize_outcomes(results)
    avg_latency = (
        sum(result["latency"] for result in results) / total
        if total
        else 0.0
    )
    metrics = {
        name: _average(results, name)
        for name in (
            "faithfulness",
            "answer_accuracy",
            "context_precision",
            "context_recall",
        )
    }
    average_queue = _average(results, "queue_latency") or 0.0
    average_pipeline = _average(results, "pipeline_latency") or 0.0
    average_ragas = _average(results, "ragas_latency") or 0.0
    retrieval_eligible = [
        result
        for result in results
        if result.get("gold_context_hit") is not None
    ]
    gold_hits = sum(
        1 for result in retrieval_eligible if result["gold_context_hit"]
    )
    gold_hit_rate = 100.0 * (
        gold_hits / len(retrieval_eligible)
        if retrieval_eligible
        else 0.0
    )
    gold_recall = _average(results, "gold_context_recall") or 0.0
    mean_reciprocal_rank = _average(results, "reciprocal_rank") or 0.0

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        file.write("# SYSTEM EVALUATION REPORT - VIETLEX LEGAL RAG\n\n")
        file.write(
            f"**Evaluation Timestamp**: `{datetime.now():%Y-%m-%d %H:%M:%S}`  \n"
        )
        file.write(
            f"**Number of Test Queries**: `{total}` across Factoid, "
            "Multi-hop and Unanswerable groups  \n"
        )
        file.write(f"**Semantic cache enabled**: `{use_cache}`  \n")
        file.write(
            "**Dataset warning**: third-party research data; not an "
            "official source of current Vietnamese law.\n\n"
        )
        file.write("## Metrics\n\n")
        file.write("| Metric | Value |\n| :--- | ---: |\n")
        file.write(f"| Average end-to-end latency | {avg_latency:.2f}s |\n")
        file.write(f"| Average queue latency | {average_queue:.2f}s |\n")
        file.write(f"| Average online pipeline latency | {average_pipeline:.2f}s |\n")
        file.write(f"| Average Ragas latency | {average_ragas:.2f}s |\n")
        file.write(f"| Evaluation failures | {errors}/{total} |\n")
        file.write(f"| Cache hits | {cache_hits}/{total} |\n")
        file.write(f"| Legal input pass rate | {legal_input_pass_rate:.1f}% |\n")
        file.write(
            "| Answerable accuracy | "
            f"{100.0 * outcomes['answerable_accuracy']:.1f}% "
            f"({outcomes['answerable_correct']}/"
            f"{outcomes['answerable_count']}) |\n"
        )
        file.write(
            "| Grounded generation rate | "
            f"{100.0 * outcomes['grounded_generation_rate']:.1f}% "
            f"({outcomes['grounded_generation_count']}/"
            f"{outcomes['answerable_count']}) |\n"
        )
        file.write(
            "| Service completion rate | "
            f"{100.0 * outcomes['service_completion_rate']:.1f}% |\n"
        )
        file.write(
            "| Unanswerable accuracy | "
            f"{100.0 * outcomes['unanswerable_accuracy']:.1f}% "
            f"({outcomes['unanswerable_correct']}/"
            f"{outcomes['unanswerable_count']}) |\n"
        )
        file.write(
            f"| Refusal precision | {100.0 * outcomes['refusal_precision']:.1f}% |\n"
        )
        file.write(
            f"| Refusal recall | {100.0 * outcomes['refusal_recall']:.1f}% |\n"
        )
        file.write(
            f"| Gold context hit rate | {gold_hit_rate:.1f}% "
            f"({gold_hits}/{len(retrieval_eligible)}) |\n"
        )
        file.write(f"| Gold context recall | {gold_recall:.2f} |\n")
        file.write(f"| Retrieval MRR | {mean_reciprocal_rank:.2f} |\n")
        file.write(f"| Output blocked | {output_blocked}/{total} |\n")
        file.write(
            f"| Ragas Faithfulness | {_score_text(metrics['faithfulness'])} |\n"
        )
        file.write(
            f"| Ragas Answer Accuracy | {_score_text(metrics['answer_accuracy'])} |\n"
        )
        file.write(
            "| Ragas Context Precision | "
            f"{_score_text(metrics['context_precision'])} |\n"
        )
        file.write(
            f"| Ragas Context Recall | {_score_text(metrics['context_recall'])} |\n\n"
        )
        file.write(
            "> Cache hits and honest refusals are not assigned artificial "
            "Ragas scores. Metric averages include scored generations only.\n\n"
        )
        file.write(
            "> Answerable accuracy requires Ragas answer accuracy >= "
            f"{ANSWER_ACCURACY_PASS_THRESHOLD:.2f}; technical failures remain "
            "in denominators. Reference-less cases are excluded from direct "
            "retrieval metrics.\n\n"
        )
        file.write("## Scenarios\n\n")
        file.write(
            "| ID | Group | Query | Status | Latency | Faithfulness | "
            "Accuracy | Precision | Recall |\n"
        )
        file.write(
            "| :-: | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |\n"
        )
        for index, result in enumerate(results, start=1):
            query = result["query"].replace("|", "\\|")
            file.write(
                f"| {index} | {result['group']} | {query} | "
                f"{result['evaluation_status']} | {result['latency']:.2f}s | "
                f"{_score_text(result['faithfulness'])} | "
                f"{_score_text(result['answer_accuracy'])} | "
                f"{_score_text(result['context_precision'])} | "
                f"{_score_text(result['context_recall'])} |\n"
            )


async def run_suite(arguments=None) -> list[dict]:
    args = arguments or build_parser().parse_args()
    if args.concurrency <= 0:
        raise ValueError("concurrency must be positive.")
    settings = get_settings()
    await verify_evaluation_fts(settings)
    await warm_evaluation_guardrails()
    cases = load_evaluation_dataset(
        args.dataset,
        factoid_count=args.factoids,
        multihop_count=args.multihop,
        unanswerable_count=args.unanswerable,
    )
    run_ragas = judge_enabled(args)
    fingerprint = evaluation_fingerprint(
        cases,
        run_ragas=run_ragas,
        use_cache=args.use_cache,
        configuration=runtime_evaluation_configuration(
            settings,
            run_ragas=run_ragas,
        ),
    )
    ragas_evaluator = (
        build_ragas_evaluator(
            settings,
            judge_concurrency=args.judge_concurrency,
        )
        if run_ragas
        else None
    )

    checkpoint_path = Path(args.checkpoint).resolve()
    completed: dict[str, dict] = {}
    if checkpoint_path.exists() and not args.fresh:
        try:
            saved = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            completed = {
                result["query"]: result
                for result in saved
                if is_valid_checkpoint(result, fingerprint)
            }
        except (OSError, ValueError, TypeError, KeyError) as error:
            print(f"Ignoring invalid checkpoint: {error}")

    print("=" * 60)
    print(f"VIETLEX GOLDEN EVALUATION: {len(cases)} queries")
    print(
        f"pipeline_concurrency={args.concurrency} "
        f"judge_concurrency={args.judge_concurrency} "
        f"cache={args.use_cache} ragas={run_ragas}"
    )
    print(f"Restored {len(completed)} valid checkpoint rows.")
    print("=" * 60)

    semaphore = asyncio.Semaphore(args.concurrency)
    result_map = dict(completed)

    async def evaluate_case(case: dict) -> dict:
        queued_at = time.perf_counter()
        async with semaphore:
            queue_latency = time.perf_counter() - queued_at
            return await evaluate_single_query(
                case,
                settings,
                ragas_evaluator,
                fingerprint,
                use_cache=args.use_cache,
                queue_latency=queue_latency,
            )

    tasks = [
        asyncio.create_task(evaluate_case(case))
        for case in cases
        if case["query"] not in completed
    ]
    for completed_task in asyncio.as_completed(tasks):
        result = await completed_task
        result_map[result["query"]] = result
        ordered_partial = [
            result_map[case["query"]]
            for case in cases
            if case["query"] in result_map
        ]
        _write_checkpoint(checkpoint_path, ordered_partial)
        print(f"Checkpoint: {len(ordered_partial)}/{len(cases)}")

    results = [result_map[case["query"]] for case in cases]
    _write_checkpoint(checkpoint_path, results)
    report_path = Path(args.report).resolve()
    write_report(report_path, results, use_cache=args.use_cache)
    print(f"Report written to: {report_path}")
    return results


if __name__ == "__main__":
    asyncio.run(run_suite())
