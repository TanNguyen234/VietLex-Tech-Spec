"""Opt-in structural Qdrant retrieval without a production cutover."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Protocol, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    ValidationError,
    model_validator,
)
from qdrant_client import QdrantClient, models

from app.config import Settings
from app.ingestion.legal_fts import extract_legal_references
from app.ingestion.legal_text import EvidenceChunk
from app.ingestion.structural_qdrant import (
    InferenceUsageReceipt,
    StructuralProviderError,
    StructuralQdrantContract,
    StructuralQdrantTransport,
    dense_query_document,
    sparse_query_document,
)
from app.services.remote_reranker import (
    RerankOutcome,
    is_transient_provider_error,
)


_PositiveInt = Annotated[StrictInt, Field(gt=0)]
_NonnegativeInt = Annotated[StrictInt, Field(ge=0)]
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_RerankerMode = Literal["current", "pinecone-only", "qdrant-only"]


class StructuralRetrievalError(RuntimeError):
    """Raised when an opt-in structural retrieval contract is invalid."""


class _MalformedPayloadError(StructuralRetrievalError):
    pass


class _NeighborReadOverflowError(StructuralRetrievalError):
    pass


class StructuralCandidate(BaseModel):
    """One validated structural payload with auditable stage ranks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str = Field(min_length=1)
    document_id: _PositiveInt
    body: str = Field(min_length=1)
    document_number: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    legal_type: str = Field(min_length=1)
    issuing_authority: str | None = Field(default=None, min_length=1)
    issuance_date: str | None = Field(default=None, min_length=1)
    article: str | None = Field(default=None, min_length=1)
    clause: str | None = Field(default=None, min_length=1)
    heading_path: str
    citation: str = Field(min_length=1)
    token_count: _PositiveInt
    dataset_revision: str = Field(min_length=1)
    content_sha256: str = Field(pattern=_SHA256_PATTERN)
    chunk_sha256: str = Field(pattern=_SHA256_PATTERN)
    inference_text_sha256: str = Field(pattern=_SHA256_PATTERN)
    dense_rank: _PositiveInt | None = None
    dense_score: float | None = Field(default=None, allow_inf_nan=False)
    bm25_rank: _PositiveInt | None = None
    bm25_score: float | None = Field(default=None, allow_inf_nan=False)
    exact_rank: _PositiveInt | None = None
    exact_score: float | None = Field(default=None, allow_inf_nan=False)
    fused_score: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    reranker_rank: _PositiveInt | None = None
    reranker_score: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_chunk_identity(self) -> Self:
        if hashlib.sha256(self.body.encode("utf-8")).hexdigest() != self.chunk_sha256:
            raise ValueError("structural chunk SHA-256 mismatch")
        return self


class StructuralSourceHit(BaseModel):
    """Provider order and score before cross-lane fusion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str = Field(min_length=1)
    candidate: StructuralCandidate
    source_score: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.record_id != self.candidate.record_id:
            raise ValueError("source hit record identity mismatch")
        return self


class StructuralTechnicalError(BaseModel):
    """Typed diagnostics that deliberately exclude raw provider messages."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: str = Field(min_length=1)
    category: str = Field(min_length=1)
    error_type: str = Field(min_length=1)
    transient: bool
    attempts: _PositiveInt = 1


class StructuralRetrievalTrace(BaseModel):
    """Honest structural lane names retained for offline evaluation."""

    model_config = ConfigDict(extra="forbid")

    dense_hits: list[StructuralSourceHit] = Field(default_factory=list)
    bm25_hits: list[StructuralSourceHit] = Field(default_factory=list)
    exact_hits: list[StructuralSourceHit] = Field(default_factory=list)
    exact_document_ids: list[_PositiveInt] = Field(default_factory=list)
    fused_hits: list[StructuralCandidate] = Field(default_factory=list)
    reranker_input: list[StructuralCandidate] = Field(default_factory=list)
    reranker_output: list[StructuralCandidate] = Field(default_factory=list)
    final_hits: list[StructuralCandidate] = Field(default_factory=list)
    provider_usage_by_lane: dict[str, dict[str, StrictInt]] = Field(
        default_factory=dict
    )
    reranker_provider: str | None = None
    reranker_model: str | None = None
    reranker_fallback_reason: str | None = None
    reranker_attempts: _PositiveInt | None = None
    reranker_input_count: _NonnegativeInt | None = None
    reranker_output_count: _NonnegativeInt | None = None
    reranker_input_format: Literal["body_v1"] | None = None
    reranker_input_sha256: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )


