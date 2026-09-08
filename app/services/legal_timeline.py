"""Bounded date extraction, not a determination of legal effect or deadlines."""

from datetime import date
import re

_DATE = re.compile(
    r"(?<!\d)(?:(?P<iso>\d{4})-(?P<im>\d{1,2})-(?P<id>\d{1,2})|(?P<d>\d{1,2})[/.-](?P<m>\d{1,2})[/.-](?P<y>\d{4})|ngày\s+(?P<vd>\d{1,2})\s+tháng\s+(?P<vm>\d{1,2})\s+năm\s+(?P<vy>\d{4}))(?!\d)",
    re.I,
)
_RELATIVE = re.compile(
    r"\b(?:trong|sau|trước|kể từ)\s+\d{1,4}\s+(?:ngày|tháng|năm)\b", re.I
)


def build_legal_timeline(evidence: list[dict]) -> dict:
    if not 1 <= len(evidence) <= 10:
        raise ValueError("invalid_evidence_scope")
    ids = [item.get("evidence_id") for item in evidence]
    if any(not isinstance(i, str) or not i or len(i) > 100 for i in ids) or len(
        set(ids)
    ) != len(ids):
        raise ValueError("invalid_evidence_ids")
    texts = [
        str(item.get("excerpt") or item.get("original") or "") for item in evidence
    ]
    if sum(map(len, texts)) > 20_000:
        raise ValueError("evidence_scope_too_large")
    events, unresolved, covered = [], [], set()
    for evidence_id, text in zip(ids, texts):
        for match in _DATE.finditer(text):
            record = {
                "evidence_id": evidence_id,
                "quote": match.group(),
                "start": match.start(),
                "end": match.end(),
            }
            try:
                y, m, d = (
                    (match["iso"], match["im"], match["id"])
                    if match["iso"]
                    else (match["y"], match["m"], match["d"])
                    if match["y"]
                    else (match["vy"], match["vm"], match["vd"])
                )
                normalized = date(int(y), int(m), int(d)).isoformat()
            except ValueError:
                unresolved.append({**record, "reason": "invalid_calendar_date"})
                continue
            events.append(
                {
                    **record,
                    "date": normalized,
                    "precision": "day",
                    "kind": "stated_date",
                    "context": text[
                        max(0, match.start() - 120) : min(len(text), match.end() + 120)
                    ],
                }
            )
            covered.add(evidence_id)
        for match in _RELATIVE.finditer(text):
            unresolved.append(
                {
                    "evidence_id": evidence_id,
                    "quote": match.group(),
                    "start": match.start(),
                    "end": match.end(),
                    "reason": "relative_date_requires_trigger",
                }
            )
    # Reject excessive output rather than silently omit dates.
    if len(events) + len(unresolved) > 100:
        raise ValueError("timeline_scope_too_large")
    events.sort(key=lambda row: (row["date"], row["evidence_id"], row["start"]))
    return {
        "method": "explicit_date_extraction_v1",
        "legal_effect_status": "unverified",
        "timezone": "date_only_no_instant",
        "offset_unit": "unicode_codepoints",
        "events": events,
        "unresolved": unresolved,
        "coverage": {
            "sources_total": len(ids),
            "sources_with_dates": len(covered),
            "events": len(events),
            "unresolved": len(unresolved),
        },
    }
