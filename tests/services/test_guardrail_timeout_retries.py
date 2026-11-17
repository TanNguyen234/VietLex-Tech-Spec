"""Guardrail stages retry only after a timeout, up to GUARDRAIL_TIMEOUT_ATTEMPTS, then fail closed."""

import pytest

from app.services import guardrails
from app.services.runtime_errors import GuardrailUnavailableError

ONCE_ATTRIBUTE = {
    "input": "_check_input_guardrails_once",
    "output": "_check_output_guardrails_once",
}


def _scripted_stage(outcomes, calls):
    async def _run(*_args, **_kwargs):
        calls.append(1)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return _run


async def _call_stage(stage):
    if stage == "input":
        return await guardrails.check_input_guardrails("Điều kiện cấp phép là gì?")
    return await guardrails.check_output_guardrails("Câu trả lời", ["Căn cứ pháp lý"], "Câu hỏi")


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["input", "output"])
async def test_stage_recovers_when_a_later_attempt_succeeds(monkeypatch, stage) -> None:
    calls: list[int] = []
    timeout = GuardrailUnavailableError(stage, "timeout")
    monkeypatch.setattr(
        guardrails,
        ONCE_ATTRIBUTE[stage],
        _scripted_stage([timeout, (True, "")], calls),
    )

    assert await _call_stage(stage) == (True, "")
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["input", "output"])
async def test_stage_fails_closed_after_every_attempt_times_out(monkeypatch, stage) -> None:
    calls: list[int] = []
    timeout = GuardrailUnavailableError(stage, "timeout")
    monkeypatch.setattr(
        guardrails,
        ONCE_ATTRIBUTE[stage],
        _scripted_stage([timeout] * guardrails.GUARDRAIL_TIMEOUT_ATTEMPTS, calls),
    )

    with pytest.raises(GuardrailUnavailableError, match=f"{stage} guardrail unavailable: timeout"):
        await _call_stage(stage)
    assert len(calls) == guardrails.GUARDRAIL_TIMEOUT_ATTEMPTS


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["input", "output"])
async def test_non_timeout_failure_is_not_retried(monkeypatch, stage) -> None:
    calls: list[int] = []
    failure = GuardrailUnavailableError(stage, "generation_incomplete")
    monkeypatch.setattr(
        guardrails,
        ONCE_ATTRIBUTE[stage],
        _scripted_stage([failure, (True, "")], calls),
    )

    with pytest.raises(GuardrailUnavailableError, match="generation_incomplete"):
        await _call_stage(stage)
    assert len(calls) == 1


def test_guardrail_timeout_budget_covers_one_provider_request() -> None:
    # Regression: a 20 s guardrail budget cut calls before the 30 s Vertex request timeout,
    # so slow-but-recoverable calls became 503 answers.
    from app.config import get_settings

    settings = get_settings()

    assert settings.GUARDRAIL_TIMEOUT_SECONDS > settings.VERTEX_REQUEST_TIMEOUT_SECONDS
    assert guardrails.GUARDRAIL_TIMEOUT_ATTEMPTS >= 2
