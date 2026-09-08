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
    assert await service.check_output_guardrails('answer', [], 'query') == (True, '')
    generation.assert_not_awaited()


@pytest.mark.asyncio
async def test_timeout_is_typed_and_has_no_private_error_content(guard):
    service, generation = guard
    generation.side_effect = TimeoutError('private text')
    with pytest.raises(service.GuardrailUnavailableError, match='timeout') as result:
        await service.check_input_guardrails('query')
    assert 'private text' not in str(result.value)


@pytest.mark.asyncio
async def test_serverless_route_uses_lightweight_backend(monkeypatch):
    import app.api.routes as routes
    from app.services import serverless_guardrails as guard
    monkeypatch.setattr(routes.settings, 'SERVERLESS_ONLINE_ONLY', True)
    check = AsyncMock(return_value=(True, ''))
    monkeypatch.setattr(guard, 'check_input_guardrails', check)
    assert await routes.check_input_guardrails('query') == (True, '')
    check.assert_awaited_once_with('query')
