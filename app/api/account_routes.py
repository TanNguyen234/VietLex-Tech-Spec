from __future__ import annotations

import json
import secrets

import logfire
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from app.paths import APP_ROOT
from pymongo.errors import DuplicateKeyError

from app.account_database import (
    claim_anonymous_history,
    consume_account_token,
    create_account_token,
    create_auth_session,
    create_user,
    delete_account,
    delete_account_history,
    export_account,
    get_user_by_email,
    list_auth_sessions,
    mark_last_login,
    mark_user_verified,
    revoke_auth_session,
    revoke_auth_session_by_id,
    revoke_other_auth_sessions,
    update_password,
)
from app.api.dependencies import optional_user, require_user, verify_csrf
from app.config import get_settings
from app.services.accounts import (
    hash_password,
    new_token,
    normalize_email,
    verify_password,
)
from app.services.email_delivery import SmtpEmailSender
from app.services.web_security import authentication_rate_limit_key
from app.rate_limit import limiter


router = APIRouter()
templates = Jinja2Templates(directory=APP_ROOT / "templates")
settings = get_settings()
_GENERIC_EMAIL_MESSAGE = (
    "Nếu địa chỉ hợp lệ, VietLex đã gửi hướng dẫn tới email của bạn."
)


def get_email_sender() -> SmtpEmailSender:
    return SmtpEmailSender(settings)


def _form_response(
    request: Request,
    *,
    mode: str,
    message: str = "",
    token: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    csrf_token = secrets.token_hex(32)
    response = templates.TemplateResponse(
        request,
        "account_form.html",
        {
            "mode": mode,
            "message": message,
            "token": token,
            "csrf_token": csrf_token,
        },
        status_code=status_code,
    )
    response.set_cookie(
        "csrf_token",
        csrf_token,
        httponly=True,
        secure=settings.APP_ENV == "production" or request.url.scheme == "https",
        samesite="strict",
    )
    return response


def _valid_password(password: str) -> bool:
    return 10 <= len(password) <= 256


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return _form_response(request, mode="register")


@router.post("/register", response_class=HTMLResponse)
@limiter.limit(settings.SESSION_RATE_LIMIT, key_func=authentication_rate_limit_key)
async def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    _csrf: str = Depends(verify_csrf),
):
    if not settings.ACCOUNT_EMAIL_ENABLED:
        return _form_response(
            request,
            mode="register",
            message="Đăng ký email hiện chưa được cấu hình.",
            status_code=503,
        )
    try:
        normalized = normalize_email(email)
    except ValueError:
        return _form_response(
            request, mode="register", message=_GENERIC_EMAIL_MESSAGE
        )
    if not _valid_password(password):
        return _form_response(
            request,
            mode="register",
            message="Mật khẩu cần từ 10 đến 256 ký tự.",
            status_code=400,
        )
    user = await get_user_by_email(normalized)
    if user is None:
        try:
            user = await create_user(normalized, hash_password(password))
        except DuplicateKeyError:
            user = await get_user_by_email(normalized)
    if user and not user.get("email_verified"):
        token = new_token()
        await create_account_token(str(user["_id"]), "verify_email", token)
        try:
            await get_email_sender().send_verification(normalized, token)
        except Exception as error:
            logfire.error(
                "Account verification email delivery failed: {error_kind}",
                error_kind=type(error).__name__,
            )
    return _form_response(
        request, mode="register", message=_GENERIC_EMAIL_MESSAGE
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return _form_response(request, mode="login")


@router.post("/login")
@limiter.limit(settings.SESSION_RATE_LIMIT, key_func=authentication_rate_limit_key)
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    _csrf: str = Depends(verify_csrf),
):
    try:
        user = await get_user_by_email(normalize_email(email))
    except ValueError:
        user = None
    if (
        not user
        or not user.get("email_verified")
        or user.get("status", "active") != "active"
        or not verify_password(password, str(user.get("password_hash", "")))
    ):
        return _form_response(
            request,
            mode="login",
            message="Email hoặc mật khẩu không hợp lệ.",
            status_code=401,
        )
    token = new_token()
    user_id = str(user["_id"])
    await create_auth_session(user_id, token)
    await mark_last_login(user_id)
    await claim_anonymous_history(
        user_id, getattr(request.state, "client_id", "legacy")
    )
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        settings.AUTH_COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.APP_ENV == "production" or request.url.scheme == "https",
        samesite="lax",
        max_age=60 * 60 * 24 * settings.AUTH_SESSION_DAYS,
    )
    return response


@router.post("/logout")
async def logout(
    request: Request,
    _csrf: str = Depends(verify_csrf),
):
    await revoke_auth_session(request.cookies.get(settings.AUTH_COOKIE_NAME))
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(settings.AUTH_COOKIE_NAME)
    return response


