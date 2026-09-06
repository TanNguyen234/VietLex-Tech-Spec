from __future__ import annotations

import re
import asyncio
import time

from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)
_WORKSPACE_UPLOAD_PATH = re.compile(r"^/workspaces/[^/]+/documents$")


class WorkspaceUploadBodyLimitMiddleware:
    """Reject oversized multipart bodies before Starlette parses or spools them."""

    def __init__(self, app, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.active = 0
        self.ip_windows = {}

    async def __call__(self, scope, receive, send) -> None:
        if (
            scope.get("type") != "http"
            or scope.get("method") != "POST"
            or not _WORKSPACE_UPLOAD_PATH.fullmatch(scope.get("path", ""))
        ):
            await self.app(scope, receive, send)
            return
        now = time.monotonic()
        self.ip_windows = {ip: times for ip, times in self.ip_windows.items() if times[-1] > now - 60}
        ip = (scope.get('client') or ('unknown',))[0]
        times = [stamp for stamp in self.ip_windows.get(ip, []) if stamp > now - 60]
        if len(times) >= 6 or (ip not in self.ip_windows and len(self.ip_windows) >= 1024):
            await JSONResponse({'detail': 'upload_rate_limit'}, status_code=429)(scope, receive, send)
            return
        if self.active >= 2:
            await JSONResponse({'detail': 'upload_capacity_limit'}, status_code=503)(scope, receive, send)
            return
        self.ip_windows[ip] = times + [now]
        self.active += 1
        try:
            await self._upload(scope, receive, send)
        finally:
            self.active -= 1

    async def _upload(self, scope, receive, send):
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = 0
        if declared > self.max_bytes:
            await JSONResponse(
                {"detail": "document_too_large"}, status_code=413
            )(scope, receive, send)
            return
        messages = []
        observed = 0
        deadline = time.monotonic() + 30
        while True:
            try:
                message = await asyncio.wait_for(receive(), timeout=max(0, deadline - time.monotonic()))
            except TimeoutError:
                await JSONResponse({'detail': 'upload_timeout'}, status_code=408)(scope, receive, send)
                return
            messages.append(message)
            if message.get("type") == "http.request":
                observed += len(message.get("body", b""))
                if observed > self.max_bytes:
                    await JSONResponse(
                        {"detail": "document_too_large"}, status_code=413
                    )(scope, receive, send)
                    return
                if not message.get("more_body", False):
                    break
            elif message.get("type") == "http.disconnect":
                break

        async def replay():
            if messages:
                return messages.pop(0)
            return {"type": "http.disconnect"}

        await self.app(scope, replay, send)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), camera=(), microphone=()"
        )
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path == '/admin' or request.url.path.startswith('/admin/'):
            response.headers['Cache-Control'] = 'no-store'
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        if request.url.scheme == "https" or forwarded_proto.split(",")[0].strip() == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response
