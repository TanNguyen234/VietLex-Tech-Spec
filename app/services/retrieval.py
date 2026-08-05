from __future__ import annotations

import asyncio
import math
import random
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import logfire

from app.config import Settings, get_settings
from app.ingestion.content_store import ContentStore
from app.ingestion.legal_fts import LegalFtsIndex
from app.ingestion.legal_text import EvidenceChunk, chunk_document
from app.ingestion.pinecone_store import (
    FastSparseEncoder,
    scale_hybrid_query,
)
from app.ingestion.qdrant_inference import embed_query
from app.ingestion.sparse_encoder import (
    normalized_terms,
)
from app.services.clients import (
    get_pinecone_index,
    get_qdrant_inference_client,
    get_remote_reranker,
)
from app.services.remote_reranker import RerankOutcome


@dataclass(frozen=True)
class RetrievalOutcome:
    evidence: list[EvidenceChunk]
    latency: dict[str, float]
    status: str = "ok"
    diagnostics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class HybridRetrievalError(RuntimeError):
    def __init__(
        self,
        *,
        stage: str,
        attempts: int,
        latency: float,
        cause: Exception,
    ) -> None:
        self.stage = stage
        self.attempts = attempts
        self.latency = latency
        self.cause_type = type(cause).__name__
        self.cause_message = str(cause)[:300]
        super().__init__(f"{stage} failed after {attempts} attempt(s): {cause}")

    def diagnostics(self) -> dict[str, Any]:
        return {
            "hybrid_error_stage": self.stage,
            "hybrid_error_attempts": self.attempts,
            "hybrid_error_latency": round(self.latency, 6),
            "hybrid_error_type": self.cause_type,
            "hybrid_error_message": self.cause_message,
        }


def _is_transient_hybrid_error(error: Exception) -> bool:
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return True
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        status_code = getattr(
            getattr(error, "response", None),
            "status_code",
            None,
        )
    return status_code in {408, 429, 500, 502, 503, 504} or (
        type(error).__name__
        in {
            "ConnectError",
            "ConnectTimeout",
            "ReadTimeout",
            "ServiceException",
            "TimeoutException",
        }
    )


def merge_document_ids(
    lexical_ids: list[int],
    pinecone_ids: list[int],
) -> list[int]:
    merged: list[int] = []
    seen: set[int] = set()
    for document_id in (*lexical_ids, *pinecone_ids):
        if document_id not in seen:
            merged.append(document_id)
            seen.add(document_id)
    return merged


def balanced_document_ids(
    lexical_ids: list[int],
    semantic_ids: list[int],
    *,
    limit: int,
) -> list[int]:
    if limit <= 0:
        return []
    selected: list[int] = []
    seen: set[int] = set()
    maximum = max(len(lexical_ids), len(semantic_ids))
    for index in range(maximum):
        for source in (lexical_ids, semantic_ids):
            if index >= len(source):
                continue
            document_id = source[index]
            if document_id in seen:
                continue
            selected.append(document_id)
            seen.add(document_id)
            if len(selected) >= limit:
                return selected
    return selected


def lexical_prefilter(
    query: str,
    chunks: list[EvidenceChunk],
    *,
    limit: int,
) -> list[EvidenceChunk]:
    query_terms = normalized_terms(query)
    query_phrase = " ".join(query.casefold().split())

    def score(chunk: EvidenceChunk) -> tuple[float, int, str]:
        normalized_text = " ".join(
            chunk.text.casefold().split()
        )
        counts = Counter(normalized_terms(chunk.text))
        lexical_score = sum(
            1.0 + math.log(counts[term])
            for term in set(query_terms)
            if counts[term] > 0
        )
        if query_phrase and query_phrase in normalized_text:
            lexical_score += 8.0
        return (
            lexical_score,
            -chunk.document_id,
            chunk.citation,
        )

    return sorted(
        chunks,
        key=score,
        reverse=True,
    )[: max(0, limit)]


