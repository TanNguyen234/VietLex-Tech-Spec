from unittest.mock import AsyncMock
from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.dependencies import optional_user, verify_csrf


def _analysis():
    return {"analysis_id": "a-1", "kind": "research_report", "status": "ok",
            "result": {"report": {"issue": "Test <script>", "analysis": [{"text": "A claim", "evidence_ids": ["e-1"]}], "exceptions": [], "checklist": [], "unknown": []}},
            "evidence_snapshot": [{"evidence_id": "e-1", "citation": "Article 1", "excerpt": "Snapshot", "source_url": "https://vbpl.vn/test"}]}


@pytest.fixture
def client(monkeypatch):
    from app.api.research_report_routes import router
    app = FastAPI()
    app.dependency_overrides[verify_csrf] = lambda: "ok"
    app.dependency_overrides[optional_user] = lambda: None
    app.include_router(router)
    monkeypatch.setattr("app.api.workspace_routes.get_workspace", AsyncMock(return_value={"analyses": [_analysis()]}))
    return TestClient(app)


def test_exports_are_owner_scoped_no_store_and_preserve_sources(client, monkeypatch):
    md = client.get("/workspaces/w-1/reports/a-1/export?format=md")
    assert md.status_code == 200
    assert "Snapshot" in md.text and "https://vbpl.vn/test" in md.text
    assert md.headers["cache-control"] == "no-store"
    docx = client.get("/workspaces/w-1/reports/a-1/export?format=docx")
    assert docx.status_code == 200
    with ZipFile(BytesIO(docx.content)) as archive:
        assert "Snapshot" in archive.read("word/document.xml").decode()
    monkeypatch.setattr("app.api.workspace_routes.get_workspace", AsyncMock(return_value=None))
    assert client.get("/workspaces/w-1/reports/a-1/export?format=md").status_code == 404


def test_edit_creates_new_unverified_version_and_keeps_snapshot(client, monkeypatch):
    save = AsyncMock(return_value=True)
    monkeypatch.setattr("app.api.research_report_routes.save_workspace_analysis", save)
    response = client.post("/workspaces/w-1/reports/a-1", data={"markdown": "Edited report", "csrf_token": "ok"}, follow_redirects=False)
    assert response.status_code == 303
    stored = save.await_args.args[1]
    assert stored["analysis_id"] != "a-1" and stored["parent_analysis_id"] == "a-1"
    assert stored["status"] == "human_edited_unverified"
    assert stored["evidence_snapshot"] == _analysis()["evidence_snapshot"]
    assert "model_assessment" not in stored


def test_print_view_escapes_user_content_and_unknown_format_is_rejected(client):
    response = client.get("/workspaces/w-1/reports/a-1")
    assert response.status_code == 200
    assert "<script>" not in response.text
    assert client.get("/workspaces/w-1/reports/a-1/export?format=exe").status_code == 422


def test_report_preview_has_source_anchors_and_escapes_active_content():
    from app.services.report_deliverables import report_preview
    analysis = _analysis()
    analysis['markdown'] = '# Memo\n\n- **Check** [e-1]\n\n<script>alert(1)</script>\n[x](javascript:alert(2))'
    html = report_preview(analysis)
    assert '<h1>Memo</h1>' in html
    assert '<strong>Check</strong>' in html
    assert 'href="#report-source-e-1"' in html
    assert '<script>' not in html
    assert 'href="javascript:' not in html
    assert analysis['markdown'].startswith('# Memo')
