from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Optional

import logfire

from app.config import get_settings
from app.ingestion.qdrant_inference import embed_query
from app.services.clients import (
    get_pinecone_client,
    get_pinecone_index,
    get_qdrant_inference_client,
)


settings = get_settings()
CACHE_SCHEMA_VERSION = "vietlex-grounded-cache-v5-explicit-location"


@dataclass(frozen=True)
class SemanticCacheHit:
    response: str
    contexts: list[str]


def _embedding_client():
    return get_qdrant_inference_client()


def semantic_cache_point_id(
    user_query: str,
    revision: str,
    pipeline_revision: str = CACHE_SCHEMA_VERSION,
) -> str:
    normalized = " ".join(user_query.casefold().split())
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{revision}\n{pipeline_revision}\n{normalized}",
        )
    )


def semantic_cache_pipeline_revision() -> str:
    contract = {
        "schema": CACHE_SCHEMA_VERSION,
        "dense_model": settings.DENSE_INFERENCE_MODEL,
        "dense_backend": settings.DENSE_EMBEDDING_BACKEND,
        "structural_enabled": settings.STRUCTURAL_BACKEND_ENABLED,
        "cross_lane_final_rerank_enabled": (
            settings.CROSS_LANE_FINAL_RERANK_ENABLED
        ),
        "structural_collection": settings.STRUCTURAL_COLLECTION_NAME,
        "structural_text_version": settings.STRUCTURAL_DOCUMENT_TEXT_VERSION,
        "structural_query_version": settings.STRUCTURAL_QUERY_INSTRUCTION_VERSION,
        "structural_reranker": settings.STRUCTURAL_RERANKER_MODE,
        "legacy_reranker": settings.QDRANT_RERANK_MODEL,
        "fallback_reranker": settings.PINECONE_RERANK_MODEL,
        "answer_model": settings.VERTEX_LLM_MODEL,
        "answer_prompt_version": settings.ANSWER_PROMPT_VERSION,
        "final_evidence_limit": settings.FINAL_EVIDENCE_LIMIT,
        "context_limit": settings.LLM_CONTEXT_MAX_TOKENS,
    }
    encoded = json.dumps(
        contract,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def cache_revision_filter(
    revision: str,
    pipeline_revision: str,
) -> dict[str, object]:
    return {
        "$and": [
            {"corpus_revision": {"$eq": revision}},
            {"pipeline_revision": {"$eq": pipeline_revision}},
            {"request_status": {"$eq": "ok"}},
        ]
    }


def serialize_evidence(contexts: list[str]) -> str:
    return json.dumps(contexts, ensure_ascii=False, separators=(",", ":"))


def evidence_sha256(evidence_json: str) -> str:
    return hashlib.sha256(evidence_json.encode("utf-8")).hexdigest()


@logfire.instrument("Ensure revision-aware semantic cache schema")
async def ensure_semantic_cache_collection() -> None:
    client = get_pinecone_client()
    exists = await asyncio.to_thread(
        client.has_index,
        settings.PINECONE_INDEX_NAME,
    )
    if not exists:
        raise RuntimeError(
            "Pinecone index is not initialized; run full ingestion first."
        )


@logfire.instrument("Check semantic cache")
async def check_semantic_cache(
    user_query: str,
) -> Optional[SemanticCacheHit]:
    try:
        pipeline_revision = semantic_cache_pipeline_revision()
        vector = await asyncio.to_thread(
            embed_query,
            _embedding_client(),
            settings,
            user_query,
        )
        response = await asyncio.to_thread(
            get_pinecone_index().query,
            namespace=settings.PINECONE_CACHE_NAMESPACE,
            vector=vector,
            top_k=1,
            include_metadata=True,
            include_values=False,
            filter=cache_revision_filter(
                settings.DATASET_REVISION,
                pipeline_revision,
            ),
        )
        matches = (
            response.get("matches", [])
            if isinstance(response, dict)
            else getattr(response, "matches", [])
        )
        if not matches:
            return None
        best_hit = matches[0]
        score = (
            best_hit.get("score", 0.0)
            if isinstance(best_hit, dict)
            else getattr(best_hit, "score", 0.0)
        )
        if float(score) < 0.96:
            return None
        payload = (
            best_hit.get("metadata", {})
            if isinstance(best_hit, dict)
            else getattr(best_hit, "metadata", {})
        )
        if (
            payload.get("corpus_revision")
            != settings.DATASET_REVISION
            or payload.get("pipeline_revision") != pipeline_revision
            or payload.get("request_status") != "ok"
        ):
            return None
        response_text = payload.get("bot_response")
        evidence_json = payload.get("evidence_json")
        if not isinstance(response_text, str) or not response_text.strip():
            return None
        if not isinstance(evidence_json, str):
            return None
        if payload.get("evidence_sha256") != evidence_sha256(evidence_json):
            return None
        contexts = json.loads(evidence_json)
        if not isinstance(contexts, list) or not contexts:
            return None
        if not all(isinstance(item, str) and item.strip() for item in contexts):
            return None
        return SemanticCacheHit(response=response_text, contexts=contexts)
    except Exception as error:
        logfire.error(
            "Semantic cache lookup failed: {error}",
            error=str(error),
        )
        return None


@logfire.instrument("Save semantic cache")
async def save_to_semantic_cache(
    user_query: str,
    bot_response: str,
    contexts: list[str],
) -> None:
    if not contexts or not bot_response.strip():
        return
    try:
        pipeline_revision = semantic_cache_pipeline_revision()
        evidence_json = serialize_evidence(contexts)
        vector = await asyncio.to_thread(
            embed_query,
            _embedding_client(),
            settings,
            user_query,
        )
        await asyncio.to_thread(
            get_pinecone_index().upsert,
            vectors=[
                {
                    "id": semantic_cache_point_id(
                        user_query,
                        settings.DATASET_REVISION,
                        pipeline_revision,
                    ),
                    "values": vector,
                    "metadata": {
                        "user_query": user_query,
                        "bot_response": bot_response,
                        "corpus_revision": settings.DATASET_REVISION,
                        "pipeline_revision": pipeline_revision,
                        "request_status": "ok",
                        "evidence_json": evidence_json,
                        "evidence_sha256": evidence_sha256(evidence_json),
                    },
                }
            ],
            namespace=settings.PINECONE_CACHE_NAMESPACE,
        )
    except Exception as error:
        logfire.error(
            "Semantic cache save failed: {error}",
            error=str(error),
        )
