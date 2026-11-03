"""Request-scoped accounting for the provider HTTP transports this app owns.

This boundary covers Vertex model HTTP through injected HTTPX clients and the
dedicated HTTPX client used by direct LLM fallbacks. OAuth refresh, vector
databases, optional judges, and unrelated HTTP clients are outside this scope.
"""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Lock
from typing import Any, Iterator

import httpx


MAX_PROVIDER_HTTP_EVENTS = 100
SUPPORTED_PROVIDER_HTTP_BOUNDARIES = (
    "vertex_model_httpx_sync",
    "vertex_model_httpx_async",
    "direct_llm_httpx_async",
)
EXCLUDED_PROVIDER_HTTP_BOUNDARIES = (
    "google_auth_token_refresh",
    "qdrant_and_pinecone_clients",
    "optional_judge_clients",
    "unrelated_web_and_database_clients",
)
_PROVIDERS = {
    "google_vertex_ai",
    "openrouter",
    "gemini",
    "nvidia",
    "groq",
    "omnigate",
    "unknown",
}


class ProviderHttpAttemptBudgetExceeded(RuntimeError):
    """A supported provider HTTP send was denied before its transport ran."""

    kind = "technical"
    error_code = "provider_http_attempt_limit_exceeded"

    def __init__(self, limit: int, attempts: int) -> None:
        self.limit = limit
        self.attempts = attempts
        super().__init__(self.error_code)


@dataclass(frozen=True)
class _AttemptPermit:
    event_id: int


class ProviderHttpAttemptBudget:
    """Thread-safe attempt ledger shared through copied task/thread contexts."""

    def __init__(self, limit: int | None = None) -> None:
        if limit is not None and (type(limit) is not int or limit < 1):
            raise ValueError("provider_http_attempt_limit_must_be_positive")
        self.limit = limit
        self._lock = Lock()
        self._events: deque[dict[str, Any]] = deque()
        self._event_by_id: dict[int, dict[str, Any]] = {}
        self._next_event_id = 1
        self._attempt_count = 0
        self._denied_count = 0
        self._success_count = 0
        self._failure_count = 0
        self._incomplete_count = 0
        self._active_attempt_ids: set[int] = set()

    def _append_event_locked(self, event: dict[str, Any]) -> int:
        event_id = self._next_event_id
        self._next_event_id += 1
        event["event_id"] = event_id
        if len(self._events) == MAX_PROVIDER_HTTP_EVENTS:
            dropped = self._events.popleft()
            self._event_by_id.pop(dropped["event_id"], None)
        self._events.append(event)
        self._event_by_id[event_id] = event
        return event_id

    def reserve(self, *, boundary: str, provider: str | None = None) -> _AttemptPermit:
        safe_boundary = (
            boundary if boundary in SUPPORTED_PROVIDER_HTTP_BOUNDARIES else "unknown"
        )
        safe_provider = provider if provider in _PROVIDERS else "unknown"
        with self._lock:
            if self.limit is not None and self._attempt_count >= self.limit:
                self._deny_locked(safe_boundary, safe_provider)
            self._attempt_count += 1
            event_id = self._append_event_locked(
                {
                    "boundary": safe_boundary,
                    "provider": safe_provider,
                    "outcome": "in_flight",
                    "status_code": None,
                    "error_kind": None,
                }
            )
            self._active_attempt_ids.add(event_id)
            return _AttemptPermit(event_id)

    def ensure_capacity(self, *, boundary: str, provider: str | None = None) -> None:
        """Deny already-exhausted work before expensive provider client setup."""

        safe_boundary = (
            boundary if boundary in SUPPORTED_PROVIDER_HTTP_BOUNDARIES else "unknown"
        )
        safe_provider = provider if provider in _PROVIDERS else "unknown"
        with self._lock:
            if self.limit is not None and self._attempt_count >= self.limit:
                self._deny_locked(safe_boundary, safe_provider)

    def _deny_locked(self, boundary: str, provider: str) -> None:
        self._denied_count += 1
        self._append_event_locked(
            {
                "boundary": boundary,
                "provider": provider,
                "outcome": "denied",
                "status_code": None,
                "error_kind": None,
            }
        )
        raise ProviderHttpAttemptBudgetExceeded(self.limit, self._attempt_count)

    def finish(
        self,
        permit: _AttemptPermit,
        *,
        status_code: int | None = None,
        error_kind: str | None = None,
        incomplete: bool = False,
    ) -> None:
        failed = error_kind is not None or (status_code is not None and status_code >= 400)
        outcome = "failure" if failed else "incomplete" if incomplete else "success"
        safe_status = status_code if type(status_code) is int and 100 <= status_code <= 599 else None
        safe_error = error_kind if error_kind and error_kind.isidentifier() else None
        with self._lock:
            if permit.event_id not in self._active_attempt_ids:
                return
            self._active_attempt_ids.remove(permit.event_id)
            if failed:
                self._failure_count += 1
            elif incomplete:
                self._incomplete_count += 1
            else:
                self._success_count += 1
            event = self._event_by_id.get(permit.event_id)
            if event is not None:
                event["outcome"] = outcome
                event["status_code"] = safe_status
                event["error_kind"] = safe_error

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema_version": "provider-http-budget-v1",
                "scope": "request_or_explicit_run_supported_transports",
                "coverage": {
                    "supported": list(SUPPORTED_PROVIDER_HTTP_BOUNDARIES),
                    "excluded": list(EXCLUDED_PROVIDER_HTTP_BOUNDARIES),
                    "complete_for_all_network": False,
                },
                "attempt_limit": self.limit,
                "attempt_count": self._attempt_count,
                "success_count": self._success_count,
                "failure_count": self._failure_count,
                "incomplete_count": self._incomplete_count,
                "in_flight_count": len(self._active_attempt_ids),
                "denied_count": self._denied_count,
                "event_count": self._attempt_count + self._denied_count,
                "dropped_event_count": (
                    self._attempt_count + self._denied_count - len(self._events)
                ),
                "events": [dict(event) for event in self._events],
            }


