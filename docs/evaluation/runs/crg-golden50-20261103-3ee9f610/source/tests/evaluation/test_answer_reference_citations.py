import pytest

from app.evaluation.answer_metrics import calculate_case_answer_metrics


CONTEXTS = [
    '[72/2020/QH14, Điều 34, Khoản 6]\nĐiều 34. Thẩm định 6. Thời gian chỉnh sửa không tính vào thời hạn.',
    '[72/2020/QH14, Điều 34, Khoản 5]\nĐiều 34. Thẩm định 5. Cơ quan thông báo bằng văn bản.',
    '[09/2026/TT-BNNMT, Điều 4]\nĐiều 4. Bổ sung điều khoản.',
]


def score(answer, contexts=CONTEXTS):
    return calculate_case_answer_metrics(answer, 'tham khảo', 'answerable', contexts)


def test_explicit_source_index_prevents_later_disclaimer_document_misattribution():
    metrics = score('Thông báo bằng văn bản [Tài liệu tham khảo #2, Điều 34, Khoản 5].\n\n'
                    'Lưu ý: hiệu lực Thông tư 09/2026/TT-BNNMT chưa được xác minh.')
    assert metrics['citation_precision'] == 1.0
    assert metrics['invalid_citation_rate'] == 0.0


def test_parenthetical_source_index_binds_preceding_article_and_clause():
    metrics = score('Theo Khoản 5 Điều 34 Luật Bảo vệ môi trường 2020 '
                    '(Tài liệu tham khảo #2).\n\nThông tư 09/2026/TT-BNNMT cần kiểm tra hiệu lực.')
    assert metrics['citation_precision'] == 1.0


@pytest.mark.parametrize('index', ['0', '999', '-1'])
def test_nonexistent_source_index_is_invalid_even_when_legal_locator_exists(index):
    metrics = score(f'Thông báo [Tài liệu tham khảo #{index}, Điều 34, Khoản 5].')
    assert metrics['invalid_citation_rate'] > 0


def test_source_pointer_cannot_bless_a_wrong_clause():
    assert score('Theo Khoản 999 Điều 34 (Tài liệu tham khảo #2).')['invalid_citation_rate'] == 1.0


def test_pointer_conflicting_with_explicit_document_stays_invalid():
    metrics = score('Khoản 5 Điều 34 của 72/2020/QH14 [Tài liệu tham khảo #3].')
    assert metrics['invalid_citation_rate'] > 0


def test_pointer_does_not_replace_an_explicit_wrong_document():
    metrics = score('Khoản 5 Điều 34 của 55/2014/QH13 [Tài liệu tham khảo #2].')
    assert metrics['invalid_citation_rate'] > 0


def test_bare_source_pointer_resolves_only_supplied_header_identity():
    assert score('Thông báo bằng văn bản [Tài liệu tham khảo #2].')['citation_precision'] == 1.0


def test_unresolvable_source_header_does_not_invent_document_identity():
    metrics = score('Theo Điều 34 (Tài liệu tham khảo #1).', ['Nội dung không có định danh văn bản.'])
    assert metrics['citation_precision'] is None


@pytest.mark.parametrize('index,valid', [('9' * 5000, False), ('0' * 5000 + '2', True)],
                         ids=['oversized', 'padded_valid'])
def test_oversized_numeric_pointer_never_crashes_metric_evaluation(index, valid):
    metrics = score(f'Thông báo [Tài liệu tham khảo #{index}, Điều 34, Khoản 5].')
    assert (metrics['invalid_citation_rate'] == 0) is valid
