from __future__ import annotations

import math
import random
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from pinecone import Pinecone, ServerlessSpec

from app.config import Settings
from app.ingestion.content_store import StoredDocument
from app.ingestion.legal_text import deterministic_point_id
from app.ingestion.sparse_encoder import stable_term_id


_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
_STOP_WORDS = frozenset(
    {
        "bị",
        "bởi",
        "các",
        "có",
        "của",
        "được",
        "là",
        "một",
        "những",
        "theo",
        "thì",
        "trong",
        "và",
        "về",
        "với",
    }
)


@dataclass(frozen=True)
class SparseValues:
    indices: list[int]
    values: list[float]


@dataclass(frozen=True)
class IndexVerification:
    index_name: str
    namespace: str
    vector_count: int
    dense_size: int
    ready: bool


def fast_terms(text: str, *, max_terms: int = 1_024) -> list[str]:
    terms = [
        term
        for term in _TOKEN_PATTERN.findall((text or "").casefold())
        if term not in _STOP_WORDS
    ]
    return terms[:max_terms]


@dataclass(frozen=True)
class FastSparseEncoder:
    average_document_length: float
    max_nonzero_terms: int = 64

    def _encode(self, text: str, *, query: bool) -> SparseValues:
        terms = fast_terms(text)
        counts = Counter(terms)
        length = max(1, len(terms))
        weights: defaultdict[int, float] = defaultdict(float)
        for term, frequency in counts.items():
            if query:
                weight = 1.0 + math.log(frequency)
            else:
                k1 = 1.2
                b = 0.75
                denominator = frequency + k1 * (
                    1.0
                    - b
                    + b
                    * length
                    / max(1.0, self.average_document_length)
                )
                weight = frequency * (k1 + 1.0) / denominator
            weights[stable_term_id(term)] += float(weight)
        selected = sorted(
            weights,
            key=lambda term_id: (-weights[term_id], term_id),
        )[: self.max_nonzero_terms]
        selected.sort()
        return SparseValues(
            indices=selected,
            values=[weights[term_id] for term_id in selected],
        )

    def encode_document(self, text: str) -> SparseValues:
        return self._encode(text, query=False)

    def encode_query(self, text: str) -> SparseValues:
        return self._encode(text, query=True)


def scale_hybrid_query(
    dense: list[float],
    sparse: SparseValues,
    *,
    alpha: float,
) -> tuple[list[float], dict[str, list[int] | list[float]]]:
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("alpha must be between zero and one.")
    return (
        [float(value) * alpha for value in dense],
        {
            "indices": sparse.indices,
            "values": [
                float(value) * (1.0 - alpha)
                for value in sparse.values
            ],
        },
    )


def build_record(
    *,
    document: StoredDocument,
    dense_vector: list[float],
    sparse_vector: SparseValues,
    settings: Settings,
) -> dict[str, Any]:
    if len(dense_vector) != settings.DENSE_VECTOR_SIZE:
        raise ValueError("Dense vector dimension does not match settings.")
    metadata = document.metadata
    return {
        "id": str(
            deterministic_point_id(
                settings.DATASET_REPOSITORY,
                settings.DATASET_REVISION,
                metadata.document_id,
            )
        ),
        "values": [float(value) for value in dense_vector],
        "sparse_values": {
            "indices": sparse_vector.indices,
            "values": sparse_vector.values,
        },
        "metadata": {
            "document_id": metadata.document_id,
            "content_store_key": document.content_store_key,
            "content_sha256": document.content_sha256,
            "dataset_revision": settings.DATASET_REVISION,
        },
    }


def create_control_client(settings: Settings) -> Pinecone:
    api_key = settings.pinecone_api_key
    if not api_key:
        raise RuntimeError(
            "PIPECONE_API or PINECONE_API_KEY is required."
        )
    return Pinecone(api_key=api_key)


def _index_value(index: Any, name: str) -> Any:
    if isinstance(index, dict):
        return index.get(name)
    return getattr(index, name, None)