_current_budget: ContextVar[ProviderHttpAttemptBudget | None] = ContextVar(
    "provider_http_attempt_budget", default=None
)
_current_provider: ContextVar[str | None] = ContextVar(
    "provider_http_attempt_provider", default=None
)


def current_provider_http_budget() -> ProviderHttpAttemptBudget | None:
    return _current_budget.get()


def current_provider_http_budget_snapshot() -> dict[str, Any] | None:
    budget = current_provider_http_budget()
    return budget.snapshot() if budget is not None else None


@contextmanager
def provider_http_budget_scope(
    limit: int | None = None,
) -> Iterator[ProviderHttpAttemptBudget]:
    """Bind a run budget; nested scopes reuse the outer budget without reset."""

    existing = current_provider_http_budget()
    if existing is not None:
        yield existing
        return
    budget = ProviderHttpAttemptBudget(limit)
    token = _current_budget.set(budget)
    try:
        yield budget
    finally:
        _current_budget.reset(token)


@contextmanager
def provider_identity_scope(provider: str) -> Iterator[None]:
    safe_provider = provider if provider in _PROVIDERS else "unknown"
    token = _current_provider.set(safe_provider)
    try:
        yield
    finally:
        _current_provider.reset(token)


def _provider_for_transport(provider: str | None) -> str:
    candidate = provider or _current_provider.get() or "unknown"
    return candidate if candidate in _PROVIDERS else "unknown"


class _SyncAttemptStream(httpx.SyncByteStream):
    def __init__(self, stream: httpx.SyncByteStream, completion: "_AttemptCompletion") -> None:
        self._stream = stream
        self._completion = completion

    def __iter__(self):
        try:
            yield from self._stream
        except GeneratorExit:
            self._completion.finish(incomplete=True)
            raise
        except BaseException as error:
            self._completion.finish(error_kind=type(error).__name__)
            raise
        else:
            self._completion.finish()

    def close(self) -> None:
        try:
            self._stream.close()
        except BaseException as error:
            self._completion.finish(error_kind=type(error).__name__)
            raise
        else:
            self._completion.finish(incomplete=True)


class _AsyncAttemptStream(httpx.AsyncByteStream):
    def __init__(self, stream: httpx.AsyncByteStream, completion: "_AttemptCompletion") -> None:
        self._stream = stream
        self._completion = completion

    async def __aiter__(self):
        try:
            async for chunk in self._stream:
                yield chunk
        except GeneratorExit:
            self._completion.finish(incomplete=True)
            raise
        except BaseException as error:
            self._completion.finish(error_kind=type(error).__name__)
            raise
        else:
            self._completion.finish()

    async def aclose(self) -> None:
        try:
            await self._stream.aclose()
        except BaseException as error:
            self._completion.finish(error_kind=type(error).__name__)
            raise
        else:
            self._completion.finish(incomplete=True)


class _AttemptCompletion:
    def __init__(
        self,
        budget: ProviderHttpAttemptBudget,
        permit: _AttemptPermit,
        status_code: int,
    ) -> None:
        self._budget = budget
        self._permit = permit
        self._status_code = status_code
        self._lock = Lock()
        self._finished = False

    def finish(
        self, *, error_kind: str | None = None, incomplete: bool = False
    ) -> None:
        with self._lock:
            if self._finished:
                return
            self._finished = True
        self._budget.finish(
            self._permit,
            status_code=self._status_code,
            error_kind=error_kind,
            incomplete=incomplete,
        )


def _track_sync_response(
    response: httpx.Response,
    budget: ProviderHttpAttemptBudget,
    permit: _AttemptPermit,
) -> None:
    completion = _AttemptCompletion(budget, permit, response.status_code)
    # HTTPX MockTransport and custom transports may hand back an already buffered
    # body. In that case reading it is complete before control returns here.
    if hasattr(response, "_content"):
        completion.finish()
        return
    if not isinstance(response.stream, httpx.SyncByteStream):
        completion.finish(error_kind="UnsupportedResponseStream")
        raise TypeError("provider_sync_response_stream_unsupported")
    if response.is_closed:
        completion.finish(incomplete=True)
        return
    response.stream = _SyncAttemptStream(response.stream, completion)


