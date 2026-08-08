from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, StringConstraints

from app.evaluation.gold_sidecar import GoldSidecar
from app.evaluation.legal_citations import parse_legal_citations
from app.evaluation.provenance import GitProvenance
from app.evaluation.retrieval_metrics import normalize_legal_identifier
from app.evaluation.schemas import GoldEvidence, GoldenCase


class AdjudicationDecision(BaseModel):
    """A human-review decision; automated discovery may only create pending decisions."""

    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "pending", "verified", "rejected", "corpus_missing", "ambiguous",
        "insufficient_evidence",
    ] = "pending"
    selected_candidate_id: str | None = None
    confidence: str = "unreviewed"
    notes: str = ""
    reviewer_identity: str | None = None
    reviewed_at_utc: str | None = None


StrictPositiveDocumentId = Annotated[StrictInt, Field(gt=0)]
StrictNonblankDocumentId = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class AdjudicationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    document_id: StrictPositiveDocumentId | StrictNonblankDocumentId | None = None
    document_number: str | None = None
    title: str | None = None
    source_url: str | None = None
    citation: str | None = None
    article: str | None = None
    clause: str | None = None
    text: str | None = None
    score: float | None = None
    discovery_method: str | None = None
    rank: int | None = None
    content_sha256: str | None = None
    anchor_match_method: str | None = None
    anchor_diagnostics: dict[str, Any] = Field(default_factory=dict)
    structural_citation: str | None = None
    structural_chunk_sha256: str | None = None
    required_level_supported: bool = False
    evidence_item_id: str | None = None


class AdjudicationQueueRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queue_row_id: str
    case_id: str
    evidence_item_id: str
    question: str
    question_type: str
    reference_answer_sha256: str
    reference_context_sha256: list[str] = Field(default_factory=list)
    reference_anchor_sha256: str | None = None
    parsed_citation_units: dict[str, str | None]
    citation_parse_status: Literal["parsed", "none"]
    source_evidence_status: str
    source_adjudication_provenance: dict[str, str | None]
    required_level: Literal["document", "article", "clause"]
    candidates: list[AdjudicationCandidate] = Field(default_factory=list)
    decision: AdjudicationDecision = Field(default_factory=AdjudicationDecision)


