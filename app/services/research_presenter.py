from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.evaluation.online_metrics import sanitize_error_message
from app.services.evidence_presenter import present_context
from app.services.runtime_errors import guardrail_error_reason


_CLAIM_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_ARTICLE = re.compile(r"\bĐiều\s+\d+[a-zđ]?\b", re.IGNORECASE)
_DOCUMENT = re.compile(r"\b\d{1,4}/\d{4}/[A-ZĐ0-9-]+\b", re.IGNORECASE)
_CLAUSE = re.compile(r"\bkhoản\s+\d+[a-zđ]?\b", re.IGNORECASE)
_STAGES = (
    "pinecone_hits",
    "fts_hits",
    "merged_document_candidates",
    "resolved_document_candidates",
    "structural_chunks_generated",
    "locally_selected_chunks",
    "reranker_input_chunks",
    "reranker_output_chunks",
    "final_evidence_chunks",
)


def _claims(answer: str) -> list[str]:
    cleaned = re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", str(answer), flags=re.MULTILINE)
    values = []
    for part in _CLAIM_SPLIT.split(cleaned):
        value = re.sub(r"\s+", " ", part).strip(" #*`-_\t")
        if len(value) >= 5 and "lưu ý" not in value.casefold():
            values.append(value[:500])
        if len(values) == 12:
            break
    return values


def build_claim_support(answer: str, contexts: list[str]) -> list[dict[str, Any]]:
    evidence = [present_context(item) for item in contexts[:10]]
    result = []
    for index, claim in enumerate(_claims(answer), start=1):
        documents = {value.casefold() for value in _DOCUMENT.findall(claim)}
        articles = {value.casefold() for value in _ARTICLE.findall(claim)}
        clauses = {value.casefold() for value in _CLAUSE.findall(claim)}
        matched = []
        for evidence_index, item in enumerate(evidence):
            citation = item.citation or ""
            if documents and (item.document_number or "").casefold() not in documents:
                continue
            if articles and not articles.intersection(
                value.casefold() for value in _ARTICLE.findall(citation)
            ):
                continue
            if clauses and not clauses.intersection(
                value.casefold() for value in _CLAUSE.findall(citation)
            ):
                continue
            if documents or articles:
                matched.append(evidence_index)
        # An article number alone cannot distinguish two different legal documents.
        if not documents and len({evidence[i].document_number for i in matched}) > 1:
            matched = []
        state = (
            "directly_supported"
            if matched and articles
            else "partially_supported"
            if matched
            else "unresolved"
        )
        result.append(
            {
                "claim_id": f"claim-{index}",
                "text": claim,
                "support_state": state,
                "evidence_indices": matched,
                "method": "citation_anchor_only",
            }
        )
    return result


def _value(source: object, name: str) -> object:
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


