from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx

from app.config import system_ssl_context


logger = logging.getLogger(__name__)


async def _run_probe(
    name: str, probe: Callable[[], Awaitable[bool]] | None
) -> str:
    if probe is None:
        return "not_probed"
    try:
        return "ready" if await probe() else "unavailable"
    except Exception as error:
        logger.warning(
            "readiness_dependency_probe_failed",
            extra={"dependency": name, "error_type": type(error).__name__},
        )
        return "unavailable"


async def _ping_qdrant_collection(settings: Any, collection: str) -> bool:
    def ping() -> bool:
        with httpx.Client(
            verify=system_ssl_context(), timeout=httpx.Timeout(3.0)
        ) as client:
            response = client.get(
                f"{settings.QDRANT_URL.rstrip('/')}/collections/{collection}",
                headers={"api-key": settings.QDRANT_API_KEY},
            )
            response.raise_for_status()
            payload = response.json()
        result = payload.get("result") if isinstance(payload, dict) else None
        return bool(
            isinstance(result, dict)
            and result.get("status") == "green"
            and type(result.get("points_count")) is int
            and result["points_count"] > 0
        )

    return await asyncio.to_thread(ping)


async def _ping_supabase_documents(settings: Any) -> bool:
    from app.services.legal_browser import SupabaseLegalStore

    def ping() -> bool:
        with httpx.Client(
            verify=system_ssl_context(), timeout=httpx.Timeout(3.0)
        ) as client:
            store = SupabaseLegalStore(
                url=settings.SUPABASE_URL,
                publishable_key=settings.SUPABASE_PUBLISHABLE_KEY,
                client=client,
            )
            return store.count_documents() > 0

    return await asyncio.to_thread(ping)


async def _ping_body_search(settings: Any) -> bool:
    from app.services.legal_browser import SupabaseLegalStore

    def ping() -> bool:
        with httpx.Client(
            verify=system_ssl_context(), timeout=httpx.Timeout(3.0)
        ) as supabase_client:
            store = SupabaseLegalStore(
                url=settings.SUPABASE_URL,
                publishable_key=settings.SUPABASE_PUBLISHABLE_KEY,
                client=supabase_client,
            )
            if settings.QDRANT_FULL_DOC_BODY_SEARCH_ENABLED:
                from app.services.qdrant_full_doc_body_search import (
                    QdrantFullDocBodySearch,
                )

                with httpx.Client(
                    verify=system_ssl_context(), timeout=httpx.Timeout(3.0)
                ) as qdrant_client:
                    return bool(
                        QdrantFullDocBodySearch(
                            url=settings.QDRANT_URL,
                            api_key=settings.QDRANT_API_KEY,
                            collection=settings.QDRANT_FULL_DOC_BODY_COLLECTION,
                            store=store,
                            client=qdrant_client,
                        ).coverage()["document_count"]
                    )
            from app.services.full_doc_body_search import SupabaseFullDocBodySearch

            return bool(
                SupabaseFullDocBodySearch(
                    url=settings.SUPABASE_URL,
                    publishable_key=settings.SUPABASE_PUBLISHABLE_KEY,
                    client=store._client,
                ).coverage()["document_count"]
            )

    return await asyncio.to_thread(ping)


async def _ping_pinecone_namespace(settings: Any) -> bool:
    def value(item: Any, key: str) -> Any:
        return item.get(key) if isinstance(item, dict) else getattr(item, key, None)

    def ping() -> bool:
        from app.services.clients import get_pinecone_index

        stats = get_pinecone_index().describe_index_stats()
        namespaces = value(stats, "namespaces") or {}
        namespace = value(namespaces, settings.PINECONE_NAMESPACE)
        count = value(namespace, "vector_count")
        return type(count) is int and count > 0

    return await asyncio.to_thread(ping)

