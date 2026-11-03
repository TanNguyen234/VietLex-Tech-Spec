import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.dependencies import require_user, verify_csrf, verify_csrf_header
from app.rate_limit import limiter


@pytest.fixture
def client(monkeypatch):
    import app.api.account_routes as routes

    limiter._storage.reset()
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.client_id = "client-a"
        return await call_next(request)

    app.dependency_overrides[verify_csrf] = lambda: "valid"
    app.dependency_overrides[verify_csrf_header] = lambda: "valid"
    app.include_router(routes.router)
    monkeypatch.setattr(
        routes,
        "settings",
        SimpleNamespace(
            ACCOUNT_EMAIL_ENABLED=True,
            AUTH_COOKIE_NAME="vietlex_auth",
            AUTH_SESSION_DAYS=7,
            APP_ENV="test",
            SESSION_RATE_LIMIT="1000/minute",
        ),
    )
    return TestClient(app)


@pytest.mark.parametrize(
    "path",
    [
        "/register",
        "/login",
        "/verify-email?token=unused",
        "/forgot-password",
        "/reset-password?token=unused",
    ],
)
def test_development_account_pages_are_explicitly_online_only(
    client, monkeypatch, path
) -> None:
    import app.api.account_routes as routes

    routes.settings.APP_ENV = "development"
    consume_token = AsyncMock(side_effect=AssertionError("local page accessed account storage"))
    monkeypatch.setattr(routes, "consume_account_token", consume_token)

    response = client.get(path)

    assert response.status_code == 503
    assert "chỉ khả dụng trên môi trường trực tuyến" in response.text
    assert "<form" not in response.text
    consume_token.assert_not_awaited()


def test_disabled_production_registration_does_not_show_a_form(
    client, monkeypatch
) -> None:
    import app.api.account_routes as routes

    routes.settings.ACCOUNT_EMAIL_ENABLED = False

    page = client.get("/register")
    submit = client.post(
        "/register",
        data={
            "email": "person@example.com",
            "password": "long-enough-password",
            "csrf_token": "valid",
        },
    )

    for response in (page, submit):
        assert response.status_code == 503
        assert "Đăng ký email hiện chưa được cấu hình" in response.text
        assert "<form" not in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/register",
        "/login",
        "/forgot-password",
        "/verify-email?token=verification-token",
        "/reset-password?token=reset-token",
    ],
)
def test_account_pages_are_not_cacheable(client, path: str) -> None:
    response = client.get(path)

    assert response.headers["cache-control"] == "no-store"