def canonical_sha256(data: Any) -> str:
    """Hash JSON data with stable key ordering and UTF-8 encoding."""
    payload = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if hasattr(value, "value"):
        return value.value
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def select_stratified_case_ids(
    cases: Sequence[GoldenCase],
    labels_by_case_id: Mapping[str, Sequence[GoldEvidence]],
    *,
    target_cases: int = 40,
    seed: str = "vietlex-p1-v1",
) -> list[str]:
    """Select answerable factoid and multi-hop cases reproducibly for review."""
    if not 30 <= target_cases <= 50:
        raise ValueError("target_cases must be between 30 and 50")

    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case IDs must be unique")

    strata: dict[str, list[GoldenCase]] = {"factoid": [], "multi-hop": []}
    for case in cases:
        if case.question_type not in strata or not case.answerable:
            continue
        labels = labels_by_case_id.get(case.case_id)
        if not labels:
            continue
        if any(label.case_id != case.case_id or not label.evidence_item_id for label in labels):
            raise ValueError(f"invalid evidence identity for case '{case.case_id}'")
        strata[case.question_type].append(case)

    quotas = {"factoid": target_cases // 2, "multi-hop": target_cases // 2}
    if target_cases % 2:
        quotas["factoid"] += 1
    for question_type, quota in quotas.items():
        if len(strata[question_type]) < quota:
            raise ValueError(f"insufficient eligible {question_type} cases for stratified selection")

    selected: list[GoldenCase] = []
    for question_type, quota in quotas.items():
        ranked = sorted(
            strata[question_type],
            key=lambda case: _rank_key(seed, question_type, case.case_id),
        )
        selected.extend(ranked[:quota])
    return [case.case_id for case in sorted(selected, key=lambda case: _rank_key(seed, "selected", case.case_id))]


def _rank_key(seed: str, stratum: str, case_id: str) -> tuple[str, str]:
    return (hashlib.sha256(f"{seed}:{stratum}:{case_id}".encode("utf-8")).hexdigest(), case_id)


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _require_sha256(value: str | None, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a full lowercase SHA-256 hash")
    return value


def _normalize_candidate(candidate: AdjudicationCandidate) -> AdjudicationCandidate:
    if not isinstance(candidate.candidate_id, str) or not candidate.candidate_id.strip():
        raise ValueError("candidate must have a stable nonblank candidate_id")
    document_id = candidate.document_id
    if isinstance(document_id, bool) or document_id is None:
        raise ValueError("candidate must have a resolved positive document_id")
    if isinstance(document_id, int):
        valid_document_id = document_id > 0
    elif isinstance(document_id, str):
        valid_document_id = bool(document_id.strip())
    else:
        valid_document_id = False
    if not valid_document_id:
        raise ValueError("candidate must have a resolved positive document_id")
    if not isinstance(candidate.document_number, str) or not candidate.document_number.strip():
        raise ValueError("candidate must have a nonblank document_number")
    if not isinstance(candidate.source_url, str) or not candidate.source_url.strip():
        raise ValueError("candidate must have a nonblank source_url")
    return candidate.model_copy(
        update={
            "candidate_id": candidate.candidate_id.strip(),
            "document_id": document_id.strip() if isinstance(document_id, str) else document_id,
            "document_number": candidate.document_number.strip(),
            "source_url": candidate.source_url.strip(),
        }
    )


def _normalize_citation_units(evidence: GoldEvidence) -> tuple[dict[str, str | None], Literal["parsed", "none"]]:
    supplied = {
        "document_number": _strip_or_none(evidence.document_number),
        "article": _strip_or_none(evidence.article),
        "clause": _strip_or_none(evidence.clause),
    }
    if not any(supplied.values()):
        return supplied, "none"
    parsed = parse_legal_citations(" ".join(value for value in supplied.values() if value))
    for item in parsed:
        unit = {
            "document_number": _strip_or_none(item.document_number),
            "article": _strip_or_none(item.article),
            "clause": _strip_or_none(item.clause),
        }
        if all(
            value is None or normalize_legal_identifier(value) == normalize_legal_identifier(unit[key])
            for key, value in supplied.items()
        ):
            return unit, "parsed"
    raise ValueError("citation units must satisfy the legal-citation contract")


def _strip_or_none(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def build_queue_payload(
    *,
    cases: Sequence[GoldenCase],
    sidecar: GoldSidecar,
    candidates_by_evidence_id: Mapping[str, Sequence[AdjudicationCandidate]],
    selected_case_ids: Sequence[str],
    dataset_sha256: str,
    corpus_revision: str,
    provenance: GitProvenance,
    command: Sequence[str],
    candidate_limit: int,
    selection_seed: str,
) -> dict[str, Any]:
    """Build a review queue without asserting that any candidate is verified."""
    if candidate_limit < 0:
        raise ValueError("candidate_limit must be non-negative")
    if len(selected_case_ids) != len(set(selected_case_ids)):
        raise ValueError("selected_case_ids must be unique")
    sidecar_sha256 = _require_sha256(sidecar.metadata.sidecar_sha256, "sidecar_sha256")
    case_by_id = {case.case_id: case for case in cases}
    if len(case_by_id) != len(cases):
        raise ValueError("case IDs must be unique")

    rows: list[dict[str, Any]] = []
    for case_id in selected_case_ids:
        case = case_by_id.get(case_id)
        labels = sidecar.labels_by_case_id.get(case_id)
        if case is None or not labels:
            raise ValueError(f"missing case or evidence labels for '{case_id}'")
        for evidence in labels:
            if evidence.case_id != case_id or not evidence.evidence_item_id:
                raise ValueError(f"invalid evidence identity for case '{case_id}'")
            if not case.reference_contexts:
                raise ValueError(f"missing reference context for case '{case_id}'")
            reference_answer_sha256 = _require_sha256(
                _text_sha256(case.reference_answer), "reference_answer_sha256"
            )
            reference_context_sha256 = [
                _require_sha256(_text_sha256(item), "reference_context_sha256")
                for item in case.reference_contexts
            ]
            reference_anchor_sha256 = _require_sha256(
                evidence.reference_anchor_hash or reference_context_sha256[0],
                "reference_anchor_sha256",
            )
            candidates = [
                _normalize_candidate(candidate)
                for candidate in list(candidates_by_evidence_id.get(evidence.evidence_item_id, ()))[:candidate_limit]
            ]
            citation_units, citation_parse_status = _normalize_citation_units(evidence)
            rows.append(
                AdjudicationQueueRow(
                    queue_row_id=canonical_sha256({"case_id": case_id, "evidence_item_id": evidence.evidence_item_id}),
                    case_id=case_id,
                    evidence_item_id=evidence.evidence_item_id,
                    question=case.question,
                    question_type=case.question_type,
                    reference_answer_sha256=reference_answer_sha256,
                    reference_context_sha256=reference_context_sha256,
                    reference_anchor_sha256=reference_anchor_sha256,
                    parsed_citation_units=citation_units,
                    citation_parse_status=citation_parse_status,
                    source_evidence_status=evidence.status.value,
                    source_adjudication_provenance={
                        "adjudication_queue_sha256": evidence.adjudication_queue_sha256,
                        "adjudication_decision_sha256": evidence.adjudication_decision_sha256,
                        "adjudication_candidate_id": evidence.adjudication_candidate_id,
                        "adjudication_confidence": evidence.adjudication_confidence,
                        "adjudication_reviewer_identity": evidence.adjudication_reviewer_identity,
                        "adjudicated_at_utc": evidence.adjudicated_at_utc,
                        "adjudication_notes_sha256": evidence.adjudication_notes_sha256,
                        "adjudication_notes": evidence.adjudication_notes,
                    },
                    required_level=evidence.required_level.value,
                    candidates=candidates,
                ).model_dump(mode="json")
            )

    return {
        "schema_version": "1.0.0",
        "dataset_sha256": dataset_sha256,
        "corpus_revision": corpus_revision,
        "provenance": {
            **provenance.model_dump(mode="json"),
            "sidecar_sha256": sidecar_sha256,
        },
        "command": list(command),
        "candidate_limit": candidate_limit,
        "selection_seed": selection_seed,
        "selected_case_ids": list(selected_case_ids),
        "rows": rows,
    }


def build_decision_template(queue_payload: Mapping[str, Any], queue_sha256: str) -> dict[str, Any]:
    """Create a review template that is bound to the exact queue preview."""
    if canonical_sha256(queue_payload) != queue_sha256:
        raise ValueError("queue_sha256 does not match queue_payload")
    rows = queue_payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("queue_payload missing rows")
    decisions: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping) or not row.get("queue_row_id") or not row.get("evidence_item_id"):
            raise ValueError("queue_payload contains a row without required identity")
        decisions.append({
            "queue_row_id": row["queue_row_id"],
            "evidence_item_id": row["evidence_item_id"],
            "decision": AdjudicationDecision().model_dump(mode="json"),
        })
    return {"schema_version": "1.0.0", "queue_sha256": queue_sha256, "decisions": decisions}


_DECISION_SCHEMA_VERSION = "1.0.0"
_SIDECAR_SCHEMA_VERSION = "2.0.0"
_NEGATIVE_DECISION_STATUSES = {
    "rejected", "corpus_missing", "ambiguous", "insufficient_evidence",
}
_CONFIDENCE_LEVELS = {"high", "medium", "low"}
_UTC_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$"
)


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return value


def _require_nonblank(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be nonblank")
    return value.strip()


def _normalized_utc_timestamp(value: Any) -> str:
    if not isinstance(value, str) or _UTC_TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise ValueError("reviewed_at_utc must be RFC3339 with an explicit zero UTC offset")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("reviewed_at_utc must be a valid RFC3339 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("reviewed_at_utc must use a zero UTC offset")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validated_queue_rows(queue_payload: Mapping[str, Any]) -> list[AdjudicationQueueRow]:
    rows = queue_payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("queue_payload missing rows")
    parsed_rows = [AdjudicationQueueRow.model_validate(row) for row in rows]
    queue_row_ids = [row.queue_row_id for row in parsed_rows]
    evidence_ids = [row.evidence_item_id for row in parsed_rows]
    if len(queue_row_ids) != len(set(queue_row_ids)):
        raise ValueError("queue_payload contains duplicate queue_row_id")
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("queue_payload contains duplicate evidence_item_id")
    return parsed_rows


def _validate_selected_candidate(
    row: AdjudicationQueueRow, decision: AdjudicationDecision
) -> AdjudicationCandidate | None:
    if decision.status != "verified":
        return None
    selected_id = _require_nonblank(decision.selected_candidate_id, "selected_candidate_id")
    matches = [item for item in row.candidates if item.candidate_id == selected_id]
    if len(matches) != 1:
        raise ValueError("selected candidate is unknown or duplicated for queue row")
    candidate = _normalize_candidate(matches[0])
    if candidate.evidence_item_id != row.evidence_item_id:
        raise ValueError("selected candidate evidence_item_id does not match queue evidence")
    if not _strip_or_none(candidate.anchor_match_method) or candidate.anchor_match_method == "none":
        raise ValueError("verified candidate requires a matched document anchor")
    if not candidate.required_level_supported:
        raise ValueError("verified candidate must have required_level_supported=True")
    if row.required_level in {"article", "clause"} and not _strip_or_none(candidate.article):
        raise ValueError("Article evidence requires a matched Article")
    if row.required_level == "clause" and not _strip_or_none(candidate.clause):
        raise ValueError("Clause evidence requires a matched Article and Clause")
    return candidate


def validate_decisions(
    queue_payload: Mapping[str, Any], decisions_payload: Mapping[str, Any], *, queue_sha256: str,
) -> list[AdjudicationDecision]:
    """Validate a complete, human-authored decision artifact against its immutable queue."""
    queue_sha256 = _require_sha256(queue_sha256, "queue_sha256")
    if canonical_sha256(queue_payload) != queue_sha256:
        raise ValueError("queue_sha256 does not match queue_payload")
    rows = _validated_queue_rows(queue_payload)
    decisions_payload = _require_mapping(decisions_payload, "decisions_payload")
    if decisions_payload.get("schema_version") != _DECISION_SCHEMA_VERSION:
        raise ValueError("unsupported decisions schema_version")
    if decisions_payload.get("queue_sha256") != queue_sha256:
        raise ValueError("decisions queue_sha256 does not match queue")
    entries = decisions_payload.get("decisions")
    if not isinstance(entries, list):
        raise ValueError("decisions_payload missing decisions")

    expected_by_row_id = {row.queue_row_id: row for row in rows}
    seen_row_ids: set[str] = set()
    seen_evidence_ids: set[str] = set()
    by_row_id: dict[str, AdjudicationDecision] = {}
    for entry in entries:
        entry = _require_mapping(entry, "decision entry")
        row_id = _require_nonblank(entry.get("queue_row_id"), "queue_row_id")
        evidence_id = _require_nonblank(entry.get("evidence_item_id"), "evidence_item_id")
        if row_id in seen_row_ids or evidence_id in seen_evidence_ids:
            raise ValueError("duplicate queue row or evidence ID in decisions")
        seen_row_ids.add(row_id)
        seen_evidence_ids.add(evidence_id)
        row = expected_by_row_id.get(row_id)
        if row is None or row.evidence_item_id != evidence_id:
            raise ValueError("decision queue row or evidence ID is missing or extra")
        raw_decision = _require_mapping(entry.get("decision"), "decision")
        try:
            decision = AdjudicationDecision.model_validate(raw_decision)
        except Exception as error:
            raise ValueError(f"invalid decision: {error}") from error
        if decision.status == "pending":
            raise ValueError("resolved decision status cannot be pending")
        reviewer_identity = _require_nonblank(decision.reviewer_identity, "reviewer_identity")
        reviewed_at_utc = _normalized_utc_timestamp(decision.reviewed_at_utc)
        confidence = _require_nonblank(decision.confidence, "confidence").casefold()
        if confidence not in _CONFIDENCE_LEVELS:
            raise ValueError("confidence must be high, medium, or low")
        notes = decision.notes.strip() if isinstance(decision.notes, str) else ""
        if (decision.status in _NEGATIVE_DECISION_STATUSES or confidence in {"medium", "low"}) and not notes:
            raise ValueError("notes are required for negative decisions and medium/low confidence")
        normalized = decision.model_copy(update={
            "reviewer_identity": reviewer_identity,
            "reviewed_at_utc": reviewed_at_utc,
            "confidence": confidence,
            "notes": notes,
            "selected_candidate_id": _strip_or_none(decision.selected_candidate_id),
        })
        _validate_selected_candidate(row, normalized)
        by_row_id[row_id] = normalized
    if set(by_row_id) != set(expected_by_row_id) or seen_evidence_ids != {
        row.evidence_item_id for row in rows
    }:
        raise ValueError("decisions must contain exactly one entry for every queue row and evidence ID")
    return [by_row_id[row.queue_row_id] for row in rows]


def _validate_source_sidecar(
    source_sidecar_payload: Mapping[str, Any], dataset_case_ids: Sequence[str],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    source = deepcopy(dict(_require_mapping(source_sidecar_payload, "source_sidecar_payload")))
    if source.get("schema_version") != _SIDECAR_SCHEMA_VERSION:
        raise ValueError("unsupported source sidecar schema_version")
    labels = source.get("labels")
    if not isinstance(labels, list):
        raise ValueError("source sidecar labels must be a list")
    labels_by_id: dict[str, dict[str, Any]] = {}
    case_ids: list[str] = []
    for raw_label in labels:
        label = _require_mapping(raw_label, "source sidecar label")
        evidence = GoldEvidence.model_validate(label)
        if evidence.evidence_item_id in labels_by_id:
            raise ValueError("source sidecar contains duplicate evidence_item_id")
        if not isinstance(label, dict):
            raise ValueError("source sidecar label must be a JSON object")
        labels_by_id[evidence.evidence_item_id] = label
        case_ids.append(evidence.case_id)
    actual_case_set = set(case_ids)
    expected_case_ids = list(dataset_case_ids)
    if len(expected_case_ids) != len(set(expected_case_ids)):
        raise ValueError("dataset_case_ids contains duplicate case ID")
    if actual_case_set != set(expected_case_ids):
        raise ValueError("source sidecar case ID set does not exactly match dataset_case_ids")
    if source.get("total_cases") != len(actual_case_set):
        raise ValueError("source sidecar total_cases does not match labels")
    if source.get("total_evidence_items") != len(labels):
        raise ValueError("source sidecar total_evidence_items does not match labels")
    return source, labels_by_id


def build_promotion_preview(
    *, queue_payload: Mapping[str, Any], queue_sha256: str,
    decisions_payload: Mapping[str, Any], source_sidecar_payload: Mapping[str, Any],
    source_sidecar_sha256: str, dataset_case_ids: Sequence[str],
    provenance: GitProvenance,
) -> dict[str, Any]:
    """Build a deterministic, non-persistent proposed sidecar from resolved decisions."""
    source_sidecar_sha256 = _require_sha256(source_sidecar_sha256, "source_sidecar_sha256")
    rows = _validated_queue_rows(queue_payload)
    decisions = validate_decisions(queue_payload, decisions_payload, queue_sha256=queue_sha256)
    source, labels_by_id = _validate_source_sidecar(source_sidecar_payload, dataset_case_ids)
    for row in rows:
        label = labels_by_id.get(row.evidence_item_id)
        if label is None or label.get("case_id") != row.case_id:
            raise ValueError("queue evidence does not match source sidecar evidence identity")

    before_counts = _status_counts(source["labels"])
    diffs: list[dict[str, Any]] = []
    decision_entries_by_row_id = {
        entry["queue_row_id"]: entry for entry in decisions_payload["decisions"]
    }
    for row, decision in zip(rows, decisions, strict=True):
        entry = decision_entries_by_row_id[row.queue_row_id]
        label = labels_by_id[row.evidence_item_id]
        before_status = label["status"]
        label["status"] = decision.status
        label["adjudication_queue_sha256"] = queue_sha256
        label["adjudication_decision_sha256"] = canonical_sha256(entry)
        label["adjudication_candidate_id"] = decision.selected_candidate_id
        label["adjudication_confidence"] = decision.confidence
        label["adjudication_reviewer_identity"] = decision.reviewer_identity
        label["adjudicated_at_utc"] = decision.reviewed_at_utc
        label["adjudication_notes_sha256"] = _text_sha256(decision.notes) if decision.notes else None
        label.pop("adjudication_notes", None)
        candidate = _validate_selected_candidate(row, decision)
        if candidate is not None:
            label.update({
                "document_id": candidate.document_id,
                "document_number": candidate.document_number,
                "article": candidate.article,
                "clause": candidate.clause,
            })
        diffs.append({
            "case_id": row.case_id,
            "evidence_item_id": row.evidence_item_id,
            "before_status": before_status,
            "after_status": decision.status,
            "selected_candidate_id": decision.selected_candidate_id,
        })
    # Legacy raw notes never survive into a promoted sidecar, including non-queued labels.
    for label in source["labels"]:
        label.pop("adjudication_notes", None)

    after_counts = _status_counts(source["labels"])
    selected_case_ids = queue_payload.get("selected_case_ids", [])
    if not isinstance(selected_case_ids, list) or len(selected_case_ids) != len(set(selected_case_ids)):
        raise ValueError("queue selected_case_ids must be a unique list")
    labels_by_case: dict[str, list[dict[str, Any]]] = {}
    for label in source["labels"]:
        labels_by_case.setdefault(label["case_id"], []).append(label)
    fully_verified_selected_case_count = sum(
        all(label["status"] == "verified" for label in labels_by_case.get(case_id, []) if label["required"])
        and any(label["required"] for label in labels_by_case.get(case_id, []))
        for case_id in selected_case_ids
    )
    negative_counts = {status: sum(1 for decision in decisions if decision.status == status) for status in sorted(_NEGATIVE_DECISION_STATUSES)}
    preview_core = {
        "schema_version": _DECISION_SCHEMA_VERSION,
        "source_hashes": {
            "queue_sha256": queue_sha256,
            "decisions_sha256": canonical_sha256(decisions_payload),
            "source_sidecar_sha256": source_sidecar_sha256,
        },
        "provenance": provenance.model_dump(mode="json"),
        "exact_case_set": {
            "matches": True,
            "dataset_case_ids": sorted(dataset_case_ids),
            "sidecar_case_ids": sorted(labels_by_case),
        },
        "status_counts": {"before": before_counts, "after": after_counts},
        "per_evidence_diff": diffs,
        "verified_evidence_count": after_counts.get("verified", 0),
        "fully_verified_selected_case_count": fully_verified_selected_case_count,
        "negative_counts": negative_counts,
        "proposed_sidecar": source,
    }
    return {**preview_core, "preview_sha256": canonical_sha256(preview_core)}


def _status_counts(labels: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for label in labels:
        status = label.get("status")
        if isinstance(status, str):
            counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))
