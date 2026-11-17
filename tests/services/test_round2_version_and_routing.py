"""Round-2 rubric fixes: superseded and off-topic texts are dropped, rescue routing covers paraphrases,
validity scoping follows the named instrument (not a transaction), and unverified excerpts stay bounded."""

import re

import pytest

from app.services import rag_pipeline
from app.services.instrument_registry import drop_superseded_contexts
from app.services.legal_topic_terms import fold_topic_text
from app.services.primary_law_rescue import (
    _CIVIL_GENERAL,
    _CIVIL_PROC,
    _LABOR,
    _TRAFFIC_DECREE,
    _planned_titles,
)


def _context(header: str, title: str = "", body: str = "Điều 1. Nội dung quy định.") -> str:
    lines = [f"[{header}]", "Nguồn: https://example.gov.vn/van-ban"]
    if title:
        lines.append(f"Tiêu đề: {title}")
    return "\n".join(lines) + "\n" + body


@pytest.mark.parametrize("header,title,question", [
    (
        "38/2022/NĐ-CP, Điều 3, Khoản 1",
        "Nghị định quy định mức lương tối thiểu vùng",
        "Vùng I hiện áp dụng lương tối thiểu bao nhiêu đồng mỗi tháng?",
    ),
    (
        "152/2006/NĐ-CP, Điều 5",
        "Nghị định quy định chi tiết Luật bảo hiểm xã hội",
        "Đóng bảo hiểm xã hội bao nhiêu năm thì được hưởng lương hưu?",
    ),
    (
        "22/2000/QH10, Điều 9",
        "Luật Hôn nhân và gia đình 2000",
        "Ly hôn do chồng ngoại tình, con 2 tuổi thì ai được nuôi?",
    ),
    (
        "02/2000/NQ-HĐTP, Mục 6",
        "Nghị quyết hướng dẫn Luật Hôn nhân và gia đình",
        "Ly hôn do chồng ngoại tình, con 2 tuổi thì ai được nuôi?",
    ),
    (
        "028-TTg, Điều 4",
        "Quyết định về nghỉ phép hằng năm",
        "Người lao động được nghỉ phép bao nhiêu ngày một năm?",
    ),
    (
        "45-LCT/HĐNN8, Điều 6",
        "Pháp lệnh hợp đồng kinh tế",
        "Hợp đồng miệng có giá trị pháp lý không?",
    ),
    (
        "01-TANDTC/CT, Điểm 2",
        "Chỉ thị về giải quyết tranh chấp dân sự",
        "Đòi nợ dân sự có phải hòa giải trước không?",
    ),
    (
        "18/1993/PL-UBTVQH9, Điều 3",
        "Pháp lệnh Thú y",
        "Mua chó cảnh ở chợ có bị cấm không?",
    ),
])
def test_superseded_text_is_dropped_unless_the_question_names_its_year(header, title, question):
    context = _context(header, title)

    kept, dropped = drop_superseded_contexts(question, [context])

    assert kept == []
    assert sum(dropped.values()) == 1


def test_superseded_text_is_kept_when_the_question_names_its_year():
    context = _context("38/2022/NĐ-CP, Điều 3, Khoản 1", "Nghị định quy định mức lương tối thiểu vùng")

    kept, dropped = drop_superseded_contexts("Năm 2022, Vùng I áp dụng lương tối thiểu bao nhiêu?", [context])

    assert kept == [context]
    assert dropped == {}


def test_current_instrument_is_never_dropped_as_superseded():
    context = _context("45/2019/QH14, Điều 35, Khoản 1", "Bộ luật Lao động 2019")

    kept, dropped = drop_superseded_contexts("Báo trước bao nhiêu ngày khi nghỉ việc?", [context])

    assert kept == [context]
    assert dropped == {}


def test_international_judicial_assistance_notice_is_dropped_for_a_domestic_question():
    context = _context("29/2020/TB-LPQT, ĐIỀU 16", "Thông báo về tương trợ tư pháp")

    kept, dropped = drop_superseded_contexts("Cho bạn vay 50 triệu không giấy tờ, đem ra tòa được không?", [context])

    assert kept == []
    assert dropped == {"off_topic:international_judicial_assistance": 1}


def test_international_judicial_assistance_notice_is_kept_for_a_cross_border_question():
    context = _context("29/2020/TB-LPQT, ĐIỀU 16", "Thông báo về tương trợ tư pháp")

    kept, dropped = drop_superseded_contexts("Tòa án nước ngoài có thi hành bản án ở Việt Nam không?", [context])

    assert kept == [context]
    assert dropped == {}


