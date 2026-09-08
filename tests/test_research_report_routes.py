from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import optional_user, verify_csrf


@pytest.fixture
def client():
    from app.api.research_report_routes import router

    app = FastAPI()

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.client_id = "owner-a"
        return await call_next(request)

    app.dependency_overrides[verify_csrf] = lambda: "valid"
    app.dependency_overrides[optional_user] = lambda: None
    app.include_router(router)
    return TestClient(app)


def _workspace() -> dict:
    return {
        "workspace_id": "w-1",
        "evidence": [
            {
                "evidence_id": "ev-1",
                "citation": "Điều 1",
                "excerpt": "Người sử dụng lao động phải thông báo.",
                "original": "private source context",
                "workspace_document_id": "document-1",
            }
        ],
    }


def _result(status: str = "ok") -> dict:
    return {
        "status": status,
        "report": {
            "status": "ok",
            "issue": "Nghĩa vụ thông báo",
            "analysis": [{"text": "Phải thông báo.", "evidence_ids": ["ev-1"]}],
            "exceptions": [],
            "checklist": [],
            "sources": ["ev-1"],
            "unknown": [],
        },
        "coverage": {"report_claims": 1, "verified_claims": 1},
        "unknown": [],
        "model_assessment": {"status": "ok", "result": {"coverage": {}}},
        "provider": "test-provider",
        "model": "test-model",
        "provider_status": "success",
        "legal_certification": False,
    }


def test_research_report_uses_owned_evidence_and_persists_private_snapshot(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace", AsyncMock(return_value=_workspace())
    )
    generate = AsyncMock(return_value=_result())
    save = AsyncMock(return_value=True)
    log = AsyncMock(return_value={"trace_id": "trace"})
    monkeypatch.setattr(
        "app.api.research_report_routes.generate_research_report", generate
    )
    monkeypatch.setattr("app.api.research_report_routes.save_workspace_analysis", save)
    monkeypatch.setattr("app.api.research_report_routes.log_interaction", log)

    response = client.post(
        "/workspaces/w-1/analyses/report",
        data={"question": "Cần làm gì?", "evidence_ids": "ev-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "research_report"
    assert body["legal_certification"] is False
    assert body["evidence_scope"] == 1
    generate.assert_awaited_once_with("Cần làm gì?", _workspace()["evidence"])
    saved = save.await_args.args[1]
    assert saved["evidence_snapshot"][0]["original"] == "private source context"
    assert saved["workspace_document_ids"] == ["document-1"]
    assert saved["result"]["report"]["issue"] == "Nghĩa vụ thông báo"
    assert saved["result"]["coverage"] == {"report_claims": 1, "verified_claims": 1}
    assert saved["admin_trace_status"] == "persisted"
    assert log.await_args.kwargs["contexts"] == []
    assert "Cần làm gì" not in log.await_args.kwargs["user_query"]
    assert log.await_args.kwargs["retrieval_trace"]["context_sha256"]


def test_research_report_rejects_unselected_evidence_before_generation(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace", AsyncMock(return_value=_workspace())
    )
    generate = AsyncMock()
    monkeypatch.setattr(
        "app.api.research_report_routes.generate_research_report", generate
    )

    response = client.post(
        "/workspaces/w-1/analyses/report",
        data={"question": "Q", "evidence_ids": "forged"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "insufficient_evidence"
    generate.assert_not_awaited()


def test_research_report_persists_typed_failure_and_marks_workspace_change(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace", AsyncMock(return_value=_workspace())
    )
    monkeypatch.setattr(
        "app.api.research_report_routes.generate_research_report",
        AsyncMock(return_value=_result("provider_error")),
    )
    save = AsyncMock(return_value=False)
    update = AsyncMock(return_value=True)
    monkeypatch.setattr("app.api.research_report_routes.save_workspace_analysis", save)
    monkeypatch.setattr(
        "app.api.research_report_routes.log_interaction", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "app.api.research_report_routes.update_interaction_request_status", update
    )

    response = client.post(
        "/workspaces/w-1/analyses/report",
        data={"question": "Q", "evidence_ids": "ev-1"},
    )

    assert response.status_code == 409
    update.assert_awaited_once_with(
        save.await_args.args[1]["analysis_id"], "workspace_changed"
    )
