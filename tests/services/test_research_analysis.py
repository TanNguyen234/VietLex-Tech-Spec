import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from pydantic import ValidationError

from app.services.research_analysis import (
    ComparisonResult,
    ObligationMatrixResult,
    build_selected_evidence_prompt,
    parse_comparison,
    parse_obligation_matrix,
    generate_comparison,
    generate_selected_evidence_answer,
)


def test_selected_evidence_prompt_contains_only_selected_records() -> None:
    prompt = build_selected_evidence_prompt(
        "Phân tích nghĩa vụ",
        [
            {
                "evidence_id": "ev-1",
                "citation": "Điều 1",
                "excerpt": "Bên A phải báo cáo.",
            },
            {
                "evidence_id": "ev-2",
                "citation": "Điều 2",
                "excerpt": "Bên B được lựa chọn.",
            },
        ],
    )

    assert "ev-1" in prompt and "ev-2" in prompt
    assert "global retrieval" not in prompt.casefold()


def test_comparison_schema_requires_selected_evidence_links() -> None:
    raw = (
        '{"findings":[{"topic":"Thời hạn","document_a_finding":"30 ngày",'
        '"document_b_finding":"45 ngày","interpretation":"Khác nhau",'
        '"evidence_a":["ev-a"],"evidence_b":["ev-b"],'
        '"support_state":"directly_supported","change_type":"difference"}]}'
    )

    result = parse_comparison(raw, {"ev-a", "ev-b"})

    assert isinstance(result, ComparisonResult)
    with pytest.raises(ValidationError):
        parse_comparison(raw, {"ev-a"})


def test_comparison_schema_rejects_cross_group_provenance() -> None:
    raw = (
        '{"findings":[{"topic":"Thời hạn","document_a_finding":"30 ngày",'
        '"document_b_finding":"45 ngày","interpretation":"Khác nhau",'
        '"evidence_a":["ev-b"],"evidence_b":["ev-a"],'
        '"support_state":"directly_supported","change_type":"difference"}]}'
    )

    with pytest.raises(ValidationError):
        parse_comparison(
            raw, {"ev-a", "ev-b"}, group_a_ids={"ev-a"}, group_b_ids={"ev-b"}
        )


def test_obligation_schema_preserves_modality_and_rejects_unknown_evidence() -> None:
    raw = (
        '{"rows":[{"subject":"Người sử dụng lao động","action":"Thông báo",'
        '"modality":"required","condition":null,"deadline":"03 ngày",'
        '"exception":null,"evidence_ids":["ev-1"],'
        '"support_state":"needs_verification"}]}'
    )

    result = parse_obligation_matrix(raw, {"ev-1"})

    assert isinstance(result, ObligationMatrixResult)
    assert result.rows[0].modality == "required"
    with pytest.raises(ValidationError):
        parse_obligation_matrix(raw, set())


def test_structured_parsers_do_not_strip_markdown_fences() -> None:
    with pytest.raises(ValidationError):
        parse_comparison('```json\n{"findings": []}\n```', set())


def test_selected_context_budget_rejects_instead_of_silently_truncating() -> None:
    with pytest.raises(ValueError, match="evidence_scope_too_large"):
        build_selected_evidence_prompt(
            "Q", [{"evidence_id": "a", "excerpt": "word " * 721}]
        )


@pytest.mark.asyncio
async def test_comparison_never_drops_group_b_before_generation(monkeypatch) -> None:
    from app.services import research_analysis as analysis

    generate = AsyncMock(
        return_value=SimpleNamespace(
            status="success",
            text='{"findings": []}',
            observed_provider="test",
            observed_model="test",
        )
    )
    monkeypatch.setattr(analysis, "_generate", generate)
    with pytest.raises(ValueError, match="evidence_scope_too_large"):
        await generate_comparison(
            [{"evidence_id": f"a-{i}", "excerpt": "A"} for i in range(10)],
            [{"evidence_id": "b", "excerpt": "B"}],
        )
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_selected_answer_preserves_insufficient_evidence_state(
    monkeypatch,
) -> None:
    from app.services import research_analysis as analysis

    generate = AsyncMock(
        return_value=SimpleNamespace(
            status="success",
            text='{"status":"insufficient_evidence","text":"Không đủ bằng chứng","evidence_ids":[]}',
            observed_provider="test",
            observed_model="test",
        )
    )
    monkeypatch.setattr(analysis, "_generate", generate)
    result = await generate_selected_evidence_answer(
        "Q", [{"evidence_id": "a", "excerpt": "A"}]
    )
    assert result["status"] == "insufficient_evidence"

    generate.return_value.text = (
        '{"status":"ok","text":"Answer","evidence_ids":["forged"]}'
    )
    result = await generate_selected_evidence_answer(
        "Q", [{"evidence_id": "a", "excerpt": "A"}]
    )
    assert result["status"] == "invalid_structured_response"
    assert "forged" not in str(result)
