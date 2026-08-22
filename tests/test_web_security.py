from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


def test_signed_client_id_rejects_tampering() -> None:
    from app.services.web_security import ClientIdentitySigner

    signer = ClientIdentitySigner("test-secret")
    token = signer.sign("client-123")

    assert signer.unsign(token) == "client-123"
    assert signer.unsign(token + "tampered") is None


def test_resolve_client_id_reuses_valid_cookie_and_rotates_invalid_cookie() -> None:
    from app.services.web_security import ClientIdentitySigner, resolve_client_id

    signer = ClientIdentitySigner("test-secret")
    valid = signer.sign("client-existing")

    assert resolve_client_id(valid, signer) == ("client-existing", False)
    rotated_id, should_set_cookie = resolve_client_id("invalid", signer)
    assert should_set_cookie is True
    assert rotated_id != "client-existing"
    assert len(rotated_id) == 36


def test_admin_credentials_fail_closed_when_not_configured() -> None:
    from app.services.web_security import AdminAuthState, verify_admin_credentials

    state = verify_admin_credentials(
        username="admin",
        password="password",
        settings=SimpleNamespace(ADMIN_USERNAME=None, ADMIN_PASSWORD=None),
    )

    assert state is AdminAuthState.UNAVAILABLE


@pytest.mark.parametrize(
    ("username", "password", "expected"),
    [
        ("portfolio", "correct-secret", True),
        ("portfolio", "wrong", False),
        ("wrong", "correct-secret", False),
    ],
)
def test_admin_credentials_require_exact_match(
    username: str, password: str, expected: bool
) -> None:
    from app.services.web_security import AdminAuthState, verify_admin_credentials

    state = verify_admin_credentials(
        username=username,
        password=password,
        settings=SimpleNamespace(
            ADMIN_USERNAME="portfolio", ADMIN_PASSWORD="correct-secret"
        ),
    )

    assert (state is AdminAuthState.AUTHENTICATED) is expected


def test_public_rate_limit_key_combines_client_and_ip() -> None:
    from app.services.web_security import public_rate_limit_key

    request = SimpleNamespace(
        state=SimpleNamespace(client_id="client-123"),
        client=SimpleNamespace(host="203.0.113.10"),
    )

    assert public_rate_limit_key(request) == "203.0.113.10:client-123"


def test_anonymous_middleware_sets_and_reuses_signed_cookie() -> None:
    from app.services.web_security import AnonymousClientMiddleware

    app = FastAPI()
    app.add_middleware(
        AnonymousClientMiddleware,
        secret="test-secret",
        cookie_name="vietlex_client",
        max_age=3600,
    )

    @app.get("/")
    async def identity(request: Request):
        return {"client_id": request.state.client_id}

    client = TestClient(app)
    first = client.get("/")
    second = client.get("/")

    assert first.status_code == 200
    assert first.cookies.get("vietlex_client")
    assert second.json()["client_id"] == first.json()["client_id"]


def test_csrf_header_dependency_accepts_matching_cookie() -> None:
    from fastapi import Depends

    from app.api.dependencies import verify_csrf_header

    app = FastAPI()

    @app.delete("/resource")
    async def remove(_token: str = Depends(verify_csrf_header)):
        return {"ok": True}

    client = TestClient(app)
    client.cookies.set("csrf_token", "known-token")

    assert client.delete(
        "/resource", headers={"X-CSRF-Token": "known-token"}
    ).status_code == 200
    assert client.delete(
        "/resource", headers={"X-CSRF-Token": "wrong-token"}
    ).status_code == 403
