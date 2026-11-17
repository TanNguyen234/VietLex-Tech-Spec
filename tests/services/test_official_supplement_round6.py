"""Round-6 official-source fixes: old regional-wage texts are a family rule (not a list only), superseded
versions are skipped before reading or packing, and fragmented Công báo PDF pages use layout extraction."""

import pytest

from app.services.deep_official_search import _is_superseded
from app.services.instrument_registry import assess_expected_instruments, drop_superseded_contexts
from app.services.official_document_reader import _fragment_ratio, _page_text_from


def _context(header: str, title: str, body: str = "Điều 1. Nội dung quy định.") -> str:
    return f"[{header}]\nNguồn: https://example.invalid/van-ban\nTiêu đề: {title}\n{body}"


@pytest.mark.parametrize("header,title", [
    ("107/2010/NĐ-CP, Điều 1", "Nghị định số 107/2010/NĐ-CP quy định mức lương tối thiểu vùng"),
    ("36/2010/TT-BLĐTBXH, Điều 2", "Thông tư số 36/2010/TT-BLĐTBXH hướng dẫn thực hiện mức lương tối thiểu vùng"),
    ("99/2016/NĐ-CP, Điều 3", "Nghị định quy định mức lương tối thiểu vùng"),
])
def test_regional_wage_text_before_2025_is_dropped_by_family_rule(header, title):
    context = _context(header, title)

    kept, dropped = drop_superseded_contexts("Vùng I hiện áp dụng lương tối thiểu bao nhiêu đồng mỗi tháng?", [context])

    assert kept == []
    assert sum(dropped.values()) == 1


@pytest.mark.parametrize("header,title", [
    ("99/2026/NĐ-CP, Điều 3", "Nghị định quy định mức lương tối thiểu vùng"),
    ("293/2025/NĐ-CP, Điều 3", "Nghị định số 293/2025/NĐ-CP quy định mức lương tối thiểu đối với người lao động"),
])
def test_regional_wage_text_from_2025_onward_is_never_dropped_by_family_rule(header, title):
    context = _context(header, title)

    kept, dropped = drop_superseded_contexts("Vùng I hiện áp dụng lương tối thiểu bao nhiêu đồng mỗi tháng?", [context])

    assert kept == [context]
    assert dropped == {}


def test_current_regional_decree_title_without_the_word_vung_counts_as_present():
    contexts = [
        _context("293/2025/NĐ-CP, Điều 3", "Nghị định số 293/2025/NĐ-CP quy định mức lương tối thiểu đối với người lao động",
                 "Vùng I: 5.310.000 đồng/tháng."),
    ]

    result = assess_expected_instruments("Vùng I hiện áp dụng lương tối thiểu bao nhiêu đồng mỗi tháng?", contexts)

    assert "minimum_wage_region" not in result.diagnostics["missing_entries"]


@pytest.mark.parametrize("title,number,question,expected", [
    ("Nghị định số 182/2013/NĐ-CP quy định mức lương tối thiểu vùng", "182/2013/NĐ-CP",
     "Vùng I hiện áp dụng lương tối thiểu bao nhiêu đồng mỗi tháng?", True),
    ("Nghị định số 293/2025/NĐ-CP quy định mức lương tối thiểu đối với người lao động", "293/2025/NĐ-CP",
     "Vùng I hiện áp dụng lương tối thiểu bao nhiêu đồng mỗi tháng?", False),
    ("Nghị định số 182/2013/NĐ-CP quy định mức lương tối thiểu vùng", "182/2013/NĐ-CP",
     "Năm 2013, Vùng I áp dụng lương tối thiểu bao nhiêu?", False),
])
def test_superseded_versions_are_skipped_before_reading(title, number, question, expected):
    assert _is_superseded(question, title, number) is expected


class _FakePage:
    def __init__(self, plain: str, layout: str):
        self._plain = plain
        self._layout = layout

    def extract_text(self, extraction_mode: str = "plain"):
        return self._layout if extraction_mode == "layout" else self._plain


def test_fragmented_plain_page_uses_layout_text():
    plain = "Đ\niều\n1.\nQuy đ\nịnh\nmức\nl\nương\nt\nối\nthiểu\n"
    layout = "     Điều 1. Phạm vi điều chỉnh\n     Quy định mức lương tối thiểu\n"

    text = _page_text_from(_FakePage(plain, layout))

    assert "Điều 1. Phạm vi điều chỉnh" in text
    assert _fragment_ratio(text) < 0.2


def test_clean_plain_page_keeps_plain_text():
    plain = "Điều 1. Phạm vi điều chỉnh\nNghị định này quy định mức lương tối thiểu vùng.\n"

    assert _page_text_from(_FakePage(plain, "unused layout")) == plain
