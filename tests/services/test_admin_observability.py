import asyncio
from types import SimpleNamespace

import pytest


def test_usage_preserves_unknown_and_does_not_double_count_thinking():
    from app.services.admin_observability import summarize_usage

    result = summarize_usage(
        [
            {
                "prompt_token_count": 100,
                "output_token_count": 20,
                "thinking_token_count": 30,
                "total_token_count": 150,
            },
            {"prompt_token_count": 0, "total_token_count": None},
            {
                "prompt_token_count": -1,
                "output_token_count": True,
                "total_token_count": float("nan"),
            },
        ]
    )
    assert result["total_token_count"] == 150
    assert result["prompt_token_count"] == 100
    assert result["measured_calls"] == 1
    assert result["calls"] == 3
    assert result["complete"] is False
    assert summarize_usage([])["total_token_count"] is None


@pytest.mark.asyncio
async def test_provider_capture_is_request_local_and_resets_on_error():
    from app.services.provider_runtime import (
        capture_provider_usage,
        current_provider_calls,
        record_generation_result,
    )

    @capture_provider_usage
    async def operation(name):
        record_generation_result(
            SimpleNamespace(
                observed_provider=name,
                observed_model="model",
                status="success",
                provider_latency_ms=1,
                fallback_used=False,
                prompt_token_count=4,
                output_token_count=2,
                thought_token_count=None,
                total_token_count=6,
            ),
            "answer",
        )
        await asyncio.sleep(0)
        calls = current_provider_calls()
        if name == "failure":
            raise ValueError("expected")
        return calls

    first, second = await asyncio.gather(operation("one"), operation("two"))
    assert [call["provider"] for call in first] == ["one"]
    assert [call["provider"] for call in second] == ["two"]
    with pytest.raises(ValueError):
        await operation("failure")
    assert current_provider_calls() is None


def test_detail_redacts_without_silently_cutting_context_to_200():
    from app.services.admin_observability import present_interaction

    result = present_interaction(
        {
            "user_query": "Q" * 400,
            "bot_response": "Answer",
            "contexts": ["Evidence " * 100 + " Bearer secret-token"],
            "metrics": {
                "llm_calls": [{"provider": "<script>", "total_token_count": 42}]
            },
        }
    )
    assert len(result["user_query"]) == 400
    assert len(result["contexts"][0]) > 200
    assert "secret-token" not in result["contexts"][0]
    assert result["usage"]["total_token_count"] == 42
    assert result["metrics"]["ragas_status"] == "unobserved"
    assert result["context_views"][0]["legal_status"] == "UNKNOWN"


def test_truncation_is_reported_and_malformed_legacy_records_render():
    from app.services.admin_observability import present_interaction

    result = present_interaction(
        {"contexts": ["x" * 5000] * 12, "metrics": None, "safety_status": None}
    )
    assert result["display_truncated"] is True
    assert result["stored_context_count"] == 12
    assert len(result["contexts"]) == 10
    assert result["usage"]["total_token_count"] is None


def test_admin_query_bounds_dates_and_escapes_search():
    from datetime import date, datetime
    from app.services.admin_observability import admin_query

    query = admin_query(
        search_query="a.*",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 5),
        model="model",
    )
    assert query["timestamp"] == {
        "$gte": datetime(2026, 9, 1),
        "$lt": datetime(2026, 9, 6),
    }
    assert query["$or"][0]["user_query"]["$regex"] == r"a\.\*"
    assert query["metrics.observed_model"] == "model"


@pytest.mark.asyncio
async def test_persisted_request_contains_call_usage(monkeypatch):
    from unittest.mock import AsyncMock
    from app.services.provider_runtime import (
        capture_provider_usage,
        record_provider_event,
        ProviderEvent,
    )
    import app.database as database

    collection = SimpleNamespace(replace_one=AsyncMock())
    monkeypatch.setattr(
        database, "get_db", lambda: SimpleNamespace(evaluation_logs=collection)
    )

    @capture_provider_usage
    async def request():
        record_provider_event(
            ProviderEvent(
                "provider",
                "model",
                "guardrail",
                True,
                None,
                3,
                False,
                "2026-09-05",
                5,
                2,
                None,
                7,
            )
        )
        return await database.log_interaction(
            "trace", "query", "answer", ["context"], False
        )

    document = await request()
    assert document["metrics"]["token_usage"]["total_token_count"] == 7
    assert document["metrics"]["llm_calls"][0]["use_case"] == "guardrail"
    assert collection.replace_one.await_args.args[1] == document


@pytest.mark.asyncio
async def test_stats_connection_failure_is_unavailable_not_zero(monkeypatch):
    import app.database as database

    def fail():
        raise ValueError("secret")

    monkeypatch.setattr(database, "get_db", fail)
    stats = await database.get_admin_stats()
    assert stats["status"] == "unavailable"
    assert stats["error_kind"] == "ValueError"


def test_malformed_legacy_metadata_cannot_break_detail():
    from app.services.admin_observability import present_interaction

    log = present_interaction(
        {
            "metrics": {"latency": {"t_total": float("nan")}, "context_count": "bad"},
            "retrieval_trace": {"candidate_counts": "bad"},
            "contexts": [],
        }
    )
    assert log["metrics"]["latency"] == {}
    assert log["retrieval_trace"]["candidate_counts"] == {}


def test_context_assessment_distinguishes_anchor_from_exact_quote():
    from app.services.admin_observability import present_interaction

    result = present_interaction(
        {
            "user_query": "test",
            "bot_response": "Theo Điều 25 của 45/2019/QH14, “Tối đa 60 ngày”. “Tối đa 600 ngày”.",
            "contexts": ["[45/2019/QH14, Điều 25]\nID tài liệu: 123\nTối đa 60 ngày"],
        }
    )
    view = result["context_views"][0]
    assert view["anchor_claim_count"] == 1
    assert view["quote_matches"] == ["Tối đa 60 ngày"]
    assert view["semantic_support"] == "NOT_EVALUATED"
    assert view["legal_status"] == "UNKNOWN"
@pytest.mark.asyncio
async def test_capture_overflow_is_visible_and_never_complete():
    from app.services.provider_runtime import capture_provider_usage, current_provider_calls, record_provider_event, ProviderEvent
    from app.services.admin_observability import summarize_usage

    @capture_provider_usage
    async def request():
        for _ in range(202):
            record_provider_event(ProviderEvent('p','m','answer',True,None,1,False,'2026-09-05',1,1,None,2))
        return summarize_usage(current_provider_calls())
    result = await request()
    assert result['capture_truncated'] is True
    assert result['dropped_calls'] == 2
    assert result['complete'] is False
