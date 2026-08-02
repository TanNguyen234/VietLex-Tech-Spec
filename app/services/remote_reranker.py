from __future__ import annotations

import asyncio
import math
import random
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from qdrant_client import models

from app.config import Settings


_TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_TRANSIENT_ERROR_NAMES = {
    "ConnectError",
    "ConnectTimeout",
    "ReadTimeout",
    "ResponseHandlingException",
    "TimeoutException",
}


def is_transient_provider_error(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
    return (
        status_code in _TRANSIENT_STATUS_CODES
        or type(error).__name__ in _TRANSIENT_ERROR_NAMES
    )


@dataclass(frozen=True)
class RerankResult:
    index: int
    score: float


@dataclass(frozen=True)
class RerankOutcome:
    results: list[RerankResult]
    provider: str
    model: str
    latency: float
    fallback_reason: str | None = None


class RemoteReranker:
    """Remote-only Qdrant ColBERT reranking with Pinecone fallback."""

    def __init__(
        self,
        *,
        settings: Settings,
        qdrant: Any,
        pinecone: Any,
    ) -> None:
        self._settings = settings
        self._qdrant = qdrant
        self._pinecone = pinecone
        self._collection_lock = threading.Lock()
        self._circuit_lock = threading.Lock()
        self._consecutive_failures = 0
        self._circuit_opened_at = 0.0

    def _circuit_is_open(self) -> bool:
        with self._circuit_lock:
            if self._consecutive_failures < max(
                1, self._settings.RERANK_CIRCUIT_BREAKER_FAILURES
            ):
                return False
            elapsed = time.monotonic() - self._circuit_opened_at
            if elapsed >= self._settings.RERANK_CIRCUIT_BREAKER_COOLDOWN_SECONDS:
                self._consecutive_failures = 0
                self._circuit_opened_at = 0.0
                return False
            return True

    def _record_qdrant_success(self) -> None:
        with self._circuit_lock:
            self._consecutive_failures = 0
            self._circuit_opened_at = 0.0

    def _record_qdrant_failure(self) -> None:
        with self._circuit_lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= max(
                1, self._settings.RERANK_CIRCUIT_BREAKER_FAILURES
            ):
                self._circuit_opened_at = time.monotonic()

    def _ensure_qdrant_collection(self) -> None:
        collection_name = self._settings.QDRANT_RERANK_COLLECTION_NAME
        with self._collection_lock:
            if self._qdrant.collection_exists(collection_name):
                return
            self._qdrant.create_collection(
                collection_name=collection_name,
                vectors_config={
                    self._settings.QDRANT_RERANK_VECTOR_NAME: models.VectorParams(
                        size=self._settings.QDRANT_RERANK_VECTOR_SIZE,
                        distance=models.Distance.COSINE,
                        hnsw_config=models.HnswConfigDiff(m=0),
                        on_disk=True,
                        multivector_config=models.MultiVectorConfig(
                            comparator=models.MultiVectorComparator.MAX_SIM
                        ),
                    )
                },
                optimizers_config=models.OptimizersConfigDiff(
                    indexing_threshold=0
                ),
                on_disk_payload=True,
            )

    def _request_filter(self, request_id: str) -> models.Filter:
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="request_id",
                    match=models.MatchValue(value=request_id),
                )
            ]
        )

    def _qdrant_once(
        self,
        query: str,
        documents: list[str],
    ) -> list[RerankResult]:
        self._ensure_qdrant_collection()
        request_id = str(uuid.uuid4())
        point_ids = [str(uuid.uuid4()) for _ in documents]
        request_filter = self._request_filter(request_id)
        timeout = max(1, int(self._settings.QDRANT_RERANK_TIMEOUT_SECONDS))
        try:
            self._qdrant.upsert(
                collection_name=self._settings.QDRANT_RERANK_COLLECTION_NAME,
                points=[
                    models.PointStruct(
                        id=point_id,
                        vector={
                            self._settings.QDRANT_RERANK_VECTOR_NAME: (
                                models.Document(
                                    text=document,
                                    model=self._settings.QDRANT_RERANK_MODEL,
                                )
                            )
                        },
                        payload={
                            "request_id": request_id,
                            "candidate_index": index,
                            "created_at": int(time.time()),
                        },
                    )
                    for index, (point_id, document) in enumerate(
                        zip(point_ids, documents, strict=True)
                    )
                ],
                wait=True,
                timeout=timeout,
            )
            response = self._qdrant.query_points(
                collection_name=self._settings.QDRANT_RERANK_COLLECTION_NAME,
                query=models.Document(
                    text=query,
                    model=self._settings.QDRANT_RERANK_MODEL,
                ),
                using=self._settings.QDRANT_RERANK_VECTOR_NAME,
                query_filter=request_filter,
                limit=min(
                    len(documents),
                    self._settings.RERANK_RETURN_LIMIT,
                ),
                with_payload=True,
                with_vectors=False,
                timeout=timeout,
            )
            points = getattr(response, "points", []) or []
            ranked: list[RerankResult] = []
            for point in points:
                payload = getattr(point, "payload", None) or {}
                index = payload.get("candidate_index")
                score = getattr(point, "score", None)
                if (
                    isinstance(index, int)
                    and 0 <= index < len(documents)
                    and isinstance(score, (int, float))
                    and math.isfinite(float(score))
                ):
                    ranked.append(
                        RerankResult(index=index, score=float(score))
                    )
            return ranked
        finally:
            try:
                self._qdrant.delete(
                    collection_name=(
                        self._settings.QDRANT_RERANK_COLLECTION_NAME
                    ),
                    points_selector=request_filter,
                    wait=False,
                    timeout=timeout,
                )
            except Exception:
                pass

    async def _qdrant_rerank(
        self,
        query: str,
        documents: list[str],
    ) -> RerankOutcome:
        started = time.perf_counter()
        attempts = max(1, self._settings.QDRANT_RERANK_MAX_RETRIES)
        for attempt in range(1, attempts + 1):
            try:
                results = await asyncio.wait_for(
                    asyncio.to_thread(self._qdrant_once, query, documents),
                    timeout=self._settings.QDRANT_RERANK_TIMEOUT_SECONDS,
                )
                self._record_qdrant_success()
                return RerankOutcome(
                    results=results,
                    provider="qdrant",
                    model=self._settings.QDRANT_RERANK_MODEL,
                    latency=round(time.perf_counter() - started, 6),
                )
            except Exception as error:
                if not is_transient_provider_error(error):
                    raise
                if attempt == attempts:
                    self._record_qdrant_failure()
                    raise
                delay = min(
                    self._settings.QDRANT_RERANK_RETRY_MAX_SECONDS,
                    self._settings.QDRANT_RERANK_RETRY_BASE_SECONDS
                    * (2 ** (attempt - 1)),
                )
                await asyncio.sleep(delay * (0.8 + random.random() * 0.4))
        raise RuntimeError("Qdrant reranking retry loop ended unexpectedly.")

    @staticmethod
    def _pinecone_items(response: Any) -> list[Any]:
        if isinstance(response, dict):
            return list(response.get("data") or [])
        return list(getattr(response, "data", []) or [])

    async def _pinecone_rerank(
        self,
        query: str,
        documents: list[str],
        *,
        fallback_reason: str,
    ) -> RerankOutcome:
        started = time.perf_counter()
        response = await asyncio.wait_for(
            asyncio.to_thread(
                self._pinecone.inference.rerank,
                model=self._settings.PINECONE_RERANK_MODEL,
                query=query,
                documents=documents,
                top_n=min(
                    len(documents),
                    self._settings.RERANK_RETURN_LIMIT,
                ),
                return_documents=False,
            ),
            timeout=self._settings.PINECONE_RERANK_TIMEOUT_SECONDS,
        )
        ranked: list[RerankResult] = []
        for item in self._pinecone_items(response):
            if isinstance(item, dict):
                index = item.get("index")
                score = item.get("score")
            else:
                index = getattr(item, "index", None)
                score = getattr(item, "score", None)
            if (
                isinstance(index, int)
                and 0 <= index < len(documents)
                and isinstance(score, (int, float))
                and math.isfinite(float(score))
            ):
                ranked.append(RerankResult(index=index, score=float(score)))
        return RerankOutcome(
            results=ranked,
            provider="pinecone",
            model=self._settings.PINECONE_RERANK_MODEL,
            latency=round(time.perf_counter() - started, 6),
            fallback_reason=fallback_reason,
        )

    async def rerank(
        self,
        query: str,
        documents: list[str],
    ) -> RerankOutcome:
        if not documents:
            return RerankOutcome(
                results=[],
                provider="none",
                model="none",
                latency=0.0,
            )
        if self._circuit_is_open():
            return await self._pinecone_rerank(
                query,
                documents,
                fallback_reason="qdrant_circuit_open",
            )
        try:
            return await self._qdrant_rerank(query, documents)
        except Exception as error:
            if not is_transient_provider_error(error):
                raise
            return await self._pinecone_rerank(
                query,
                documents,
                fallback_reason="qdrant_transient",
            )
