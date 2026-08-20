from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import ValidationError
from app.evaluation.legal_citations import parse_legal_citations
from app.evaluation.schemas import (
    CandidateChunk,
    CandidateDistribution,
    EvidenceStatus,
    EvaluationSchemaError,
    GoldEvidence,
    RequiredLevel,
    RetrievalCaseMetricsV3,
    RetrievalAggregateMetrics,
    RetrievalStageCapacities,
    RetrievalStageTrace,
)


def normalize_legal_identifier(value: Optional[str]) -> str:
    if not value:
        return ""
    normalized = " ".join(value.casefold().split())
    normalized = re.sub(r"(\d+)\.", r"\1", normalized)
    return normalized


def extract_citations_from_text(text: str) -> List[Dict[str, str]]:
    return [
        {
            "document_number": item.document_number,
            "article": item.article,
            "clause": item.clause,
        }
        for item in parse_legal_citations(text)
    ]


def match_gold_to_stage_candidate(
    gold: GoldEvidence,
    candidate: Any,
) -> Tuple[bool, bool, bool]:
    doc_match = False
    cand_doc_id = getattr(candidate, "document_id", None)
    cand_doc_num = getattr(candidate, "document_number", None)

    if gold.document_id is not None and cand_doc_id is not None:
        try:
            doc_match = (int(gold.document_id) == int(cand_doc_id))
        except (ValueError, TypeError):
            doc_match = False
    if not doc_match and gold.document_number and cand_doc_num:
        doc_match = (
            normalize_legal_identifier(gold.document_number) ==
            normalize_legal_identifier(cand_doc_num)
        )

    art_match = False
    cand_art = getattr(candidate, "article", None)
    if doc_match or (not gold.document_id and not gold.document_number):
        if gold.article and cand_art:
            art_match = (
                normalize_legal_identifier(gold.article) ==
                normalize_legal_identifier(cand_art)
            )
        elif not gold.article:
            art_match = doc_match

    clause_match = False
    cand_clause = getattr(candidate, "clause", None)
    if art_match:
        if gold.clause and cand_clause:
            clause_match = (
                normalize_legal_identifier(gold.clause) ==
                normalize_legal_identifier(cand_clause)
            )
        elif not gold.clause:
            clause_match = art_match

    return doc_match, art_match, clause_match


def match_gold_evidence(
    gold: GoldEvidence,
    candidate: Any,
) -> Tuple[bool, bool, bool]:
    return match_gold_to_stage_candidate(gold, candidate)


