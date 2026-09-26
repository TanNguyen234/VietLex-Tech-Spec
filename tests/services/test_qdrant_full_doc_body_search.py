import hashlib
from types import SimpleNamespace

import httpx
import pytest


def test_full_doc_body_search_is_default_for_online_deploy():
    from app.config import Settings

    assert Settings(_env_file=None).QDRANT_FULL_DOC_BODY_SEARCH_ENABLED is True


def test_qdrant_full_doc_search_filters_and_verifies_supabase_source():
    from app.services.qdrant_full_doc_body_search import QdrantFullDocBodySearch

    content = "Điều 1. Phạm vi\nNội dung chung.\nĐiều 2. Thử việc\nThời gian thử việc là 60 ngày."
    digest = hashlib.sha256(content.encode()).hexdigest()
    calls = []

    def respond(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"result": {
                "status": "green", "points_count": 1,
                "payload_schema": {"body": {"points": 1, "params": {
                    "type": "text", "phrase_matching": True, "ascii_folding": True,
                }}},
            }})
        return httpx.Response(200, json={"result": {"points": [{
            "id": 7, "payload": {"document_id": 7, "content_sha256": digest},
        }], "next_page_offset": None}})

    metadata = SimpleNamespace(document_id=7, document_number="45/2019/QH14", title="Bộ luật",
                               source_url="https://example.org", legal_type="Bộ luật",
                               issuing_authority="Quốc hội", issuance_date="2019-11-20")
    store = SimpleNamespace(count_documents=lambda: 1, get_many=lambda ids: {
        7: SimpleNamespace(metadata=metadata, content=content, content_sha256=digest),
    })
    index = QdrantFullDocBodySearch(url="https://qdrant.example", api_key="test",
                                    collection="legal-body-test", store=store,
                                    client=httpx.Client(transport=httpx.MockTransport(respond)))

    rows = index.search("thoi gian thu viec", filters=SimpleNamespace(
        legal_type="Bộ luật", authority="Quốc hội", issued_from="2019-01-01",
        issued_to="2020-01-01", sort="newest"), limit=21, offset=0)

    assert rows[0]["section_id"] == "section-2"
    assert any(part["match"] and part["text"] == "Thời gian thử việc" for part in rows[0]["snippet_parts"])
    payload = calls[-1].read().decode()
    assert '"phrase":"thoi gian thu viec"' in payload
    assert '"limit":21' in payload
    assert '"order_by":{"key":"issuance_date","direction":"desc"}' in payload
    assert '"legal_type"' in payload and '"issuing_authority"' in payload


def test_qdrant_full_doc_search_rejects_stale_hash():
    from app.services.body_search import BodySearchUnavailable
    from app.services.qdrant_full_doc_body_search import QdrantFullDocBodySearch

    def respond(request):
        if request.method == "GET":
            return httpx.Response(200, json={"result": {
                "status": "green", "points_count": 1,
                "payload_schema": {"body": {"points": 1, "params": {
                    "type": "text", "phrase_matching": True, "ascii_folding": True,
                }}},
            }})
        return httpx.Response(200, json={"result": {"points": [{
            "id": 7, "payload": {"document_id": 7, "content_sha256": "0" * 64},
        }], "next_page_offset": None}})

    store = SimpleNamespace(count_documents=lambda: 1, get_many=lambda ids: {
        7: SimpleNamespace(metadata=SimpleNamespace(), content="Điều 1. Thử việc",
                           content_sha256=hashlib.sha256("Điều 1. Thử việc".encode()).hexdigest()),
    })
    index = QdrantFullDocBodySearch(url="https://qdrant.example", api_key="test",
                                    collection="legal-body-test", store=store,
                                    client=httpx.Client(transport=httpx.MockTransport(respond)))

    with pytest.raises(BodySearchUnavailable, match="body_index_stale"):
        index.search("thử việc")


def test_online_browser_selects_qdrant_full_doc_index_when_enabled():
    from app.services.legal_browser import LegalBrowser
    from app.services.qdrant_full_doc_body_search import QdrantFullDocBodySearch

    browser = LegalBrowser.from_settings(SimpleNamespace(
        SERVERLESS_ONLINE_ONLY=True,
        SUPABASE_URL="https://project.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="public-test",
        SUPABASE_BODY_SEARCH_ENABLED=False,
        QDRANT_FULL_DOC_BODY_SEARCH_ENABLED=True,
        QDRANT_URL="https://qdrant.example",
        QDRANT_API_KEY="qdrant-test",
        QDRANT_FULL_DOC_BODY_COLLECTION="legal-body-test",
    ))

    assert isinstance(browser._body_index, QdrantFullDocBodySearch)
