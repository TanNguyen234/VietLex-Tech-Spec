"""Round-5 superseded filter: outdated texts that the official-web supplement returned as current
are dropped unless the question names their year; current replacements stay expected/kept."""

import pytest

from app.services.instrument_registry import (
    SUPERSEDED_INSTRUMENTS,
    assess_expected_instruments,
    drop_superseded_contexts,
)


def _context(header: str, title: str, body: str = "Điều 1. Nội dung quy định.") -> str:
    return f"[{header}]\nNguồn: https://example.invalid/van-ban\nTiêu đề: {title}\n{body}"


@pytest.mark.parametrize(
    "header,title,question",
    [
        ("103/2012/NĐ-CP, Điều 3, Khoản 1, Điểm a", "Nghị định số 103/2012/NĐ-CP quy định mức lương tối thiểu vùng",
         "Vùng I hiện áp dụng lương tối thiểu bao nhiêu đồng mỗi tháng?"),
        ("182/2013/NĐ-CP, Điều 3, Khoản 1, Điểm a", "Nghị định số 182/2013/NĐ-CP quy định mức lương tối thiểu vùng",
         "mức lương tối thiểu vùng năm nay là bao nhiêu tiền một tháng?"),
        ("103/2014/NĐ-CP, Điều 3", "Nghị định 103/2014/NĐ-CP quy định mức lương tối thiểu vùng",
         "lương tối thiểu vùng mới nhất theo nghị định là bao nhiêu?"),
        ("122/2015/NĐ-CP, Điều 3", "Nghị định 122/2015/NĐ-CP quy định mức lương tối thiểu vùng",
         "lương tối thiểu vùng hiện nay là bao nhiêu?"),
        ("153/2016/NĐ-CP, Điều 3", "Nghị định 153/2016/NĐ-CP quy định mức lương tối thiểu vùng",
         "lương tối thiểu vùng hiện nay là bao nhiêu?"),
        ("90/2019/NĐ-CP, Điều 3", "Nghị định 90/2019/NĐ-CP quy định mức lương tối thiểu vùng",
         "lương tối thiểu vùng hiện nay là bao nhiêu?"),
        ("74/2024/NĐ-CP, Điều 3, Khoản 1", "Nghị định 74/2024/NĐ-CP quy định mức lương tối thiểu vùng",
         "lương tối thiểu vùng hiện nay là bao nhiêu?"),
        ("29/2012/TT-BLĐTBXH, Điều 2", "Thông tư 29/2012/TT-BLĐTBXH hướng dẫn mức lương tối thiểu vùng",
         "Vùng I hiện áp dụng lương tối thiểu bao nhiêu đồng mỗi tháng?"),
        ("33/2013/TT-BLĐTBXH, Điều 2", "Thông tư 33/2013/TT-BLĐTBXH hướng dẫn mức lương tối thiểu vùng",
         "Vùng I hiện áp dụng lương tối thiểu bao nhiêu đồng mỗi tháng?"),
        ("53/2014/QH13, Điều 2", "Luật Công chứng 2014",
         "Mua bán quyền sử dụng đất có buộc phải công chứng hợp đồng không?"),
        ("38/2019/QH14, Điều 59, Khoản 2, Điểm a", "Luật Quản lý thuế số 38/2019/QH14",
         "Nộp thuế trễ hạn thì tiền chậm nộp tính theo tỷ lệ bao nhiêu mỗi ngày?"),
        ("309-LĐTL, Điều 1", "Thông tư 309-LĐTL quy định tạm thời về nghỉ hàng năm của thuyền viên",
         "Điều 999 BLLĐ 2019 nói gì về ngày nghỉ phép năm?"),
        ("05/2007/NĐ-CP, Điều 10, Khoản 1", "Nghị định 05/2007/NĐ-CP về phòng, chống bệnh dại ở động vật",
         "mua chó cảnh ở chợ có bị cấm không?"),
        ("118/2005/NĐ-CP, Điều 1", "Nghị định 118/2005/NĐ-CP điều chỉnh mức lương tối thiểu chung",
         "mức lương tối thiểu chung hiện nay là bao nhiêu?"),
        ("22/2011/NĐ-CP, Điều 1", "Nghị định số 22/2011/NĐ-CP quy định mức lương tối thiểu chung",
         "mức lương tối thiểu chung hiện nay là bao nhiêu?"),
        ("70/2011/NĐ-CP, Điều 3", "Nghị định 70/2011/NĐ-CP quy định mức lương tối thiểu vùng",
         "Vùng I hiện áp dụng lương tối thiểu bao nhiêu đồng mỗi tháng?"),
        ("23/2011/TT-BLĐTBXH, Điều 3", "Thông tư số 23/2011/TT-BLĐTBXH hướng dẫn mức lương tối thiểu vùng",
         "Vùng I hiện áp dụng lương tối thiểu bao nhiêu đồng mỗi tháng?"),
    ],
)
def test_round5_superseded_text_is_dropped_when_the_question_names_no_year(header, title, question):
    context = _context(header, title)

    kept, dropped = drop_superseded_contexts(question, [context])

    assert kept == []
    assert sum(dropped.values()) == 1