def calculate_stage_candidate_metrics(
    gold_list: List[GoldEvidence],
    candidates: List[Any],
    is_doc_stage: bool,
    stage_capacity: int,
) -> Dict[str, Any]:
    total_req = len(gold_list)
    if total_req == 0:
        return {
            "candidate_count": len(candidates),
            "configured_stage_capacity": stage_capacity,
            "scored_case_count": 0,
            "verified_evidence_item_count": 0,
        }

    doc_gold = [g for g in gold_list if g.status == EvidenceStatus.VERIFIED or g.required_level == RequiredLevel.DOCUMENT]
    art_gold = [g for g in gold_list if g.required_level in (RequiredLevel.ARTICLE, RequiredLevel.CLAUSE)]
    clause_gold = [g for g in gold_list if g.required_level == RequiredLevel.CLAUSE]

    res: Dict[str, Any] = {
        "candidate_count": len(candidates),
        "configured_stage_capacity": stage_capacity,
        "scored_case_count": 1 if total_req > 0 else 0,
        "verified_evidence_item_count": total_req,
    }

    if is_doc_stage:
        k_list = (1, 3, 5, 10, 24)
        matched_doc_indices: Set[int] = set()
        first_doc_rank: Optional[int] = None
        doc_hits_at_k: Dict[int, int] = {k: 0 for k in k_list}

        for rank, cand in enumerate(candidates, start=1):
            for idx, g in enumerate(doc_gold):
                doc_m, _, _ = match_gold_to_stage_candidate(g, cand)
                if doc_m:
                    matched_doc_indices.add(idx)
                    if first_doc_rank is None:
                        first_doc_rank = rank
            for k in k_list:
                if rank <= k:
                    doc_hits_at_k[k] = len(matched_doc_indices)

        if len(doc_gold) == 0:
            res["doc_mrr"] = None
            res["doc_mrr_reason"] = "no_applicable_verified_document_gold"
        else:
            res["doc_mrr"] = round(1.0 / first_doc_rank, 4) if first_doc_rank else 0.0

        for k in k_list:
            key = f"doc_recall_at_{k}"
            if stage_capacity is not None and k > stage_capacity:
                res[key] = None
                res[f"{key}_reason"] = "k_exceeds_effective_stage_limit"
            elif len(doc_gold) == 0:
                res[key] = None
                res[f"{key}_reason"] = "no_applicable_verified_document_gold"
            else:
                res[key] = round(doc_hits_at_k[k] / len(doc_gold), 4)

    else:  # Chunk stage
        k_list = (1, 3, 6)
        matched_art_indices: Set[int] = set()
        matched_clause_indices: Set[int] = set()
        first_art_rank: Optional[int] = None
        first_clause_rank: Optional[int] = None

        art_hits_at_k: Dict[int, int] = {k: 0 for k in k_list}
        clause_hits_at_k: Dict[int, int] = {k: 0 for k in k_list}

        for rank, cand in enumerate(candidates, start=1):
            for idx, g in enumerate(art_gold):
                _, art_m, _ = match_gold_to_stage_candidate(g, cand)
                if art_m:
                    matched_art_indices.add(idx)
                    if first_art_rank is None:
                        first_art_rank = rank

            for idx, g in enumerate(clause_gold):
                _, _, cl_m = match_gold_to_stage_candidate(g, cand)
                if cl_m:
                    matched_clause_indices.add(idx)
                    if first_clause_rank is None:
                        first_clause_rank = rank

            for k in k_list:
                if rank <= k:
                    art_hits_at_k[k] = len(matched_art_indices)
                    clause_hits_at_k[k] = len(matched_clause_indices)

        if len(art_gold) == 0:
            res["article_mrr"] = None
            res["article_mrr_reason"] = "no_applicable_verified_article_gold"
        else:
            res["article_mrr"] = round(1.0 / first_art_rank, 4) if first_art_rank else 0.0

        if len(clause_gold) == 0:
            res["clause_mrr"] = None
            res["clause_mrr_reason"] = "no_applicable_verified_clause_gold"
        else:
            res["clause_mrr"] = round(1.0 / first_clause_rank, 4) if first_clause_rank else 0.0

        for k in k_list:
            art_key = f"article_recall_at_{k}"
            if stage_capacity is not None and k > stage_capacity:
                res[art_key] = None
                res[f"{art_key}_reason"] = "k_exceeds_effective_stage_limit"
            elif len(art_gold) == 0:
                res[art_key] = None
                res[f"{art_key}_reason"] = "no_applicable_verified_article_gold"
            else:
                res[art_key] = round(art_hits_at_k[k] / len(art_gold), 4)

            cl_key = f"clause_recall_at_{k}"
            if stage_capacity is not None and k > stage_capacity:
                res[cl_key] = None
                res[f"{cl_key}_reason"] = "k_exceeds_effective_stage_limit"
            elif len(clause_gold) == 0:
                res[cl_key] = None
                res[f"{cl_key}_reason"] = "no_applicable_verified_clause_gold"
            else:
                res[cl_key] = round(clause_hits_at_k[k] / len(clause_gold), 4)

    return res


DOCUMENT_RECALL_K = (1, 3, 5, 10, 24)
STRUCTURAL_RECALL_K = (1, 3, 6)
STAGE_METRIC_SEQUENCE = (
    "pinecone_document_metrics",
    "fts_document_metrics",
    "source_retrieval_metrics",
    "merged_document_metrics",
    "resolved_document_metrics",
    "structural_chunk_metrics",
    "local_selection_metrics",
    "reranker_input_metrics",
    "reranker_output_metrics",
    "final_evidence_metrics",
)
FIRST_LOSS_SEQUENCE = (
    "source_retrieval_metrics",
    "merged_document_metrics",
    "resolved_document_metrics",
    "structural_chunk_metrics",
    "local_selection_metrics",
    "reranker_input_metrics",
    "reranker_output_metrics",
    "final_evidence_metrics",
)
DOCUMENT_ONLY_STAGES = {
    "pinecone_document_metrics",
    "fts_document_metrics",
    "source_retrieval_metrics",
    "merged_document_metrics",
    "resolved_document_metrics",
}
QUALITY_SKIP_STATUSES = {
    "retrieval_error",
    "reranker_error",
    "input_guardrail_rejected",
    "input_guardrail_error",
}


def ratio(
    numerator: float,
    denominator: float,
    reason: str,
) -> Dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": (
            round(numerator / denominator, 4)
            if denominator
            else None
        ),
        "reason": None if denominator else reason,
    }


def reciprocal_rank(
    first_rank: Optional[int],
    applicable: int,
) -> Dict[str, Any]:
    reciprocal = 1.0 / first_rank if first_rank is not None else 0.0
    return {
        "numerator": round(reciprocal, 6) if applicable else 0.0,
        "denominator": 1 if applicable else 0,
        "value": (
            round(reciprocal, 4)
            if first_rank is not None
            else (0.0 if applicable else None)
        ),
        "reason": None if applicable else "no_applicable_gold",
    }


