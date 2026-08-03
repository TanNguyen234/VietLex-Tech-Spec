from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from app.evaluation.schemas import CandidateChunk, GoldEvidence, GoldenCase, RetrievalStageTrace


def normalize_legal_identifier(value: Optional[str]) -> str:
    if not value:
        return ""
    # Strip whitespace, convert to lower, normalize spaces
    normalized = " ".join(value.casefold().split())
    # Remove dots after numbers in clause if any (e.g., "1." -> "1")
    normalized = re.sub(r"(\d+)\.", r"\1", normalized)
    return normalized


def extract_citations_from_text(text: str) -> List[Dict[str, str]]:
    """Helper to extract doc numbers, articles, clauses from text strings for diagnostic matching."""
    citations: List[Dict[str, str]] = []
    # Match patterns like "Điều 3", "Khoản 8", "Luật 72/2020/QH14"
    doc_nums = re.findall(r"\b\d{1,4}/\d{4}/[A-ZĐ0-9-]+\b", text, re.IGNORECASE)
    articles = re.findall(r"\bĐiều\s+\d+[A-Za-z]?\b", text, re.IGNORECASE)
    clauses = re.findall(r"\bKhoản\s+\d+\b", text, re.IGNORECASE)
    
    doc_num = doc_nums[0].upper() if doc_nums else ""
    art = articles[0] if articles else ""
    cl = clauses[0] if clauses else ""
    if doc_num or art or cl:
        citations.append({
            "document_number": doc_num,
            "article": art,
            "clause": cl
        })
    return citations


def match_gold_evidence(
    gold: GoldEvidence,
    candidate: CandidateChunk
) -> Tuple[bool, bool, bool]:
    """Check if candidate matches gold evidence at document, article, and clause levels."""
    doc_match = False
    if gold.document_id is not None and candidate.document_id is not None:
        try:
            doc_match = (int(gold.document_id) == int(candidate.document_id))
        except (ValueError, TypeError):
            doc_match = False
    if not doc_match and gold.document_number and candidate.document_number:
        doc_match = (
            normalize_legal_identifier(gold.document_number) ==
            normalize_legal_identifier(candidate.document_number)
        )

    art_match = False
    if doc_match or (not gold.document_id and not gold.document_number):
        if gold.article and candidate.article:
            art_match = (
                normalize_legal_identifier(gold.article) ==
                normalize_legal_identifier(candidate.article)
            )
        elif not gold.article:
            art_match = doc_match

    clause_match = False
    if art_match:
        if gold.clause and candidate.clause:
            clause_match = (
                normalize_legal_identifier(gold.clause) ==
                normalize_legal_identifier(candidate.clause)
            )
        elif not gold.clause:
            clause_match = art_match

    return doc_match, art_match, clause_match


