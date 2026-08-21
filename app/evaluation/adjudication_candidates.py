"""Bounded, read-only local candidates for human gold-evidence adjudication."""

from __future__ import annotations

import hashlib
import re
from typing import Mapping, Sequence

from audit_golden_dataset import (
    check_anchor_match,
    check_normalized_anchor_match,
    norm_text,
)
from app.evaluation.adjudication import AdjudicationCandidate, candidate_identity_sha256
from app.evaluation.legal_citations import parse_legal_citations
from app.evaluation.schemas import GoldEvidence, GoldenCase, RequiredLevel
from app.ingestion.content_store import ContentStore
from app.ingestion.legal_fts import LegalFtsIndex
from app.ingestion.legal_text import EvidenceChunk, chunk_document


_ANCHOR_SCAN_BATCH_SIZE = 256
_ANCHOR_SCAN_TIERS = (
    ("primary_normative", ("Hiến pháp", "Luật", "Pháp lệnh")),
    (
        "secondary_normative",
        (
            "Nghị định",
            "Nghị quyết",
            "Thông tư",
            "Thông tư liên tịch",
            "Văn bản hợp nhất",
            "Quy định",
            "Quy chế",
        ),
    ),
)


def discover_adjudication_candidates(
    *,
    cases_by_id: Mapping[str, GoldenCase],
    labels_by_case_id: Mapping[str, Sequence[GoldEvidence]],
    selected_case_ids: Sequence[str],
    content_store: ContentStore,
    fts_index: LegalFtsIndex,
    candidate_limit: int = 12,
) -> dict[str, list[AdjudicationCandidate]]:
    """Discover candidates without changing corpus data or evidence status."""
    if candidate_limit <= 0:
        raise ValueError("candidate_limit must be positive")
    if len(selected_case_ids) != len(set(selected_case_ids)):
        raise ValueError("selected_case_ids must be unique")

    anchor_scan_ids, anchor_scan_tiers = _discover_anchor_scan_ids(
        cases_by_id=cases_by_id,
        labels_by_case_id=labels_by_case_id,
        selected_case_ids=selected_case_ids,
        content_store=content_store,
        candidate_limit=candidate_limit,
    )
    result: dict[str, list[AdjudicationCandidate]] = {}
    for case_id in selected_case_ids:
        case = cases_by_id.get(case_id)
        if case is None:
            raise ValueError(f"unknown selected case '{case_id}'")
        labels = labels_by_case_id.get(case_id)
        if not labels:
            raise ValueError(f"missing labels for selected case '{case_id}'")
        if any(label.case_id != case_id for label in labels):
            raise ValueError(f"invalid evidence identity for selected case '{case_id}'")

        source_ids = _source_document_ids(labels, case_id)
        query = _case_query(case)
        fts_ids = fts_index.search(query, limit=candidate_limit)
        document_ids_by_evidence: dict[str, list[int]] = {}
        case_document_ids: list[int] = []
        seen_case_ids: set[int] = set()
        for evidence in labels:
            scan_ids = anchor_scan_ids.get(evidence.evidence_item_id, ())
            document_ids = _stable_bounded_ids(
                source_ids,
                [*scan_ids, *fts_ids],
                candidate_limit,
            )
            document_ids_by_evidence[evidence.evidence_item_id] = document_ids
            for document_id in document_ids:
                if document_id not in seen_case_ids:
                    seen_case_ids.add(document_id)
                    case_document_ids.append(document_id)
        documents = content_store.get_many(case_document_ids)
        missing_ids = [
            document_id
            for document_id in case_document_ids
            if document_id not in documents
        ]
        if missing_ids:
            raise ValueError(
                f"missing retrieved documents for selected case '{case_id}': {missing_ids}"
            )

        chunks_by_id: dict[int, list[EvidenceChunk]] = {}
        candidates: list[AdjudicationCandidate] = []
        source_set = set(source_ids)
        for evidence in labels:
            document_ids = document_ids_by_evidence[evidence.evidence_item_id]
            scan_set = set(anchor_scan_ids.get(evidence.evidence_item_id, ()))
            for rank, document_id in enumerate(document_ids, start=1):
                document = documents[document_id]
                metadata = document.metadata
                _validate_document(document_id, metadata, document)
                matched, anchor_method, diagnostics = check_anchor_match(
                    _reference_anchor(case, evidence), document.content
                )
                method = (
                    "source_sidecar_document_id" if document_id in source_set else "fts"
                )
                if document_id in scan_set and document_id not in source_set:
                    method = "normative_anchor_scan"
                article = clause = structural_citation = structural_chunk_sha256 = None
                required_supported = False
                citation = metadata.document_number
                if matched:
                    if method == "normative_anchor_scan":
                        diagnostics = {
                            **diagnostics,
                            "anchor_scan_tier": anchor_scan_tiers[
                                evidence.evidence_item_id
                            ],
                            "corpus_search_complete": False,
                        }
                    chunks = chunks_by_id.get(document_id)
                    if chunks is None:
                        chunks = chunk_document(
                            metadata, document.content, max_tokens=220, overlap_tokens=24
                        )
                        chunks_by_id[document_id] = chunks
                    structural = _first_structural_anchor(case, evidence, chunks)
                    if structural is not None:
                        article = structural.article
                        clause = structural.clause
                        structural_citation = structural.citation
                        structural_chunk_sha256 = _sha256(structural.text)
                        citation = structural.citation
                    required_supported = _supports_required_level(evidence, structural)
                else:
                    anchor_method = "none"
                    diagnostics = {}
                candidates.append(
                    AdjudicationCandidate(
                        candidate_id=candidate_identity_sha256(
                            document_id,
                            metadata.document_number,
                            metadata.source_url,
                            document.content_sha256,
                        ),
                        evidence_item_id=evidence.evidence_item_id,
                        document_id=document_id,
                        document_number=metadata.document_number,
                        title=metadata.title,
                        source_url=metadata.source_url,
                        citation=citation,
                        article=article,
                        clause=clause,
                        text=None,
                        discovery_method=method,
                        rank=rank,
                        content_sha256=document.content_sha256,
                        anchor_match_method=anchor_method,
                        anchor_diagnostics=diagnostics,
                        structural_citation=structural_citation,
                        structural_chunk_sha256=structural_chunk_sha256,
                        required_level_supported=required_supported,
                    )
                )
        result[case_id] = candidates
    return result


