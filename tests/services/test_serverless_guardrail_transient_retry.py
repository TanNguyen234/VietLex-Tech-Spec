"""Serverless guardrail stages retry only transient provider failures (quota/network), inside one deadline.

Timeouts, invalid decisions and other statuses are not retried; the last attempt still fails closed.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def guard(monkeypatch):
    from app.services import serverless_guardrails as service

    generation = AsyncMock()
    monkeypatch.setattr(service, "generate_llm_response_with_metadata", generation)
    monkeypatch.setattr(service, "GUARDRAIL_RETRY_BACKOFF_SECONDS", (0, 0))
    return service, generation


def _result(text="no", status="success", finish="STOP"):
    return SimpleNamespace(text=text, status=status, finish_reason=finish)


@pytest.mark.asyncio
async def test_quota_failure_then_success_is_retried_and_decided(guard):
    service, generation = guard
    generation.side_effect = [_result("", "quota", None), _result("no")]

    assert await service.check_input_guardrails("Điều kiện hợp đồng?") == (True, "")
    assert generation.await_count == 2


@pytest.mark.asyncio
async def test_output_network_failure_then_yes_is_retried(guard):
    service, generation = guard
    generation.side_effect = [_result("", "network", None), _result("yes")]

    assert await service.check_output_guardrails("answer", ["evidence"], "query") == (True, "")
    assert generation.await_count == 2


@pytest.mark.asyncio
async def test_persistent_transient_failure_fails_closed_after_bounded_attempts(guard):
    service, generation = guard
    generation.return_value = _result("", "quota", None)

    with pytest.raises(service.GuardrailUnavailableError, match="input guardrail unavailable: generation_incomplete"):
        await service.check_input_guardrails("query")
    assert generation.await_count == service.GUARDRAIL_MAX_ATTEMPTS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        _result("maybe"),
        _result("", "authentication", None),
        _result("no", "success", "MAX_TOKENS"),
    ],
)
async def test_non_transient_failures_are_not_retried(guard, result):
    service, generation = guard
    generation.return_value = result

    with pytest.raises(service.GuardrailUnavailableError):
        await service.check_input_guardrails("query")
    assert generation.await_count == 1


@pytest.mark.asyncio
async def test_retry_is_skipped_when_backoff_would_pass_the_deadline(guard, monkeypatch):
    service, generation = guard
    generation.return_value = _result("", "quota", None)
    monkeypatch.setattr(service, "GUARDRAIL_RETRY_BACKOFF_SECONDS", (60, 60))
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(GUARDRAIL_TIMEOUT_SECONDS=45))

    with pytest.raises(service.GuardrailUnavailableError):
        await service.check_input_guardrails("query")
    assert generation.await_count == 1


@pytest.mark.asyncio
async def test_timeout_is_still_not_retried(guard, monkeypatch):
    service, generation = guard
    generation.side_effect = TimeoutError("provider stalled")
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(GUARDRAIL_TIMEOUT_SECONDS=0.001))

    with pytest.raises(service.GuardrailUnavailableError, match="input guardrail unavailable: timeout"):
        await service.check_input_guardrails("query")
    # A stalled attempt may be cancelled before its coroutine runs; the point is no second attempt.
    assert generation.call_count == 1
