from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import date
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.services.deep_research import OFFICIAL_SOURCE_DOMAINS


EventKind = Literal["effective", "repeal", "amend", "replace"]
EffectStatus = Literal["effective", "amended", "partially_effective", "repealed", "replaced", "unknown"]


class LegalEffectEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_kind: EventKind
    effective_date: date
    document_number: str = Field(min_length=1, max_length=100)
    target_document_number: str = Field(min_length=1, max_length=100)
    evidence_id: str = Field(min_length=1, max_length=80)
    exact_quote: str = Field(min_length=1, max_length=4_000)
    scope: Literal["whole_document", "partial"]


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _is_official_source(value: object) -> bool:
    parsed = urlparse(str(value or ""))
    host = (parsed.hostname or "").casefold()
    return parsed.scheme == "https" and host in OFFICIAL_SOURCE_DOMAINS


def _source_text(item: dict) -> str:
    return str(item.get("excerpt") or item.get("original") or "")


def _source_sha256(item: dict) -> str:
    source = f"{item.get('source_url') or ''}\n{_source_text(item)}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _quote_has_date(quote: str, value: date) -> bool:
    variants = {
        value.isoformat(),
        value.strftime("%d/%m/%Y"),
        value.strftime("%d-%m-%Y"),
        f"ngày {value.day} tháng {value.month} năm {value.year}",
        f"ngày {value.day:02d} tháng {value.month:02d} năm {value.year}",
    }
    normalized = _normalize(quote)
    return any(_normalize(variant) in normalized for variant in variants)


def _validated_events(
    evidence: list[dict], events: list[dict]
) -> tuple[list[dict], list[dict]]:
    if len(evidence) > 10 or len(events) > 20:
        raise ValueError("legal_effect_scope_too_large")
    sources: dict[str, dict] = {}
    for item in evidence:
        evidence_id = str(item.get("evidence_id") or "")
        if not evidence_id or evidence_id in sources or not _is_official_source(item.get("source_url")):
            raise ValueError("invalid_legal_effect_event")
        sources[evidence_id] = item
    try:
        parsed = [LegalEffectEvent.model_validate(event) for event in events]
    except ValidationError as error:
        raise ValueError("invalid_legal_effect_event") from error

    assertions = []
    for event in parsed:
        source = sources.get(event.evidence_id)
        quote = event.exact_quote
        if (
            source is None
            or not quote.strip()
            or quote not in _source_text(source)
            or not _quote_has_date(quote, event.effective_date)
            or _normalize(event.document_number) not in _normalize(quote)
            or _normalize(event.target_document_number) not in _normalize(quote)
        ):
            raise ValueError("invalid_legal_effect_event")
        assertions.append(
            {
                "event_kind": event.event_kind,
                "effective_date": event.effective_date.isoformat(),
                "evidence_id": event.evidence_id,
                "exact_quote": quote,
                "source_url": str(source["source_url"]),
                "source_sha256": _source_sha256(source),
                "document_number": event.document_number,
                "target_document_number": event.target_document_number,
                "scope": event.scope,
                "document_relationship": {
                    "source_document_number": event.document_number,
                    "target_document_number": event.target_document_number,
                },
            }
        )
    selected_sources = [
        {
            "evidence_id": evidence_id,
            "source_url": str(source["source_url"]),
            "source_sha256": _source_sha256(source),
            "source_provenance": "admin_reviewed_selected_evidence",
        }
        for evidence_id, source in sorted(sources.items())
    ]
    return assertions, selected_sources


def _effect_for_target(
    target_document_number: str, assertions: list[dict], as_of: date
) -> dict:
    normalized_target = _normalize(target_document_number)
    relevant = [
        assertion
        for assertion in assertions
        if _normalize(assertion["target_document_number"]) == normalized_target
    ]
    dated = [
        assertion
        for assertion in relevant
        if date.fromisoformat(assertion["effective_date"]) <= as_of
    ]
    status_events = [
        assertion
        for assertion in dated
        if assertion["event_kind"] in {"effective", "repeal", "replace"}
        and assertion["scope"] == "whole_document"
    ]
    reasons: list[str] = []
    if not status_events:
        reasons.append(
            "partial_scope_does_not_establish_document_effect"
            if any(assertion["scope"] == "partial" for assertion in dated)
            else "amendment_does_not_establish_effect"
            if dated
            else "no_event_as_of_date"
        )
        status: EffectStatus = "unknown"
    else:
        by_date: dict[str, set[str]] = defaultdict(set)
        for assertion in status_events:
            by_date[assertion["effective_date"]].add(assertion["event_kind"])
        if any(len(kinds) > 1 for kinds in by_date.values()):
            status = "unknown"
            reasons.append("conflicting_effect_events")
        else:
            latest = max(
                status_events, key=lambda assertion: assertion["effective_date"]
            )
            status = {
                "effective": "effective",
                "repeal": "repealed",
                "replace": "replaced",
            }[latest["event_kind"]]
            if status == "effective":
                changes = [
                    event for event in dated
                    if event["effective_date"] >= latest["effective_date"]
                ]
                if any(event["scope"] == "partial" and event["event_kind"] in {"repeal", "replace"} for event in changes):
                    status = "partially_effective"
                    reasons.append("partial_termination_in_reviewed_events")
                elif any(event["event_kind"] == "amend" for event in changes):
                    status = "amended"
                    reasons.append("amendment_in_reviewed_events")
    return {
        "target_document_number": target_document_number,
        "as_of": as_of.isoformat(),
        "status": status,
        "reasons": reasons,
    }


def review_legal_effect(evidence: list[dict], as_of: str, events: list[dict]) -> dict:
    """Return only explicit, human-reviewed legal-effect assertions and states."""
    try:
        as_of_date = date.fromisoformat(as_of)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid_as_of_date") from error
    assertions, selected_sources = _validated_events(evidence, events)
    targets: dict[str, str] = {}
    for assertion in assertions:
        target = assertion["target_document_number"]
        targets.setdefault(_normalize(target), target)
    effects = [
        _effect_for_target(target, assertions, as_of_date)
        for _normalized, target in sorted(targets.items())
    ]
    unknown = not effects or any(effect["status"] == "unknown" for effect in effects)
    review = {
        "status": "unknown" if unknown else "reviewed",
        "result": {
            "method": "human_admin_reviewed_events",
            "legal_certification": False,
            "as_of": as_of_date.isoformat(),
            "assertions": assertions,
            "effects": effects,
            "selected_sources": selected_sources,
            "reasons": ["no_reviewed_events"] if not assertions else [],
            "provenance": {
                "source_selection": "server_selected_evidence",
                "source_url_validation": "trusted_legal_domain_allowlist",
                "source_content_independently_fetched": False,
                "review_required": True,
            },
        },
    }
    return review
