"""Provider-free admin projections; missing telemetry is never inferred usage."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
import hashlib
import math
import re
from typing import Any

from app.evaluation.online_metrics import sanitize_error_message
from app.services.evidence_presenter import present_context
from app.services.pii import redact_pii
from app.services.public_evaluation import build_code_evaluation

TOKEN_FIELDS = (
    "prompt_token_count",
    "output_token_count",
    "thinking_token_count",
    "total_token_count",
)


class AdminDataUnavailable(RuntimeError):
    pass


def admin_query(
    *,
    search_query=None,
    request_status=None,
    provider=None,
    model=None,
    cache_hit=None,
    ragas_status=None,
    feedback=None,
    start_date=None,
    end_date=None,
    user_id=None,
    session_id=None,
):
    query = {}
    if search_query:
        query["$or"] = [
            {field: {"$regex": re.escape(search_query[:100]), "$options": "i"}}
            for field in ("user_query", "bot_response", "trace_id")
        ]
    for field, value in [
        ("metrics.request_status", request_status),
        ("metrics.observed_provider", provider),
        ("metrics.observed_model", model),
        ("metrics.ragas_status", ragas_status),
        ("feedback.rating", feedback),
    ]:
        if value:
            query[field] = str(value)[:200]
    if cache_hit is not None:
        query["cached"] = cache_hit
    if user_id:
        query['user_id'] = str(user_id)[:100]
    if session_id:
        query['session_id'] = str(session_id)[:100]
    if start_date or end_date:
        query["timestamp"] = {}
        if start_date:
            query["timestamp"]["$gte"] = datetime.combine(
                start_date, datetime.min.time()
            )
        if end_date:
            query["timestamp"]["$lt"] = datetime.combine(
                end_date, datetime.min.time()
            ) + timedelta(days=1)
    return query


def count(value: Any) -> int | None:
    return value if type(value) is int and 0 <= value <= 10**12 else None


def summarize_usage(calls: list[dict]) -> dict:
    result = {"calls": len(calls), "measured_calls": 0, "complete": False}
    result['dropped_calls'] = sum(count(call.get('dropped_calls')) or 0 for call in calls)
    result['capture_truncated'] = result['dropped_calls'] > 0
    for key in TOKEN_FIELDS:
        values = [count(call.get(key)) for call in calls]
        observed = [value for value in values if value is not None]
        result[key] = sum(observed) if observed else None
        result[key + "_coverage"] = len(observed)
    result["measured_calls"] = result["total_token_count_coverage"]
    result['calls'] += result['dropped_calls']
    result["complete"] = bool(calls) and result["measured_calls"] == result['calls'] and not result['capture_truncated']
    return result


def clean_text(value: Any, limit: int = 200) -> str:
    return redact_pii(sanitize_error_message(value, max_length=limit))[:limit]


def valid_token_integer(value):
    """Mongo equivalent of count(): missing, booleans and fractions are not usage."""
    return {'$and': [{'$in': [{'$type': value}, ['int', 'long']]},
                     {'$gte': [value, 0]}, {'$lte': [value, 10**12]}]}


def mongo_usage_summary() -> dict:
    """Recompute from the atomically appended ledger inside one Mongo update."""
    calls = {'$cond': [{'$isArray': '$metrics.llm_calls'}, '$metrics.llm_calls', []]}
    dropped = {'$sum': {'$map': {'input': calls, 'as': 'call', 'in':
                               {'$cond': [valid_token_integer('$$call.dropped_calls'), '$$call.dropped_calls', 0]}}}}
    result = {'calls': {'$add': [{'$size': calls}, dropped]}, 'dropped_calls': dropped,
              'capture_truncated': {'$gt': [dropped, 0]}}
    for field in TOKEN_FIELDS:
        values = {'$filter': {'input': {'$map': {'input': calls, 'as': 'call', 'in': '$$call.' + field}},
                              'as': 'value', 'cond': valid_token_integer('$$value')}}
        coverage = {'$size': values}
        result[field] = {'$cond': [{'$gt': [coverage, 0]}, {'$sum': values}, None]}
        result[field + '_coverage'] = coverage
    result['measured_calls'] = result['total_token_count_coverage']
    result['complete'] = {'$and': [{'$gt': [{'$size': calls}, 0]},
                                  {'$eq': [result['calls'], result['measured_calls']]}, {'$eq': [dropped, 0]}]}
    return result


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _clean_metadata(value: Any, depth: int = 0) -> Any:
    if depth > 5:
        return "[truncated]"
    if isinstance(value, dict):
        return {
            clean_text(k, 80): _clean_metadata(v, depth + 1)
            for k, v in list(value.items())[:80]
            if not any(
                secret in str(k).lower()
                for secret in (
                    "password",
                    "secret",
                    "api_key",
                    "authorization",
                    "cookie",
                )
            )
        }
    if isinstance(value, list):
        return [_clean_metadata(v, depth + 1) for v in value[:200]]
    if value is None or isinstance(value, bool) or type(value) is int:
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return clean_text(value, 2000)


def present_interaction(log: dict) -> dict:
    raw_contexts = log.get("contexts") if isinstance(log.get("contexts"), list) else []
    contexts = [clean_text(value, 4000) for value in raw_contexts[:10]]
    raw_metrics = _mapping(log.get("metrics"))
    metrics = _clean_metadata(raw_metrics)
    metrics.setdefault("ragas_status", "unobserved")
    for new, old in [
        ("ragas_proxy_faithfulness", "faithfulness"),
        ("ragas_proxy_answer_relevance", "answer_relevance"),
    ]:
        if metrics.get(new) is None and isinstance(metrics.get(old), (int, float)):
            metrics[new] = metrics[old]
    calls = raw_metrics.get("llm_calls")
    if not isinstance(calls, list):
        calls = [
            dict(
                info,
                use_case=stage,
                thinking_token_count=info.get("thought_token_count"),
            )
            for stage, info in _mapping(raw_metrics.get("provider_usage")).items()
            if isinstance(info, dict) and info.get("observed")
        ]
    calls = [call for call in calls if isinstance(call, dict)]
    external_calls = raw_metrics.get("external_calls")
    if not isinstance(external_calls, list):
        external_calls = []
    external_calls = [call for call in external_calls if isinstance(call, dict)]
    result = {
        "trace_id": clean_text(log.get("trace_id", log.get("_id", "")), 100),
        "session_id": clean_text(log.get("session_id", ""), 100),
        "user_id": clean_text(log.get('user_id') or 'anonymous', 100),
        "timestamp": log.get("timestamp")
        if hasattr(log.get("timestamp"), "strftime")
        else None,
        "user_query": clean_text(log.get("user_query", ""), 2000),
        "bot_response": clean_text(log.get("bot_response", ""), 10000),
        "contexts": contexts,
        "cached": bool(log.get("cached")),
        "metrics": metrics,
        "safety_status": _clean_metadata(_mapping(log.get("safety_status"))),
        "feedback": _clean_metadata(_mapping(log.get("feedback"))),
        "retrieval_trace": _clean_metadata(_mapping(log.get("retrieval_trace"))),
        "request_metadata": _clean_metadata(_mapping(log.get("request_metadata"))),
        "calls": _clean_metadata(calls),
        "external_calls": _clean_metadata(external_calls[:200]),
        'usage_display_truncated': len(calls) > 200,
        "external_calls_display_truncated": len(external_calls) > 200,
        "usage": summarize_usage(calls),
        "stored_context_count": len(raw_contexts),
        "display_truncated": len(raw_contexts) > 10
        or any(len(str(c)) > 4000 for c in raw_contexts[:10])
        or len(str(log.get("user_query", ""))) > 2000
        or len(str(log.get("bot_response", ""))) > 10000,
        "context_views": [],
    }
    from app.services.research_presenter import build_claim_support

    claims = build_claim_support(
        str(log.get("bot_response") or ""), [str(c) for c in raw_contexts[:10]]
    )
    quotes = [
        a or b
        for a, b in re.findall(
            r'“([^”]{5,2000})”|"([^"\n]{5,2000})"',
            str(log.get("bot_response") or "")[:10000],
        )
    ][:30]
    for index, context in enumerate(contexts):
        view = asdict(present_context(context))
        original_view = present_context(str(raw_contexts[index]))
        view.update(
            rank=index + 1,
            sha256=hashlib.sha256(str(raw_contexts[index]).encode()).hexdigest(),
            legal_status="UNKNOWN",
            evaluation_status="structural_only",
            semantic_support="NOT_EVALUATED",
            anchor_claim_count=sum(
                index in claim["evidence_indices"] for claim in claims
            ),
            quote_matches=[
                clean_text(quote, 2000)
                for quote in quotes
                if quote in original_view.excerpt
            ],
            body_present=bool(original_view.excerpt.strip()),
            character_count=len(str(raw_contexts[index])),
            approximate_whitespace_tokens=len(str(raw_contexts[index]).split()),
        )
        result["context_views"].append(view)
    # Evaluate full stored content, before display truncation; no judge/provider call.
    safe_metrics = dict(metrics)
    safe_metrics["latency"] = {
        key: value
        for key, value in _mapping(metrics.get("latency")).items()
        if type(value) in (int, float) and math.isfinite(value) and value >= 0
    }
    result["metrics"]["latency"] = safe_metrics["latency"]
    result["retrieval_trace"]["candidate_counts"] = {
        clean_text(key, 80): value
        for key, value in _mapping(
            result["retrieval_trace"].get("candidate_counts")
        ).items()
        if count(value) is not None
    }
    safe_metrics["context_count"] = len(raw_contexts)
    result["code_evaluation"] = build_code_evaluation({**log, "metrics": safe_metrics})
    return result


def usage_facets() -> dict:
    """Aggregate persisted request summaries, not an in-process provider snapshot."""
    totals = {
        "_id": None,
        "requests": {"$sum": 1},
        "calls": {"$sum": "$metrics.token_usage.calls"},
        "measured_calls": {"$sum": "$metrics.token_usage.measured_calls"},
        'dropped_calls': {'$sum': '$metrics.token_usage.dropped_calls'},
    }
    for field in TOKEN_FIELDS:
        totals[field] = {"$sum": "$metrics.token_usage." + field}
        totals[field + "_coverage"] = {
            "$sum": "$metrics.token_usage." + field + "_coverage"
        }
    call_group = {
        "_id": {key: "$metrics.llm_calls." + key for key in ("provider", "model", "use_case")},
        "calls": {"$sum": 1},
    }
    for field in TOKEN_FIELDS:
        value = "$metrics.llm_calls." + field
        valid = valid_token_integer(value)
        call_group[field] = {"$sum": {"$cond": [valid, value, 0]}}
        call_group[field + "_coverage"] = {"$sum": {"$cond": [valid, 1, 0]}}
    # Preserve existing projections while applying the same validation everywhere.
    call_group["tokens"] = call_group["total_token_count"]
    call_group["measured"] = call_group["total_token_count_coverage"]
    return {
        'user_usage': [{'$group': {'_id': '$user_id', 'requests': {'$sum': 1},
                                  'tokens': {'$sum': '$metrics.token_usage.total_token_count'},
                                  'measured_calls': {'$sum': '$metrics.token_usage.measured_calls'}}},
                       {'$sort': {'requests': -1}}, {'$limit': 30}],
        "token_usage": [
            {"$match": {"metrics.token_usage": {"$type": "object"}}},
            {"$group": totals},
        ],
        "providers": [
            {
                "$group": {
                    "_id": {
                        "provider": "$metrics.observed_provider",
                        "model": "$metrics.observed_model",
                    },
                    "requests": {"$sum": 1},
                    "avg_seconds": {"$avg": "$metrics.latency.t_total"},
                }
            },
            {"$sort": {"requests": -1}},
            {"$limit": 50},
        ],
        "request_statuses": [
            {"$group": {"_id": "$metrics.request_status", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ],
        "daily": [
            {
                "$group": {
                    "_id": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": "$timestamp",
                            "timezone": "UTC",
                        }
                    },
                    "requests": {"$sum": 1},
                    "tokens": {"$sum": "$metrics.token_usage.total_token_count"},
                    "measured_calls": {"$sum": "$metrics.token_usage.measured_calls"},
                }
            },
            {"$sort": {"_id": -1}},
            {"$limit": 31},
        ],
        "latency": [
            {"$match": {"metrics.latency.t_total": {"$type": "number", "$gte": 0}}},
            {
                "$group": {
                    "_id": None,
                    "count": {"$sum": 1},
                    "avg": {"$avg": "$metrics.latency.t_total"},
                    "max": {"$max": "$metrics.latency.t_total"},
                }
            },
        ],
        "latency_buckets": [
            {"$match": {"metrics.latency.t_total": {"$type": "number", "$gte": 0}}},
            {
                "$bucket": {
                    "groupBy": "$metrics.latency.t_total",
                    "boundaries": [0, 1, 3, 10, 30, 60, 120],
                    "default": "120+",
                    "output": {"count": {"$sum": 1}},
                }
            },
        ],
        "judge_statuses": [
            {"$group": {"_id": "$metrics.ragas_status", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ],
        "error_stages": [
            {"$match": {"metrics.technical_error": {"$ne": None}}},
            {
                "$group": {
                    "_id": {
                        "stage": "$metrics.technical_error.stage",
                        "kind": "$metrics.technical_error.error_type",
                    },
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"count": -1}},
            {"$limit": 30},
        ],
        "no_context": [{"$match": {"metrics.context_count": 0}}, {"$count": "count"}],
        "no_citation": [{"$match": {"metrics.citation_count": 0}}, {"$count": "count"}],
        "context_measured": [
            {"$match": {"metrics.context_count": {"$type": "number"}}},
            {"$count": "count"},
        ],
        "citation_measured": [
            {"$match": {"metrics.citation_count": {"$type": "number"}}},
            {"$count": "count"},
        ],
        "llm_usage": [
            {"$unwind": "$metrics.llm_calls"},
            {"$group": call_group},
            {"$sort": {"calls": -1}},
            {"$limit": 50},
        ],
    }
