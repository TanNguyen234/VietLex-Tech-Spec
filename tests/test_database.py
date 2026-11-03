from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.database import log_interaction, update_evaluation, update_feedback


def test_get_db_uses_bounded_connection_timeouts(monkeypatch) -> None:
    import app.database as database

    fake_database = MagicMock()
    fake_client = MagicMock()
    fake_client.get_default_database.return_value = fake_database
    monkeypatch.setattr(database.settings, "APP_ENV", "production")
    monkeypatch.setattr(database.settings, "MONGO_URL", "mongodb://example.invalid/vietlex")
    monkeypatch.setattr(database, "client", None)
    monkeypatch.setattr(database, "db", None)

    with patch("app.database.AsyncIOMotorClient", return_value=fake_client) as create:
        assert database.get_db() is fake_database

    assert create.call_args.kwargs == {
        "serverSelectionTimeoutMS": database.settings.MONGO_TIMEOUT_MS,
        "connectTimeoutMS": database.settings.MONGO_TIMEOUT_MS,
        "socketTimeoutMS": database.settings.MONGO_TIMEOUT_MS,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("request_status,expected", [
    ("full_document_review_invalid_structured_response", {"stage":"full_document_review", "error_type":"invalid_structured_response"}),
    ("research_report_provider_error", {"stage":"research_report", "error_type":"provider_error"}),
    ("claim_verification_invalid_structured_response", {"stage":"claim_verification", "error_type":"invalid_structured_response"}),
    ("research_report_insufficient_evidence", None),
    ("blocked_input", None),
])
async def test_structured_failures_are_visible_in_admin_error_metrics(request_status, expected):
    database = MagicMock()
    database.evaluation_logs = AsyncMock()
    with patch("app.database.get_db", return_value=database):
        doc = await log_interaction("trace", "synthetic", "status", [], False,
                                    request_status=request_status)
    assert doc["metrics"]["technical_error"] == expected


@pytest.mark.asyncio
async def test_log_interaction_persists_all_operational_fields() -> None:
    import app.database as database

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
            request_metadata={"guardrail_engine": "direct_self_check"},
            retrieval_trace={"status": "available", "backend": "vertex-qdrant-v3"},
        )

    assert doc["_id"] == "trace-db-test-01"
    assert doc["timestamp"].utcoffset() == timedelta(0)
    assert doc["expires_at"] - doc["timestamp"] == timedelta(
        days=database.settings.DATA_RETENTION_DAYS
    )
    assert doc['request_metadata']['guardrail_engine'] == 'direct_self_check'
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
    assert doc["retrieval_trace"]["backend"] == "vertex-qdrant-v3"

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
    assert set_data["metrics.evaluated_at"].utcoffset() == timedelta(0)
    # Ensure ambiguous aliases are NOT in update
    assert "metrics.faithfulness" not in set_data
    assert "metrics.answer_relevance" not in set_data


@pytest.mark.asyncio
async def test_update_feedback_uses_utc_aware_timestamp() -> None:
    fake_collection = AsyncMock()
    fake_collection.update_one.return_value = MagicMock(modified_count=1)
    fake_db = MagicMock()
    fake_db.evaluation_logs = fake_collection

    with patch("app.database.get_db", return_value=fake_db):
        assert await update_feedback("trace-feedback-01", "up", client_id="client-1")

    query, update = fake_collection.update_one.call_args.args
    assert query == {"_id": "trace-feedback-01", "client_id": "client-1"}
    assert update["$set"]["feedback.updated_at"].utcoffset() == timedelta(0)


@pytest.mark.asyncio
async def test_admin_inventory_uses_utc_aware_session_cutoff() -> None:
    import app.database as database

    users = SimpleNamespace(count_documents=AsyncMock(return_value=0))
    auth_sessions = SimpleNamespace(count_documents=AsyncMock(return_value=0))
    chat_sessions = SimpleNamespace(count_documents=AsyncMock(return_value=0))
    workspaces = SimpleNamespace(count_documents=AsyncMock(return_value=0))
    fake_db = SimpleNamespace(
        users=users,
        auth_sessions=auth_sessions,
        chat_sessions=chat_sessions,
        research_workspaces=workspaces,
    )

    with patch("app.database.get_db", return_value=fake_db):
        result = await database.get_admin_inventory()

    cutoff = auth_sessions.count_documents.call_args.args[0]["expires_at"]["$gt"]
    assert result["status"] == "available"
    assert cutoff.utcoffset() == timedelta(0)


@pytest.mark.asyncio
async def test_session_history_roundtrip_keeps_official_provenance_sidecar(monkeypatch) -> None:
    import app.database as database
    from app.services.evidence_presenter import (
        TrustedOfficialEvidenceContext,
        present_context,
    )

    trusted = TrustedOfficialEvidenceContext(
        "[Nguồn chính thức ngoài VietLex · 45/2019/QH14]\n"
        "Nguồn: https://vanban.chinhphu.vn/default.aspx?docid=123\n"
        "Nguồn loại: official_external\n"
        "Hiệu lực pháp lý: unverified\n"
        f"SHA-256 nguồn: {'b' * 64}\n"
        "Thời điểm đọc: 2026-10-15T10:00:00+00:00\n"
        "Phương thức đọc: visible_html_text\n"
        "Tiêu đề: Bộ luật Lao động\n"
        "Mức lương thử việc ít nhất bằng 85%."
    )
    plain = str(trusted)
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.to_list = AsyncMock()
    collection = MagicMock()
    collection.replace_one = AsyncMock()
    collection.find.return_value = cursor
    fake_db = SimpleNamespace(evaluation_logs=collection)
    monkeypatch.setattr(database.settings, "APP_ENV", "production")

    with patch("app.database.get_db", return_value=fake_db):
        stored = await database.log_interaction(
            trace_id="trace-official-context",
            user_query="Câu hỏi",
            bot_response="Câu trả lời",
            contexts=[trusted, plain],
            cached=False,
            session_id="session-official-context",
        )
        cursor.to_list.return_value = [{
            **stored,
            "contexts": [str(value) for value in stored["contexts"]],
            "context_provenance": list(stored["context_provenance"]),
        }]
        messages = await database.get_session_messages(
            "session-official-context", "client-1"
        )

    assert stored["contexts"] == [str(trusted), plain]
    assert stored["context_provenance"][0] == {
        "kind": "trusted_official_evidence_v1",
        "source_type": "official_external",
        "legal_effect_status": "unverified",
        "source_url": "https://vanban.chinhphu.vn/default.aspx?docid=123",
        "source_sha256": "b" * 64,
        "retrieved_at": "2026-10-15T10:00:00+00:00",
        "read_method": "visible_html_text",
    }
    assert stored["context_provenance"][1] is None
    restored = messages[0]["contexts"]
    assert isinstance(restored[0], TrustedOfficialEvidenceContext)
    assert present_context(restored[0]).source_url == "https://vanban.chinhphu.vn/default.aspx?docid=123"
    assert present_context(restored[0]).source_sha256 == "b" * 64
    assert present_context(restored[1]).source_type is None
