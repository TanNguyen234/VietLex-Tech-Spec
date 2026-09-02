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


def test_document_page_has_source_and_validity_warning(monkeypatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/documents/7")

    assert response.status_code == 200
    assert "Điều 25. Thời gian thử việc" in response.text
    assert 'href="https://example.gov.vn/7"' in response.text
    assert "chưa xác minh tình trạng hiệu lực" in response.text
    assert client.get("/documents/999").status_code == 404


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
