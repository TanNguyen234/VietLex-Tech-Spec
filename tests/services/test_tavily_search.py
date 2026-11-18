from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest


def _tavily_settings(**overrides):
    values = {
        "TAVILY_API": "tvly-unit-test-secret",
        "TAVILY_API_KEY": None,
        "tavily_api_key": "tvly-unit-test-secret",
        "TAVILY_SEARCH_ENABLED": True,
        "TAVILY_EXTRACT_ENABLED": True,
        "TAVILY_TIMEOUT_SECONDS": 5.0,
        "TAVILY_SEARCH_DEPTH": "basic",
        "USE_LEGACY_FREE_PIPELINE": False,
        "OFFICIAL_WEB_RESEARCH_ENABLED": True,
        "CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED": True,
        "CHAT_OFFICIAL_DEEP_READING_ENABLED": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_tavily_client_requires_key_and_blocks_legacy_free_pipeline():
    from app.services.tavily_search import TavilyOfficialClient

    with pytest.raises(ValueError, match="tavily_not_configured"):
        TavilyOfficialClient(settings=_tavily_settings(TAVILY_API=None, tavily_api_key=None))

    with pytest.raises(ValueError, match="legacy_free_pipeline"):
        TavilyOfficialClient(settings=_tavily_settings(USE_LEGACY_FREE_PIPELINE=True))


@pytest.mark.asyncio
async def test_tavily_search_splits_tier1_evidence_and_tier2_pivot_hints():
    from app.services.provider_runtime import capture_provider_usage, current_provider_calls
    from app.services.tavily_search import TavilyOfficialClient

    seen_requests: list[tuple[str, dict, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen_requests.append((str(request.url), dict(request.headers), body))
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://thuvienphapluat.vn/van-ban/Giao-thong/Nghi-dinh-100-2019-ND-CP.aspx",
                        "title": "Nghị định 100/2019/NĐ-CP xử phạt giao thông (Hết hiệu lực)",
                        "content": (
                            "Tình trạng: Đã hết hiệu lực. Văn bản 100/2019/NĐ-CP bị thay thế bởi "
                            "Nghị định 168/2024/NĐ-CP từ ngày 01/01/2025. Mức phạt vượt đèn đỏ ô tô "
                            "quy định tại Điều 6 và tạm giữ xe tại Điều 82 Nghị định 168/2024/NĐ-CP."
                        ),
                        "raw_content": "",
                    },
                    {
                        "url": "https://congbao.chinhphu.vn/van-ban/nghi-dinh-so-168-2024-nd-cp-44112.htm",
                        "title": "Nghị định số 168/2024/NĐ-CP quy định xử phạt vi phạm hành chính về trật tự, an toàn giao thông",
                        "content": "Phạt tiền từ 18.000.000 đồng đến 20.000.000 đồng đối với hành vi vượt đèn đỏ.",
                        "raw_content": (
                            "### Điều 6. Xử phạt người điều khiển xe ô tô\n"
                            "9. Phạt tiền từ 18.000.000 đồng đến 20.000.000 đồng đối với người điều khiển xe "
                            "không chấp hành hiệu lệnh của đèn tín hiệu giao thông.\n"
                            "### Điều 7. Xử phạt người điều khiển xe mô tô\n"
                            "7. Phạt tiền từ 4.000.000 đồng đến 6.000.000 đồng."
                        ),
                    },
                    {
                        "url": "https://random-blog.example.com/vuot-den-do",
                        "title": "Blog tin tức",
                        "content": "Nội dung không đáng tin cậy 999/2026/NĐ-CP.",
                        "raw_content": "Điều 1. Giả mạo.",
                    },
                ]
            },
        )

    @capture_provider_usage
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = TavilyOfficialClient(settings=_tavily_settings(), client=http_client)
            bundle = await client.search("vượt đèn đỏ ô tô phạt bao nhiêu tiền", limit=5)
            return bundle, current_provider_calls()

    bundle, calls = await run()

    assert len(seen_requests) == 1
    req_url, headers, req_body = seen_requests[0]
    assert req_url == "https://api.tavily.com/search"
    assert headers["authorization"] == "Bearer tvly-unit-test-secret"
    assert req_body["include_raw_content"] == "markdown"
    assert "thuvienphapluat.vn" in req_body["include_domains"]
    assert "congbao.chinhphu.vn" in req_body["include_domains"]

    # Tier-1 records ONLY (never Tier-2 or untrusted)
    assert len(bundle.tier1_records) == 1
    assert bundle.results == bundle.tier1_records
    assert bundle.tier1_records[0].url == (
        "https://congbao.chinhphu.vn/van-ban/nghi-dinh-so-168-2024-nd-cp-44112.htm"
    )
    assert bundle.tier1_records[0].document_number == "168/2024/NĐ-CP"
    assert "thuvienphapluat.vn" not in str(bundle.tier1_records)
    assert "random-blog" not in str(bundle.tier1_records)

    # Tier-1 raw markdown normalized so article headings start cleanly with "Điều 6."
    raw_md = bundle.tier1_raw_markdown[bundle.tier1_records[0].url]
    assert "Điều 6. Xử phạt người điều khiển xe ô tô" in raw_md
    assert "18.000.000 đồng" in raw_md

    # Tier-2 pivot hints extracted accurately, superseded filtered out
    assert "168/2024/NĐ-CP" in bundle.pivot_hints.document_numbers
    assert "100/2019/NĐ-CP" not in bundle.pivot_hints.document_numbers
    assert "100/2019/NĐ-CP" in bundle.pivot_hints.superseded_numbers
    assert bundle.pivot_hints.superseded_by.get("100/2019/NĐ-CP") == "168/2024/NĐ-CP"
    assert 6 in bundle.pivot_hints.target_articles
    assert "999/2026/NĐ-CP" not in bundle.pivot_hints.document_numbers

    # Provider telemetry recorded without leaking secret
    assert calls and calls[0]["provider"] == "tavily"
    assert calls[0]["success"] is True
    assert "tvly-unit-test-secret" not in str(calls)