def _track_async_response(
    response: httpx.Response,
    budget: ProviderHttpAttemptBudget,
    permit: _AttemptPermit,
) -> None:
    completion = _AttemptCompletion(budget, permit, response.status_code)
    if hasattr(response, "_content"):
        completion.finish()
        return
    if not isinstance(response.stream, httpx.AsyncByteStream):
        completion.finish(error_kind="UnsupportedResponseStream")
        raise TypeError("provider_async_response_stream_unsupported")
    if response.is_closed:
        completion.finish(incomplete=True)
        return
    response.stream = _AsyncAttemptStream(response.stream, completion)


class ProviderHttpSyncTransport(httpx.BaseTransport):
    def __init__(
        self,
        transport: httpx.BaseTransport,
        *,
        boundary: str,
        provider: str | None = None,
    ) -> None:
        self._transport = transport
        self._boundary = boundary
        self._provider = provider

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        budget = current_provider_http_budget()
        if budget is None:
            return self._transport.handle_request(request)
        permit = budget.reserve(
            boundary=self._boundary,
            provider=_provider_for_transport(self._provider),
        )
        try:
            response = self._transport.handle_request(request)
            _track_sync_response(response, budget, permit)
        except BaseException as error:
            budget.finish(permit, error_kind=type(error).__name__)
            raise
        return response

    def close(self) -> None:
        self._transport.close()


class ProviderHttpAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        transport: httpx.AsyncBaseTransport,
        *,
        boundary: str,
        provider: str | None = None,
    ) -> None:
        self._transport = transport
        self._boundary = boundary
        self._provider = provider

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        budget = current_provider_http_budget()
        if budget is None:
            return await self._transport.handle_async_request(request)
        permit = budget.reserve(
            boundary=self._boundary,
            provider=_provider_for_transport(self._provider),
        )
        try:
            response = await self._transport.handle_async_request(request)
            _track_async_response(response, budget, permit)
        except BaseException as error:
            budget.finish(permit, error_kind=type(error).__name__)
            raise
        return response

    async def aclose(self) -> None:
        await self._transport.aclose()


def create_vertex_httpx_clients(
    *, timeout_seconds: float, verify: Any
) -> tuple[httpx.Client, httpx.AsyncClient]:
    """Create HTTPX clients using the application's verified trust context."""

    timeout = httpx.Timeout(timeout_seconds)
    limits = httpx.Limits()
    sync_client = httpx.Client(
        timeout=timeout,
        verify=verify,
        limits=limits,
        follow_redirects=True,
        trust_env=True,
    )
    try:
        async_client = httpx.AsyncClient(
            timeout=timeout,
            verify=verify,
            limits=limits,
            follow_redirects=True,
            trust_env=True,
        )
        _wrap_client_transports(
            sync_client,
            ProviderHttpSyncTransport,
            boundary="vertex_model_httpx_sync",
            provider="google_vertex_ai",
        )
        _wrap_client_transports(
            async_client,
            ProviderHttpAsyncTransport,
            boundary="vertex_model_httpx_async",
            provider="google_vertex_ai",
        )
    except BaseException:
        sync_client.close()
        if "async_client" in locals() and not async_client.is_closed:
            import asyncio

            try:
                asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(async_client.aclose())
        raise
    return sync_client, async_client


def _wrap_client_transports(
    client: httpx.Client | httpx.AsyncClient,
    wrapper_type: type[ProviderHttpSyncTransport] | type[ProviderHttpAsyncTransport],
    *,
    boundary: str,
    provider: str | None,
) -> None:
    """Wrap HTTPX 0.28.1's selected base and proxy transports without rebuilding routing.

    HTTPX only builds its environment proxy mounts when no custom transport is
    supplied. Constructing the normal client first preserves HTTP_PROXY,
    HTTPS_PROXY, ALL_PROXY and NO_PROXY behavior, including its TLS and pool
    configuration. Its private base/mount transport slots are then wrapped so
    every selected network route remains within the attempt budget.
    """

    base = getattr(client, "_transport", None)
    mounts = getattr(client, "_mounts", None)
    if base is None or not isinstance(mounts, dict):
        raise RuntimeError("provider_httpx_transport_routing_unsupported")
    wrapped_by_id: dict[int, Any] = {}

    def wrap(transport: Any) -> Any:
        if transport is None:
            return None
        key = id(transport)
        if key not in wrapped_by_id:
            wrapped_by_id[key] = wrapper_type(
                transport,
                boundary=boundary,
                provider=provider,
            )
        return wrapped_by_id[key]

    client._transport = wrap(base)
    client._mounts = {
        pattern: wrap(transport) for pattern, transport in mounts.items()
    }
