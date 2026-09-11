from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import verify_csrf, verify_csrf_header
from app.api.routes import router
from app.rate_limit import limiter


@pytest.fixture
def client():
    limiter._storage.reset()
    app = FastAPI()

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.client_id = "owner-a"
        return await call_next(request)

    app.dependency_overrides[verify_csrf] = lambda: "valid"
    app.dependency_overrides[verify_csrf_header] = lambda: "valid"
    app.include_router(router)
    return TestClient(app)


def test_health_is_provider_free(client) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "vietlex"}


def test_document_chat_bypasses_global_cache(client, monkeypatch):
    from app.api import legal_routes
    from app.services import rag_pipeline
    from app.ingestion.legal_text import DocumentMetadata

    document = SimpleNamespace(metadata=DocumentMetadata(7, "45/2019/QH14", "Luật", "https://vbpl.vn/7", "Luật", "", "", None), content="Điều 25. Thử việc")
    monkeypatch.setattr(legal_routes, "browser", SimpleNamespace(get_document=lambda value: document if value == 7 else None))
    cache = AsyncMock(side_effect=AssertionError("global cache forbidden"))
    monkeypatch.setattr("app.api.routes.check_semantic_cache", cache)
    monkeypatch.setattr("app.api.routes.save_to_semantic_cache", cache)
    monkeypatch.setattr("app.api.routes.log_interaction", AsyncMock())
    pipeline = AsyncMock(return_value=("Trong văn bản này", ["Điều 25"], {"t_total": 0.1}))
    monkeypatch.setattr(rag_pipeline, "run_advanced_rag", pipeline)
    response = client.post("/chat", data={"message": "Điều 25", "csrf_token": "valid", "session_id": "s-1", "document_id": "7"})
    assert response.status_code == 200
    assert pipeline.await_args.kwargs["scoped_outcome"].evidence[0].document_id == 7
    cache.assert_not_awaited()
    assert client.post("/chat", data={"message": "Test", "csrf_token": "valid", "session_id": "s-1", "document_id": "999"}).status_code == 404


def test_progress_endpoint_is_owner_scoped(client, monkeypatch) -> None:
    registry = SimpleNamespace(
        get=lambda request_id, client_id: (
            {
                "stage": "retrieval",
                "label": "Đang truy xuất bằng chứng",
                "elapsed_seconds": 2.4,
                "complete": False,
                "status": "running",
            }
            if request_id == "request-1" and client_id == "owner-a"
            else None
        )
    )
    monkeypatch.setattr("app.api.routes.chat_progress", registry)

    response = client.get("/api/progress/request-1")

    assert response.status_code == 200
    assert response.json()["stage"] == "retrieval"
    assert client.get("/api/progress/missing").status_code == 404


def test_admin_requires_account_auth_when_legacy_basic_is_disabled(client) -> None:
    response = client.get("/admin")

    assert response.status_code == 401


def test_chat_defaults_to_nemo_off(client, monkeypatch) -> None:
    input_guardrail = AsyncMock(return_value=(True, ""))
    output_guardrail = AsyncMock(return_value=(True, ""))
    monkeypatch.setattr("app.api.routes.check_input_guardrails", input_guardrail)
    monkeypatch.setattr("app.api.routes.check_output_guardrails", output_guardrail)
    monkeypatch.setattr("app.api.routes.check_semantic_cache", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "app.api.routes.run_advanced_rag",
        AsyncMock(return_value=("Câu trả lời", ["Context"], {"t_total": 0.1})),
    )
    monkeypatch.setattr("app.api.routes.log_interaction", AsyncMock())
    monkeypatch.setattr("app.api.routes.save_to_semantic_cache", AsyncMock())

    response = client.post(
        "/chat",
        data={"message": "Thử việc?", "csrf_token": "valid", "session_id": "s-1"},
    )

    assert response.status_code == 200
    input_guardrail.assert_not_awaited()
    output_guardrail.assert_not_awaited()


