from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import verify_csrf
from app.api.routes import router as api_router
from app.config import get_settings


@pytest.fixture
def client():
    test_app = FastAPI()
    test_app.dependency_overrides[verify_csrf] = lambda: "valid_token"
    test_app.include_router(api_router)
    return TestClient(test_app)


def test_chat_route_off_mode_does_not_enqueue_ragas(client, monkeypatch) -> None:

    monkeypatch.setattr(
        "app.api.routes.check_semantic_cache",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.api.routes.save_to_semantic_cache",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.api.routes.check_input_guardrails",
        AsyncMock(return_value=(True, "")),
    )

    monkeypatch.setattr(
        "app.api.routes.run_advanced_rag",
        AsyncMock(
            return_value=(
                "Theo Luật 12/2026/NĐ-CP Điều 1...",
                ["Ngữ cảnh trích xuất"],
                {"t_total": 0.5, "t_retrieval": 0.2, "t_llm": 0.3},
            )
        ),
    )
    monkeypatch.setattr(
        "app.api.routes.check_output_guardrails",
        AsyncMock(return_value=(True, "")),
    )
    monkeypatch.setattr(
        "app.api.routes.create_session",
        AsyncMock(),
    )

    logged_interaction = {}

    async def fake_log_interaction(**kwargs):
        nonlocal logged_interaction
        logged_interaction = kwargs
        return kwargs

    monkeypatch.setattr(
        "app.api.routes.log_interaction",
        fake_log_interaction,
    )

    ragas_mock = MagicMock()
    monkeypatch.setattr("app.api.routes.run_llm_as_judge", ragas_mock)

    # settings RAGAS_EVALUATION_MODE is default 'off'
    response = client.post(
        "/chat",
        data={
            "message": "Quy định thuế như thế nào?",
            "csrf_token": "valid_token",
            "session_id": "test-session",
        },
    )

    assert response.status_code == 200
    assert "Theo Luật 12/2026/NĐ-CP" in response.text
    # When off, ragas_mock should not be enqueued/called
    ragas_mock.assert_not_called()
    assert logged_interaction.get("trace_id") is not None


def test_chat_route_all_mode_enqueues_ragas_for_valid_rag(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.check_semantic_cache",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.api.routes.save_to_semantic_cache",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.api.routes.check_input_guardrails",
        AsyncMock(return_value=(True, "")),
    )
    monkeypatch.setattr(
        "app.api.routes.run_advanced_rag",
        AsyncMock(
            return_value=(
                "Theo Luật 12/2026/NĐ-CP Điều 1...",
                ["Ngữ cảnh trích xuất"],
                {"t_total": 0.5},
            )
        ),
    )
    monkeypatch.setattr(
        "app.api.routes.check_output_guardrails",
        AsyncMock(return_value=(True, "")),
    )
    monkeypatch.setattr(
        "app.api.routes.create_session",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.api.routes.log_interaction",
        AsyncMock(),
    )

    settings = get_settings()
    monkeypatch.setattr(settings, "RAGAS_EVALUATION_MODE", "all")

    ragas_enqueued = False

    def fake_run_llm_as_judge(*args, **kwargs):
        nonlocal ragas_enqueued
        ragas_enqueued = True

    monkeypatch.setattr("app.api.routes.run_llm_as_judge", fake_run_llm_as_judge)

    response = client.post(
        "/chat",
        data={
            "message": "Quy định thuế như thế nào?",
            "csrf_token": "valid_token",
            "session_id": "test-session",
        },
    )

    assert response.status_code == 200
    assert ragas_enqueued is True


def test_admin_stats_and_details_display_proxy_labels(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.get_admin_stats",
        AsyncMock(
            return_value={
                "total_queries": 10,
                "cache_hit_rate": 20.0,
                "avg_faithfulness": 0.85,
                "avg_relevance": 0.90,
                "positive_feedback_rate": 80.0,
            }
        ),
    )
    monkeypatch.setattr(
        "app.api.routes.get_interaction",
        AsyncMock(
            return_value={
                "trace_id": "trace-test-admin",
                "timestamp": None,
                "cached": False,
                "user_query": "Câu hỏi",
                "bot_response": "Câu trả lời",
                "safety_status": {"input_safe": True, "output_safe": True, "rejection_reason": None},
                "metrics": {"faithfulness": 0.85, "answer_relevance": 0.90, "evaluated_at": None},
                "feedback": {"rating": "up"},
                "contexts": ["Context 1"],
            }
        ),
    )

    stats_resp = client.get("/admin/stats")
    assert stats_resp.status_code == 200
    # Must contain explicit Proxy indication
    assert "proxy" in stats_resp.text.lower() or "đánh giá ragas" in stats_resp.text.lower()

    details_resp = client.get("/admin/details/trace-test-admin")
    assert details_resp.status_code == 200
    assert "proxy" in details_resp.text.lower() or "đánh giá ragas" in details_resp.text.lower()
