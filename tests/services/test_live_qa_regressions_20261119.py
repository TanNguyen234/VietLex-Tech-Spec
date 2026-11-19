from __future__ import annotations

import asyncio
import inspect
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.services.evidence_presenter import present_context
from app.services.legal_browser import LegalBrowser, LegalBrowserBackendError
from app.services.rag_pipeline import _strip_latex_markup

APP_ROOT = Path(__file__).resolve().parents[2] / "app"


def test_latex_inline_single_dollar_math_becomes_plain_text():
    raw = (
        r"Khoản bồi thường: $12 \text{ triệu đồng} \times 0,5 = 6 \text{ triệu đồng}$ "
        r"và tổng là $6 + 12 = 18 \text{ triệu đồng}$."
    )
    cleaned = _strip_latex_markup(raw)
    assert "$" not in cleaned
    assert "\\text" not in cleaned
    assert "\\times" not in cleaned
    assert "12 triệu đồng × 0,5 = 6 triệu đồng" in cleaned
    assert "6 + 12 = 18 triệu đồng" in cleaned


def test_currency_dollar_amounts_remain_intact_during_latex_cleanup():
    raw = "Mức giao dịch dự kiến từ $100 đến $200 cho một hợp đồng."
    assert _strip_latex_markup(raw) == raw


def test_evidence_presenter_normalizes_nfd_citation_and_title_to_nfc():
    nfd_citation = unicodedata.normalize("NFD", "45/2019/QH14, Điều   25")
    nfd_title = unicodedata.normalize("NFD", "Bộ   luật Lao động 2019")
    decomposed = f"[{nfd_citation}]\nTiêu đề: {nfd_title}\nNội dung điều."
    view = present_context(decomposed)
    assert view.citation == "45/2019/QH14, Điều 25"
    assert view.title == "Bộ luật Lao động 2019"


def test_redesign_css_and_legal_document_ui_polish():
    css = (APP_ROOT / "static" / "css" / "vietlex-redesign.css").read_text(encoding="utf-8")
    assert "NotoSerif-Variable.ttf" in css
    assert ".citation{" in css and "font-family:inherit" in css
    assert "body>p[role=note]" in css or ".legal-note[role=note]" in css
    assert "grid-template-columns:230px minmax(0,1fr) 260px" in css

    html = (APP_ROOT / "templates" / "legal_document.html").read_text(encoding="utf-8")
    assert 'placeholder="Lọc Điều, Chương, Mục…"' in html


def test_stateless_banner_css_does_not_apply_flex_basis_100_to_body_note_and_polishes_checkbox_settings():
    css = (APP_ROOT / "static" / "css" / "vietlex-redesign.css").read_text(encoding="utf-8")
    assert "body>p[role=status],.topbar>p[role=status],body>p[role=note]" not in css
    assert "body>p[role=note]{" in css or "body>p[role=status],body>p[role=note]{" in css
    assert "flex:0 0 auto" in css
    assert ".deep-research-panel label:has(input[type=checkbox])" in css
    assert ".settings-section form .button{justify-self:start;width:auto}" in css


@pytest.mark.asyncio
async def test_local_stateless_session_history_preserves_followup_turns(monkeypatch):
    from app import database
    from app.services.conversation_context import followup_context

    monkeypatch.setattr(database.settings, "APP_ENV", "development")
    monkeypatch.setattr(database.settings, "LOCAL_STATELESS_MODE", True)

    p01 = "Kiện đòi nợ dân sự có bắt buộc phải hòa giải trước không?"
    f02 = "Vậy nếu tôi đã hòa giải thất bại thì có được khởi kiện không?"

    await database.log_interaction(
        trace_id="trace-local-1",
        user_query=p01,
        bot_response="Không bắt buộc.",
        contexts=[],
        cached=False,
        session_id="s-local-1",
        client_id="c-local-1",
    )
    history = await database.get_session_messages("s-local-1", "c-local-1", recent_limit=8)
    assert len(history) == 1
    assert history[0]["user_query"] == p01
    assert followup_context(f02, history) == p01
    assert await database.get_session_messages("s-local-1", "c-other", recent_limit=8) == []

    deleted = await database.delete_session("s-local-1", "c-local-1")
    assert deleted is True
    assert await database.get_session_messages("s-local-1", "c-local-1", recent_limit=8) == []


