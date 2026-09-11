from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_v3_browser_uses_packaged_v3_data_paths(monkeypatch) -> None:
    from pathlib import Path

    from app.services import legal_browser

    captured = {}

    def store(path):
        captured["content"] = path
        return object()

    def index(*, store, path, dataset_revision):
        captured["fts"] = path
        return object()

    monkeypatch.setattr(legal_browser, "ContentStore", store)
    monkeypatch.setattr(legal_browser, "LegalFtsIndex", index)
    legal_browser.LegalBrowser.from_settings(
        SimpleNamespace(
            USE_LEGACY_FREE_PIPELINE=False,
            CONTENT_STORE_PATH=Path("full.sqlite3"),
            LEGAL_FTS_PATH=Path("full-fts.sqlite3"),
            V3_CONTENT_STORE_PATH=Path("data/v3/content_store.sqlite3"),
            V3_LEGAL_FTS_PATH=Path("data/v3/legal_fts.sqlite3"),
            DATASET_REVISION="rev",
        )
    )

    assert captured == {
        "content": Path("data/v3/content_store.sqlite3"),
        "fts": Path("data/v3/legal_fts.sqlite3"),
    }


def test_serverless_browser_uses_supabase_instead_of_local_files(monkeypatch) -> None:
    from app.services import legal_browser

    captured = {}
    remote_store = object()

    def supabase_store(*, url, publishable_key):
        captured.update(url=url, publishable_key=publishable_key)
        return remote_store

    monkeypatch.setattr(legal_browser, "SupabaseLegalStore", supabase_store)
    browser = legal_browser.LegalBrowser.from_settings(
        SimpleNamespace(
            SERVERLESS_ONLINE_ONLY=True,
            SUPABASE_URL="https://project.supabase.co",
            SUPABASE_PUBLISHABLE_KEY="publishable-test",
            USE_LEGACY_FREE_PIPELINE=False,
        )
    )

    assert captured == {
        "url": "https://project.supabase.co",
        "publishable_key": "publishable-test",
    }
    assert browser._store is remote_store
    assert browser._index is remote_store


def _client(monkeypatch, *, source_url="https://example.gov.vn/7"):
    import app.api.legal_routes as routes

    result = SimpleNamespace(
        document_id=7,
        document_number="45/2019/QH14",
        title="Bộ luật Lao động 2019",
        source_url=source_url,
        legal_type="Bộ luật",
        issuing_authority="Quốc hội",
        issuance_date="2019-11-20",
    )
    document = SimpleNamespace(metadata=result, content="Điều 25. Thời gian thử việc")
    browser = SimpleNamespace(
        search=lambda query, limit: [result] if query else [],
        get_document=lambda document_id: document if document_id == 7 else None,
    )
    monkeypatch.setattr(routes, "browser", browser)
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def test_search_page_links_to_document_detail(monkeypatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/search?q=lao+dong")

    assert response.status_code == 200
    assert "Bộ luật Lao động 2019" in response.text
    assert 'href="/documents/7"' in response.text


def test_reader_pin_resolves_source_on_server_and_checks_workspace_owner(monkeypatch):
    from unittest.mock import AsyncMock
    from app.api import workspace_routes
    from app.api.dependencies import verify_csrf
    from app.api.legal_routes import router
    _client(monkeypatch)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_csrf] = lambda: "ok"
    monkeypatch.setattr(workspace_routes, "get_workspace", AsyncMock(return_value={}))
    save = AsyncMock(return_value=True)
    monkeypatch.setattr(workspace_routes, "pin_workspace_evidence", save)
    client = TestClient(app)
    response = client.post("/documents/7/sections/section-1/pin", data={"workspace_id": "w-1", "note": "Check current version"})
    assert response.status_code == 200
    evidence = save.await_args.args[1]
    assert evidence["document_id"] == 7
    assert evidence["excerpt"] == "Điều 25. Thời gian thử việc"
    assert evidence["note"] == "Check current version"
    monkeypatch.setattr(workspace_routes, "get_workspace", AsyncMock(return_value=None))
    assert client.post("/documents/7/sections/section-1/pin", data={"workspace_id": "other"}).status_code == 404


def test_document_page_has_source_and_validity_warning(monkeypatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/documents/7")

    assert response.status_code == 200
    assert "Điều 25. Thời gian thử việc" in response.text
    assert 'href="https://example.gov.vn/7"' in response.text
    assert "chưa xác minh tình trạng hiệu lực" in response.text
    assert client.get("/documents/999").status_code == 404


def test_reader_outline_preserves_source_and_escapes_markup(monkeypatch):
    client = _client(monkeypatch)
    import app.api.legal_routes as routes

    document = routes.browser.get_document(7)
    document.content = (
        "Mở đầu\nĐiều 1. Phạm vi\n<script>alert(1)</script>\nĐiều 2. Áp dụng\nNội dung"
    )
    response = client.get("/documents/7")
    assert 'href="#section-1"' in response.text
    assert 'id="section-2"' in response.text
    assert (
        "&lt;script&gt;" in response.text
        and "<script>alert(1)</script>" not in response.text
    )
    sections = routes.document_sections(document.content)
    assert "".join(row["text"] for row in sections) == document.content


def test_document_page_suppresses_non_http_source_url(monkeypatch) -> None:
    client = _client(monkeypatch, source_url="javascript:alert(1)")

    response = client.get("/documents/7")

    assert response.status_code == 200
    assert "javascript:" not in response.text


def test_privacy_and_terms_pages_are_public(monkeypatch) -> None:
    client = _client(monkeypatch)

    privacy = client.get("/privacy")
    terms = client.get("/terms")

    assert privacy.status_code == 200
    assert "Truy vấn pháp luật có thể chứa dữ liệu nhạy cảm" in privacy.text
    assert terms.status_code == 200
    assert "không thay thế tư vấn pháp lý" in terms.text
