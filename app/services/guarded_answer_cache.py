"""Fast, zero-RPC, bounded TTL cache for input- and output-guardrail-approved answers."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict, dataclass
import hashlib
import json
import os
import re
import threading
import time
from typing import Any

from app.config import get_settings
from app.services.chat_intent import deterministic_guidance
from app.services.official_search_plan import DEEP_READING
from app.services.runtime_identity import runtime_identity
from app.services.semantic_cache import (
    CACHE_SCHEMA_VERSION,
    CACHE_TTL_SECONDS,
    EVIDENCE_SELECTION_VERSION,
    _contains_official_external_context,
    _normalize_query,
    deserialize_evidence,
    evidence_sha256,
    is_cacheable_query,
    serialize_evidence,
)


@dataclass(frozen=True)
class GuardedAnswerCacheHit:
    response: str
    contexts: list[str]
    observed_provider: str | None = None
    observed_model: str | None = None
    evidence_sha256: str = ""
    pipeline_revision: str = ""


@dataclass(frozen=True)
class _GuardedCacheEntry:
    normalized_query: str
    response: str
    evidence_json: str
    evidence_sha256: str
    corpus_revision: str
    pipeline_revision: str
    route_key: str
    request_status: str
    input_safe: bool
    output_safe: bool
    observed_provider: str | None
    observed_model: str | None
    expires_at: float


def is_guarded_answer_cache_enabled(active_settings: Any = None) -> bool:
    s = active_settings if active_settings is not None else get_settings()
    explicit = getattr(s, "GUARDED_ANSWER_CACHE_ENABLED", None)
    if isinstance(explicit, bool):
        return explicit
    if getattr(s, "APP_ENV", None) == "test":
        return False
    if "PYTEST_CURRENT_TEST" in os.environ:
        return False
    return True


def is_guarded_cacheable_query(user_query: str) -> bool:
    if not isinstance(user_query, str) or not user_query.strip():
        return False
    return deterministic_guidance(user_query) is None and is_cacheable_query(user_query)


def guarded_cache_pipeline_revision(active_settings: Any = None) -> str:
    s = active_settings if active_settings is not None else get_settings()
    identity = runtime_identity(s)
    if any(
        not isinstance(identity.get(key), str)
        or not re.fullmatch(r"[a-f0-9]{64}", identity[key])
        for key in ("app_source_sha256", "configuration_sha256")
    ):
        raise ValueError("guarded_cache_runtime_identity_unavailable")
    contract = {
        "app_source_sha256": identity["app_source_sha256"],
        "configuration_sha256": identity["configuration_sha256"],
        "evidence_selection_version": EVIDENCE_SELECTION_VERSION,
        "schema": CACHE_SCHEMA_VERSION,
        "legacy_free_pipeline": getattr(s, "USE_LEGACY_FREE_PIPELINE", False),
        "dense_model": getattr(s, "DENSE_INFERENCE_MODEL", ""),
        "dense_backend": getattr(s, "DENSE_EMBEDDING_BACKEND", ""),
        "structural_enabled": getattr(s, "STRUCTURAL_BACKEND_ENABLED", False),
        "cross_lane_final_rerank_enabled": getattr(
            s, "CROSS_LANE_FINAL_RERANK_ENABLED", False
        ),
        "structural_collection": getattr(s, "STRUCTURAL_COLLECTION_NAME", ""),
        "structural_text_version": getattr(s, "STRUCTURAL_DOCUMENT_TEXT_VERSION", ""),
        "structural_query_version": getattr(
            s, "STRUCTURAL_QUERY_INSTRUCTION_VERSION", ""
        ),
        "structural_reranker": getattr(s, "STRUCTURAL_RERANKER_MODE", ""),
        "vertex_qdrant_collection": getattr(s, "VERTEX_QDRANT_COLLECTION_NAME", ""),
        "vertex_embedding_model": getattr(s, "VERTEX_EMBEDDING_MODEL", ""),
        "vertex_embedding_dimension": getattr(s, "VERTEX_QDRANT_VECTOR_SIZE", 1024),
        "legacy_reranker": getattr(s, "QDRANT_RERANK_MODEL", ""),
        "fallback_reranker": getattr(s, "PINECONE_RERANK_MODEL", ""),
        "answer_model": getattr(s, "VERTEX_LLM_MODEL", ""),
        "default_llm_provider": getattr(s, "DEFAULT_LLM_PROVIDER", "auto"),
        "answer_prompt_version": getattr(s, "ANSWER_PROMPT_VERSION", ""),
        "chat_official_web_supplement_enabled": getattr(
            s, "CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED", True
        ),
        "tavily_search_enabled": bool(getattr(s, "TAVILY_SEARCH_ENABLED", False)),
        "tavily_extract_enabled": bool(getattr(s, "TAVILY_EXTRACT_ENABLED", False)),
        "final_evidence_limit": getattr(s, "FINAL_EVIDENCE_LIMIT", 3),
        "context_limit": getattr(s, "LLM_CONTEXT_MAX_TOKENS", 720),
        "official_deep_reading_enabled": getattr(
            s, "CHAT_OFFICIAL_DEEP_READING_ENABLED", False
        ),
        "instrument_hypothesis_enabled": getattr(
            s, "CHAT_INSTRUMENT_HYPOTHESIS_ENABLED", False
        ),
        "official_deep_profile": asdict(DEEP_READING),
    }
    encoded = json.dumps(
        contract,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class GuardedAnswerCache:
    def __init__(
        self,
        *,
        max_entries: int = 256,
        ttl_seconds: float = CACHE_TTL_SECONDS,
    ) -> None:
        self._max_entries = max(1, int(max_entries))
        self._ttl_seconds = float(ttl_seconds)
        self._entries: OrderedDict[tuple[str, str, str, str], _GuardedCacheEntry] = (
            OrderedDict()
        )
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    @staticmethod
    def _build_key(
        user_query: str,
        *,
        settings: Any,
        route_key: str,
    ) -> tuple[tuple[str, str, str, str], str]:
        normalized = _normalize_query(user_query)
        query_sha = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        corpus_rev = str(getattr(settings, "DATASET_REVISION", ""))
        pipeline_rev = guarded_cache_pipeline_revision(settings)
        return (query_sha, corpus_rev, pipeline_rev, route_key), normalized

    def get(
        self,
        user_query: str,
        *,
        settings: Any = None,
        route_key: str = "auto:",
    ) -> GuardedAnswerCacheHit | None:
        active_settings = settings if settings is not None else get_settings()
        if not is_guarded_cacheable_query(user_query):
            return None
        try:
            cache_key, normalized = self._build_key(
                user_query,
                settings=active_settings,
                route_key=route_key,
            )
        except Exception:
            return None

        now = time.time()
        with self._lock:
            entry = self._entries.get(cache_key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                self._entries.pop(cache_key, None)
                return None
            if (
                entry.normalized_query != normalized
                or entry.request_status != "ok"
                or entry.input_safe is not True
                or entry.output_safe is not True
                or not entry.response.strip()
                or entry.evidence_sha256 != evidence_sha256(entry.evidence_json)
            ):
                self._entries.pop(cache_key, None)
                return None
            contexts = deserialize_evidence(entry.evidence_json)
            if contexts is None or _contains_official_external_context(contexts):
                self._entries.pop(cache_key, None)
                return None
            self._entries.move_to_end(cache_key)
            return GuardedAnswerCacheHit(
                response=entry.response,
                contexts=contexts,
                observed_provider=entry.observed_provider,
                observed_model=entry.observed_model,
                evidence_sha256=entry.evidence_sha256,
                pipeline_revision=entry.pipeline_revision,
            )

    def put(
        self,
        user_query: str,
        bot_response: str,
        contexts: list[str],
        *,
        settings: Any = None,
        route_key: str = "auto:",
        input_safe: bool,
        output_safe: bool,
        request_status: str,
        observed_provider: str | None = None,
        observed_model: str | None = None,
    ) -> bool:
        active_settings = settings if settings is not None else get_settings()
        if (
            request_status != "ok"
            or input_safe is not True
            or output_safe is not True
            or not isinstance(bot_response, str)
            or not bot_response.strip()
            or not isinstance(contexts, list)
            or not contexts
            or _contains_official_external_context(contexts)
            or not is_guarded_cacheable_query(user_query)
        ):
            return False
        try:
            cache_key, normalized = self._build_key(
                user_query,
                settings=active_settings,
                route_key=route_key,
            )
            evidence_json = serialize_evidence(contexts)
            if deserialize_evidence(evidence_json) is None:
                return False
            sha = evidence_sha256(evidence_json)
        except Exception:
            return False

        entry = _GuardedCacheEntry(
            normalized_query=normalized,
            response=bot_response,
            evidence_json=evidence_json,
            evidence_sha256=sha,
            corpus_revision=cache_key[1],
            pipeline_revision=cache_key[2],
            route_key=route_key,
            request_status="ok",
            input_safe=True,
            output_safe=True,
            observed_provider=observed_provider,
            observed_model=observed_model,
            expires_at=time.time() + self._ttl_seconds,
        )
        with self._lock:
            self._entries[cache_key] = entry
            self._entries.move_to_end(cache_key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
        return True


guarded_answer_cache = GuardedAnswerCache()
