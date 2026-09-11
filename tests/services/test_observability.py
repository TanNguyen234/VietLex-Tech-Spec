from types import SimpleNamespace


class FakeLogfire:
    def __init__(self):
        self.calls = []

    def configure(self, **kwargs):
        self.calls.append(kwargs)


class FailingOnceLogfire(FakeLogfire):
    def configure(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise RuntimeError("export unavailable")


class FailingAlwaysLogfire(FakeLogfire):
    def configure(self, **kwargs):
        self.calls.append(kwargs)
        raise RuntimeError("logfire unavailable")


def test_test_environment_never_exports_logfire() -> None:
    from app.services.observability import configure_observability

    fake = FakeLogfire()
    enabled = configure_observability(
        SimpleNamespace(
            APP_ENV="test",
            LOGFIRE_TOKEN="must-not-be-used",
            LOGFIRE_SERVICE_NAME="vietlex-test",
        ),
        fake,
    )

    assert enabled is False
    assert fake.calls == []


def test_non_test_environment_uses_logfire_environment_contract() -> None:
    from app.services.observability import configure_observability

    fake = FakeLogfire()
    assert configure_observability(
        SimpleNamespace(
            APP_ENV="production",
            LOGFIRE_TOKEN="configured",
            LOGFIRE_SERVICE_NAME="vietlex",
        ),
        fake,
    ) is True
    assert fake.calls[0]["send_to_logfire"] == "if-token-present"
    assert fake.calls[0]["token"] == "configured"


def test_logfire_export_failure_falls_back_to_local_disabled_mode() -> None:
    from app.services.observability import configure_observability

    fake = FailingOnceLogfire()
    enabled = configure_observability(
        SimpleNamespace(
            APP_ENV="production",
            LOGFIRE_TOKEN="configured",
            LOGFIRE_SERVICE_NAME="vietlex",
        ),
        fake,
    )

    assert enabled is False
    assert fake.calls[0]["send_to_logfire"] == "if-token-present"
    assert fake.calls[1]["send_to_logfire"] is False


def test_total_logfire_failure_does_not_break_startup() -> None:
    from app.services.observability import configure_observability

    assert configure_observability(
        SimpleNamespace(
            APP_ENV="production",
            LOGFIRE_TOKEN="configured",
            LOGFIRE_SERVICE_NAME="vietlex",
        ),
        FailingAlwaysLogfire(),
    ) is False
