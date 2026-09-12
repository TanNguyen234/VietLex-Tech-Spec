from unittest.mock import AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def client(monkeypatch):
    import app.api.trusted_source_routes as routes

    app = FastAPI()
    app.state.limiter = routes.limiter
    routes.limiter._storage.reset()
    app.include_router(routes.router)
    app.dependency_overrides[routes.optional_user] = lambda: {"_id": "owner"}
    app.dependency_overrides[routes.verify_csrf] = lambda: "ok"
    monkeypatch.setattr(
        routes,
        "_owned_workspace",
        AsyncMock(return_value=({"analyses": []}, "client", "owner")),
    )
    monkeypatch.setattr(routes, "save_workspace_analysis", AsyncMock(return_value=True))
    return TestClient(app)


def test_unknown_url_prevents_every_fetch(client, monkeypatch):
    import app.api.trusted_source_routes as routes

    reader = AsyncMock()
    monkeypatch.setattr(routes, "read_source", reader)
    response = client.post(
        "/workspaces/w/analyses/sources",
        data={"urls": "https://vanban.chinhphu.vn/a\nhttps://evil.test"},
    )
    assert response.status_code == 422
    reader.assert_not_awaited()


def test_source_failure_is_persisted_without_fabricated_text(client, monkeypatch):
    import app.api.trusted_source_routes as routes

    monkeypatch.setattr(
        routes,
        "read_source",
        AsyncMock(side_effect=routes.SourceReadError("source_http_403")),
    )
    response = client.post(
        "/workspaces/w/analyses/sources", data={"urls": "https://vanban.chinhphu.vn/a"}
    )
    assert response.status_code == 502
    assert response.json()["result"]["sources"] == []
    assert response.json()["result"]["errors"][0]["kind"] == "source_http_403"
    routes.save_workspace_analysis.assert_awaited_once()


def test_reader_forwards_explicit_page_and_ocr_and_reports_readable_coverage(client,monkeypatch):
    import app.api.trusted_source_routes as routes
    reader=AsyncMock(return_value={'url':'https://datafiles.chinhphu.vn/a.pdf','sha256':'a','text':'','document_number':None,'content_status':'metadata_only'})
    monkeypatch.setattr(routes,'read_source',reader)
    response=client.post('/workspaces/w/analyses/sources',data={'urls':'https://datafiles.chinhphu.vn/a.pdf','page_start':'6','use_ocr':'true'})
    reader.assert_awaited_once_with('https://datafiles.chinhphu.vn/a.pdf',page_start=6,use_ocr=True,page_limit=5)
    assert response.json()['result']['coverage']['readable']==0
    assert response.json()['status']=='metadata_only'