def test_client_cannot_disable_server_guardrail_policy(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.settings.PUBLIC_NEMO_DEFAULT_ENABLED", True)
    guard = AsyncMock(return_value=(True, ""))
    monkeypatch.setattr("app.api.routes.check_input_guardrails", guard)
    monkeypatch.setattr("app.api.routes.check_output_guardrails", guard)
    monkeypatch.setattr("app.api.routes.check_semantic_cache", AsyncMock(return_value=None))
    monkeypatch.setattr("app.api.routes.run_advanced_rag", AsyncMock(return_value=("Answer", ["Context"], {})))
    monkeypatch.setattr("app.api.routes.log_interaction", AsyncMock())
    monkeypatch.setattr("app.api.routes.save_to_semantic_cache", AsyncMock())
    response = client.post("/chat", data={"message": "Test", "csrf_token": "valid", "session_id": "s-1", "nemo_enabled": "false"})
    assert response.status_code == 200
    assert guard.await_count == 2


def test_chat_runs_nemo_only_when_explicitly_enabled(client, monkeypatch) -> None:
    input_guardrail = AsyncMock(return_value=(True, ""))
    output_guardrail = AsyncMock(return_value=(True, ""))
    monkeypatch.setattr("app.api.routes.check_input_guardrails", input_guardrail)
    monkeypatch.setattr("app.api.routes.check_output_guardrails", output_guardrail)
    monkeypatch.setattr("app.api.routes.check_semantic_cache", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "app.api.routes.run_advanced_rag",
        AsyncMock(return_value=("Câu trả lời", ["Context"], {"t_total": 0.1})),
    )
    monkeypatch.setattr("app.api.routes.log_interaction", AsyncMock())
    monkeypatch.setattr("app.api.routes.save_to_semantic_cache", AsyncMock())

    response = client.post(
        "/chat",
        data={
            "message": "Thử việc?",
            "csrf_token": "valid",
            "session_id": "s-1",
            "nemo_enabled": "true",
        },
    )

    assert response.status_code == 200
    input_guardrail.assert_awaited_once()
    output_guardrail.assert_awaited_once()


def test_code_evaluation_is_owned_and_does_not_call_ragas(client, monkeypatch) -> None:
    interaction = {
        "trace_id": "trace-1",
        "client_id": "owner-a",
        "bot_response": "Điều 25 quy định...",
        "contexts": ["Điều 25"],
        "metrics": {"request_status": "ok", "latency": {"t_total": 0.2}},
    }
    owned = AsyncMock(return_value=interaction)
    judge = AsyncMock()
    monkeypatch.setattr("app.api.routes.get_owned_interaction", owned)
    monkeypatch.setattr("app.api.routes.run_llm_as_judge", judge)

    response = client.post(
        "/api/evaluation/trace-1",
        data={"csrf_token": "valid", "run_ragas": "false"},
    )

    assert response.status_code == 200
    assert response.json()["code_evaluation"]["status"] == "available"
    owned.assert_awaited_once_with("trace-1", "owner-a")
    judge.assert_not_awaited()


def test_public_ragas_fails_closed_when_deployment_disabled(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.get_owned_interaction",
        AsyncMock(
            return_value={
                "trace_id": "trace-1",
                "client_id": "owner-a",
                "user_query": "Câu hỏi",
                "bot_response": "Câu trả lời",
                "contexts": ["Context"],
                "metrics": {},
            }
        ),
    )
    monkeypatch.setattr(
        "app.api.routes.settings",
        SimpleNamespace(PUBLIC_RAGAS_ENABLED=False),
    )

    response = client.post(
        "/api/evaluation/trace-1",
        data={"csrf_token": "valid", "run_ragas": "true"},
    )

    assert response.status_code == 503
    assert response.json()["ragas"]["status"] == "disabled"


def test_public_ragas_runs_only_after_explicit_opt_in(client, monkeypatch) -> None:
    initial = {
        "trace_id": "trace-1",
        "client_id": "owner-a",
        "user_query": "Câu hỏi",
        "bot_response": "Câu trả lời",
        "contexts": ["Context"],
        "metrics": {},
    }
    refreshed = {
        **initial,
        "metrics": {
            "ragas_executed": True,
            "ragas_status": "ok",
            "ragas_proxy_faithfulness": 0.91,
            "ragas_proxy_answer_relevance": 0.87,
        },
    }
    judge = AsyncMock()
    monkeypatch.setattr(
        "app.api.routes.get_owned_interaction",
        AsyncMock(side_effect=[initial, refreshed]),
    )
    monkeypatch.setattr("app.api.routes.run_llm_as_judge", judge)
    monkeypatch.setattr(
        "app.api.routes.settings",
        SimpleNamespace(PUBLIC_RAGAS_ENABLED=True),
    )
    monkeypatch.setattr(
        "app.api.routes._public_ragas_quota",
        SimpleNamespace(reserve=lambda _client_id: True),
    )

    response = client.post(
        "/api/evaluation/trace-1",
        data={"csrf_token": "valid", "run_ragas": "true"},
    )

    assert response.status_code == 200
    assert response.json()["ragas"] == {
        "status": "ok",
        "cached": False,
        "faithfulness": 0.91,
        "answer_relevance": 0.87,
    }
    judge.assert_awaited_once_with(
        "Câu hỏi", ["Context"], "Câu trả lời", "trace-1", force=True
    )


def test_public_ragas_skips_trace_without_context(client, monkeypatch) -> None:
    judge = AsyncMock()
    monkeypatch.setattr(
        "app.api.routes.get_owned_interaction",
        AsyncMock(
            return_value={
                "trace_id": "trace-empty",
                "client_id": "owner-a",
                "user_query": "Câu hỏi",
                "bot_response": "Không có bằng chứng.",
                "contexts": [],
                "metrics": {},
            }
        ),
    )
    monkeypatch.setattr("app.api.routes.run_llm_as_judge", judge)
    monkeypatch.setattr(
        "app.api.routes.settings",
        SimpleNamespace(PUBLIC_RAGAS_ENABLED=True),
    )

    response = client.post(
        "/api/evaluation/trace-empty",
        data={"csrf_token": "valid", "run_ragas": "true"},
    )

    assert response.status_code == 422
    assert response.json()["ragas"]["status"] == "skipped_no_context"
    judge.assert_not_awaited()
