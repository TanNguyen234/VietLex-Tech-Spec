from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.evaluation.gold_sidecar import GoldSidecar
from app.evaluation.provenance import GitProvenance
from app.evaluation.schemas import GoldEvidence, GoldenCase


class AdjudicationDecision(BaseModel):
    """A human-review decision; automated discovery may only create pending decisions."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["pending", "rejected", "corpus_missing", "insufficient_evidence"] = "pending"
    selected_candidate_id: str | None = None
    confidence: str = "unreviewed"
    notes: str = ""
    reviewer_identity: str | None = None
    reviewed_at_utc: str | None = None


class AdjudicationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    document_id: int | str | None = None
    document_number: str | None = None
    title: str | None = None
    source_url: str | None = None
    citation: str | None = None
    article: str | None = None
    clause: str | None = None
    text: str | None = None
    score: float | None = None
    discovery_method: str | None = None


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


def _validate_candidate(candidate: AdjudicationCandidate) -> None:
    if not isinstance(candidate.candidate_id, str) or not candidate.candidate_id.strip():
        raise ValueError("candidate must have a stable nonblank candidate_id")
    document_id = candidate.document_id
    if isinstance(document_id, bool) or document_id is None:
        raise ValueError("candidate must have a resolved positive document_id")
    if isinstance(document_id, int):
        valid_document_id = document_id > 0
    elif isinstance(document_id, str):
        valid_document_id = document_id.isdecimal() and int(document_id) > 0
    else:
        valid_document_id = False
    if not valid_document_id:
        raise ValueError("candidate must have a resolved positive document_id")
    if not isinstance(candidate.document_number, str) or not candidate.document_number.strip():
        raise ValueError("candidate must have a nonblank document_number")
    if not isinstance(candidate.source_url, str) or not candidate.source_url.strip():
        raise ValueError("candidate must have a nonblank source_url")


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
            candidates = list(candidates_by_evidence_id.get(evidence.evidence_item_id, ()))[:candidate_limit]
            for candidate in candidates:
                _validate_candidate(candidate)
            citation_units = {
                "document_number": evidence.document_number,
                "article": evidence.article,
                "clause": evidence.clause,
            }
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
                    citation_parse_status=("parsed" if any(citation_units.values()) else "none"),
                    source_evidence_status=evidence.status.value,
                    source_adjudication_provenance={
                        "adjudication_queue_sha256": evidence.adjudication_queue_sha256,
                        "adjudication_decision_sha256": evidence.adjudication_decision_sha256,
                        "adjudication_candidate_id": evidence.adjudication_candidate_id,
                        "adjudication_confidence": evidence.adjudication_confidence,
                        "adjudication_reviewer_identity": evidence.adjudication_reviewer_identity,
                        "adjudicated_at_utc": evidence.adjudicated_at_utc,
                        "adjudication_notes": evidence.adjudication_notes,
                    },
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