@pytest.mark.asyncio
async def test_two_hop_pivot_rescues_from_corpus_first_and_pivots_to_tier1_when_missing():
    from app.ingestion.legal_text import DocumentMetadata
    from app.services.deep_official_search import search_and_read
    from app.services.tavily_search import TavilyOfficialClient

    # Sub-case A: Tier-2 discovers 293/2025/NĐ-CP and local/Supabase browser HAS it -> <100ms corpus rescue!
    def handler_corpus(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://luatvietnam.vn/lao-dong/nghi-dinh-293-2025-nd-cp.html",
                        "title": "Nghị định 293/2025/NĐ-CP quy định mức lương tối thiểu vùng mới nhất",
                        "content": "Điều 3 Nghị định 293/2025/NĐ-CP quy định mức lương tối thiểu vùng I là 5.310.000 đồng/tháng.",
                        "raw_content": "",
                    }
                ]
            },
        )

    corpus_text = (
        "Điều 3. Mức lương tối thiểu\n"
        "1. Mức lương tối thiểu tháng đối với người lao động làm việc theo vùng:\n"
        "Vùng I là 5.310.000 đồng/tháng; Vùng II là 4.730.000 đồng/tháng.\n"
    )
    meta = DocumentMetadata(
        document_id=2932025,
        document_number="293/2025/NĐ-CP",
        title="Nghị định quy định mức lương tối thiểu đối với người lao động làm việc theo hợp đồng lao động",
        source_url="https://vanban.chinhphu.vn/?docid=2932025",
        legal_type="Nghị định",
        legal_sectors="Lao động",
        issuing_authority="Chính phủ",
        issuance_date="2025-11-10",
    )

    class FakeBrowser:
        def search(self, query: str, *, limit: int = 50):
            if "293/2025" in query.upper():
                return [
                    SimpleNamespace(
                        document_id=meta.document_id,
                        document_number=meta.document_number,
                        title=meta.title,
                        issuing_authority=meta.issuing_authority,
                        issuance_date=meta.issuance_date,
                    )
                ]
            return []

        def get_document(self, doc_id: int):
            assert doc_id == meta.document_id
            return SimpleNamespace(
                metadata=meta,
                content=corpus_text,
                content_sha256=hashlib.sha256(corpus_text.encode("utf-8")).hexdigest(),
            )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler_corpus)) as http_client:
        tavily = TavilyOfficialClient(settings=_tavily_settings(), client=http_client)
        rescued = await search_and_read(
            "mức lương tối thiểu vùng hiện nay là bao nhiêu?",
            settings=_tavily_settings(),
            providers=[tavily],
            browser=FakeBrowser(),
            reader=lambda *_a, **_kw: pytest.fail("corpus hit must not need slow PDF download"),
        )

    assert rescued.contexts
    assert any("5.310.000 đồng/tháng" in ctx for ctx in rescued.contexts)
    assert all("luatvietnam.vn" not in ctx for ctx in rescued.contexts)
    assert rescued.diagnostics["official_corpus_rescue"]["status"] == "evidence_selected"

    # Sub-case B: Not in local browser -> Hop 2 runs exact-number Tier-1 search (include_tier2=False)
    hop_queries: list[tuple[str, list[str]]] = []

    def handler_two_hop(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        hop_queries.append((body["query"], body["include_domains"]))
        if "thuvienphapluat.vn" in body["include_domains"]:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "url": "https://thuvienphapluat.vn/van-ban/Lao-dong/Nghi-dinh-293-2025-ND-CP.aspx",
                            "title": "Nghị định 293/2025/NĐ-CP mức lương tối thiểu",
                            "content": "Xem Điều 3 Nghị định 293/2025/NĐ-CP quy định mức lương tối thiểu vùng.",
                            "raw_content": "",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://vanban.chinhphu.vn/?docid=999293",
                        "title": "Nghị định 293/2025/NĐ-CP mức lương tối thiểu",
                        "content": "Mức lương tối thiểu vùng.",
                        "raw_content": (
                            "Điều 3. Mức lương tối thiểu\n"
                            "1. Vùng I mức lương tối thiểu tháng là 5.310.000 đồng.\n"
                            "Điều 5. Hiệu lực thi hành\n"
                            "Nghị định này có hiệu lực thi hành từ ngày 01 tháng 01 năm 2026."
                        ),
                    }
                ]
            },
        )

    class MissBrowser:
        def search(self, *_a, **_kw):
            return []

        def get_document(self, *_a, **_kw):
            return None

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler_two_hop)) as http_client:
        tavily = TavilyOfficialClient(settings=_tavily_settings(), client=http_client)
        pivoted = await search_and_read(
            "mức lương tối thiểu vùng hiện nay?",
            settings=_tavily_settings(),
            providers=[tavily],
            browser=MissBrowser(),
            explicit_queries=("mức lương tối thiểu vùng hiện nay",),
            explicit_topics=("luong toi thieu",),
        )

    assert any("293/2025/NĐ-CP" in q and "thuvienphapluat.vn" not in doms for q, doms in hop_queries)
    assert pivoted.contexts
    assert any("5.310.000 đồng" in ctx for ctx in pivoted.contexts)
    assert all("thuvienphapluat.vn" not in ctx for ctx in pivoted.contexts)


