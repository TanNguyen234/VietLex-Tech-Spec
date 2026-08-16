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


def test_chat_route_cache_hit_measures_real_latency_and_persists_status(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.check_semantic_cache",
        AsyncMock(return_value="Câu trả lời từ cache."),
    )
    monkeypatch.setattr("app.api.routes.create_session", AsyncMock())

    logged = {}

    async def fake_log(**kwargs):
        nonlocal logged
        logged = kwargs
        return kwargs

    monkeypatch.setattr("app.api.routes.log_interaction", fake_log)

    resp = client.post(
        "/chat",
        data={"message": "Câu hỏi cache", "csrf_token": "valid_token", "session_id": "test-session"},
    )
    assert resp.status_code == 200
    assert "Câu trả lời từ cache." in resp.text
    assert logged.get("request_status") == "cache_hit"
    assert logged.get("cached") is True
    assert "t_total" in logged.get("latency", {})
    assert logged["latency"]["t_total"] > 0.0


def test_chat_route_input_guardrail_unavailable_persists_technical_error(client, monkeypatch) -> None:
    from app.services.guardrails import GuardrailUnavailableError

    monkeypatch.setattr("app.api.routes.check_semantic_cache", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "app.api.routes.check_input_guardrails",
        AsyncMock(side_effect=GuardrailUnavailableError("input", "Input guardrail service unreachable")),
    )
    monkeypatch.setattr("app.api.routes.create_session", AsyncMock())

    logged = {}

    async def fake_log(**kwargs):
        nonlocal logged
        logged = kwargs
        return kwargs

    monkeypatch.setattr("app.api.routes.log_interaction", fake_log)

    resp = client.post(
        "/chat",
        data={"message": "Câu hỏi kiểm tra", "csrf_token": "valid_token", "session_id": "test-session"},
    )
    assert resp.status_code == 503
    assert logged.get("request_status") == "technical_error"
    assert logged.get("technical_error") is not None
    assert logged["technical_error"]["stage"] == "guardrails_input"
    assert "t_total" in logged.get("latency", {})


