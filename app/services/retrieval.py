from __future__ import annotations

import asyncio
import math
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


def _lexical_score(
    query_terms: list[str],
    query_phrase: str,
    chunk: EvidenceChunk,
) -> float:
    normalized_text = " ".join(chunk.text.casefold().split())
    counts = Counter(normalized_terms(chunk.text))
    score = sum(
        1.0 + math.log(counts[term])
        for term in set(query_terms)
        if counts[term] > 0
    )
    if query_phrase and query_phrase in normalized_text:
        score += 8.0
    return score


def select_rerank_candidates(
    query: str,
    chunks: list[EvidenceChunk],
    *,
    limit: int,
    per_document_limit: int,
) -> list[EvidenceChunk]:
    """Prefer lexical evidence, then retain semantic document diversity."""
    if limit <= 0 or per_document_limit <= 0:
        return []

    query_terms = normalized_terms(query)
    query_phrase = " ".join(query.casefold().split())
    scored = [
        (
            _lexical_score(query_terms, query_phrase, chunk),
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

    async def _hybrid_documents(
        self,
        dense_query_text: str,
        sparse_query_text: str | None = None,
    ) -> list[Any]:
        sparse_query_text = sparse_query_text or dense_query_text
        dense_query = await asyncio.to_thread(
            embed_query,
            self._qdrant_inference,
            self._settings,
            dense_query_text,
        )
        sparse_query = self._sparse_encoder.encode_query(sparse_query_text)
        dense_query, sparse_query_payload = scale_hybrid_query(
            dense_query,
            sparse_query,
            alpha=self._settings.PINECONE_HYBRID_ALPHA,
        )
        response = await asyncio.to_thread(
            self._pinecone.query,
            namespace=self._settings.PINECONE_NAMESPACE,
            vector=dense_query,
            sparse_vector=sparse_query_payload,
            top_k=self._settings.RETRIEVAL_DOCUMENT_LIMIT,
            include_metadata=True,
            include_values=False,
        )
        if isinstance(response, dict):
            return list(response.get("matches") or [])
        return list(getattr(response, "matches", []) or [])

    async def _resolve_chunks(
        self,
        hits: list[Any],
        lexical_document_ids: list[int] | None = None,
    ) -> list[EvidenceChunk]:
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
        document_ids = merge_document_ids(
            lexical_document_ids,
            list(payload_by_id),
        )
        if not document_ids:
            return []
        documents = await asyncio.to_thread(
            self._content_store.get_many,
            document_ids,
        )
        chunks: list[EvidenceChunk] = []
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
            chunks.extend(
                chunk_document(
                    document.metadata,
                    document.content,
                    max_tokens=self._settings.QUERY_CHUNK_MAX_TOKENS,
                    overlap_tokens=(
                        self._settings.QUERY_CHUNK_OVERLAP_TOKENS
                    ),
                )
            )
        return chunks

    async def _rerank(
        self,
        query: str,
        chunks: list[EvidenceChunk],
    ) -> tuple[list[EvidenceChunk], RerankOutcome]:
        if not chunks:
            return (
                [],
                RerankOutcome(
                    results=[],
                    provider="none",
                    model="none",
                    latency=0.0,
                ),
            )
        documents = [
            f"[{chunk.citation}]\n{chunk.text}" for chunk in chunks
        ]
        outcome = await self._reranker.rerank(query, documents)
        ranked = [
            (item.score, chunks[item.index])
            for item in outcome.results
            if 0 <= item.index < len(chunks)
        ]
        return (
            select_ranked_evidence(
                ranked,
                max_chunks=self._settings.RERANK_TOP_K,
                max_tokens=self._settings.LLM_CONTEXT_MAX_TOKENS,
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
    ) -> RetrievalOutcome:
        latency = {
            "t_hybrid": 0.0,
            "t_lexical": 0.0,
            "t_resolve_chunk": 0.0,
            "t_candidate": 0.0,
            "t_rerank": 0.0,
        }
        diagnostics: dict[str, Any] = {}
        try:
            async def timed_hybrid() -> tuple[list[Any], float]:
                started = time.perf_counter()
                value = await self._hybrid_documents(query, sparse_query)
                return value, time.perf_counter() - started

            async def timed_lexical() -> tuple[list[int], float]:
                started = time.perf_counter()
                value = await asyncio.to_thread(
                    self._fts_index.search,
                    sparse_query or query,
                    limit=self._settings.LEGAL_FTS_RESULT_LIMIT,
                )
                return value, time.perf_counter() - started

            (hits, hybrid_seconds), (
                lexical_document_ids,
                lexical_seconds,
            ) = await asyncio.gather(timed_hybrid(), timed_lexical())
            latency["t_hybrid"] = round(hybrid_seconds, 6)
            latency["t_lexical"] = round(lexical_seconds, 6)
            diagnostics["top_documents"] = self._hit_diagnostics(hits)
            diagnostics["lexical_document_ids"] = lexical_document_ids

            stage_started = time.perf_counter()
            chunks = await self._resolve_chunks(
                hits,
                lexical_document_ids,
            )
            latency["t_resolve_chunk"] = round(
                time.perf_counter() - stage_started,
                6,
            )
            if not chunks:
                return RetrievalOutcome(
                    evidence=[],
                    latency=latency,
                    status="no_candidate",
                    diagnostics=diagnostics,
                )

            stage_started = time.perf_counter()
            bounded = select_rerank_candidates(
                sparse_query or query,
                chunks,
                limit=self._settings.RERANK_CANDIDATE_LIMIT,
                per_document_limit=(
                    self._settings.RERANK_PER_DOCUMENT_LIMIT
                ),
            )
            latency["t_candidate"] = round(
                time.perf_counter() - stage_started,
                6,
            )
            diagnostics["candidate_citations"] = [
                chunk.citation for chunk in bounded
            ]
            if not bounded:
                return RetrievalOutcome(
                    evidence=[],
                    latency=latency,
                    status="no_candidate",
                    diagnostics=diagnostics,
                )

            stage_started = time.perf_counter()
            try:
                evidence, rerank_outcome = await self._rerank(query, bounded)
            except Exception as error:
                latency["t_rerank"] = round(
                    time.perf_counter() - stage_started,
                    6,
                )
                logfire.error(
                    "Legal reranking failed: {error}",
                    error=str(error),
                )
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
            diagnostics.update(
                {
                    "rerank_provider": rerank_outcome.provider,
                    "rerank_model": rerank_outcome.model,
                    "rerank_fallback_reason": (
                        rerank_outcome.fallback_reason
                    ),
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
