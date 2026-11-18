from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
import app.services.reviewer_demo as demo


def _prod_demo_settings() -> SimpleNamespace:
    return SimpleNamespace(
        APP_ENV="production",
        REVIEWER_DEMO_MODE=True,
        AUTH_COOKIE_NAME="vietlex_auth",
        DEMO_AI_DAILY_LIMIT=20,
        DEMO_AI_GLOBAL_DAILY_LIMIT=100,
    )


def test_settings_resolves_tavily_api_and_provider_defaults() -> None:
    defaults = Settings(_env_file=None)
    assert defaults.TAVILY_API is None
    assert defaults.TAVILY_API_KEY is None
    assert defaults.tavily_api_key is None
    assert defaults.TAVILY_SEARCH_ENABLED is True
    assert defaults.TAVILY_EXTRACT_ENABLED is True
    assert defaults.TAVILY_TIMEOUT_SECONDS == 8.0
    assert defaults.TAVILY_SEARCH_DEPTH == "basic"
    assert defaults.DEFAULT_LLM_PROVIDER == "auto"

    alias_only = Settings(_env_file=None, TAVILY_API="tvly-test-alias")
    assert alias_only.tavily_api_key == "tvly-test-alias"

    both = Settings(
        _env_file=None,
        TAVILY_API="tvly-fallback",
        TAVILY_API_KEY="tvly-primary",
    )
    assert both.tavily_api_key == "tvly-primary"


@pytest.mark.asyncio
async def test_active_bodies_released_before_downstream_handler_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        demo,
        "resolve_auth_session",
        AsyncMock(
            return_value={
                "_id": "user-concurrent",
                "email_verified": True,
                "status": "active",
                "role": "admin",
            }
        ),
    )
    monkeypatch.setattr(demo, "reserve_demo_budget", AsyncMock(return_value=True))

    entered = 0
    all_three_in_handler = asyncio.Event()
    release_handler = asyncio.Event()
    observed_active_bodies_in_handler: list[int] = []

    async def slow_app(scope, receive, send):
        nonlocal entered
        msg = await receive()
        assert msg["type"] == "http.request"
        observed_active_bodies_in_handler.append(middleware.active_bodies)
        entered += 1
        if entered == 3:
            all_three_in_handler.set()
        await release_handler.wait()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = demo.ReviewerDemoMiddleware(slow_app, settings=_prod_demo_settings())

    async def invoke_one(idx: int) -> int:
        sent_events: list[dict] = []

        async def receive():
            return {
                "type": "http.request",
                "body": f"csrf_token=x&message=q{idx}".encode("utf-8"),
                "more_body": False,
            }

        async def send(event: dict):
            sent_events.append(event)

        await middleware(
            {
                "type": "http",
                "method": "POST",
                "path": "/chat",
                "headers": [],
                "client": ("127.0.0.1", 5000 + idx),
            },
            receive,
            send,
        )
        return sent_events[0]["status"]

    tasks = [asyncio.create_task(invoke_one(i)) for i in range(3)]
    try:
        await asyncio.wait_for(all_three_in_handler.wait(), timeout=1.0)
    finally:
        release_handler.set()
    statuses = await asyncio.gather(*tasks)

    assert statuses == [200, 200, 200]
    assert observed_active_bodies_in_handler == [0, 0, 0]
    assert middleware.active_bodies == 0


@pytest.mark.asyncio
async def test_active_bodies_still_caps_concurrent_in_flight_body_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        demo,
        "resolve_auth_session",
        AsyncMock(
            return_value={
                "_id": "user-upload",
                "email_verified": True,
                "status": "active",
                "role": "admin",
            }
        ),
    )
    monkeypatch.setattr(demo, "reserve_demo_budget", AsyncMock(return_value=True))

    two_streams_open = asyncio.Event()
    release_streams = asyncio.Event()
    in_flight = 0

    middleware = demo.ReviewerDemoMiddleware(AsyncMock(), settings=_prod_demo_settings())

    async def slow_body_request() -> int:
        nonlocal in_flight
        chunk_idx = 0
        sent: list[dict] = []

        async def receive():
            nonlocal chunk_idx, in_flight
            chunk_idx += 1
            if chunk_idx == 1:
                in_flight += 1
                if in_flight == 2:
                    two_streams_open.set()
                await release_streams.wait()
                return {"type": "http.request", "body": b"part1", "more_body": True}
            return {"type": "http.request", "body": b"part2", "more_body": False}

        async def send(event: dict):
            sent.append(event)

        await middleware(
            {
                "type": "http",
                "method": "POST",
                "path": "/workspaces/w1/documents",
                "headers": [],
                "client": ("127.0.0.1", 6000),
            },
            receive,
            send,
        )
        return sent[0]["status"] if sent else 200

    t1 = asyncio.create_task(slow_body_request())
    t2 = asyncio.create_task(slow_body_request())
    await asyncio.wait_for(two_streams_open.wait(), timeout=1.0)
    assert middleware.active_bodies == 2

    third_sent: list[dict] = []
    await middleware(
        {
            "type": "http",
            "method": "POST",
            "path": "/chat",
            "headers": [],
            "client": ("127.0.0.1", 6003),
        },
        AsyncMock(return_value={"type": "http.request", "body": b"x", "more_body": False}),
        AsyncMock(side_effect=lambda e: third_sent.append(e)),
    )
    release_streams.set()
    await asyncio.gather(t1, t2)

    assert third_sent[0]["status"] == 503
    assert middleware.active_bodies == 0


