"""Opt-in retrieval over the isolated Pinecone structural namespace."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Literal

from app.config import Settings
from app.ingestion.legal_fts import extract_legal_references
from app.ingestion.structural_pinecone import PineconeStructuralContract
from app.services.remote_reranker import is_transient_provider_error
from app.services.structural_retrieval import (
    StructuralRetrievalError,
    StructuralRetrievalOutcome,
    StructuralRetrievalTrace,
    StructuralSourceHit,
    StructuralTechnicalError,
    bounded_fused_candidates,
    reciprocal_rank_fusion,
    select_final_structural_candidates,
    structural_candidate_to_evidence,
    structural_source_hits,
    validate_structural_rerank,
)


_FIELDS = (
    "body",
    "document_id",
    "document_number",
    "title",
    "source_url",
    "legal_type",
    "issuing_authority",
    "issuance_date",
    "article",
    "clause",
    "heading_path",
    "citation",
    "token_count",
    "dataset_revision",
    "content_sha256",
    "chunk_sha256",
    "inference_text_sha256",
)


class _PineconeSearchError(RuntimeError):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


@dataclass
class _Lane:
    hits: list[StructuralSourceHit] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    errors: dict[str, StructuralTechnicalError] = field(default_factory=dict)
    latency_seconds: float = 0.0
    document_ids: list[int] = field(default_factory=list)


def _technical_error(stage: str, error: Exception) -> StructuralTechnicalError:
    timeout = isinstance(error, (TimeoutError, asyncio.TimeoutError))
    category = getattr(error, "category", None) or (
        "timeout" if timeout else type(error).__name__
    )
    return StructuralTechnicalError(
        stage=stage,
        category=category,
        error_type=type(error).__name__,
        transient=timeout or is_transient_provider_error(error),
        attempts=1,
    )


def _hit_value(hit: object, name: str) -> object:
    if isinstance(hit, Mapping):
        return hit.get(name)
    return getattr(hit, name, None)


class PineconeStructuralRetriever:
    """Dense plus exact-reference structural retrieval; no production cutover."""

    def __init__(
        self,
        *,
        settings: Settings,
        contract: PineconeStructuralContract,
        index: object,
        fts_index: Any,
        reranker: Any,
    ) -> None:
        limits = (
            settings.RERANK_INPUT_LIMIT,
            settings.RERANK_RETURN_LIMIT,
            settings.FINAL_EVIDENCE_LIMIT,
            settings.LLM_CONTEXT_MAX_TOKENS,
            settings.LLM_CONTEXT_PER_DOCUMENT_LIMIT,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            for value in limits
        ) or not math.isfinite(settings.RERANK_MIN_SCORE):
            raise StructuralRetrievalError(
                "Pinecone structural runtime limits are invalid"
            )
        self.settings = settings
        self.contract = contract
        self.index = index
        self.fts_index = fts_index
        self.reranker = reranker

    def _search(
        self,
        query: str,
        *,
        limit: int,
        query_filter: Mapping[str, object] | None = None,
    ) -> tuple[list[StructuralSourceHit], dict[str, int]]:
        response = self.index.search(
            namespace=self.contract.namespace,
            top_k=limit,
            inputs={"text": query},
            filter=query_filter,
            fields=list(_FIELDS),
            timeout=60.0,
        )
        result = getattr(response, "result", None)
        raw_hits = getattr(result, "hits", None)
        if not isinstance(raw_hits, list) or len(raw_hits) > limit:
            raise _PineconeSearchError(
                "malformed_hits",
                "Pinecone structural search hits are malformed",
            )
        points: list[object] = []
        for hit in raw_hits:
            record_id = _hit_value(hit, "_id")
            score = _hit_value(hit, "_score")
            fields = _hit_value(hit, "fields")
            if not isinstance(fields, Mapping):
                raise _PineconeSearchError(
                    "malformed_hits",
                    "Pinecone structural search fields are malformed",
                )
            points.append(
                SimpleNamespace(
                    id=record_id,
                    score=score,
                    payload=dict(fields),
                )
            )
        try:
            hits = structural_source_hits(
                points,
                dataset_revision=self.settings.DATASET_REVISION,
            )
        except Exception as error:
            raise _PineconeSearchError(
                "malformed_hits",
                "Pinecone structural payload validation failed",
            ) from error
        usage = getattr(response, "usage", None)
        tokens = getattr(usage, "embed_total_tokens", None)
        read_units = getattr(usage, "read_units", None)
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            for value in (tokens, read_units)
        ):
            raise _PineconeSearchError(
                "malformed_usage",
                "Pinecone structural search usage is malformed",
            )
        return hits, {
            self.contract.model: tokens,
            "pinecone_read_units": read_units,
        }

    async def _search_lane(
        self,
        *,
        lane: str,
        query: str,
        limit: int,
        query_filter: Mapping[str, object] | None = None,
    ) -> _Lane:
        started = time.perf_counter()
        try:
            hits, usage = await asyncio.to_thread(
                self._search,
                query,
                limit=limit,
                query_filter=query_filter,
            )
            return _Lane(
                hits=hits,
                usage=usage,
                latency_seconds=time.perf_counter() - started,
            )
        except Exception as error:
            return _Lane(
                errors={lane: _technical_error(lane, error)},
                latency_seconds=time.perf_counter() - started,
            )

    async def _exact_lane(self, query: str) -> _Lane:
        if not extract_legal_references(query):
            return _Lane()
        started = time.perf_counter()
        try:
            raw_ids = await asyncio.to_thread(
                self.fts_index.search,
                query,
                limit=self.contract.fused_limit,
            )
            document_ids: list[int] = []
            seen: set[int] = set()
            for document_id in raw_ids:
                if (
                    isinstance(document_id, bool)
                    or not isinstance(document_id, int)
                    or document_id <= 0
                ):
                    raise StructuralRetrievalError(
                        "FTS returned an invalid document identity"
                    )
                if document_id not in seen:
                    seen.add(document_id)
                    document_ids.append(document_id)
        except Exception as error:
            return _Lane(
                errors={"exact_fts": _technical_error("exact_fts", error)},
                latency_seconds=time.perf_counter() - started,
            )
        if not document_ids:
            return _Lane(latency_seconds=time.perf_counter() - started)
        lane = await self._search_lane(
            lane="exact_remote",
            query=query,
            limit=self.contract.exact_top_k,
            query_filter={"document_id": {"$in": document_ids}},
        )
        lane.document_ids = document_ids
        lane.latency_seconds = time.perf_counter() - started
        return lane

    async def retrieve(self, query: str) -> StructuralRetrievalOutcome:
        normalized = " ".join(query.split()) if isinstance(query, str) else ""
        if not normalized:
            raise StructuralRetrievalError(
                "Pinecone structural query must be nonblank"
            )
        total_started = time.perf_counter()
        dense, exact = await asyncio.gather(
            self._search_lane(
                lane="dense",
                query=normalized,
                limit=self.contract.dense_top_k,
            ),
            self._exact_lane(normalized),
        )
        technical_errors = {**dense.errors, **exact.errors}
        usage_by_lane = {
            lane: result.usage
            for lane, result in (("dense", dense), ("exact_remote", exact))
            if result.usage
        }
        provider_usage: Counter[str] = Counter()
        for usage in usage_by_lane.values():
            provider_usage.update(usage)
        latency = {
            "dense": dense.latency_seconds,
            "exact": exact.latency_seconds,
        }
        trace = StructuralRetrievalTrace(
            dense_hits=dense.hits,
            exact_hits=exact.hits,
            exact_document_ids=exact.document_ids,
            provider_usage_by_lane=usage_by_lane,
        )
        if dense.errors and not exact.hits:
            latency["total"] = time.perf_counter() - total_started
            return StructuralRetrievalOutcome(
                status="retrieval_error",
                evidence=[],
                trace=trace,
                latency=latency,
                technical_errors=technical_errors,
                provider_usage=dict(provider_usage),
            )
        try:
            fused = reciprocal_rank_fusion(
                dense=dense.hits,
                bm25=[],
                exact=exact.hits,
                rrf_k=self.contract.rrf_k,
            )
            fused = bounded_fused_candidates(
                fused,
                limit=self.contract.fused_limit,
                per_document_limit=self.contract.per_document_limit,
            )
        except Exception as error:
            technical_errors["fusion"] = _technical_error("fusion", error)
            latency["total"] = time.perf_counter() - total_started
            return StructuralRetrievalOutcome(
                status="retrieval_error",
                evidence=[],
                trace=trace,
                latency=latency,
                technical_errors=technical_errors,
                provider_usage=dict(provider_usage),
            )
        trace.fused_hits = fused
        reranker_input = fused[: self.settings.RERANK_INPUT_LIMIT]
        trace.reranker_input = reranker_input
        if not reranker_input:
            latency["total"] = time.perf_counter() - total_started
            return StructuralRetrievalOutcome(
                status=("partial_technical_error" if technical_errors else "no_candidate"),
                evidence=[],
                trace=trace,
                latency=latency,
                technical_errors=technical_errors,
                provider_usage=dict(provider_usage),
            )
        documents = [candidate.body for candidate in reranker_input]
        trace.reranker_input_format = "body_v1"
        trace.reranker_input_sha256 = hashlib.sha256(
            json.dumps(
                {"query": normalized, "documents": documents},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        reranker_started = time.perf_counter()
        try:
            rerank = await self.reranker.rerank(
                normalized,
                documents,
                mode="pinecone-only",
                rerank_return_limit=self.settings.RERANK_RETURN_LIMIT,
            )
            reranked = validate_structural_rerank(
                rerank,
                reranker_input,
                self.settings,
            )
        except Exception as error:
            technical_errors["reranker"] = _technical_error("reranker", error)
            latency["reranker"] = time.perf_counter() - reranker_started
            latency["total"] = time.perf_counter() - total_started
            return StructuralRetrievalOutcome(
                status="reranker_error",
                evidence=[],
                trace=trace,
                latency=latency,
                technical_errors=technical_errors,
                provider_usage=dict(provider_usage),
            )
        latency["reranker"] = time.perf_counter() - reranker_started
        latency["reranker_provider"] = rerank.latency
        trace.reranker_output = reranked
        trace.reranker_provider = rerank.provider
        trace.reranker_model = rerank.model
        trace.reranker_fallback_reason = rerank.fallback_reason
        trace.reranker_attempts = rerank.attempts
        trace.reranker_input_count = rerank.input_count
        trace.reranker_output_count = rerank.output_count
        final = select_final_structural_candidates(reranked, self.settings)
        trace.final_hits = final
        evidence = [structural_candidate_to_evidence(row) for row in final]
        latency["total"] = time.perf_counter() - total_started
        status: Literal["ok", "no_candidate", "partial_technical_error"]
        if technical_errors:
            status = "partial_technical_error"
        elif evidence:
            status = "ok"
        else:
            status = "no_candidate"
        return StructuralRetrievalOutcome(
            status=status,
            evidence=evidence,
            trace=trace,
            latency=latency,
            technical_errors=technical_errors,
            provider_usage=dict(provider_usage),
        )
