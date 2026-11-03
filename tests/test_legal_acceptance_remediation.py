"""Pure scope/format checks; live generation acceptance is recorded separately."""
from dataclasses import replace
import pytest
from app.services import rag_pipeline


@pytest.mark.asyncio
async def test_answer_prompt_requires_each_calculation_and_calendar_uncertainty(monkeypatch):
    captured = {}

    async def provider(user_prompt, system_prompt, **kwargs):
        captured['system'] = system_prompt
        captured['user'] = user_prompt
        return rag_pipeline.LLMGenerationResult('provider output', 'test', 'test')

    monkeypatch.setattr(rag_pipeline, 'generate_llm_response_with_metadata', provider)
    question = 'Mức đề xuất 65% của 18 triệu so với mức tối thiểu trong nguồn; ba tháng có bằng số ngày tối đa không?'
    result = await rag_pipeline.generate_response_with_metadata(
        question, question, ['[Nguồn giả định]\nMức tối thiểu bằng một tỷ lệ của mức lương; thời hạn tính bằng ngày.'],
    )
    assert result.text == 'provider output'
    assert question in captured['user']
    assert 'từng phương án' in captured['system']
    assert 'so sánh' in captured['system']
    assert 'tháng lịch' in captured['system']
    assert 'ngày bắt đầu' in captured['system']
    assert 'Không tự thêm khoảng số ngày hoặc ví dụ lịch' in captured['system']
    assert 'Không dùng ngày hỏi hoặc ngày tra cứu làm ngày bắt đầu' in captured['system']
    assert 'dẫn riêng đoạn mở đầu Điều' in captured['system']
    assert 'đoạn không đánh số phải dẫn Điều' in captured['system']
    assert '12 triệu' not in captured['system']
    assert 'Điều 25' not in captured['system']


@pytest.mark.asyncio
@pytest.mark.parametrize('corrected', [True, False])
async def test_as_of_date_cannot_become_an_unconfirmed_start_date(monkeypatch, corrected):
    calls = []
    bad = 'Thời hạn bắt đầu từ ngày 14/03/2026.'
    good = 'Chưa có ngày bắt đầu nên chưa tính được ngày kết thúc.'

    async def provider(user_prompt, system_prompt, **kwargs):
        calls.append((user_prompt, system_prompt))
        return rag_pipeline.LLMGenerationResult(
            good if corrected and len(calls) == 2 else bad, 'test', 'test', observed=True)

    monkeypatch.setattr(rag_pipeline, 'generate_llm_response_with_metadata', provider)
    question = 'Tại ngày 14/03/2026, tôi cần tính tiền thuê và thời hạn hai tháng theo giả định.'
    result = await rag_pipeline.generate_response_with_metadata(question, question, ['[Nguồn]\nĐiều kiện thuê.'])
    assert len(calls) == 2
    assert question in calls[1][0]
    assert bad not in result.text
    assert result.status == ('success' if corrected else 'factual_scope_error')


@pytest.mark.asyncio
async def test_explicit_start_date_is_not_rejected_as_a_lookup_date(monkeypatch):
    calls = []

    async def provider(*args, **kwargs):
        calls.append(True)
        return rag_pipeline.LLMGenerationResult('Thời hạn bắt đầu từ ngày 14/03/2026.', 'test', 'test')

    monkeypatch.setattr(rag_pipeline, 'generate_llm_response_with_metadata', provider)
    question = 'Tại ngày 14/03/2026, hợp đồng bắt đầu từ ngày 14/03/2026, tính tiền thuê thế nào?'
    result = await rag_pipeline.generate_response_with_metadata(question, question, ['[Nguồn]\nĐiều kiện thuê.'])
    assert result.text.endswith('Thời hạn bắt đầu từ ngày 14/03/2026.')
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_denial_of_an_unconfirmed_start_is_not_treated_as_confirmation(monkeypatch):
    calls = []
    answer = 'Không được coi thời hạn bắt đầu từ ngày 14/03/2026 khi chưa xác nhận.'

    async def provider(*args, **kwargs):
        calls.append(True)
        return rag_pipeline.LLMGenerationResult(answer, 'test', 'test')

    monkeypatch.setattr(rag_pipeline, 'generate_llm_response_with_metadata', provider)
    question = 'Tại ngày 14/03/2026, tiền thuê được tính thế nào?'
    result = await rag_pipeline.generate_response_with_metadata(question, question, ['[Nguồn]\nĐiều kiện thuê.'])
    assert result.text.endswith(answer)
    assert len(calls) == 1


def test_unverified_excerpts_honor_the_request_reading_profile():
    from app.services.official_search_plan import ProfiledContexts, ReadingProfile
    contexts = ProfiledContexts(
        [f'[Nguồn {i}]\nĐiều kiện độc lập {i}.' for i in range(5)],
        ReadingProfile(context_tokens=100, evidence_limit=4),
    )
    result = rag_pipeline._unverified_effect_excerpts(contexts)
    assert '[Nguồn 3]' in result.text
    assert '[Nguồn 4]' not in result.text
    assert result.observed_provider == 'none'


