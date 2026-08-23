from __future__ import annotations

import asyncio
import hashlib
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
    select_ranked_evidence,
)
from app.services.clients import get_remote_reranker
from app.evaluation.schemas import RetrievalStageTrace, StageCandidate



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


def _evidence_identity(item: Any) -> tuple[Any, ...]:
    article = " ".join((item.article or "").casefold().split())
    clause = " ".join((item.clause or "").casefold().split())
    if clause.isdigit():
        clause = str(int(clause))
    normalized_text = " ".join((item.text or "").casefold().split())
    if normalized_text:
        content_identity = hashlib.sha256(
            normalized_text.encode("utf-8")
        ).hexdigest()
        return (
            item.document_id,
            "exact_chunk",
            article,
            clause,
            content_identity,
        )
    citation = " ".join((item.citation or "").casefold().split())
    if citation:
        return (item.document_id, "citation", citation)
    return (item.document_id, "empty")


def _interleave_evidence(
    structural: list[Any],
    full_corpus: list[Any],
    *,
    limit: int,
    max_tokens: int,
    per_document_limit: int,
) -> list[Any]:
    merged: list[Any] = []
    seen: set[tuple[Any, ...]] = set()
    tokens_used = 0
    per_document: dict[int, int] = {}
    for index in range(max(len(structural), len(full_corpus))):
        for lane in (structural, full_corpus):
            if index >= len(lane):
                continue
            item = lane[index]
            identity = _evidence_identity(item)
            if identity in seen:
                continue
            document_count = per_document.get(item.document_id, 0)
            if document_count >= per_document_limit:
                continue
            item_tokens = max(1, int(item.token_count))
            if tokens_used + item_tokens > max_tokens:
                continue
            seen.add(identity)
            merged.append(item)
            tokens_used += item_tokens
            per_document[item.document_id] = document_count + 1
            if len(merged) >= limit:
                return merged
    return merged


def _merged_stage_trace(
    structural: RetrievalOutcome,
    legacy: RetrievalOutcome,
    evidence: list[Any],
) -> RetrievalStageTrace | None:
    traces = [
        outcome.diagnostics.get("stage_trace")
        for outcome in (structural, legacy)
    ]
    traces = [trace for trace in traces if isinstance(trace, RetrievalStageTrace)]
    if not traces:
        return None
    merged: dict[str, list[StageCandidate]] = {
        field: [] for field in RetrievalStageTrace.model_fields
    }
    for trace in traces:
        for field in merged:
            merged[field].extend(getattr(trace, field))
    merged["final_evidence_chunks"] = [
        StageCandidate(
            document_id=item.document_id,
            document_number=item.document_number,
            title=item.title,
            source_url=item.source_url,
            citation=item.citation,
            article=item.article,
            clause=item.clause,
            text=item.text,
            source="parallel_final",
        )
        for item in evidence
    ]
    return RetrievalStageTrace(**merged)


