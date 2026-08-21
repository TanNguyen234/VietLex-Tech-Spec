from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, StringConstraints

from app.evaluation.artifact_io import canonical_json_bytes
from app.evaluation.gold_sidecar import GoldSidecar
from app.evaluation.legal_citations import parse_legal_citations
from app.evaluation.provenance import GitProvenance
from app.evaluation.retrieval_metrics import normalize_legal_identifier
from app.evaluation.schemas import EvidenceStatus, GoldEvidence, GoldenCase


class AdjudicationMode(str, Enum):
    NORMAL = "normal"
    TARGETED_RE_ADJUDICATION = "targeted_re_adjudication"


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
    context_index: int
    citation_index: int
    reference_answer_sha256: str
    reference_context_sha256: list[str] = Field(default_factory=list)
    reference_anchor_sha256: str | None = None
    reference_anchor_legacy_hash: str | None = None
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


def artifact_sha256(data: Any) -> str:
    """Hash the exact canonical bytes emitted for an immutable JSON artifact."""
    return hashlib.sha256(canonical_json_bytes(data)).hexdigest()


def candidate_identity_sha256(
    document_id: int | str,
    document_number: str,
    source_url: str,
    content_sha256: str,
) -> str:
    """Bind a candidate to its exact durable document identity and content."""
    return canonical_sha256({
        "document_id": document_id,
        "document_number": document_number,
        "source_url": source_url,
        "content_sha256": content_sha256,
    })


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if hasattr(value, "value"):
        return value.value
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


TASK2_SELECTION_SEED = "vietlex-p2-v1"
TASK2_BATCH_SIZE = 20
TASK2_SELECTION_POLICY = (
    "round_robin_question_type_required_level_"
    "then_underrepresented_document_"
    "then_legal_type_then_sha256"
)

_CONSERVATIVE_DOC_NUMBER_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("/NĐ-CP", "Nghị định"),
    ("/ND-CP", "Nghị định"),
    ("/TTLT-", "Thông tư liên tịch"),
    ("/TT-", "Thông tư"),
    ("/QĐ-", "Quyết định"),
    ("/QD-", "Quyết định"),
    ("/NQ-", "Nghị quyết"),
    ("/CT-", "Chỉ thị"),
    ("/VBHN-", "Văn bản hợp nhất"),
)

_EXPLICIT_TEXT_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("Hiến pháp", "Hiến pháp"),
    ("Bộ luật", "Bộ luật"),
    ("Luật", "Luật"),
    ("Pháp lệnh", "Pháp lệnh"),
    ("Nghị định", "Nghị định"),
    ("Nghị quyết", "Nghị quyết"),
    ("Thông tư liên tịch", "Thông tư liên tịch"),
    ("Thông tư", "Thông tư"),
    ("Quyết định", "Quyết định"),
    ("Chỉ thị", "Chỉ thị"),
    ("Văn bản hợp nhất", "Văn bản hợp nhất"),
)


def infer_conservative_legal_type(
    *,
    document_number: str | None = None,
    text: str | None = None,
    known_legal_type: str | None = None,
) -> str:
    """Infer legal document type conservatively without any LLM or external calls.

    Does not assume /QH is Luật or /UBTVQH is Pháp lệnh without text keyword evidence.
    """
    if known_legal_type and isinstance(known_legal_type, str) and known_legal_type.strip():
        return known_legal_type.strip()
    if document_number and isinstance(document_number, str):
        num = document_number.upper().strip()
        for suffix, lt in _CONSERVATIVE_DOC_NUMBER_SUFFIXES:
            if suffix in num:
                return lt
    if text and isinstance(text, str):
        for keyword, lt in _EXPLICIT_TEXT_KEYWORDS:
            pattern = rf"\b{re.escape(keyword)}\b"
            if re.search(pattern, text, re.IGNORECASE):
                return lt
    return "unspecified"


# Alias for backward compatibility
infer_deterministic_legal_type = infer_conservative_legal_type


def is_case_eligible_for_adjudication(
    case: GoldenCase,
    labels: Sequence[GoldEvidence] | None,
) -> bool:
    """Return True if a case is answerable, has labels, and has at least one unresolved required evidence."""
    if not case.answerable or not labels:
        return False
    required = [label for label in labels if label.required]
    if not required:
        return False
    unverified_required = [
        label for label in required
        if label.status != "verified" and label.status != EvidenceStatus.VERIFIED
    ]
    return len(unverified_required) > 0


_REQUIRED_LEVEL_ORDER = {"document": 0, "article": 1, "clause": 2}


def _rank_key(seed: str, case_id: str) -> tuple[str, str]:
    digest = hashlib.sha256(f"{seed}\0{case_id}".encode("utf-8")).hexdigest()
    return (digest, case_id)


def _reference_context(case: GoldenCase, evidence: GoldEvidence) -> str:
    if not case.reference_contexts:
        raise ValueError(f"missing reference context for case '{case.case_id}'")
    if evidence.context_index < 0:
        raise ValueError("context_index must be zero or a positive 1-based index")
    index = evidence.context_index - 1 if evidence.context_index > 0 else 0
    if index >= len(case.reference_contexts):
        raise ValueError("context_index is out of range for reference contexts")
    return case.reference_contexts[index]


