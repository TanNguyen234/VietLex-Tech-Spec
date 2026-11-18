from datetime import date
from unittest.mock import AsyncMock

import pytest


# --- tiện ích thuần ------------------------------------------------------------


def test_currency_note_flags_unverified_status_for_recent_document():
    from app.services.source_currency import currency_note

    note = currency_note("2019-11-20", today=date(2026, 11, 15))

    assert "Ban hành 2019" in note
    assert "chưa xác minh hiệu lực" in note
    assert "Cũ hơn" not in note


def test_currency_note_warns_for_old_document():
    from app.services.source_currency import currency_note

    note = currency_note("1962-01-01", today=date(2026, 11, 15))

    assert "Cũ hơn 10 năm" in note
    assert "đối chiếu hiệu lực" in note


def test_currency_note_handles_missing_date():
    from app.services.source_currency import currency_note

    assert currency_note(None) == "Chưa có ngày ban hành · chưa xác minh hiệu lực"


def test_currency_note_reads_year_from_non_iso_date_and_flags_unreadable_date():
    from app.services.source_currency import currency_note

    assert "Ban hành 2019" in currency_note("20/11/2019", today=date(2026, 11, 15))
    # Ngày có nhưng không đọc được năm không được ghi là "chưa có ngày ban hành".
    assert currency_note("không rõ") == "Ngày ban hành không đọc được · chưa xác minh hiệu lực"


def test_sector_matches_is_case_insensitive_substring_and_empty_means_no_filter():
    from app.services.source_currency import sector_matches

    assert sector_matches("Lao động - Tiền lương", "lao động")
    assert sector_matches("Thuế - Phí - Lệ Phí", "")
    assert not sector_matches("Thuế - Phí - Lệ Phí", "lao động")
    assert not sector_matches(None, "lao động")


def test_format_citation_orders_fields_and_keeps_source():
    from app.services.source_currency import format_citation

    citation = format_citation(
        title="Bộ luật Lao động 2019",
        document_number="45/2019/QH14",
        issuing_authority="Quốc hội",
        issuance_date="2019-11-20",
        source_url="https://example.test/45-2019",
    )

    assert citation == (
        "Bộ luật Lao động 2019, số hiệu 45/2019/QH14, Quốc hội, "
        "ban hành 2019-11-20. Nguồn: https://example.test/45-2019"
    )


def test_format_citation_without_optional_fields():
    from app.services.source_currency import format_citation

    citation = format_citation(
        title="Văn bản thử",
        document_number="1/2000/TT",
        issuing_authority=None,
        issuance_date=None,
        source_url=None,
    )

    assert citation == "Văn bản thử, số hiệu 1/2000/TT"


# --- bộ lọc tìm kiếm -----------------------------------------------------------


def test_search_filters_activate_backend_sector_filtering():
    from app.services.legal_browser import SearchFilters

    filters = SearchFilters(sector="Lao động")

    assert filters.active
    assert filters.sector == "Lao động"


def test_supabase_and_local_sqlite_apply_sector_and_case_insensitive_filters_before_limit(tmp_path):
    import sqlite3
    from types import SimpleNamespace
    import httpx
    from app.services.legal_browser import LegalBrowser, SearchFilters, SupabaseLegalStore

    requests = []
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(200, json=[])
        )
    )
    remote = SupabaseLegalStore(
        url="https://project.supabase.co",
        publishable_key="test",
        client=client,
    )
    remote.search(
        "lao động",
        limit=21,
        offset=20,
        filters=SearchFilters(
            legal_type="bộ luật",
            authority="quốc hội",
            sector="Lao động",
        ),
    )
    params = requests[0].url.params
    assert params["legal_type"] == "ilike.bộ luật"
    assert params["issuing_authority"] == "ilike.quốc hội"
    assert params["legal_sectors"] == "ilike.*Lao động*"
    assert params["limit"] == "21"
    assert params["offset"] == "20"

    db_path = tmp_path / "content.sqlite3"
    metadata_map = {}
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE metadata("
            "document_id INTEGER, document_number TEXT, title TEXT, "
            "legal_type TEXT, issuing_authority TEXT, issuance_date TEXT, legal_sectors TEXT)"
        )
        for idx in range(1, 25):
            conn.execute(
                "INSERT INTO metadata VALUES(?,?,?,?,?,?,?)",
                (idx, f"{idx}/2020/QH14", "Luật thuế 2020", "Luật", "Quốc hội", "2020-01-01", "Thuế - Phí"),
            )
            metadata_map[idx] = SimpleNamespace(
                document_id=idx,
                document_number=f"{idx}/2020/QH14",
                title="Luật thuế 2020",
                source_url="",
                legal_type="Luật",
                issuing_authority="Quốc hội",
                issuance_date="2020-01-01",
                legal_sectors="Thuế - Phí",
            )
        conn.execute(
            "INSERT INTO metadata VALUES(25,'45/2019/QH14','Bộ luật Lao động 2019','Bộ luật','Quốc hội','2019-11-20','Lao động - Tiền lương')"
        )
        metadata_map[25] = SimpleNamespace(
            document_id=25,
            document_number="45/2019/QH14",
            title="Bộ luật Lao động 2019",
            source_url="",
            legal_type="Bộ luật",
            issuing_authority="Quốc hội",
            issuance_date="2019-11-20",
            legal_sectors="Lao động - Tiền lương",
        )

    store = SimpleNamespace(
        path=db_path,
        get_metadata_many=lambda ids: {i: metadata_map[i] for i in ids if i in metadata_map},
    )
    browser = LegalBrowser(store=store, index=SimpleNamespace(search=lambda *_a, **_kw: []))
    hits = browser.search(
        "",
        limit=21,
        filters=SearchFilters(legal_type="bộ luật", authority="quốc hội", sector="lao động"),
    )
    assert [h.document_id for h in hits] == [25]


