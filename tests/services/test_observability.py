import ast
from pathlib import Path
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


def test_instrumented_service_functions_do_not_capture_arguments() -> None:
    services = Path(__file__).parents[2] / "app" / "services"
    decorated_functions = []

    for source_path in services.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and isinstance(decorator.func.value, ast.Name)
                    and decorator.func.value.id == "logfire"
                    and decorator.func.attr == "instrument"
                ):
                    continue
                decorated_functions.append(f"{source_path}:{node.name}")
                extract_args = next(
                    (
                        keyword.value
                        for keyword in decorator.keywords
                        if keyword.arg == "extract_args"
                    ),
                    None,
                )
                assert isinstance(extract_args, ast.Constant) and extract_args.value is False, (
                    f"{source_path}:{node.name} must opt out of Logfire argument capture"
                )

    assert decorated_functions


def test_logfire_error_fields_do_not_store_raw_exception_messages() -> None:
    app_root = Path(__file__).parents[2] / "app"
    violations = []

    for source_path in app_root.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            owner = node.func.value
            if not isinstance(owner, ast.Name) or owner.id != "logfire":
                continue
            for keyword in node.keywords:
                if keyword.arg not in {"error", "err", "exception"}:
                    continue
                value = keyword.value
                if (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id == "str"
                ):
                    violations.append(f"{source_path}:{node.lineno}")

    assert violations == []
