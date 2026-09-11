from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest


@pytest.mark.asyncio
async def test_brave_discards_nonofficial_urls_and_bounds_results():
    from app.services.federated_official_search import BraveOfficialClient
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"web": {"results": [
            {"url": "https://evil.test/", "title": "No"},
            {"url": "https://vbpl.vn/law", "title": "Law", "description": "<b>Evidence</b>"},
            {"url": "https://moj.gov.vn/law", "title": "Law 2"}]}})
    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    provider = BraveOfficialClient(settings=SimpleNamespace(BRAVE_SEARCH_API_KEY="test", OFFICIAL_WEB_SEARCH_TIMEOUT_SECONDS=1), client=client)
    result = await provider.search("thử việc", limit=1)
    assert len(result.results) == 1 and result.results[0].domain == "vbpl.vn"
    assert result.results[0].snippet == "Evidence"
    assert "site:vbpl.vn" in requests[0].url.params["q"]
    assert requests[0].headers["X-Subscription-Token"] == "test"


@pytest.mark.asyncio
async def test_federation_preserves_partial_failure_in_research_status():
    from app.services.federated_official_search import FederatedOfficialClient
    from app.services.official_web_search import OfficialSearchRecord, OfficialSearchResponse, OfficialPortalError
    from app.services.deep_research import build_research_plan, run_deep_research
    response = OfficialSearchResponse((OfficialSearchRecord("https://vbpl.vn/a", "A", "vbpl.vn", "", "", ""),), "brave", 1, 1)
    provider = FederatedOfficialClient(portal=SimpleNamespace(search=AsyncMock(side_effect=OfficialPortalError("offline", request_count=1))), web=SimpleNamespace(search=AsyncMock(return_value=response)))
    result = await run_deep_research(build_research_plan("Test research"), provider=provider, settings=SimpleNamespace(OFFICIAL_WEB_RESEARCH_ENABLED=True))
    assert result.status == "partial"
    assert all(step.status == "partial_results" for step in result.steps)
    assert all(step.sources and step.error_kind for step in result.steps)