def ndcg_at_k(
    relevant_ranks: List[int],
    relevant_count: int,
    k: int,
) -> Dict[str, Any]:
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank in relevant_ranks
        if rank <= k
    )
    ideal = sum(
        1.0 / math.log2(rank + 1)
        for rank in range(1, min(relevant_count, k) + 1)
    )
    return {
        "numerator": round(dcg, 6),
        "denominator": round(ideal, 6),
        "value": round(dcg / ideal, 4) if ideal else None,
        "reason": None if ideal else "no_applicable_gold",
    }


def matches_required_level(
    gold_item: GoldEvidence,
    candidate_item: Any,
) -> bool:
    document_match, article_match, clause_match = (
        match_gold_to_stage_candidate(gold_item, candidate_item)
    )
    if gold_item.required_level == RequiredLevel.DOCUMENT:
        return document_match
    if gold_item.required_level == RequiredLevel.ARTICLE:
        return article_match
    return clause_match


def evidence_survives_stage(
    gold_item: GoldEvidence,
    candidate_item: Any,
    stage_name: str,
) -> bool:
    document_match, _, _ = match_gold_to_stage_candidate(
        gold_item,
        candidate_item,
    )
    if stage_name in DOCUMENT_ONLY_STAGES:
        return document_match
    return matches_required_level(gold_item, candidate_item)


def _document_identity(candidate: Any) -> Tuple[str, str]:
    document_id = getattr(candidate, "document_id", None)
    if document_id is not None:
        return "id", str(document_id)
    document_number = normalize_legal_identifier(
        getattr(candidate, "document_number", None)
    )
    if document_number:
        return "number", document_number
    return "object", repr(candidate)


def _stable_document_union(
    *branches: List[Any],
) -> List[Any]:
    result: List[Any] = []
    seen: Set[Tuple[str, str]] = set()
    for branch in branches:
        for candidate in branch:
            identity = _document_identity(candidate)
            if identity in seen:
                continue
            seen.add(identity)
            result.append(candidate)
    return result


def _gold_by_level(
    required_gold: List[GoldEvidence],
) -> Tuple[List[GoldEvidence], List[GoldEvidence], List[GoldEvidence]]:
    document_gold = list(required_gold)
    article_gold = [
        item
        for item in required_gold
        if item.required_level
        in {RequiredLevel.ARTICLE, RequiredLevel.CLAUSE}
    ]
    clause_gold = [
        item
        for item in required_gold
        if item.required_level == RequiredLevel.CLAUSE
    ]
    return document_gold, article_gold, clause_gold


def _level_match(
    gold_item: GoldEvidence,
    candidate_item: Any,
    level: str,
) -> bool:
    document_match, article_match, clause_match = (
        match_gold_to_stage_candidate(gold_item, candidate_item)
    )
    return {
        "document": document_match,
        "article": article_match,
        "clause": clause_match,
    }[level]


def _matched_indices(
    gold_items: List[GoldEvidence],
    candidates: List[Any],
    level: str,
) -> Set[int]:
    return {
        index
        for index, item in enumerate(gold_items)
        if any(_level_match(item, candidate, level) for candidate in candidates)
    }


def _first_match_rank(
    gold_items: List[GoldEvidence],
    candidates: List[Any],
    level: str,
) -> Optional[int]:
    for rank, candidate in enumerate(candidates, start=1):
        if any(
            _level_match(item, candidate, level)
            for item in gold_items
        ):
            return rank
    return None


def _unavailable_recall(
    k_values: Tuple[int, ...],
    reason: str,
) -> Dict[int, Dict[str, Any]]:
    return {k: ratio(0, 0, reason) for k in k_values}


def _recall_by_k(
    gold_items: List[GoldEvidence],
    candidates: List[Any],
    level: str,
    k_values: Tuple[int, ...],
    capacity: Optional[int],
    *,
    force_reason: Optional[str] = None,
) -> Dict[int, Dict[str, Any]]:
    result: Dict[int, Dict[str, Any]] = {}
    for k in k_values:
        if force_reason:
            result[k] = ratio(0, 0, force_reason)
        elif capacity is None:
            result[k] = ratio(0, 0, "configured_capacity_unknown")
        elif k > capacity:
            result[k] = ratio(
                0,
                0,
                "k_exceeds_configured_capacity",
            )
        elif not gold_items:
            result[k] = ratio(0, 0, "no_applicable_gold")
        else:
            matched = _matched_indices(
                gold_items,
                candidates[:k],
                level,
            )
            result[k] = ratio(
                len(matched),
                len(gold_items),
                "no_applicable_gold",
            )
    return result


def _mrr(
    gold_items: List[GoldEvidence],
    candidates: List[Any],
    level: str,
    *,
    force_reason: Optional[str] = None,
) -> Dict[str, Any]:
    if force_reason:
        return ratio(0, 0, force_reason)
    return reciprocal_rank(
        _first_match_rank(gold_items, candidates, level),
        len(gold_items),
    )