def calculate_case_retrieval_metrics(
    gold_evidence: List[GoldEvidence],
    retrieved_chunks: List[CandidateChunk]
) -> Dict[str, Any]:
    """Calculate Recall@K, MRR, nDCG, citation hits, and multi-hop coverage for a single case."""
    if not gold_evidence or all(g.status == "missing_gold_label" for g in gold_evidence):
        return {
            "has_gold_labels": False,
            "skip_reason": "missing_gold_label"
        }

    valid_gold = [g for g in gold_evidence if g.status != "missing_gold_label"]
    required_gold = [g for g in valid_gold if g.required]
    if not required_gold:
        required_gold = valid_gold

    # Evaluate matches per candidate rank
    doc_hits_at_k: Dict[int, int] = {k: 0 for k in (1, 3, 5, 10, 24)}
    art_hits_at_k: Dict[int, int] = {k: 0 for k in (1, 3, 6)}
    clause_hits_at_k: Dict[int, int] = {k: 0 for k in (1, 3, 6)}

    # Track which gold evidence items were matched
    matched_gold_doc: Set[int] = set()
    matched_gold_art: Set[int] = set()
    matched_gold_clause: Set[int] = set()

    first_doc_rank: Optional[int] = None
    first_art_rank: Optional[int] = None
    first_clause_rank: Optional[int] = None

    for rank, chunk in enumerate(retrieved_chunks, start=1):
        for idx, g in enumerate(required_gold):
            doc_m, art_m, cl_m = match_gold_evidence(g, chunk)
            if doc_m:
                matched_gold_doc.add(idx)
                if first_doc_rank is None:
                    first_doc_rank = rank
            if art_m:
                matched_gold_art.add(idx)
                if first_art_rank is None:
                    first_art_rank = rank
            if cl_m:
                matched_gold_clause.add(idx)
                if first_clause_rank is None:
                    first_clause_rank = rank

        # Update Hits@K counts
        for k in doc_hits_at_k:
            if rank <= k and len(matched_gold_doc) > 0:
                doc_hits_at_k[k] = len(matched_gold_doc)
        for k in art_hits_at_k:
            if rank <= k and len(matched_gold_art) > 0:
                art_hits_at_k[k] = len(matched_gold_art)
        for k in clause_hits_at_k:
            if rank <= k and len(matched_gold_clause) > 0:
                clause_hits_at_k[k] = len(matched_gold_clause)

    total_req = len(required_gold)

    # Reciprocal Ranks
    mrr_doc = 1.0 / first_doc_rank if first_doc_rank else 0.0
    mrr_art = 1.0 / first_art_rank if first_art_rank else 0.0
    mrr_clause = 1.0 / first_clause_rank if first_clause_rank else 0.0

    # DCG / nDCG @ 10 (binary relevance)
    dcg = 0.0
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(total_req, 10) + 1))
    for rank, chunk in enumerate(retrieved_chunks[:10], start=1):
        is_rel = any(match_gold_evidence(g, chunk)[1] for g in required_gold)  # Article match relevance
        if is_rel:
            dcg += 1.0 / math.log2(rank + 1)
    ndcg_10 = (dcg / idcg) if idcg > 0 else 0.0

    # Multi-hop coverage
    all_hop_coverage = (len(matched_gold_art) == total_req)
    partial_hop_coverage = (len(matched_gold_art) > 0)
    exact_reference_hit = (len(matched_gold_art) > 0)

    return {
        "has_gold_labels": True,
        "doc_recall": {k: doc_hits_at_k[k] / total_req for k in doc_hits_at_k},
        "article_recall": {k: art_hits_at_k[k] / total_req for k in art_hits_at_k},
        "clause_recall": {k: clause_hits_at_k[k] / total_req for k in clause_hits_at_k},
        "mrr_doc": mrr_doc,
        "mrr_article": mrr_art,
        "mrr_clause": mrr_clause,
        "ndcg_10": ndcg_10,
        "exact_reference_hit": exact_reference_hit,
        "all_hop_coverage": all_hop_coverage,
        "partial_hop_coverage": partial_hop_coverage,
        "matched_required_count": len(matched_gold_art),
        "total_required_count": total_req,
    }


