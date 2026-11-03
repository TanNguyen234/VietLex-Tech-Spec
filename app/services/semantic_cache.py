from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Optional

import logfire

from app.config import get_settings
from app.ingestion.qdrant_inference import embed_query
from app.services.chat_official_supplement import _current_applicability_intent
from app.services.conversation_context import is_explicit_followup
from app.services.official_search_plan import DEEP_READING
from app.services.runtime_identity import runtime_identity
from app.services.evidence_presenter import (
    TrustedOfficialEvidenceContext,
    deserialize_evidence_context,
    serialize_evidence_context,
)
from app.services.clients import (
    get_pinecone_client,
    get_pinecone_index,
    get_qdrant_inference_client,
)


settings = get_settings()
CACHE_SCHEMA_VERSION = "vietlex-grounded-cache-v7-expiry"
EVIDENCE_SELECTION_VERSION = "scoped-primary-law-followup-v6"
CACHE_TTL_SECONDS = 24 * 60 * 60
_ENGLISH_TIME_SENSITIVE_CUE = re.compile(
    r"\b(?:as of|current(?:ly)?|latest|today|in force|still effective|effective date|up to date)\b",
    re.IGNORECASE,
)


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
    normalized = _normalize_query(user_query)
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{revision}\n{pipeline_revision}\n{normalized}",
        )
    )


def _normalize_query(query: str) -> str:
    return " ".join(query.casefold().split())


def is_cacheable_query(user_query: str) -> bool:
    """Keep current-law and context-dependent questions on fresh retrieval."""
    return not is_explicit_followup(user_query) and not _current_applicability_intent(user_query) and not bool(
        _ENGLISH_TIME_SENSITIVE_CUE.search(user_query)
    ) and not bool(re.search(r"\b(?:tại ngày|tính đến)\s+\d", user_query, re.I))


def _contains_official_external_context(contexts: list[str]) -> bool:
    return any(isinstance(context, TrustedOfficialEvidenceContext) for context in contexts)


def _cache_entry_is_fresh(payload: dict[str, object]) -> bool:
    expires_at = payload.get("expires_at")
    return (
        isinstance(expires_at, (int, float))
        and not isinstance(expires_at, bool)
        and expires_at > time.time()
    )


def semantic_cache_pipeline_revision(*, identity: dict | None = None) -> str:
    """Use the loaded identity online; explicit observed snapshots support offline comparison."""
    identity = runtime_identity(settings) if identity is None else identity
    if any(not isinstance(identity.get(key), str)
           or not re.fullmatch(r"[a-f0-9]{64}", identity[key])
           for key in ("app_source_sha256", "configuration_sha256")):
        raise ValueError("semantic_cache_runtime_identity_unavailable")
    contract = {
        "app_source_sha256": identity["app_source_sha256"],
        "configuration_sha256": identity["configuration_sha256"],
        "evidence_selection_version": EVIDENCE_SELECTION_VERSION,
        "schema": CACHE_SCHEMA_VERSION,
        "legacy_free_pipeline": settings.USE_LEGACY_FREE_PIPELINE,
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
        "vertex_qdrant_collection": settings.VERTEX_QDRANT_COLLECTION_NAME,
        "vertex_embedding_model": settings.VERTEX_EMBEDDING_MODEL,
        "vertex_embedding_dimension": settings.VERTEX_QDRANT_VECTOR_SIZE,
        "legacy_reranker": settings.QDRANT_RERANK_MODEL,
        "fallback_reranker": settings.PINECONE_RERANK_MODEL,
        "answer_model": settings.VERTEX_LLM_MODEL,
        "answer_prompt_version": settings.ANSWER_PROMPT_VERSION,
        "chat_official_web_supplement_enabled": (
            settings.CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED
        ),
        "final_evidence_limit": settings.FINAL_EVIDENCE_LIMIT,
        "context_limit": settings.LLM_CONTEXT_MAX_TOKENS,
        "official_deep_reading_enabled": getattr(settings, "CHAT_OFFICIAL_DEEP_READING_ENABLED", False),
        "official_deep_profile": asdict(DEEP_READING),
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
    serialized = [serialize_evidence_context(context) for context in contexts]
    return json.dumps(serialized, ensure_ascii=False, separators=(",", ":"))


def deserialize_evidence(evidence_json: str) -> list[str] | None:
    try:
        serialized = json.loads(evidence_json)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(serialized, list):
        return None
    contexts = [deserialize_evidence_context(item) for item in serialized]
    if not contexts or any(
        not isinstance(context, str) or not context.strip() for context in contexts
    ):
        return None
    return contexts


def evidence_sha256(evidence_json: str) -> str:
    return hashlib.sha256(evidence_json.encode("utf-8")).hexdigest()


@logfire.instrument(
    "Ensure revision-aware semantic cache schema", extract_args=False
)
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


@logfire.instrument("Check semantic cache", extract_args=False)
async def check_semantic_cache(
    user_query: str,
) -> Optional[SemanticCacheHit]:
    if not is_cacheable_query(user_query):
        return None
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
            or not _cache_entry_is_fresh(payload)
        ):
            return None
        cached_query = payload.get("user_query")
        if not isinstance(cached_query, str) or _normalize_query(cached_query) != _normalize_query(user_query):
            return None
        response_text = payload.get("bot_response")
        evidence_json = payload.get("evidence_json")
        if not isinstance(response_text, str) or not response_text.strip():
            return None
        if not isinstance(evidence_json, str):
            return None
        if payload.get("evidence_sha256") != evidence_sha256(evidence_json):
            return None
        contexts = deserialize_evidence(evidence_json)
        if contexts is None or _contains_official_external_context(contexts):
            return None
        return SemanticCacheHit(response=response_text, contexts=contexts)
    except Exception as error:
        logfire.error(
            "Semantic cache lookup failed",
            error_kind=type(error).__name__,
        )
        return None


@logfire.instrument("Save semantic cache", extract_args=False)
async def save_to_semantic_cache(
    user_query: str,
    bot_response: str,
    contexts: list[str],
) -> None:
    if (
        not is_cacheable_query(user_query)
        or not contexts
        or not bot_response.strip()
        or _contains_official_external_context(contexts)
    ):
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
                        "expires_at": int(time.time()) + CACHE_TTL_SECONDS,
                        "evidence_json": evidence_json,
                        "evidence_sha256": evidence_sha256(evidence_json),
                    },
                }
            ],
            namespace=settings.PINECONE_CACHE_NAMESPACE,
        )
    except Exception as error:
        logfire.error(
            "Semantic cache save failed",
            error_kind=type(error).__name__,
        )