def test_logout_revokes_current_session_and_clears_auth_cookie(
    client, monkeypatch
) -> None:
    import app.api.account_routes as routes

    revoke = AsyncMock()
    monkeypatch.setattr(routes, "revoke_auth_session", revoke)
    client.cookies.set("vietlex_auth", "opaque-session-token")

    response = client.post(
        "/logout",
        data={"csrf_token": "valid"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    revoke.assert_awaited_once_with("opaque-session-token")
    cookie = response.headers.get("set-cookie", "").lower()
    assert "vietlex_auth=" in cookie
    assert "max-age=0" in cookie


def test_csrf_form_survives_opening_another_account_page(client, monkeypatch) -> None:
    import app.api.account_routes as routes

    client.app.dependency_overrides.pop(verify_csrf)
    first_page = client.get("/login")
    token = re.search(r'name="csrf_token" value="([0-9a-f]{64})"', first_page.text).group(1)
    assert client.get("/register").status_code == 200

    client.app.dependency_overrides[require_user] = lambda: {
        "_id": "owner", "email": "owner@example.com", "role": "user"
    }
    monkeypatch.setattr(routes, "list_auth_sessions", AsyncMock(return_value=[]))
    monkeypatch.setattr(routes, "get_demo_quota", AsyncMock(return_value={"status": "disabled"}))
    assert client.get("/settings").status_code == 200

    revoke = AsyncMock()
    monkeypatch.setattr(routes, "revoke_auth_session", revoke)
    response = client.post("/logout", data={"csrf_token": token}, follow_redirects=False)
    assert response.status_code == 303
    revoke.assert_awaited_once()
    assert client.post("/logout", data={"csrf_token": "wrong"}).status_code == 403


def test_history_delete_requires_csrf_and_scopes_to_authenticated_user(
    client, monkeypatch
) -> None:
    import app.api.account_routes as routes

    client.app.dependency_overrides[require_user] = lambda: {"_id": "user-1"}
    delete_history = AsyncMock()
    monkeypatch.setattr(routes, "delete_account_history", delete_history)
    client.app.dependency_overrides.pop(verify_csrf)

    rejected = client.post(
        "/account/history/delete",
        data={"csrf_token": "invalid"},
        follow_redirects=False,
    )

    assert rejected.status_code == 403
    delete_history.assert_not_awaited()

    client.app.dependency_overrides[verify_csrf] = lambda: "valid"
    response = client.post(
        "/account/history/delete",
        data={"csrf_token": "valid"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/settings"
    delete_history.assert_awaited_once_with("user-1")


def test_revoke_other_sessions_uses_current_user_and_cookie(
    client, monkeypatch
) -> None:
    import app.api.account_routes as routes

    client.app.dependency_overrides[require_user] = lambda: {"_id": "user-1"}
    client.cookies.set("vietlex_auth", "current-session-token")
    revoke = AsyncMock()
    monkeypatch.setattr(routes, "revoke_other_auth_sessions", revoke)

    response = client.post(
        "/account/sessions/revoke-others",
        data={"csrf_token": "valid"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/settings"
    revoke.assert_awaited_once_with("user-1", "current-session-token")


def test_registration_creates_unverified_user_and_sends_token(
    client, monkeypatch
) -> None:
    import app.api.account_routes as routes

    user = {"_id": "user-1", "email": "person@example.com"}
    sender = SimpleNamespace(send_verification=AsyncMock())
    monkeypatch.setattr(routes, "get_user_by_email", AsyncMock(return_value=None))
    monkeypatch.setattr(routes, "create_user", AsyncMock(return_value=user))
    monkeypatch.setattr(routes, "create_account_token", AsyncMock())
    monkeypatch.setattr(routes, "get_email_sender", lambda: sender)
    monkeypatch.setattr(routes, "new_token", lambda: "verification-token")

    response = client.post(
        "/register",
        data={
            "email": " Person@Example.com ",
            "password": "long-enough-password",
            "role": "admin",
            "csrf_token": "valid",
        },
    )

    assert response.status_code == 200
    assert "Nếu địa chỉ hợp lệ" in response.text
    routes.create_user.assert_awaited_once()
    assert len(routes.create_user.await_args.args) == 2
    routes.create_account_token.assert_awaited_once_with(
        "user-1", "verify_email", "verification-token"
    )
    sender.send_verification.assert_awaited_once_with(
        "person@example.com", "verification-token"
    )


def test_login_sets_opaque_cookie_and_claims_anonymous_history(
    client, monkeypatch
) -> None:
    import app.api.account_routes as routes

    monkeypatch.setattr(
        routes,
        "get_user_by_email",
        AsyncMock(
            return_value={
                "_id": "user-1",
                "email": "person@example.com",
                "email_verified": True,
                "password_hash": "password-envelope",
            }
        ),
    )
    monkeypatch.setattr(routes, "verify_password", lambda *_args: True)
    monkeypatch.setattr(routes, "new_token", lambda: "opaque-session-token")
    monkeypatch.setattr(routes, "create_auth_session", AsyncMock())
    monkeypatch.setattr(routes, "mark_last_login", AsyncMock())
    monkeypatch.setattr(routes, "claim_anonymous_history", AsyncMock())

    response = client.post(
        "/login",
        data={
            "email": "person@example.com",
            "password": "correct-password",
            "csrf_token": "valid",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.cookies["vietlex_auth"] == "opaque-session-token"
    assert "Max-Age=604800" in response.headers["set-cookie"]
    routes.create_auth_session.assert_awaited_once_with(
        "user-1", "opaque-session-token"
    )
    routes.claim_anonymous_history.assert_awaited_once_with("user-1", "client-a")


def test_verification_get_is_read_only_and_post_consumes_once(
    client, monkeypatch
) -> None:
    import app.api.account_routes as routes

    consume = AsyncMock(side_effect=["user-1", "user-1"])
    monkeypatch.setattr(routes, "consume_account_token", consume)
    mark_verified = AsyncMock(return_value=True)
    monkeypatch.setattr(routes, "mark_user_verified", mark_verified)
    monkeypatch.setattr(routes, "update_password", AsyncMock(return_value=True))

    confirmation = client.get("/verify-email?token=verify-token")
    assert confirmation.status_code == 200
    assert 'action="/verify-email"' in confirmation.text
    assert 'name="token" value="verify-token"' in confirmation.text
    consume.assert_not_awaited()
    mark_verified.assert_not_awaited()

    verified = client.post(
        "/verify-email",
        data={"token": "verify-token", "csrf_token": "valid"},
    )
    reset = client.post(
        "/reset-password",
        data={
            "token": "reset-token",
            "password": "new-long-password",
            "csrf_token": "valid",
        },
    )

    assert verified.status_code == 200
    assert "đã được xác minh" in verified.text
    assert reset.status_code == 200
    assert "đã được cập nhật" in reset.text
    assert consume.await_args_list[0].args == ("verify-token", "verify_email")
    assert consume.await_args_list[1].args == ("reset-token", "reset_password")
    mark_verified.assert_awaited_once_with("user-1")


def test_verify_email_post_requires_csrf_before_consuming_token(
    client, monkeypatch
) -> None:
    import app.api.account_routes as routes

    consume = AsyncMock()
    monkeypatch.setattr(routes, "consume_account_token", consume)
    client.app.dependency_overrides.pop(verify_csrf)

    response = client.post(
        "/verify-email",
        data={"token": "verify-token", "csrf_token": "submitted-without-cookie"},
    )

    assert response.status_code == 403
    consume.assert_not_awaited()


def test_verify_email_missing_and_invalid_tokens_use_generic_message(
    client, monkeypatch
) -> None:
    import app.api.account_routes as routes

    consume = AsyncMock(return_value=None)
    mark_verified = AsyncMock(return_value=True)
    monkeypatch.setattr(routes, "consume_account_token", consume)
    monkeypatch.setattr(routes, "mark_user_verified", mark_verified)

    missing_get = client.get("/verify-email")
    missing_post = client.post("/verify-email", data={"csrf_token": "valid"})
    invalid_post = client.post(
        "/verify-email",
        data={"token": "invalid-token", "csrf_token": "valid"},
    )

    expected = "Liên kết xác minh không hợp lệ hoặc đã hết hạn."
    assert missing_get.status_code == 200
    assert missing_post.status_code == 200
    assert invalid_post.status_code == 200
    assert all(expected in response.text for response in (missing_get, missing_post, invalid_post))
    consume.assert_awaited_once_with("invalid-token", "verify_email")
    mark_verified.assert_not_awaited()


def test_account_delete_requires_authenticated_user_and_clears_cookie(
    client, monkeypatch
) -> None:
    import app.api.account_routes as routes

    app = client.app
    app.dependency_overrides[routes.require_user] = lambda: {
        "_id": "user-1",
        "email": "person@example.com",
    }
    monkeypatch.setattr(routes, "delete_account", AsyncMock())

    response = client.post(
        "/account/delete",
        data={"csrf_token": "valid"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    routes.delete_account.assert_awaited_once_with("user-1")
    assert response.headers["location"] == "/"


def test_login_is_rate_limited(client, monkeypatch) -> None:
    import app.api.account_routes as routes

    monkeypatch.setattr(routes, "get_user_by_email", AsyncMock(return_value=None))

    responses = [
        client.post(
            "/login",
            data={
                "email": "person@example.com",
                "password": "wrong-password",
                "csrf_token": "valid",
            },
        )
        for _ in range(31)
    ]

    assert responses[-1].status_code == 429


def test_disabled_user_cannot_login(client, monkeypatch) -> None:
    import app.api.account_routes as routes

    monkeypatch.setattr(
        routes,
        "get_user_by_email",
        AsyncMock(return_value={
            "_id": "user-1",
            "email_verified": True,
            "status": "disabled",
            "password_hash": "password-envelope",
        }),
    )
    monkeypatch.setattr(routes, "verify_password", lambda *_args: True)
    create_session = AsyncMock()
    monkeypatch.setattr(routes, "create_auth_session", create_session)

    response = client.post(
        "/login",
        data={"email": "u@example.com", "password": "correct-password", "csrf_token": "valid"},
    )

    assert response.status_code == 401
    create_session.assert_not_awaited()

def test_settings_quota_is_owner_scoped_and_not_cached(client, monkeypatch):
    import app.api.account_routes as routes
    client.app.dependency_overrides[routes.require_user] = lambda: {'_id': 'owner', 'email': 'a@example.com'}
    monkeypatch.setattr(routes, 'list_auth_sessions', AsyncMock(return_value=[]))
    quota = AsyncMock(return_value={'status': 'ok', 'resets_at': '2026-09-09T00:00:00+00:00', 'ai': {'used': 7, 'limit': 20, 'remaining': 13, 'available': 1}, 'write': {'used': 0, 'limit': 100, 'remaining': 100, 'available': 100}})
    monkeypatch.setattr(routes, 'get_demo_quota', quota)
    response = client.get('/settings')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert 'còn 13' in response.text
    assert quota.await_args.args[0] == 'owner'


def test_admin_settings_explain_daily_quota_exemption(client, monkeypatch):
    import app.api.account_routes as routes
    client.app.dependency_overrides[routes.require_user] = lambda: {
        '_id': 'developer', 'email': 'dev@example.com', 'role': 'admin'}
    monkeypatch.setattr(routes, 'list_auth_sessions', AsyncMock(return_value=[]))
    quota = AsyncMock(return_value={'status': 'exempt'})
    monkeypatch.setattr(routes, 'get_demo_quota', quota)
    response = client.get('/settings')
    assert response.status_code == 200
    assert quota.await_args.kwargs == {'is_admin': True}
    assert 'không áp dụng cho tài khoản admin' in response.text

def test_account_export_is_not_cached(client, monkeypatch):
    import app.api.account_routes as routes
    client.app.dependency_overrides[routes.require_user] = lambda: {'_id': 'owner'}
    monkeypatch.setattr(routes, 'export_account', AsyncMock(return_value={'private': 'data'}))
    response = client.get('/account/export')
    assert response.headers['cache-control'] == 'no-store'