INTENT_PATTERNS = {
    "definition": ({"định nghĩa", "là gì", "hiểu như thế nào", "khái niệm"}, {"là", "được hiểu là", "gồm", "nghĩa là"}),
    "penalty": ({"xử phạt", "phạt tiền", "tội", "mức phạt", "phạt bao nhiêu", "bồi thường"}, {"phạt", "tội", "tước", "phạt tiền", "bồi thường", "bị phạt"}),
    "deadline": ({"thời hạn", "thời hiệu", "bao lâu", "ngày", "tháng", "khi nào"}, {"thời hạn", "ngày", "tháng", "năm", "thời hiệu", "thời gian"}),
    "authority": ({"cơ quan", "thẩm quyền", "ai có quyền", "bộ", "ủy ban", "đơn vị"}, {"thẩm quyền", "cơ quan", "bộ", "ủy ban", "thủ tướng", "chủ tịch"}),
    "responsibility": ({"trách nhiệm", "nghĩa vụ", "bắt buộc", "phải"}, {"trách nhiệm", "nghĩa vụ", "bắt buộc", "phải", "có nghĩa vụ"}),
    "condition": ({"điều kiện", "đối tượng", "được phép", "tiêu chuẩn", "quy chuẩn"}, {"điều kiện", "đối tượng", "tiêu chuẩn", "quy chuẩn", "yêu cầu"}),
    "exception": ({"trừ trường hợp", "ngoại lệ", "không áp dụng", "loại trừ"}, {"trừ", "ngoại lệ", "không áp dụng", "loại trừ"}),
}


from app.evaluation.schemas import StageCandidate


def _hit_to_stage_candidate(hit: Any, source: str) -> StageCandidate:
    if isinstance(hit, dict):
        payload = hit.get("metadata") or {}
        score = hit.get("score")
    else:
        payload = getattr(hit, "metadata", None) or {}
        score = getattr(hit, "score", None)
    return StageCandidate(
        document_id=payload.get("document_id"),
        document_number=payload.get("document_number"),
        title=payload.get("title"),
        source_url=payload.get("source_url"),
        citation=payload.get("citation"),
        article=payload.get("article"),
        clause=payload.get("clause"),
        score=float(score) if score is not None else None,
        source=source,
    )


def _chunk_to_stage_candidate(chunk: EvidenceChunk, source: str, score: float | None = None) -> StageCandidate:
    return StageCandidate(
        document_id=chunk.document_id,
        document_number=chunk.document_number,
        title=chunk.title,
        source_url=chunk.source_url,
        citation=chunk.citation,
        article=chunk.article,
        clause=chunk.clause,
        text=chunk.text,
        score=score,
        source=source,
    )


def _lexical_score(
    query_terms: list[str],
    query_phrase: str,
    chunk: EvidenceChunk,
    *,
    intent_scoring_enabled: bool = True,
) -> float:
    normalized_text = " ".join(chunk.text.casefold().split())
    query_lower = query_phrase.casefold()
    score = 0.0
    for term in set(query_terms):
        phrase = term.replace("_", " ").casefold()
        count = normalized_text.count(phrase)
        if count:
            score += 1.0 + math.log(count)
    if query_phrase and query_phrase in normalized_text:
        score += 8.0

    # Legal intent boost (definition, penalty, deadline, authority, responsibility, condition, exception)
    if intent_scoring_enabled:
        for intent, (query_kw, chunk_kw) in INTENT_PATTERNS.items():
            if any(qkw in query_lower for qkw in query_kw):
                if any(ckw in normalized_text for ckw in chunk_kw):
                    score += 4.0

    return score



