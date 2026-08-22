import secrets

from fastapi import Depends, Form, Header, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import get_settings
from app.services.web_security import AdminAuthState, verify_admin_credentials


_admin_basic = HTTPBasic(auto_error=False)

# Dependency for CSRF token validation in form POST
async def verify_csrf(request: Request, csrf_token: str = Form(...)):
    cookie_token = request.cookies.get("csrf_token")
    if not cookie_token or not secrets.compare_digest(cookie_token, csrf_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token validation failed. Request blocked."
        )
    return csrf_token


async def verify_csrf_header(
    request: Request,
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
):
    cookie_token = request.cookies.get("csrf_token")
    if (
        not cookie_token
        or not csrf_token
        or not secrets.compare_digest(cookie_token, csrf_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token validation failed. Request blocked.",
        )
    return csrf_token


async def require_admin(
    credentials: HTTPBasicCredentials | None = Depends(_admin_basic),
):
    settings = get_settings()
    state = verify_admin_credentials(
        username=credentials.username if credentials else None,
        password=credentials.password if credentials else None,
        settings=settings,
    )
    if state is AdminAuthState.UNAVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin access is not configured.",
        )
    if state is not AdminAuthState.AUTHENTICATED:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