@pytest.mark.asyncio
async def test_trusted_reader_falls_back_to_tavily_extract_on_vbpl_403():
    from app.services.chat_official_supplement import _source_context
    from app.services.evidence_presenter import (
         present_context,
        serialize_evidence_context,
    )
    from app.services.tavily_search import TavilyOfficialClient
    from app.services.trusted_source_reader import read_source

    vbpl_url = "https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=1682024"

    def portal_403(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden")

    def tavily_extract_ok(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        assert str(request.url) == "https://api.tavily.com/extract"
        assert body["urls"] == [vbpl_url]
        assert body["format"] == "markdown"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": vbpl_url,
                        "raw_content": (
                            "# Nghị định 168/2024/NĐ-CP\n\n"
                            "### Điều 6. Xử phạt vi phạm giao thông đối với xe ô tô\n"
                            "9. Phạt tiền từ 18.000.000 đồng đến 20.000.000 đồng khi vượt đèn đỏ.\n\n"
                            "### Điều 53. Hiệu lực thi hành\n"
                            "Nghị định này có hiệu lực từ ngày 01 tháng 01 năm 2025."
                        ),
                    }
                ]
            },
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(portal_403)) as portal_client,
        httpx.AsyncClient(transport=httpx.MockTransport(tavily_extract_ok)) as tavily_http,
    ):
        tavily_client = TavilyOfficialClient(settings=_tavily_settings(), client=tavily_http)
        source = await read_source(
            vbpl_url,
            question="xử phạt vượt đèn đỏ",
            client=portal_client,
            tavily_client=tavily_client,
            settings=_tavily_settings(),
        )

    assert source["method"] == "tavily_extract_tier1"
    assert source["content_status"] == "full_text"
    assert source["sha256"] == hashlib.sha256(source["text"].encode("utf-8")).hexdigest()
    assert "Điều 6. Xử phạt vi phạm giao thông" in source["text"]

    ctx = _source_context(vbpl_url, source, "xử phạt vi phạm", excerpt_override=source["text"])
    assert ctx is not None
    view = present_context(ctx)
    assert view.read_method == "tavily_extract_tier1"
    assert view.source_type == "official_external"
    serialized = serialize_evidence_context(ctx)
    assert isinstance(serialized, dict)
    assert serialized["provenance"]["read_method"] == "tavily_extract_tier1"

    # Mismatched single-result hostname from Tavily Extract must be rejected (Optional #1)
    def tavily_extract_wrong_host(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://congbao.chinhphu.vn/van-ban/other-law.htm",
                        "raw_content": "Điều 1. Nội dung khác domain.",
                    }
                ]
            },
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(portal_403)) as portal_client2,
        httpx.AsyncClient(transport=httpx.MockTransport(tavily_extract_wrong_host)) as tavily_http2,
    ):
        from app.services.runtime_errors import SourceReadError

        wrong_host_tavily = TavilyOfficialClient(settings=_tavily_settings(), client=tavily_http2)
        with pytest.raises(SourceReadError, match="source_http_403"):
            await read_source(
                vbpl_url,
                question="xử phạt vượt đèn đỏ",
                client=portal_client2,
                tavily_client=wrong_host_tavily,
                settings=_tavily_settings(),
            )


