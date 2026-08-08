"""Bounded, read-only local candidates for human gold-evidence adjudication."""

from __future__ import annotations

import hashlib
import re
from typing import Mapping, Sequence

from audit_golden_dataset import check_anchor_match, norm_text
from app.evaluation.adjudication import AdjudicationCandidate, candidate_identity_sha256
from app.evaluation.legal_citations import parse_legal_citations
from app.evaluation.schemas import GoldEvidence, GoldenCase, RequiredLevel
from app.ingestion.content_store import ContentStore
from app.ingestion.legal_fts import LegalFtsIndex
from app.ingestion.legal_text import EvidenceChunk, chunk_document


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
        document_ids = _stable_bounded_ids(source_ids, fts_ids, candidate_limit)
        documents = content_store.get_many(document_ids)
        missing_ids = [document_id for document_id in document_ids if document_id not in documents]
        if missing_ids:
            raise ValueError(
                f"missing retrieved documents for selected case '{case_id}': {missing_ids}"
            )

        chunks_by_id: dict[int, list[EvidenceChunk]] = {}
        candidates: list[AdjudicationCandidate] = []
        source_set = set(source_ids)
        for evidence in labels:
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
                article = clause = structural_citation = structural_chunk_sha256 = None
                required_supported = False
                citation = metadata.document_number
                if matched:
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


def _first_structural_anchor(
    case: GoldenCase, evidence: GoldEvidence, chunks: Sequence[EvidenceChunk]
) -> EvidenceChunk | None:
    anchor = _reference_anchor(case, evidence)
    for chunk in chunks:
        matched, _, _ = check_anchor_match(anchor, chunk.text)
        if matched:
            return chunk
    return None


def _supports_required_level(evidence: GoldEvidence, chunk: EvidenceChunk | None) -> bool:
    if evidence.required_level == RequiredLevel.DOCUMENT:
        return True
    if chunk is None:
        return False
    article_matches = bool(
        evidence.article and chunk.article and norm_text(evidence.article) == norm_text(chunk.article)
    )
    if evidence.required_level == RequiredLevel.ARTICLE:
        return article_matches
    return bool(
        article_matches
        and evidence.clause
        and chunk.clause
        and norm_text(evidence.clause) == norm_text(f"Khoản {chunk.clause}")
    )


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
