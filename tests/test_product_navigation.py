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


def test_settings_template_shows_role_logout_and_admin_shortcut():
    env = Environment(loader=FileSystemLoader("app/templates"), autoescape=select_autoescape())
    admin_html = env.get_template("settings.html").render(
        user={"_id": "a1", "email": "admin@vietlex.vn", "role": "admin"},
        sessions=[],
        csrf_token="test-csrf",
        demo_quota={"status": "exempt"},
    )
    assert "Quản trị viên (admin)" in admin_html
    assert 'href="/admin"' in admin_html
    assert 'action="/logout"' in admin_html

    user_html = env.get_template("settings.html").render(
        user={"_id": "u1", "email": "user@vietlex.vn", "role": "user"},
        sessions=[],
        csrf_token="test-csrf",
        demo_quota={"status": "unavailable"},
    )
    assert "Người dùng (user)" in user_html
    assert 'href="/admin"' not in user_html
    assert 'action="/logout"' in user_html


def test_admin_users_template_renders_role_toggle_except_for_current_admin():
    env = Environment(loader=FileSystemLoader("app/templates"), autoescape=select_autoescape())
    html = env.get_template("admin_users.html").render(
        current_admin={"_id": "admin-1"},
        csrf_token="test",
        users=[
            {"_id": "admin-1", "email": "admin@example.test", "status": "active", "role": "admin"},
            {"_id": "user-2", "email": "user@example.test", "status": "active", "role": "user"},
        ],
    )
    assert '/admin/users/admin-1/status' not in html
    assert '/admin/users/admin-1/role' not in html
    assert '/admin/users/user-2/role' in html
    assert 'Cấp quyền Admin' in html


def test_admin_set_user_role_blocks_self_demotion_and_updates_other_user(monkeypatch):
    from unittest.mock import AsyncMock
    from app.api import routes as public_routes
    from app.api.dependencies import require_admin, verify_csrf
    from app.rate_limit import limiter

    limiter._storage.reset()
    app = FastAPI()
    app.state.limiter = limiter
    app.dependency_overrides[require_admin] = lambda: {"_id": "admin-1", "role": "admin"}
    app.dependency_overrides[verify_csrf] = lambda: "valid"
    set_role_mock = AsyncMock(return_value=True)
    audit_mock = AsyncMock()
    monkeypatch.setattr(public_routes, "set_user_role", set_role_mock, raising=False)
    monkeypatch.setattr(public_routes, "write_admin_audit", audit_mock)
    app.include_router(public_routes.router)
    client = TestClient(app)

    self_resp = client.post(
        "/admin/users/admin-1/role",
        data={"account_role": "user", "csrf_token": "valid"},
        follow_redirects=False,
    )
    assert self_resp.status_code == 409
    set_role_mock.assert_not_awaited()

    promote_resp = client.post(
        "/admin/users/user-2/role",
        data={"account_role": "admin", "csrf_token": "valid"},
        follow_redirects=False,
    )
    assert promote_resp.status_code == 303
    assert promote_resp.headers["location"] == "/admin/users"
    set_role_mock.assert_awaited_once_with("user-2", "admin")
    audit_mock.assert_awaited_once()

