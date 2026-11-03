from unittest.mock import AsyncMock

import pytest

from app.services.chat_intent import deterministic_guidance


def test_ambiguous_money_claim_asks_material_facts_without_predicting_victory():
    kind, text = deterministic_guidance('Tôi chỉ nói bên kia giữ tiền của tôi, tôi có chắc thắng kiện không?')
    assert kind == 'clarification'
    assert 'giao dịch' in text and 'chứng từ' in text and 'thời điểm' in text.casefold()
    assert 'không thể khẳng định chắc thắng' in text


@pytest.mark.parametrize('query', [
    'Hướng dẫn tôi làm bánh mì chuối và giải thích vì sao sao Hỏa có màu đỏ.',
    'Cách làm bánh chuối?',
])
def test_unambiguously_nonlegal_request_gets_short_unsupported_response(query):
    kind, text = deterministic_guidance(query)
    assert kind == 'unsupported_intent'
    assert 'pháp luật' in text


@pytest.mark.parametrize('query', [
    'Làm bánh chuối để bán cần giấy phép gì?',
    'Tôi thuê nhà, bên kia giữ tiền cọc không trả theo hợp đồng.',
    'Quy định mới về bảo vệ người mua hàng trên mạng là gì?',
    'Có được đăng ký nhãn hiệu bánh chuối không?',
    'Tôi có quyền đòi bồi thường khi học làm bánh bị bỏng không?',
    'Hướng dẫn làm bánh chuối; nếu người dạy lừa đảo lấy tiền học của tôi thì sao?',
    'Hướng dẫn làm bánh chuối và tôi muốn tố cáo người lấy tiền học.',
    'Cách làm bánh chuối, tôi bị lừa lấy tiền thì xử lý sao?',
])
def test_legal_or_unknown_question_is_not_classified_as_unsupported(query):
    assert deterministic_guidance(query) is None


@pytest.mark.asyncio
async def test_pipeline_guidance_precedes_rewrite_retrieval_and_generation(monkeypatch):
    from app.services import rag_pipeline
    forbidden = AsyncMock(side_effect=AssertionError('provider pipeline forbidden'))
    for name in ('rewrite_query_with_metadata', 'retrieve_configured_legal_evidence', 'generate_response_with_metadata'):
        monkeypatch.setattr(rag_pipeline, name, forbidden)
    text, contexts, latency = await rag_pipeline.run_advanced_rag('Cách làm bánh chuối?', rewrite_mode='on')
    assert contexts == []
    assert latency['response_kind'] == 'unsupported_intent'
    forbidden.assert_not_awaited()


def test_guidance_metrics_are_not_retrieval_failures():
    from app.evaluation.online_metrics import build_online_metrics
    for kind in ('clarification', 'unsupported_intent'):
        metrics = build_online_metrics(trace_id='test', request_status=kind,
                                       bot_response='test', context_used=[])
        assert metrics.no_evidence is False
        assert metrics.refusal_category == kind