def test_local_quality_queue_timeout_and_admin_corpus_html_error_fallback(monkeypatch):
    from app.api import legal_routes, product_quality_routes
    from app.services import legal_browser

    assert getattr(legal_browser, "LOCAL_QUALITY_QUEUE_TIMEOUT_SECONDS", 0) >= 45.0

    class FailingBrowser:
        def quality_queue(self, issue: str, *, offset: int = 0):
            raise LegalBrowserBackendError("timeout")

    monkeypatch.setattr(legal_routes, "_get_browser", lambda: FailingBrowser())
    req = Request({"type": "http", "method": "GET", "path": "/admin/corpus", "headers": [], "query_string": b""})
    resp = asyncio.run(
        product_quality_routes.corpus_queue(req, issue="missing_date", skip=0, _admin={"role": "admin"})
    )
    assert resp.status_code == 503
    assert "text/html" in resp.media_type
    assert "admin-sidebar" in resp.body.decode("utf-8")


def test_local_quality_queue_caches_ids_and_invalidates_on_file_change(tmp_path, monkeypatch):
    import sqlite3
    from app.services import legal_browser

    db_path = tmp_path / "content_store.sqlite3"
    with sqlite3.connect(db_path) as con:
        con.execute(
            "CREATE TABLE metadata (document_id INTEGER PRIMARY KEY, issuance_date TEXT, source_url TEXT)"
        )
        con.execute("INSERT INTO metadata VALUES (1, '', 'https://example.com/1')")
        con.execute("INSERT INTO metadata VALUES (2, '2024-01-01', 'https://example.com/2')")
        con.commit()

    class StubStore:
        def __init__(self, path: Path) -> None:
            self.path = path
            self.metadata_calls: list[list[int]] = []

        def get_metadata_many(self, ids: list[int]) -> dict[int, dict[str, int]]:
            self.metadata_calls.append(list(ids))
            return {doc_id: {"document_id": doc_id} for doc_id in ids}

    real_connect = sqlite3.connect
    connect_calls = 0

    def counting_connect(*args, **kwargs):
        nonlocal connect_calls
        connect_calls += 1
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(legal_browser.sqlite3, "connect", counting_connect)
    legal_browser._LOCAL_QUALITY_QUEUE_CACHE.clear()

    store = StubStore(db_path)
    browser = LegalBrowser(store=store, index=None)

    first = browser.quality_queue("missing_date", offset=0)
    second = browser.quality_queue("missing_date", offset=0)
    assert first == [{"document_id": 1}]
    assert second == [{"document_id": 1}]
    assert connect_calls == 1

    # Also ensure empty results are cached and skip get_metadata_many
    empty1 = browser.quality_queue("missing_source", offset=0)
    empty2 = browser.quality_queue("missing_source", offset=0)
    assert empty1 == []
    assert empty2 == []
    assert connect_calls == 2

    # Mutate SQLite file (new row with missing date + updated mtime/size) -> invalidates cache
    with real_connect(db_path) as con:
        con.execute("INSERT INTO metadata VALUES (3, '', 'https://example.com/3')")
        con.commit()

    third = browser.quality_queue("missing_date", offset=0)
    assert third == [{"document_id": 1}, {"document_id": 3}]
    assert connect_calls == 3


def test_analysis_dock_model_select_and_settings_logout_button_css():
    css = (APP_ROOT / "static" / "css" / "vietlex-redesign.css").read_text(encoding="utf-8")
    assert ".analysis-dock .composer-dev-controls label{flex-wrap:wrap" in css
    assert ".analysis-dock .composer-dev-controls select{width:100%" in css
    assert ".settings-page form .button" in css and "justify-self:start;width:auto" in css