def wait_for_index_ready(
    client: Any,
    index_name: str,
    *,
    timeout_seconds: float = 600.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        description = client.describe_index(index_name)
        status = _index_value(description, "status")
        ready = _index_value(status, "ready")
        if ready is True:
            return
        time.sleep(2.0)
    raise TimeoutError(f"Pinecone index {index_name!r} is not ready.")


def reset_or_create_index(
    client: Any,
    settings: Settings,
    *,
    allow_destructive: bool,
    resume_existing_target: bool,
) -> tuple[Any, bool]:
    name = settings.PINECONE_INDEX_NAME
    exists = bool(client.has_index(name))
    if exists and not resume_existing_target:
        if not allow_destructive:
            raise RuntimeError(
                "Destructive Pinecone reset requires explicit authorization."
            )
        client.delete_index(name)
        deadline = time.monotonic() + 600.0
        while client.has_index(name):
            if time.monotonic() >= deadline:
                raise TimeoutError("Pinecone index deletion timed out.")
            time.sleep(2.0)
        exists = False
    if not exists:
        client.create_index(
            name=name,
            dimension=settings.DENSE_VECTOR_SIZE,
            metric="dotproduct",
            spec=ServerlessSpec(
                cloud=settings.PINECONE_CLOUD,
                region=settings.PINECONE_REGION,
            ),
            deletion_protection="disabled",
            tags={"application": "vietlex-legal-rag"},
        )
        wait_for_index_ready(client, name)
    description = client.describe_index(name)
    dimension = int(_index_value(description, "dimension") or 0)
    metric = str(_index_value(description, "metric") or "").lower()
    if dimension != settings.DENSE_VECTOR_SIZE or metric != "dotproduct":
        raise RuntimeError(
            "Pinecone index schema is incompatible with the embedding model."
        )
    return client.index(name, grpc=True), not exists


def upload_record_batch(
    index: Any,
    settings: Settings,
    records: Iterable[dict[str, Any]],
) -> None:
    payload = list(records)
    if not payload:
        return
    for attempt in range(8):
        try:
            index.upsert(
                vectors=payload,
                namespace=settings.PINECONE_NAMESPACE,
                max_concurrency=1,
                show_progress=False,
            )
            return
        except Exception as error:
            text = str(error).casefold()
            retryable = any(
                marker in text
                for marker in ("429", "resource_exhausted", "timeout", "503")
            )
            if not retryable or attempt == 7:
                raise
            time.sleep(min(30.0, 2.0**attempt) + random.random())


def _namespace_count(stats: Any, namespace: str) -> int:
    namespaces = _index_value(stats, "namespaces") or {}
    details = namespaces.get(namespace) if hasattr(namespaces, "get") else None
    if details is None:
        return 0
    return int(
        _index_value(details, "vector_count")
        or _index_value(details, "record_count")
        or 0
    )


def verify_index(
    control: Any,
    index: Any,
    settings: Settings,
    *,
    expected_count: int,
) -> IndexVerification:
    description = control.describe_index(settings.PINECONE_INDEX_NAME)
    status = _index_value(description, "status")
    ready = _index_value(status, "ready") is True
    dense_size = int(_index_value(description, "dimension") or 0)
    stats = index.describe_index_stats()
    count = _namespace_count(stats, settings.PINECONE_NAMESPACE)
    if not ready or dense_size != settings.DENSE_VECTOR_SIZE:
        raise RuntimeError("Pinecone index is not ready or has wrong dimension.")
    if count != expected_count:
        raise RuntimeError(
            f"Pinecone vector count mismatch: expected {expected_count}, "
            f"got {count}."
        )
    return IndexVerification(
        index_name=settings.PINECONE_INDEX_NAME,
        namespace=settings.PINECONE_NAMESPACE,
        vector_count=count,
        dense_size=dense_size,
        ready=ready,
    )


def wait_for_vector_count(
    index: Any,
    settings: Settings,
    *,
    expected_count: int,
    timeout_seconds: float = 1_200.0,
) -> int:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        count = _namespace_count(
            index.describe_index_stats(),
            settings.PINECONE_NAMESPACE,
        )
        if count == expected_count:
            return count
        time.sleep(10.0)
    raise TimeoutError(
        "Pinecone namespace did not reach the expected vector count."
    )