def sanitize_retrieval_trace(
    latency: Mapping[str, Any] | None,
    contexts: list[str],
    settings: Any,
    *,
    query: str,
    cached: bool,
) -> dict[str, Any]:
    latency = latency or {}
    diagnostics = latency.get("retrieval_diagnostics")
    diagnostics = diagnostics if isinstance(diagnostics, Mapping) else {}
    stage_trace = diagnostics.get("stage_trace")
    counts: dict[str, int] = {}
    if stage_trace is not None:
        for stage in _STAGES:
            items = _value(stage_trace, stage)
            if isinstance(items, (list, tuple)):
                counts[stage] = len(items)
    if "final_evidence_chunks" in counts:
        counts["retrieval_selected_chunks"] = counts.pop("final_evidence_chunks")
    if cached:
        counts = {"cache_response_contexts": len(contexts)}
    else:
        counts["final_evidence_chunks"] = len(contexts)
    numeric_latency = {
        str(key)[:80]: float(value)
        for key, value in latency.items()
        if isinstance(value, (int, float))
    }
    profile = diagnostics.get("context_profile")
    profile = profile if isinstance(profile, Mapping) else {}
    result: dict[str, Any] = {
        "status": "available",
        "query": str(query)[:2_000],
        "rewritten_query": str(latency.get("rewritten_query") or "")[:2_000] or None,
        "request_status": str(
            latency.get("retrieval_status") or ("cache_hit" if cached else "unobserved")
        )[:50],
        "cached": bool(cached),
        "runtime_mode": (
            "legacy-free-pinecone-v1"
            if bool(getattr(settings, "USE_LEGACY_FREE_PIPELINE", False))
            else "vertex-qdrant-v3"
        ),
        "backend": str(
            diagnostics.get("backend")
            or diagnostics.get("retrieval_backend")
            or "unobserved"
        )[:100],
        "collection": str(diagnostics.get("collection") or "")[:160] or None,
        "ranking": str(diagnostics.get("ranking") or "")[:80] or None,
        "candidate_counts": counts,
        "final_evidence_count": len(contexts),
        "prompt_context_count": 0 if cached else len(contexts),
        "count_semantics": "cache-response-v1" if cached else "prompt-contexts-v1",
        "context_stages": [
            {"stage": item["stage"], "count": item["count"],
             "sha256": [digest for digest in item.get("sha256", [])[:32]
                        if isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest)]}
            for item in (diagnostics.get("context_stages") or [])[:16]
            if isinstance(item, Mapping) and item.get("stage") in {
                "retrieval_selected", "expanded", "quality_filtered", "situation_filtered",
                "primary_rescue", "official_supplement", "prompt",
            } and type(item.get("count")) is int
        ],
        "context_budget_tokens": int(profile.get("max_tokens", getattr(settings, "LLM_CONTEXT_MAX_TOKENS", 0))),
        "latency": numeric_latency,
    }
    supplement = diagnostics.get("official_supplement")
    if isinstance(supplement, Mapping) and (isinstance(supplement.get("profile"), Mapping)
                                           or isinstance(diagnostics.get("context_profile"), Mapping)):
        result["official_search"] = {
            key: supplement[key] for key in (
                "status", "search_queries", "queries_completed", "provider_attempts", "urls_discovered",
                "urls_attempted", "sources_read", "sources_downloaded", "read_failures", "phase_seconds", "budget_unit",
                "context_tokens", "evidence_blocks", "legal_effect_status", "effect_as_of", "effect_reason",
            ) if key in supplement
        }
        result["official_search"]["errors"] = [
            {key: sanitize_error_message(error[key]) for key in ("phase", "provider", "kind") if key in error}
            for error in (supplement.get("errors") or [])[:32] if isinstance(error, Mapping)
        ]
        result["official_search"]["source_reads"] = [
            {key: item[key] for key in ("url", "sha256", "document_sha256", "inspected_pages", "retained_pages", "partial_read") if key in item}
            for item in (supplement.get("source_reads") or [])[:8] if isinstance(item, Mapping)
        ]
        result["official_search"]["discovered_urls"] = [
            url[:2048] for url in (supplement.get("discovered_urls") or [])[:120]
            if isinstance(url, str)
        ]
        coverage = supplement.get("topic_coverage")
        if isinstance(coverage, Mapping):
            result["official_search"]["topic_coverage"] = {
                key: [str(value)[:220] for value in (coverage.get(key) or [])[:8]]
                for key in ("covered", "missing")
            }
            result["official_search"]["topic_coverage"]["status"] = str(coverage.get("status", "unknown"))[:40]
        result["official_search"]["excluded_blocks"] = [
            {key: item[key] if key == "source" else str(item[key])[:500]
             for key in ("source", "article", "reason") if key in item}
            for item in (supplement.get("excluded_blocks") or [])[:128] if isinstance(item, Mapping)
        ]
    error_type = diagnostics.get("error_type")
    if error_type:
        result["diagnostic"] = {
            "error_type": sanitize_error_message(error_type),
        }
    return result


