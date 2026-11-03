from __future__ import annotations

import asyncio
import json

import httpx
import pytest


def _api():
    from app.services import provider_http_budget

    return provider_http_budget


def test_budgeted_vertex_clients_keep_httpx_environment_proxy_routes(monkeypatch) -> None:
    api = _api()
    proxy_names = (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    )
    for name in proxy_names:
        monkeypatch.delenv(name, raising=False)
    proxy = "http://127.0.0.1:3128"
    monkeypatch.setenv("HTTP_PROXY", proxy)
    monkeypatch.setenv("HTTPS_PROXY", proxy)
    monkeypatch.setenv("ALL_PROXY", proxy)
    monkeypatch.setenv("NO_PROXY", "internal.example.invalid")

    sync_client, async_client = api.create_vertex_httpx_clients(
        timeout_seconds=3, verify=True
    )
    try:
        for client, wrapper_type in (
            (sync_client, api.ProviderHttpSyncTransport),
            (async_client, api.ProviderHttpAsyncTransport),
        ):
            proxied = client._transport_for_url(httpx.URL("https://external.example.invalid"))
            bypassed = client._transport_for_url(httpx.URL("https://internal.example.invalid"))
            assert isinstance(proxied, wrapper_type)
            assert proxied is not client._transport
            assert isinstance(bypassed, wrapper_type)
            assert bypassed is client._transport
            assert all(
                transport is None or isinstance(transport, wrapper_type)
                for transport in client._mounts.values()
            )
    finally:
        sync_client.close()
        import asyncio
        asyncio.run(async_client.aclose())


def test_direct_client_applies_pool_limits_to_proxy_and_no_proxy_transports(
    monkeypatch,
) -> None:
    api = _api()
    proxy_names = (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    )
    for name in proxy_names:
        monkeypatch.delenv(name, raising=False)
    proxy = "http://127.0.0.1:3128"
    monkeypatch.setenv("HTTP_PROXY", proxy)
    monkeypatch.setenv("HTTPS_PROXY", proxy)
    monkeypatch.setenv("ALL_PROXY", proxy)
    monkeypatch.setenv("NO_PROXY", "internal.example.invalid")

    import app.services.direct_llm as direct_llm

    client = direct_llm.create_direct_httpx_client()
    try:
        assert isinstance(client._transport, api.ProviderHttpAsyncTransport)
        proxied = client._transport_for_url(httpx.URL("https://external.example.invalid"))
        bypassed = client._transport_for_url(httpx.URL("https://internal.example.invalid"))
        assert isinstance(proxied, api.ProviderHttpAsyncTransport)
        assert proxied is not client._transport
        assert isinstance(bypassed, api.ProviderHttpAsyncTransport)
        assert bypassed is client._transport
        selected = [client._transport, *(t for t in client._mounts.values() if t)]
        for wrapped in selected:
            pool = wrapped._transport._pool
            assert pool._max_connections == 50
            assert pool._max_keepalive_connections == 20
    finally:
        import asyncio
        asyncio.run(client.aclose())


def test_sync_response_body_error_is_counted_as_failure_only_after_read() -> None:
    api = _api()

    class LateReadError(httpx.SyncByteStream):
        def __iter__(self):
            yield b"partial"
            raise httpx.ReadError("private body and auth data")

        def close(self):
            pass

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, stream=LateReadError())

    client = httpx.Client(
        transport=api.ProviderHttpSyncTransport(
            httpx.MockTransport(handler), boundary="vertex_model_httpx_sync"
        )
    )
    with api.provider_http_budget_scope(limit=None) as budget:
        response = client.send(client.build_request("GET", "https://example.invalid"), stream=True)
        assert budget.snapshot()["success_count"] == 0
        assert budget.snapshot()["failure_count"] == 0
        with pytest.raises(httpx.ReadError):
            response.read()
        response.close()
        snapshot = budget.snapshot()
    client.close()

    assert snapshot["success_count"] == 0
    assert snapshot["failure_count"] == 1
    assert snapshot["events"][0]["error_kind"] == "ReadError"
    snapshot_json = json.dumps(snapshot)
    assert "private body and auth data" not in snapshot_json
    assert "example.invalid" not in snapshot_json


