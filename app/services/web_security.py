from __future__ import annotations

import secrets
import uuid
from enum import Enum
from typing import Any

from itsdangerous import BadSignature, URLSafeSerializer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class AdminAuthState(str, Enum):
    AUTHENTICATED = "authenticated"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"


class ClientIdentitySigner:
    def __init__(self, secret: str) -> None:
        if not secret:
            raise ValueError("client identity secret must not be blank")
        self._serializer = URLSafeSerializer(secret, salt="vietlex-anonymous-client-v1")

    def sign(self, client_id: str) -> str:
        return self._serializer.dumps(client_id)

    def unsign(self, token: str | None) -> str | None:
        if not token:
            return None
        try:
            value = self._serializer.loads(token)
        except BadSignature:
            return None
        if not isinstance(value, str):
            return None
        try:
            return str(uuid.UUID(value)) if len(value) == 36 else value
        except ValueError:
            return None


def resolve_client_id(
    cookie_value: str | None, signer: ClientIdentitySigner
) -> tuple[str, bool]:
    existing = signer.unsign(cookie_value)
    if existing:
        return existing, False
    return str(uuid.uuid4()), True


def verify_admin_credentials(
    *, username: str | None, password: str | None, settings: Any
) -> AdminAuthState:
    configured_username = getattr(settings, "ADMIN_USERNAME", None)
    configured_password = getattr(settings, "ADMIN_PASSWORD", None)
    if not configured_username or not configured_password:
        return AdminAuthState.UNAVAILABLE
    username_ok = secrets.compare_digest(username or "", configured_username)
    password_ok = secrets.compare_digest(password or "", configured_password)
    return (
        AdminAuthState.AUTHENTICATED
        if username_ok and password_ok
        else AdminAuthState.DENIED
    )


def public_rate_limit_key(request: Any) -> str:
    client = getattr(request, "client", None)
    ip_address = getattr(client, "host", None) or "unknown"
    state = getattr(request, "state", None)
    client_id = getattr(state, "client_id", None) or "anonymous"
    return f"{ip_address}:{client_id}"


class AnonymousClientMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: Any,
        *,
        secret: str,
        cookie_name: str,
        max_age: int,
    ) -> None:
        super().__init__(app)
        self._signer = ClientIdentitySigner(secret)
        self._cookie_name = cookie_name
        self._max_age = max_age

    async def dispatch(self, request: Request, call_next):
        client_id, should_set_cookie = resolve_client_id(
            request.cookies.get(self._cookie_name), self._signer
        )
        request.state.client_id = client_id
        response = await call_next(request)
        if should_set_cookie:
            response.set_cookie(
                self._cookie_name,
                self._signer.sign(client_id),
                max_age=self._max_age,
                httponly=True,
                secure=request.url.scheme == "https",
                samesite="lax",
            )
        return response
