from unittest.mock import AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def client(monkeypatch):
    import app.api.legal_timeline_routes as routes

    app = FastAPI()
    app.state.limiter = routes.limiter
    routes.limiter._storage.reset()
    app.include_router(routes.router)
    app.dependency_overrides[routes.optional_user] = lambda: {"_id": "owner"}
    app.dependency_overrides[routes.verify_csrf] = lambda: "ok"
    monkeypatch.setattr(
        routes,
        "_owned_workspace",
        AsyncMock(
            return_value=(
                {
                    "evidence": [
                        {
                            "evidence_id": "e1",
                            "excerpt": "Ngày 01/01/2025",
                            "workspace_document_id": "doc1",
                        }
                    ]
                },
                "client",
                "owner",
            )
        ),
    )
    monkeypatch.setattr(routes, "save_workspace_analysis", AsyncMock(return_value=True))
    return TestClient(app)


def test_timeline_saves_owner_and_document_guards(client):
    import app.api.legal_timeline_routes as routes

    response = client.post(
        "/workspaces/w/analyses/timeline", data={"evidence_ids": "e1"}
    )
    assert response.status_code == 200
    assert response.json()["result"]["events"][0]["date"] == "2025-01-01"
    assert routes.save_workspace_analysis.await_args.kwargs[
        "required_document_ids"
    ] == ["doc1"]
    assert response.headers["cache-control"] == "no-store"


def test_timeline_rejects_unknown_evidence_and_save_race(client, monkeypatch):
    import app.api.legal_timeline_routes as routes

    assert (
        client.post(
            "/workspaces/w/analyses/timeline", data={"evidence_ids": "foreign"}
        ).status_code
        == 422
    )
    monkeypatch.setattr(
        routes, "save_workspace_analysis", AsyncMock(return_value=False)
    )
    assert (
        client.post(
            "/workspaces/w/analyses/timeline", data={"evidence_ids": "e1"}
        ).status_code
        == 409
    )