@pytest.mark.asyncio
async def test_async_response_body_error_is_counted_once_and_close_is_incomplete() -> None:
    api = _api()

    class LateReadError(httpx.AsyncByteStream):
        def __init__(self, *, fail: bool) -> None:
            self.fail = fail

        async def __aiter__(self):
            yield b"partial"
            if self.fail:
                raise httpx.ReadError("private body and auth data")

        async def aclose(self):
            pass

    replies = iter(("fail", "success", "close"))

    def handler(request: httpx.Request) -> httpx.Response:
        behavior = next(replies)
        return httpx.Response(
            200,
            request=request,
            stream=LateReadError(fail=behavior == "fail"),
        )

    async with httpx.AsyncClient(
        transport=api.ProviderHttpAsyncTransport(
            httpx.MockTransport(handler), boundary="direct_llm_httpx_async"
        )
    ) as client:
        with api.provider_http_budget_scope(limit=None) as budget:
            failed = await client.send(
                client.build_request("GET", "https://example.invalid/fail"), stream=True
            )
            with pytest.raises(httpx.ReadError):
                await failed.aread()
            await failed.aclose()

            succeeded = await client.send(
                client.build_request("GET", "https://example.invalid/success"), stream=True
            )
            assert await succeeded.aread() == b"partial"
            await succeeded.aclose()

            closed = await client.send(
                client.build_request("GET", "https://example.invalid/close"), stream=True
            )
            await closed.aclose()
            snapshot = budget.snapshot()

    assert snapshot["success_count"] == 1
    assert snapshot["failure_count"] == 1
    assert snapshot["incomplete_count"] == 1
    assert [event["outcome"] for event in snapshot["events"]] == [
        "failure", "success", "incomplete"
    ]


def test_sync_stream_success_and_early_close_finalize_once() -> None:
    api = _api()

    class BodyStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"body"

        def close(self):
            pass

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, stream=BodyStream())

    client = httpx.Client(
        transport=api.ProviderHttpSyncTransport(
            httpx.MockTransport(handler), boundary="vertex_model_httpx_sync"
        )
    )
    with api.provider_http_budget_scope(limit=None) as budget:
        succeeded = client.send(
            client.build_request("GET", "https://example.invalid/success"), stream=True
        )
        assert succeeded.read() == b"body"
        succeeded.close()

        closed = client.send(
            client.build_request("GET", "https://example.invalid/close"), stream=True
        )
        closed.close()
        snapshot = budget.snapshot()
    client.close()

    assert snapshot["success_count"] == 1
    assert snapshot["failure_count"] == 0
    assert snapshot["incomplete_count"] == 1
    assert [event["outcome"] for event in snapshot["events"]] == [
        "success", "incomplete"
    ]


def test_sync_partial_response_iterator_close_is_incomplete() -> None:
    api = _api()

    class BodyStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"first"
            yield b"second"

        def close(self):
            pass

    client = httpx.Client(
        transport=api.ProviderHttpSyncTransport(
            httpx.MockTransport(
                lambda request: httpx.Response(
                    200, request=request, stream=BodyStream()
                )
            ),
            boundary="vertex_model_httpx_sync",
        )
    )
    with api.provider_http_budget_scope(limit=None) as budget:
        response = client.send(
            client.build_request("GET", "https://example.invalid/partial"),
            stream=True,
        )
        iterator = response.iter_raw()
        assert next(iterator) == b"first"
        iterator.close()
        response.close()
        snapshot = budget.snapshot()
    client.close()

    assert snapshot["failure_count"] == 0
    assert snapshot["incomplete_count"] == 1
    assert snapshot["in_flight_count"] == 0
    assert snapshot["events"][0]["outcome"] == "incomplete"


@pytest.mark.asyncio
async def test_async_partial_response_iterator_close_is_incomplete() -> None:
    api = _api()

    class BodyStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"first"
            yield b"second"

        async def aclose(self):
            pass

    async with httpx.AsyncClient(
        transport=api.ProviderHttpAsyncTransport(
            httpx.MockTransport(
                lambda request: httpx.Response(
                    200, request=request, stream=BodyStream()
                )
            ),
            boundary="direct_llm_httpx_async",
        )
    ) as client:
        with api.provider_http_budget_scope(limit=None) as budget:
            response = await client.send(
                client.build_request("GET", "https://example.invalid/partial"),
                stream=True,
            )
            # AsyncClient wraps the transport stream in BoundAsyncStream; use
            # its recorded delegate to close the attempt stream's own iterator.
            iterator = response.stream._stream.__aiter__()
            assert await anext(iterator) == b"first"
            await iterator.aclose()
            await response.aclose()
            snapshot = budget.snapshot()

    assert snapshot["failure_count"] == 0
    assert snapshot["incomplete_count"] == 1
    assert snapshot["in_flight_count"] == 0
    assert snapshot["events"][0]["outcome"] == "incomplete"