def compute_verified_diversity_counts(
    cases: Sequence[GoldenCase],
    labels_by_case_id: Mapping[str, Sequence[GoldEvidence]],
) -> tuple[dict[str, int], dict[str, int]]:
    """Compute representation counts (doc_counts, legal_type_counts) for verified evidence.

    Uses deterministic text evidence from case question, answer, and reference context
    for conservative legal type inference.
    """
    case_by_id = {case.case_id: case for case in cases}
    doc_counts: dict[str, int] = {}
    legal_type_counts: dict[str, int] = {}

    for case_id, labels in labels_by_case_id.items():
        case = case_by_id.get(case_id)
        for label in labels:
            if label.status == "verified" or label.status == EvidenceStatus.VERIFIED:
                doc_num = label.document_number.strip() if label.document_number and label.document_number.strip() else None
                if label.document_id is not None:
                    key = str(label.document_id)
                    doc_counts[key] = doc_counts.get(key, 0) + 1
                if doc_num:
                    doc_counts[doc_num] = doc_counts.get(doc_num, 0) + 1

                ref_text = ""
                if case and case.reference_contexts:
                    try:
                        ref_text = _reference_context(case, label)
                    except ValueError:
                        ref_text = ""

                text_for_ltype = ""
                if case:
                    full_case_text = "\n".join([case.question, case.reference_answer, *case.reference_contexts])
                    text_for_ltype = f"{case.question}\n{case.reference_answer}\n{ref_text}" if ref_text else full_case_text

                lt = infer_conservative_legal_type(document_number=doc_num, text=text_for_ltype)
                if lt != "unspecified":
                    legal_type_counts[lt] = legal_type_counts.get(lt, 0) + 1

    return doc_counts, legal_type_counts


def resolve_case_diversity_identity(
    case: GoldenCase,
    unresolved_required: Sequence[GoldEvidence],
    doc_counts: Mapping[str, int],
    legal_type_counts: Mapping[str, int],
) -> dict[str, Any]:
    """Deterministically determine the representative document & legal type for a case.

    Derives identity exclusively from unresolved (unverified) required evidence items.
    For multi-hop cases with multiple unresolved evidence items, selects the representative
    item that minimizes (document_representation, legal_type_representation, evidence_item_id).
    """
    full_case_text = "\n".join([case.question, case.reference_answer, *case.reference_contexts])
    if not unresolved_required:
        doc_num = None
        citations = parse_legal_citations(full_case_text)
        for cit in citations:
            if cit.document_number and cit.document_number.strip():
                doc_num = cit.document_number.strip()
                break
        ltype = infer_conservative_legal_type(document_number=doc_num, text=full_case_text)
        doc_key = doc_num if doc_num else f"case_{case.case_id}"
        return {
            "selection_evidence_item_id": None,
            "document_key": doc_key,
            "legal_type": ltype,
            "verified_document_representation_before": doc_counts.get(doc_key, 0),
            "verified_legal_type_representation_before": legal_type_counts.get(ltype, 0),
        }

    candidate_identities: list[tuple[tuple[int, int, str], dict[str, Any]]] = []
    for ev in unresolved_required:
        doc_id = str(ev.document_id) if ev.document_id is not None else None
        doc_num = ev.document_number.strip() if ev.document_number and ev.document_number.strip() else None

        ref_text = ""
        if case.reference_contexts:
            try:
                ref_text = _reference_context(case, ev)
            except ValueError:
                ref_text = ""

        if not doc_id and not doc_num:
            if ref_text:
                citations = parse_legal_citations(ref_text)
                for cit in citations:
                    if cit.document_number and cit.document_number.strip():
                        doc_num = cit.document_number.strip()
                        break
            if not doc_num:
                citations = parse_legal_citations(full_case_text)
                for cit in citations:
                    if cit.document_number and cit.document_number.strip():
                        doc_num = cit.document_number.strip()
                        break

        doc_key = doc_id if doc_id else (doc_num if doc_num else f"case_{case.case_id}")
        text_for_ltype = f"{case.question}\n{case.reference_answer}\n{ref_text}" if ref_text else full_case_text
        ltype = infer_conservative_legal_type(document_number=doc_num, text=text_for_ltype)

        doc_rep = doc_counts.get(doc_key, 0)
        ltype_rep = legal_type_counts.get(ltype, 0)
        ev_id = ev.evidence_item_id or ""

        candidate_identities.append((
            (doc_rep, ltype_rep, ev_id),
            {
                "selection_evidence_item_id": ev.evidence_item_id,
                "document_key": doc_key,
                "legal_type": ltype,
                "verified_document_representation_before": doc_rep,
                "verified_legal_type_representation_before": ltype_rep,
            },
        ))

    candidate_identities.sort(key=lambda item: item[0])
    return candidate_identities[0][1]


