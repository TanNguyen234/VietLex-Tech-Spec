import pytest

from app.evaluation.case_selection import select_evaluation_cases
from app.evaluation.schemas import GoldEvidence, GoldenCase


def _case(case_id: str, *, verified: bool = True) -> GoldenCase:
    evidence = GoldEvidence(
        evidence_item_id=f"{case_id}-e1",
        case_id=case_id,
        required=True,
        required_level="article",
        status="verified" if verified else "ambiguous",
    )
    return GoldenCase(
        case_id=case_id,
        question=f"Question {case_id}",
        question_type="factoid",
        answerable=True,
        reference_answer="Answer",
        gold_evidence=[evidence],
    )


def test_requested_case_ids_select_exact_order() -> None:
    result = select_evaluation_cases(
        [_case("case_001"), _case("case_002"), _case("case_003")],
        "all-required-verified",
        requested_case_ids=["case_003", "case_001"],
    )

    assert result.selected_case_ids == ["case_003", "case_001"]
    assert result.selected_case_count == 2
    assert result.total_candidate_cases == 3


@pytest.mark.parametrize(
    "requested",
    [["case_999"], ["case_001", "case_001"], ["case_002"]],
)
def test_requested_case_ids_fail_closed(requested: list[str]) -> None:
    cases = [_case("case_001"), _case("case_002", verified=False)]

    with pytest.raises(ValueError, match="requested case"):
        select_evaluation_cases(
            cases,
            "all-required-verified",
            requested_case_ids=requested,
        )
