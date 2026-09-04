from __future__ import annotations

from typing import Any

def configure_observability(settings: Any, logfire_module: Any | None = None) -> bool:
    """Configure Logfire once without ever exporting telemetry from tests."""
    is_test = settings.APP_ENV == "test"
    if is_test:
        # Keep unit-test imports fast and guarantee that an inherited token can
        # never start Logfire's background credential-validation thread.
        return False
    if logfire_module is None:
        import logfire as logfire_module
    options = {
        "send_to_logfire": "if-token-present",
        "service_name": settings.LOGFIRE_SERVICE_NAME,
        "environment": settings.APP_ENV,
        "inspect_arguments": False,
    }
    try:
        logfire_module.configure(**options)
    except Exception:
        # Telemetry must never be an application availability dependency.
        try:
            logfire_module.configure(
                send_to_logfire=False,
                service_name=settings.LOGFIRE_SERVICE_NAME,
                environment=settings.APP_ENV,
                inspect_arguments=False,
            )
        except Exception:
            pass
        return False
    return bool(settings.LOGFIRE_TOKEN)