def test_already_consumed_mock_response_is_finalized_once() -> None:
    api = _api()
    client = httpx.Client(
        transport=api.ProviderHttpSyncTransport(
            httpx.MockTransport(lambda request: httpx.Response(200, request=request, content=b"ok")),
            boundary="vertex_model_httpx_sync",
        )
    )
    with api.provider_http_budget_scope(limit=None) as budget:
        assert client.get("https://example.invalid").content == b"ok"
        snapshot = budget.snapshot()
    client.close()

    assert snapshot["success_count"] == 1
    assert snapshot["failure_count"] == 0
    assert snapshot["incomplete_count"] == 0


def test_hidden_httpx_redirect_consumes_budget_for_each_send() -> None:
    api = _api()
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.url.path)
        if request.url.path == "/model":
            return httpx.Response(
                307,
                request=request,
                headers={"Location": "/redirected-model"},
                content=b"",
            )
        return httpx.Response(200, request=request, content=b"ok")

    client = httpx.Client(
        transport=api.ProviderHttpSyncTransport(
            httpx.MockTransport(handler), boundary="vertex_model_httpx_sync"
        ),
        follow_redirects=True,
    )
    with api.provider_http_budget_scope(limit=1) as budget:
        with pytest.raises(api.ProviderHttpAttemptBudgetExceeded):
            client.get("https://example.invalid/model")
        snapshot = budget.snapshot()
    client.close()

    assert sent == ["/model"]
    assert snapshot["attempt_count"] == 1
    assert snapshot["success_count"] == 1
    assert snapshot["denied_count"] == 1


@pytest.mark.asyncio
async def test_concurrent_async_sends_reserve_one_shared_cap_before_transport() -> None:
    api = _api()
    sends: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sends.append(request.url.path)
        return httpx.Response(200, request=request)

    transport = httpx.MockTransport(handler)
    with api.provider_http_budget_scope(limit=1) as budget:
        async def send(path: str):
            async with httpx.AsyncClient(
                transport=api.ProviderHttpAsyncTransport(
                    transport,
                    boundary="direct_llm_httpx_async",
                    provider="openrouter",
                )
            ) as client:
                return await client.get(f"https://example.invalid/{path}")

        results = await asyncio.gather(
            send("first"), send("second"), return_exceptions=True
        )

    assert sum(isinstance(result, httpx.Response) for result in results) == 1
    denied = [result for result in results if isinstance(result, Exception)]
    assert len(denied) == 1
    assert isinstance(denied[0], api.ProviderHttpAttemptBudgetExceeded)
    assert len(sends) == 1
    snapshot = budget.snapshot()
    assert snapshot["attempt_count"] == 1
    assert snapshot["denied_count"] == 1
    assert snapshot["success_count"] == 1


@pytest.mark.asyncio
async def test_context_propagates_to_to_thread_and_failed_transport_is_counted() -> None:
    api = _api()
    secret = "Bearer sensitive-token-and-private-prompt"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(secret, request=request)

    client = httpx.Client(
        transport=api.ProviderHttpSyncTransport(
            httpx.MockTransport(handler),
            boundary="vertex_model_httpx_sync",
            provider="google_vertex_ai",
        )
    )
    with api.provider_http_budget_scope(limit=None) as budget:
        with pytest.raises(httpx.ConnectError):
            await asyncio.to_thread(
                client.post,
                "https://example.invalid/model",
                headers={"Authorization": secret},
                content=secret,
            )
    client.close()

    snapshot_json = json.dumps(budget.snapshot())
    assert budget.snapshot()["attempt_count"] == 1
    assert budget.snapshot()["failure_count"] == 1
    assert secret not in snapshot_json
    assert "example.invalid" not in snapshot_json


