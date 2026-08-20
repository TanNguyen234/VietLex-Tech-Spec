from __future__ import annotations

import hashlib
import math
from typing import Any, Iterable

from app.services.vertex_ai import VertexAIProvider


PROBE_DIMENSIONS = (384, 768, 1024)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
        sum(value * value for value in right)
    )
    if denominator == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / denominator


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def run_dimension_probe(
    provider: VertexAIProvider | Any,
    *,
    query: str,
    document: str,
    document_title: str,
    dimensions: Iterable[int] = PROBE_DIMENSIONS,
    repeat_cosine_minimum: float = 0.999,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for dimension in dimensions:
        query_first = await provider.embed_query(
            query,
            output_dimensionality=dimension,
            task="question_answering",
        )
        query_repeat = await provider.embed_query(
            query,
            output_dimensionality=dimension,
            task="question_answering",
        )
        document_first = await provider.embed_document(
            document,
            title=document_title,
            output_dimensionality=dimension,
        )
        document_repeat = await provider.embed_document(
            document,
            title=document_title,
            output_dimensionality=dimension,
        )
        query_cosine = _cosine(query_first.values, query_repeat.values)
        document_cosine = _cosine(
            document_first.values,
            document_repeat.values,
        )
        metadata = query_first.metadata.to_dict()
        results.append(
            {
                "dimension": dimension,
                "status": (
                    "pass"
                    if query_cosine >= repeat_cosine_minimum
                    and document_cosine >= repeat_cosine_minimum
                    else "fail"
                ),
                "query_dimension": len(query_first.values),
                "document_dimension": len(document_first.values),
                "query_l2_norm": query_first.l2_norm,
                "document_l2_norm": document_first.l2_norm,
                "query_repeat_cosine": query_cosine,
                "document_repeat_cosine": document_cosine,
                "latency_ms": {
                    "query_first": query_first.metadata.latency_ms,
                    "query_repeat": query_repeat.metadata.latency_ms,
                    "document_first": document_first.metadata.latency_ms,
                    "document_repeat": document_repeat.metadata.latency_ms,
                },
                "provider": metadata["provider"],
                "model": metadata["model"],
                "project": metadata["project"],
                "location": metadata["location"],
            }
        )
    return {
        "status": (
            "pass" if all(item["status"] == "pass" for item in results) else "fail"
        ),
        "dimensions": results,
        "query_sha256": _sha256(query),
        "document_sha256": _sha256(document),
        "repeat_cosine_minimum": repeat_cosine_minimum,
        "vector_write_attempted": False,
        "production_retrieval_changed": False,
    }