class StructuralRetrievalOutcome(BaseModel):
    """Typed online result; offline evaluation consumes the trace separately."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
    )

    status: Literal[
        "ok",
        "no_candidate",
        "partial_technical_error",
        "retrieval_error",
        "reranker_error",
    ]
    evidence: list[EvidenceChunk]
    trace: StructuralRetrievalTrace
    latency: dict[str, float]
    technical_errors: dict[str, StructuralTechnicalError]
    provider_usage: dict[str, StrictInt]

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
            for value in self.latency.values()
        ):
            raise ValueError("structural retrieval latency is malformed")
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            for value in self.provider_usage.values()
        ):
            raise ValueError("structural retrieval provider usage is malformed")
        if self.status == "ok" and (not self.evidence or self.technical_errors):
            raise ValueError("successful structural retrieval evidence is invalid")
        if self.status == "no_candidate" and (
            self.evidence or self.technical_errors
        ):
            raise ValueError("no-candidate structural outcome is invalid")
        if self.status in {
            "partial_technical_error",
            "retrieval_error",
            "reranker_error",
        } and not self.technical_errors:
            raise ValueError("technical structural outcome requires errors")
        if self.status in {"retrieval_error", "reranker_error"} and self.evidence:
            raise ValueError("failed structural retrieval must be fail-closed")
        return self


class _QueryTransport(Protocol):
    contract: StructuralQdrantContract

    def query_with_usage(
        self,
        *,
        document: models.Document,
        using: str,
        limit: int,
        query_filter: models.Filter | None = None,
        with_vectors: bool = False,
    ) -> tuple[list[models.ScoredPoint], InferenceUsageReceipt]: ...

    def read_by_filter(
        self,
        *,
        query_filter: models.Filter,
        limit: int,
    ) -> Sequence[object]: ...


@dataclass
class _LaneResult:
    hits: list[StructuralSourceHit] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    errors: dict[str, StructuralTechnicalError] = field(default_factory=dict)
    latency_seconds: float = 0.0
    document_ids: list[int] = field(default_factory=list)


_RANK_FIELDS = {
    "dense_rank",
    "dense_score",
    "bm25_rank",
    "bm25_score",
    "exact_rank",
    "exact_score",
    "fused_score",
    "reranker_rank",
    "reranker_score",
}


def _candidate_identity(candidate: StructuralCandidate) -> dict[str, object]:
    return candidate.model_dump(exclude=_RANK_FIELDS)


def reciprocal_rank_fusion(
    *,
    dense: Sequence[StructuralSourceHit],
    bm25: Sequence[StructuralSourceHit],
    exact: Sequence[StructuralSourceHit],
    rrf_k: int,
) -> list[StructuralCandidate]:
    """Fuse three ranked lanes while preserving source ranks and scores."""
    if isinstance(rrf_k, bool) or not isinstance(rrf_k, int) or rrf_k <= 0:
        raise StructuralRetrievalError("RRF k must be a positive integer")
    by_id: dict[str, StructuralCandidate] = {}
    for source, hits in (
        ("dense", dense),
        ("bm25", bm25),
        ("exact", exact),
    ):
        seen: set[str] = set()
        for rank, hit in enumerate(hits, start=1):
            if hit.record_id in seen:
                continue
            seen.add(hit.record_id)
            current = by_id.get(hit.record_id)
            if current is None:
                current = hit.candidate
            elif _candidate_identity(current) != _candidate_identity(
                hit.candidate
            ):
                raise StructuralRetrievalError(
                    "conflicting structural payloads share one record ID"
                )
            current = current.model_copy(
                update={
                    f"{source}_rank": rank,
                    f"{source}_score": hit.source_score,
                    "fused_score": (
                        current.fused_score + 1.0 / (rrf_k + rank)
                    ),
                }
            )
            by_id[hit.record_id] = current
    return sorted(
        by_id.values(),
        key=lambda row: (
            -row.fused_score,
            row.exact_rank is None,
            row.exact_rank or 0,
            row.record_id,
        ),
    )


def _technical_error(
    stage: str,
    error: Exception,
    *,
    category: str | None = None,
) -> StructuralTechnicalError:
    if isinstance(error, StructuralProviderError):
        return StructuralTechnicalError(
            stage=stage,
            category=error.category,
            error_type=type(error).__name__,
            transient=error.transient,
            attempts=max(1, error.attempts),
        )
    timeout = isinstance(error, (TimeoutError, asyncio.TimeoutError))
    return StructuralTechnicalError(
        stage=stage,
        category=category or ("timeout" if timeout else type(error).__name__),
        error_type=type(error).__name__,
        transient=timeout or is_transient_provider_error(error),
        attempts=1,
    )


def _source_hits(
    points: Sequence[object],
    *,
    dataset_revision: str,
) -> list[StructuralSourceHit]:
    hits: list[StructuralSourceHit] = []
    seen: set[str] = set()
    try:
        for point in points:
            raw_id = getattr(point, "id", None)
            if raw_id is None:
                raise _MalformedPayloadError("missing structural record ID")
            record_id = str(raw_id).strip()
            score = getattr(point, "score", None)
            payload = getattr(point, "payload", None)
            if (
                not record_id
                or isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(score)
                or not isinstance(payload, Mapping)
            ):
                raise _MalformedPayloadError("malformed structural source hit")
            candidate = StructuralCandidate.model_validate(
                {"record_id": record_id, **dict(payload)}
            )
            if candidate.dataset_revision != dataset_revision:
                raise _MalformedPayloadError(
                    "structural source revision mismatch"
                )
            if record_id in seen:
                continue
            seen.add(record_id)
            hits.append(
                StructuralSourceHit(
                    record_id=record_id,
                    candidate=candidate,
                    source_score=float(score),
                )
            )
    except (ValidationError, ValueError, TypeError) as error:
        if isinstance(error, _MalformedPayloadError):
            raise
        raise _MalformedPayloadError(
            "structural source payload validation failed"
        ) from error
    return hits


_ARTICLE_NUMBER = re.compile(r"^Điều\s+(\d+)\b", re.IGNORECASE)


def _neighbor_filter(
    candidates: Sequence[StructuralCandidate],
) -> tuple[models.Filter | None, dict[int, set[str]]]:
    allowed: dict[int, set[str]] = {}
    for candidate in candidates:
        if candidate.article is None:
            continue
        articles = allowed.setdefault(candidate.document_id, set())
        articles.add(candidate.article)
        match = _ARTICLE_NUMBER.match(candidate.article.strip())
        if match is not None:
            number = int(match.group(1))
            if number > 1:
                articles.add(f"Điều {number - 1}")
            articles.add(f"Điều {number + 1}")
    if not allowed:
        return None, allowed
    should = [
        models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=document_id),
                ),
                models.FieldCondition(
                    key="article",
                    match=models.MatchAny(any=sorted(articles)),
                ),
            ]
        )
        for document_id, articles in sorted(allowed.items())
    ]
    return models.Filter(should=should), allowed


def _neighbor_candidates(
    points: Sequence[object],
    *,
    dataset_revision: str,
    allowed: Mapping[int, set[str]],
    limit: int,
) -> list[StructuralCandidate]:
    if len(points) > limit:
        raise _NeighborReadOverflowError("structural neighbor read overflow")
    result: list[StructuralCandidate] = []
    seen: set[str] = set()
    try:
        for point in points:
            raw_id = getattr(point, "id", None)
            payload = getattr(point, "payload", None)
            record_id = str(raw_id).strip() if raw_id is not None else ""
            if not record_id or not isinstance(payload, Mapping):
                raise _MalformedPayloadError("malformed structural neighbor")
            candidate = StructuralCandidate.model_validate(
                {"record_id": record_id, **dict(payload)}
            )
            if (
                candidate.dataset_revision != dataset_revision
                or candidate.article not in allowed.get(candidate.document_id, set())
            ):
                raise _MalformedPayloadError(
                    "structural neighbor scope or revision mismatch"
                )
            if record_id not in seen:
                seen.add(record_id)
                result.append(candidate)
    except (ValidationError, ValueError, TypeError) as error:
        if isinstance(error, _MalformedPayloadError):
            raise
        raise _MalformedPayloadError(
            "structural neighbor payload validation failed"
        ) from error
    return result


def _interleave_neighbors(
    fused: Sequence[StructuralCandidate],
    neighbors: Sequence[StructuralCandidate],
) -> list[StructuralCandidate]:
    by_locator: dict[tuple[int, str], list[StructuralCandidate]] = {}
    for candidate in neighbors:
        if candidate.article is not None:
            by_locator.setdefault(
                (candidate.document_id, candidate.article), []
            ).append(candidate)
    result: list[StructuralCandidate] = []
    seen: set[str] = set()
    for seed in fused:
        if seed.record_id not in seen:
            seen.add(seed.record_id)
            result.append(seed)
        if seed.article is None:
            continue
        articles = {seed.article}
        match = _ARTICLE_NUMBER.match(seed.article.strip())
        if match is not None:
            number = int(match.group(1))
            if number > 1:
                articles.add(f"Điều {number - 1}")
            articles.add(f"Điều {number + 1}")
        for article in sorted(articles):
            for candidate in by_locator.get((seed.document_id, article), []):
                if candidate.record_id not in seen:
                    seen.add(candidate.record_id)
                    result.append(candidate)
    return result


def _bounded_fused_candidates(
    candidates: Sequence[StructuralCandidate],
    *,
    limit: int,
    per_document_limit: int,
) -> list[StructuralCandidate]:
    selected: list[StructuralCandidate] = []
    per_document: Counter[int] = Counter()
    for candidate in candidates:
        if len(selected) >= limit:
            break
        if per_document[candidate.document_id] >= per_document_limit:
            continue
        selected.append(candidate)
        per_document[candidate.document_id] += 1
    return selected


def _candidate_to_evidence(candidate: StructuralCandidate) -> EvidenceChunk:
    return EvidenceChunk(
        document_id=candidate.document_id,
        document_number=candidate.document_number,
        title=candidate.title,
        source_url=candidate.source_url,
        heading_path=candidate.heading_path,
        article=candidate.article,
        clause=candidate.clause,
        citation=candidate.citation,
        text=candidate.body,
        token_count=candidate.token_count,
    )


class StructuralRetriever:
    """Concurrent dense/BM25/exact retrieval over final structural points."""

    def __init__(
        self,
        *,
        settings: Settings,
        contract: StructuralQdrantContract,
        transport: _QueryTransport,
        fts_index: Any,
        reranker: Any,
        reranker_mode: _RerankerMode = "current",
        neighbor_expansion_enabled: bool | None = None,
        neighbor_read_limit: int | None = None,
    ) -> None:
        if transport.contract != contract:
            raise StructuralRetrievalError("transport contract mismatch")
        if reranker_mode not in {"current", "pinecone-only", "qdrant-only"}:
            raise StructuralRetrievalError("structural reranker mode is invalid")
        resolved_neighbor_enabled = (
            settings.STRUCTURAL_NEIGHBOR_EXPANSION_ENABLED
            if neighbor_expansion_enabled is None
            else neighbor_expansion_enabled
        )
        resolved_neighbor_limit = (
            settings.STRUCTURAL_NEIGHBOR_READ_LIMIT
            if neighbor_read_limit is None
            else neighbor_read_limit
        )
        if not isinstance(resolved_neighbor_enabled, bool):
            raise StructuralRetrievalError(
                "structural neighbor expansion flag is invalid"
            )
        runtime_limits = (
            settings.RERANK_INPUT_LIMIT,
            settings.RERANK_RETURN_LIMIT,
            settings.FINAL_EVIDENCE_LIMIT,
            settings.LLM_CONTEXT_MAX_TOKENS,
            settings.LLM_CONTEXT_PER_DOCUMENT_LIMIT,
            resolved_neighbor_limit,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            for value in runtime_limits
        ) or not math.isfinite(settings.RERANK_MIN_SCORE):
            raise StructuralRetrievalError(
                "structural retrieval runtime limits are invalid"
            )
        self.settings = settings
        self.contract = contract
        self.transport = transport
        self.fts_index = fts_index
        self.reranker = reranker
        self.reranker_mode = reranker_mode
        self.neighbor_expansion_enabled = resolved_neighbor_enabled
        self.neighbor_read_limit = resolved_neighbor_limit

    async def _expand_structural_neighbors(
        self,
        fused: Sequence[StructuralCandidate],
    ) -> list[StructuralCandidate]:
        query_filter, allowed = _neighbor_filter(fused)
        if query_filter is None:
            return list(fused)
        points = await asyncio.to_thread(
            self.transport.read_by_filter,
            query_filter=query_filter,
            limit=self.neighbor_read_limit,
        )
        neighbors = _neighbor_candidates(
            points,
            dataset_revision=self.settings.DATASET_REVISION,
            allowed=allowed,
            limit=self.neighbor_read_limit,
        )
        return _interleave_neighbors(fused, neighbors)

    async def _query_lane(
        self,
        *,
        lane: str,
        error_key: str,
        document: models.Document,
        using: str,
        limit: int,
        query_filter: models.Filter | None = None,
    ) -> _LaneResult:
        started = time.perf_counter()
        usage: dict[str, int] = {}
        try:
            points, receipt = await asyncio.to_thread(
                self.transport.query_with_usage,
                document=document,
                using=using,
                limit=limit,
                query_filter=query_filter,
            )
            usage = dict(receipt.model_tokens)
            if len(points) > limit:
                raise _MalformedPayloadError(
                    "structural source returned more than the requested limit"
                )
            hits = _source_hits(
                points,
                dataset_revision=self.settings.DATASET_REVISION,
            )
            return _LaneResult(
                hits=hits,
                usage=usage,
                latency_seconds=time.perf_counter() - started,
            )
        except Exception as error:
            category = (
                "malformed_payload"
                if isinstance(error, _MalformedPayloadError)
                else None
            )
            return _LaneResult(
                usage=usage,
                errors={
                    error_key: _technical_error(
                        lane,
                        error,
                        category=category,
                    )
                },
                latency_seconds=time.perf_counter() - started,
            )

    async def _exact_lane(
        self,
        query: str,
        sparse_document: models.Document,
    ) -> _LaneResult:
        if not extract_legal_references(query):
            return _LaneResult()
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
            return _LaneResult(
                errors={"exact_fts": _technical_error("exact_fts", error)},
                latency_seconds=time.perf_counter() - started,
            )
        if not document_ids:
            return _LaneResult(
                latency_seconds=time.perf_counter() - started,
            )
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchAny(any=document_ids),
                )
            ]
        )
        result = await self._query_lane(
            lane="exact_remote",
            error_key="exact_remote",
            document=sparse_document,
            using=self.contract.sparse_vector_name,
            limit=self.contract.bm25_top_k,
            query_filter=query_filter,
        )
        result.document_ids = document_ids
        result.latency_seconds = time.perf_counter() - started
        return result

    async def retrieve(self, query: str) -> StructuralRetrievalOutcome:
        normalized = " ".join(query.split()) if isinstance(query, str) else ""
        if not normalized:
            raise StructuralRetrievalError("structural query must be nonblank")
        total_started = time.perf_counter()
        dense_document = dense_query_document(normalized, self.contract)
        sparse_document = sparse_query_document(normalized, self.contract)
        dense, bm25, exact = await asyncio.gather(
            self._query_lane(
                lane="dense",
                error_key="dense",
                document=dense_document,
                using=self.contract.dense_vector_name,
                limit=self.contract.dense_top_k,
            ),
            self._query_lane(
                lane="bm25",
                error_key="bm25",
                document=sparse_document,
                using=self.contract.sparse_vector_name,
                limit=self.contract.bm25_top_k,
            ),
            self._exact_lane(normalized, sparse_document),
        )
        technical_errors = {
            **dense.errors,
            **bm25.errors,
            **exact.errors,
        }
        usage_by_lane = {
            lane: result.usage
            for lane, result in (
                ("dense", dense),
                ("bm25", bm25),
                ("exact_remote", exact),
            )
            if result.usage
        }
        provider_usage: Counter[str] = Counter()
        for usage in usage_by_lane.values():
            provider_usage.update(usage)
        latency = {
            "dense": dense.latency_seconds,
            "bm25": bm25.latency_seconds,
            "exact": exact.latency_seconds,
        }
        trace = StructuralRetrievalTrace(
            dense_hits=dense.hits,
            bm25_hits=bm25.hits,
            exact_hits=exact.hits,
            exact_document_ids=exact.document_ids,
            provider_usage_by_lane=usage_by_lane,
        )
        if dense.errors and bm25.errors:
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
                bm25=bm25.hits,
                exact=exact.hits,
                rrf_k=self.contract.rrf_k,
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
        if self.neighbor_expansion_enabled:
            neighbor_started = time.perf_counter()
            try:
                fused = await self._expand_structural_neighbors(fused)
            except Exception as error:
                category = None
                if isinstance(error, _MalformedPayloadError):
                    category = "malformed_payload"
                elif isinstance(error, _NeighborReadOverflowError):
                    category = "read_overflow"
                technical_errors["structural_neighbors"] = _technical_error(
                    "structural_neighbors", error, category=category
                )
                latency["structural_neighbors"] = (
                    time.perf_counter() - neighbor_started
                )
                latency["total"] = time.perf_counter() - total_started
                return StructuralRetrievalOutcome(
                    status="retrieval_error",
                    evidence=[],
                    trace=trace,
                    latency=latency,
                    technical_errors=technical_errors,
                    provider_usage=dict(provider_usage),
                )
            latency["structural_neighbors"] = (
                time.perf_counter() - neighbor_started
            )
        fused = _bounded_fused_candidates(
            fused,
            limit=self.contract.fused_limit,
            per_document_limit=self.contract.per_document_limit,
        )
        trace.fused_hits = fused
        reranker_input = fused[: self.settings.RERANK_INPUT_LIMIT]
        trace.reranker_input = reranker_input
        if not reranker_input:
            latency["total"] = time.perf_counter() - total_started
            return StructuralRetrievalOutcome(
                status=(
                    "partial_technical_error"
                    if technical_errors
                    else "no_candidate"
                ),
                evidence=[],
                trace=trace,
                latency=latency,
                technical_errors=technical_errors,
                provider_usage=dict(provider_usage),
            )

        reranker_started = time.perf_counter()
        reranker_documents = [candidate.body for candidate in reranker_input]
        trace.reranker_input_format = "body_v1"
        trace.reranker_input_sha256 = hashlib.sha256(
            json.dumps(
                {"query": normalized, "documents": reranker_documents},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        try:
            rerank = await self.reranker.rerank(
                normalized,
                reranker_documents,
                mode=self.reranker_mode,
                rerank_return_limit=self.settings.RERANK_RETURN_LIMIT,
            )
            reranked = self._validated_rerank(rerank, reranker_input)
        except Exception as error:
            technical_errors["reranker"] = _technical_error(
                "reranker",
                error,
            )
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
        trace.reranker_output = reranked
        trace.reranker_provider = rerank.provider
        trace.reranker_model = rerank.model
        trace.reranker_fallback_reason = rerank.fallback_reason
        trace.reranker_attempts = rerank.attempts
        trace.reranker_input_count = rerank.input_count
        trace.reranker_output_count = rerank.output_count
        latency["reranker_provider"] = rerank.latency
        if rerank.fallback_reason in {
            "qdrant_transient",
            "qdrant_circuit_open",
        }:
            technical_errors["reranker_primary"] = StructuralTechnicalError(
                stage="reranker_primary",
                category=rerank.fallback_reason,
                error_type="QdrantRerankerFallback",
                transient=True,
                attempts=max(1, rerank.attempts),
            )

        final = self._select_final(reranked)
        trace.final_hits = final
        evidence = [_candidate_to_evidence(candidate) for candidate in final]
        latency["total"] = time.perf_counter() - total_started
        status: Literal[
            "ok",
            "no_candidate",
            "partial_technical_error",
        ]
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

    def _validated_rerank(
        self,
        outcome: RerankOutcome,
        candidates: Sequence[StructuralCandidate],
    ) -> list[StructuralCandidate]:
        if (
            not isinstance(outcome.provider, str)
            or not outcome.provider
            or not isinstance(outcome.model, str)
            or not outcome.model
            or len(outcome.results) > self.settings.RERANK_RETURN_LIMIT
            or isinstance(outcome.input_count, bool)
            or outcome.input_count != len(candidates)
            or isinstance(outcome.output_count, bool)
            or outcome.output_count != len(outcome.results)
            or isinstance(outcome.attempts, bool)
            or not isinstance(outcome.attempts, int)
            or outcome.attempts <= 0
            or isinstance(outcome.latency, bool)
            or not isinstance(outcome.latency, (int, float))
            or not math.isfinite(outcome.latency)
            or outcome.latency < 0
            or (
                outcome.fallback_reason
                in {"qdrant_transient", "qdrant_circuit_open"}
                and outcome.provider != "pinecone"
            )
        ):
            raise StructuralRetrievalError("reranker response is malformed")
        result: list[StructuralCandidate] = []
        seen: set[int] = set()
        for rank, item in enumerate(outcome.results, start=1):
            if (
                isinstance(item.index, bool)
                or not isinstance(item.index, int)
                or item.index < 0
                or item.index >= len(candidates)
                or item.index in seen
                or isinstance(item.score, bool)
                or not isinstance(item.score, (int, float))
                or not math.isfinite(item.score)
            ):
                raise StructuralRetrievalError("reranker result is malformed")
            seen.add(item.index)
            result.append(
                candidates[item.index].model_copy(
                    update={
                        "reranker_rank": rank,
                        "reranker_score": float(item.score),
                    }
                )
            )
        if not result and candidates:
            raise StructuralRetrievalError("reranker returned no candidates")
        return result

    def _select_final(
        self,
        candidates: Sequence[StructuralCandidate],
    ) -> list[StructuralCandidate]:
        selected: list[StructuralCandidate] = []
        per_document: Counter[int] = Counter()
        tokens = 0
        for candidate in candidates:
            if len(selected) >= self.settings.FINAL_EVIDENCE_LIMIT:
                break
            if (
                candidate.reranker_score is None
                or candidate.reranker_score < self.settings.RERANK_MIN_SCORE
                or per_document[candidate.document_id]
                >= self.settings.LLM_CONTEXT_PER_DOCUMENT_LIMIT
                or tokens + candidate.token_count
                > self.settings.LLM_CONTEXT_MAX_TOKENS
            ):
                continue
            selected.append(candidate)
            per_document[candidate.document_id] += 1
            tokens += candidate.token_count
        return selected


def build_structural_retriever(
    settings: Settings,
    *,
    client: QdrantClient,
    fts_index: Any,
    reranker: Any,
    contract: StructuralQdrantContract | None = None,
    reranker_mode: _RerankerMode = "current",
    neighbor_expansion_enabled: bool | None = None,
    neighbor_read_limit: int | None = None,
) -> StructuralRetriever:
    """Construct the explicit opt-in backend; never alter the v1 factory."""
    if not settings.STRUCTURAL_BACKEND_ENABLED:
        raise StructuralRetrievalError("structural backend is disabled")
    resolved_contract = contract or StructuralQdrantContract.from_settings(
        settings
    )
    return StructuralRetriever(
        settings=settings,
        contract=resolved_contract,
        transport=StructuralQdrantTransport(client, resolved_contract),
        fts_index=fts_index,
        reranker=reranker,
        reranker_mode=reranker_mode,
        neighbor_expansion_enabled=neighbor_expansion_enabled,
        neighbor_read_limit=neighbor_read_limit,
    )
