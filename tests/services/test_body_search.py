from types import SimpleNamespace
import pytest


def document(identifier, text, legal_type="Bộ luật"):
    import hashlib

    return SimpleNamespace(
        content=text,
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        metadata=SimpleNamespace(
            document_id=identifier,
            document_number=f"{identifier}/2026/QH15",
            title="Văn bản",
            legal_type=legal_type,
            issuing_authority="Quốc hội",
            issuance_date="2026-01-01",
            source_url="https://vanban.chinhphu.vn/",
        ),
    )


def test_body_index_matches_content_and_filters_before_limit(tmp_path):
    from app.services.body_search import BodySearchIndex

    path = tmp_path / "body.sqlite3"
    docs = [
        document(1, "Điều 25. Thời gian thử việc\n1. Không quá 60 ngày.", "Khác"),
        document(2, "Điều 25. Thời gian thử việc\n1. Không quá 60 ngày."),
    ]
    index = BodySearchIndex.build(path, docs)
    from app.services.legal_browser import SearchFilters

    hits = index.search(
        "thu viec", filters=SearchFilters(legal_type="Bộ luật"), limit=1
    )
    assert len(hits) == 1 and hits[0]["document_id"] == 2
    assert hits[0]["section_id"] == "section-1"
    assert any(p["match"] for p in hits[0]["snippet_parts"])
    assert index.coverage()["document_count"] == 2
    with pytest.raises(FileExistsError):
        BodySearchIndex.build(path, docs)


def test_body_search_quotes_fts_syntax_and_preserves_reader_sections(tmp_path):
    from app.services.body_search import BodySearchIndex, passage_rows

    text = "Mở đầu\nChương I\nĐiều 1. Phạm vi\n<script>alert(1)</script> bảo vệ dữ liệu\nĐiều 2. Quyền\nNội dung"
    doc = document(1, text)
    rows = list(passage_rows(doc))
    assert "".join(r["text"] for r in rows) == text
    assert rows[-1]["section_id"] == "section-3"
    index = BodySearchIndex.build(tmp_path / "body.sqlite3", [doc])
    hit = index.search("bảo vệ dữ liệu")[0]
    assert hit["section_id"] == "section-2"
    assert "<script>" in "".join(p["text"] for p in hit["snippet_parts"])
    assert index.search('" OR NOT *') == []


def test_body_index_missing_does_not_create_database(tmp_path):
    from app.services.body_search import BodySearchIndex, BodySearchUnavailable

    path = tmp_path / "missing.sqlite3"
    with pytest.raises(BodySearchUnavailable):
        BodySearchIndex(path).search("luật")
    assert not path.exists()


def test_body_search_route_highlights_escaped_source_and_links_anchor(
    tmp_path, monkeypatch
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import legal_routes
    from app.services.body_search import BodySearchIndex
    from app.services.legal_browser import LegalBrowser

    index = BodySearchIndex.build(
        tmp_path / "body.sqlite3",
        [
            document(
                1, "Điều 25. Thử việc\n<script>alert(1)</script> thời gian thử việc"
            )
        ],
    )
    browser = LegalBrowser(
        store=SimpleNamespace(get_many=lambda ids: {1: document(1, "Điều 25. Thử việc\n<script>alert(1)</script> thời gian thử việc")}), index=SimpleNamespace(), body_index=index
    )
    monkeypatch.setattr(legal_routes, "browser", browser)
    app = FastAPI()
    app.include_router(legal_routes.router)
    response = TestClient(app).get("/search", params={"q": "thu viec", "scope": "body"})
    assert response.status_code == 200
    assert (
        "<mark>Thử việc</mark>" in response.text
        or "<mark>thử việc</mark>" in response.text
    )
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text
    assert "/documents/1#section-1" in response.text
    assert "1 văn bản" in response.text


def test_online_body_search_never_falls_back_to_local(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import legal_routes
    from app.services.legal_browser import LegalBrowser

    browser = LegalBrowser(store=SimpleNamespace(), index=SimpleNamespace())
    monkeypatch.setattr(legal_routes, "browser", browser)
    app = FastAPI()
    app.include_router(legal_routes.router)
    response = TestClient(app).get("/search", params={"q": "thử việc", "scope": "body"})
    assert response.status_code == 503
    assert "chỉ mục" in response.text


def test_incomplete_or_corrupt_source_never_becomes_ready(tmp_path):
    from app.services.body_search import BodySearchIndex, BodySearchUnavailable

    bad = document(1, "Nội dung")
    bad.content_sha256 = "wrong"
    path = tmp_path / "body.sqlite3"
    with pytest.raises(ValueError, match="hash_mismatch"):
        BodySearchIndex.build(path, [bad])
    with pytest.raises(BodySearchUnavailable):
        BodySearchIndex(path).coverage()


def test_long_article_has_exact_windows_and_stable_anchor():
    from app.services.body_search import passage_rows

    text = "Điều 1. Phạm vi\n" + "nội dung " * 900
    rows = list(passage_rows(document(1, text)))
    assert len(rows) > 1
    assert rows[0]["offset"] == 0
    assert rows[-1]["offset"] + len(rows[-1]["text"]) == len(text)
    assert all(
        row["text"] == text[row["offset"] : row["offset"] + len(row["text"])]
        for row in rows
    )
    assert all(
        row["section_id"] == "section-1" and len(row["text"]) <= 2400 for row in rows
    )


def test_body_pagination_is_stable(tmp_path):
    from app.services.body_search import BodySearchIndex

    index = BodySearchIndex.build(
        tmp_path / "body.sqlite3", [document(i, "Điều 1. thử việc") for i in range(25)]
    )
    first = index.search("thử việc", limit=20)
    second = index.search("thử việc", limit=20, offset=20)
    assert len(first) == 20 and len(second) == 5
    assert not {x["document_id"] for x in first} & {x["document_id"] for x in second}


def test_phrase_search_does_not_match_disconnected_words(tmp_path):
    from app.services.body_search import BodySearchIndex

    index = BodySearchIndex.build(
        tmp_path / "body.sqlite3",
        [
            document(1, "Điều 1. thời gian thử thách về việc thi hành án"),
            document(2, "Điều 25. thời gian thử việc"),
        ],
    )
    assert [row["document_id"] for row in index.search("thời gian thử việc")] == [2]


def test_phrase_across_window_boundary_is_not_lost(tmp_path):
    from app.services.body_search import BodySearchIndex

    text = "Điều 1. " + "x " * 1190 + "thời gian thử việc " + "y " * 400
    index = BodySearchIndex.build(tmp_path / "body.sqlite3", [document(1, text)])
    assert index.search("thời gian thử việc")


def test_phrase_does_not_silently_drop_terms_after_thirty(tmp_path):
    from app.services.body_search import BodySearchIndex

    index = BodySearchIndex.build(
        tmp_path / "body.sqlite3", [document(1, " ".join(["a"] * 30))]
    )
    assert index.search(" ".join(["a"] * 31)) == []


def test_browser_rejects_index_when_reader_source_has_changed(tmp_path):
    from app.services.body_search import BodySearchIndex, BodySearchUnavailable
    from app.services.legal_browser import LegalBrowser
    original = document(1, "Điều 1. Thử việc")
    changed = document(1, "Điều 1. Nội dung khác")
    index = BodySearchIndex.build(tmp_path / "body.sqlite3", [original])
    store = SimpleNamespace(get_many=lambda ids: {1: changed})
    browser = LegalBrowser(store=store, index=None, body_index=index)
    with pytest.raises(BodySearchUnavailable, match="body_index_stale"):
        browser.search_body("thử việc")
