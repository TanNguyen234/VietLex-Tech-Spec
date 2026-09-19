import json
from types import SimpleNamespace

import httpx
import pytest

from app.services.official_web_search import OfficialPortalError


@pytest.mark.asyncio
async def test_gazette_search_maps_real_protocol_and_bounds_records():
    from app.services.congbao_search import CongBaoClient
    def respond(request):
        assert request.url == "https://api-searchcongbao.chinhphu.vn/search/van-ban"
        assert json.loads(request.content)["query"] == "dữ liệu cá nhân"
        return httpx.Response(200, json={"success": True, "data": [{
            "id_van_ban": 45578, "so_ky_hieu": "91/2025/QH15",
            "loai_van_ban": "Luật", "trich_yeu": "Bảo vệ dữ liệu cá nhân",
            "ngay_ban_hanh": "2025-06-26T00:00:00",
            "noi_dung_lien_quan_tim_thay": "Điều 3 Nguyên tắc",
        }]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await CongBaoClient(client=client, settings=SimpleNamespace()).search("dữ liệu cá nhân", limit=1)
    assert result.request_count == 1
    assert result.provider == "congbao_official_search"
    assert result.results[0].url == "https://congbao.chinhphu.vn/van-ban/luat-so-91-2025-qh15-45578.htm"
    assert result.results[0].issued_date == "2025-06-26"
    assert result.results[0].snippet == "Điều 3 Nguyên tắc"


@pytest.mark.asyncio
@pytest.mark.parametrize("response,kind", [
    (httpx.Response(302, headers={"location": "https://evil.test"}), "unexpected_redirect"),
    (httpx.Response(200, json={"success": False, "data": []}), "invalid_search_response"),
    (httpx.Response(200, json={"success": True, "data": {}}), "invalid_search_response"),
    (httpx.Response(200, content=b"x" * 2_000_001), "response_too_large"),
])
async def test_gazette_failure_is_not_empty_results(response, kind):
    from app.services.congbao_search import CongBaoClient
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        with pytest.raises(OfficialPortalError, match=kind) as caught:
            await CongBaoClient(client=client, settings=SimpleNamespace()).search("query")
    assert caught.value.request_count == 1


@pytest.mark.asyncio
async def test_gazette_detail_follows_approved_data_href_pdf(monkeypatch):
    from app.services.trusted_source_reader import read_source
    from unittest.mock import AsyncMock
    extractor = AsyncMock(return_value={"text": "Actual extractor tested separately", "method": "pdf_text"})
    monkeypatch.setattr("app.services.official_document_reader.extract_official_pdf", extractor)
    detail = "https://congbao.chinhphu.vn/van-ban/luat-so-91-2025-qh15-45578.htm"
    pdf = "https://congbaocdn.chinhphu.vn/law.pdf"
    requests = []
    def respond(request):
        requests.append(str(request.url))
        if str(request.url) == detail:
            return httpx.Response(200, headers={"content-type": "text/html"}, text='<title>Law</title><a href="/view" data-href="' + pdf + '">PDF</a>')
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-test-double")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await read_source(detail, client=client)
    assert requests == [detail, pdf]
    assert result["attachments"] == [pdf]
    assert extractor.await_args.kwargs["url"] == detail
    assert extractor.await_args.kwargs["attachment_url"] == pdf


@pytest.mark.asyncio
async def test_gazette_unapproved_attachment_stays_metadata_only():
    from app.services.trusted_source_reader import read_source
    requests = []
    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(200, headers={"content-type": "text/html"}, text='<title>Law</title><a data-href="https://congbaocdn.chinhphu.vn.evil.test/law.pdf">Download</a>')
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await read_source("https://congbao.chinhphu.vn/van-ban/law-1.htm", client=client)
    assert len(requests) == 1
    assert result["text"] == ""
    assert result["content_status"] == "metadata_only"


@pytest.mark.asyncio
async def test_default_research_queries_both_direct_portals(monkeypatch):
    from unittest.mock import AsyncMock
    from app.services.deep_research import build_research_plan, run_deep_research
    from app.services.official_web_search import OfficialSearchResponse
    portal = AsyncMock(return_value=OfficialSearchResponse((), "chinhphu", 1, 2))
    gazette = AsyncMock(return_value=OfficialSearchResponse((), "congbao", 1, 1))
    monkeypatch.setattr("app.services.official_web_search.OfficialPortalClient.search", portal)
    monkeypatch.setattr("app.services.congbao_search.CongBaoClient.search", gazette)
    plan = build_research_plan("bảo vệ dữ liệu cá nhân")
    result = await run_deep_research(plan, settings=SimpleNamespace(OFFICIAL_WEB_RESEARCH_ENABLED=True))
    assert portal.await_count == gazette.await_count == len(plan.steps)
    assert result.provider == "chinhphu_and_congbao"
