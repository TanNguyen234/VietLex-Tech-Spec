from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_development_startup_skips_persistent_provider_initialization(monkeypatch):
    import app.main as main
    import app.services.semantic_cache as semantic_cache

    monkeypatch.setattr(main.settings, "APP_ENV", "development")
    monkeypatch.setattr(main.settings, "PUBLIC_NEMO_DEFAULT_ENABLED", False)
    init_db = AsyncMock()
    ensure_cache = AsyncMock()
    monkeypatch.setattr(main, "init_db", init_db)
    monkeypatch.setattr(semantic_cache, "ensure_semantic_cache_collection", ensure_cache)

    await main.startup_event()

    init_db.assert_not_awaited()
    ensure_cache.assert_not_awaited()


@pytest.mark.asyncio
async def test_production_startup_keeps_mongo_and_cache_initialization(monkeypatch):
    import app.main as main
    import app.services.semantic_cache as semantic_cache

    monkeypatch.setattr(main.settings, "APP_ENV", "production")
    monkeypatch.setattr(main.settings, "PUBLIC_NEMO_DEFAULT_ENABLED", False)
    init_db = AsyncMock()
    ensure_cache = AsyncMock()
    monkeypatch.setattr(main, "init_db", init_db)
    monkeypatch.setattr(semantic_cache, "ensure_semantic_cache_collection", ensure_cache)

    await main.startup_event()

    init_db.assert_awaited_once()
    ensure_cache.assert_awaited_once()


def test_development_database_guard_never_constructs_motor(monkeypatch):
    import app.database as database

    monkeypatch.setattr(database.settings, "APP_ENV", "development")
    monkeypatch.setattr(database.settings, "MONGO_URL", "mongodb://must-not-connect")
    monkeypatch.setattr(database, "client", None)
    monkeypatch.setattr(database, "db", None)

    with patch("app.database.AsyncIOMotorClient") as motor:
        with pytest.raises(RuntimeError, match="online_persistence_required"):
            database.get_db()

    motor.assert_not_called()


@pytest.mark.asyncio
async def test_development_chat_session_and_interaction_are_not_persisted(monkeypatch):
    import app.database as database

    monkeypatch.setattr(database.settings, "APP_ENV", "development")
    get_db = Mock(side_effect=AssertionError("local chat must not use Mongo"))
    monkeypatch.setattr(database, "get_db", get_db)

    session = await database.create_session("local-session", "Local chat")
    interaction = await database.log_interaction(
        "local-trace", "query", "answer", [], False, session_id="local-session"
    )

    assert session["session_id"] == "local-session"
    assert interaction["trace_id"] == "local-trace"
    assert await database.get_sessions("local-client") == []
    assert await database.get_session_messages("local-session", "local-client") == []
    get_db.assert_not_called()


@pytest.mark.asyncio
async def test_local_auth_cookie_is_ignored_without_mongo(monkeypatch):
    import app.account_database as accounts

    monkeypatch.setattr(
        accounts,
        "get_settings",
        lambda: SimpleNamespace(APP_ENV="development"),
    )
    get_db = Mock(side_effect=AssertionError("local auth must not use Mongo"))
    monkeypatch.setattr(accounts, "get_db", get_db)

    assert await accounts.resolve_auth_session("stale-or-online-cookie") is None
    get_db.assert_not_called()


@pytest.mark.asyncio
async def test_local_stateful_route_dependency_returns_explicit_503(monkeypatch):
    from app.api import dependencies

    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: SimpleNamespace(APP_ENV="development"),
    )

    with pytest.raises(HTTPException) as error:
        await dependencies.require_online_persistence()

    assert error.value.status_code == 503
    assert error.value.detail["code"] == "online_persistence_required"


@pytest.mark.asyncio
async def test_production_stateful_route_dependency_allows_online_path(monkeypatch):
    from app.api import dependencies

    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: SimpleNamespace(APP_ENV="production"),
    )

    assert await dependencies.require_online_persistence() is None


def test_main_workspace_and_account_routes_are_gated_in_local_mode(monkeypatch):
    import app.api.dependencies as dependencies
    import app.main as main

    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: SimpleNamespace(APP_ENV="development"),
    )
    client = TestClient(main.app, raise_server_exceptions=False)

    for path in ("/workspaces", "/account", "/login", "/register"):
        response = client.get(path)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "online_persistence_required"


def test_main_account_form_route_remains_available_online(monkeypatch):
    import app.api.dependencies as dependencies
    import app.main as main

    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: SimpleNamespace(APP_ENV="production"),
    )

    response = TestClient(main.app, raise_server_exceptions=False).get("/login")

    assert response.status_code == 200
    assert "Đăng nhập" in response.text


@pytest.mark.asyncio
async def test_local_readiness_does_not_probe_configured_mongo(tmp_path):
    from app.services.readiness import build_readiness

    mongo_ping = AsyncMock(return_value=True)
    result = await build_readiness(
        SimpleNamespace(
            APP_ENV="development",
            CONTENT_STORE_PATH=tmp_path / "content.sqlite3",
            LEGAL_FTS_PATH=tmp_path / "fts.sqlite3",
            MONGO_URL="mongodb://must-not-connect",
        ),
        mongo_ping=mongo_ping,
    )

    assert result["checks"]["mongodb"] == "not_required"
    mongo_ping.assert_not_awaited()