def aggregate_retrieval_metrics(
    case_results: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Aggregate retrieval metrics across all cases with explicit numerator, denominator, coverage, and skip reasons."""
    total_cases = len(case_results)
    scored_cases = [c for c in case_results if c.get("metrics", {}).get("has_gold_labels")]
    skipped_cases = total_cases - len(scored_cases)

    # Status counts
    no_candidate_count = sum(1 for c in case_results if c.get("status") == "no_candidate")
    retrieval_error_count = sum(1 for c in case_results if c.get("status") == "retrieval_error")
    reranker_error_count = sum(1 for c in case_results if c.get("status") == "reranker_error")

    if not scored_cases:
        return {
            "total_cases": total_cases,
            "scored_cases_count": 0,
            "skipped_cases_count": skipped_cases,
            "skip_reasons": {"missing_gold_label": skipped_cases},
            "coverage": 0.0,
            "no_candidate_rate": (no_candidate_count / total_cases) if total_cases else 0.0,
            "retrieval_error_rate": (retrieval_error_count / total_cases) if total_cases else 0.0,
            "reranker_error_rate": (reranker_error_count / total_cases) if total_cases else 0.0,
            "doc_recall": {k: None for k in (1, 3, 5, 10, 24)},
            "article_recall": {k: None for k in (1, 3, 6)},
            "clause_recall": {k: None for k in (1, 3, 6)},
            "mrr_article": None,
            "ndcg_10": None,
            "all_hop_coverage": None,
        }

    denom = len(scored_cases)
    
    # Sum up metrics over scored cases
    doc_recall_sums = {k: 0.0 for k in (1, 3, 5, 10, 24)}
    art_recall_sums = {k: 0.0 for k in (1, 3, 6)}
    clause_recall_sums = {k: 0.0 for k in (1, 3, 6)}
    mrr_sum = 0.0
    ndcg_sum = 0.0
    exact_hit_sum = 0
    all_hop_sum = 0
    partial_hop_sum = 0

    for c in scored_cases:
        m = c["metrics"]
        for k in doc_recall_sums:
            doc_recall_sums[k] += m["doc_recall"][k]
        for k in art_recall_sums:
            art_recall_sums[k] += m["article_recall"][k]
        for k in clause_recall_sums:
            clause_recall_sums[k] += m["clause_recall"][k]
        mrr_sum += m["mrr_article"]
        ndcg_sum += m["ndcg_10"]
        if m["exact_reference_hit"]:
            exact_hit_sum += 1
        if m["all_hop_coverage"]:
            all_hop_sum += 1
        if m["partial_hop_coverage"]:
            partial_hop_sum += 1

    return {
        "total_cases": total_cases,
        "scored_cases_count": denom,
        "skipped_cases_count": skipped_cases,
        "skip_reasons": {"missing_gold_label": skipped_cases},
        "coverage": round(denom / total_cases, 4) if total_cases else 0.0,
        "no_candidate_rate": round(no_candidate_count / total_cases, 4) if total_cases else 0.0,
        "no_candidate_count": no_candidate_count,
        "retrieval_error_rate": round(retrieval_error_count / total_cases, 4) if total_cases else 0.0,
        "retrieval_error_count": retrieval_error_count,
        "reranker_error_rate": round(reranker_error_count / total_cases, 4) if total_cases else 0.0,
        "reranker_error_count": reranker_error_count,
        "doc_recall": {k: round(doc_recall_sums[k] / denom, 4) for k in doc_recall_sums},
        "article_recall": {k: round(art_recall_sums[k] / denom, 4) for k in art_recall_sums},
        "clause_recall": {k: round(clause_recall_sums[k] / denom, 4) for k in clause_recall_sums},
        "mrr_article": round(mrr_sum / denom, 4),
        "ndcg_10": round(ndcg_sum / denom, 4),
        "exact_reference_hit_rate": round(exact_hit_sum / denom, 4),
        "all_hop_coverage_rate": round(all_hop_sum / denom, 4),
        "partial_hop_coverage_rate": round(partial_hop_sum / denom, 4),
        "numerator_scored": denom,
        "denominator_total": total_cases,
    }


def calculate_stage_survival_rates(
    stage_traces: List[RetrievalStageTrace]
) -> Dict[str, Any]:
    """Track candidate retention and survival across all stages of retrieval."""
    if not stage_traces:
        return {}

    total = len(stage_traces)
    stage_counts = {
        "pinecone_hits": sum(1 for t in stage_traces if t.pinecone_hits),
        "lexical_hits": sum(1 for t in stage_traces if t.lexical_hits),
        "merged_document_ids": sum(1 for t in stage_traces if t.merged_document_ids),
        "resolved_document_ids": sum(1 for t in stage_traces if t.resolved_document_ids),
        "locally_selected_chunks": sum(1 for t in stage_traces if t.locally_selected_chunks),
        "reranker_input_chunks": sum(1 for t in stage_traces if t.reranker_input_chunks),
        "reranker_output_chunks": sum(1 for t in stage_traces if t.reranker_output_chunks),
        "final_evidence_chunks": sum(1 for t in stage_traces if t.final_evidence_chunks),
    }

    avg_counts = {
        "avg_pinecone_hits": sum(len(t.pinecone_hits) for t in stage_traces) / total,
        "avg_lexical_hits": sum(len(t.lexical_hits) for t in stage_traces) / total,
        "avg_merged_docs": sum(len(t.merged_document_ids) for t in stage_traces) / total,
        "avg_resolved_docs": sum(len(t.resolved_document_ids) for t in stage_traces) / total,
        "avg_local_chunks": sum(len(t.locally_selected_chunks) for t in stage_traces) / total,
        "avg_reranker_input_chunks": sum(len(t.reranker_input_chunks) for t in stage_traces) / total,
        "avg_reranker_output_chunks": sum(len(t.reranker_output_chunks) for t in stage_traces) / total,
        "avg_final_evidence_chunks": sum(len(t.final_evidence_chunks) for t in stage_traces) / total,
    }

    return {
        "total_queries": total,
        "stage_active_query_counts": stage_counts,
        "stage_survival_rates": {stage: round(cnt / total, 4) for stage, cnt in stage_counts.items()},
        "average_candidates_per_stage": {stage: round(val, 2) for stage, val in avg_counts.items()}
    }
