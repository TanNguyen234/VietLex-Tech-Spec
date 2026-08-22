from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_readiness_reports_each_dependency_without_provider_calls(tmp_path: Path) -> None:
    from app.services.readiness import build_readiness

    content = tmp_path / "content.sqlite3"
    fts = tmp_path / "fts.sqlite3"
    content.write_bytes(b"sqlite")
    fts.write_bytes(b"sqlite")

    result = await build_readiness(
        SimpleNamespace(
            CONTENT_STORE_PATH=content,
            LEGAL_FTS_PATH=fts,
            MONGO_URL="mongodb://configured",
        ),
        mongo_ping=lambda: _async_value(True),
    )

    assert result == {
        "status": "ready",
        "checks": {
            "content_store": "ready",
            "legal_fts": "ready",
            "mongodb": "ready",
        },
    }


@pytest.mark.asyncio
async def test_readiness_fails_closed_for_missing_store_and_database(tmp_path: Path) -> None:
    from app.services.readiness import build_readiness

    result = await build_readiness(
        SimpleNamespace(
            CONTENT_STORE_PATH=tmp_path / "missing.sqlite3",
            LEGAL_FTS_PATH=tmp_path / "missing-fts.sqlite3",
            MONGO_URL=None,
        ),
        mongo_ping=lambda: _async_value(False),
    )

    assert result["status"] == "not_ready"
    assert result["checks"] == {
        "content_store": "missing",
        "legal_fts": "missing",
        "mongodb": "not_configured",
    }


async def _async_value(value: bool) -> bool:
    return value