def select_rerank_candidates(
    query: str,
    chunks: list[EvidenceChunk],
    *,
    limit: int,
    per_document_limit: int,
    intent_scoring_enabled: bool = True,
) -> list[EvidenceChunk]:
    """Prefer lexical evidence, then retain semantic document diversity."""
    if limit <= 0 or per_document_limit <= 0:
        return []

    query_terms = normalized_terms(query)
    query_phrase = " ".join(query.casefold().split())
    scored = [
        (
            _lexical_score(
                query_terms,
                query_phrase,
                chunk,
                intent_scoring_enabled=intent_scoring_enabled,
            ),
            position,
            chunk,
        )
        for position, chunk in enumerate(chunks)
    ]
    selected: list[EvidenceChunk] = []
    selected_ids: set[int] = set()
    document_counts: Counter[int] = Counter()

    def add(chunk: EvidenceChunk) -> bool:
        identity = id(chunk)
        if identity in selected_ids:
            return False
        if document_counts[chunk.document_id] >= per_document_limit:
            return False
        selected.append(chunk)
        selected_ids.add(identity)
        document_counts[chunk.document_id] += 1
        return True

    for score, _, chunk in sorted(
        scored,
        key=lambda item: (-item[0], item[1]),
    ):
        if score <= 0 or len(selected) >= limit:
            break
        add(chunk)

    # Give each not-yet-represented Pinecone hit one semantic fallback.
    represented = set(document_counts)
    for _, _, chunk in scored:
        if len(selected) >= limit:
            break
        if chunk.document_id in represented:
            continue
        if add(chunk):
            represented.add(chunk.document_id)

    # Fill any remaining capacity in Pinecone/chunk source order.
    for _, _, chunk in scored:
        if len(selected) >= limit:
            break
        add(chunk)
    return selected


def select_ranked_evidence(
    ranked: list[tuple[float, EvidenceChunk]],
    *,
    max_chunks: int,
    max_tokens: int,
    per_document_limit: int,
    min_score: float,
) -> list[EvidenceChunk]:
    """Apply provider-score, diversity, and global context limits."""
    selected: list[EvidenceChunk] = []
    document_counts: Counter[int] = Counter()
    token_count = 0
    for score, chunk in sorted(ranked, key=lambda item: item[0], reverse=True):
        if len(selected) >= max_chunks:
            break
        if not math.isfinite(score) or score < min_score:
            continue
        if document_counts[chunk.document_id] >= per_document_limit:
            continue
        if token_count + chunk.token_count > max_tokens:
            continue
        selected.append(chunk)
        document_counts[chunk.document_id] += 1
        token_count += chunk.token_count
    return selected


