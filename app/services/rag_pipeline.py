from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Dict, List, Tuple

import logfire

from app.config import get_settings
from app.services.direct_llm import generate_llm_response
from app.services.retrieval import RetrievalOutcome, get_legal_retriever


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
    rewrite_mode: str = "on",
    profile: Any = None,
) -> Tuple[str, List[str], Dict[str, Any], RetrievalOutcome]:
    started = time.perf_counter()

    if rewrite_mode == "off":
        rewritten_query = user_query
        rewrite_seconds = 0.0
    else:
        rewrite_started = time.perf_counter()
        rewritten_query = await rewrite_query(user_query)
        rewrite_seconds = time.perf_counter() - rewrite_started

    retrieval_started = time.perf_counter()
    retrieval_kwargs: dict[str, Any] = {"sparse_query": user_query}
    if profile is not None:
        retrieval_kwargs["profile"] = profile
    retrieval_outcome: RetrievalOutcome = (
        await get_legal_retriever().retrieve_detailed(
            rewritten_query,
            **retrieval_kwargs,
        )
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
        return NO_EVIDENCE_RESPONSE, [], latency

    llm_started = time.perf_counter()
    response = await generate_response(
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
    return response, contexts, latency



@logfire.instrument("Rewrite legal search query")
async def rewrite_query(query: str) -> str:
    if len(query.split()) <= 10:
        return query
    prompt = (
        "Bạn là chuyên gia pháp luật Việt Nam. Viết lại câu hỏi "
        "sau thành một truy vấn ngắn gọn chứa thuật ngữ pháp lý "
        "chính thống để tìm kiếm văn bản hiệu quả.\n"
        "Câu hỏi: "
        f"{query[:get_settings().QUERY_REWRITE_MAX_CHARACTERS]}\n"
        "Chỉ trả về truy vấn đã viết lại, không giải thích."
    )
    try:
        rewritten = await asyncio.wait_for(
            generate_llm_response(
                prompt,
                max_output_tokens=(
                    get_settings().QUERY_REWRITE_MAX_OUTPUT_TOKENS
                ),
            ),
            timeout=get_settings().QUERY_REWRITE_TIMEOUT_SECONDS,
        )
        rewritten = rewritten.strip()
        normalized_rewrite = rewritten.casefold()
        words = re.findall(r"[^\W_]+", rewritten.casefold(), re.UNICODE)
        unique_ratio = len(set(words)) / len(words) if words else 0.0
        if (
            len(words) < 2
            or (len(words) >= 6 and unique_ratio < 0.5)
            or len(rewritten) > len(query) * 2
            or "hệ thống chưa thể xử lý" in normalized_rewrite
            or "api keys đang bị giới hạn" in normalized_rewrite
        ):
            logfire.warning(
                "Rejected malformed legal query rewrite; use original query."
            )
            return query
        return rewritten
    except Exception as error:
        logfire.warning(
            "Legal query rewrite failed; use original query: {error}",
            error=str(error),
        )
        return query


@logfire.instrument("Generate grounded legal answer")
async def generate_response(
    original_query: str,
    rewritten_query: str,
    context: List[str],
) -> str:
    if not context:
        return NO_EVIDENCE_RESPONSE
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
    return await generate_llm_response(
        user_prompt,
        system_prompt,
        max_output_tokens=get_settings().LLM_MAX_OUTPUT_TOKENS,
    )