def _count_null_reasons(stage: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    metrics: List[Dict[str, Any]] = []
    for by_k in stage["recall"].values():
        metrics.extend(by_k.values())
    metrics.extend(stage["mrr"].values())
    for metric in metrics:
        reason = metric.get("reason")
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
    return counts


def _build_stage_metrics(
    *,
    stage_name: str,
    candidates: List[Any],
    capacity: Optional[int],
    required_gold: List[GoldEvidence],
    skip_reason: Optional[str],
) -> Dict[str, Any]:
    document_gold, article_gold, clause_gold = _gold_by_level(
        required_gold
    )
    document_only = stage_name in DOCUMENT_ONLY_STAGES
    structural_reason = (
        skip_reason or "stage_does_not_expose_structural_locators"
    )
    applicable_counts = (
        {"document": 0, "article": 0, "clause": 0}
        if skip_reason
        else {
            "document": len(document_gold),
            "article": 0 if document_only else len(article_gold),
            "clause": 0 if document_only else len(clause_gold),
        }
    )
    matched_counts = {
        "document": (
            0
            if skip_reason
            else len(
                _matched_indices(
                    document_gold,
                    candidates,
                    "document",
                )
            )
        ),
        "article": (
            0
            if skip_reason or document_only
            else len(
                _matched_indices(article_gold, candidates, "article")
            )
        ),
        "clause": (
            0
            if skip_reason or document_only
            else len(
                _matched_indices(clause_gold, candidates, "clause")
            )
        ),
    }
    stage = {
        "configured_capacity": capacity,
        "candidate_count": len(candidates),
        "scored_case_count": 0 if skip_reason else 1,
        "applicable_gold_counts": applicable_counts,
        "matched_gold_counts": matched_counts,
        "recall": {
            "document": _recall_by_k(
                document_gold,
                candidates,
                "document",
                DOCUMENT_RECALL_K,
                capacity,
                force_reason=skip_reason,
            ),
            "article": (
                _unavailable_recall(
                    STRUCTURAL_RECALL_K,
                    structural_reason,
                )
                if document_only
                else _recall_by_k(
                    article_gold,
                    candidates,
                    "article",
                    STRUCTURAL_RECALL_K,
                    capacity,
                    force_reason=skip_reason,
                )
            ),
            "clause": (
                _unavailable_recall(
                    STRUCTURAL_RECALL_K,
                    structural_reason,
                )
                if document_only
                else _recall_by_k(
                    clause_gold,
                    candidates,
                    "clause",
                    STRUCTURAL_RECALL_K,
                    capacity,
                    force_reason=skip_reason,
                )
            ),
        },
        "mrr": {
            "document": _mrr(
                document_gold,
                candidates,
                "document",
                force_reason=skip_reason,
            ),
            "article": (
                ratio(0, 0, structural_reason)
                if document_only
                else _mrr(
                    article_gold,
                    candidates,
                    "article",
                    force_reason=skip_reason,
                )
            ),
            "clause": (
                ratio(0, 0, structural_reason)
                if document_only
                else _mrr(
                    clause_gold,
                    candidates,
                    "clause",
                    force_reason=skip_reason,
                )
            ),
        },
        "null_reason_counts": {},
    }
    stage["null_reason_counts"] = _count_null_reasons(stage)
    return stage


def _exact_reference_matches(
    gold_item: GoldEvidence,
    candidate_item: Any,
) -> bool:
    gold_number = normalize_legal_identifier(gold_item.document_number)
    candidate_number = normalize_legal_identifier(
        getattr(candidate_item, "document_number", None)
    )
    if not gold_number or gold_number != candidate_number:
        return False
    if gold_item.required_level == RequiredLevel.DOCUMENT:
        return True
    gold_article = normalize_legal_identifier(gold_item.article)
    candidate_article = normalize_legal_identifier(
        getattr(candidate_item, "article", None)
    )
    if not gold_article or gold_article != candidate_article:
        return False
    if gold_item.required_level == RequiredLevel.ARTICLE:
        return True
    gold_clause = normalize_legal_identifier(gold_item.clause)
    candidate_clause = normalize_legal_identifier(
        getattr(candidate_item, "clause", None)
    )
    return bool(gold_clause and gold_clause == candidate_clause)


def _exact_reference_gold(
    required_gold: List[GoldEvidence],
) -> List[GoldEvidence]:
    result: List[GoldEvidence] = []
    for item in required_gold:
        if not normalize_legal_identifier(item.document_number):
            continue
        if (
            item.required_level
            in {RequiredLevel.ARTICLE, RequiredLevel.CLAUSE}
            and not normalize_legal_identifier(item.article)
        ):
            continue
        if (
            item.required_level == RequiredLevel.CLAUSE
            and not normalize_legal_identifier(item.clause)
        ):
            continue
        result.append(item)
    return result


def _relevant_ranks(
    required_gold: List[GoldEvidence],
    candidates: List[Any],
) -> List[int]:
    unmatched = set(range(len(required_gold)))
    ranks: List[int] = []
    for rank, candidate in enumerate(candidates, start=1):
        matched_index = next(
            (
                index
                for index in sorted(unmatched)
                if matches_required_level(
                    required_gold[index],
                    candidate,
                )
            ),
            None,
        )
        if matched_index is not None:
            unmatched.remove(matched_index)
            ranks.append(rank)
    return ranks


def _first_loss(
    required_gold: List[GoldEvidence],
    stage_candidates: Dict[str, List[Any]],
) -> Dict[str, str]:
    losses: Dict[str, str] = {}
    for item in required_gold:
        for stage_name in FIRST_LOSS_SEQUENCE:
            survives = any(
                evidence_survives_stage(item, candidate, stage_name)
                for candidate in stage_candidates[stage_name]
            )
            if not survives:
                losses[item.evidence_item_id] = stage_name
                break
    return losses


def calculate_case_retrieval_metrics(
    gold_evidence: List[GoldEvidence],
    retrieved_chunks: List[CandidateChunk],
    stage_trace: Optional[RetrievalStageTrace] = None,
    capacities: Optional[RetrievalStageCapacities] = None,
    *,
    status: str = "ok",
) -> Dict[str, Any]:
    caps = capacities or RetrievalStageCapacities()
    trace = stage_trace or RetrievalStageTrace()
    verified_required = [
        item
        for item in gold_evidence
        if item.status == EvidenceStatus.VERIFIED and item.required
    ]
    skip_reason: Optional[str] = None
    if status in QUALITY_SKIP_STATUSES:
        skip_reason = status
    elif not verified_required:
        skip_reason = "no_verified_gold_label"
    applicable = skip_reason is None

    source_candidates = _stable_document_union(
        trace.pinecone_hits,
        trace.fts_hits,
    )
    if not source_candidates and stage_trace is None:
        source_candidates = list(retrieved_chunks)
    final_candidates: List[Any] = list(retrieved_chunks)
    stage_candidates: Dict[str, List[Any]] = {
        "pinecone_document_metrics": list(trace.pinecone_hits),
        "fts_document_metrics": list(trace.fts_hits),
        "source_retrieval_metrics": source_candidates,
        "merged_document_metrics": list(
            trace.merged_document_candidates
        ),
        "resolved_document_metrics": list(
            trace.resolved_document_candidates
        ),
        "structural_chunk_metrics": list(
            trace.structural_chunks_generated
        ),
        "local_selection_metrics": list(
            trace.locally_selected_chunks
        ),
        "reranker_input_metrics": list(trace.reranker_input_chunks),
        "reranker_output_metrics": list(trace.reranker_output_chunks),
        "final_evidence_metrics": final_candidates,
    }
    stage_capacities = {
        "pinecone_document_metrics": caps.pinecone_document_limit,
        "fts_document_metrics": caps.fts_document_limit,
        "source_retrieval_metrics": caps.merged_document_limit,
        "merged_document_metrics": caps.merged_document_limit,
        "resolved_document_metrics": caps.resolved_document_limit,
        "structural_chunk_metrics": caps.structural_chunk_limit,
        "local_selection_metrics": caps.local_chunks_limit,
        "reranker_input_metrics": caps.rerank_input_limit,
        "reranker_output_metrics": caps.rerank_return_limit,
        "final_evidence_metrics": caps.final_evidence_limit,
    }
    stages = {
        name: _build_stage_metrics(
            stage_name=name,
            candidates=stage_candidates[name],
            capacity=stage_capacities[name],
            required_gold=verified_required,
            skip_reason=skip_reason,
        )
        for name in STAGE_METRIC_SEQUENCE
    }

    document_gold, article_gold, clause_gold = _gold_by_level(
        verified_required
    )
    matched_required = (
        sum(
            1
            for item in verified_required
            if any(
                matches_required_level(item, candidate)
                for candidate in final_candidates
            )
        )
        if applicable
        else 0
    )
    matched_counts = {
        "document": (
            len(
                _matched_indices(
                    document_gold,
                    final_candidates,
                    "document",
                )
            )
            if applicable
            else 0
        ),
        "article": (
            len(
                _matched_indices(
                    article_gold,
                    final_candidates,
                    "article",
                )
            )
            if applicable
            else 0
        ),
        "clause": (
            len(
                _matched_indices(
                    clause_gold,
                    final_candidates,
                    "clause",
                )
            )
            if applicable
            else 0
        ),
    }
    applicable_counts = {
        "document": len(document_gold),
        "article": len(article_gold),
        "clause": len(clause_gold),
    }

    exact_gold = _exact_reference_gold(verified_required)
    if skip_reason:
        exact_reference = ratio(0, 0, skip_reason)
    elif not exact_gold:
        exact_reference = ratio(0, 0, "no_exact_reference_gold")
    else:
        exact_hit = any(
            _exact_reference_matches(item, candidate)
            for item in exact_gold
            for candidate in final_candidates
        )
        exact_reference = ratio(
            1 if exact_hit else 0,
            1,
            "no_exact_reference_gold",
        )

    if skip_reason:
        ndcg = ratio(0, 0, skip_reason)
    else:
        ndcg = ndcg_at_k(
            _relevant_ranks(verified_required, final_candidates),
            len(verified_required),
            10,
        )

    required_count = len(verified_required)
    all_required = bool(
        required_count and matched_required == required_count
    )
    if skip_reason:
        all_required_metric = ratio(0, 0, skip_reason)
        partial_metric = ratio(0, 0, skip_reason)
    elif not required_count:
        all_required_metric = ratio(0, 0, "no_applicable_gold")
        partial_metric = ratio(0, 0, "no_applicable_gold")
    else:
        all_required_metric = ratio(
            1 if all_required else 0,
            1,
            "no_applicable_gold",
        )
        partial_metric = ratio(
            matched_required,
            required_count,
            "no_applicable_gold",
        )

    metrics = RetrievalCaseMetricsV3(
        status=status,
        applicable=applicable,
        skip_reason=skip_reason,
        applicable_gold_counts=applicable_counts,
        matched_gold_counts=matched_counts,
        document_recall=_recall_by_k(
            document_gold,
            source_candidates,
            "document",
            DOCUMENT_RECALL_K,
            caps.merged_document_limit,
            force_reason=skip_reason,
        ),
        article_recall=_recall_by_k(
            article_gold,
            final_candidates,
            "article",
            STRUCTURAL_RECALL_K,
            caps.final_evidence_limit,
            force_reason=skip_reason,
        ),
        clause_recall=_recall_by_k(
            clause_gold,
            final_candidates,
            "clause",
            STRUCTURAL_RECALL_K,
            caps.final_evidence_limit,
            force_reason=skip_reason,
        ),
        mrr={
            "document": _mrr(
                document_gold,
                source_candidates,
                "document",
                force_reason=skip_reason,
            ),
            "article": _mrr(
                article_gold,
                final_candidates,
                "article",
                force_reason=skip_reason,
            ),
            "clause": _mrr(
                clause_gold,
                final_candidates,
                "clause",
                force_reason=skip_reason,
            ),
        },
        ndcg_at_10=ndcg,
        exact_reference_hit=exact_reference,
        multi_hop={
            "all_required": all_required,
            "matched_required_items": matched_required,
            "required_items": required_count,
            "all_required_metric": all_required_metric,
            "partial_metric": partial_metric,
        },
        no_candidate=status == "no_candidate",
        retrieval_technical_error=status in {
            "retrieval_error",
            "partial_retrieval_error",
        },
        reranker_technical_error=status == "reranker_error",
        stages=stages,
        first_loss_by_evidence=(
            _first_loss(verified_required, stage_candidates)
            if applicable and stage_trace is not None
            else {}
        ),
    )
    return metrics.model_dump(mode="json")


def percentile(
    values: List[int],
    quantile: float,
) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return float(ordered[lower])
    weight = index - lower
    return round(
        ordered[lower] * (1.0 - weight)
        + ordered[upper] * weight,
        4,
    )


def candidate_distribution(
    values: List[int],
) -> CandidateDistribution:
    return CandidateDistribution(
        count=len(values),
        min=float(min(values)) if values else None,
        mean=round(sum(values) / len(values), 4) if values else None,
        p50=percentile(values, 0.50),
        p95=percentile(values, 0.95),
        max=float(max(values)) if values else None,
    )


def _empty_aggregate_metric(reason: str) -> Dict[str, Any]:
    return {
        "macro": None,
        "micro": None,
        "numerator": 0.0,
        "denominator": 0.0,
        "scored_cases": 0,
        "skipped_cases": 0,
        "skip_reasons": {},
        "reason": reason,
    }


def _aggregate_ratios(
    ratios: List[Any],
    *,
    empty_reason: str = "no_applicable_values",
) -> Dict[str, Any]:
    if not ratios:
        return _empty_aggregate_metric(empty_reason)
    values = [
        float(metric.value)
        for metric in ratios
        if metric.value is not None
    ]
    numerator = sum(float(metric.numerator) for metric in ratios)
    denominator = sum(float(metric.denominator) for metric in ratios)
    skip_reasons: Dict[str, int] = {}
    for metric in ratios:
        if metric.reason:
            skip_reasons[metric.reason] = (
                skip_reasons.get(metric.reason, 0) + 1
            )
    return {
        "macro": (
            round(sum(values) / len(values), 4)
            if values
            else None
        ),
        "micro": (
            round(numerator / denominator, 4)
            if denominator
            else None
        ),
        "numerator": round(numerator, 6),
        "denominator": round(denominator, 6),
        "scored_cases": len(values),
        "skipped_cases": len(ratios) - len(values),
        "skip_reasons": skip_reasons,
        "reason": None if denominator else empty_reason,
    }


def _operational_rate(
    *,
    numerator: int,
    denominator: int,
    reason: str = "no_cases",
) -> Dict[str, Any]:
    value = (
        round(numerator / denominator, 4)
        if denominator
        else None
    )
    return {
        "macro": value,
        "micro": value,
        "numerator": numerator,
        "denominator": denominator,
        "scored_cases": denominator,
        "skipped_cases": 0,
        "skip_reasons": {},
        "reason": None if denominator else reason,
    }


def _aggregate_ratio_mapping(
    metrics: List[RetrievalCaseMetricsV3],
    attribute: str,
) -> Dict[int, Dict[str, Any]]:
    keys = sorted(
        {
            key
            for metric in metrics
            for key in getattr(metric, attribute)
        }
    )
    return {
        key: _aggregate_ratios(
            [
                getattr(metric, attribute)[key]
                for metric in metrics
                if key in getattr(metric, attribute)
            ]
        )
        for key in keys
    }


def _validated_case_metrics(
    case_results: List[Dict[str, Any]],
) -> List[RetrievalCaseMetricsV3]:
    validated: List[RetrievalCaseMetricsV3] = []
    for row in case_results:
        try:
            status = row["status"]
            metrics = RetrievalCaseMetricsV3.model_validate(
                row["metrics"]
            )
        except (KeyError, TypeError, ValidationError) as error:
            raise EvaluationSchemaError(
                "invalid per-case retrieval metric schema"
            ) from error
        if status != metrics.status:
            raise EvaluationSchemaError(
                "case status does not match metrics status"
            )
        validated.append(metrics)
    return validated


def aggregate_retrieval_metrics(
    case_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    total_cases = len(case_results)
    if not case_results:
        no_cases = _empty_aggregate_metric("no_cases")
        return RetrievalAggregateMetrics(
            total_cases=0,
            scored_cases=0,
            skipped_cases=0,
            coverage=no_cases,
            skip_reason_counts={},
            document_recall={},
            article_recall={},
            clause_recall={},
            mrr={},
            ndcg_at_10=no_cases,
            exact_reference_hit=no_cases,
            multi_hop_all_required=no_cases,
            multi_hop_partial=no_cases,
            no_candidate_rate=no_cases,
            retrieval_technical_error_rate=no_cases,
            reranker_technical_error_rate=no_cases,
            stages={},
        ).model_dump(mode="json")

    metrics_list = _validated_case_metrics(case_results)
    scored_cases = sum(metric.applicable for metric in metrics_list)
    skipped_cases = total_cases - scored_cases
    skip_reason_counts: Dict[str, int] = {}
    for metric in metrics_list:
        if not metric.applicable:
            reason = metric.skip_reason or "unspecified_skip_reason"
            skip_reason_counts[reason] = (
                skip_reason_counts.get(reason, 0) + 1
            )

    coverage_value = round(scored_cases / total_cases, 4)
    coverage = {
        "macro": coverage_value,
        "micro": coverage_value,
        "numerator": scored_cases,
        "denominator": total_cases,
        "scored_cases": total_cases,
        "skipped_cases": 0,
        "skip_reasons": skip_reason_counts,
        "reason": None,
    }

    mrr_levels = sorted(
        {
            level
            for metric in metrics_list
            for level in metric.mrr
        }
    )
    mrr = {
        level: _aggregate_ratios(
            [
                metric.mrr[level]
                for metric in metrics_list
                if level in metric.mrr
            ]
        )
        for level in mrr_levels
    }

    stage_names = [
        stage_name
        for stage_name in STAGE_METRIC_SEQUENCE
        if any(
            stage_name in metric.stages
            for metric in metrics_list
        )
    ]
    first_loss_counts: Dict[str, int] = {
        stage_name: 0 for stage_name in stage_names
    }
    for metric in metrics_list:
        for stage_name in metric.first_loss_by_evidence.values():
            if stage_name not in STAGE_METRIC_SEQUENCE:
                raise EvaluationSchemaError(
                    f"unknown first-loss stage: {stage_name}"
                )
            if stage_name not in first_loss_counts:
                raise EvaluationSchemaError(
                    f"first-loss stage missing from metrics: {stage_name}"
                )
            first_loss_counts[stage_name] += 1

    aggregate_stages: Dict[str, Any] = {}
    for stage_name in stage_names:
        stage_rows = [
            metric.stages[stage_name]
            for metric in metrics_list
            if stage_name in metric.stages
        ]
        capacities = {
            stage.configured_capacity
            for stage in stage_rows
            if stage.configured_capacity is not None
        }
        if len(capacities) > 1:
            raise EvaluationSchemaError(
                "inconsistent configured capacity for "
                f"{stage_name}"
            )
        configured_capacity = (
            next(iter(capacities)) if capacities else None
        )
        levels = sorted(
            {
                level
                for stage in stage_rows
                for level in stage.recall
            }
        )
        recall: Dict[str, Dict[int, Any]] = {}
        for level in levels:
            k_values = sorted(
                {
                    k
                    for stage in stage_rows
                    for k in stage.recall.get(level, {})
                }
            )
            recall[level] = {
                k: _aggregate_ratios(
                    [
                        stage.recall[level][k]
                        for stage in stage_rows
                        if k in stage.recall.get(level, {})
                    ]
                )
                for k in k_values
            }
        mrr_stage_levels = sorted(
            {
                level
                for stage in stage_rows
                for level in stage.mrr
            }
        )
        stage_mrr = {
            level: _aggregate_ratios(
                [
                    stage.mrr[level]
                    for stage in stage_rows
                    if level in stage.mrr
                ]
            )
            for level in mrr_stage_levels
        }
        applicable_gold_counts = {
            level: sum(
                stage.applicable_gold_counts.get(level, 0)
                for stage in stage_rows
            )
            for level in ("document", "article", "clause")
        }
        matched_gold_counts = {
            level: sum(
                stage.matched_gold_counts.get(level, 0)
                for stage in stage_rows
            )
            for level in ("document", "article", "clause")
        }
        null_reason_counts: Dict[str, int] = {}
        for stage in stage_rows:
            for reason, count in stage.null_reason_counts.items():
                null_reason_counts[reason] = (
                    null_reason_counts.get(reason, 0) + count
                )
        aggregate_stages[stage_name] = {
            "configured_capacity": configured_capacity,
            "scored_case_count": sum(
                stage.scored_case_count for stage in stage_rows
            ),
            "applicable_gold_counts": applicable_gold_counts,
            "matched_gold_counts": matched_gold_counts,
            "recall": recall,
            "mrr": stage_mrr,
            "candidates": candidate_distribution(
                [stage.candidate_count for stage in stage_rows]
            ),
            "first_loss_evidence_count": first_loss_counts[
                stage_name
            ],
            "null_reason_counts": null_reason_counts,
        }

    statuses = [metric.status for metric in metrics_list]
    summary = RetrievalAggregateMetrics(
        total_cases=total_cases,
        scored_cases=scored_cases,
        skipped_cases=skipped_cases,
        coverage=coverage,
        skip_reason_counts=skip_reason_counts,
        document_recall=_aggregate_ratio_mapping(
            metrics_list,
            "document_recall",
        ),
        article_recall=_aggregate_ratio_mapping(
            metrics_list,
            "article_recall",
        ),
        clause_recall=_aggregate_ratio_mapping(
            metrics_list,
            "clause_recall",
        ),
        mrr=mrr,
        ndcg_at_10=_aggregate_ratios(
            [metric.ndcg_at_10 for metric in metrics_list]
        ),
        exact_reference_hit=_aggregate_ratios(
            [metric.exact_reference_hit for metric in metrics_list]
        ),
        multi_hop_all_required=_aggregate_ratios(
            [
                metric.multi_hop.all_required_metric
                for metric in metrics_list
            ]
        ),
        multi_hop_partial=_aggregate_ratios(
            [
                metric.multi_hop.partial_metric
                for metric in metrics_list
            ]
        ),
        no_candidate_rate=_operational_rate(
            numerator=statuses.count("no_candidate"),
            denominator=total_cases,
        ),
        retrieval_technical_error_rate=_operational_rate(
            numerator=(
                statuses.count("retrieval_error")
                + statuses.count("partial_retrieval_error")
            ),
            denominator=total_cases,
        ),
        reranker_technical_error_rate=_operational_rate(
            numerator=statuses.count("reranker_error"),
            denominator=total_cases,
        ),
        stages=aggregate_stages,
    )
    return summary.model_dump(mode="json")


def calculate_stage_survival_rates(
    stage_traces: List[RetrievalStageTrace],
) -> Dict[str, Any]:
    total = len(stage_traces)
    if total == 0:
        return {}

    return {
        "total_traces": total,
        "avg_pinecone_hits": round(sum(len(t.pinecone_hits) for t in stage_traces) / total, 2),
        "avg_fts_hits": round(sum(len(t.fts_hits) for t in stage_traces) / total, 2),
        "avg_merged_docs": round(sum(len(t.merged_document_candidates) for t in stage_traces) / total, 2),
        "avg_resolved_docs": round(sum(len(t.resolved_document_candidates) for t in stage_traces) / total, 2),
        "avg_structural_chunks": round(sum(len(t.structural_chunks_generated) for t in stage_traces) / total, 2),
        "avg_local_selected": round(sum(len(t.locally_selected_chunks) for t in stage_traces) / total, 2),
        "avg_rerank_input": round(sum(len(t.reranker_input_chunks) for t in stage_traces) / total, 2),
        "avg_rerank_output": round(sum(len(t.reranker_output_chunks) for t in stage_traces) / total, 2),
        "avg_final_evidence": round(sum(len(t.final_evidence_chunks) for t in stage_traces) / total, 2),
    }
