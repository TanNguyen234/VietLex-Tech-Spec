from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Dict, List, Tuple

import logfire

from app.config import get_settings
from app.services.direct_llm import (
    LLMGenerationResult,
    generate_llm_response_with_metadata,
)
from app.services.retrieval import (
    RetrievalOutcome,
    get_legal_retriever,
    get_structural_legal_retriever,
)



NO_EVIDENCE_RESPONSE = (
    "Xin lỗi, tôi không tìm thấy bằng chứng pháp luật đủ tin cậy "
    "trong kho dữ liệu để trả lời câu hỏi này."
)


class RetrievalPipelineError(RuntimeError):
    def __init__(
        self,
        status: str,
        message: str,
        diagnostics: dict[str, Any],
        latency: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.diagnostics = diagnostics
        self.latency = latency or {}


class QueryRewriteError(RuntimeError):
    """Typed rewrite failure used by observable evaluation paths."""


def _structural_retrieval_outcome(outcome: Any) -> RetrievalOutcome:
    from app.evaluation.structural_pilot_eval import (
        structural_evaluation_trace,
        to_metric_v3_trace,
    )

    technical_errors = {
        key: value.model_dump(mode="json")
        for key, value in outcome.technical_errors.items()
    }
    stage_trace = to_metric_v3_trace(
        structural_evaluation_trace(outcome.trace)
    )
    return RetrievalOutcome(
        evidence=list(outcome.evidence),
        latency={
            f"t_structural_{key}": value
            for key, value in outcome.latency.items()
        },
        status=(
            "partial_retrieval_error"
            if outcome.status == "partial_technical_error"
            else outcome.status
        ),
        diagnostics={
            "retrieval_backend": "qdrant_structural_v2",
            "structural_trace": outcome.trace,
            "stage_trace": stage_trace,
            "structural_technical_errors": technical_errors,
            "structural_provider_usage": dict(outcome.provider_usage),
        },
        error=(
            "Structural retrieval reported a technical error."
            if technical_errors
            else None
        ),
    )


async def _legacy_retrieval_outcome(
    rewritten_query: str,
    user_query: str,
    profile: Any,
) -> RetrievalOutcome:
    retrieval_kwargs: dict[str, Any] = {"sparse_query": user_query}
    if profile is not None:
        retrieval_kwargs["profile"] = profile
    return await get_legal_retriever().retrieve_detailed(
        rewritten_query,
        **retrieval_kwargs,
    )


async def retrieve_configured_legal_evidence(
    rewritten_query: str,
    user_query: str,
    profile: Any,
) -> RetrievalOutcome:
    if not get_settings().STRUCTURAL_BACKEND_ENABLED:
        return await _legacy_retrieval_outcome(
            rewritten_query,
            user_query,
            profile,
        )
    try:
        structural = _structural_retrieval_outcome(
            await get_structural_legal_retriever().retrieve(
                rewritten_query,
                sparse_query=user_query,
            )
        )
    except Exception as error:
        structural = RetrievalOutcome(
            evidence=[],
            latency={},
            status="retrieval_error",
            diagnostics={
                "retrieval_backend": "qdrant_structural_v2",
                "structural_technical_errors": {
                    "initialization": {
                        "category": type(error).__name__,
                    }
                },
            },
            error="Structural retrieval initialization failed.",
        )
    if structural.evidence and structural.status in {
        "ok",
        "partial_retrieval_error",
    }:
        return structural

    legacy = await _legacy_retrieval_outcome(
        rewritten_query,
        user_query,
        profile,
    )
    diagnostics = dict(legacy.diagnostics)
    diagnostics.update(
        {
            "retrieval_backend": "pinecone_v1_fallback",
            "structural_fallback_reason": structural.status,
            "structural_primary_technical_errors": (
                structural.diagnostics.get(
                    "structural_technical_errors",
                    {},
                )
            ),
        }
    )
    structural_failed = structural.status in {
        "retrieval_error",
        "reranker_error",
        "partial_retrieval_error",
    }
    status = legacy.status
    error = legacy.error
    if structural_failed and legacy.evidence and legacy.status == "ok":
        status = "partial_retrieval_error"
        error = structural.error
    return RetrievalOutcome(
        evidence=list(legacy.evidence),
        latency={**structural.latency, **legacy.latency},
        status=status,
        diagnostics=diagnostics,
        error=error,
    )


def build_bounded_context(
    context: List[str],
    *,
    max_tokens: int,
) -> str:
    """Assemble ranked evidence under one whitespace-token budget."""
    if max_tokens <= 0:
        return ""
    remaining = max_tokens
    blocks: list[str] = []
    for index, document in enumerate(context, start=1):
        label = f"[Tài liệu tham khảo #{index}]"
        label_tokens = label.split()
        document_tokens = document.split()
        available = remaining - len(label_tokens)
        if available <= 0:
            break
        selected = document_tokens[:available]
        if not selected:
            break
        blocks.append(f"{label}\n{' '.join(selected)}")
        remaining -= len(label_tokens) + len(selected)
        if len(selected) < len(document_tokens):
            break
    return "\n\n".join(blocks)


@logfire.instrument("Run advanced legal retrieval pipeline")
async def run_advanced_rag(
    user_query: str,
    *,
    rewrite_mode: str = "off",
    profile: Any = None,
) -> Tuple[str, List[str], Dict[str, Any]]:
    started = time.perf_counter()

    if rewrite_mode == "off":
        rewritten_query = user_query
        rewrite_seconds = 0.0
        rewrite_meta = {
            "provider": "none",
            "model": "none",
            "observed": False,
            "reason": "disabled",
        }
    else:
        rewrite_started = time.perf_counter()
        rewritten_query, rewrite_meta = await rewrite_query_with_metadata(
            user_query
        )
        rewrite_seconds = time.perf_counter() - rewrite_started

    retrieval_started = time.perf_counter()
    retrieval_outcome = await retrieve_configured_legal_evidence(
        rewritten_query,
        user_query,
        profile,
    )
    evidence = retrieval_outcome.evidence
    retrieval_seconds = time.perf_counter() - retrieval_started

    contexts = [
        chunk.formatted_context() for chunk in evidence
    ]
    latency = {
        "t_rewrite": round(rewrite_seconds, 3),
        "t_retrieval": round(retrieval_seconds, 3),
        **retrieval_outcome.latency,
        "t_llm": 0.0,
        "t_total": 0.0,
        "retrieval_status": retrieval_outcome.status,
        "retrieval_diagnostics": retrieval_outcome.diagnostics,
        "rewritten_query": rewritten_query,
        "retrieval_outcome": retrieval_outcome,
    }
    rewrite_provider_usage = {
        "query_rewrite": {
            "provider": rewrite_meta.get("provider", "unobserved"),
            "model": rewrite_meta.get("model", "unobserved"),
            "observed": bool(rewrite_meta.get("observed", False)),
        },
        "answer_generation": {
            "provider": "unobserved",
            "model": "unobserved",
            "observed": False,
        },
        "guardrails": {
            "provider": "unobserved",
            "model": "unobserved",
            "observed": False,
        },
    }
    latency["provider_usage"] = rewrite_provider_usage
    if rewrite_meta.get("observed") and rewrite_meta.get("provider") not in ("none", "unobserved"):
        latency["observed_provider"] = rewrite_meta["provider"]
        latency["observed_model"] = rewrite_meta.get("model", "unobserved")
    else:
        latency["observed_provider"] = "unobserved"
        latency["observed_model"] = "unobserved"

    if retrieval_outcome.status in {
        "retrieval_error",
        "reranker_error",
    }:
        latency["t_total"] = round(time.perf_counter() - started, 3)
        raise RetrievalPipelineError(
            retrieval_outcome.status,
            retrieval_outcome.error or "Legal retrieval failed.",
            retrieval_outcome.diagnostics,
            latency,
        )
    if not contexts:
        latency["t_total"] = round(
            time.perf_counter() - started,
            3,
        )
        latency["generation_status"] = "no_contexts"
        return NO_EVIDENCE_RESPONSE, [], latency

    llm_started = time.perf_counter()
    llm_result = await generate_response_with_metadata(
        user_query,
        rewritten_query,
        contexts,
    )
    latency["t_llm"] = round(
        time.perf_counter() - llm_started,
        3,
    )
    latency["t_total"] = round(
        time.perf_counter() - started,
        3,
    )
    latency["generation_status"] = getattr(llm_result, "status", "success")
    provider_usage = {
        "query_rewrite": {
            "provider": rewrite_meta.get("provider", "unobserved"),
            "model": rewrite_meta.get("model", "unobserved"),
            "observed": bool(rewrite_meta.get("observed", False)),
        },
        "answer_generation": {
            "provider": llm_result.observed_provider,
            "model": llm_result.observed_model,
            "observed": bool(llm_result.observed),
            "project": llm_result.project,
            "location": llm_result.location,
            "status": llm_result.status,
            "latency_ms": llm_result.provider_latency_ms,
            "fallback_used": llm_result.fallback_used,
            "primary_error_kind": llm_result.primary_error_kind,
        },
        "guardrails": {
            "provider": "unobserved",
            "model": "unobserved",
            "observed": False,
        },
    }
    latency["provider_usage"] = provider_usage
    if llm_result.observed and llm_result.observed_provider not in ("none", "unobserved"):
        latency["observed_provider"] = llm_result.observed_provider
        latency["observed_model"] = llm_result.observed_model
    elif rewrite_meta.get("observed") and rewrite_meta.get("provider") not in ("none", "unobserved"):
        latency["observed_provider"] = rewrite_meta["provider"]
        latency["observed_model"] = rewrite_meta.get("model", "unobserved")
    else:
        latency["observed_provider"] = "unobserved"
        latency["observed_model"] = "unobserved"
    return llm_result.text, contexts, latency



@logfire.instrument("Rewrite legal search query with metadata")
async def rewrite_query_with_metadata(
    query: str,
    *,
    raise_on_error: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    if len(query.split()) <= 10:
        return query, {
            "provider": "none",
            "model": "none",
            "observed": False,
            "reason": "short_query",
        }
    prompt = (
        "Bạn là chuyên gia pháp luật Việt Nam. Viết lại câu hỏi "
        "sau thành một truy vấn ngắn gọn chứa thuật ngữ pháp lý "
        "chính thống để tìm kiếm văn bản hiệu quả.\n"
        "Câu hỏi: "
        f"{query[:get_settings().QUERY_REWRITE_MAX_CHARACTERS]}\n"
        "Chỉ trả về truy vấn đã viết lại, không giải thích."
    )
    try:
        llm_result = await asyncio.wait_for(
            generate_llm_response_with_metadata(
                prompt,
                max_output_tokens=(
                    get_settings().QUERY_REWRITE_MAX_OUTPUT_TOKENS
                ),
            ),
            timeout=get_settings().QUERY_REWRITE_TIMEOUT_SECONDS,
        )
        rewritten = llm_result.text.strip()
        normalized_rewrite = rewritten.casefold()
        words = re.findall(r"[^\W_]+", rewritten.casefold(), re.UNICODE)
        unique_ratio = len(set(words)) / len(words) if words else 0.0
        if (
            not llm_result.observed
            or len(words) < 2
            or (len(words) >= 6 and unique_ratio < 0.5)
            or len(rewritten) > len(query) * 2
            or "hệ thống chưa thể xử lý" in normalized_rewrite
            or "api keys đang bị giới hạn" in normalized_rewrite
            or "chưa được cấu hình" in normalized_rewrite
        ):
            logfire.warning(
                "Rejected malformed legal query rewrite; use original query."
            )
            if raise_on_error:
                raise QueryRewriteError("malformed rewrite rejected")
            return query, {
                "provider": llm_result.observed_provider if llm_result.observed else "unobserved",
                "model": llm_result.observed_model if llm_result.observed else "unobserved",
                "observed": bool(llm_result.observed),
                "rejected": True,
            }
        return rewritten, {
            "provider": llm_result.observed_provider,
            "model": llm_result.observed_model,
            "observed": bool(llm_result.observed),
        }
    except QueryRewriteError:
        raise
    except Exception as error:
        logfire.warning(
            "Legal query rewrite failed; use original query: {error}",
            error=str(error),
        )
        if raise_on_error:
            raise QueryRewriteError(str(error)) from error
        return query, {
            "provider": "unobserved",
            "model": "unobserved",
            "observed": False,
            "error": str(error)[:100],
        }


@logfire.instrument("Rewrite legal search query")
async def rewrite_query(
    query: str,
    *,
    raise_on_error: bool = False,
) -> str:
    rewritten, _ = await rewrite_query_with_metadata(
        query,
        raise_on_error=raise_on_error,
    )
    return rewritten


@logfire.instrument("Generate grounded legal answer with metadata")
async def generate_response_with_metadata(
    original_query: str,
    rewritten_query: str,
    context: List[str],
) -> LLMGenerationResult:
    if not context:
        return LLMGenerationResult(
            text=NO_EVIDENCE_RESPONSE,
            observed_provider="none",
            observed_model="none",
        )
    context_text = build_bounded_context(
        context,
        max_tokens=get_settings().LLM_CONTEXT_MAX_TOKENS,
    )
    system_prompt = (
        "Bạn là trợ lý thông tin pháp luật Việt Nam. Nguồn dữ liệu "
        "bên thứ ba này không phải cơ sở dữ liệu pháp luật chính thức "
        "và không xác nhận tình trạng hiệu lực của văn bản. Chỉ trả "
        "lời từ bằng chứng được cung cấp; không khẳng định văn bản còn "
        "hiệu lực nếu bằng chứng không nêu rõ. Dẫn số văn bản, Điều, "
        "Khoản và URL khi có. Yêu cầu người dùng kiểm tra lại trên "
        "nguồn chính thức hiện hành hoặc với người có chuyên môn. "
        "Nội dung chỉ nhằm cung cấp thông tin, không phải tư vấn pháp "
        "lý. Nếu bằng chứng không đủ, phải nói không đủ dữ liệu và "
        "không suy đoán."
    )
    user_prompt = (
        f"Tài liệu tham khảo:\n{context_text}\n\n"
        f"Truy vấn tìm kiếm: {rewritten_query}\n"
        f"Câu hỏi người dùng: {original_query}"
    )
    return await generate_llm_response_with_metadata(
        user_prompt,
        system_prompt,
        max_output_tokens=get_settings().LLM_MAX_OUTPUT_TOKENS,
    )


@logfire.instrument("Generate grounded legal answer")
async def generate_response(
    original_query: str,
    rewritten_query: str,
    context: List[str],
) -> str:
    result = await generate_response_with_metadata(
        original_query,
        rewritten_query,
        context,
    )
    return result.text