def test_chat_route_output_guardrail_unavailable_persists_technical_error(client, monkeypatch) -> None:
    from app.services.guardrails import GuardrailUnavailableError

    monkeypatch.setattr("app.api.routes.check_semantic_cache", AsyncMock(return_value=None))
    monkeypatch.setattr("app.api.routes.check_input_guardrails", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr(
        "app.api.routes.run_advanced_rag",
        AsyncMock(return_value=("Câu trả lời thô", ["Context"], {"t_total": 0.3})),
    )
    monkeypatch.setattr(
        "app.api.routes.check_output_guardrails",
        AsyncMock(side_effect=GuardrailUnavailableError("output", "Output guardrail service unreachable")),
    )
    monkeypatch.setattr("app.api.routes.create_session", AsyncMock())


    logged = {}

    async def fake_log(**kwargs):
        nonlocal logged
        logged = kwargs
        return kwargs

    monkeypatch.setattr("app.api.routes.log_interaction", fake_log)

    resp = client.post(
        "/chat",
        data={"message": "Câu hỏi", "csrf_token": "valid_token", "session_id": "test-session"},
    )
    assert resp.status_code == 503
    assert logged.get("request_status") == "technical_error"
    assert logged.get("technical_error") is not None
    assert logged["technical_error"]["stage"] == "guardrails_output"


def test_chat_route_retrieval_pipeline_error_persists_technical_error(client, monkeypatch) -> None:
    from app.services.rag_pipeline import RetrievalPipelineError

    monkeypatch.setattr("app.api.routes.check_semantic_cache", AsyncMock(return_value=None))
    monkeypatch.setattr("app.api.routes.check_input_guardrails", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr(
        "app.api.routes.run_advanced_rag",
        AsyncMock(
            side_effect=RetrievalPipelineError(
                "retrieval_error",
                "Qdrant staging connection failure",
                {"error_code": "QDRANT_CONN_ERR"},
                {"t_total": 0.25},
            )
        ),
    )
    monkeypatch.setattr("app.api.routes.create_session", AsyncMock())

    logged = {}

    async def fake_log(**kwargs):
        nonlocal logged
        logged = kwargs
        return kwargs

    monkeypatch.setattr("app.api.routes.log_interaction", fake_log)

    resp = client.post(
        "/chat",
        data={"message": "Câu hỏi", "csrf_token": "valid_token", "session_id": "test-session"},
    )
    assert resp.status_code in (500, 503)
    assert logged.get("request_status") == "technical_error"
    assert logged.get("technical_error") is not None
    assert logged["technical_error"]["stage"] == "retrieval_error"


def test_chat_route_no_evidence_persists_no_evidence_status(client, monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.check_semantic_cache", AsyncMock(return_value=None))
    monkeypatch.setattr("app.api.routes.save_to_semantic_cache", AsyncMock())
    monkeypatch.setattr("app.api.routes.check_input_guardrails", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr(
        "app.api.routes.run_advanced_rag",
        AsyncMock(return_value=("Xin lỗi, tôi không tìm thấy...", [], {"t_total": 0.2, "observed_provider": "none"})),
    )
    monkeypatch.setattr("app.api.routes.check_output_guardrails", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr("app.api.routes.create_session", AsyncMock())

    logged = {}

    async def fake_log(**kwargs):
        nonlocal logged
        logged = kwargs
        return kwargs

    monkeypatch.setattr("app.api.routes.log_interaction", fake_log)

    resp = client.post(
        "/chat",
        data={"message": "Câu hỏi không có luật", "csrf_token": "valid_token", "session_id": "test-session"},
    )
    assert resp.status_code == 200
    assert logged.get("request_status") == "no_evidence"
    assert logged.get("no_evidence") is True
    assert logged.get("context_count") == 0


def test_chat_route_retrieval_error_preserves_query_rewrite_provider_usage(client, monkeypatch) -> None:
    from app.services.rag_pipeline import RetrievalPipelineError

    monkeypatch.setattr("app.api.routes.check_semantic_cache", AsyncMock(return_value=None))
    monkeypatch.setattr("app.api.routes.check_input_guardrails", AsyncMock(return_value=(True, "")))

    latency_with_provider = {
        "t_total": 0.25,
        "t_rewrite": 0.15,
        "observed_provider": "gemini",
        "observed_model": "gemini-2.5-flash",
        "provider_usage": {
            "query_rewrite": {"provider": "gemini", "model": "gemini-2.5-flash", "observed": True},
            "answer_generation": {"provider": "unobserved", "model": "unobserved", "observed": False},
            "guardrails": {"provider": "unobserved", "model": "unobserved", "observed": False},
        },
    }

    monkeypatch.setattr(
        "app.api.routes.run_advanced_rag",
        AsyncMock(
            side_effect=RetrievalPipelineError(
                "retrieval_error",
                "Qdrant connection timeout",
                {"error_code": "QDRANT_CONN_ERR"},
                latency_with_provider,
            )
        ),
    )
    monkeypatch.setattr("app.api.routes.create_session", AsyncMock())

    logged = {}

    async def fake_log(**kwargs):
        nonlocal logged
        logged = kwargs
        return kwargs

    monkeypatch.setattr("app.api.routes.log_interaction", fake_log)

    resp = client.post(
        "/chat",
        data={"message": "Câu hỏi dài cần viết lại", "csrf_token": "valid_token", "session_id": "test-session"},
    )
    assert resp.status_code == 500
    assert logged.get("request_status") == "technical_error"
    assert logged.get("observed_provider") == "gemini"
    assert logged.get("observed_model") == "gemini-2.5-flash"
    assert logged.get("provider_usage", {}).get("query_rewrite", {}).get("provider") == "gemini"


def test_chat_route_output_guardrail_unavailable_preserves_answer_provider_usage(client, monkeypatch) -> None:
    from app.services.guardrails import GuardrailUnavailableError

    monkeypatch.setattr("app.api.routes.check_semantic_cache", AsyncMock(return_value=None))
    monkeypatch.setattr("app.api.routes.check_input_guardrails", AsyncMock(return_value=(True, "")))

    rag_latency = {
        "t_total": 0.45,
        "t_llm": 0.35,
        "observed_provider": "openrouter",
        "observed_model": "google/gemini-2.5-flash",
        "provider_usage": {
            "query_rewrite": {"provider": "none", "model": "none", "observed": False},
            "answer_generation": {"provider": "openrouter", "model": "google/gemini-2.5-flash", "observed": True},
            "guardrails": {"provider": "unobserved", "model": "unobserved", "observed": False},
        },
    }

    monkeypatch.setattr(
        "app.api.routes.run_advanced_rag",
        AsyncMock(return_value=("Câu trả lời thô", ["Context 1"], rag_latency)),
    )
    monkeypatch.setattr(
        "app.api.routes.check_output_guardrails",
        AsyncMock(side_effect=GuardrailUnavailableError("output", "Output guardrail service unreachable")),
    )
    monkeypatch.setattr("app.api.routes.create_session", AsyncMock())

    logged = {}

    async def fake_log(**kwargs):
        nonlocal logged
        logged = kwargs
        return kwargs

    monkeypatch.setattr("app.api.routes.log_interaction", fake_log)

    resp = client.post(
        "/chat",
        data={"message": "Câu hỏi", "csrf_token": "valid_token", "session_id": "test-session"},
    )
    assert resp.status_code == 503
    assert logged.get("request_status") == "technical_error"
    assert logged.get("observed_provider") == "openrouter"
    assert logged.get("observed_model") == "google/gemini-2.5-flash"
    assert logged.get("provider_usage", {}).get("answer_generation", {}).get("provider") == "openrouter"


def test_chat_route_technical_error_sanitizes_secrets(client, monkeypatch) -> None:
    from app.services.guardrails import GuardrailUnavailableError

    secret_in_error = "https://api.openai.com/v1/chat?api_key=sk-secret_test_12345 Bearer super-secret-token"
    monkeypatch.setattr("app.api.routes.check_semantic_cache", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "app.api.routes.check_input_guardrails",
        AsyncMock(side_effect=GuardrailUnavailableError("input", secret_in_error)),
    )
    monkeypatch.setattr("app.api.routes.create_session", AsyncMock())

    logged = {}

    async def fake_log(**kwargs):
        nonlocal logged
        logged = kwargs
        return kwargs

    monkeypatch.setattr("app.api.routes.log_interaction", fake_log)

    resp = client.post(
        "/chat",
        data={"message": "Câu hỏi kiểm tra", "csrf_token": "valid_token", "session_id": "test-session"},
    )
    assert resp.status_code == 503
    tech_err = logged.get("technical_error", {})
    msg = tech_err.get("message", "")
    assert "sk-secret_test_12345" not in msg
    assert "super-secret-token" not in msg
    assert "[REDACTED]" in msg


def test_chat_route_answer_generation_no_provider_available_persists_technical_error(client, monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.check_semantic_cache", AsyncMock(return_value=None))
    monkeypatch.setattr("app.api.routes.check_input_guardrails", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr("app.api.routes.check_output_guardrails", AsyncMock(return_value=(True, "")))

    mock_save_cache = AsyncMock()
    mock_evaluator = AsyncMock()
    monkeypatch.setattr("app.api.routes.save_to_semantic_cache", mock_save_cache)
    monkeypatch.setattr("app.api.routes.run_llm_as_judge", mock_evaluator)

    rag_latency = {
        "t_total": 0.30,
        "t_llm": 0.20,
        "generation_status": "no_provider_available",
        "observed_provider": "unobserved",
        "observed_model": "unobserved",
        "provider_usage": {
            "query_rewrite": {"provider": "none", "model": "none", "observed": False},
            "answer_generation": {"provider": "unobserved", "model": "unobserved", "observed": False},
            "guardrails": {"provider": "unobserved", "model": "unobserved", "observed": False},
        },
    }
    monkeypatch.setattr(
        "app.api.routes.run_advanced_rag",
        AsyncMock(return_value=("Hệ thống chưa được cấu hình API Keys.", ["Context 1"], rag_latency)),
    )
    monkeypatch.setattr("app.api.routes.create_session", AsyncMock())

    logged = {}

    async def fake_log(**kwargs):
        nonlocal logged
        logged = kwargs
        return kwargs

    monkeypatch.setattr("app.api.routes.log_interaction", fake_log)

    resp = client.post(
        "/chat",
        data={"message": "Câu hỏi", "csrf_token": "valid_token", "session_id": "test-session"},
    )
    assert resp.status_code == 200
    assert logged.get("request_status") == "technical_error"
    assert logged.get("technical_error") is not None
    assert logged["technical_error"]["stage"] == "answer_generation"
    assert logged["technical_error"]["error_type"] == "no_provider_available"
    assert logged.get("observed_provider") in ("unobserved", "none")
    assert mock_save_cache.called is False
    assert mock_evaluator.called is False


def test_chat_route_answer_generation_providers_exhausted_persists_technical_error(client, monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.check_semantic_cache", AsyncMock(return_value=None))
    monkeypatch.setattr("app.api.routes.check_input_guardrails", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr("app.api.routes.check_output_guardrails", AsyncMock(return_value=(True, "")))

    mock_save_cache = AsyncMock()
    mock_evaluator = AsyncMock()
    monkeypatch.setattr("app.api.routes.save_to_semantic_cache", mock_save_cache)
    monkeypatch.setattr("app.api.routes.run_llm_as_judge", mock_evaluator)

    rag_latency = {
        "t_total": 0.40,
        "t_llm": 0.30,
        "generation_status": "providers_exhausted",
        "observed_provider": "unobserved",
        "observed_model": "unobserved",
        "provider_usage": {
            "query_rewrite": {"provider": "none", "model": "none", "observed": False},
            "answer_generation": {"provider": "unobserved", "model": "unobserved", "observed": False},
            "guardrails": {"provider": "unobserved", "model": "unobserved", "observed": False},
        },
    }
    monkeypatch.setattr(
        "app.api.routes.run_advanced_rag",
        AsyncMock(return_value=("Hệ thống bị giới hạn tốc độ...", ["Context 1"], rag_latency)),
    )
    monkeypatch.setattr("app.api.routes.create_session", AsyncMock())

    logged = {}

    async def fake_log(**kwargs):
        nonlocal logged
        logged = kwargs
        return kwargs

    monkeypatch.setattr("app.api.routes.log_interaction", fake_log)

    resp = client.post(
        "/chat",
        data={"message": "Câu hỏi", "csrf_token": "valid_token", "session_id": "test-session"},
    )
    assert resp.status_code == 200
    assert logged.get("request_status") == "technical_error"
    assert logged.get("technical_error") is not None
    assert logged["technical_error"]["stage"] == "answer_generation"
    assert logged["technical_error"]["error_type"] == "providers_exhausted"
    assert logged.get("observed_provider") in ("unobserved", "none")
    assert mock_save_cache.called is False
    assert mock_evaluator.called is False
