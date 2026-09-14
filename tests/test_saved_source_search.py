import pytest


def reading(identifier, version, text, page=1):
    return {"analysis_id": identifier, "kind": "trusted_sources", "result": {"sources": [{"url": "https://vanban.chinhphu.vn/?docid=1", "document_sha256": version, "title": "Văn bản", "text": text, "pages": [{"page": page, "text": text}]}]}}


def test_phrase_search_preserves_original_quote_and_matches_line_breaks():
    from app.services.workspace_presenter import search_saved_sources
    text = "Điều 3. Phụ\ncấp nghề được quy định tại đây."
    result = search_saved_sources({"analyses": [reading("a", "v1", text)]}, "PHỤ cấp")
    assert result["total_matches"] == 1
    hit = result["results"][0]
    assert hit["match"] == "Phụ\ncấp"
    assert hit["quote"] in text
    assert hit["can_pin"] is True
    assert hit["page"] == 1 and hit["analysis_id"] == "a"


def test_latest_page_wins_but_distinct_pdf_versions_do_not_merge():
    from app.services.workspace_presenter import search_saved_sources
    workspace = {"analyses": [reading("old", "v1", "phụ cấp"), reading("latest", "v1", "Nội dung khác"), reading("version2", "v2", "phụ cấp")]}
    result = search_saved_sources(workspace, "phụ cấp")
    assert [row["analysis_id"] for row in result["results"]] == ["version2"]
    assert result["pages_searched"] == 2


def test_search_retention_and_result_cap_are_explicit():
    from app.services.workspace_presenter import search_saved_sources
    rows = [reading("old", "old", "secret old text")] + [reading(str(i), str(i), "phụ cấp") for i in range(50)]
    assert search_saved_sources({"analyses": rows}, "secret")["total_matches"] == 0
    result = search_saved_sources({"analyses": rows}, "phụ cấp")
    assert result["pages_searched"] == 50
    assert result["total_matches"] == 50 and len(result["results"]) == 20
    assert search_saved_sources({"analyses": rows}, " ")["results"] == []
    with pytest.raises(ValueError):
        search_saved_sources({}, "x" * 201)


def test_unretained_quote_is_readable_but_cannot_be_pinned():
    from app.services.workspace_presenter import search_saved_sources
    row = reading("a", "v1", "phụ cấp")
    row["result"]["sources"][0]["text"] = "truncated text"
    assert search_saved_sources({"analyses": [row]}, "phụ cấp")["results"][0]["can_pin"] is False


def test_very_wide_whitespace_match_does_not_offer_an_oversized_pin():
    from app.services.workspace_presenter import search_saved_sources
    text = "phụ" + " " * 4000 + "cấp"
    hit = search_saved_sources({"analyses": [reading("a", "v1", text)]}, "phụ cấp")["results"][0]
    assert hit["can_pin"] is False
