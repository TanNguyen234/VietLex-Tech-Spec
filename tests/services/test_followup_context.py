from app.services.conversation_context import followup_context, is_explicit_followup
from unittest.mock import AsyncMock, Mock
from types import SimpleNamespace
import json
from pathlib import Path
import pytest


def _frozen_queries():
    root = Path(__file__).parents[2] / 'docs/evaluation/runs/legal-acceptance-independent-20261029-174544'
    return {case['id']: case['input'] for name in ('cases-frozen.json', 'extra-cases-frozen.json')
            for case in json.loads((root / name).read_text(encoding='utf-8'))['cases']}


def test_frozen_followup_keeps_prior_user_wage_and_newest_correction():
    cases = _frozen_queries()
    history = [{'user_query': cases['L01'], 'bot_response': 'UNTRUSTED 99 triệu'}]
    assert followup_context(cases['L02'], history) == cases['L01']
    correction = 'Tôi sửa dữ kiện: mức lương công việc là 20 triệu đồng, vẫn đang thử việc.'
    history.append({'user_query': correction, 'bot_response': 'UNTRUSTED 99 triệu'})
    assert followup_context(cases['L02'], history) == correction
    assert followup_context(cases['X02'], [{'user_query': cases['X01']}]) == cases['X01']


@pytest.mark.parametrize('query', [
    'Với mức lương công việc đó thì 85% bằng bao nhiêu tiền?',
    'Vậy 85% bằng bao nhiêu tiền?',
])
def test_referenced_situation_is_followup_but_never_supplies_missing_facts(query):
    assert is_explicit_followup(query)
    assert followup_context(query, []) is None
    assert followup_context(query, [{'bot_response': 'Lương 12 triệu, thử việc.'}]) is None


def test_explicit_unrelated_followup_never_inherits_previous_trial_situation():
    assert followup_context('Vậy tình huống thuê nhà ở trên thì sao?', [
        {'user_query': 'Tôi thử việc, lương công việc 12 triệu.'}
    ]) is None


def test_only_explicit_followup_can_carry_previous_user_facts():
    history = [{'user_query': 'Tôi thử việc, lương công việc 12 triệu, nhận 8,4 triệu.',
                'bot_response': 'UNTRUSTED OLD ANSWER'}]
    query = 'Thế nếu công việc cần trình độ cao đẳng thì sao?'
    assert is_explicit_followup(query)
    assert '12 triệu' in followup_context(query, history)
    assert 'UNTRUSTED' not in followup_context(query, history)
    assert followup_context('Tôi muốn hỏi về thuê nhà.', history) is None


def test_explicit_named_situation_can_refer_back_past_other_topics():
    history = [{'user_query': 'Tôi thử việc hai tháng.'}, {'user_query': 'Tôi thuê nhà.'}]
    assert followup_context('Tôi hỏi tiếp tình huống thử việc trước đó.', history) == 'Tôi thử việc hai tháng.'
    assert followup_context('Thế nếu giá thuê nhà tăng thì sao?', history) == 'Tôi thuê nhà.'


def test_no_cross_topic_carry_or_unbounded_history():
    assert followup_context('Thế nếu tôi thử việc thì sao?', [{'user_query': 'Tôi thuê nhà.'}]) is None
    assert followup_context('Thế nếu công việc cần bằng cấp?', []) is None
    history = [{'user_query': 'Tôi thử việc.'}] + [{'user_query': 'Khác.'}] * 8
    assert followup_context('Tôi hỏi tiếp tình huống thử việc trước đó.', history) is None


@pytest.mark.asyncio
async def test_followup_database_read_is_recent_bounded_and_owner_scoped(monkeypatch):
    from app import database
    monkeypatch.setattr(database.settings, 'APP_ENV', 'test')
    cursor = Mock()
    cursor.sort.return_value = cursor
    cursor.to_list = AsyncMock(return_value=[{'user_query': 'newest'}, {'user_query': 'older'}])
    collection = Mock()
    collection.find.return_value = cursor
    monkeypatch.setattr(database, 'get_db', lambda: SimpleNamespace(evaluation_logs=collection))
    result = await database.get_session_messages('session', 'client', user_id='owner', recent_limit=8)
    assert result == [{'user_query': 'older'}, {'user_query': 'newest'}]
    assert collection.find.call_args.args[0] == {'session_id': 'session', 'user_id': 'owner'}
    assert collection.find.call_args.args[1] == {'user_query': 1, 'timestamp': 1}
    cursor.sort.assert_called_once_with('timestamp', -1)
    cursor.to_list.assert_awaited_once_with(length=8)
