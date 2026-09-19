"""Projection of explicitly published human reviews; never a completeness certificate."""

from datetime import date, datetime, timezone
from app.services.legal_effect import (
    review_legal_effect,
    _effect_for_target,
    _normalize,
)

_EVENT_FIELDS = (
    "event_kind",
    "effective_date",
    "document_number",
    "target_document_number",
    "evidence_id",
    "exact_quote",
    "scope",
)


def publication_record(analysis, publisher_id):
    if (
        analysis.get("kind") != "legal_effect_review"
        or not analysis.get("reviewer_id")
        or not publisher_id
    ):
        raise ValueError("human_review_required")
    reviewed_at = analysis.get("reviewed_at", "")
    if datetime.fromisoformat(reviewed_at).tzinfo is None:
        raise ValueError("review_timestamp_required")
    original = analysis.get("result") or {}
    if original.get("method") != "human_admin_reviewed_events" or not original.get(
        "assertions"
    ):
        raise ValueError("human_review_required")
    try:
        events = [
            {key: row[key] for key in _EVENT_FIELDS} for row in original["assertions"]
        ]
        checked = review_legal_effect(
            analysis["evidence_snapshot"], original["as_of"], events
        )["result"]["assertions"]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("review_snapshot_invalid") from error
    if checked != original["assertions"]:
        raise ValueError("review_snapshot_changed")
    # Public quotes only; workspace IDs, notes, selected evidence IDs stay private.
    assertions = [
        {
            key: value
            for key, value in row.items()
            if key not in {"evidence_id", "document_relationship"}
        }
        for row in checked
    ]
    return {
        "_id": analysis["analysis_id"],
        "state": "published",
        "assertions": assertions,
        "document_numbers": sorted(
            {
                _normalize(row[key])
                for row in assertions
                for key in ("document_number", "target_document_number")
            }
        ),
        "reviewer_id": str(analysis["reviewer_id"]),
        "reviewed_at": reviewed_at,
        "published_by": str(publisher_id),
        "published_at": datetime.now(timezone.utc).isoformat(),
        "provenance": "human_admin_reviewed_events",
        "source_content_independently_fetched": False,
    }


def registry_view(document_number, as_of, records):
    target = document_number.strip()
    if not target or len(target) > 100:
        raise ValueError("invalid_document_number")
    day = date.fromisoformat(as_of)
    if day.isoformat() != as_of:
        raise ValueError("invalid_as_of_date")
    key = _normalize(target)
    events = []
    for record in records:
        if record.get("state") != "published":
            continue
        for event in record["assertions"]:
            if key not in {
                _normalize(event["document_number"]),
                _normalize(event["target_document_number"]),
            }:
                continue
            events.append(
                {
                    **event,
                    "source_verified_at": record["reviewed_at"],
                    "provenance": "human_admin_reviewed_event",
                }
            )
    if len(events) > 200:
        raise ValueError("registry_scope_too_large")
    events.sort(
        key=lambda e: (e["effective_date"], e["document_number"], e["event_kind"])
    )
    effect = _effect_for_target(target, events, day)
    own = [
        e
        for e in events
        if _normalize(e["target_document_number"]) == key
        and e["scope"] == "whole_document"
    ]
    starts = sorted(
        {e["effective_date"] for e in own if e["event_kind"] == "effective"}
    )
    past = [value for value in starts if value <= as_of]
    start = max(past) if past else min(starts, default=None)
    ends = sorted(
        {
            e["effective_date"]
            for e in own
            if e["event_kind"] in {"repeal", "replace"}
            and (start is None or e["effective_date"] >= start)
        }
    )
    result = {
        **effect,
        "document_number": target,
        "effective_from": start,
        "effective_to": min(ends, default=None),
        "source_verified_at": max(
            (e["source_verified_at"] for e in events), default=None
        ),
        "legal_certification": False,
        "history_complete": False,
        "status_basis": "published_reviewed_events_only",
        "amends": [],
        "amended_by": [],
        "replaces": [],
        "replaced_by": [],
        "events": [],
    }
    for event in events:
        if event["effective_date"] <= as_of:
            for kind, outgoing, incoming in [
                ("amend", "amends", "amended_by"),
                ("replace", "replaces", "replaced_by"),
            ]:
                if event["event_kind"] == kind:
                    if _normalize(event["document_number"]) == key:
                        result[outgoing].append(event["target_document_number"])
                    if _normalize(event["target_document_number"]) == key:
                        result[incoming].append(event["document_number"])
        result["events"].append(
            {key: value for key, value in event.items() if key != "source_url"}
            | {
                "official_source": event["source_url"],
                "future_event": event["effective_date"] > as_of,
            }
        )
    for relation in ("amends", "amended_by", "replaces", "replaced_by"):
        result[relation] = sorted(set(result[relation]))
    return result
