"""Frozen acceptance follow-ups at the public route boundary; all providers doubled."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import verify_csrf
from app.api.routes import router
from app.rate_limit import limiter


_RUN = Path(__file__).parents[1] / 'docs/evaluation/runs/legal-acceptance-independent-20261029-174544'
_CASES = {case['id']: case['input'] for name in ('cases-frozen.json', 'extra-cases-frozen.json')
          for case in json.loads((_RUN / name).read_text(encoding='utf-8'))['cases']}


@pytest.mark.parametrize('case_id,previous,new_session', [
    ('L02', _CASES['L01'], False),
    ('X02', _CASES['X01'], False),
    ('X03', None, True),
], ids=['L02', 'X02', 'X03'])
def test_frozen_followups_use_only_owner_history_and_bypass_global_cache(
    case_id, previous, new_session, monkeypatch
):
    monkeypatch.setattr('app.api.routes.check_input_guardrails', AsyncMock(return_value=(True, '')))
    monkeypatch.setattr('app.api.routes.check_output_guardrails', AsyncMock(return_value=(True, '')))
    limiter._storage.reset()
    app = FastAPI()

    @app.middleware('http')
    async def identity(request, call_next):
        request.state.client_id = 'context-owner'
        return await call_next(request)

    app.dependency_overrides[verify_csrf] = lambda: 'valid'
    app.include_router(router)
    monkeypatch.setattr('app.api.routes.settings.PUBLIC_NEMO_DEFAULT_ENABLED', False)
    history = AsyncMock(return_value=[{'user_query': previous, 'bot_response': 'UNTRUSTED 99 triệu'}])
    monkeypatch.setattr('app.api.routes.get_session_messages', history)
    forbidden = AsyncMock(side_effect=AssertionError('global cache forbidden'))
    monkeypatch.setattr('app.api.routes.check_semantic_cache', forbidden)
    monkeypatch.setattr('app.api.routes.save_to_semantic_cache', forbidden)
    pipeline = AsyncMock(return_value=('Cần đối chiếu bằng chứng.', [], {'generation_status': 'no_contexts'}))
    monkeypatch.setattr('app.api.routes.run_advanced_rag', pipeline)
    monkeypatch.setattr('app.api.routes.log_interaction', AsyncMock())
    data = {'message': _CASES[case_id], 'csrf_token': 'valid'}
    if not new_session:
        data['session_id'] = 'context-session'
    with TestClient(app) as client:
        response = client.post('/chat', data=data)
    assert response.status_code == 200
    forbidden.assert_not_awaited()
    if new_session:
        history.assert_not_awaited()
        assert pipeline.await_args.kwargs == {}
    else:
        history.assert_awaited_once_with('context-session', 'context-owner', user_id=None, recent_limit=8)
        assert pipeline.await_args.kwargs['previous_user_query'] == previous