@pytest.mark.parametrize("question,expected", [
    ("hết bao nhiêu năm thì không còn được kiện đòi khoản vay tài sản?", _CIVIL_GENERAL),
    ("thời hạn để khởi kiện đòi khoản nợ vay tài sản theo BLDS là bao lâu kể từ khi đến hạn trả?", _CIVIL_GENERAL),
    ("thỏa thuận miệng có được pháp luật công nhận không, trường hợp nào bắt buộc phải lập thành văn bản?", _CIVIL_GENERAL),
    ("làm hợp đồng không xác định thời hạn thì nhân viên muốn nghỉ phải báo trước mấy ngày?", _LABOR),
    ("hợp đồng vô thời hạn, người lao động xin nghỉ thì thời gian báo trước tối thiểu là bao nhiêu ngày?", _LABOR),
    ("muốn đòi nợ bằng đơn kiện thì luật có yêu cầu hòa giải trước hay không?", _CIVIL_PROC),
    ("say xỉn lái xe máy thì mức phạt và biện pháp xử lý phương tiện là gì?", _TRAFFIC_DECREE),
    ("điều khiển xe máy sau khi uống rượu có bị tước bằng lái không và xử phạt thế nào?", _TRAFFIC_DECREE),
])
def test_paraphrased_round2_questions_route_to_the_controlling_law(question, expected):
    assert expected in _planned_titles(question, max_docs=3)


def _domain_phrases_for(law, question: str) -> set[str]:
    folded = fold_topic_text(question)
    return {
        phrase
        for pattern, phrases in law.domain_rules
        if re.search(pattern, folded)
        for phrase in phrases
    }


def test_notice_period_question_targets_the_forty_five_day_clause():
    phrases = _domain_phrases_for(
        _LABOR,
        "làm hợp đồng không xác định thời hạn thì nhân viên muốn nghỉ phải báo trước mấy ngày?",
    )
    assert "it nhat 45 ngay" in phrases


def test_severance_question_with_years_of_service_targets_the_half_month_clause():
    phrases = _domain_phrases_for(
        _LABOR,
        "nếu đã làm 5 năm rồi mới bị sa thải thì trợ cấp mất việc được tính thế nào?",
    )
    assert "mot nua thang tien luong" in phrases


def test_drink_driving_wording_targets_the_alcohol_concentration_rule():
    phrases = _domain_phrases_for(
        _TRAFFIC_DECREE,
        "điều khiển xe máy sau khi uống rượu có bị tước bằng lái không và xử phạt thế nào?",
    )
    assert "nong do con" in phrases


@pytest.mark.parametrize("question", [
    "Giao dịch bằng lời nói có hiệu lực không, những loại nào buộc phải có văn bản?",
    "Hợp đồng không viết thành văn bản có hiệu lực không?",
])
def test_transaction_validity_is_not_a_current_law_question(question):
    assert not rag_pipeline._current_effect_conclusion_requested(question)
    assert not rag_pipeline._requires_verified_effect_evidence(question)


@pytest.mark.parametrize("question", [
    "Văn bản này còn hiệu lực hiện nay không?",
    "Quy định này hiện nay đang áp dụng không?",
    "Điều 35 Bộ luật Lao động còn hiệu lực không?",
])
def test_instrument_validity_is_still_a_current_law_question(question):
    assert rag_pipeline._current_effect_conclusion_requested(question)


@pytest.mark.asyncio
async def test_prompt_asks_for_direct_answer_when_the_evidence_contains_the_clause(monkeypatch):
    captured: dict[str, str] = {}

    async def provider(user_prompt, system_prompt="", **kwargs):
        captured["system"] = system_prompt
        return rag_pipeline.LLMGenerationResult("Trả lời theo điều khoản.", "test", "test")

    monkeypatch.setattr(rag_pipeline, "generate_llm_response_with_metadata", provider)
    context = (
        "[45/2019/QH14, Điều 35, Khoản 1]\nNguồn: https://example.gov.vn/bllđ\n"
        "Tiêu đề: Bộ luật Lao động 2019\n"
        "Điều 35. Quyền đơn phương chấm dứt hợp đồng lao động. 1. Ít nhất 45 ngày đối với hợp đồng không xác định thời hạn."
    )

    await rag_pipeline.generate_response_with_metadata(
        "Làm hợp đồng không xác định thời hạn thì phải báo trước mấy ngày?", "báo trước 45 ngày", [context]
    )

    assert "trả lời ý đó bằng điều khoản ấy" in captured["system"]
    assert "không suy đoán" in captured["system"]


def test_unverified_excerpts_stay_bounded_for_long_sources():
    contexts = [f"[Nguồn {i}, Điều {i}]\n" + "điều kiện chi tiết " * 400 for i in range(6)]

    result = rag_pipeline._unverified_effect_excerpts(contexts)

    assert len(result.text) < 9000
    assert "[Nguồn 5" not in result.text
