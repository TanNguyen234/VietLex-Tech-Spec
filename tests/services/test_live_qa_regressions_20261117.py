"""Regression tests for the 2026-11-17 live rubric round: topic routing, rescue rules, LaTeX cleanup.

Corpus snippets below are copied from the production legal store (Supabase legal_documents) and
verified on 2026-11-17. Missing-corpus items (NĐ 168/2024, Luật KDBĐS 2023, NĐ 293/2025) are out of scope.
"""

import pytest

from app.services.legal_topic_terms import extract_official_topic_phrases, fold_topic_text, normalize_colloquial_query
from app.services.primary_law_rescue import (
    _CIVIL_GENERAL,
    _CIVIL_PROC,
    _LABOR,
    _LAND,
    _MARRIAGE,
    _SOCIAL_INSURANCE,
    _planned_titles,
)
from app.services.rag_pipeline import _strip_latex_markup


@pytest.mark.parametrize(
    "query, expected_topic",
    [
        ("chồng ngoại tình, tôi xin nuôi con 2 tuổi thì tòa có ưu tiên mẹ không?", "nuôi con"),
        ("đóng bảo hiểm xã hội đủ bao nhiêu năm thì được hưởng lương hưu?", "lương hưu"),
        ("hồ sơ khởi kiện vụ án dân sự cần chuẩn bị những giấy tờ gì?", "hồ sơ khởi kiện"),
        ("em đi thực tập không có hợp đồng, công ty trả 3 triệu một tháng", "thực tập"),
        ("mua bán đất có bắt buộc phải công chứng không?", "mua bán đất"),
        ("em bị sa thải thì có được bồi thường không?", "sa thải"),
    ],
)
def test_legal_topic_vocabulary_recognizes_round7_concepts(query, expected_topic):
    assert expected_topic in extract_official_topic_phrases(normalize_colloquial_query(query), limit=6)


@pytest.mark.parametrize(
    "query, expected_law",
    [
        ("chồng ngoại tình, tôi xin nuôi con 2 tuổi thì tòa có ưu tiên mẹ không?", _MARRIAGE),
        ("đóng bảo hiểm xã hội đủ bao nhiêu năm thì được hưởng lương hưu?", _SOCIAL_INSURANCE),
        ("hồ sơ khởi kiện vụ án dân sự cần chuẩn bị những giấy tờ gì?", _CIVIL_PROC),
        ("mua bán đất có bắt buộc phải công chứng không?", _LAND),
        ("chuyển nhượng đất không công chứng thì hợp đồng có bị vô hiệu không?", _LAND),
        ("chuyển nhượng đất không công chứng thì hợp đồng có bị vô hiệu không?", _CIVIL_GENERAL),
        ("làm thực tập không ký hợp đồng lao động thì có được đóng bảo hiểm xã hội và nghỉ phép không?", _LABOR),
        ("điều 999 bộ luật lao động 2019 quy định gì về nghỉ phép?", _LABOR),
        ("em bị sa thải thì có được bồi thường không?", _LABOR),
        ("công ty cắt tiền hỗ trợ đã cam kết, tôi có phải hòa giải trước khi đi kiện không?", _LABOR),
    ],
)
def test_round7_queries_plan_the_expected_law(query, expected_law):
    assert expected_law in _planned_titles(query)


def test_civil_mediation_question_does_not_route_to_labor():
    titles = _planned_titles("Kiện đòi nợ dân sự có bắt buộc phải hòa giải trước không?")
    assert _LABOR not in titles


# Verified corpus excerpts (folded) for each rescue phrase added in this round.
_CORPUS_SNIPPETS = {
    "45/2019/QH14": (
        "Điều 91. Mức lương tối thiểu. 1. Mức lương tối thiểu là mức lương thấp nhất được trả. "
        "Điều 113. Nghỉ hằng năm. 1. Người lao động làm việc đủ 12 tháng cho một người sử dụng lao động "
        "thì được nghỉ hằng năm, hưởng nguyên lương"
    ),
    "52/2014/QH13": "3. Con dưới 36 tháng tuổi được giao cho mẹ trực tiếp nuôi, trừ trường hợp người mẹ không đủ điều kiện",
    "41/2024/QH15": "từ đủ 20 năm trở lên thì được hưởng lương hưu với mức thấp hơn",
    "92/2015/QH13": "i) Danh mục tài liệu, chứng cứ kèm theo đơn khởi kiện.",
    "31/2024/QH15": "a) Hợp đồng chuyển nhượng, tặng cho, thế chấp, góp vốn bằng quyền sử dụng đất phải được công chứng hoặc chứng thực",
    "91/2015/QH13": "2. Giao dịch dân sự đã được xác lập bằng văn bản nhưng vi phạm quy định bắt buộc về công chứng, chứng thực mà một bên hoặc các bên đã thực hiện ít nhất hai phần ba nghĩa vụ",
}

_RULE_PHRASES = {
    "45/2019/QH14": ("muc luong toi thieu", "nghi hang nam", "lam viec du 12 thang"),
    "52/2014/QH13": ("duoi 36 thang tuoi", "giao cho me truc tiep nuoi"),
    "41/2024/QH15": ("tu du 20 nam", "huong luong huu"),
    "92/2015/QH13": ("danh muc tai lieu",),
    "31/2024/QH15": ("phai duoc cong chung hoac chung thuc",),
    "91/2015/QH13": ("vi pham quy dinh bat buoc ve cong chung", "hai phan ba nghia vu"),
}


@pytest.mark.parametrize("document_number", sorted(_RULE_PHRASES))
def test_rescue_phrases_match_the_verified_corpus_text(document_number):
    folded = fold_topic_text(_CORPUS_SNIPPETS[document_number])
    for phrase in _RULE_PHRASES[document_number]:
        assert phrase in folded, (document_number, phrase)


def test_latex_display_math_becomes_plain_text():
    raw = r"Mức là $$5 \times 0,5 = 2,5 \text{ tháng tiền lương}$$ theo luật."
    cleaned = _strip_latex_markup(raw)
    assert "$$" not in cleaned
    assert "\\text" not in cleaned
    assert "\\times" not in cleaned
    assert "×" in cleaned
    assert "2,5 tháng tiền lương" in cleaned


def test_plain_answer_is_unchanged_by_latex_cleanup():
    plain = "Thời gian thử việc không quá 60 ngày [Bộ luật Lao động 2019, Điều 25, Khoản 2]."
    assert _strip_latex_markup(plain) == plain


def test_ungrounded_document_number_citation_is_dropped_and_grounded_one_kept():
    from app.services.citation_clause_guard import drop_ungrounded_document_citations

    contexts = ["[45/2019/QH14, Điều 25]\nThời gian thử việc không quá 60 ngày."]
    answer = (
        "Thử việc tối đa 60 ngày [45/2019/QH14, Điều 25]. Ý khác [122/VBHN-VPQH, Điều 5]. "
        "Tham chiếu [Bộ luật Lao động 2019, Điều 25]."
    )
    cleaned, removed = drop_ungrounded_document_citations(answer, contexts)
    assert "[45/2019/QH14, Điều 25]" in cleaned
    assert "[Bộ luật Lao động 2019, Điều 25]" in cleaned
    assert "122/VBHN-VPQH" not in cleaned
    assert removed == ["122/VBHN-VPQH, Điều 5"]


def test_grounding_guard_is_a_noop_without_contexts():
    from app.services.citation_clause_guard import drop_ungrounded_document_citations

    answer = "Nội dung [122/VBHN-VPQH, Điều 5]."
    assert drop_ungrounded_document_citations(answer, []) == (answer, [])
