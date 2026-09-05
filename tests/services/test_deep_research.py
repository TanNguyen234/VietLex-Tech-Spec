from types import SimpleNamespace

import pytest

from app.services.deep_research import (
    DeepResearchDisabled,
    ResearchPlan,
    build_research_plan,
    is_official_source,
    run_deep_research,
)


def _settings(**overrides):
    values = {
        "OFFICIAL_WEB_RESEARCH_ENABLED": True,
        "USE_LEGACY_FREE_PIPELINE": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_plan_is_provider_free_deterministic_and_bounded() -> None:
    first = build_research_plan("Điều kiện đơn phương chấm dứt hợp đồng lao động?")
    second = build_research_plan("Điều kiện đơn phương chấm dứt hợp đồng lao động?")

    assert first == second
    assert isinstance(first, ResearchPlan)
    assert len(first.steps) == 5
    assert first.steps[0].query == "hợp đồng lao động"
    assert first.steps[-1].kind == "official_verification"
    assert all(len(step.query) <= 500 for step in first.steps)


@pytest.mark.parametrize(
    ("url", "domain", "expected"),
    [
        ("https://vbpl.vn/a", "vbpl.vn", True),
        ("https://vanban.chinhphu.vn/a", "", True),
        ("https://sub.moj.gov.vn/a", "sub.moj.gov.vn", True),
        ("http://vbpl.vn/a", "vbpl.vn", False),
        ("https://vbpl.vn.evil.test/a", "vbpl.vn.evil.test", False),
        ("https://evil.test/a", "vbpl.vn", False),
    ],
)
def test_official_source_validation_requires_https_and_exact_host_boundary(
    url, domain, expected
) -> None:
    assert is_official_source(url, domain) is expected


@pytest.mark.asyncio
async def test_research_keeps_only_result_metadata_from_official_sources() -> None:
    source_official = SimpleNamespace(
        url="https://vbpl.vn/a", title="Văn bản A", domain="vbpl.vn",
        snippet="Kết luận chính thức.", document_number="01/2026", issued_date="01/01/2026"
    )
    source_other = SimpleNamespace(
        url="https://example.com/b", title="Bài viết B", domain="example.com",
        snippet="Nhận định blog.", document_number="", issued_date=""
    )
    provider_result = SimpleNamespace(
        results=(source_official, source_other),
        provider="chinhphu_official_portal", latency_ms=12.0, request_count=2,
    )
    provider = SimpleNamespace(search=pytest.importorskip("unittest.mock").AsyncMock(return_value=provider_result))
    plan = build_research_plan("Câu hỏi")

    result = await run_deep_research(plan, provider=provider, settings=_settings())

    assert result.status == "complete"
    assert len(result.steps) == 5
    assert all(step.sources[0].url == "https://vbpl.vn/a" for step in result.steps)
    assert all(step.status == "results_found" for step in result.steps)
    assert all(step.sources[0].snippet == "Kết luận chính thức." for step in result.steps)
    assert "blog" not in str(result.model_dump()).casefold()


@pytest.mark.asyncio
async def test_research_reports_partial_when_a_step_has_no_results() -> None:
    from unittest.mock import AsyncMock

    valid = SimpleNamespace(
        results=(SimpleNamespace(url="https://vbpl.vn/a", title="A", domain="vbpl.vn", snippet="Có nguồn.", document_number="", issued_date=""),),
        provider="chinhphu_official_portal", latency_ms=1, request_count=2,
    )
    missing = SimpleNamespace(
        **{**valid.__dict__, "results": ()}
    )
    provider = SimpleNamespace(search=AsyncMock(side_effect=[valid, valid, missing, valid, valid]))

    result = await run_deep_research(
        build_research_plan("Câu hỏi"), provider=provider, settings=_settings()
    )

    assert result.status == "partial"
    assert result.steps[2].status == "no_results"


@pytest.mark.asyncio
async def test_disabled_setting_blocks_portal_before_provider_use() -> None:
    from unittest.mock import AsyncMock

    provider = SimpleNamespace(search=AsyncMock())
    with pytest.raises(DeepResearchDisabled):
        await run_deep_research(
            build_research_plan("Câu hỏi"),
            provider=provider,
            settings=_settings(OFFICIAL_WEB_RESEARCH_ENABLED=False),
        )
    provider.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_failure_preserves_http_error_telemetry() -> None:
    from unittest.mock import AsyncMock

    from app.services.official_web_search import OfficialPortalError
    from app.services.provider_runtime import (
        capture_provider_usage,
        current_provider_calls,
    )

    provider = SimpleNamespace(
        search=AsyncMock(
            side_effect=OfficialPortalError(
                "unexpected_redirect", request_count=1, latency_ms=4.5
            )
        )
    )

    @capture_provider_usage
    async def execute():
        result = await run_deep_research(
            build_research_plan("Câu hỏi"), provider=provider, settings=_settings()
        )
        return result, current_provider_calls()

    result, calls = await execute()
    assert result.status == "failed"
    assert result.provider == "chinhphu_official_portal"
    assert result.model == "webforms-search-v1"
    assert all(step.error_kind == "unexpected_redirect" for step in result.steps)
    assert calls[0]["call_kind"] == "http"
    assert calls[0]["request_count"] == 1
    assert calls[0]["latency_ms"] == 4.5