async def _parallel_retrieval_outcome(
    structural: RetrievalOutcome,
    legacy: RetrievalOutcome,
    *,
    query: str,
) -> RetrievalOutcome:
    configured_limit = max(
        1,
        int(getattr(get_settings(), "FINAL_EVIDENCE_LIMIT", 3)),
    )
    max_tokens = max(
        1,
        int(getattr(get_settings(), "LLM_CONTEXT_MAX_TOKENS", 720)),
    )
    per_document_limit = max(
        1,
        int(getattr(get_settings(), "LLM_CONTEXT_PER_DOCUMENT_LIMIT", 2)),
    )
    pool_size = len(structural.evidence) + len(legacy.evidence)
    pool_tokens = sum(
        max(1, int(item.token_count))
        for item in (*structural.evidence, *legacy.evidence)
    )
    candidate_pool = _interleave_evidence(
        structural.evidence,
        legacy.evidence,
        limit=max(1, pool_size),
        max_tokens=max(1, pool_tokens),
        per_document_limit=max(1, pool_size),
    )
    fallback_evidence = _interleave_evidence(
        structural.evidence,
        legacy.evidence,
        limit=configured_limit,
        max_tokens=max_tokens,
        per_document_limit=per_document_limit,
    )
    evidence = fallback_evidence
    final_reranker = None
    final_reranker_error = None
    final_reranker_latency = 0.0
    final_rerank_enabled = bool(
        getattr(get_settings(), "CROSS_LANE_FINAL_RERANK_ENABLED", False)
    )
    if final_rerank_enabled and structural.evidence and legacy.evidence:
        if len(candidate_pool) > 1:
            try:
                final_reranker = await get_remote_reranker().rerank(
                    query,
                    [item.formatted_context() for item in candidate_pool],
                    mode="pinecone-only",
                    rerank_return_limit=len(candidate_pool),
                )
                final_reranker_latency = final_reranker.latency
                ranked = [
                    (result.score, candidate_pool[result.index])
                    for result in final_reranker.results
                    if 0 <= result.index < len(candidate_pool)
                ]
                evidence = select_ranked_evidence(
                    ranked,
                    max_chunks=configured_limit,
                    max_tokens=max_tokens,
                    per_document_limit=per_document_limit,
                    min_score=float(
                        getattr(get_settings(), "RERANK_MIN_SCORE", 0.05)
                    ),
                )
            except Exception as error:
                final_reranker_error = {
                    "category": type(error).__name__,
                    "provider": "pinecone",
                }
    technical_statuses = {
        "retrieval_error",
        "reranker_error",
        "partial_retrieval_error",
    }
    failed_lanes = [
        name
        for name, outcome in (
            ("structural", structural),
            ("full_corpus", legacy),
        )
        if outcome.status in technical_statuses
    ]
    if final_reranker_error is not None:
        failed_lanes.append("final_reranker")
    if final_reranker is not None and not evidence:
        status = "no_candidate"
    elif evidence and failed_lanes:
        status = "partial_retrieval_error"
    elif evidence:
        status = "ok"
    elif "reranker_error" in {structural.status, legacy.status}:
        status = "reranker_error"
    elif failed_lanes:
        status = "retrieval_error"
    else:
        status = "ok"

    diagnostics = dict(legacy.diagnostics)
    combined_stage_trace = _merged_stage_trace(structural, legacy, evidence)
    diagnostics.update(
        {
            "retrieval_backend": "parallel_structural_full_corpus_v1",
            "fusion_policy": (
                "canonical_dedupe_pinecone_final_rerank_v1"
                if final_reranker is not None
                else "canonical_dedupe_rank_interleave_fallback_v1"
            ),
            "structural_status": structural.status,
            "full_corpus_status": legacy.status,
            "failed_lanes": failed_lanes,
            "structural_diagnostics": structural.diagnostics,
            "full_corpus_diagnostics": legacy.diagnostics,
            "final_reranker_provider": (
                final_reranker.provider if final_reranker else "none"
            ),
            "final_reranker_model": (
                final_reranker.model if final_reranker else "none"
            ),
            "final_reranker_error": final_reranker_error,
            "final_reranker_enabled": final_rerank_enabled,
            "pre_final_candidate_count": len(candidate_pool),
            "post_final_candidate_count": len(evidence),
            "no_candidate_reason": (
                "no_candidate_after_final_rerank"
                if final_reranker is not None and not evidence
                else None
            ),
        }
    )
    if combined_stage_trace is not None:
        diagnostics["stage_trace"] = combined_stage_trace
    errors = [value for value in (structural.error, legacy.error) if value]
    if final_reranker_error is not None:
        errors.append("Final cross-lane reranking failed.")
    return RetrievalOutcome(
        evidence=evidence,
        latency={
            **structural.latency,
            **legacy.latency,
            "t_final_cross_lane_rerank": final_reranker_latency,
        },
        status=status,
        diagnostics=diagnostics,
        error="; ".join(errors) or None,
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
    async def run_structural() -> RetrievalOutcome:
        try:
            return _structural_retrieval_outcome(
                await get_structural_legal_retriever().retrieve(
                    rewritten_query,
                    sparse_query=user_query,
                )
            )
        except Exception as error:
            return RetrievalOutcome(
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

    async def run_legacy() -> RetrievalOutcome:
        try:
            return await _legacy_retrieval_outcome(
                rewritten_query,
                user_query,
                profile,
            )
        except Exception as error:
            return RetrievalOutcome(
                evidence=[],
                latency={},
                status="retrieval_error",
                diagnostics={
                    "retrieval_backend": "pinecone_v1",
                    "full_corpus_technical_error": {
                        "category": type(error).__name__,
                    },
                },
                error="Full-corpus retrieval initialization failed.",
            )

    structural, legacy = await asyncio.gather(run_structural(), run_legacy())
    return await _parallel_retrieval_outcome(
        structural,
        legacy,
        query=rewritten_query,
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
    *,
    thinking_level: Any = "MINIMAL",
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
        thinking_level=thinking_level,
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
