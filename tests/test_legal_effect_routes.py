import json
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import optional_user, require_admin, verify_csrf


@pytest.fixture
def client():
    from app.api.legal_effect_routes import router

    app = FastAPI()

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.client_id = "owner-a"
        return await call_next(request)

    app.dependency_overrides[verify_csrf] = lambda: "valid"
    app.dependency_overrides[optional_user] = lambda: {"_id": "admin-1"}
    app.dependency_overrides[require_admin] = lambda: {
        "_id": "admin-1",
        "role": "admin",
    }
    app.include_router(router)
    return TestClient(app)


def _workspace() -> dict:
    return {
        "workspace_id": "w-1",
        "evidence": [
            {
                "evidence_id": "ev-1",
                "source_url": "https://vbpl.vn/van-ban/01",
                "excerpt": "Văn bản 01/2020/QH14 có hiệu lực thi hành từ ngày 01/01/2021.",
            }
        ],
    }


def _event() -> dict:
    return {
        "event_kind": "effective",
        "effective_date": "2021-01-01",
        "document_number": "01/2020/QH14",
        "target_document_number": "01/2020/QH14",
        "evidence_id": "ev-1",
        "exact_quote": "Văn bản 01/2020/QH14 có hiệu lực thi hành từ ngày 01/01/2021.",
        "scope": "whole_document",
    }


def test_legal_effect_route_requires_admin_review_and_saves_immutable_trace(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace", AsyncMock(return_value=_workspace())
    )
    save = AsyncMock(return_value=True)
    log = AsyncMock(return_value={"trace_id": "trace"})
    monkeypatch.setattr("app.api.legal_effect_routes.save_workspace_analysis", save)
    monkeypatch.setattr("app.api.legal_effect_routes.log_interaction", log)

    response = client.post(
        "/workspaces/w-1/analyses/legal-effect",
        data={
            "evidence_ids": "ev-1",
            "as_of": "2023-06-01",
            "events": json.dumps([_event()]),
        },
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["result"]["effects"][0]["status"] == "effective"
    saved = save.await_args.args[1]
    assert saved["reviewer_id"] == "admin-1"
    assert saved["reviewed_at"] and saved["last_checked"]
    assert saved["result"]["selected_sources"][0]["source_sha256"]
    assert saved["query_date"]
    assert log.await_args.kwargs["contexts"] == []
    assert "01/2020" not in log.await_args.kwargs["user_query"]


def test_legal_effect_route_rejects_invalid_events_before_save(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace", AsyncMock(return_value=_workspace())
    )
    save = AsyncMock()
    monkeypatch.setattr("app.api.legal_effect_routes.save_workspace_analysis", save)

    event = _event()
    event["evidence_id"] = "forged"
    response = client.post(
        "/workspaces/w-1/analyses/legal-effect",
        data={
            "evidence_ids": "ev-1",
            "as_of": "2023-06-01",
            "events": json.dumps([event]),
        },
    )

    assert response.status_code == 422
    save.assert_not_awaited()


def test_legal_effect_route_denies_nonadministrator(client, monkeypatch) -> None:
    del client.app.dependency_overrides[require_admin]
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace", AsyncMock(return_value=_workspace())
    )

    response = client.post(
        "/workspaces/w-1/analyses/legal-effect",
        data={
            "evidence_ids": "ev-1",
            "as_of": "2023-06-01",
            "events": json.dumps([_event()]),
        },
    )

    assert response.status_code in {401, 403}