def test_document_structure_recognizes_hierarchical_headings_while_preserving_exact_text():
    from app.services.document_structure import document_sections, reader_sections

    content = (
        "Quốc hội nước CHXHCN Việt Nam\n"
        "Phần thứ nhất. NHỮNG QUY ĐỊNH CHUNG\n"
        "Chương I. PHẠM VI ĐIỀU CHỈNH\n"
        "Mục 1. Nguyên tắc cơ bản\n"
        "Tiểu mục 1. Áp dụng\n"
        "Điều 1. Phạm vi điều chỉnh\nNội dung điều 1.\n"
        "Phụ lục I. Danh mục biểu mẫu\nBiểu mẫu 01."
    )
    sections = document_sections(content)
    assert "".join(s["text"] for s in sections) == content
    assert [set(s.keys()) for s in sections] == [{"id", "title", "text"}] * len(sections)
    # Keep BodySearchIndex section-{i} anchors stable on Chương/Điều only!
    assert [s["id"] for s in sections] == ["preamble", "section-1", "section-2"]
    assert sections[1]["title"].startswith("Chương I")
    assert sections[2]["title"].startswith("Điều 1")

    enriched = reader_sections(content)
    assert "".join(s["text"] for s in enriched) == content
    titles = [s["title"] for s in enriched]
    for prefix in ("Phần thứ nhất", "Chương I", "Mục 1", "Tiểu mục 1", "Điều 1", "Phụ lục I"):
        assert any(t.startswith(prefix) for t in titles)
    by_title = {s["title"].split(".")[0]: s["id"] for s in enriched}
    assert by_title["Chương I"] == "section-1"
    assert by_title["Điều 1"] == "section-2"
    kinds = [s["kind"] for s in enriched]
    assert "part" in kinds
    assert "chapter" in kinds
    assert "subpart" in kinds
    assert "subsection" in kinds
    assert "article" in kinds
    assert "annex" in kinds


def test_postgrest_text_match_never_restores_wildcards():
    from types import SimpleNamespace
    from app.services.legal_browser import SearchFilters, SupabaseLegalStore, _CANONICAL_LEGAL_TYPES, _postgrest_text_match

    assert _postgrest_text_match("*", _CANONICAL_LEGAL_TYPES) is None
    assert _postgrest_text_match("%_\\", _CANONICAL_LEGAL_TYPES) is None
    assert _postgrest_text_match("bộ_luật*", _CANONICAL_LEGAL_TYPES) == "ilike.bộ luật"

    store = SupabaseLegalStore(
        url="https://example.supabase.co",
        publishable_key="sb_publishable_test",
        client=SimpleNamespace(headers={}, get=lambda *_a, **_kw: pytest.fail("Wildcard-only filter must not query PostgREST")),
    )
    assert store.search("", limit=20, filters=SearchFilters(legal_type="*")) == []


def test_search_filters_reject_overlong_sector():
    from app.services.legal_browser import SearchFilters

    with pytest.raises(ValueError):
        SearchFilters(sector="x" * 101)


# --- route: lọc lĩnh vực, cảnh báo tuổi, nút sao chép trích dẫn ------------------


def _fake_browser(results):
    class _Browser:
        def search(self, query, limit, *, filters=None, offset=0):
            return list(results)

    return _Browser()


def test_search_route_filters_by_sector_and_shows_currency_and_copy_button(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import legal_routes
    from app.services.legal_browser import LegalSearchResult

    labour = LegalSearchResult(
        document_id=1,
        document_number="45/2019/QH14",
        title="Bộ luật Lao động 2019",
        source_url="https://example.test/45",
        legal_type="Bộ luật",
        issuing_authority="Quốc hội",
        issuance_date="2019-11-20",
        legal_sectors="Lao động - Tiền lương",
    )
    tax = LegalSearchResult(
        document_id=2,
        document_number="38/2019/QH14",
        title="Luật Quản lý thuế 2019",
        source_url="https://example.test/38",
        legal_type="Luật",
        issuing_authority="Quốc hội",
        issuance_date="2019-06-13",
        legal_sectors="Thuế - Phí - Lệ Phí",
    )
    monkeypatch.setattr(legal_routes, "browser", _fake_browser([labour, tax]))
    monkeypatch.setattr(legal_routes, "_get_browser", lambda: _fake_browser([labour, tax]))
    monkeypatch.setattr(
        legal_routes,
        "registry_records_batch",
        AsyncMock(return_value=[]),
        raising=False,
    )
    monkeypatch.setattr(
        legal_routes,
        "_registry_context",
        AsyncMock(return_value={"registry_results": {}, "registry_error": None, "as_of": None, "status_labels": {}}),
    )
    app = FastAPI()
    app.include_router(legal_routes.router)

    response = TestClient(app).get("/search", params={"q": "2019", "sector": "lao động"})

    assert response.status_code == 200
    assert "Bộ luật Lao động 2019" in response.text
    assert "Luật Quản lý thuế 2019" not in response.text
    assert "Ban hành 2019" in response.text
    assert "Sao chép trích dẫn" in response.text
    assert "data-citation=" in response.text
    assert "số hiệu 45/2019/QH14" in response.text
    # CSP của VietLex chặn script inline: JS phải nằm trong file tĩnh, không có onclick.
    assert "/static/js/legal-search.js" in response.text
    assert "onclick=" not in response.text
    assert "<script>" not in response.text