def test_semantic_cache_revision_tracks_tavily_flags_and_deep_research_plan_avoids_trailing_filler(
    monkeypatch,
):
    from app.services import semantic_cache
    from app.services.deep_research import build_research_plan

    base_rev = semantic_cache.semantic_cache_pipeline_revision()
    monkeypatch.setattr(
        semantic_cache.settings,
        "TAVILY_SEARCH_ENABLED",
        not semantic_cache.settings.TAVILY_SEARCH_ENABLED,
    )
    search_toggled_rev = semantic_cache.semantic_cache_pipeline_revision()
    assert search_toggled_rev != base_rev

    monkeypatch.setattr(
        semantic_cache.settings,
        "TAVILY_EXTRACT_ENABLED",
        not semantic_cache.settings.TAVILY_EXTRACT_ENABLED,
    )
    assert semantic_cache.semantic_cache_pipeline_revision() != search_toggled_rev

    plan = build_research_plan("Mức phạt vượt đèn đỏ đối với xe ô tô hiện nay là bao nhiêu tiền?")
    assert "nhiêu tiền" not in plan.steps[0].query
    assert any(term in plan.steps[0].query for term in ("xử phạt", "vượt đèn đỏ", "mức phạt"))


@pytest.mark.asyncio
async def test_federated_official_client_pivots_tier2_hit_to_tier1_on_hop2():
    from unittest.mock import AsyncMock
    from app.services.federated_official_search import FederatedOfficialClient
    from app.services.official_web_search import OfficialSearchRecord, OfficialSearchResponse
    from app.services.tavily_search import TavilyOfficialClient

    seen_tavily_calls: list[tuple[str, list[str]]] = []

    def tavily_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen_tavily_calls.append((body["query"], body["include_domains"]))
        if "luatvietnam.vn" in body["include_domains"]:
            # Hop 1: only Tier-2 discovery pivot + superseded reference
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "url": "https://luatvietnam.vn/lao-dong/nghi-dinh-293-2025-nd-cp.html",
                            "title": "Nghị định 293/2025/NĐ-CP thay thế Nghị định 74/2024/NĐ-CP",
                            "content": (
                                "Nghị định 74/2024/NĐ-CP hết hiệu lực, bị thay thế bởi "
                                "Nghị định 293/2025/NĐ-CP quy định mức lương tối thiểu vùng."
                            ),
                            "raw_content": "",
                        }
                    ]
                },
            )
        # Hop 2: Tier-1 exact document number search
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://vanban.chinhphu.vn/?docid=2932025",
                        "title": "Nghị định 293/2025/NĐ-CP quy định mức lương tối thiểu",
                        "content": "Mức lương tối thiểu đối với người lao động.",
                        "raw_content": "Điều 3. Mức lương tối thiểu vùng I là 5.310.000 đồng/tháng.",
                    }
                ]
            },
        )

    superseded_portal_row = OfficialSearchRecord(
        "https://vanban.chinhphu.vn/?docid=742024",
        "Nghị định 74/2024/NĐ-CP mức lương tối thiểu",
        "vanban.chinhphu.vn",
        "",
        "74/2024/NĐ-CP",
        "2024-06-30",
    )
    portal = SimpleNamespace(
        search=AsyncMock(
            return_value=OfficialSearchResponse((superseded_portal_row,), "portal", 1.0, 1)
        )
    )
    gazette_calls: list[str] = []

    async def gazette_search(q: str, *, limit: int = 3):
        gazette_calls.append(q)
        if "293/2025/NĐ-CP" in q.upper():
            rec = OfficialSearchRecord(
                "https://congbao.chinhphu.vn/van-ban/nghi-dinh-293-2025-nd-cp-1.htm",
                "Nghị định số 293/2025/NĐ-CP",
                "congbao.chinhphu.vn",
                "",
                "293/2025/NĐ-CP",
                "2025-11-10",
            )
            return OfficialSearchResponse((rec,), "congbao", 1.0, 1)
        return OfficialSearchResponse((), "congbao", 1.0, 1)

    from app.services.free_web_research import _BoundedProvider

    async with httpx.AsyncClient(transport=httpx.MockTransport(tavily_handler)) as http_client:
        tavily = TavilyOfficialClient(settings=_tavily_settings(), client=http_client)
        fed = FederatedOfficialClient(
            portal=portal,
            gazette=SimpleNamespace(search=gazette_search),
            tavily=_BoundedProvider(tavily, 5.0),
        )
        res = await fed.search("mức lương tối thiểu vùng hiện nay", limit=3)

    urls = [r.url for r in res.results]
    assert "https://vanban.chinhphu.vn/?docid=2932025" in urls
    assert "https://congbao.chinhphu.vn/van-ban/nghi-dinh-293-2025-nd-cp-1.htm" in urls
    assert all("luatvietnam.vn" not in u for u in urls)
    assert all("742024" not in u for u in urls)
    assert any("293/2025/NĐ-CP" in q and "luatvietnam.vn" not in doms for q, doms in seen_tavily_calls)
    assert any("293/2025/NĐ-CP" in q for q in gazette_calls)
    assert res.request_count == 5