def _discover_anchor_scan_ids(
    *,
    cases_by_id: Mapping[str, GoldenCase],
    labels_by_case_id: Mapping[str, Sequence[GoldEvidence]],
    selected_case_ids: Sequence[str],
    content_store: ContentStore,
    candidate_limit: int,
) -> tuple[dict[str, list[int]], dict[str, str]]:
    iterator = getattr(content_store, "iter_document_ids_by_legal_types", None)
    if not callable(iterator):
        return {}, {}

    normalized_anchors: dict[str, str] = {}
    for case_id in selected_case_ids:
        case = cases_by_id.get(case_id)
        if case is None:
            raise ValueError(f"unknown selected case '{case_id}'")
        labels = labels_by_case_id.get(case_id)
        if not labels:
            raise ValueError(f"missing labels for selected case '{case_id}'")
        if any(label.case_id != case_id for label in labels):
            raise ValueError(f"invalid evidence identity for selected case '{case_id}'")
        for evidence in labels:
            if evidence.document_id is not None or (
                isinstance(evidence.document_number, str)
                and evidence.document_number.strip()
            ):
                continue
            if evidence.evidence_item_id in normalized_anchors:
                raise ValueError("evidence_item_id must be unique")
            normalized_anchor = norm_text(_reference_anchor(case, evidence))
            if not normalized_anchor:
                raise ValueError("reference anchor must be nonblank")
            normalized_anchors[evidence.evidence_item_id] = normalized_anchor

    matches = {evidence_id: [] for evidence_id in normalized_anchors}
    tiers_by_evidence: dict[str, str] = {}
    unresolved = set(normalized_anchors)
    for tier_name, legal_types in _ANCHOR_SCAN_TIERS:
        if not unresolved:
            break
        active = set(unresolved)
        after_id = -1
        while True:
            document_ids = iterator(
                legal_types,
                after_id=after_id,
                limit=_ANCHOR_SCAN_BATCH_SIZE,
            )
            if not document_ids:
                break
            if (
                document_ids != sorted(set(document_ids))
                or any(
                    isinstance(document_id, bool)
                    or not isinstance(document_id, int)
                    or document_id <= after_id
                    for document_id in document_ids
                )
            ):
                raise ValueError("invalid corpus document identity")
            documents = content_store.get_many(document_ids)
            missing_ids = [
                document_id
                for document_id in document_ids
                if document_id not in documents
            ]
            if missing_ids:
                raise ValueError(f"missing scanned documents: {missing_ids}")
            for document_id in document_ids:
                document = documents[document_id]
                _validate_document(document_id, document.metadata, document)
                normalized_content = norm_text(document.content)
                for evidence_id in active:
                    if len(matches[evidence_id]) >= candidate_limit:
                        continue
                    matched, _, _ = check_normalized_anchor_match(
                        normalized_anchors[evidence_id],
                        normalized_content,
                    )
                    if matched:
                        matches[evidence_id].append(document_id)
            after_id = document_ids[-1]
            if all(len(matches[evidence_id]) >= candidate_limit for evidence_id in active):
                break
        matched_in_tier = {
            evidence_id for evidence_id in active if matches[evidence_id]
        }
        for evidence_id in matched_in_tier:
            tiers_by_evidence[evidence_id] = tier_name
        unresolved.difference_update(matched_in_tier)

    return (
        {
            evidence_id: document_ids
            for evidence_id, document_ids in matches.items()
            if document_ids
        },
        tiers_by_evidence,
    )


