"""Expected current instruments and superseded versions are checked against retrieved headers only."""

from types import SimpleNamespace

import pytest

from app.services.deep_official_search import search_and_read
from app.services.instrument_registry import assess_expected_instruments


def _labor_code(article: str, body: str) -> str:
    return (
        f"[45/2019/QH14, Điều {article}]\n"
        "Nguồn: https://example.invalid/45-2019\n"
        "Tiêu đề: Bộ luật Lao động 2019\n"
        f"{body}"
    )


def test_missing_social_insurance_law_when_only_labor_code_is_retrieved() -> None:
    contexts = [_labor_code("169", "Người lao động được hưởng lương hưu khi đủ tuổi nghỉ hưu.")]

    result = assess_expected_instruments(
        "Đóng bảo hiểm xã hội bao nhiêu năm thì được hưởng lương hưu?", contexts
    )

    assert "social_insurance_2024" in result.diagnostics["missing_entries"]
    assert result.kept_contexts == tuple(contexts)
    assert any("bảo hiểm xã hội" in query.casefold() for query in result.queries)


def test_current_social_insurance_header_satisfies_the_registry() -> None:
    contexts = [
        "[41/2024/QH15, Điều 70]\n"
        "Nguồn: https://example.invalid/41-2024\n"
        "Tiêu đề: Luật Bảo hiểm xã hội 2024\n"
        "Hưởng bảo hiểm xã hội một lần khi đủ tuổi hưởng lương hưu mà chưa đủ 15 năm.",
    ]

    result = assess_expected_instruments(
        "Nghỉ việc rồi thì có được rút bảo hiểm xã hội một lần không?", contexts
    )

    assert "social_insurance_2024" not in result.diagnostics["missing_entries"]


def test_superseded_official_web_text_is_dropped_from_supplement_contexts() -> None:
    from app.services.instrument_registry import drop_superseded_contexts

    official = (
        "[Nguồn chính thức ngoài VietLex · 58/2014/QH13]\n"
        "Nguồn: https://example.invalid/58-2014\n"
        "Nguồn loại: official_external\n"
        "Hiệu lực pháp lý: unverified\n"
        "SHA-256 nguồn: " + "a" * 64 + "\n"
        "Tiêu đề: Luật Bảo hiểm xã hội 2014\n"
        "Người lao động đóng bảo hiểm xã hội đủ 20 năm được hưởng lương hưu."
    )

    kept, dropped = drop_superseded_contexts("Đóng bảo hiểm xã hội bao nhiêu năm thì được hưởng lương hưu?", [official])

    assert kept == []
    assert dropped == {"bhxh_law_2014": 1}


def test_body_mention_of_a_current_law_does_not_count_as_present() -> None:
    contexts = [
        _labor_code("169", "Xem thêm Luật Bảo hiểm xã hội 41/2024/QH15 về lương hưu.")
    ]

    result = assess_expected_instruments("Lương hưu cần đóng bao nhiêu năm bảo hiểm xã hội?", contexts)

    assert "social_insurance_2024" in result.diagnostics["missing_entries"]


def test_superseded_traffic_decree_is_dropped_and_current_decree_is_missing() -> None:
    contexts = [
        "[143-CP, Điều 15, Khoản 7]\n"
        "Nguồn: https://example.invalid/143-cp\n"
        "Tiêu đề: Điều lệ về phạt vi cảnh\n"
        "Điều khiển xe cơ giới trong tình trạng say rượu."
    ]

    result = assess_expected_instruments("Đi xe máy say rượu thì bị xử lý thế nào và có bị giữ xe không?", contexts)

    assert result.kept_contexts == ()
    assert result.diagnostics["superseded_dropped"] == {"traffic_decree_1977": 1}
    assert "traffic_penalty_decree_2024" in result.diagnostics["missing_entries"]


def test_superseded_text_is_kept_only_when_the_question_names_its_year() -> None:
    contexts = [
        "[143-CP, Điều 15, Khoản 7]\n"
        "Nguồn: https://example.invalid/143-cp\n"
        "Tiêu đề: Điều lệ về phạt vi cảnh\n"
        "Điều khiển xe cơ giới trong tình trạng say rượu."
    ]

    result = assess_expected_instruments("Quy định năm 1977 về say rượu khi lái xe là gì?", contexts)

    assert result.kept_contexts == tuple(contexts)
    assert result.diagnostics["superseded_dropped"] == {}


def test_minimum_wage_region_instrument_is_missing_without_a_regional_decree() -> None:
    contexts = [_labor_code("91", "Mức lương tối thiểu là mức lương thấp nhất được trả cho người lao động.")]

    result = assess_expected_instruments("Lương tối thiểu vùng hiện nay là bao nhiêu?", contexts)

    assert "minimum_wage_region" in result.diagnostics["missing_entries"]
    assert result.queries and len(result.queries) <= 4


def test_unrelated_question_matches_no_registry_entry() -> None:
    contexts = [_labor_code("1", "Phạm vi điều chỉnh.")]

    result = assess_expected_instruments("Thủ tục đăng ký kinh doanh hộ kinh doanh là gì?", contexts)

    assert result.diagnostics["matched_entries"] == []
    assert result.missing == ()
    assert result.queries == ()


def test_diagnostics_never_carry_the_question_text() -> None:
    question = "Chồng tôi có thu nhập cá nhân cao, em muốn hỏi về giảm trừ gia cảnh"
    result = assess_expected_instruments(question, [])

    assert question not in str(result.diagnostics)
    assert "personal_income_tax_2025" in result.diagnostics["missing_entries"]


@pytest.mark.asyncio
async def test_registry_queries_replace_the_derived_plan_in_the_deep_search() -> None:
    class RecordingProvider:
        def __init__(self) -> None:
            self.queries: list[str] = []

        async def search(self, query, limit=8):
            self.queries.append(query)
            return SimpleNamespace(results=(), errors=())

    provider = RecordingProvider()
    explicit = ("Luật Công chứng 2014 công chứng hợp đồng chuyển nhượng bất động sản",)

    await search_and_read(
        "Bán đất có bắt buộc phải công chứng không?",
        settings=SimpleNamespace(),
        providers=[provider],
        reader=None,
        explicit_queries=explicit,
        explicit_topics=("cong chung",),
    )

    assert provider.queries == list(explicit)