def select_stratified_case_ids(
    cases: Sequence[GoldenCase],
    labels_by_case_id: Mapping[str, Sequence[GoldEvidence]],
    *,
    target_cases: int = TASK2_BATCH_SIZE,
    seed: str = TASK2_SELECTION_SEED,
) -> list[str]:
    """Round-robin answerable cases with diversity prioritization across legal types and documents.

    Fails closed immediately if fewer than target_cases (exactly 20) eligible cases exist.
    """
    if target_cases != TASK2_BATCH_SIZE:
        raise ValueError(f"target_cases must be exactly {TASK2_BATCH_SIZE} for task 2 queue generation")

    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case IDs must be unique")

    # Compute representation counts for verified items across the sidecar
    doc_counts, legal_type_counts = compute_verified_diversity_counts(cases, labels_by_case_id)

    strata: dict[tuple[str, str], list[tuple[tuple[int, int, str, str], GoldenCase]]] = {}

    for case in cases:
        labels = labels_by_case_id.get(case.case_id)
        if not is_case_eligible_for_adjudication(case, labels):
            continue
        if any(label.case_id != case.case_id or not label.evidence_item_id for label in (labels or ())):
            raise ValueError(f"invalid evidence identity for case '{case.case_id}'")
        required = [label for label in labels if label.required]  # type: ignore[union-attr]
        unverified_required = [
            label for label in required
            if label.status != "verified" and label.status != EvidenceStatus.VERIFIED
        ]

        identity = resolve_case_diversity_identity(
            case=case,
            unresolved_required=unverified_required,
            doc_counts=doc_counts,
            legal_type_counts=legal_type_counts,
        )
        doc_rep = identity["verified_document_representation_before"]
        ltype_rep = identity["verified_legal_type_representation_before"]
        highest = max(
            (label.required_level.value for label in unverified_required),
            key=_REQUIRED_LEVEL_ORDER.__getitem__,
        )
        q_type = case.question_type

        stratum_key = (q_type, highest)
        digest, cid = _rank_key(seed, case.case_id)
        sort_tuple = (doc_rep, ltype_rep, digest, cid)
        strata.setdefault(stratum_key, []).append((sort_tuple, case))

    sorted_strata: dict[tuple[str, str], list[GoldenCase]] = {}
    for key in sorted(strata.keys()):
        items = strata[key]
        items.sort(key=lambda pair: pair[0])
        sorted_strata[key] = [pair[1] for pair in items]

    selected: list[str] = []
    offsets = {key: 0 for key in sorted_strata}
    while len(selected) < target_cases:
        added = False
        for key in sorted_strata:
            offset = offsets[key]
            if offset >= len(sorted_strata[key]):
                continue
            selected.append(sorted_strata[key][offset].case_id)
            offsets[key] += 1
            added = True
            if len(selected) == target_cases:
                break
        if not added:
            break

    if len(selected) < target_cases:
        raise ValueError(
            f"insufficient_eligible_cases: found {len(selected)} eligible cases, expected exactly {target_cases}"
        )

    return selected


def _eligible_strata(
    cases: Sequence[GoldenCase],
    labels_by_case_id: Mapping[str, Sequence[GoldEvidence]],
) -> dict[tuple[str, str], list[GoldenCase]]:
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case IDs must be unique")
    strata: dict[tuple[str, str], list[GoldenCase]] = {}
    for case in cases:
        labels = labels_by_case_id.get(case.case_id)
        if not labels or not case.answerable:
            continue
        if any(label.case_id != case.case_id or not label.evidence_item_id for label in labels):
            raise ValueError(f"invalid evidence identity for case '{case.case_id}'")
        required = [label for label in labels if label.required]
        if not required:
            continue
        highest = max(
            (label.required_level.value for label in required),
            key=_REQUIRED_LEVEL_ORDER.__getitem__,
        )
        strata.setdefault((case.question_type, highest), []).append(case)
    return strata


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_LEGACY_ANCHOR_HASH_PATTERN = re.compile(r"(?:[0-9a-f]{16}|[0-9a-f]{64})")