def _public_guardrail_state(value: object) -> dict[str, Any]:
    value = value if isinstance(value, Mapping) else {}
    mode = value.get("mode")
    mode = mode if isinstance(mode, str) and mode in {"off", "shadow", "enforce"} else "unobserved"
    stages = value.get("stages")
    stages = stages if isinstance(stages, Mapping) else {}
    result = {"mode": mode, "requested": mode != "off" if mode != "unobserved" else None,
              "executed": mode != "off" and value.get("executed") is True if mode != "unobserved" else None,
              "status": "unobserved" if mode == "unobserved" else "not_run", "stages": {}}
    inconsistent_execution = False
    for name in ("input", "output"):
        stage = stages.get(name)
        stage = stage if isinstance(stage, Mapping) else {}
        status = stage.get("status")
        if (mode in {"shadow", "enforce"} and result["executed"] is not True
                and status in ("passed", "rejected", "error")):
            inconsistent_execution = True
        if (result["executed"] is not True or not isinstance(status, str)
                or status not in {"passed", "rejected", "error"}
                or (status == "passed" and stage.get("safe") is not True)
                or (status == "rejected" and stage.get("safe") is not False)):
            status = "not_run"
        safe = True if status == "passed" else False if status == "rejected" else None
        error = stage.get("error")
        diagnostic = None
        if status == "error" and isinstance(error, Mapping):
            diagnostic = {"type": "GuardrailUnavailableError", "stage": name,
                          "reason": guardrail_error_reason(error.get("reason"))}
        result["stages"][name] = {"status": status, "safe": safe, "error": diagnostic}
        result[f"{name}_safe"] = safe
    if mode != "unobserved":
        statuses = [stage["status"] for stage in result["stages"].values()]
        result["status"] = ("error" if "error" in statuses else "rejected" if "rejected" in statuses
                            else "passed" if all(status == "passed" for status in statuses) else "not_run")
    if inconsistent_execution:
        result["status"] = "unobserved"
    return result


def build_public_retrieval_trace(interaction: Mapping[str, Any]) -> dict[str, Any]:
    metrics = interaction.get("metrics")
    metrics = metrics if isinstance(metrics, Mapping) else {}
    recorded_latency = metrics.get("latency")
    recorded_latency = recorded_latency if isinstance(recorded_latency, Mapping) else {}
    additions = {
        "request_status": str(metrics.get("request_status") or "unobserved")[:50],
        "cached": bool(interaction.get("cached")),
        "observed_provider": str(metrics.get("observed_provider") or "unobserved")[
            :100
        ],
        "observed_model": str(metrics.get("observed_model") or "unobserved")[:200],
        "guardrail_state": _public_guardrail_state(interaction.get("guardrail_state")),
        "latency": {
            str(key)[:80]: float(value)
            for key, value in recorded_latency.items()
            if isinstance(value, (int, float))
        },
    }
    trace = interaction.get("retrieval_trace")
    if isinstance(trace, Mapping):
        result = {
            key: value
            for key, value in trace.items()
            if key
            in {
                "status",
                "query",
                "rewritten_query",
                "runtime_mode",
                "backend",
                "collection",
                "ranking",
                "candidate_counts",
                "final_evidence_count",
                "context_budget_tokens",
                "official_search",
                "prompt_context_count",
                "count_semantics",
                "context_stages",
            }
        }
        if result.get("count_semantics") not in {"prompt-contexts-v1", "cache-response-v1"}:
            counts = dict(result.get("candidate_counts") or {})
            if "final_evidence_chunks" in counts:
                counts["retrieval_selected_chunks"] = counts.pop("final_evidence_chunks")
            result["candidate_counts"] = counts
            result["prompt_context_count"] = None
            result["count_semantics"] = "legacy"
        result.update(additions)
    else:
        result = {"status": "unavailable", "reason": "trace_not_recorded", **additions}
    result["evidence"] = []
    result["displayed_evidence_count"] = min(10, len(interaction.get("contexts") or []))
    for index, context in enumerate((interaction.get("contexts") or [])[:10]):
        view = present_context(context)
        result["evidence"].append(
            {
                "rank": index + 1,
                "document_id": view.document_id,
                "citation": (view.citation or view.title or "")[:500],
                "excerpt": view.excerpt[:4_000],
            }
        )
    error = metrics.get("technical_error")
    if isinstance(error, Mapping):
        result["diagnostics"] = {
            str(key)[:80]: sanitize_error_message(value)
            for key, value in error.items()
            if key in {"stage", "error_type", "message"}
        }
    elif error:
        result["diagnostics"] = {"message": sanitize_error_message(error)}
    elif isinstance(trace, Mapping) and isinstance(trace.get("diagnostic"), Mapping):
        result["diagnostics"] = {
            "error_type": sanitize_error_message(trace["diagnostic"].get("error_type"))
        }
    return result