@pytest.mark.asyncio
async def test_to_thread_concurrent_sends_share_atomic_reservation() -> None:
    api = _api()
    sends: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sends.append(request.url.path)
        return httpx.Response(200, request=request)

    client = httpx.Client(
        transport=api.ProviderHttpSyncTransport(
            httpx.MockTransport(handler),
            boundary="vertex_model_httpx_sync",
            provider="google_vertex_ai",
        )
    )
    with api.provider_http_budget_scope(limit=1) as budget:
        results = await asyncio.gather(
            asyncio.to_thread(client.get, "https://example.invalid/one"),
            asyncio.to_thread(client.get, "https://example.invalid/two"),
            return_exceptions=True,
        )
    client.close()

    assert sum(isinstance(result, httpx.Response) for result in results) == 1
    assert sum(
        isinstance(result, api.ProviderHttpAttemptBudgetExceeded)
        for result in results
    ) == 1
    assert len(sends) == 1
    assert budget.snapshot()["attempt_count"] == 1
    assert budget.snapshot()["denied_count"] == 1


@pytest.mark.asyncio
async def test_capture_isolates_requests_and_nested_scope_keeps_outer_budget() -> None:
    api = _api()
    from app.services.provider_runtime import (
        capture_provider_usage,
        current_provider_http_budget,
    )

    @capture_provider_usage
    async def request():
        budget = current_provider_http_budget()
        assert budget is not None
        async with httpx.AsyncClient(
            transport=api.ProviderHttpAsyncTransport(
                httpx.MockTransport(
                    lambda request: httpx.Response(200, request=request)
                ),
                boundary="direct_llm_httpx_async",
                provider="openrouter",
            )
        ) as client:
            await client.get("https://example.invalid/request")
        return budget.snapshot()

    first, second = await asyncio.gather(request(), request())
    assert first["attempt_count"] == second["attempt_count"] == 1
    assert current_provider_http_budget() is None

    with api.provider_http_budget_scope(limit=1) as outer:
        @capture_provider_usage
        async def nested():
            assert current_provider_http_budget() is outer
            with api.provider_http_budget_scope(limit=100) as inner:
                assert inner is outer
            async with httpx.AsyncClient(
                transport=api.ProviderHttpAsyncTransport(
                    httpx.MockTransport(
                        lambda request: httpx.Response(200, request=request)
                    ),
                    boundary="direct_llm_httpx_async",
                    provider="openrouter",
                )
            ) as client:
                await client.get("https://example.invalid/allowed")
                with pytest.raises(api.ProviderHttpAttemptBudgetExceeded):
                    await client.get("https://example.invalid/denied")

        await nested()
    assert outer.snapshot()["attempt_count"] == 1
    assert outer.snapshot()["denied_count"] == 1


def test_budget_detail_is_bounded_and_aggregate_drop_count_is_exact() -> None:
    api = _api()
    with api.provider_http_budget_scope(limit=None) as budget:
        for _ in range(api.MAX_PROVIDER_HTTP_EVENTS + 3):
            permit = budget.reserve(
                boundary="direct_llm_httpx_async", provider="gemini"
            )
            budget.finish(permit, status_code=200)

    snapshot = budget.snapshot()
    assert snapshot["attempt_count"] == api.MAX_PROVIDER_HTTP_EVENTS + 3
    assert snapshot["success_count"] == api.MAX_PROVIDER_HTTP_EVENTS + 3
    assert len(snapshot["events"]) == api.MAX_PROVIDER_HTTP_EVENTS
    assert snapshot["dropped_event_count"] == 3


def test_completion_after_detail_drop_updates_aggregate_and_ignores_double_finish() -> None:
    api = _api()
    with api.provider_http_budget_scope(limit=None) as budget:
        first = budget.reserve(boundary="direct_llm_httpx_async", provider="gemini")
        for _ in range(api.MAX_PROVIDER_HTTP_EVENTS + 1):
            permit = budget.reserve(
                boundary="direct_llm_httpx_async", provider="gemini"
            )
            budget.finish(permit, status_code=200)
        budget.finish(first, status_code=503)
        budget.finish(first, status_code=200)

    snapshot = budget.snapshot()
    assert snapshot["attempt_count"] == api.MAX_PROVIDER_HTTP_EVENTS + 2
    assert snapshot["success_count"] == api.MAX_PROVIDER_HTTP_EVENTS + 1
    assert snapshot["failure_count"] == 1
    assert snapshot["incomplete_count"] == 0
    assert snapshot["in_flight_count"] == 0
    assert snapshot["dropped_event_count"] == 2