def _source_document_ids(labels: Sequence[GoldEvidence], case_id: str) -> list[int]:
    document_ids: list[int] = []
    for label in labels:
        if label.document_id is None:
            continue
        if isinstance(label.document_id, bool) or not isinstance(label.document_id, int) or label.document_id <= 0:
            raise ValueError(f"invalid corpus document identity for selected case '{case_id}'")
        document_ids.append(label.document_id)
    return document_ids


def _case_query(case: GoldenCase) -> str:
    texts = [case.question, case.reference_answer, *case.reference_contexts]
    document_numbers: list[str] = []
    seen: set[str] = set()
    for citation in parse_legal_citations("\n".join(texts)):
        if citation.document_number and citation.document_number not in seen:
            seen.add(citation.document_number)
            document_numbers.append(citation.document_number)
    return "\n".join([case.question, *document_numbers])


def _stable_bounded_ids(source_ids: Sequence[int], fts_ids: Sequence[object], limit: int) -> list[int]:
    ids: list[int] = []
    for raw_id in [*source_ids, *fts_ids]:
        if isinstance(raw_id, bool) or not isinstance(raw_id, int) or raw_id <= 0:
            raise ValueError("invalid corpus document identity")
        if raw_id not in ids:
            ids.append(raw_id)
        if len(ids) == limit:
            break
    return ids


def _reference_anchor(case: GoldenCase, evidence: GoldEvidence) -> str:
    if not case.reference_contexts:
        raise ValueError(f"missing reference context for case '{case.case_id}'")
    if evidence.context_index < 0:
        raise ValueError("context_index must be zero or a positive 1-based index")
    index = evidence.context_index - 1 if evidence.context_index > 0 else 0
    if index >= len(case.reference_contexts):
        raise ValueError("context_index is out of range for reference contexts")
    return case.reference_contexts[index]


def _candidate_satisfies_required_level(
    required_level: RequiredLevel,
    article: str | None,
    clause: str | None,
) -> bool:
    if required_level == RequiredLevel.DOCUMENT:
        return True
    article_valid = bool(article and article.strip())
    if required_level == RequiredLevel.ARTICLE:
        return article_valid
    if required_level == RequiredLevel.CLAUSE:
        clause_valid = bool(clause and clause.strip())
        return article_valid and clause_valid
    return False


def _supports_required_level(evidence: GoldEvidence, chunk: EvidenceChunk | None) -> bool:
    """Check whether a discovered structural candidate chunk satisfies evidence required_level."""
    if evidence.required_level == RequiredLevel.DOCUMENT:
        return True
    if chunk is None:
        return False
    return _candidate_satisfies_required_level(
        evidence.required_level, chunk.article, chunk.clause
    )


def _first_structural_anchor(
    case: GoldenCase, evidence: GoldEvidence, chunks: Sequence[EvidenceChunk]
) -> EvidenceChunk | None:
    if case.reference_answer:
        norm_ans = norm_text(case.reference_answer)
        if len(norm_ans.split()) >= 3:
            answer_matches = [
                chunk for chunk in chunks
                if norm_ans in norm_text(chunk.text)
            ]
            if len(answer_matches) == 1:
                return answer_matches[0]
            if len(answer_matches) > 1:
                anchor = _reference_anchor(case, evidence)
                norm_anc = norm_text(anchor)
                for chunk in answer_matches:
                    norm_ch = norm_text(chunk.text)
                    if norm_ch in norm_anc or any(
                        w in norm_anc
                        for w in [" ".join(norm_ch.split()[j:j+6]) for j in range(0, max(1, len(norm_ch.split())-5), 4)]
                    ):
                        return chunk
                return answer_matches[0]

    anchor = _reference_anchor(case, evidence)
    for chunk in chunks:
        matched, _, _ = check_anchor_match(anchor, chunk.text)
        if matched:
            return chunk
    return None


def _validate_document(document_id: int, metadata: object, document: object) -> None:
    metadata_document_id = getattr(metadata, "document_id", None)
    if (
        isinstance(metadata_document_id, bool)
        or not isinstance(metadata_document_id, int)
        or metadata_document_id != document_id
    ):
        raise ValueError("invalid corpus document identity")
    for name in ("document_number", "title", "source_url"):
        if not isinstance(getattr(metadata, name, None), str) or not getattr(metadata, name).strip():
            raise ValueError("invalid corpus document identity")
    content_sha256 = getattr(document, "content_sha256", None)
    content = getattr(document, "content", None)
    if (
        not isinstance(content_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", content_sha256) is None
        or not isinstance(content, str)
        or _sha256(content) != content_sha256
    ):
        raise ValueError("invalid corpus document identity")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
