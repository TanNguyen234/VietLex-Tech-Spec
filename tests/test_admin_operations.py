from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import require_admin, verify_csrf
from app.api.routes import _sanitize_admin_interaction, router
from app.rate_limit import limiter


def _client():
    limiter._storage.reset()
    app = FastAPI()
    app.state.limiter = limiter
    app.dependency_overrides[require_admin] = lambda: {
        "_id": "admin-1", "role": "admin", "status": "active"
    }
    app.dependency_overrides[verify_csrf] = lambda: "valid"
    app.include_router(router)
    return TestClient(app)


def test_admin_disable_creates_audit_record(monkeypatch) -> None:
    import app.api.routes as routes

    set_status = AsyncMock(return_value=True)
    audit = AsyncMock()
    monkeypatch.setattr(routes, "set_user_status", set_status)
    monkeypatch.setattr(routes, "write_admin_audit", audit)

    response = _client().post(
        "/admin/users/user-1/status",
        data={"account_status": "disabled", "csrf_token": "valid"},
        headers={"x-request-id": "request-1"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    set_status.assert_awaited_once_with("user-1", "disabled")
    assert audit.await_args.args[:4] == (
        "admin-1", "account_disabled", "user", "user-1"
    )


def test_admin_cannot_disable_self(monkeypatch) -> None:
    import app.api.routes as routes

    set_status = AsyncMock(return_value=True)
    monkeypatch.setattr(routes, "set_user_status", set_status)

    response = _client().post(
        "/admin/users/admin-1/status",
        data={"account_status": "disabled", "csrf_token": "valid"},
    )

    assert response.status_code == 409
    set_status.assert_not_awaited()


def test_admin_revoke_sessions_rejects_unknown_user(monkeypatch) -> None:
    import app.api.routes as routes

    monkeypatch.setattr(routes, "get_user_by_id", AsyncMock(return_value=None))
    revoke = AsyncMock()
    monkeypatch.setattr(routes, "revoke_all_auth_sessions", revoke)

    response = _client().post(
        "/admin/users/missing/revoke-sessions",
        data={"csrf_token": "valid"},
    )

    assert response.status_code == 404
    revoke.assert_not_awaited()


def test_admin_interaction_display_is_redacted_and_bounded() -> None:
    result = _sanitize_admin_interaction({
        "user_query": "a" * 3_000,
        "bot_response": "b" * 12_000,
        "contexts": ["c" * 5_000] * 12,
    })

    assert len(result["user_query"]) <= 2_000
    assert len(result["bot_response"]) <= 10_000
    assert len(result["contexts"]) == 10
    assert all(len(context) <= 4_000 for context in result["contexts"])
