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


def test_search_filters_accept_sector_without_changing_backend_filter_path():
    from app.services.legal_browser import SearchFilters

    filters = SearchFilters(sector="Lao động")

    # Lĩnh vực được lọc sau khi có kết quả; không đẩy xuống backend như ngày/loại/cơ quan.
    assert not filters.active
    assert filters.sector == "Lao động"


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