def _require_sha256(value: str | None, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a full lowercase SHA-256 hash")
    return value


def _legacy_anchor_hash(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or _LEGACY_ANCHOR_HASH_PATTERN.fullmatch(value) is None:
        raise ValueError("reference_anchor_legacy_hash must be 16 or 64 lowercase hex characters")
    return value


def _normalize_candidate(
    candidate: AdjudicationCandidate, expected_evidence_item_id: str
) -> AdjudicationCandidate:
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
    content_sha256 = _require_sha256(candidate.content_sha256, "candidate content_sha256")
    if isinstance(candidate.rank, bool) or not isinstance(candidate.rank, int) or candidate.rank <= 0:
        raise ValueError("candidate rank must be a positive integer")
    evidence_item_id = _require_nonblank(candidate.evidence_item_id, "candidate evidence_item_id")
    if evidence_item_id != expected_evidence_item_id:
        raise ValueError("candidate evidence_item_id does not match queue evidence")
    normalized_document_id = document_id.strip() if isinstance(document_id, str) else document_id
    normalized_document_number = candidate.document_number.strip()
    normalized_source_url = candidate.source_url.strip()
    candidate_id = candidate.candidate_id.strip()
    expected_candidate_id = candidate_identity_sha256(
        normalized_document_id,
        normalized_document_number,
        normalized_source_url,
        content_sha256,
    )
    if candidate_id != expected_candidate_id:
        raise ValueError("candidate_id does not match the candidate identity fields")
    return candidate.model_copy(update={
        "candidate_id": candidate_id,
        "evidence_item_id": evidence_item_id,
        "document_id": normalized_document_id,
        "document_number": normalized_document_number,
        "source_url": normalized_source_url,
        "content_sha256": content_sha256,
    })


def _normalize_citation_units(evidence: GoldEvidence) -> tuple[dict[str, str | None], Literal["parsed", "none"]]:
    clause_val = _strip_or_none(evidence.clause)
    clause_query = (
        f"Khoản {clause_val}"
        if (clause_val and not clause_val.lower().startswith("khoản"))
        else clause_val
    )
    supplied = {
        "document_number": _strip_or_none(evidence.document_number),
        "article": _strip_or_none(evidence.article),
        "clause": clause_val,
    }
    if not any(supplied.values()):
        return supplied, "none"
    citation_str = " ".join(
        v for v in [supplied["document_number"], supplied["article"], clause_query] if v
    )
    parsed = parse_legal_citations(citation_str)
    for item in parsed:
        unit = {
            "document_number": _strip_or_none(item.document_number),
            "article": _strip_or_none(item.article),
            "clause": _strip_or_none(item.clause),
        }
        doc_matches = (
            supplied["document_number"] is None
            or normalize_legal_identifier(supplied["document_number"]) == normalize_legal_identifier(unit["document_number"])
        )
        art_matches = (
            supplied["article"] is None
            or normalize_legal_identifier(supplied["article"]) == normalize_legal_identifier(unit["article"])
        )
        cl_matches = (
            supplied["clause"] is None
            or normalize_legal_identifier(supplied["clause"]) == normalize_legal_identifier(unit["clause"])
            or normalize_legal_identifier(f"Khoản {supplied['clause']}") == normalize_legal_identifier(unit["clause"])
        )
        if doc_matches and art_matches and cl_matches:
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
    selection_seed: str = TASK2_SELECTION_SEED,
    target_case_count: int = TASK2_BATCH_SIZE,
    mode: AdjudicationMode = AdjudicationMode.NORMAL,
    re_adjudication_reason: str | None = None,
    source_sidecar_path: str | None = None,
) -> dict[str, Any]:
    """Build a review queue without asserting that any candidate is verified."""
    if candidate_limit < 0:
        raise ValueError("candidate_limit must be non-negative")
    if not selected_case_ids:
        raise ValueError("selected_case_ids must not be empty")
    if len(selected_case_ids) != len(set(selected_case_ids)):
        raise ValueError("selected_case_ids must be unique")

    is_targeted = (
        mode == AdjudicationMode.TARGETED_RE_ADJUDICATION
        or (isinstance(mode, str) and mode == "targeted_re_adjudication")
    )
    if is_targeted:
        if target_case_count <= 0 or len(selected_case_ids) != target_case_count:
            raise ValueError(f"selected_case_ids count ({len(selected_case_ids)}) must match target_case_count ({target_case_count})")
        if not source_sidecar_path:
            raise ValueError("source_sidecar_path must be provided in targeted_re_adjudication mode")
        selection_policy = "explicit_targeted_case_ids"
    else:
        if target_case_count != TASK2_BATCH_SIZE:
            raise ValueError(f"target_case_count must be exactly {TASK2_BATCH_SIZE} for task 2 queue generation")
        if len(selected_case_ids) != TASK2_BATCH_SIZE:
            raise ValueError(f"selected_case_ids must contain exactly {TASK2_BATCH_SIZE} unique cases, got {len(selected_case_ids)}")
        selection_policy = TASK2_SELECTION_POLICY

    sidecar_sha256 = _require_sha256(sidecar.metadata.sidecar_sha256, "sidecar_sha256")
    case_by_id = {case.case_id: case for case in cases}
    if len(case_by_id) != len(cases):
        raise ValueError("case IDs must be unique")

    # Compute baseline verified representation counts across sidecar
    doc_counts, legal_type_counts = compute_verified_diversity_counts(cases, sidecar.labels_by_case_id)

    rows: list[dict[str, Any]] = []
    case_diagnostics: list[dict[str, Any]] = []
    selected_strata_counts: dict[str, int] = {}

    for case_id in selected_case_ids:
        case = case_by_id.get(case_id)
        labels = sidecar.labels_by_case_id.get(case_id)
        if case is None or not labels:
            raise ValueError(f"missing case or evidence labels for '{case_id}'")

        if is_targeted:
            target_evidence = [ev for ev in labels if ev.required]
            if not target_evidence:
                raise ValueError(f"selected case '{case_id}' has no required evidence to re-adjudicate")
        else:
            # Exclude already-verified evidence items from decision rows in normal mode
            target_evidence = [
                ev for ev in labels
                if ev.required and ev.status != EvidenceStatus.VERIFIED and ev.status != "verified"
            ]
            if not target_evidence:
                raise ValueError(f"selected case '{case_id}' has no unresolved required evidence")

        identity = resolve_case_diversity_identity(
            case=case,
            unresolved_required=target_evidence,
            doc_counts=doc_counts,
            legal_type_counts=legal_type_counts,
        )
        highest = max(
            (label.required_level.value for label in target_evidence),
            key=_REQUIRED_LEVEL_ORDER.__getitem__,
        )
        stratum_str = f"{case.question_type}|{highest}"
        selected_strata_counts[stratum_str] = selected_strata_counts.get(stratum_str, 0) + 1
        digest, _ = _rank_key(selection_seed, case.case_id)

        case_diagnostics.append({
            "case_id": case.case_id,
            "selection_evidence_item_id": identity["selection_evidence_item_id"],
            "document_key": identity["document_key"],
            "legal_type": identity["legal_type"],
            "verified_document_representation_before": identity["verified_document_representation_before"],
            "verified_legal_type_representation_before": identity["verified_legal_type_representation_before"],
            "selection_stratum": stratum_str,
            "tie_break_digest": digest,
            "selection_policy": selection_policy,
        })

        for evidence in target_evidence:
            if evidence.case_id != case_id or not evidence.evidence_item_id:
                raise ValueError(f"invalid evidence identity for case '{case_id}'")
            reference_answer_sha256 = _require_sha256(
                _text_sha256(case.reference_answer), "reference_answer_sha256"
            )
            reference_context_sha256 = [
                _require_sha256(_text_sha256(item), "reference_context_sha256")
                for item in case.reference_contexts
            ]
            reference_anchor_sha256 = _require_sha256(
                _text_sha256(_reference_context(case, evidence)), "reference_anchor_sha256"
            )
            candidates = [
                _normalize_candidate(candidate, evidence.evidence_item_id)
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
                    context_index=evidence.context_index,
                    citation_index=evidence.citation_index,
                    reference_answer_sha256=reference_answer_sha256,
                    reference_context_sha256=reference_context_sha256,
                    reference_anchor_sha256=reference_anchor_sha256,
                    reference_anchor_legacy_hash=_legacy_anchor_hash(
                        evidence.reference_anchor_hash
                    ),
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
                    },
                    required_level=evidence.required_level.value,
                    candidates=candidates,
                ).model_dump(mode="json")
            )

    eligible_count = sum(
        1 for c in cases
        if is_case_eligible_for_adjudication(c, sidecar.labels_by_case_id.get(c.case_id))
    )
    diagnostics: dict[str, Any] = {
        "eligible_case_count": eligible_count,
        "selected_strata": selected_strata_counts,
        "selection_policy": selection_policy,
        "case_diagnostics": case_diagnostics,
    }

    provenance_data = provenance.model_dump(mode="json")
    provenance_data["sidecar_sha256"] = sidecar_sha256
    if source_sidecar_path:
        provenance_data["source_sidecar_path"] = source_sidecar_path

    payload = {
        "schema_version": "1.0.0",
        "mode": mode.value if isinstance(mode, AdjudicationMode) else str(mode),
        "dataset_sha256": dataset_sha256,
        "corpus_revision": corpus_revision,
        "provenance": provenance_data,
        "command": list(command),
        "candidate_limit": candidate_limit,
        "selection_seed": selection_seed,
        "target_case_count": target_case_count,
        "selected_case_count": len(selected_case_ids),
        "provider_calls": 0,
        "queue_status": "READY_FOR_REVIEW",
        "selection_diagnostics": diagnostics,
        "selected_case_ids": list(selected_case_ids),
        "rows": rows,
    }
    if re_adjudication_reason:
        payload["re_adjudication_reason"] = re_adjudication_reason
    return payload