def test_local_chat_returns_answer_without_mongo_or_history(monkeypatch):
    from fastapi import FastAPI
    from app.api import routes
    import app.database as database

    monkeypatch.setattr(routes.settings, "APP_ENV", "development")
    get_db = Mock(side_effect=AssertionError("local chat must not use Mongo"))
    monkeypatch.setattr(database, "get_db", get_db)
    monkeypatch.setattr(routes, "check_semantic_cache", AsyncMock(return_value=None))
    monkeypatch.setattr(routes, "save_to_semantic_cache", AsyncMock())
    monkeypatch.setattr(
        routes, "check_input_guardrails", AsyncMock(return_value=(True, ""))
    )
    monkeypatch.setattr(
        routes,
        "run_advanced_rag",
        AsyncMock(
            return_value=(
                "Câu trả lời local.",
                ["[Luật 1, Điều 1] Căn cứ"],
                {"t_total": 0.1, "retrieval_status": "ok"},
            )
        ),
    )
    monkeypatch.setattr(
        routes, "check_output_guardrails", AsyncMock(return_value=(True, ""))
    )
    test_app = FastAPI()
    test_app.dependency_overrides[routes.verify_csrf] = lambda: "valid"
    test_app.dependency_overrides[routes.optional_user] = lambda: None
    test_app.include_router(routes.router)

    response = TestClient(test_app, raise_server_exceptions=False).post(
        "/chat",
        data={
            "message": "Câu hỏi kiểm thử",
            "csrf_token": "valid",
            "session_id": "default",
        },
    )

    assert response.status_code == 200
    assert "Câu trả lời local." in response.text
    get_db.assert_not_called()


def test_local_home_explains_stateless_and_online_only_features(monkeypatch):
    import app.main as main

    monkeypatch.setattr(main.settings, "APP_ENV", "development")
    main.templates.env.globals["local_stateless_mode"] = True
    response = TestClient(main.app, raise_server_exceptions=False).get("/")

    assert response.status_code == 200
    assert "không lưu hội thoại" in response.text.lower()
    assert "lượt AI/ngày UTC" not in response.text


def test_local_asgi_lifespan_serves_health_without_mongo(monkeypatch):
    import app.database as database
    import app.main as main

    monkeypatch.setattr(main.settings, "APP_ENV", "development")
    monkeypatch.setattr(main.settings, "MONGO_URL", None)
    monkeypatch.setattr(main.settings, "PUBLIC_NEMO_DEFAULT_ENABLED", False)
    monkeypatch.setattr(main.settings, "REVIEWER_DEMO_MODE", False)
    monkeypatch.setattr(database, "client", None)
    monkeypatch.setattr(database, "db", None)
    with patch(
        "app.database.AsyncIOMotorClient",
        side_effect=AssertionError("local lifespan must not initialize Mongo"),
    ) as motor:
        with TestClient(main.app) as client:
            health = client.get("/healthz")
            readiness = client.get("/readyz")
            home = client.get("/")

    motor.assert_not_called()
    assert health.status_code == 200
    assert readiness.status_code == 200
    assert readiness.json()["checks"]["mongodb"] == "not_required"
    assert "không lưu hội thoại" in home.text.lower()


@pytest.mark.asyncio
async def test_development_bypasses_production_demo_admission(monkeypatch):
    import app.services.reviewer_demo as demo

    config = SimpleNamespace(
        APP_ENV="development",
        REVIEWER_DEMO_MODE=True,
        AUTH_COOKIE_NAME="auth",
        DEMO_AI_DAILY_LIMIT=20,
        DEMO_AI_GLOBAL_DAILY_LIMIT=100,
    )
    resolve = AsyncMock(side_effect=AssertionError("local mode must not require login"))
    reserve = AsyncMock(side_effect=AssertionError("local mode has no demo quota"))
    monkeypatch.setattr(demo, "resolve_auth_session", resolve)
    monkeypatch.setattr(demo, "reserve_demo_budget", reserve)

    downstream = AsyncMock()
    receive = AsyncMock(return_value={"type": "http.request", "body": b"", "more_body": False})
    await demo.ReviewerDemoMiddleware(downstream, settings=config)(
        {"type": "http", "method": "POST", "path": "/chat", "headers": []},
        receive,
        AsyncMock(),
    )

    downstream.assert_awaited_once()
    resolve.assert_not_awaited()
    reserve.assert_not_awaited()


@pytest.mark.asyncio
async def test_development_disables_inherited_demo_quota_without_database(monkeypatch):
    import app.services.reviewer_demo as demo

    config = SimpleNamespace(
        APP_ENV="development",
        REVIEWER_DEMO_MODE=True,
        DEMO_AI_DAILY_LIMIT=20,
        DEMO_AI_GLOBAL_DAILY_LIMIT=100,
    )
    monkeypatch.setattr(demo, "get_db", Mock(side_effect=AssertionError("no local quota storage")))

    assert await demo.get_demo_quota("developer", config) == {"status": "disabled"}
