import importlib
import ssl

import pytest

from app import config


def _clients_module():
    return importlib.import_module("app.services.clients")


def test_system_ssl_context_keeps_certificate_verification_enabled() -> None:
    clients = _clients_module()

    context = clients.system_ssl_context()

    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_system_trust_store_installation_is_idempotent(monkeypatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(
        config.truststore,
        "inject_into_ssl",
        lambda: calls.append(True),
    )
    monkeypatch.setattr(config, "_SYSTEM_TRUST_INSTALLED", False)

    config.install_system_trust_store()
    config.install_system_trust_store()

    assert calls == [True]


@pytest.mark.asyncio
async def test_http_client_is_reused_and_closed_by_lifecycle() -> None:
    clients = _clients_module()

    first = clients.get_http_client()
    second = clients.get_http_client()
    assert first is second

    await clients.close_clients()
    assert first.is_closed

    replacement = clients.get_http_client()
    assert replacement is not first
    await clients.close_clients()
