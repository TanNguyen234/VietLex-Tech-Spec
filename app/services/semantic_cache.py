from __future__ import annotations

import asyncio
import uuid
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


def _embedding_client():
    return get_qdrant_inference_client()


def semantic_cache_point_id(
    user_query: str,
    revision: str,
) -> str:
    normalized = " ".join(user_query.casefold().split())
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{revision}\n{normalized}",
        )
    )


def cache_revision_filter(revision: str) -> dict[str, object]:
    return {"corpus_revision": {"$eq": revision}}


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
) -> Optional[str]:
    try:
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
            filter=cache_revision_filter(settings.DATASET_REVISION),
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
        ):
            return None
        return payload.get("bot_response")
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
) -> None:
    try:
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
                    ),
                    "values": vector,
                    "metadata": {
                        "user_query": user_query,
                        "bot_response": bot_response,
                        "corpus_revision": settings.DATASET_REVISION,
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
