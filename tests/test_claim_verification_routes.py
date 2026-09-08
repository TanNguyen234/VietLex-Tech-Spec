from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import optional_user, verify_csrf


def _result(status: str = "ok") -> dict:
    claims = (
        [
            {
                "claim_id": "claim-1",
                "text": "Người sử dụng lao động phải thông báo.",
                "verdict": "supported",
                "quotes": [{"evidence_id": "ev-1", "quote": "phải thông báo"}],
            }
        ]
        if status == "ok"
        else []
    )
    return {
        "status": status,
        "result": {
            "method": "model_assessment",
            "legal_certification": False,
            "confidence": "not_assessed",
            "claims": claims,
            "coverage": {
                "total_claims": 1,
                "assessed_claims": 1 if status == "ok" else 0,
                "supported_claims": 1 if status == "ok" else 0,
                "contradicted_claims": 0,
                "insufficient_claims": 0,
                "skipped_claims": 0 if status == "ok" else 1,
            },
        },
        "provider": "test-provider",
        "model": "test-model",
        "provider_status": "success" if status == "ok" else "quota",
        "provenance": {
            "source": "selected_server_evidence",
            "evidence_ids": ["ev-1"],
            "claim_ids": ["claim-1"],
            "evidence_is_untrusted": True,
        },
    }


@pytest.fixture
def client():
    from app.api.claim_verification_routes import router

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
                "excerpt": "Người sử dụng lao động phải thông báo bằng văn bản.",
                "original": "private source context",
            }
        ],
    }


def test_claim_verification_uses_owned_evidence_and_persists_snapshot(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace",
        AsyncMock(return_value=_workspace()),
    )
    verify = AsyncMock(return_value=_result())
    save = AsyncMock(return_value=True)
    log = AsyncMock(return_value={"trace_id": "trace"})
    monkeypatch.setattr("app.api.claim_verification_routes.verify_claims", verify)
    monkeypatch.setattr(
        "app.api.claim_verification_routes.save_workspace_analysis", save
    )
    monkeypatch.setattr("app.api.claim_verification_routes.log_interaction", log)

    response = client.post(
        "/workspaces/w-1/analyses/claims",
        data={
            "claim_text": "Người sử dụng lao động phải thông báo.",
            "evidence_ids": "ev-1",
        },
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["kind"] == "claim_verification"
    assert body["evidence_scope"] == 1
    assert body["result"]["claims"][0]["claim_id"] == "claim-1"
    verify.assert_awaited_once_with(
        "Người sử dụng lao động phải thông báo.", _workspace()["evidence"]
    )
    saved = save.await_args.args[1]
    assert saved["claim_text"] == "Người sử dụng lao động phải thông báo."
    assert saved["evidence_snapshot"][0]["original"] == "private source context"
    assert saved["provider_calls"] == []
    assert saved["admin_trace_status"] == "persisted"
    logged = log.await_args.kwargs
    assert logged["contexts"] == []
    assert logged["bot_response"] == "ok"
    assert "Người sử dụng" not in logged["user_query"]
    assert logged["retrieval_trace"]["context_sha256"]


def test_claim_verification_rejects_unselected_evidence_before_provider(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace",
        AsyncMock(return_value=_workspace()),
    )
    verify = AsyncMock()
    monkeypatch.setattr("app.api.claim_verification_routes.verify_claims", verify)

    response = client.post(
        "/workspaces/w-1/analyses/claims",
        data={"claim_text": "Claim.", "evidence_ids": "forged"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "insufficient_evidence"
    verify.assert_not_awaited()


def test_claim_verification_persists_typed_provider_error(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace",
        AsyncMock(return_value=_workspace()),
    )
    monkeypatch.setattr(
        "app.api.claim_verification_routes.verify_claims",
        AsyncMock(return_value=_result("provider_error")),
    )
    save = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.api.claim_verification_routes.save_workspace_analysis", save
    )
    monkeypatch.setattr(
        "app.api.claim_verification_routes.log_interaction",
        AsyncMock(return_value=None),
    )

    response = client.post(
        "/workspaces/w-1/analyses/claims",
        data={"claim_text": "Claim.", "evidence_ids": "ev-1"},
    )

    assert response.status_code == 502
    assert response.json()["status"] == "provider_error"
    assert save.await_args.args[1]["admin_trace_status"] == "unavailable"


def test_claim_verification_requires_owned_workspace(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace", AsyncMock(return_value=None)
    )

    response = client.post(
        "/workspaces/not-owned/analyses/claims",
        data={"claim_text": "Claim.", "evidence_ids": "ev-1"},
    )

    assert response.status_code == 404


def test_claim_verification_marks_logged_request_when_workspace_changes(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace",
        AsyncMock(return_value=_workspace()),
    )
    monkeypatch.setattr(
        "app.api.claim_verification_routes.verify_claims",
        AsyncMock(return_value=_result()),
    )
    save = AsyncMock(return_value=False)
    update = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.api.claim_verification_routes.save_workspace_analysis", save
    )
    monkeypatch.setattr(
        "app.api.claim_verification_routes.log_interaction", AsyncMock(return_value={})
    )
    monkeypatch.setattr(
        "app.api.claim_verification_routes.update_interaction_request_status", update
    )

    response = client.post(
        "/workspaces/w-1/analyses/claims",
        data={"claim_text": "Claim.", "evidence_ids": "ev-1"},
    )

    assert response.status_code == 409
    update.assert_awaited_once_with(
        save.await_args.args[1]["analysis_id"], "workspace_changed"
    )
