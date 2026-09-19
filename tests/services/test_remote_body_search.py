import json
from types import SimpleNamespace
import httpx
import pytest


def adapter(handler):
    from app.services.remote_body_search import SupabaseBodySearch

    return SupabaseBodySearch(
        url="https://project.supabase.co",
        publishable_key="public-test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_rpc_filters_and_plain_highlight_spans():
    from app.services.legal_browser import SearchFilters

    calls = []

    def respond(request):
        if request.url.path.endswith("legal_body_coverage"):
            return httpx.Response(
                200,
                json={
                    "document_count": 1,
                    "passage_count": 1,
                    "built_at": "2026-09-19T00:00:00Z",
                    "source_sha256": "a" * 64,
                },
            )
        calls.append(request)
        return httpx.Response(
            200,
            json=[
                dict(
                    document_id=7,
                    section_id="section-2",
                    section_title="Điều 25",
                    marked="<script>bad</script> \ue000thử việc\ue001",
                )
            ],
        )

    index = adapter(respond)
    rows = index.search(
        "thử việc",
        filters=SearchFilters(
            legal_type="Bộ luật", issued_from="2019-01-01", sort="newest"
        ),
        limit=21,
        offset=20,
    )
    assert calls[0].url.path == "/rest/v1/rpc/search_legal_body"
    assert calls[0].headers["apikey"] == "public-test"
    payload = json.loads(calls[0].content)
    assert (
        payload["type_filter"] == "Bộ luật" and payload["issued_from"] == "2019-01-01"
    )
    assert (
        payload["limit_count"] == 21
        and payload["offset_count"] == 20
        and payload["sort_order"] == "newest"
    )
    assert rows[0]["snippet_parts"] == [
        {"text": "<script>bad</script> ", "match": False},
        {"text": "thử việc", "match": True},
    ]


@pytest.mark.parametrize(
    "status,payload",
    [(404, {}), (500, {}), (200, None), (200, []), (200, {"document_count": 0})],
)
def test_coverage_failure_is_not_healthy_zero(status, payload):
    from app.services.body_search import BodySearchUnavailable

    index = adapter(lambda r: httpx.Response(status, json=payload))
    with pytest.raises(BodySearchUnavailable):
        index.coverage()


def test_ready_coverage_and_rpc_error():
    from app.services.body_search import BodySearchUnavailable

    index = adapter(
        lambda r: httpx.Response(
            200,
            json={
                "document_count": 1,
                "passage_count": 2,
                "built_at": "2026-09-19T00:00:00Z",
                "source_sha256": "a" * 64,
            },
        )
    )
    assert index.coverage()["document_count"] == 1
    failing = adapter(lambda r: httpx.Response(503, json={"message": "unavailable"}))
    with pytest.raises(BodySearchUnavailable):
        failing.search("luật")


def test_online_body_search_is_opt_in():
    from app.services.legal_browser import LegalBrowser

    settings = SimpleNamespace(
        SERVERLESS_ONLINE_ONLY=True,
        SUPABASE_URL="https://project.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="public-test",
    )
    browser = LegalBrowser.from_settings(settings)
    assert browser._body_index is None
    settings.SUPABASE_BODY_SEARCH_ENABLED = True
    browser = LegalBrowser.from_settings(settings)
    assert browser._body_index is not None


def test_search_without_active_batch_is_unavailable_not_no_results():
    from app.services.body_search import BodySearchUnavailable

    index = adapter(
        lambda r: httpx.Response(
            200, json=None if r.url.path.endswith("legal_body_coverage") else []
        )
    )
    with pytest.raises(BodySearchUnavailable):
        index.search("thử việc")