@pytest.mark.asyncio
async def test_admin_exempt_from_three_per_minute_personal_ai_cap_while_regular_user_throttled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prod = _prod_demo_settings()
    admin_user = {
        "_id": "admin-1",
        "email_verified": True,
        "status": "active",
        "role": "admin",
    }
    regular_user = {
        "_id": "user-1",
        "email_verified": True,
        "status": "active",
        "role": "user",
    }
    assert demo.is_demo_exempt(admin_user, prod) is True
    assert demo.is_demo_exempt(regular_user, prod) is False
    assert demo.is_demo_exempt(regular_user, SimpleNamespace(APP_ENV="development", REVIEWER_DEMO_MODE=True)) is True

    usage_counters: dict[tuple[str, str, bool], int] = {}

    async def fake_reserve(
        subject: str,
        category: str,
        personal: int,
        total: int,
        *,
        minute: bool = False,
    ) -> bool:
        key = (subject, category, minute)
        used = usage_counters.get(key, 0)
        if used >= personal or used >= total:
            return False
        usage_counters[key] = used + 1
        return True

    monkeypatch.setattr(demo, "reserve_demo_budget", fake_reserve)

    async def run_chat_for(user: dict) -> int:
        monkeypatch.setattr(demo, "resolve_auth_session", AsyncMock(return_value=user))
        sent: list[dict] = []

        async def ok_app(scope, receive, send):
            await receive()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = demo.ReviewerDemoMiddleware(ok_app, settings=prod)
        await mw(
            {"type": "http", "method": "POST", "path": "/chat", "headers": []},
            AsyncMock(return_value={"type": "http.request", "body": b"m=1", "more_body": False}),
            AsyncMock(side_effect=lambda event: sent.append(event)),
        )
        return sent[0]["status"]

    admin_statuses = [await run_chat_for(admin_user) for _ in range(5)]
    assert admin_statuses == [200, 200, 200, 200, 200]

    regular_statuses = [await run_chat_for(regular_user) for _ in range(4)]
    assert regular_statuses == [200, 200, 200, 429]


@pytest.mark.asyncio
async def test_v3_production_startup_logs_warning_when_pinecone_key_missing(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import app.main as main
    import app.services.semantic_cache as semantic_cache

    monkeypatch.setattr(main.settings, "APP_ENV", "production")
    monkeypatch.setattr(main.settings, "USE_LEGACY_FREE_PIPELINE", False)
    monkeypatch.setattr(main.settings, "PUBLIC_NEMO_DEFAULT_ENABLED", False)
    monkeypatch.setattr(main, "init_db", AsyncMock())
    monkeypatch.setattr(
        semantic_cache,
        "ensure_semantic_cache_collection",
        AsyncMock(side_effect=RuntimeError("PIPECONE_API or PINECONE_API_KEY is required.")),
    )

    with caplog.at_level(logging.WARNING):
        await main.startup_event()

    assert any("Semantic cache" in record.message for record in caplog.records)


def test_dockerfile_and_vercel_entrypoint_default_serverless_online_only() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    dockerfile = (repo_root / "Dockerfile").read_text(encoding="utf-8")
    server_py = (repo_root / "app" / "server.py").read_text(encoding="utf-8")

    assert "SERVERLESS_ONLINE_ONLY=true" in dockerfile
    assert '"SERVERLESS_ONLINE_ONLY", "true"' in server_py or "'SERVERLESS_ONLINE_ONLY', 'true'" in server_py
