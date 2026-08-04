from __future__ import annotations

import socket
import pytest

_real_connect = socket.socket.connect


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "live: Mark test as requiring live network / external provider access"
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-live", default=False):
        skip_live = pytest.mark.skip(reason="Skipping live test (use --run-live to run)")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip_live)


def pytest_addoption(parser):
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="Run live integration tests requiring external network access",
    )


@pytest.fixture(autouse=True)
def block_external_network(request, monkeypatch):
    """
    Autouse fixture that prevents real remote network connections during unit tests.
    Local loopback connections (127.0.0.1 / localhost) used by asyncio internal self-pipes are allowed.
    Tests marked with @pytest.mark.live bypass this guard.
    """
    if "live" in request.keywords:
        return

    def guarded_connect(self, address):
        host = ""
        if isinstance(address, tuple) and len(address) > 0:
            host = str(address[0])
        elif isinstance(address, str):
            host = address

        if host in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
            return _real_connect(self, address)

        raise RuntimeError(
            f"Real external network connection to '{host}' blocked during evaluation unit tests! "
            "Use test doubles / mocks or mark test with @pytest.mark.live."
        )

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