@pytest.mark.asyncio
async def test_deep_official_search_bounds_tavily_queries_and_skips_rescued_doc_download():
    from app.ingestion.legal_text import DocumentMetadata
    from app.services.deep_official_search import search_and_read
    from app.services.tavily_search import TavilyOfficialClient

    tavily_queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        tavily_queries.append(body["query"])
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://luatvietnam.vn/lao-dong/nghi-dinh-293-2025-nd-cp.html",
                        "title": "Nghị định 293/2025/NĐ-CP mức lương tối thiểu",
                        "content": "Điều 3 Nghị định 293/2025/NĐ-CP quy định mức lương tối thiểu vùng.",
                        "raw_content": "",
                    },
                    {
                        "url": "https://vanban.chinhphu.vn/?docid=2932025",
                        "title": "Nghị định 293/2025/NĐ-CP quy định mức lương tối thiểu",
                        "content": "Mức lương tối thiểu vùng.",
                        "raw_content": "",
                    },
                ]
            },
        )

    corpus_text = (
        "Điều 3. Mức lương tối thiểu\n"
        "1. Vùng I là 5.310.000 đồng/tháng.\n"
    )
    meta = DocumentMetadata(
        document_id=2932025,
        document_number="293/2025/NĐ-CP",
        title="Nghị định quy định mức lương tối thiểu",
        source_url="https://vanban.chinhphu.vn/?docid=2932025",
        legal_type="Nghị định",
        legal_sectors="Lao động",
        issuing_authority="Chính phủ",
        issuance_date="2025-11-10",
    )

    class FakeBrowser:
        def search(self, query: str, *, limit: int = 50):
            if "293/2025" in query.upper():
                return [
                    SimpleNamespace(
                        document_id=meta.document_id,
                        document_number=meta.document_number,
                        title=meta.title,
                        issuing_authority=meta.issuing_authority,
                        issuance_date=meta.issuance_date,
                    )
                ]
            return []

        def get_document(self, doc_id: int):
            return SimpleNamespace(
                metadata=meta,
                content=corpus_text,
                content_sha256=hashlib.sha256(corpus_text.encode("utf-8")).hexdigest(),
            )

    read_urls: list[str] = []

    async def spy_reader(url: str, **_kwargs):
        read_urls.append(url)
        raise AssertionError(f"Should skip external download for rescued document URL {url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        tavily = TavilyOfficialClient(settings=_tavily_settings(), client=http_client)
        res = await search_and_read(
            "mức lương tối thiểu vùng hiện nay?",
            settings=_tavily_settings(),
            providers=[tavily],
            browser=FakeBrowser(),
            reader=spy_reader,
            explicit_queries=("q1 lương tối thiểu", "q2 vùng I", "q3 nghị định", "q4 2025", "q5 chính phủ"),
            explicit_topics=("luong toi thieu",),
        )

    assert len(tavily_queries) <= 2
    assert read_urls == []
    assert any("5.310.000 đồng/tháng" in ctx for ctx in res.contexts)


def test_guarded_cache_and_runtime_identity_tavily_parity_without_secrets(tmp_path):
    from app.services.guarded_answer_cache import guarded_cache_pipeline_revision
    from app.services.runtime_identity import runtime_identity

    (tmp_path / "stub.py").write_text("x = 1\n", encoding="utf-8")

    s1 = SimpleNamespace(
        USE_LEGACY_FREE_PIPELINE=False,
        DEFAULT_LLM_PROVIDER="auto",
        TAVILY_SEARCH_ENABLED=True,
        TAVILY_EXTRACT_ENABLED=True,
        tavily_api_key="tvly-secret-alpha",
    )
    s2 = SimpleNamespace(
        USE_LEGACY_FREE_PIPELINE=False,
        DEFAULT_LLM_PROVIDER="auto",
        TAVILY_SEARCH_ENABLED=True,
        TAVILY_EXTRACT_ENABLED=True,
        tavily_api_key=None,
    )
    assert guarded_cache_pipeline_revision(s1) == guarded_cache_pipeline_revision(s2)

    id1 = runtime_identity(s1, source_root=tmp_path)
    id2 = runtime_identity(s2, source_root=tmp_path)
    assert id1["configuration_sha256"] == id2["configuration_sha256"]
    assert "tvly-secret-alpha" not in json.dumps(id1)

    s_toggled_search = SimpleNamespace(**{**s2.__dict__, "TAVILY_SEARCH_ENABLED": False})
    assert guarded_cache_pipeline_revision(s_toggled_search) != guarded_cache_pipeline_revision(s2)
    assert (
        runtime_identity(s_toggled_search, source_root=tmp_path)["configuration_sha256"]
        != id2["configuration_sha256"]
    )

    s_toggled_provider = SimpleNamespace(**{**s2.__dict__, "DEFAULT_LLM_PROVIDER": "groq"})
    assert (
        runtime_identity(s_toggled_provider, source_root=tmp_path)["configuration_sha256"]
        != id2["configuration_sha256"]
    )
