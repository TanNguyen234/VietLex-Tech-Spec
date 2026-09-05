from urllib.parse import parse_qs

import httpx
import pytest

from app.services.official_web_search import OfficialPortalClient


HTML_FORM = """
<html><form><input type="hidden" name="__VIEWSTATE" value="state">
<input type="hidden" name="__EVENTVALIDATION" value="validation"></form></html>
"""
HTML_RESULTS = """
<table id="ctrl_191017_163_grvDocument">
<tr><th>Số ký hiệu</th><th>Ngày ban hành</th><th>Trích yếu</th></tr>
<tr><td><a href="/?docid=123&pageid=27160">01/2026/NĐ-CP</a></td>
<td>01/01/2026</td><td><a href="/?docid=123&pageid=27160">Quy định về thử việc</a>
<a href="https://datafiles.chinhphu.vn/a.pdf">Tài liệu đính kèm</a></td></tr>
</table>
"""


@pytest.mark.asyncio
async def test_official_portal_posts_webforms_state_and_parses_bounded_results() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, text=HTML_FORM, request=request)
        form = parse_qs(request.content.decode())
        assert form["__VIEWSTATE"] == ["state"]
        assert form["ctrl_191017_163$txtSearchKeyword"] == ["thử việc"]
        return httpx.Response(200, text=HTML_RESULTS, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        response = await OfficialPortalClient(client=http).search("thử việc", limit=3)

    assert len(requests) == 2
    assert response.request_count == 2
    assert len(response.results) == 1
    assert response.results[0].document_number == "01/2026/NĐ-CP"
    assert response.results[0].url == "https://vanban.chinhphu.vn/?docid=123&pageid=27160"
    assert response.results[0].snippet == "Quy định về thử việc"


@pytest.mark.asyncio
async def test_official_portal_rejects_oversized_or_malformed_response() -> None:
    from app.services.official_web_search import OfficialPortalError

    async def run(body: str):
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, text=body, request=request)
        )
        async with httpx.AsyncClient(transport=transport) as http:
            await OfficialPortalClient(client=http).search("query")

    with pytest.raises(OfficialPortalError, match="form_contract"):
        await run("<html>missing hidden state</html>")
    with pytest.raises(OfficialPortalError, match="response_too_large"):
        await run("x" * 2_000_001)


@pytest.mark.asyncio
async def test_official_portal_rejects_post_response_without_results_contract() -> None:
    from app.services.official_web_search import OfficialPortalError

    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text=HTML_FORM, request=request)
    )
    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(
            OfficialPortalError, match="form_contract_unavailable"
        ) as captured:
            await OfficialPortalClient(client=http).search("query")
    assert captured.value.kind == "form_contract_unavailable"
    assert captured.value.request_count == 2
    assert captured.value.latency_ms is not None


@pytest.mark.asyncio
async def test_official_portal_rejects_cross_origin_redirect() -> None:
    from app.services.official_web_search import OfficialPortalError

    requested_hosts = []

    def redirect(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        if request.url.host == "vanban.chinhphu.vn":
            return httpx.Response(
                302, headers={"location": "https://evil.test/capture"}, request=request
            )
        return httpx.Response(200, text=HTML_FORM, request=request)

    transport = httpx.MockTransport(redirect)
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as http:
        with pytest.raises(OfficialPortalError, match="unexpected_redirect"):
            await OfficialPortalClient(client=http).search("query")
    assert requested_hosts == ["vanban.chinhphu.vn"]
