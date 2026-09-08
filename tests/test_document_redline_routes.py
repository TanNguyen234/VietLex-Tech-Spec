from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import optional_user, verify_csrf


def _workspace() -> dict:
    return {
        "workspace_id": "w-1",
        "documents": [
            {
                "document_id": "doc-a",
                "filename": "draft-a.txt",
                "clauses": [{"clause_id": "a-1", "title": "Điều 1", "text": "A"}],
            },
            {
                "document_id": "doc-b",
                "filename": "draft-b.txt",
                "clauses": [{"clause_id": "b-1", "title": "Điều 1", "text": "B"}],
            },
        ],
    }


def _result() -> dict:
    return {
        "schema_version": "document-redline-v1",
        "document_a_id": "doc-a",
        "document_b_id": "doc-b",
        "legal_conclusion": "not_evaluated",
        "added": [],
        "removed": [],
        "changed": [],
        "same": [],
        "coverage": {},
    }


def test_document_redline_resolves_owned_documents_and_persists_atomic_requirements(
    monkeypatch,
) -> None:
    from app.api.document_redline_routes import router

    app = FastAPI()
    app.dependency_overrides[verify_csrf] = lambda: "valid"
    app.dependency_overrides[optional_user] = lambda: None
    app.include_router(router)
    client = TestClient(app)
    compare = Mock(return_value=_result())
    save = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace", AsyncMock(return_value=_workspace())
    )
    monkeypatch.setattr("app.api.document_redline_routes.compare_documents", compare)
    monkeypatch.setattr("app.api.document_redline_routes.save_workspace_analysis", save)

    response = client.post(
        "/workspaces/w-1/analyses/redline",
        data={"document_a_id": "doc-a", "document_b_id": "doc-b"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert compare.call_args.args == (
        _workspace()["documents"][0],
        _workspace()["documents"][1],
    )
    saved = save.await_args.args[1]
    assert saved["kind"] == "document_redline"
    assert saved["workspace_document_ids"] == ["doc-a", "doc-b"]
    assert saved["result"] == _result()
    assert save.await_args.kwargs["required_document_ids"] == ["doc-a", "doc-b"]


def test_document_redline_rejects_same_or_missing_documents_before_comparison(
    monkeypatch,
) -> None:
    from app.api.document_redline_routes import router

    app = FastAPI()
    app.dependency_overrides[verify_csrf] = lambda: "valid"
    app.dependency_overrides[optional_user] = lambda: None
    app.include_router(router)
    client = TestClient(app)
    compare = Mock()
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace", AsyncMock(return_value=_workspace())
    )
    monkeypatch.setattr("app.api.document_redline_routes.compare_documents", compare)

    same = client.post(
        "/workspaces/w-1/analyses/redline",
        data={"document_a_id": "doc-a", "document_b_id": "doc-a"},
    )
    missing = client.post(
        "/workspaces/w-1/analyses/redline",
        data={"document_a_id": "doc-a", "document_b_id": "missing"},
    )

    assert same.status_code == 422
    assert same.json()["detail"] == "different_document_ids_required"
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Document not found"
    compare.assert_not_called()


def test_document_redline_reports_atomic_workspace_change(monkeypatch) -> None:
    from app.api.document_redline_routes import router

    app = FastAPI()
    app.dependency_overrides[verify_csrf] = lambda: "valid"
    app.dependency_overrides[optional_user] = lambda: None
    app.include_router(router)
    client = TestClient(app)
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace", AsyncMock(return_value=_workspace())
    )
    monkeypatch.setattr(
        "app.api.document_redline_routes.compare_documents",
        Mock(return_value=_result()),
    )
    monkeypatch.setattr(
        "app.api.document_redline_routes.save_workspace_analysis",
        AsyncMock(return_value=False),
    )

    response = client.post(
        "/workspaces/w-1/analyses/redline",
        data={"document_a_id": "doc-a", "document_b_id": "doc-b"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "workspace_changed"
