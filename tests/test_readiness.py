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
        "runtime": {
            "retrieval_backend": "pinecone-v1",
            "google_cloud_calls_enabled": False,
            "vertex_qdrant_shadow_enabled": False,
            "pinecone_configured": False,
            "qdrant_configured": False,
            "vertex_project_configured": False,
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


@pytest.mark.asyncio
async def test_readiness_reports_explicit_runtime_backend(tmp_path: Path) -> None:
    from app.services.readiness import build_readiness

    result = await build_readiness(
        SimpleNamespace(
            CONTENT_STORE_PATH=tmp_path / "wrong-full.sqlite3",
            LEGAL_FTS_PATH=tmp_path / "wrong-full-fts.sqlite3",
            V3_CONTENT_STORE_PATH=tmp_path / "v3.sqlite3",
            V3_LEGAL_FTS_PATH=tmp_path / "v3-fts.sqlite3",
            MONGO_URL=None,
            USE_LEGACY_FREE_PIPELINE=False,
        ),
        mongo_ping=lambda: _async_value(False),
    )

    assert result["runtime"]["retrieval_backend"] == "vertex-qdrant-v3"
    assert result["runtime"]["google_cloud_calls_enabled"] is True
    assert result["runtime"]["content_store_path"].endswith("v3.sqlite3")


@pytest.mark.asyncio
async def test_free_switch_overrides_old_structural_selector(tmp_path: Path) -> None:
    from app.services.readiness import build_readiness

    result = await build_readiness(
        SimpleNamespace(
            CONTENT_STORE_PATH=tmp_path / "missing.sqlite3",
            LEGAL_FTS_PATH=tmp_path / "missing-fts.sqlite3",
            MONGO_URL=None,
            USE_LEGACY_FREE_PIPELINE=True,
            STRUCTURAL_BACKEND_ENABLED=True,
        ),
        mongo_ping=lambda: _async_value(False),
    )

    assert result["runtime"]["retrieval_backend"] == "pinecone-v1"
    assert result["runtime"]["google_cloud_calls_enabled"] is False


@pytest.mark.asyncio
async def test_online_only_readiness_does_not_require_local_corpus(tmp_path: Path) -> None:
    from app.services.readiness import build_readiness

    result = await build_readiness(
        SimpleNamespace(
            CONTENT_STORE_PATH=tmp_path / "missing.sqlite3",
            LEGAL_FTS_PATH=tmp_path / "missing-fts.sqlite3",
            V3_CONTENT_STORE_PATH=tmp_path / "missing-v3.sqlite3",
            V3_LEGAL_FTS_PATH=tmp_path / "missing-v3-fts.sqlite3",
            MONGO_URL="mongodb://configured",
            USE_LEGACY_FREE_PIPELINE=False,
            SERVERLESS_ONLINE_ONLY=True,
            QDRANT_URL="https://qdrant.example",
            GOOGLE_CLOUD_PROJECT="project-id",
        ),
        mongo_ping=lambda: _async_value(True),
    )

    assert result["status"] == "ready"
    assert result["checks"] == {
        "content_store": "not_required",
        "legal_fts": "not_required",
        "online_retrieval": "ready",
        "mongodb": "ready",
    }


async def _async_value(value: bool) -> bool:
    return value
