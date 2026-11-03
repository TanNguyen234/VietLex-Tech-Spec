from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_free_research_uses_ordinary_quota_category_not_ai_budget(monkeypatch):
    import app.services.reviewer_demo as demo

    settings = SimpleNamespace(
        APP_ENV="production",
        REVIEWER_DEMO_MODE=True,
        AUTH_COOKIE_NAME="auth",
        DEMO_AI_DAILY_LIMIT=20,
        DEMO_AI_GLOBAL_DAILY_LIMIT=100,
    )
    monkeypatch.setattr(
        demo,
        "resolve_auth_session",
        AsyncMock(return_value={"_id": "verified-user", "email_verified": True, "status": "active"}),
    )
    reserve = AsyncMock(return_value=True)
    monkeypatch.setattr(demo, "reserve_demo_budget", reserve)
    downstream = AsyncMock()

    await demo.ReviewerDemoMiddleware(downstream, settings=settings)(
        {"type": "http", "method": "POST", "path": "/workspaces/w/research/read", "headers": [], "client": ("peer", 1)},
        AsyncMock(return_value={"type": "http.request", "body": b"", "more_body": False}),
        AsyncMock(),
    )

    assert reserve.await_count == 2
    assert reserve.await_args_list[0].args[1] == "free_research"
    assert reserve.await_args_list[0].args[2:] == (2, 60)
    assert reserve.await_args_list[1].args[1] == "free_research"
    assert reserve.await_args_list[1].args[2:] == (100, 1000)
