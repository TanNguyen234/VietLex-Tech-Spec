from fastapi import FastAPI
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader, select_autoescape
import pytest

from app.api.account_routes import router
from app.api.dependencies import optional_user


def test_session_revocation_returns_to_account_entry(monkeypatch):
    from unittest.mock import AsyncMock
    import app.api.account_routes as routes
    from app.api.dependencies import require_user, verify_csrf
    from app.rate_limit import limiter

    limiter._storage.reset()
    app = FastAPI()
    app.state.limiter = limiter
    app.dependency_overrides[require_user] = lambda: {"_id": "u1"}
    app.dependency_overrides[verify_csrf] = lambda: "valid"
    revoke = AsyncMock()
    monkeypatch.setattr(routes, "revoke_auth_session_by_id", revoke)
    app.include_router(router)
    response = TestClient(app).post("/account/sessions/current/revoke", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/account"
    revoke.assert_awaited_once_with("u1", "current")


@pytest.mark.parametrize("user,destination", [(None, "/login"), ({"_id": "u1"}, "/settings")])
def test_account_navigation_uses_session(user, destination):
    app = FastAPI()
    app.dependency_overrides[optional_user] = lambda: user
    app.include_router(router)
    response = TestClient(app).get("/account", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == destination


def test_admin_unknown_guardrail_is_not_a_block():
    env = Environment(loader=FileSystemLoader("app/templates"), autoescape=select_autoescape())
    html = env.get_template("admin_details.html").render(log={
        "trace_id": "test", "timestamp": None, "cached": False,
        "safety_status": {"input_safe": None, "output_safe": None},
        "user_query": "<script>alert(1)</script>", "bot_response": "test",
        "metrics": {}, "contexts": [],
    })
    assert html.count("Chưa ghi nhận") >= 2
    assert "Input: Chưa ghi nhận · Output: Chưa ghi nhận" in html
    assert "Bị chặn" not in html
    assert "<script>alert(1)</script>" not in html
    assert 'href="/admin"' in html


def test_admin_does_not_offer_self_disable():
    env = Environment(loader=FileSystemLoader("app/templates"), autoescape=select_autoescape())
    html = env.get_template("admin_users.html").render(
        current_admin={"_id": "admin-1"}, csrf_token="test",
        users=[{"_id": "admin-1", "email": "admin@example.test", "status": "active", "role": "admin"}],
    )
    assert '/admin/users/admin-1/status' not in html
    assert '/admin/users/admin-1/revoke-sessions' in html
    assert 'data-confirm=' in html