class LegalRetriever:
    def __init__(
        self,
        *,
        settings: Settings,
        pinecone: Any,
        qdrant_inference: Any,
        reranker: Any,
        fts_index: Any,
        content_store: Any,
    ) -> None:
        self._settings = settings
        self._pinecone = pinecone
        self._qdrant_inference = qdrant_inference
        self._reranker = reranker
        self._fts_index = fts_index
        self._content_store = content_store
        report = content_store.build_report()
        self._sparse_encoder = FastSparseEncoder(
            average_document_length=report.average_sparse_document_length,
            max_nonzero_terms=settings.PINECONE_SPARSE_MAX_NONZERO,
        )

    async def _run_remote_stage(
        self,
        *,
        stage: str,
        operation: Any,
        timeout: float,
        attempts: int,
    ) -> tuple[Any, int, float]:
        started = time.perf_counter()
        attempts = max(1, attempts)
        for attempt in range(1, attempts + 1):
            try:
                value = await asyncio.wait_for(
                    asyncio.to_thread(operation),
                    timeout=max(0.1, timeout),
                )
                return value, attempt, time.perf_counter() - started
            except Exception as error:
                if (
                    not _is_transient_hybrid_error(error)
                    or attempt == attempts
                ):
                    raise HybridRetrievalError(
                        stage=stage,
                        attempts=attempt,
                        latency=time.perf_counter() - started,
                        cause=error,
                    ) from error
                delay = min(
                    self._settings.HYBRID_RETRY_MAX_SECONDS,
                    self._settings.HYBRID_RETRY_BASE_SECONDS
                    * (2 ** (attempt - 1)),
                )
                if delay > 0:
                    await asyncio.sleep(
                        delay * (0.8 + random.random() * 0.4)
                    )
        raise RuntimeError("Hybrid retry loop ended unexpectedly.")

    async def _hybrid_documents(
        self,
        dense_query_text: str,
        sparse_query_text: str | None = None,
        diagnostics: dict[str, Any] | None = None,
        *,
        retrieval_document_limit: int | None = None,
    ) -> list[Any]:
        diagnostics = diagnostics if diagnostics is not None else {}
        top_k = (
            retrieval_document_limit
            if retrieval_document_limit is not None
            else self._settings.RETRIEVAL_DOCUMENT_LIMIT
        )
        diagnostics["requested_top_k"] = top_k
        diagnostics["effective_top_k"] = top_k
        sparse_query_text = sparse_query_text or dense_query_text
        dense_query, embedding_attempts, embedding_latency = (
            await self._run_remote_stage(
                stage="qdrant_embedding",
                operation=lambda: embed_query(
                    self._qdrant_inference,
                    self._settings,
                    dense_query_text,
                ),
                timeout=self._settings.HYBRID_EMBEDDING_TIMEOUT_SECONDS,
                attempts=1,
            )
        )
        diagnostics["hybrid_embedding_attempts"] = embedding_attempts
        diagnostics["hybrid_embedding_latency"] = round(
            embedding_latency, 6
        )
        sparse_query = self._sparse_encoder.encode_query(sparse_query_text)
        dense_query, sparse_query_payload = scale_hybrid_query(
            dense_query,
            sparse_query,
            alpha=self._settings.PINECONE_HYBRID_ALPHA,
        )
        response, query_attempts, query_latency = await self._run_remote_stage(
            stage="pinecone_query",
            operation=lambda: self._pinecone.query(
                namespace=self._settings.PINECONE_NAMESPACE,
                vector=dense_query,
                sparse_vector=sparse_query_payload,
                top_k=top_k,
                include_metadata=True,
                include_values=False,
            ),
            timeout=self._settings.HYBRID_QUERY_TIMEOUT_SECONDS,
            attempts=self._settings.HYBRID_MAX_RETRIES,
        )
        diagnostics["hybrid_query_attempts"] = query_attempts
        diagnostics["hybrid_query_latency"] = round(query_latency, 6)
        if isinstance(response, dict):
            return list(response.get("matches") or [])
        return list(getattr(response, "matches", []) or [])

    async def _resolve_chunks(
        self,
        hits: list[Any],
        lexical_document_ids: list[int] | None = None,
        query_text: str = "",
        *,
        resolved_doc_limit: int | None = None,
        local_chunks_limit: int | None = None,
        intent_scoring_enabled: bool = True,
    ) -> tuple[list[EvidenceChunk], list[EvidenceChunk], list[int]]:
        doc_limit = resolved_doc_limit if resolved_doc_limit is not None else self._settings.RERANK_CANDIDATE_LIMIT
        chunk_limit = local_chunks_limit if local_chunks_limit is not None else self._settings.RERANK_PER_DOCUMENT_LIMIT
        lexical_document_ids = lexical_document_ids or []
        lexical_set = set(lexical_document_ids)
        payload_by_id: dict[int, dict[str, Any]] = {}
        for hit in hits:
            if isinstance(hit, dict):
                payload = dict(hit.get("metadata") or {})
            else:
                payload = dict(getattr(hit, "metadata", None) or {})
            if (
                payload.get("dataset_revision")
                != self._settings.DATASET_REVISION
            ):
                continue
            try:
                document_id = int(payload["document_id"])
                content_store_key = int(payload["content_store_key"])
            except (KeyError, TypeError, ValueError):
                continue
            if document_id != content_store_key:
                continue
            payload_by_id.setdefault(document_id, payload)
        document_ids = balanced_document_ids(
            lexical_document_ids,
            list(payload_by_id),
            limit=doc_limit,
        )
        if not document_ids:
            return [], [], []
        documents = await asyncio.to_thread(
            self._content_store.get_many,
            document_ids,
        )
        all_structural_chunks: list[EvidenceChunk] = []
        locally_selected_chunks: list[EvidenceChunk] = []
        query_terms = normalized_terms(query_text)
        query_phrase = " ".join(query_text.casefold().split())
        for document_id in document_ids:
            document = documents.get(document_id)
            if document is None:
                continue
            if document_id not in lexical_set:
                payload = payload_by_id[document_id]
                if (
                    payload.get("content_sha256")
                    != document.content_sha256
                ):
                    continue
            document_chunks = chunk_document(
                document.metadata,
                document.content,
                max_tokens=self._settings.QUERY_CHUNK_MAX_TOKENS,
                overlap_tokens=(
                    self._settings.QUERY_CHUNK_OVERLAP_TOKENS
                ),
            )
            all_structural_chunks.extend(document_chunks)
            ranked_chunks = sorted(
                enumerate(document_chunks),
                key=lambda item: (
                    -_lexical_score(
                        query_terms,
                        query_phrase,
                        item[1],
                        intent_scoring_enabled=intent_scoring_enabled,
                    ),
                    item[0],
                ),
            )
            locally_selected_chunks.extend(
                chunk
                for _, chunk in ranked_chunks[:chunk_limit]
            )
        return all_structural_chunks, locally_selected_chunks, document_ids

    async def _rerank(
        self,
        query: str,
        chunks: list[EvidenceChunk],
        *,
        mode: str = "current",
        final_evidence_limit: int = 3,
        final_context_token_limit: int = 720,
        rerank_return_limit: int | None = None,
    ) -> tuple[list[EvidenceChunk], RerankOutcome]:
        documents = [chunk.formatted_context() for chunk in chunks]
        outcome = await self._reranker.rerank(query, documents, mode=mode, rerank_return_limit=rerank_return_limit)
        ranked = [
            (item.score, chunks[item.index])
            for item in outcome.results
            if 0 <= item.index < len(chunks)
        ]
        return (
            select_ranked_evidence(
                ranked,
                max_chunks=final_evidence_limit,
                max_tokens=final_context_token_limit,
                per_document_limit=(
                    self._settings.LLM_CONTEXT_PER_DOCUMENT_LIMIT
                ),
                min_score=self._settings.RERANK_MIN_SCORE,
            ),
            outcome,
        )

    @staticmethod
    def _hit_diagnostics(hits: list[Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for hit in hits:
            if isinstance(hit, dict):
                payload = hit.get("metadata") or {}
                score = hit.get("score")
            else:
                payload = getattr(hit, "metadata", None) or {}
                score = getattr(hit, "score", None)
            result.append(
                {
                    "document_id": payload.get("document_id"),
                    "score": score,
                }
            )
        return result

    @logfire.instrument("Retrieve grounded legal evidence")
    async def retrieve_detailed(
        self,
        query: str,
        sparse_query: str | None = None,
        *,
        profile: Any = None,
    ) -> RetrievalOutcome:
        from app.evaluation.schemas import RetrievalStageTrace
        
        # Extract profile limits or fall back to settings defaults
        retrieval_doc_limit = getattr(profile, "retrieval_document_limit", getattr(self._settings, "RETRIEVAL_DOCUMENT_LIMIT", 24))
        resolved_doc_limit = getattr(profile, "resolved_document_limit", getattr(self._settings, "RESOLVED_DOCUMENT_LIMIT", 16))
        local_chunks_limit = getattr(profile, "local_chunks_per_document", getattr(self._settings, "LOCAL_CHUNKS_PER_DOCUMENT", 4))
        rerank_input_limit = getattr(profile, "rerank_input_limit", getattr(self._settings, "RERANK_INPUT_LIMIT", 24))
        final_evidence_limit = getattr(profile, "final_evidence_limit", getattr(self._settings, "FINAL_EVIDENCE_LIMIT", 3))
        final_context_token_limit = getattr(profile, "final_context_token_limit", getattr(self._settings, "LLM_CONTEXT_MAX_TOKENS", 720))
        rerank_return_limit = getattr(profile, "rerank_return_limit", None)
        intent_scoring_enabled = getattr(profile, "intent_scoring_enabled", getattr(self._settings, "INTENT_SCORING_ENABLED", True))
        reranker_mode = getattr(profile, "reranker_mode", "current")

        latency = {
            "t_hybrid": 0.0,
            "t_lexical": 0.0,
            "t_resolve_chunk": 0.0,
            "t_candidate": 0.0,
            "t_rerank": 0.0,
        }
        diagnostics: dict[str, Any] = {}
        stage_trace = RetrievalStageTrace()

        try:
            async def timed_hybrid() -> tuple[
                list[Any], float, dict[str, Any], HybridRetrievalError | None
            ]:
                started = time.perf_counter()
                details: dict[str, Any] = {}
                try:
                    value = await self._hybrid_documents(
                        query,
                        sparse_query,
                        details,
                        retrieval_document_limit=retrieval_doc_limit,
                    )
                    return (
                        value,
                        time.perf_counter() - started,
                        details,
                        None,
                    )
                except HybridRetrievalError as error:
                    details.update(error.diagnostics())
                    return (
                        [],
                        time.perf_counter() - started,
                        details,
                        error,
                    )

            async def timed_lexical() -> tuple[
                list[int], float, str | None
            ]:
                started = time.perf_counter()
                try:
                    value = await asyncio.to_thread(
                        self._fts_index.search,
                        sparse_query or query,
                        limit=self._settings.LEGAL_FTS_RESULT_LIMIT,
                    )
                    return value, time.perf_counter() - started, None
                except Exception as error:
                    logfire.warning(
                        "Optional legal FTS search failed: {error}",
                        error=str(error),
                    )
                    return [], time.perf_counter() - started, str(error)

            (hits, hybrid_seconds, hybrid_details, hybrid_error), (
                lexical_document_ids,
                lexical_seconds,
                lexical_error,
            ) = await asyncio.gather(timed_hybrid(), timed_lexical())
            latency["t_hybrid"] = round(hybrid_seconds, 6)
            latency["t_lexical"] = round(lexical_seconds, 6)
            diagnostics.update(hybrid_details)
            diagnostics["top_documents"] = self._hit_diagnostics(hits)
            diagnostics["lexical_document_ids"] = lexical_document_ids

            stage_trace.pinecone_hits = [_hit_to_stage_candidate(h, "pinecone") for h in hits]
            stage_trace.fts_hits = [
                _hit_to_stage_candidate({"metadata": {"document_id": doc_id}}, "fts")
                for doc_id in lexical_document_ids
            ]

            merged_ids = merge_document_ids(lexical_document_ids, [h.get("metadata", {}).get("document_id") if isinstance(h, dict) else getattr(getattr(h, "metadata", None), "document_id", None) for h in hits if h])
            stage_trace.merged_document_candidates = [
                _hit_to_stage_candidate({"metadata": {"document_id": doc_id}}, "merged")
                for doc_id in merged_ids if doc_id is not None
            ]

            if lexical_error:
                diagnostics["lexical_error"] = lexical_error
            if hybrid_error is not None:
                if not lexical_document_ids:
                    raise hybrid_error
                diagnostics["retrieval_mode"] = "lexical_fallback"
            elif lexical_document_ids:
                diagnostics["retrieval_mode"] = "hybrid_lexical"
            else:
                diagnostics["retrieval_mode"] = "hybrid_only"

            stage_started = time.perf_counter()
            structural_chunks, local_chunks, resolved_ids = await self._resolve_chunks(
                hits,
                lexical_document_ids,
                sparse_query or query,
                resolved_doc_limit=resolved_doc_limit,
                local_chunks_limit=local_chunks_limit,
                intent_scoring_enabled=intent_scoring_enabled,
            )
            latency["t_resolve_chunk"] = round(
                time.perf_counter() - stage_started,
                6,
            )

            stage_trace.resolved_document_candidates = [
                _hit_to_stage_candidate({"metadata": {"document_id": doc_id}}, "resolved")
                for doc_id in resolved_ids
            ]
            stage_trace.structural_chunks_generated = [
                _chunk_to_stage_candidate(c, "structural") for c in structural_chunks
            ]
            stage_trace.locally_selected_chunks = [
                _chunk_to_stage_candidate(c, "local") for c in local_chunks
            ]

            if not local_chunks:
                diagnostics["stage_trace"] = stage_trace
                return RetrievalOutcome(
                    evidence=[],
                    latency=latency,
                    status="no_candidate",
                    diagnostics=diagnostics,
                )

            stage_started = time.perf_counter()
            bounded = select_rerank_candidates(
                sparse_query or query,
                local_chunks,
                limit=rerank_input_limit,
                per_document_limit=local_chunks_limit,
                intent_scoring_enabled=intent_scoring_enabled,
            )
            latency["t_candidate"] = round(
                time.perf_counter() - stage_started,
                6,
            )
            stage_trace.reranker_input_chunks = [
                _chunk_to_stage_candidate(c, "reranker") for c in bounded
            ]
            diagnostics["candidate_citations"] = [
                chunk.citation for chunk in bounded
            ]
            if not bounded:
                diagnostics["stage_trace"] = stage_trace
                return RetrievalOutcome(
                    evidence=[],
                    latency=latency,
                    status="no_candidate",
                    diagnostics=diagnostics,
                )

            stage_started = time.perf_counter()
            try:
                evidence, rerank_outcome = await self._rerank(
                    query,
                    bounded,
                    mode=reranker_mode,
                    final_evidence_limit=final_evidence_limit,
                    final_context_token_limit=final_context_token_limit,
                    rerank_return_limit=rerank_return_limit,
                )
            except Exception as error:
                latency["t_rerank"] = round(
                    time.perf_counter() - stage_started,
                    6,
                )
                logfire.error(
                    "Legal reranking failed: {error}",
                    error=str(error),
                )
                diagnostics["stage_trace"] = stage_trace
                return RetrievalOutcome(
                    evidence=[],
                    latency=latency,
                    status="reranker_error",
                    diagnostics=diagnostics,
                    error=str(error),
                )
            latency["t_rerank"] = round(
                time.perf_counter() - stage_started,
                6,
            )

            stage_trace.reranker_output_chunks = [
                _chunk_to_stage_candidate(bounded[item.index], "reranker_output", score=item.score)
                for item in rerank_outcome.results
                if 0 <= item.index < len(bounded)
            ]
            stage_trace.final_evidence_chunks = [
                _chunk_to_stage_candidate(c, "final") for c in evidence
            ]
            diagnostics["stage_trace"] = stage_trace

            diagnostics.update(
                {
                    "rerank_requested_return_limit": rerank_return_limit if rerank_return_limit is not None else getattr(self._settings, "RERANK_RETURN_LIMIT", 12),
                    "rerank_provider": rerank_outcome.provider,
                    "rerank_model": rerank_outcome.model,
                    "rerank_fallback_reason": (
                        rerank_outcome.fallback_reason
                    ),
                    "rerank_attempts": rerank_outcome.attempts,
                    "rerank_input_count": rerank_outcome.input_count,
                    "rerank_output_count": rerank_outcome.output_count,
                    "reranked": [
                        {
                            "citation": bounded[item.index].citation,
                            "score": item.score,
                        }
                        for item in rerank_outcome.results
                        if 0 <= item.index < len(bounded)
                    ],
                }
            )
            return RetrievalOutcome(
                evidence=evidence,
                latency=latency,
                status="ok" if evidence else "no_candidate",
                diagnostics=diagnostics,
            )
        except Exception as error:
            logfire.error(
                "Legal retrieval failed closed: {error}",
                error=str(error),
            )
            diagnostics["stage_trace"] = stage_trace
            return RetrievalOutcome(
                evidence=[],
                latency=latency,
                status="retrieval_error",
                diagnostics=diagnostics,
                error=str(error),
            )

    async def retrieve(
        self,
        query: str,
        sparse_query: str | None = None,
    ) -> list[EvidenceChunk]:
        outcome = await self.retrieve_detailed(query, sparse_query)
        return outcome.evidence


_retriever: LegalRetriever | None = None


def get_legal_retriever() -> LegalRetriever:
    global _retriever
    if _retriever is None:
        settings = get_settings()
        content_store = ContentStore(
            settings.CONTENT_STORE_PATH
        )
        fts_index = LegalFtsIndex(
            store=content_store,
            path=settings.LEGAL_FTS_PATH,
            dataset_revision=settings.DATASET_REVISION,
        )
        _retriever = LegalRetriever(
            settings=settings,
            pinecone=get_pinecone_index(),
            qdrant_inference=get_qdrant_inference_client(),
            reranker=get_remote_reranker(),
            fts_index=fts_index,
            content_store=content_store,
        )
    return _retriever


def reset_retriever() -> None:
    global _retriever
    _retriever = None