def format_queue_human_preview(queue_payload: Mapping[str, Any]) -> str:
    """Format a human-readable preview of the adjudication queue."""
    target_count = queue_payload.get("target_case_count", 20)
    selected_count = queue_payload.get("selected_case_count", 0)
    status = queue_payload.get("queue_status", "UNKNOWN")
    diagnostics = queue_payload.get("selection_diagnostics", {})
    selected_strata = diagnostics.get("selected_strata", {})
    selection_policy = diagnostics.get("selection_policy", TASK2_SELECTION_POLICY)
    rows = queue_payload.get("rows", [])

    case_diag_map = {
        cd.get("case_id"): cd.get("legal_type")
        for cd in diagnostics.get("case_diagnostics", [])
        if isinstance(cd, dict) and cd.get("case_id") and cd.get("legal_type")
    }

    legal_types: dict[str, int] = {}
    q_types: dict[str, int] = {}
    doc_numbers: set[str] = set()
    cases_seen: set[str] = set()

    for row in rows:
        cid = row.get("case_id", "")
        if cid not in cases_seen:
            cases_seen.add(cid)
            q_type = row.get("question_type", "unspecified")
            q_types[q_type] = q_types.get(q_type, 0) + 1
            units = row.get("parsed_citation_units", {})
            doc_num = units.get("document_number")
            if doc_num:
                doc_numbers.add(doc_num)
            ltype = case_diag_map.get(cid)
            if not ltype:
                ltype = infer_conservative_legal_type(document_number=doc_num, text=row.get("question", ""))
            legal_types[ltype] = legal_types.get(ltype, 0) + 1

    lines = [
        "# VIETLEX GOLD ADJUDICATION QUEUE PREVIEW",
        "",
        "> [!IMPORTANT]",
        "> **ADJUDICATION CANDIDATE QUEUE — FOR HUMAN REVIEW ONLY**",
        "> - This artifact is a proposed candidate queue for human legal adjudication.",
        "> - These are **NOT verified legal facts** and **NO evidence was auto-promoted**.",
        "> - **Human review is strictly required** before any candidate can be promoted to verified gold.",
        "> - This is data-quality preparation, NOT a benchmark result (no claims of recall or quality improvement).",
        "",
        "## Queue Summary",
        f"- **Queue Status**: `{status}`",
        f"- **Target Case Count**: {target_count}",
        f"- **Selected Case Count**: {selected_count}",
        f"- **Provider Calls**: {queue_payload.get('provider_calls', 0)} (Deterministic local discovery only)",
        "- **Adjudication State**: `PENDING_HUMAN` (All queued evidence items are unverified)",
        f"- **Selection Policy**: `{selection_policy}`",
        "",
        "## Diversity Breakdown",
        f"- **Distinct Legal Types**: {', '.join(f'{k}: {v}' for k, v in sorted(legal_types.items())) if legal_types else 'None'}",
        f"- **Question Types**: {', '.join(f'{k}: {v}' for k, v in sorted(q_types.items())) if q_types else 'None'}",
        f"- **Distinct Document Numbers**: {len(doc_numbers)}",
        f"- **Selected Strata**: {json.dumps(selected_strata, ensure_ascii=False)}",
        "",
        "## Queued Cases",
    ]

    case_rows: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        case_rows.setdefault(row.get("case_id", ""), []).append(row)

    for idx, (cid, c_rows) in enumerate(case_rows.items(), start=1):
        first_row = c_rows[0]
        q_text = first_row.get("question", "")
        q_type = first_row.get("question_type", "")
        req_lvl = first_row.get("required_level", "")
        units = first_row.get("parsed_citation_units", {})
        doc_num = units.get("document_number") or "unspecified"
        ltype = case_diag_map.get(cid)
        if not ltype:
            ltype = infer_conservative_legal_type(document_number=units.get("document_number"), text=q_text)
        cand_count = sum(len(r.get("candidates", [])) for r in c_rows)
        lines.extend([
            f"### {idx}. Case `{cid}` — `{q_type}` ({req_lvl})",
            f"- **Question**: {q_text}",
            f"- **Legal Type**: {ltype} | **Document**: {doc_num}",
            "- **Status**: `PENDING_HUMAN` (Unverified)",
            f"- **Evidence Items**: {len(c_rows)} | **Candidates Discovered**: {cand_count}",
        ])

    return "\n".join(lines)