@pytest.mark.parametrize(
    "header,title,question",
    [
        ("182/2013/NĐ-CP, Điều 3, Khoản 1, Điểm a", "Nghị định số 182/2013/NĐ-CP quy định mức lương tối thiểu vùng",
         "Năm 2013, Vùng I áp dụng lương tối thiểu bao nhiêu?"),
        ("74/2024/NĐ-CP, Điều 3, Khoản 1", "Nghị định 74/2024/NĐ-CP quy định mức lương tối thiểu vùng",
         "Năm 2024, Vùng I áp dụng lương tối thiểu bao nhiêu?"),
        ("53/2014/QH13, Điều 2", "Luật Công chứng 2014",
         "Năm 2014, công chứng hợp đồng chuyển nhượng cần những gì?"),
    ],
)
def test_round5_superseded_text_is_kept_when_the_question_names_its_year(header, title, question):
    context = _context(header, title)

    kept, dropped = drop_superseded_contexts(question, [context])

    assert kept == [context]
    assert dropped == {}


@pytest.mark.parametrize(
    "header,title",
    [
        ("293/2025/NĐ-CP, Điều 3", "Nghị định quy định mức lương tối thiểu vùng"),
        ("46/2024/QH15, Điều 44", "Luật Công chứng 2024"),
        ("108/2025/QH15, Điều 16, Khoản 2", "Luật Quản lý thuế số 108/2025/QH15"),
    ],
)
def test_round5_current_text_is_never_dropped(header, title):
    context = _context(header, title)

    kept, dropped = drop_superseded_contexts("Vùng I hiện áp dụng lương tối thiểu bao nhiêu đồng mỗi tháng?", [context])

    assert kept == [context]
    assert dropped == {}


def test_superseded_registry_keys_are_unique():
    keys = [item.key for item in SUPERSEDED_INSTRUMENTS]

    assert len(keys) == len(set(keys))


def test_notary_question_drops_the_2014_law_and_expects_the_2024_law() -> None:
    contexts = [
        _context("53/2014/QH13, Điều 2", "Luật Công chứng 2014",
                 "Điều 2. Công chứng hợp đồng chuyển nhượng quyền sử dụng đất."),
    ]

    result = assess_expected_instruments("Mua bán quyền sử dụng đất có buộc phải công chứng hợp đồng không?", contexts)

    assert result.kept_contexts == ()
    assert "notary_law_2024" in result.diagnostics["missing_entries"]
    assert any("46/2024" in query for query in result.queries)


def test_late_payment_question_drops_the_2019_tax_law_and_expects_the_2025_law() -> None:
    contexts = [
        _context("38/2019/QH14, Điều 59, Khoản 2, Điểm a", "Luật Quản lý thuế số 38/2019/QH14",
                 "Mức tính tiền chậm nộp bằng 0,03%/ngày."),
    ]

    result = assess_expected_instruments("Nộp thuế trễ hạn thì tiền chậm nộp tính theo tỷ lệ bao nhiêu mỗi ngày?", contexts)

    assert result.kept_contexts == ()
    assert "tax_administration_2025" in result.diagnostics["missing_entries"]
    assert any("108/2025" in query for query in result.queries)


def test_minimum_wage_question_drops_old_regional_decrees_and_asks_for_the_current_one() -> None:
    contexts = [
        _context("182/2013/NĐ-CP, Điều 3, Khoản 1, Điểm a",
                 "Nghị định số 182/2013/NĐ-CP quy định mức lương tối thiểu vùng", "Vùng I: 2.700.000 đồng/tháng."),
        _context("103/2012/NĐ-CP, Điều 3, Khoản 1, Điểm a",
                 "Nghị định số 103/2012/NĐ-CP quy định mức lương tối thiểu vùng", "Vùng I: 2.350.000 đồng/tháng."),
    ]

    result = assess_expected_instruments("Vùng I hiện áp dụng lương tối thiểu bao nhiêu đồng mỗi tháng?", contexts)

    assert result.kept_contexts == ()
    assert "minimum_wage_region" in result.diagnostics["missing_entries"]
    assert any("293/2025" in query for query in result.queries)


def test_current_regional_decree_satisfies_the_minimum_wage_entry() -> None:
    contexts = [
        _context("293/2025/NĐ-CP, Điều 3", "Nghị định quy định mức lương tối thiểu vùng", "Vùng I: 5.310.000 đồng/tháng."),
    ]

    result = assess_expected_instruments("Vùng I hiện áp dụng lương tối thiểu bao nhiêu đồng mỗi tháng?", contexts)

    assert result.kept_contexts == tuple(contexts)
    assert "minimum_wage_region" not in result.diagnostics["missing_entries"]
