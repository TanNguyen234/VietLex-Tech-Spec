from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import optional_user, verify_csrf


def _workspace() -> dict:
    return {
        "documents": [
            {
                "document_id": "doc-1",
                "clauses": [
                    {"clause_id": "a" * 24 + "-001", "title": "One", "text": "text"}
                ],
            }
        ],
        "evidence": [{"evidence_id": "law-1", "excerpt": "law"}],
        "analyses": [],
    }


def _plan() -> dict:
    return {
        "input_sha256": "a" * 64,
        "document_id": "doc-1",
        "legal_evidence_ids": ["law-1"],
        "batches": [{"batch_id": "batch-1", "clause_ids": ["a" * 24 + "-001"]}],
        "skipped": [],
        "coverage": {},
    }


@pytest.fixture
def client():
    from app.api.full_document_review_routes import router

    app = FastAPI()

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.client_id = "owner-a"
        return await call_next(request)

    app.dependency_overrides[verify_csrf] = lambda: "ok"
    app.dependency_overrides[optional_user] = lambda: None
    app.include_router(router)
    return TestClient(app)


def test_plan_returns_reload_aggregate_and_rejects_user_document_as_law(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace", AsyncMock(return_value=_workspace())
    )
    monkeypatch.setattr(
        "app.api.full_document_review_routes.plan_full_document_review",
        lambda *_: _plan(),
    )
    monkeypatch.setattr(
        "app.api.full_document_review_routes.aggregate_full_document_review",
        lambda *_: {"status": "review_incomplete"},
    )
    response = client.post(
        "/workspaces/w-1/documents/doc-1/analyses/full-review/plan",
        data={"legal_evidence_ids": "law-1"},
    )
    assert (
        response.status_code == 200
        and response.json()["aggregate"]["status"] == "review_incomplete"
    )
    _workspace()["evidence"].append(
        {"evidence_id": "user-doc", "workspace_document_id": "doc-1"}
    )
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace",
        AsyncMock(
            return_value={
                **_workspace(),
                "evidence": [
                    {"evidence_id": "user-doc", "workspace_document_id": "doc-1"}
                ],
            }
        ),
    )
    assert (
        client.post(
            "/workspaces/w-1/documents/doc-1/analyses/full-review/plan",
            data={"legal_evidence_ids": "user-doc"},
        ).status_code
        == 422
    )


def test_run_stale_hash_fails_before_provider_and_wrong_owner_is_404(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace", AsyncMock(return_value=_workspace())
    )
    monkeypatch.setattr(
        "app.api.full_document_review_routes.plan_full_document_review",
        lambda *_: _plan(),
    )
    generate = AsyncMock()
    monkeypatch.setattr(
        "app.api.full_document_review_routes.generate_contract_review", generate
    )
    response = client.post(
        "/workspaces/w-1/analyses/full-review",
        data={
            "document_id": "doc-1",
            "batch_id": "batch-1",
            "input_sha256": "b" * 64,
            "legal_evidence_ids": "law-1",
        },
    )
    assert response.status_code == 409
    generate.assert_not_awaited()
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace", AsyncMock(return_value=None)
    )
    assert (
        client.post(
            "/workspaces/w-1/analyses/full-review",
            data={
                "document_id": "doc-1",
                "batch_id": "batch-1",
                "input_sha256": "a" * 64,
                "legal_evidence_ids": "law-1",
            },
        ).status_code
        == 404
    )


def test_run_success_uses_atomic_clause_progress(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace", AsyncMock(return_value=_workspace())
    )
    monkeypatch.setattr(
        "app.api.full_document_review_routes.plan_full_document_review",
        lambda *_: _plan(),
    )
    monkeypatch.setattr(
        "app.api.full_document_review_routes.generate_contract_review",
        AsyncMock(
            return_value=(
                type("R", (), {"model_dump": lambda self, **_: {"findings": []}})(),
                {},
            )
        ),
    )
    save = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.api.full_document_review_routes.save_full_document_review_batch", save
    )
    monkeypatch.setattr(
        "app.api.full_document_review_routes.log_interaction",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "app.api.full_document_review_routes.aggregate_full_document_review",
        lambda *_: {"status": "review_incomplete"},
    )
    response = client.post(
        "/workspaces/w-1/analyses/full-review",
        data={
            "csrf_token": "present",
            "document_id": "doc-1",
            "batch_id": "batch-1",
            "input_sha256": "a" * 64,
            "legal_evidence_ids": "law-1",
        },
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert save.await_args.kwargs["completed_clause_ids"] == ["a" * 24 + "-001"]


def test_provider_failure_persists_without_progress(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace", AsyncMock(return_value=_workspace())
    )
    monkeypatch.setattr(
        "app.api.full_document_review_routes.plan_full_document_review",
        lambda *_: _plan(),
    )
    monkeypatch.setattr(
        "app.api.full_document_review_routes.generate_contract_review",
        AsyncMock(side_effect=RuntimeError("quota")),
    )
    atomic = AsyncMock()
    fallback = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.api.full_document_review_routes.save_full_document_review_batch", atomic
    )
    monkeypatch.setattr(
        "app.api.full_document_review_routes.save_workspace_analysis", fallback
    )
    monkeypatch.setattr(
        "app.api.full_document_review_routes.log_interaction",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.api.full_document_review_routes.aggregate_full_document_review",
        lambda *_: {"status": "review_incomplete"},
    )
    response = client.post(
        "/workspaces/w-1/analyses/full-review",
        data={
            "csrf_token": "present",
            "document_id": "doc-1",
            "batch_id": "batch-1",
            "input_sha256": "a" * 64,
            "legal_evidence_ids": "law-1",
        },
    )
    assert response.status_code == 502
    atomic.assert_not_awaited()
    assert fallback.await_args.args[1]["status"] == "provider_error"


def test_run_requires_csrf_before_workspace_or_provider(client, monkeypatch) -> None:
    client.app.dependency_overrides.pop(verify_csrf)
    owned = AsyncMock(return_value=_workspace())
    monkeypatch.setattr("app.api.workspace_routes.get_workspace", owned)
    response = client.post(
        "/workspaces/w-1/analyses/full-review",
        data={
            "csrf_token": "present",
            "document_id": "doc-1",
            "batch_id": "batch-1",
            "input_sha256": "a" * 64,
            "legal_evidence_ids": "law-1",
        },
    )
    assert response.status_code == 403
    owned.assert_not_awaited()
