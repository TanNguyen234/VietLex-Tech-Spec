from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import require_user, verify_csrf


def _workspace() -> dict:
    return {
        "workspace_id": "w-1",
        "evidence": [
            {
                "evidence_id": "ev-1",
                "original": "Nội dung riêng tư",
                "workspace_document_id": "doc-a",
            },
            {
                "evidence_id": "ev-2",
                "original": "Nội dung riêng tư B",
                "workspace_document_id": "doc-b",
            },
        ],
    }


def _result() -> dict:
    return {
        "generation_call_budget": {"analysis_attempts": 1, "generation_calls": 2},
        "same_input_proof": {
            "input_sha256": "a" * 64,
            "all_models_received_same_input": True,
        },
        "responses": [],
        "textual_comparison": {
            "status": "not_available",
            "legal_correctness": "not_evaluated",
        },
    }


def _client(user: dict | None) -> TestClient:
    from app.api.model_comparison_routes import router

    app = FastAPI()
    app.dependency_overrides[verify_csrf] = lambda: "valid"
    app.dependency_overrides[require_user] = lambda: user
    app.include_router(router)
    return TestClient(app)


def test_model_comparison_requires_verified_active_user() -> None:
    client = _client({"_id": "user-1", "status": "active", "email_verified": False})

    response = client.post(
        "/workspaces/w-1/analyses/models",
        data={"question": "Q", "evidence_ids": "ev-1", "model_a": "a", "model_b": "b"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "verified_account_required"


def test_model_experiments_reject_regular_users_before_provider_calls(monkeypatch):
    client = _client({"_id": "user-1", "status": "active", "email_verified": True})
    compare = AsyncMock()
    monkeypatch.setattr("app.api.model_comparison_routes.compare_models", compare)
    monkeypatch.setattr("app.api.workspace_routes.get_workspace", AsyncMock(return_value=_workspace()))
    response = client.post("/workspaces/w-1/analyses/models", data={
        "question": "Q", "evidence_ids": "ev-1", "model_a": "a", "model_b": "b"})
    assert response.status_code == 403
    compare.assert_not_awaited()


def test_model_comparison_persists_server_selected_evidence_and_document_requirements(
    monkeypatch,
) -> None:
    client = _client({"_id": "user-1", "status": "active", "email_verified": True, "role": "admin"})
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace", AsyncMock(return_value=_workspace())
    )
    compare = AsyncMock(return_value=_result())
    save = AsyncMock(return_value=True)
    log = AsyncMock(return_value={"trace_id": "trace"})
    monkeypatch.setattr("app.api.model_comparison_routes.compare_models", compare)
    monkeypatch.setattr("app.api.model_comparison_routes.save_workspace_analysis", save)
    monkeypatch.setattr("app.api.model_comparison_routes.log_interaction", log)

    response = client.post(
        "/workspaces/w-1/analyses/models",
        data={
            "question": "Câu hỏi riêng tư",
            "evidence_ids": "ev-1,ev-2",
            "model_a": "openrouter_llama",
            "model_b": "groq_llama",
        },
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert compare.await_args.args == (
        "Câu hỏi riêng tư",
        _workspace()["evidence"],
        "openrouter_llama",
        "groq_llama",
    )
    analysis = save.await_args.args[1]
    assert analysis["kind"] == "model_comparison"
    assert analysis["workspace_document_ids"] == ["doc-a", "doc-b"]
    assert analysis["evidence_snapshot"][0]["original"] == "Nội dung riêng tư"
    assert save.await_args.kwargs["required_document_ids"] == ["doc-a", "doc-b"]
    assert log.await_args.kwargs["contexts"] == []
    assert "Nội dung riêng tư" not in log.await_args.kwargs["user_query"]


def test_model_comparison_fails_before_saving_when_model_is_unavailable(
    monkeypatch,
) -> None:
    client = _client({"_id": "user-1", "status": "active", "email_verified": True, "role": "admin"})
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace", AsyncMock(return_value=_workspace())
    )
    compare = AsyncMock(side_effect=ValueError("model_unavailable"))
    save = AsyncMock()
    monkeypatch.setattr("app.api.model_comparison_routes.compare_models", compare)
    monkeypatch.setattr("app.api.model_comparison_routes.save_workspace_analysis", save)

    response = client.post(
        "/workspaces/w-1/analyses/models",
        data={"question": "Q", "evidence_ids": "ev-1", "model_a": "a", "model_b": "b"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "model_unavailable"
    save.assert_not_awaited()


def test_unreported_model_identity_is_partial(monkeypatch):
    client = _client({"_id": "user-1", "status": "active", "email_verified": True, "role": "admin"})
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace", AsyncMock(return_value=_workspace())
    )
    outcome = _result()
    outcome["responses"] = [
        {"status": "success", "identity_status": "not_reported"},
        {"status": "success", "identity_status": "matched"},
    ]
    monkeypatch.setattr(
        "app.api.model_comparison_routes.compare_models",
        AsyncMock(return_value=outcome),
    )
    monkeypatch.setattr(
        "app.api.model_comparison_routes.save_workspace_analysis",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.api.model_comparison_routes.log_interaction", AsyncMock(return_value=True)
    )
    response = client.post(
        "/workspaces/w-1/analyses/models",
        data={"question": "Q", "evidence_ids": "ev-1", "model_a": "a", "model_b": "b"},
    )
    assert response.json()["status"] == "partial"
