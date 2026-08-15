from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import evaluator


@pytest.mark.asyncio
async def test_evaluator_off_mode_makes_zero_model_calls(monkeypatch) -> None:
    """
    When RAGAS_EVALUATION_MODE is 'off', run_llm_as_judge must instantiate/call
    exactly zero LLMs, embedding models, or ragas.evaluate.
    """
    chat_mock = MagicMock()
    embeddings_mock = MagicMock()
    evaluate_mock = MagicMock()
    update_mock = AsyncMock()

    monkeypatch.setattr(
        evaluator,
        "settings",
        SimpleNamespace(
            RAGAS_EVALUATION_MODE="off",
            RAGAS_SAMPLE_RATE=1.0,
            LITELLM_MASTER_KEY="test-key",
            OMNIGATE_BASE_URL="https://example.com",
        ),
    )
    monkeypatch.setattr(evaluator, "ChatOpenAI", chat_mock)
    monkeypatch.setattr(evaluator, "OpenAIEmbeddings", embeddings_mock)
    monkeypatch.setattr(evaluator, "evaluate", evaluate_mock)

    with patch("app.database.update_evaluation", update_mock):
        await evaluator.run_llm_as_judge(
            user_query="Điều kiện thành lập doanh nghiệp?",
            context=["Luật Doanh nghiệp 2020 Điều 17."],
            bot_response="Theo Luật Doanh nghiệp 2020...",
            trace_id="trace-off-123",
        )

    chat_mock.assert_not_called()
    embeddings_mock.assert_not_called()
    evaluate_mock.assert_not_called()
    update_mock.assert_not_called()


@pytest.mark.asyncio
async def test_evaluator_skips_when_context_is_empty(monkeypatch) -> None:
    chat_mock = MagicMock()
    evaluate_mock = MagicMock()

    monkeypatch.setattr(
        evaluator,
        "settings",
        SimpleNamespace(
            RAGAS_EVALUATION_MODE="all",
            LITELLM_MASTER_KEY="test-key",
            OMNIGATE_BASE_URL="https://example.com",
        ),
    )
    monkeypatch.setattr(evaluator, "ChatOpenAI", chat_mock)
    monkeypatch.setattr(evaluator, "evaluate", evaluate_mock)

    await evaluator.run_llm_as_judge(
        user_query="Câu hỏi không có ngữ cảnh",
        context=[],
        bot_response="Không tìm thấy tài liệu.",
        trace_id="trace-no-context",
    )

    chat_mock.assert_not_called()
    evaluate_mock.assert_not_called()


@pytest.mark.asyncio
async def test_evaluator_sample_mode_deterministic(monkeypatch) -> None:
    chat_mock = MagicMock()
    evaluate_mock = MagicMock()

    # trace-sample-off is chosen such that is_sampled_for_ragas returns False with sample_rate 0.0
    monkeypatch.setattr(
        evaluator,
        "settings",
        SimpleNamespace(
            RAGAS_EVALUATION_MODE="sample",
            RAGAS_SAMPLE_RATE=0.0,  # 0.0 always false
            LITELLM_MASTER_KEY="test-key",
            OMNIGATE_BASE_URL="https://example.com",
        ),
    )
    monkeypatch.setattr(evaluator, "ChatOpenAI", chat_mock)
    monkeypatch.setattr(evaluator, "evaluate", evaluate_mock)

    await evaluator.run_llm_as_judge(
        user_query="Câu hỏi test",
        context=["Context"],
        bot_response="Bot response",
        trace_id="trace-sample-not-selected",
    )

    chat_mock.assert_not_called()
    evaluate_mock.assert_not_called()


@pytest.mark.asyncio
async def test_evaluator_failure_is_typed_and_does_not_mutate_or_throw(
    monkeypatch,
) -> None:
    """
    If Ragas evaluation throws an error, it must be recorded as a typed proxy failure
    without swallowing unobservably or silently setting score 0.0.
    """
    monkeypatch.setattr(
        evaluator,
        "settings",
        SimpleNamespace(
            RAGAS_EVALUATION_MODE="all",
            LITELLM_MASTER_KEY="test-key",
            OMNIGATE_BASE_URL="https://example.com",
        ),
    )
    monkeypatch.setattr(evaluator, "ChatOpenAI", MagicMock())
    monkeypatch.setattr(evaluator, "OpenAIEmbeddings", MagicMock())
    monkeypatch.setattr(evaluator, "Dataset", MagicMock())
    monkeypatch.setattr(evaluator, "_faithfulness", MagicMock())
    monkeypatch.setattr(evaluator, "_answer_relevancy", MagicMock())

    def failing_evaluate(*args, **kwargs):
        raise RuntimeError("Ragas remote connection timeout")


    monkeypatch.setattr(evaluator, "evaluate", failing_evaluate)

    update_eval_called = False
    captured_kwargs: dict = {}

    async def fake_update_evaluation(
        trace_id: str,
        faithfulness=None,
        answer_relevance=None,
        status: str = "ok",
        error: str | None = None,
    ):
        nonlocal update_eval_called, captured_kwargs
        update_eval_called = True
        captured_kwargs = {
            "trace_id": trace_id,
            "faithfulness": faithfulness,
            "answer_relevance": answer_relevance,
            "status": status,
            "error": error,
        }
        return True

    monkeypatch.setattr(
        "app.database.update_evaluation",
        fake_update_evaluation,
    )

    # Should not raise exception
    await evaluator.run_llm_as_judge(
        user_query="Câu hỏi?",
        context=["Context"],
        bot_response="Câu trả lời.",
        trace_id="trace-failure-isolation",
    )

    assert update_eval_called is True
    assert captured_kwargs["status"] == "error"
    assert "Ragas remote connection timeout" in str(captured_kwargs["error"])
    # Scores must NOT be silently set to 0.0
    assert captured_kwargs["faithfulness"] is None
    assert captured_kwargs["answer_relevance"] is None