def build_decision_template(queue_payload: Mapping[str, Any], queue_sha256: str) -> dict[str, Any]:
    """Create a review template that is bound to the exact queue preview."""
    if artifact_sha256(queue_payload) != queue_sha256:
        raise ValueError("queue_sha256 artifact hash does not match queue_payload bytes")
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
    if queue_payload.get("schema_version") != _DECISION_SCHEMA_VERSION:
        raise ValueError("unsupported queue schema_version")
    is_targeted = (
        queue_payload.get("mode") == "targeted_re_adjudication"
        or queue_payload.get("mode") == AdjudicationMode.TARGETED_RE_ADJUDICATION.value
    )
    target_case_count = queue_payload.get("target_case_count")
    if is_targeted:
        if (
            isinstance(target_case_count, bool)
            or not isinstance(target_case_count, int)
            or target_case_count <= 0
        ):
            raise ValueError("queue target_case_count must be a positive integer in targeted mode")
    else:
        if (
            isinstance(target_case_count, bool)
            or not isinstance(target_case_count, int)
            or (target_case_count not in (20,) and not (30 <= target_case_count <= 50))
        ):
            raise ValueError("queue target_case_count must be 20 or between 30 and 50")
    selected_case_count = queue_payload.get("selected_case_count")
    if isinstance(selected_case_count, bool) or not isinstance(selected_case_count, int):
        raise ValueError("queue selected_case_count must be an integer")
    selected_case_ids = queue_payload.get("selected_case_ids")
    if not isinstance(selected_case_ids, list):
        raise ValueError("queue selected_case_ids must be a list")
    if any(not isinstance(case_id, str) or not case_id.strip() for case_id in selected_case_ids):
        raise ValueError("queue selected_case_ids must contain nonblank strings")
    if len(selected_case_ids) != len(set(selected_case_ids)):
        raise ValueError("queue selected_case_ids must be unique")
    if selected_case_count != len(selected_case_ids):
        raise ValueError("queue selected_case_count must equal selected_case_ids length")
    if selected_case_count > target_case_count:
        raise ValueError("queue selected_case_count cannot exceed target_case_count")
    expected_status = (
        "READY_FOR_REVIEW"
        if (selected_case_count == target_case_count and (target_case_count == 20 or 30 <= target_case_count <= 50 or is_targeted))
        else "BLOCKED_INSUFFICIENT_ELIGIBLE_CASES"
    )
    if queue_payload.get("queue_status") != expected_status:
        raise ValueError("queue_status does not match selected_case_count")
    if queue_payload.get("provider_calls") != 0:
        raise ValueError("queue provider_calls must equal 0")

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
    row_case_ids = {row.case_id for row in parsed_rows}
    if row_case_ids != set(selected_case_ids):
        raise ValueError("queue selected case IDs and row case IDs must match exactly")
    identity_fields = (
        "candidate_id", "evidence_item_id", "document_id", "document_number",
        "source_url", "content_sha256", "rank",
    )
    for raw_row, row in zip(rows, parsed_rows, strict=True):
        raw_candidates = _require_mapping(raw_row, "queue row").get("candidates")
        if not isinstance(raw_candidates, list) or len(raw_candidates) != len(row.candidates):
            raise ValueError("loaded queue candidates must be a canonical list")
        for raw_candidate, candidate in zip(raw_candidates, row.candidates, strict=True):
            raw_candidate = _require_mapping(raw_candidate, "queue candidate")
            if any(
                raw_candidate.get(field_name) != getattr(candidate, field_name)
                for field_name in identity_fields
            ):
                raise ValueError("loaded queue candidate identity fields must be noncanonical")
            normalized = _normalize_candidate(candidate, row.evidence_item_id)
            if normalized.model_dump(mode="json") != candidate.model_dump(mode="json"):
                raise ValueError("loaded queue candidate identity fields must be noncanonical")
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
    candidate = _normalize_candidate(matches[0], row.evidence_item_id)
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
    if row.required_level in {"article", "clause"}:
        _require_sha256(
            candidate.structural_chunk_sha256,
            "verified candidate structural_chunk_sha256",
        )
    return candidate


