from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


def _client(monkeypatch, user):
    import app.api.dependencies as dependencies

    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: SimpleNamespace(
            AUTH_COOKIE_NAME="vietlex_auth",
            LEGACY_ADMIN_BASIC_ENABLED=False,
        ),
    )
    monkeypatch.setattr(
        dependencies,
        "resolve_auth_session",
        AsyncMock(return_value=user),
    )
    app = FastAPI()

    @app.get("/admin-test")
    async def admin_test(admin=Depends(dependencies.require_admin)):
        return {"id": admin["_id"]}

    return TestClient(app)


def test_normal_account_cannot_access_admin(monkeypatch) -> None:
    client = _client(monkeypatch, {"_id": "user-1", "role": "user", "status": "active"})
    assert client.get("/admin-test", cookies={"vietlex_auth": "token"}).status_code == 403


def test_admin_account_can_access_admin(monkeypatch) -> None:
    client = _client(monkeypatch, {"_id": "admin-1", "role": "admin", "status": "active"})
    response = client.get("/admin-test", cookies={"vietlex_auth": "token"})
    assert response.status_code == 200
    assert response.json() == {"id": "admin-1"}


def test_legacy_basic_is_fail_closed_by_default(monkeypatch) -> None:
    client = _client(monkeypatch, None)
    response = client.get("/admin-test", auth=("legacy", "secret"))
    assert response.status_code == 401
