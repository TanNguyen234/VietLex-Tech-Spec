from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any


async def build_readiness(
    settings: Any, mongo_ping: Callable[[], Awaitable[bool]]
) -> dict[str, Any]:
    content_path = Path(settings.CONTENT_STORE_PATH)
    fts_path = Path(settings.LEGAL_FTS_PATH)
    checks = {
        "content_store": "ready" if content_path.is_file() else "missing",
        "legal_fts": "ready" if fts_path.is_file() else "missing",
        "mongodb": "not_configured",
    }
    if getattr(settings, "MONGO_URL", None):
        try:
            checks["mongodb"] = "ready" if await mongo_ping() else "unavailable"
        except Exception:
            checks["mongodb"] = "unavailable"
    status = "ready" if all(value == "ready" for value in checks.values()) else "not_ready"
    return {"status": status, "checks": checks}