def validate_decisions(
    queue_payload: Mapping[str, Any], decisions_payload: Mapping[str, Any], *, queue_sha256: str,
) -> list[AdjudicationDecision]:
    """Validate a complete, human-authored decision artifact against its immutable queue."""
    queue_sha256 = _require_sha256(queue_sha256, "queue_sha256")
    if artifact_sha256(queue_payload) != queue_sha256:
        raise ValueError("queue_sha256 artifact hash does not match queue_payload bytes")
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
        if "adjudication_notes" in label:
            raise ValueError("source sidecar contains legacy raw adjudication_notes")
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
    decisions_payload: Mapping[str, Any], decisions_sha256: str,
    source_sidecar_payload: Mapping[str, Any],
    source_sidecar_sha256: str, dataset_case_ids: Sequence[str],
    provenance: GitProvenance,
) -> dict[str, Any]:
    """Build a deterministic, non-persistent proposed sidecar from resolved decisions."""
    source_sidecar_sha256 = _require_sha256(source_sidecar_sha256, "source_sidecar_sha256")
    decisions_sha256 = _require_sha256(decisions_sha256, "decisions_sha256")
    if artifact_sha256(decisions_payload) != decisions_sha256:
        raise ValueError("decisions artifact SHA-256 does not match decisions_payload bytes")
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
    is_targeted = (
        queue_payload.get("mode") == "targeted_re_adjudication"
        or queue_payload.get("mode") == AdjudicationMode.TARGETED_RE_ADJUDICATION.value
    )

    preview_core = {
        "schema_version": _DECISION_SCHEMA_VERSION,
        "source_hashes": {
            "queue_sha256": queue_sha256,
            "decisions_sha256": decisions_sha256,
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
    if is_targeted:
        preview_core["mode"] = "targeted_re_adjudication"
        parent_ver = None
        source_meta = source.get("metadata")
        if isinstance(source_meta, dict):
            parent_ver = source_meta.get("gold_version")
        if parent_ver is None:
            source_path = str(queue_payload.get("provenance", {}).get("source_sidecar_path", ""))
            match = re.search(r"curated-v(\d+)", source_path)
            if match:
                parent_ver = int(match.group(1))
            else:
                parent_ver = 4
        gold_ver = parent_ver + 1
        preview_core["parent_lineage"] = {
            "gold_version": gold_ver,
            "parent_gold_version": parent_ver,
            "parent_sidecar_sha256": source_sidecar_sha256,
        }
    return {**preview_core, "preview_sha256": canonical_sha256(preview_core)}


def _status_counts(labels: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for label in labels:
        status = label.get("status")
        if isinstance(status, str):
            counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def validate_preview_approval(
    preview_payload: Mapping[str, Any], approved_preview_sha256: str,
) -> None:
    """Fail closed unless explicit approval names the exact immutable preview."""
    preview = _validate_promotion_preview(preview_payload)
    declared_hash = _require_sha256(preview.get("preview_sha256"), "preview_sha256")
    approved_hash = _require_sha256(approved_preview_sha256, "approved_preview_sha256")
    recomputed_hash = canonical_sha256({
        key: value for key, value in preview.items() if key != "preview_sha256"
    })
    if declared_hash != recomputed_hash:
        raise ValueError("preview_sha256 does not match the canonical preview payload")
    if approved_hash != declared_hash:
        raise ValueError("approved_preview_sha256 does not match preview_sha256")


def build_promotion_summary(preview_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Build a non-sensitive, deterministic handoff summary for an approved preview."""
    preview = _validate_promotion_preview(preview_payload)
    declared_hash = _require_sha256(preview.get("preview_sha256"), "preview_sha256")
    recomputed_hash = canonical_sha256({
        key: value for key, value in preview.items() if key != "preview_sha256"
    })
    if declared_hash != recomputed_hash:
        raise ValueError("preview_sha256 does not match the canonical preview payload")
    fully_verified_case_count = preview["fully_verified_selected_case_count"]
    is_targeted = preview.get("mode") == "targeted_re_adjudication"
    summary = {
        "preview_sha256": declared_hash,
        "source_hashes": deepcopy(dict(preview["source_hashes"])),
        "provenance": deepcopy(dict(preview["provenance"])),
        "status_counts": deepcopy(dict(preview["status_counts"])),
        "per_evidence_diff": deepcopy(list(preview["per_evidence_diff"])),
        "verified_evidence_count": preview["verified_evidence_count"],
        "fully_verified_selected_case_count": fully_verified_case_count,
        "negative_counts": deepcopy(dict(preview["negative_counts"])),
        "proposed_sidecar_sha256": canonical_sha256(preview["proposed_sidecar"]),
        "status": (
            "READY_FOR_P2"
            if (fully_verified_case_count == 20 or 30 <= fully_verified_case_count <= 50 or is_targeted)
            else "BLOCKED_INSUFFICIENT_VERIFIED_CASES"
        ),
    }
    if "parent_lineage" in preview:
        summary["parent_lineage"] = deepcopy(dict(preview["parent_lineage"]))
    return summary


def _validate_promotion_preview(preview_payload: Mapping[str, Any]) -> Mapping[str, Any]:
    preview = _require_mapping(preview_payload, "preview_payload")
    for field_name in (
        "schema_version", "preview_sha256", "source_hashes", "provenance",
        "exact_case_set", "status_counts", "per_evidence_diff",
        "verified_evidence_count", "fully_verified_selected_case_count",
        "negative_counts", "proposed_sidecar",
    ):
        if field_name not in preview:
            raise ValueError(f"preview is missing required {field_name}")
    if preview["schema_version"] != _DECISION_SCHEMA_VERSION:
        raise ValueError("unsupported preview schema_version")
    source_hashes = _require_mapping(preview["source_hashes"], "source_hashes")
    for field_name in ("queue_sha256", "decisions_sha256", "source_sidecar_sha256"):
        _require_sha256(source_hashes.get(field_name), f"source_hashes.{field_name}")
    _require_mapping(preview["provenance"], "provenance")
    exact_case_set = _require_mapping(preview["exact_case_set"], "exact_case_set")
    if exact_case_set.get("matches") is not True:
        raise ValueError("exact_case_set.matches must be true")
    dataset_case_ids = _validate_case_id_list(
        exact_case_set.get("dataset_case_ids"), "exact_case_set.dataset_case_ids"
    )
    sidecar_case_ids = _validate_case_id_list(
        exact_case_set.get("sidecar_case_ids"), "exact_case_set.sidecar_case_ids"
    )
    if dataset_case_ids != sidecar_case_ids:
        raise ValueError("exact_case_set dataset and sidecar case IDs must match")
    status_counts = _require_mapping(preview["status_counts"], "status_counts")
    for field_name in ("before", "after"):
        _validate_count_mapping(status_counts.get(field_name), f"status_counts.{field_name}")
    diffs = preview["per_evidence_diff"]
    if not isinstance(diffs, list):
        raise ValueError("per_evidence_diff must be a list")
    for item in diffs:
        diff = _require_mapping(item, "per_evidence_diff entry")
        for field_name in ("case_id", "evidence_item_id", "before_status", "after_status"):
            _require_nonblank(diff.get(field_name), f"per_evidence_diff.{field_name}")
        if "notes" in diff or "adjudication_notes" in diff:
            raise ValueError("per_evidence_diff must not contain raw decision notes")
    _require_nonnegative_int(preview["verified_evidence_count"], "verified_evidence_count")
    _require_nonnegative_int(
        preview["fully_verified_selected_case_count"], "fully_verified_selected_case_count"
    )
    negative_counts = _validate_count_mapping(preview["negative_counts"], "negative_counts")
    if set(negative_counts) != _NEGATIVE_DECISION_STATUSES:
        raise ValueError("negative_counts must contain every negative decision status")
    proposed_sidecar = _require_mapping(preview["proposed_sidecar"], "proposed_sidecar")
    if _contains_legacy_raw_notes(proposed_sidecar):
        raise ValueError("proposed_sidecar contains legacy raw adjudication_notes")
    labels = proposed_sidecar.get("labels")
    if not isinstance(labels, list):
        raise ValueError("proposed_sidecar.labels must be a list")
    for label in labels:
        _require_mapping(label, "proposed_sidecar label")
    return preview


def _validate_count_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    counts = _require_mapping(value, field_name)
    for name, count in counts.items():
        _require_nonblank(name, f"{field_name} key")
        _require_nonnegative_int(count, f"{field_name}.{name}")
    return counts


def _require_nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _validate_case_id_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    if any(not isinstance(case_id, str) or not case_id.strip() for case_id in value):
        raise ValueError(f"{field_name} must contain nonblank case IDs")
    if len(value) != len(set(value)) or value != sorted(value):
        raise ValueError(f"{field_name} must be sorted and unique")
    return value


def _contains_legacy_raw_notes(value: Any) -> bool:
    if isinstance(value, Mapping):
        return "adjudication_notes" in value or any(
            _contains_legacy_raw_notes(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_legacy_raw_notes(item) for item in value)
    return False
