from types import SimpleNamespace

import pytest


class _FakeSmtp:
    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.login_args = None
        self.messages = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def starttls(self, *, context) -> None:
        assert context is not None
        self.started_tls = True

    def login(self, user: str, password: str) -> None:
        self.login_args = (user, password)

    def send_message(self, message) -> None:
        self.messages.append(message)


@pytest.mark.asyncio
async def test_smtp_sender_uses_starttls_and_builds_verification_link() -> None:
    from app.services.email_delivery import SmtpEmailSender

    created = []

    def factory(host: str, port: int, timeout: float):
        smtp = _FakeSmtp(host, port, timeout)
        created.append(smtp)
        return smtp

    sender = SmtpEmailSender(
        SimpleNamespace(
            EMAIL_USER="mailer@example.com",
            EMAIL_PASS="app-password",
            EMAIL_FROM="VietLex <mailer@example.com>",
            SMTP_HOST="smtp.example.com",
            SMTP_PORT=587,
            PUBLIC_BASE_URL="https://vietlex.example/",
        ),
        smtp_factory=factory,
    )

    await sender.send_verification("person@example.com", "verify-token")

    smtp = created[0]
    assert (smtp.host, smtp.port) == ("smtp.example.com", 587)
    assert smtp.started_tls is True
    assert smtp.login_args == ("mailer@example.com", "app-password")
    message = smtp.messages[0]
    assert message["To"] == "person@example.com"
    assert "https://vietlex.example/verify-email?token=verify-token" in message.get_content()
    assert "app-password" not in message.as_string()


@pytest.mark.asyncio
async def test_smtp_sender_builds_password_reset_link() -> None:
    from app.services.email_delivery import SmtpEmailSender

    created = []
    sender = SmtpEmailSender(
        SimpleNamespace(
            EMAIL_USER="mailer@example.com",
            EMAIL_PASS="secret",
            EMAIL_FROM=None,
            SMTP_HOST="smtp.example.com",
            SMTP_PORT=587,
            PUBLIC_BASE_URL="https://vietlex.example",
        ),
        smtp_factory=lambda host, port, timeout: (
            created.append(_FakeSmtp(host, port, timeout)) or created[-1]
        ),
    )

    await sender.send_password_reset("person@example.com", "reset-token")

    message = created[0].messages[0]
    assert message["From"] == "mailer@example.com"
    assert "https://vietlex.example/reset-password?token=reset-token" in message.get_content()
