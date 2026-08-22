from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import evaluator


def _settings(mode: str, sample_rate: float = 1.0) -> SimpleNamespace:
    return SimpleNamespace(RAGAS_EVALUATION_MODE=mode, RAGAS_SAMPLE_RATE=sample_rate)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "sample_rate", "contexts"),
    [("off", 1.0, ["c"]), ("all", 1.0, []), ("sample", 0.0, ["c"])],
)
async def test_evaluator_skips_without_instantiating_judge(
    monkeypatch, mode, sample_rate, contexts
) -> None:
    scorer = AsyncMock()
    update = AsyncMock()
    monkeypatch.setattr(evaluator, "settings", _settings(mode, sample_rate))
    monkeypatch.setattr(evaluator, "_score_ragas_metrics", scorer)
    monkeypatch.setattr("app.database.update_evaluation", update)

    await evaluator.run_llm_as_judge("q", contexts, "a", "trace-skip")

    scorer.assert_not_awaited()
    update.assert_not_awaited()


@pytest.mark.asyncio
async def test_modern_ragas_scorer_is_used_and_scores_are_persisted(monkeypatch) -> None:
    scorer = AsyncMock(return_value={"faithfulness": 0.91, "answer_relevance": 0.87})
    update = AsyncMock(return_value=True)
    monkeypatch.setattr(evaluator, "settings", _settings("all"))
    monkeypatch.setattr(evaluator, "_score_ragas_metrics", scorer)
    monkeypatch.setattr("app.database.update_evaluation", update)

    await evaluator.run_llm_as_judge("q", ["c"], "a", "trace-modern")

    scorer.assert_awaited_once_with("q", ["c"], "a")
    assert update.await_args.kwargs["faithfulness"] == 0.91
    assert update.await_args.kwargs["answer_relevance"] == 0.87
    assert update.await_args.kwargs["status"] == "ok"


@pytest.mark.asyncio
async def test_failure_is_typed_without_fake_zero_scores(monkeypatch) -> None:
    scorer = AsyncMock(side_effect=RuntimeError("Ragas remote connection timeout"))
    update = AsyncMock(return_value=True)
    monkeypatch.setattr(evaluator, "settings", _settings("all"))
    monkeypatch.setattr(evaluator, "_score_ragas_metrics", scorer)
    monkeypatch.setattr("app.database.update_evaluation", update)

    await evaluator.run_llm_as_judge("q", ["c"], "a", "trace-error")

    values = update.await_args.kwargs
    assert values["status"] == "error"
    assert values["faithfulness"] is None
    assert values["answer_relevance"] is None
    assert values["error"]["error_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_failure_redacts_secrets_before_persistence(monkeypatch) -> None:
    scorer = AsyncMock(
        side_effect=RuntimeError("?api_key=sk-secret Bearer private-token")
    )
    update = AsyncMock(return_value=True)
    monkeypatch.setattr(evaluator, "settings", _settings("all"))
    monkeypatch.setattr(evaluator, "_score_ragas_metrics", scorer)
    monkeypatch.setattr("app.database.update_evaluation", update)

    await evaluator.run_llm_as_judge("q", ["c"], "a", "trace-secret")

    message = update.await_args.kwargs["error"]["message"]
    assert "sk-secret" not in message
    assert "private-token" not in message
    assert "[REDACTED]" in message


def test_numeric_score_rejects_out_of_range_values() -> None:
    with pytest.raises(ValueError, match="invalid score"):
        evaluator._numeric_score(1.2, "faithfulness")
