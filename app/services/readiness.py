from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any


async def build_readiness(
    settings: Any, mongo_ping: Callable[[], Awaitable[bool]]
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
        "mongodb": "not_configured",
    }
    online_only = bool(getattr(settings, "SERVERLESS_ONLINE_ONLY", False))
    if online_only:
        checks["content_store"] = "not_required"
        checks["legal_fts"] = "not_required"
        checks["online_retrieval"] = (
            "ready"
            if getattr(settings, "QDRANT_URL", None)
            and getattr(settings, "GOOGLE_CLOUD_PROJECT", None)
            else "not_configured"
        )
        checks["supabase_documents"] = (
            "ready"
            if getattr(settings, "SUPABASE_URL", None)
            and getattr(settings, "SUPABASE_PUBLISHABLE_KEY", None)
            else "not_configured"
        )
    if getattr(settings, "MONGO_URL", None):
        try:
            checks["mongodb"] = "ready" if await mongo_ping() else "unavailable"
        except Exception:
            checks["mongodb"] = "unavailable"
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
