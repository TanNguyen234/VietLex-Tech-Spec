import pytest

from app.evaluation.answer_metrics import calculate_case_answer_metrics
from app.evaluation.legal_citations import LegalCitation, parse_legal_citations


@pytest.mark.parametrize("number", ["04/VBHN-NHNN", "5020/QĐ-UB"])
def test_non_year_document_number_keeps_its_own_article_identity(number):
    assert parse_legal_citations(f"Khoản 1 Điều 7 văn bản {number}") == [
        LegalCitation(number, "Điều 7", "Khoản 1")
    ]


def metric_for(answer, context):
    return calculate_case_answer_metrics(
        answer, "CO2 và methane.", "factoid", [context]
    )


@pytest.mark.parametrize("clause", [1, 2])
def test_numbered_clause_in_whole_article_evidence_is_a_supported_locator(clause):
    context = (
        "[72/2020/QH14, Điều 91]\nNguồn: https://example.invalid/law\n"
        "Điều 91. Giảm nhẹ phát thải khí nhà kính\n"
        "1. Các khí nhà kính chính bao gồm CO2 và methane.\n"
        "2. Tổ chức kiểm kê khí nhà kính."
    )
    result = metric_for(f"Khoản {clause} Điều 91 văn bản 72/2020/QH14.", context)
    assert result["citation_precision"] == 1.0
    assert result["invalid_citation_rate"] == 0.0


@pytest.mark.parametrize("citation", [
    "Khoản 999 Điều 91 văn bản 72/2020/QH14",
    "Khoản 2 Điều 92 văn bản 72/2020/QH14",
    "Khoản 2 Điều 91 văn bản 12/2026/NĐ-CP",
])
def test_containment_does_not_bless_absent_clause_article_or_document(citation):
    context = "[72/2020/QH14, Điều 91]\nĐiều 91. Khí nhà kính 1. CO2. 2. Methane."
    result = metric_for(citation, context)
    assert result["citation_precision"] == 0.0
    assert result["invalid_citation_rate"] == 1.0


@pytest.mark.parametrize("body", [
    "1. CO2 và methane.",  # Partial fragment, no own article heading.
    "Điều 91. Hệ số 1.25 được dùng để tính toán.",
    "Điều 91. Theo điều 9. Quy định được dẫn ở văn bản khác.",
])
def test_partial_fragment_decimal_or_cross_reference_does_not_invent_clause(body):
    context = "[72/2020/QH14, Điều 91]\n" + body
    result = metric_for("Khoản 1 Điều 91 văn bản 72/2020/QH14", context)
    assert result["citation_precision"] == 0.0


def test_numbering_in_next_article_does_not_support_the_previous_article():
    context = (
        "[72/2020/QH14, Điều 91]\nĐiều 91. Khí nhà kính\n1. CO2.\n"
        "Điều 92. Nội dung khác\n2. Nội dung không thuộc Điều 91."
    )
    result = metric_for("Khoản 2 Điều 91 văn bản 72/2020/QH14", context)
    assert result["invalid_citation_rate"] == 1.0