@router.get("/verify-email", response_class=HTMLResponse)
async def verify_email(request: Request, token: str = ""):
    user_id = await consume_account_token(token, "verify_email") if token else None
    if user_id and await mark_user_verified(user_id):
        message = "Email của bạn đã được xác minh. Bạn có thể đăng nhập."
    else:
        message = "Liên kết xác minh không hợp lệ hoặc đã hết hạn."
    return _form_response(request, mode="message", message=message)


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return _form_response(request, mode="forgot")


@router.post("/forgot-password", response_class=HTMLResponse)
@limiter.limit(settings.SESSION_RATE_LIMIT, key_func=authentication_rate_limit_key)
async def forgot_password(
    request: Request,
    email: str = Form(...),
    _csrf: str = Depends(verify_csrf),
):
    try:
        normalized = normalize_email(email)
        user = await get_user_by_email(normalized)
    except ValueError:
        normalized, user = "", None
    if user and user.get("email_verified") and settings.ACCOUNT_EMAIL_ENABLED:
        token = new_token()
        await create_account_token(str(user["_id"]), "reset_password", token)
        try:
            await get_email_sender().send_password_reset(normalized, token)
        except Exception as error:
            logfire.error(
                "Password reset email delivery failed: {error_kind}",
                error_kind=type(error).__name__,
            )
    return _form_response(
        request, mode="forgot", message=_GENERIC_EMAIL_MESSAGE
    )


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, token: str = ""):
    return _form_response(request, mode="reset", token=token)


@router.post("/reset-password", response_class=HTMLResponse)
@limiter.limit(settings.SESSION_RATE_LIMIT, key_func=authentication_rate_limit_key)
async def reset_password(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    _csrf: str = Depends(verify_csrf),
):
    if not _valid_password(password):
        return _form_response(
            request,
            mode="reset",
            token=token,
            message="Mật khẩu cần từ 10 đến 256 ký tự.",
            status_code=400,
        )
    user_id = await consume_account_token(token, "reset_password")
    if user_id and await update_password(user_id, hash_password(password)):
        message = "Mật khẩu đã được cập nhật. Bạn có thể đăng nhập."
    else:
        message = "Liên kết đặt lại mật khẩu không hợp lệ hoặc đã hết hạn."
    return _form_response(request, mode="message", message=message)


@router.get("/account")
async def account_entry(user=Depends(optional_user)):
    """Give navigation a usable destination with or without a session."""
    return RedirectResponse("/settings" if user else "/login", status_code=303)


@router.get("/settings", response_class=HTMLResponse)
async def account_settings(request: Request, user=Depends(require_user)):
    csrf_token = secrets.token_hex(32)
    sessions = await list_auth_sessions(
        str(user["_id"]),
        current_token=request.cookies.get(settings.AUTH_COOKIE_NAME),
    )
    response = templates.TemplateResponse(
        request,
        "settings.html",
        {"user": user, "sessions": sessions, "csrf_token": csrf_token},
    )
    response.set_cookie(
        "csrf_token",
        csrf_token,
        httponly=True,
        secure=settings.APP_ENV == "production" or request.url.scheme == "https",
        samesite="strict",
    )
    return response


@router.post("/account/sessions/{session_id}/revoke")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def account_session_revoke(
    request: Request,
    session_id: str,
    _csrf: str = Depends(verify_csrf),
    user=Depends(require_user),
):
    await revoke_auth_session_by_id(str(user["_id"]), session_id[:100])
    return RedirectResponse("/account", status_code=303)


@router.post("/account/sessions/revoke-others")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def account_sessions_revoke_others(
    request: Request,
    _csrf: str = Depends(verify_csrf),
    user=Depends(require_user),
):
    token = request.cookies.get(settings.AUTH_COOKIE_NAME)
    if token:
        await revoke_other_auth_sessions(str(user["_id"]), token)
    return RedirectResponse("/settings", status_code=303)


@router.get("/account/export")
async def account_export(user=Depends(require_user)):
    payload = await export_account(str(user["_id"])) or {}
    return Response(
        json.dumps(payload, ensure_ascii=False, default=str, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="vietlex-account.json"'
        },
    )


@router.post("/account/history/delete")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def account_history_delete(
    request: Request,
    _csrf: str = Depends(verify_csrf),
    user=Depends(require_user),
):
    await delete_account_history(str(user["_id"]))
    return RedirectResponse("/settings", status_code=303)


@router.post("/account/delete")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def account_delete(
    request: Request,
    _csrf: str = Depends(verify_csrf),
    user=Depends(require_user),
):
    await delete_account(str(user["_id"]))
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(settings.AUTH_COOKIE_NAME)
    return response
