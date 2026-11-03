from types import SimpleNamespace
from unittest.mock import AsyncMock
from pathlib import Path

import pytest


def test_lightweight_prompts_match_current_nemo_contract():
    import yaml
    from app.services.guardrail_prompts import INPUT_PROMPT, OUTPUT_PROMPT
    prompts = yaml.safe_load(Path('guardrails_config/prompts.yml').read_text(encoding='utf-8'))['prompts']
    by_task = {row['task']: row['content'] for row in prompts}
    assert INPUT_PROMPT == by_task['self_check_input']
    assert OUTPUT_PROMPT == by_task['self_check_facts']


@pytest.fixture
def guard(monkeypatch):
    from app.services import serverless_guardrails as guard
    generation = AsyncMock(return_value=SimpleNamespace(text='no', status='success', finish_reason='STOP'))
    monkeypatch.setattr(guard, 'generate_llm_response_with_metadata', generation)
    return guard, generation


@pytest.mark.asyncio
@pytest.mark.parametrize('decision,safe', [('no', True), ('NO.', True), ('yes', False), ('Đánh giá (yes/no): no', True), ('Đánh giá (yes/no): yes', False)])
async def test_input_requires_explicit_decision(guard, decision, safe):
    service, generation = guard
    generation.return_value.text = decision
    assert (await service.check_input_guardrails('Điều kiện hợp đồng?'))[0] is safe
    assert generation.await_args.kwargs['max_output_tokens'] == 64
    assert generation.await_args.kwargs['use_case'].value == 'guardrail'


@pytest.mark.asyncio
@pytest.mark.parametrize('text,status,finish', [('unclear', 'success', 'STOP'), ('no', 'success', 'MAX_TOKENS'), ('no', 'quota', None), ('Đánh giá (yes/no): no nhưng yes', 'success', 'STOP')])
async def test_technical_failures_are_never_safe_or_hallucination_blocks(guard, text, status, finish):
    service, generation = guard
    generation.return_value = SimpleNamespace(text=text, status=status, finish_reason=finish)
    with pytest.raises(service.GuardrailUnavailableError):
        await service.check_input_guardrails('query')


@pytest.mark.asyncio
async def test_output_yes_is_supported_and_no_blocks(guard):
    service, generation = guard
    generation.return_value.text = 'yes'
    assert await service.check_output_guardrails('answer', ['evidence'], 'query') == (True, '')
    generation.return_value.text = 'no'
    assert (await service.check_output_guardrails('answer', ['evidence'], 'query'))[0] is False
    generation.reset_mock()
    generation.return_value.text = 'yes'
    assert await service.check_output_guardrails('answer', [], 'query') == (True, '')
    generation.assert_awaited_once()


@pytest.mark.asyncio
async def test_timeout_is_typed_and_has_no_private_error_content(guard):
    service, generation = guard
    generation.side_effect = TimeoutError('private text')
    with pytest.raises(service.GuardrailUnavailableError, match='timeout') as result:
        await service.check_input_guardrails('query')
    assert 'private text' not in str(result.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['input', 'output'])
async def test_default_deadline_allows_slow_provider_tail_without_retry(guard, monkeypatch, stage):
    from app.config import Settings
    service, generation = guard
    settings = Settings(_env_file=None)
    monkeypatch.setattr(service, 'get_settings', lambda: settings)
    # Model a ten-second provider decision without sleeping or a live call.
    async def provider_deadline(awaitable, *, timeout):
        if timeout < 10:
            awaitable.close()
            raise TimeoutError
        return await awaitable
    monkeypatch.setattr(service.asyncio, 'wait_for', provider_deadline)
    generation.return_value.text = 'no' if stage == 'input' else 'yes'
    result = await (service.check_input_guardrails('query') if stage == 'input'
                    else service.check_output_guardrails('answer', ['evidence'], 'query'))
    assert result == (True, '')
    generation.assert_awaited_once()
    assert generation.await_args.kwargs['max_retries'] == 0
    assert generation.await_args.kwargs['allow_fallback'] is False


@pytest.mark.asyncio
async def test_configured_deadline_still_cancels_provider_once_and_fails_closed(guard, monkeypatch):
    import asyncio
    service, generation = guard
    cancelled = []
    async def stalled_provider(*args, **kwargs):
        try:
            await asyncio.sleep(1)
        finally:
            cancelled.append(True)
    generation.side_effect = stalled_provider
    monkeypatch.setattr(service, 'get_settings', lambda: SimpleNamespace(GUARDRAIL_TIMEOUT_SECONDS=0.001))
    with pytest.raises(service.GuardrailUnavailableError, match='input guardrail unavailable: timeout'):
        await service.check_input_guardrails('query')
    assert cancelled == [True]
    generation.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'provider_result',
    [
        None,
        SimpleNamespace(text=None, status='success', finish_reason='STOP'),
        SimpleNamespace(text='yes', status='success'),
    ],
)
async def test_malformed_generation_result_is_typed_failure(guard, provider_result):
    service, generation = guard
    generation.return_value = provider_result

    with pytest.raises(service.GuardrailUnavailableError, match='output guardrail unavailable: invalid_generation_result') as error:
        await service.check_output_guardrails('answer', ['evidence'], 'query')

    assert error.value.stage == 'output'


@pytest.mark.asyncio
async def test_serverless_route_uses_lightweight_backend(monkeypatch):
    import app.api.routes as routes
    from app.services import serverless_guardrails as guard
    monkeypatch.setattr(routes.settings, 'SERVERLESS_ONLINE_ONLY', True)
    check = AsyncMock(return_value=(True, ''))
    monkeypatch.setattr(guard, 'check_input_guardrails', check)
    assert await routes.check_input_guardrails('query') == (True, '')
    check.assert_awaited_once_with('query')