def test_config_limit_is_optional_positive_and_included_in_runtime_identity(
    tmp_path, monkeypatch,
) -> None:
    from pydantic import ValidationError

    from app.config import Settings
    from app.services.runtime_identity import runtime_identity

    assert Settings(_env_file=None).PROVIDER_HTTP_ATTEMPT_LIMIT is None
    monkeypatch.setenv("PROVIDER_HTTP_ATTEMPT_LIMIT", "4")
    assert Settings(_env_file=None).PROVIDER_HTTP_ATTEMPT_LIMIT == 4
    monkeypatch.delenv("PROVIDER_HTTP_ATTEMPT_LIMIT")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, PROVIDER_HTTP_ATTEMPT_LIMIT=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, PROVIDER_HTTP_ATTEMPT_LIMIT=True)

    settings = Settings(_env_file=None, PROVIDER_HTTP_ATTEMPT_LIMIT=None)
    before = runtime_identity(settings, source_root=tmp_path)
    settings.PROVIDER_HTTP_ATTEMPT_LIMIT = 4
    after = runtime_identity(settings, source_root=tmp_path)
    assert after["configuration_sha256"] != before["configuration_sha256"]


def _install_vertex_mock_transport(monkeypatch, handler):
    api = _api()
    import app.services.vertex_ai as vertex_ai

    def create_clients(*, timeout_seconds, verify):
        del timeout_seconds, verify
        sync = httpx.Client(
            transport=api.ProviderHttpSyncTransport(
                httpx.MockTransport(handler),
                boundary="vertex_model_httpx_sync",
                provider="google_vertex_ai",
            ),
            follow_redirects=True,
        )
        async_client = httpx.AsyncClient(
            transport=api.ProviderHttpAsyncTransport(
                httpx.MockTransport(handler),
                boundary="vertex_model_httpx_async",
                provider="google_vertex_ai",
            ),
            follow_redirects=True,
        )
        return sync, async_client

    monkeypatch.setattr(vertex_ai, "create_vertex_httpx_clients", create_clients)


@pytest.mark.asyncio
async def test_real_genai_sdk_retry_503_then_200_counts_both_model_sends(monkeypatch) -> None:
    from google.oauth2.credentials import Credentials

    api = _api()
    import app.services.vertex_ai as vertex_ai

    replies = [503, 200]
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        status = replies.pop(0)
        if status == 503:
            return httpx.Response(
                503,
                request=request,
                json={"error": {"code": 503, "status": "UNAVAILABLE"}},
            )
        return httpx.Response(
            200,
            request=request,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [{"text": "Đã thử lại thành công"}],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 4},
            },
        )

    _install_vertex_mock_transport(monkeypatch, handler)
    provider = vertex_ai.VertexAIProvider(
        settings=vertex_ai_test_settings(max_retries=1),
        credentials_loader=lambda: (Credentials("local-test-token"), "project"),
    )

    with api.provider_http_budget_scope(limit=None) as budget:
        result = await provider.generate("synthetic prompt", max_retries=1)

    assert result.text == "Đã thử lại thành công"
    assert len(sent) == 2
    assert budget.snapshot()["attempt_count"] == 2
    assert budget.snapshot()["failure_count"] == 1
    assert budget.snapshot()["success_count"] == 1
    await vertex_ai.close_vertex_provider(provider)


@pytest.mark.asyncio
async def test_real_genai_retry_cannot_send_after_cap_and_sync_async_share_budget(
    monkeypatch,
) -> None:
    from google.oauth2.credentials import Credentials

    api = _api()
    import app.services.vertex_ai as vertex_ai

    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if "embedContent" in request.url.path or "predict" in request.url.path:
            return httpx.Response(
                200,
                request=request,
                json={
                    "predictions": [
                        {"embeddings": {"values": [1.0] + [0.0] * 127}}
                    ]
                },
            )
        return httpx.Response(
            503,
            request=request,
            json={"error": {"code": 503, "status": "UNAVAILABLE"}},
        )

    _install_vertex_mock_transport(monkeypatch, handler)
    provider = vertex_ai.VertexAIProvider(
        settings=vertex_ai_test_settings(max_retries=1),
        credentials_loader=lambda: (Credentials("local-test-token"), "project"),
    )
    client = provider._get_client()

    with api.provider_http_budget_scope(limit=1) as budget:
        embedded = client.models.embed_content(
            model="gemini-embedding-2",
            contents="synthetic embedding text",
            config={"output_dimensionality": 128},
        )
        assert embedded.embeddings
        with pytest.raises(api.ProviderHttpAttemptBudgetExceeded):
            await provider.generate("synthetic generation prompt", max_retries=1)

    assert len(sent) == 1
    assert budget.snapshot()["attempt_count"] == 1
    assert budget.snapshot()["denied_count"] == 1
    await vertex_ai.close_vertex_provider(provider)


