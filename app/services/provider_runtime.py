from __future__ import annotations

from collections import deque
from contextvars import ContextVar
from functools import wraps
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from threading import Lock
import time
from typing import Any


@dataclass(frozen=True)
class ProviderEvent:
    provider: str
    model: str
    use_case: str
    success: bool
    error_kind: str | None
    latency_ms: float | None
    fallback_used: bool
    timestamp: str
    prompt_token_count: int | None = None
    output_token_count: int | None = None
    thinking_token_count: int | None = None
    total_token_count: int | None = None
    call_kind: str = "llm"
    request_count: int | None = None


_events: deque[ProviderEvent] = deque(maxlen=200)
_lock = Lock()
_request_calls: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "provider_calls", default=None
)


def capture_provider_usage(operation):
    """Bind telemetry to one request; child tasks share its bounded event list."""

    @wraps(operation)
    async def wrapped(*args, **kwargs):
        token = _request_calls.set([])
        try:
            return await operation(*args, **kwargs)
        finally:
            _request_calls.reset(token)

    return wrapped


def current_provider_calls() -> list[dict[str, Any]] | None:
    calls = _request_calls.get()
    return [dict(call) for call in calls] if calls is not None else None


def record_provider_event(event: ProviderEvent) -> None:
    with _lock:
        _events.append(event)
    calls = _request_calls.get()
    if calls is not None:
        # Bound a single request without silently dropping token-bearing events.
        if len(calls) < 200:
            calls.append(asdict(event))
        else:
            calls[-1]['dropped_calls'] = calls[-1].get('dropped_calls', 0) + 1


def record_generation_result(result: Any, use_case: str) -> None:
    record_provider_event(
        ProviderEvent(
            provider=str(result.observed_provider)[:100],
            model=str(result.observed_model)[:200],
            use_case=use_case[:50],
            success=result.status == "success",
            error_kind=(
                None if result.status == "success" else str(result.status)[:50]
            ),
            latency_ms=result.provider_latency_ms,
            fallback_used=bool(result.fallback_used),
            timestamp=datetime.now(timezone.utc).isoformat(),
            prompt_token_count=result.prompt_token_count,
            output_token_count=result.output_token_count,
            thinking_token_count=result.thought_token_count,
            total_token_count=result.total_token_count,
        )
    )


def provider_status_snapshot(
    settings: Any, cooldowns: dict[str, float] | None = None
) -> list[dict[str, Any]]:
    configured = {
        "google_vertex_ai": not bool(settings.USE_LEGACY_FREE_PIPELINE),
        "openrouter": bool(settings.OPENROUTER_API_KEY),
        "gemini": bool(settings.GEMINI_API_KEY),
        "nvidia": bool(settings.NVIDIA_API_KEY),
        "groq": bool(settings.GROQ_API_KEY),
        "omnigate": bool(settings.LITELLM_MASTER_KEY),
    }
    with _lock:
        latest = {event.provider: event for event in _events}
    rows = []
    for provider, is_configured in configured.items():
        event = latest.get(provider)
        in_cooldown = bool((cooldowns or {}).get(provider, 0) > time.time())
        if not is_configured:
            state = "NOT CONFIGURED"
        elif in_cooldown:
            state = "COOLDOWN"
        elif event is None:
            state = "UNKNOWN"
        else:
            state = "HEALTHY" if event.success else "DEGRADED"
        rows.append(
            {
                "provider": provider,
                "configured": is_configured,
                "state": state,
                "recent": asdict(event) if event else None,
            }
        )
    return rows
