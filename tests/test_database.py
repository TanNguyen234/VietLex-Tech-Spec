from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.database import log_interaction, update_evaluation


@pytest.mark.asyncio
async def test_log_interaction_persists_all_operational_fields() -> None:
    fake_collection = AsyncMock()
    fake_db = MagicMock()
    fake_db.evaluation_logs = fake_collection

    with patch("app.database.get_db", return_value=fake_db):
        doc = await log_interaction(
            trace_id="trace-db-test-01",
            user_query="Quy định thuế GTGT?",
            bot_response="Theo Luật Thuế GTGT...",
            contexts=["Context 1"],
            cached=False,
            session_id="session-01",
            request_status="ok",
            latency={"t_total": 0.45, "t_retrieval": 0.15, "t_llm": 0.30},
            observed_provider="openrouter",
            observed_model="google/gemini-2.5-flash",
            provider_usage={
                "query_rewrite": {"provider": "gemini", "model": "gemini-2.5-flash", "observed": True},
                "answer_generation": {"provider": "openrouter", "model": "google/gemini-2.5-flash", "observed": True},
                "guardrails": {"provider": "unobserved", "model": "unobserved", "observed": False},
            },
            ragas_mode="sample",
            ragas_status="selected",
            ragas_selected=True,
            ragas_executed=False,
            citation_count=1,
            context_count=1,
            no_evidence=False,
            technical_error=None,
        )

    assert doc["_id"] == "trace-db-test-01"
    metrics = doc["metrics"]
    assert metrics["request_status"] == "ok"
    assert metrics["ragas_selected"] is True
    assert metrics["ragas_executed"] is False
    assert metrics["observed_provider"] == "openrouter"
    assert metrics["observed_model"] == "google/gemini-2.5-flash"
    assert metrics["provider_usage"]["query_rewrite"]["provider"] == "gemini"
    assert metrics["latency"]["t_total"] == 0.45
    assert metrics["citation_count"] == 1
    assert metrics["context_count"] == 1
    assert metrics["no_evidence"] is False
    assert metrics["technical_error"] is None

    # Verify no ambiguous old aliases are written for new records
    assert "faithfulness" not in metrics
    assert "answer_relevance" not in metrics
    assert metrics["ragas_proxy_faithfulness"] is None
    assert metrics["ragas_proxy_answer_relevance"] is None

    fake_collection.replace_one.assert_called_once_with(
        {"_id": "trace-db-test-01"},
        doc,
        upsert=True,
    )


@pytest.mark.asyncio
async def test_log_interaction_persists_technical_error() -> None:
    fake_collection = AsyncMock()
    fake_db = MagicMock()
    fake_db.evaluation_logs = fake_collection

    tech_error = {"stage": "retrieval_error", "error_type": "RetrievalPipelineError", "message": "Qdrant timeout"}

    with patch("app.database.get_db", return_value=fake_db):
        doc = await log_interaction(
            trace_id="trace-db-error-02",
            user_query="Câu hỏi lỗi",
            bot_response="Lỗi hệ thống",
            contexts=[],
            cached=False,
            session_id="session-02",
            request_status="technical_error",
            latency={"t_total": 0.12},
            technical_error=tech_error,
        )

    metrics = doc["metrics"]
    assert metrics["request_status"] == "technical_error"
    assert metrics["technical_error"] == tech_error
    assert metrics["ragas_selected"] is False
    assert metrics["ragas_executed"] is False


@pytest.mark.asyncio
async def test_update_evaluation_sets_ragas_executed_and_proxy_metrics() -> None:
    fake_collection = AsyncMock()
    fake_collection.update_one.return_value = MagicMock(modified_count=1)
    fake_db = MagicMock()
    fake_db.evaluation_logs = fake_collection

    with patch("app.database.get_db", return_value=fake_db):
        ok = await update_evaluation(
            trace_id="trace-eval-01",
            faithfulness=0.92,
            answer_relevance=0.88,
            status="ok",
            executed=True,
            error=None,
        )

    assert ok is True
    call_args = fake_collection.update_one.call_args[0]
    filter_doc, update_doc = call_args[0], call_args[1]
    assert filter_doc == {"_id": "trace-eval-01"}
    set_data = update_doc["$set"]
    assert set_data["metrics.ragas_proxy_faithfulness"] == 0.92
    assert set_data["metrics.ragas_proxy_answer_relevance"] == 0.88
    assert set_data["metrics.ragas_status"] == "ok"
    assert set_data["metrics.ragas_executed"] is True
    assert set_data["metrics.ragas_error"] is None
    # Ensure ambiguous aliases are NOT in update
    assert "metrics.faithfulness" not in set_data
    assert "metrics.answer_relevance" not in set_data
