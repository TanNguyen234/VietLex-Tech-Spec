from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.dependencies import verify_csrf, verify_csrf_header
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
            "csrf_token": "valid",
        },
    )

    assert response.status_code == 200
    assert "Nếu địa chỉ hợp lệ" in response.text
    routes.create_user.assert_awaited_once()
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


def test_verification_and_reset_tokens_are_consumed_once(client, monkeypatch) -> None:
    import app.api.account_routes as routes

    consume = AsyncMock(side_effect=["user-1", "user-1"])
    monkeypatch.setattr(routes, "consume_account_token", consume)
    monkeypatch.setattr(routes, "mark_user_verified", AsyncMock(return_value=True))
    monkeypatch.setattr(routes, "update_password", AsyncMock(return_value=True))

    verified = client.get("/verify-email?token=verify-token")
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
