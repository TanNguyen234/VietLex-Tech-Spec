from __future__ import annotations

import asyncio
from email.message import EmailMessage
import smtplib
import ssl
from typing import Any, Callable
from urllib.parse import urlencode


class SmtpEmailSender:
    def __init__(
        self,
        settings: Any,
        *,
        smtp_factory: Callable[..., Any] = smtplib.SMTP,
    ) -> None:
        self._settings = settings
        self._smtp_factory = smtp_factory

    async def send_verification(self, email: str, token: str) -> None:
        await asyncio.to_thread(
            self._send,
            email,
            "Xác minh tài khoản VietLex",
            "Xác minh email của bạn tại:\n"
            + self._link("/verify-email", token),
        )

    async def send_password_reset(self, email: str, token: str) -> None:
        await asyncio.to_thread(
            self._send,
            email,
            "Đặt lại mật khẩu VietLex",
            "Đặt lại mật khẩu của bạn tại:\n"
            + self._link("/reset-password", token),
        )

    def _link(self, path: str, token: str) -> str:
        base = self._settings.PUBLIC_BASE_URL.rstrip("/")
        return f"{base}{path}?{urlencode({'token': token})}"

    def _send(self, recipient: str, subject: str, body: str) -> None:
        user = self._settings.EMAIL_USER
        password = self._settings.EMAIL_PASS
        if not user or not password:
            raise RuntimeError("SMTP credentials are not configured")
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self._settings.EMAIL_FROM or user
        message["To"] = recipient
        message.set_content(body)
        with self._smtp_factory(
            self._settings.SMTP_HOST,
            self._settings.SMTP_PORT,
            timeout=15.0,
        ) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(user, password)
            smtp.send_message(message)