@pytest.mark.asyncio
@pytest.mark.parametrize('opening', [True, False])
async def test_duration_answer_keeps_bounded_unnumbered_article_source(monkeypatch, opening):
    preface = ('Các bên chỉ được yêu cầu điều chỉnh một lần cho mỗi hồ sơ và phải giữ đầy đủ các điều kiện sau đây. '
               if opening else '')
    context = ('[88/2024/QH15, Điều 7]\nNguồn: https://example.gov.vn/law\nTiêu đề: Luật giả định\n'
               'Điều 7. Thời hạn ' + preface + '1. Không quá mười ngày. 2. Ngoại lệ riêng.')

    async def provider(*args, **kwargs):
        return rag_pipeline.LLMGenerationResult('Giới hạn thời hạn là mười ngày.', 'test', 'test')

    monkeypatch.setattr(rag_pipeline, 'generate_llm_response_with_metadata', provider)
    result = await rag_pipeline.generate_response_with_metadata(
        'Thời hạn tối đa và điều kiện cần đối chiếu là gì?', 'thời hạn', [context])
    if opening:
        assert preface.strip() in result.text
        assert 'Đoạn mở đầu không đánh số' in result.text
        assert '[88/2024/QH15, Điều 7]' in result.text
    else:
        assert result.text == 'Giới hạn thời hạn là mười ngày.'


@pytest.mark.asyncio
async def test_opening_quote_cannot_use_a_source_excluded_from_the_prompt_budget(monkeypatch):
    config = rag_pipeline.get_settings().model_copy(update={'LLM_CONTEXT_MAX_TOKENS': 80})
    context = ('[88/2024/QH15, Điều 7]\nNguồn: https://example.gov.vn/law\nTiêu đề: Luật giả định\n'
               'Điều 7. Thời hạn Các bên chỉ được yêu cầu điều chỉnh một lần cho mỗi hồ sơ và phải '
               'giữ đầy đủ các điều kiện sau đây. 1. Không quá mười ngày.')

    async def provider(user_prompt, *args, **kwargs):
        assert '88/2024/QH15' not in user_prompt
        return rag_pipeline.LLMGenerationResult('Chỉ giải thích phần nguồn đã nhận.', 'test', 'test')

    monkeypatch.setattr(rag_pipeline, 'get_settings', lambda: config)
    monkeypatch.setattr(rag_pipeline, 'generate_llm_response_with_metadata', provider)
    result = await rag_pipeline.generate_response_with_metadata(
        'Thời hạn tối đa và điều kiện là gì?', 'thời hạn', ['[Nguồn]\n' + 'điều kiện ' * 25, context])
    assert result.text == 'Chỉ giải thích phần nguồn đã nhận.'


@pytest.mark.parametrize('question', [
    'Tại ngày 29/10/2026, cơ quan nào có thẩm quyền cấp giấy phép môi trường cho cơ sở nhập phế liệu?',
    'Văn bản này còn hiệu lực hiện nay không?',
    'Hiện nay thời gian thử việc tối đa là bao nhiêu?',
    'Tại ngày 29/10/2026, mức lương thử việc tối thiểu là bao nhiêu?',
    'Hien nay thoi gian thu viec toi da la bao nhieu?',
    'Tinh den ngay 29/10/2026, muc luong thu viec la bao nhieu?',
    'What is the current minimum probation salary?',
    'Theo Bộ luật Lao động, tính đến năm 2026 tiền lương thử việc thế nào?',
])
def test_current_effect_question_keeps_source_only_scope(question):
    assert rag_pipeline._current_effect_conclusion_requested(question)
    result = rag_pipeline.LLMGenerationResult(
        'Nội dung điều khoản và phép tính theo dữ kiện người dùng.',
        'google_vertex_ai', 'configured-model', observed=True,
        prompt_token_count=123, output_token_count=24, total_token_count=147,
    )
    scoped = rag_pipeline._scope_current_effect_answer(question, result)
    assert scoped.text.startswith(rag_pipeline.UNVERIFIED_EFFECT_RESPONSE + '\n\n')
    assert scoped.text.endswith(result.text)
    assert replace(scoped, text=result.text) == result
    assert rag_pipeline._legal_effect_answer_diagnostics(question, scoped) == {
        'status': 'unverified', 'scope': 'source_text_only', 'generation_executed': True,
    }


@pytest.mark.parametrize('question', [
    'Chỉ giải thích khoản 2 Điều 25 văn bản đang mở; không suy diễn hiệu lực hiện tại.',
    'Tình huống trước do người dùng cung cấp (chỉ làm ngữ cảnh):\nLương 12 triệu, thử việc cần cao đẳng.\nCâu hỏi mới (ưu tiên dữ kiện mới):\nVậy mức 85% ở trên bằng bao nhiêu?',
    'Trong vòng 24 tháng kể từ ngày Luật này có hiệu lực phải làm gì theo điều khoản gốc?',
])
def test_original_clause_hypothetical_does_not_request_current_effect(question):
    result = rag_pipeline.LLMGenerationResult('Nội dung được cung cấp.', 'none', 'none')
    assert not rag_pipeline._current_effect_conclusion_requested(question)
    assert rag_pipeline._scope_current_effect_answer(question, result) is result
    assert rag_pipeline._legal_effect_answer_diagnostics(question, result) is None


