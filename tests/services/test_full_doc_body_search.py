import hashlib
import httpx


def test_full_doc_search_resolves_verified_section_and_highlight():
    from app.services.full_doc_body_search import SupabaseFullDocBodySearch

    content = "Mở đầu.\nĐiều 1. Phạm vi\nQuy định chung.\nĐiều 2. Thử việc\nThời gian thử việc là 60 ngày."
    digest = hashlib.sha256(content.encode()).hexdigest()
    calls = []

    def respond(request):
        calls.append(request)
        if request.url.path.endswith("legal_full_doc_coverage"):
            return httpx.Response(200, json={"document_count": 14962, "index_version": 1})
        return httpx.Response(200, json=[{
            "document_id": 7, "document_number": "45/2019/QH14", "title": "Bộ luật",
            "source_url": "https://example.org/source", "legal_type": "Bộ luật",
            "issuing_authority": "Quốc hội", "issuance_date": "2019-11-20",
            "content": content, "content_sha256": digest,
        }])

    index = SupabaseFullDocBodySearch(
        url="https://project.supabase.co", publishable_key="public-test",
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    rows = index.search("thoi gian thu viec", limit=21, offset=20)

    assert rows[0]["section_id"] == "section-2"
    assert rows[0]["section_title"] == "Điều 2. Thử việc"
    assert any(part["match"] and part["text"] == "Thời gian thử việc" for part in rows[0]["snippet_parts"])
    assert b'"offset_count":20' in calls[-1].content
    assert b'"limit_count":21' in calls[-1].content


def test_full_doc_search_rejects_source_hash_mismatch():
    from app.services.body_search import BodySearchUnavailable
    from app.services.full_doc_body_search import SupabaseFullDocBodySearch

    def respond(request):
        if request.url.path.endswith("legal_full_doc_coverage"):
            return httpx.Response(200, json={"document_count": 1, "index_version": 1})
        return httpx.Response(200, json=[{
            "document_id": 7, "document_number": "7/2026", "title": "Test",
            "source_url": "https://example.org", "legal_type": "Luật",
            "issuing_authority": "Quốc hội", "issuance_date": "2026-01-01",
            "content": "Điều 1. Test", "content_sha256": "0" * 64,
        }])

    index = SupabaseFullDocBodySearch(
        url="https://project.supabase.co", publishable_key="public-test",
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    try:
        index.search("test")
    except BodySearchUnavailable as error:
        assert str(error) == "full_doc_source_mismatch"
    else:
        raise AssertionError("stale full-document content was accepted")


def test_full_doc_phrase_crossing_section_heading_has_reader_anchor():
    from app.services.full_doc_body_search import _marked_section

    content = "Điều 1. Quyền\nNội dung cuối.\nĐiều 2. Nghĩa vụ\nNội dung tiếp."

    section = _marked_section(content, "cuối Điều 2")

    assert section is not None
    assert section[0] == "section-1"
    assert "\ue000cuối.\nĐiều 2\ue001" in section[2]


def test_online_body_search_uses_existing_full_documents_when_enabled():
    from types import SimpleNamespace
    from app.services.full_doc_body_search import SupabaseFullDocBodySearch
    from app.services.legal_browser import LegalBrowser

    browser = LegalBrowser.from_settings(SimpleNamespace(
        SERVERLESS_ONLINE_ONLY=True,
        SUPABASE_URL="https://project.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="public-test",
        SUPABASE_BODY_SEARCH_ENABLED=True,
    ))

    assert isinstance(browser._body_index, SupabaseFullDocBodySearch)