@pytest.mark.asyncio
async def test_exhausted_budget_denies_vertex_before_adc_or_client_creation() -> None:
    api = _api()
    import app.services.vertex_ai as vertex_ai

    provider = vertex_ai.VertexAIProvider(
        settings=vertex_ai_test_settings(max_retries=0),
        credentials_loader=lambda: pytest.fail("ADC loaded after cap exhausted"),
        client_factory=lambda **_kwargs: pytest.fail("client created after cap exhausted"),
    )
    with api.provider_http_budget_scope(limit=1) as budget:
        permit = budget.reserve(
            boundary="direct_llm_httpx_async", provider="openrouter"
        )
        budget.finish(permit, status_code=200)
        with pytest.raises(api.ProviderHttpAttemptBudgetExceeded):
            await provider.embed_query("synthetic", output_dimensionality=128)

    assert budget.snapshot()["attempt_count"] == 1
    assert budget.snapshot()["denied_count"] == 1


def vertex_ai_test_settings(*, max_retries: int):
    from types import SimpleNamespace

    return SimpleNamespace(
        GOOGLE_CLOUD_PROJECT="local-test-project",
        GOOGLE_CLOUD_QUOTA_PROJECT=None,
        GOOGLE_CLOUD_LOCATION="global",
        VERTEX_LLM_MODEL="gemini-3.5-flash",
        VERTEX_EMBEDDING_MODEL="gemini-embedding-2",
        VERTEX_REQUEST_TIMEOUT_SECONDS=3.0,
        VERTEX_MAX_RETRIES=max_retries,
    )


@pytest.mark.asyncio
async def test_async_cancellation_finishes_as_failed_attempt_without_swallowing() -> None:
    api = _api()
    request_started = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        request_started.set()
        raise asyncio.CancelledError()

    async with httpx.AsyncClient(
        transport=api.ProviderHttpAsyncTransport(
            httpx.MockTransport(handler),
            boundary="direct_llm_httpx_async",
            provider="gemini",
        )
    ) as client:
        with api.provider_http_budget_scope(limit=None) as budget:
            with pytest.raises(asyncio.CancelledError):
                await client.post("https://example.invalid/cancel", content="private")

    assert request_started.is_set()
    assert budget.snapshot()["attempt_count"] == 1
    assert budget.snapshot()["failure_count"] == 1


@pytest.mark.asyncio
async def test_secondary_fallback_cap_exhaustion_propagates_without_more_network(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    api = _api()
    import app.services.direct_llm as direct_llm
    from app.services.vertex_ai import VertexQuotaError

    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.url.host)
        return httpx.Response(503, request=request)

    def create_direct_client():
        return httpx.AsyncClient(
            transport=api.ProviderHttpAsyncTransport(
                httpx.MockTransport(handler),
                boundary="direct_llm_httpx_async",
            )
        )

    monkeypatch.setattr(direct_llm, "create_direct_httpx_client", create_direct_client)
    monkeypatch.setattr(direct_llm, "_http_client", None)
    monkeypatch.setattr(
        direct_llm,
        "_cooldowns",
        {"openrouter": 0.0, "gemini": 0.0, "nvidia": 0.0, "groq": 0.0},
    )
    monkeypatch.setattr(
        direct_llm,
        "settings",
        SimpleNamespace(
            OPENROUTER_API_KEY="local-openrouter-key",
            GEMINI_API_KEY="local-gemini-key",
            NVIDIA_API_KEY=None,
            GROQ_API_KEY=None,
        ),
    )
    async def fail_vertex(*_args, **_kwargs):
        raise VertexQuotaError("local quota fixture", status_code=429)

    monkeypatch.setattr(
        direct_llm,
        "get_vertex_provider",
        lambda: SimpleNamespace(generate=fail_vertex),
    )

    with api.provider_http_budget_scope(limit=1) as budget:
        with pytest.raises(api.ProviderHttpAttemptBudgetExceeded):
            await direct_llm.generate_llm_response_with_metadata("private prompt")

    assert len(sent) == 1
    assert budget.snapshot()["attempt_count"] == 1
    assert budget.snapshot()["denied_count"] == 1