@pytest.mark.parametrize('status,text', [
    ('network', 'Không thể kết nối.'),
    ('providers_exhausted', 'Không thể tạo câu trả lời.'),
    ('success', ''),
    ('success', rag_pipeline.NO_EVIDENCE_RESPONSE),
])
def test_technical_or_empty_result_is_not_relabelled_as_source_explanation(status, text):
    result = rag_pipeline.LLMGenerationResult(text, 'google_vertex_ai', 'configured-model', status=status)
    assert rag_pipeline._scope_current_effect_answer('Hiện nay thế nào?', result) is result
    assert rag_pipeline._legal_effect_answer_diagnostics('Hiện nay thế nào?', result) is None


def test_unobserved_generation_is_unknown_rather_than_false_or_verified():
    result = rag_pipeline.LLMGenerationResult('Nội dung điều khoản.', 'unobserved', 'unobserved')
    assert rag_pipeline._legal_effect_answer_diagnostics('Hiện nay thế nào?', result) == {
        'status': 'unverified', 'scope': 'source_text_only', 'generation_executed': None,
    }


def test_currentness_instruction_never_promotes_metadata_to_current_law():
    instruction = rag_pipeline.SOURCE_TEXT_ONLY_INSTRUCTION
    assert 'Không kết luận' in instruction
    assert 'mọi nguồn' in instruction
    assert 'tên cơ quan' in instruction
    assert 'tính toán' in instruction

@pytest.mark.parametrize('question,history', [
    ('Tại ngày 29/10/2026, cơ quan nào có thẩm quyền cấp giấy phép?', None),
    ('Văn bản này còn hiệu lực không?', None),
    ('Quy định này hiện nay đang áp dụng không?', None),
    ('Hiện nay cơ quan cấp phép là ai?', None),
    ('Cho biết tình trạng hiệu lực của văn bản này.', None),
    ('Vậy cơ quan nào cấp?', 'Hiện nay tôi cần xin giấy phép.'),
    ('As of 2026, which authority issues this permit?', None),
    ('Không kết luận thẩm quyền hiện hành theo bản gốc, nhưng hiện nay ai cấp?', None),
])
def test_current_authority_or_validity_requires_verified_chain(question, history):
    assert rag_pipeline._requires_verified_effect_evidence(question, context_query=history)


@pytest.mark.parametrize('question,history', [
    ('Tại ngày 29/10/2026, mức lương thử việc tối thiểu theo giả định là bao nhiêu?', None),
    ('Vậy 85% mức lương ở trên bằng bao nhiêu?', 'Hiện nay cơ quan nào cấp giấy phép?'),
    ('Theo văn bản gốc, cơ quan nào cấp? Không kết luận thẩm quyền hiện hành.', 'Tại ngày 29/10/2026, ai cấp?'),
    ('Hiện nay tôi làm ở cơ quan này, tính lương theo giả định thế nào?', None),
    ('Chỉ giải thích khoản 2 trong văn bản gốc. Không suy diễn tình trạng hiệu lực hiện tại nếu chưa có chứng cứ.', None),
])
def test_currentness_history_does_not_turn_fresh_math_or_source_only_into_authority(question, history):
    assert not rag_pipeline._requires_verified_effect_evidence(question, context_query=history)


def test_unverified_authority_uses_whole_quoted_sources_without_generation():
    context = ['[Nguồn thử nghiệm, Điều 7]\nCơ quan được ghi trong văn bản gốc.\n\nĐiều kiện của nguồn.']
    result = rag_pipeline._unverified_effect_excerpts(context)
    assert result.observed_provider == result.observed_model == 'none'
    assert result.observed is False
    assert result.text.startswith(rag_pipeline.UNVERIFIED_EFFECT_RESPONSE)
    assert '> Cơ quan được ghi trong văn bản gốc.\n> \n> Điều kiện của nguồn.' in result.text
    assert rag_pipeline._legal_effect_answer_diagnostics('Hiện nay cơ quan nào cấp?', result) == {
        'status': 'unverified', 'scope': 'source_text_only', 'generation_executed': False,
    }


def test_oversized_source_is_not_cut_into_a_partial_legal_quote():
    context = ['[Nguồn thử nghiệm]\n' + 'điều kiện ' * (rag_pipeline.get_settings().LLM_CONTEXT_MAX_TOKENS + 1)]
    result = rag_pipeline._unverified_effect_excerpts(context)
    assert result.text == rag_pipeline.UNVERIFIED_EFFECT_RESPONSE
    assert result.observed_provider == 'none'
