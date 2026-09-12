import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import official_query_planner as planner


@pytest.mark.asyncio
async def test_disabled_research_never_calls_keyword_model(monkeypatch):
    from app.services.deep_research import DeepResearchDisabled
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "OFFICIAL_WEB_RESEARCH_ENABLED", False)
    generate = AsyncMock()
    monkeypatch.setattr(planner, "_generate", generate)
    with pytest.raises(DeepResearchDisabled):
        await planner.prepare_research_plan("Quy định bảo hiểm nông nghiệp?")
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_natural_question_uses_bounded_keywords_without_invented_law(monkeypatch):
    generate = AsyncMock(
        return_value=SimpleNamespace(
            status="success",
            finish_reason="STOP",
            text=json.dumps(
                {
                    "queries": [
                        "phụ cấp ưu đãi nghề",
                        "nhân viên y tế",
                        "phụ cấp y tế",
                        "chế độ phụ cấp",
                        "cơ sở y tế",
                    ]
                }
            ),
            observed_provider="observed",
            observed_model="observed-model",
        )
    )
    monkeypatch.setattr(planner, "_generate", generate)
    plan = await planner.prepare_research_plan(
        "Nhân viên y tế hưởng phụ cấp ưu đãi nghề như thế nào trong tháng 9/2026?"
    )
    assert plan.steps[0].query == "phụ cấp ưu đãi nghề"
    assert plan.query_method == "model_keywords"
    assert plan.planner_provider == "observed"
    assert plan.question.endswith("9/2026?")


@pytest.mark.asyncio
async def test_exact_reference_does_not_require_model(monkeypatch):
    generate = AsyncMock()
    monkeypatch.setattr(planner, "_generate", generate)
    plan = await planner.prepare_research_plan("Nội dung 350/2026/NĐ-CP?")
    assert all("350/2026/NĐ-CP" in s.query for s in plan.steps)
    generate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(
            status="timeout",
            finish_reason=None,
            text="",
            observed_provider="p",
            observed_model="m",
        ),
        SimpleNamespace(
            status="success",
            finish_reason="STOP",
            text='{"queries":["999/2026/NĐ-CP"]}',
            observed_provider="p",
            observed_model="m",
        ),
    ],
)
async def test_failure_or_invented_reference_is_explicit_fallback(
    monkeypatch, response
):
    monkeypatch.setattr(planner, "_generate", AsyncMock(return_value=response))
    plan = await planner.prepare_research_plan(
        "Quy định về bảo hiểm nông nghiệp là gì?"
    )
    assert plan.query_method == "fallback"
    assert plan.planner_error
    assert "999/2026" not in str(plan)