@pytest.mark.asyncio
async def test_local_cap_denial_does_not_degrade_remote_provider_health(monkeypatch):
    from collections import deque
    from types import SimpleNamespace

    api = _api()
    import app.services.direct_llm as direct_llm
    import app.services.provider_runtime as provider_runtime

    monkeypatch.setattr(provider_runtime, "_events", deque())
    provider_runtime.record_provider_event(
        provider_runtime.ProviderEvent(
            provider="google_vertex_ai",
            model="gemini-3.5-flash",
            use_case="answer",
            success=True,
            error_kind=None,
            latency_ms=1,
            fallback_used=False,
            timestamp="synthetic",
        )
    )

    async def generate(*_args, **_kwargs):
        async with httpx.AsyncClient(
            transport=api.ProviderHttpAsyncTransport(
                httpx.MockTransport(
                    lambda request: httpx.Response(200, request=request)
                ),
                boundary="vertex_model_httpx_async",
                provider="google_vertex_ai",
            )
        ) as client:
            await client.post("https://example.invalid/denied")
        raise AssertionError("cap must deny before model HTTP is delegated")

    monkeypatch.setattr(
        direct_llm, "get_vertex_provider", lambda: SimpleNamespace(generate=generate)
    )
    with api.provider_http_budget_scope(limit=1) as budget:
        permit = budget.reserve(
            boundary="vertex_model_httpx_async", provider="google_vertex_ai"
        )
        budget.finish(permit, status_code=200)
        with pytest.raises(api.ProviderHttpAttemptBudgetExceeded):
            await direct_llm.generate_llm_response_with_metadata("synthetic")

    configured = SimpleNamespace(
        USE_LEGACY_FREE_PIPELINE=False,
        OPENROUTER_API_KEY=None,
        GEMINI_API_KEY=None,
        NVIDIA_API_KEY=None,
        GROQ_API_KEY=None,
        LITELLM_MASTER_KEY=None,
    )
    status = provider_runtime.provider_status_snapshot(configured)
    vertex_status = next(row for row in status if row["provider"] == "google_vertex_ai")
    assert vertex_status["state"] == "HEALTHY"
    assert budget.snapshot()["denied_count"] == 1


@pytest.mark.asyncio
async def test_vertex_custom_clients_are_closed_by_provider_lifecycle(monkeypatch) -> None:
    from google.oauth2.credentials import Credentials

    api = _api()
    import app.services.vertex_ai as vertex_ai

    _install_vertex_mock_transport(
        monkeypatch,
        lambda request: pytest.fail("lifecycle test must not send HTTP"),
    )

    provider = vertex_ai.VertexAIProvider(
        settings=vertex_ai_test_settings(max_retries=0),
        credentials_loader=lambda: (Credentials("local-test-token"), "project"),
    )
    provider._get_client()
    sync_client, async_client = provider._owned_httpx_clients
    await provider.close()

    assert sync_client.is_closed
    assert async_client.is_closed


def test_required_mtls_fails_closed_before_credentials_or_client_creation(
    monkeypatch,
) -> None:
    import app.services.vertex_ai as vertex_ai

    monkeypatch.setattr(vertex_ai, "_provider", None)
    monkeypatch.setattr(vertex_ai.genai, "Client", lambda **_kwargs: pytest.fail("client created"))
    monkeypatch.setattr(vertex_ai, "_mtls_required_for_default_client", lambda: True)
    provider = vertex_ai.VertexAIProvider(
        settings=vertex_ai_test_settings(max_retries=0),
        credentials_loader=lambda: pytest.fail("credentials loaded before mTLS check"),
    )

    with pytest.raises(vertex_ai.VertexMTLSUnsupportedError):
        provider._get_client()


def test_legacy_mode_blocks_direct_provider_client_creation() -> None:
    import app.services.vertex_ai as vertex_ai

    settings = vertex_ai_test_settings(max_retries=0)
    settings.USE_LEGACY_FREE_PIPELINE = True
    provider = vertex_ai.VertexAIProvider(
        settings=settings,
        credentials_loader=lambda: pytest.fail("credentials loaded in legacy mode"),
        client_factory=lambda **_kwargs: pytest.fail("client created in legacy mode"),
    )
    existing_client = object()
    provider._client = existing_client

    with pytest.raises(vertex_ai.VertexDisabledError):
        provider._get_client()
    assert provider._client is existing_client

