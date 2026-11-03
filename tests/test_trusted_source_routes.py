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


@pytest.mark.parametrize('tamper', ['text', 'owner', 'key', None])
def test_free_snapshot_pin_checks_hash_and_owner_before_synthesis(client, monkeypatch, tamper):
    import hashlib
    import app.api.trusted_source_routes as routes
    from app.services.free_web_research import _snapshot

    text = 'Đặt cọc bảo đảm hợp đồng thuê nhà.'
    source = _snapshot({
        'url': 'https://vanban.chinhphu.vn/?docid=1', 'title': 'Bộ luật Dân sự',
        'text': text, 'sha256': hashlib.sha256(text.encode()).hexdigest(),
        'retrieved_at': '2026-10-19T00:00:00+00:00', 'method': 'visible_html_text',
    }, 'https://vanban.chinhphu.vn/?docid=1', workspace_id='w', owner_scope='user:owner', question='đặt cọc')
    assert source
    if tamper == 'text':
        source['text'] += ' giả'
    elif tamper == 'owner':
        source['snapshot_scope_sha256'] = 'a' * 64
    elif tamper == 'key':
        source['snapshot_key'] = 'a' * 64
    workspace = {'workspace_id': 'w', 'analyses': [{
        'analysis_id': 'run-1', 'kind': 'trusted_sources', 'research_mode': 'free_web_research',
        'result': {'sources': [source]},
    }]}
    monkeypatch.setattr(routes, '_owned_workspace', AsyncMock(return_value=(workspace, 'client', 'owner')))
    pin = AsyncMock(return_value=True)
    monkeypatch.setattr(routes, 'pin_workspace_evidence', pin)
    response = client.post('/workspaces/w/sources/pin', data={'analysis_id': 'run-1', 'source_index': 0, 'quote': text})
    if tamper:
        assert response.status_code == 422
        pin.assert_not_awaited()
    else:
        assert response.status_code == 200
        evidence = pin.await_args.args[1]
        assert evidence['source_sha256'] == source['sha256']
        assert evidence['source_url'] == source['url']