async def build_readiness(
    settings: Any,
    mongo_ping: Callable[[], Awaitable[bool]],
    *,
    online_retrieval_ping: Callable[[], Awaitable[bool]] | None = None,
    supabase_documents_ping: Callable[[], Awaitable[bool]] | None = None,
    body_search_ping: Callable[[], Awaitable[bool]] | None = None,
) -> dict[str, Any]:
    pipeline_switch = getattr(settings, "USE_LEGACY_FREE_PIPELINE", None)
    use_v3_data = pipeline_switch is False
    content_path = Path(
        settings.V3_CONTENT_STORE_PATH
        if use_v3_data
        else settings.CONTENT_STORE_PATH
    )
    fts_path = Path(
        settings.V3_LEGAL_FTS_PATH
        if use_v3_data
        else settings.LEGAL_FTS_PATH
    )
    checks = {
        "content_store": "ready" if content_path.is_file() else "missing",
        "legal_fts": "ready" if fts_path.is_file() else "missing",
        "mongodb": (
            "not_required"
            if getattr(settings, "APP_ENV", None) == "development"
            else "not_configured"
        ),
    }
    pending_probes: dict[str, Awaitable[str]] = {}
    if (
        getattr(settings, "APP_ENV", None) != "development"
        and getattr(settings, "MONGO_URL", None)
    ):
        pending_probes["mongodb"] = _run_probe("mongodb", mongo_ping)

    online_only = bool(getattr(settings, "SERVERLESS_ONLINE_ONLY", False))
    if online_only:
        if pipeline_switch is False:
            checks["content_store"] = "not_required"
            checks["legal_fts"] = "not_required"
        if pipeline_switch is True:
            retrieval_configured = bool(
                getattr(settings, "pinecone_api_key", None)
            )
            retrieval_probe = online_retrieval_ping or (
                lambda: _ping_pinecone_namespace(settings)
            )
        else:
            retrieval_configured = bool(
                getattr(settings, "QDRANT_URL", None)
                and getattr(settings, "QDRANT_API_KEY", None)
                and getattr(settings, "GOOGLE_CLOUD_PROJECT", None)
                and getattr(settings, "VERTEX_QDRANT_COLLECTION_NAME", None)
            )
            retrieval_probe = online_retrieval_ping or (
                lambda: _ping_qdrant_collection(
                    settings, settings.VERTEX_QDRANT_COLLECTION_NAME
                )
            )
        if retrieval_configured:
            pending_probes["online_retrieval"] = _run_probe(
                "online_retrieval", retrieval_probe
            )
        else:
            checks["online_retrieval"] = "not_configured"

        supabase_configured = bool(
            getattr(settings, "SUPABASE_URL", None)
            and getattr(settings, "SUPABASE_PUBLISHABLE_KEY", None)
        )
        if supabase_configured:
            pending_probes["supabase_documents"] = _run_probe(
                "supabase_documents",
                supabase_documents_ping
                or (lambda: _ping_supabase_documents(settings)),
            )
        else:
            checks["supabase_documents"] = "not_configured"

        body_search_enabled = bool(
            getattr(settings, "QDRANT_FULL_DOC_BODY_SEARCH_ENABLED", False)
            or getattr(settings, "SUPABASE_BODY_SEARCH_ENABLED", False)
        )
        body_search_configured = bool(
            supabase_configured
            and (
                (
                    getattr(settings, "QDRANT_FULL_DOC_BODY_SEARCH_ENABLED", False)
                    and getattr(settings, "QDRANT_URL", None)
                    and getattr(settings, "QDRANT_API_KEY", None)
                    and getattr(settings, "QDRANT_FULL_DOC_BODY_COLLECTION", None)
                )
                or (
                    getattr(settings, "SUPABASE_BODY_SEARCH_ENABLED", False)
                )
            )
        )
        if not body_search_enabled:
            checks["body_search_index"] = "not_required"
        elif body_search_configured:
            pending_probes["body_search_index"] = _run_probe(
                "body_search_index",
                body_search_ping or (lambda: _ping_body_search(settings)),
            )
        else:
            checks["body_search_index"] = "not_configured"
    if pending_probes:
        statuses = await asyncio.gather(*pending_probes.values())
        checks.update(dict(zip(pending_probes, statuses)))
    acceptable = {"ready", "not_required"}
    status = (
        "ready"
        if all(value in acceptable for value in checks.values())
        else "not_ready"
    )
    if pipeline_switch is False:
        backend = "vertex-qdrant-v3"
    elif pipeline_switch is True:
        backend = "pinecone-v1"
    elif getattr(settings, "STRUCTURAL_BACKEND_ENABLED", False):
        backend = "qdrant-v2-parallel"
    else:
        backend = "pinecone-v1"
    return {
        "status": status,
        "checks": checks,
        "runtime": {
            "retrieval_backend": backend,
            "google_cloud_calls_enabled": pipeline_switch is False,
            **({"serverless_online_only": True} if online_only else {}),
            **(
                {"content_store_path": str(content_path)}
                if use_v3_data
                else {}
            ),
            "vertex_qdrant_shadow_enabled": bool(
                getattr(settings, "VERTEX_QDRANT_SHADOW_ENABLED", False)
            ),
            "pinecone_configured": bool(
                getattr(settings, "pinecone_api_key", None)
            ),
            "qdrant_configured": bool(getattr(settings, "QDRANT_URL", None)),
            "vertex_project_configured": bool(
                getattr(settings, "GOOGLE_CLOUD_PROJECT", None)
            ),
        },
    }
