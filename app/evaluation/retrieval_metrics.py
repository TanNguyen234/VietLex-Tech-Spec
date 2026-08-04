from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from app.evaluation.schemas import CandidateChunk, GoldEvidence, GoldenCase, RetrievalStageTrace


def normalize_legal_identifier(value: Optional[str]) -> str:
    if not value:
        return ""
    normalized = " ".join(value.casefold().split())
    normalized = re.sub(r"(\d+)\.", r"\1", normalized)
    return normalized


def extract_citations_from_text(text: str) -> List[Dict[str, str]]:
    citations: List[Dict[str, str]] = []
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
    max_k_limit: Optional[int] = None,
) -> Dict[str, Any]:
    total_req = len(gold_list)
    if total_req == 0:
        return {
            "candidate_count": len(candidates),
            "scored_case_count": 0,
            "verified_evidence_item_count": 0,
        }

    k_list = (1, 3, 5, 10, 24) if is_doc_stage else (1, 3, 6)
    hits_at_k: Dict[int, int] = {k: 0 for k in k_list}
    matched_indices: Set[int] = set()
    first_rank: Optional[int] = None

    for rank, cand in enumerate(candidates, start=1):
        for idx, g in enumerate(gold_list):
            doc_m, art_m, cl_m = match_gold_to_stage_candidate(g, cand)
            is_hit = doc_m if is_doc_stage else art_m
            if is_hit:
                matched_indices.add(idx)
                if first_rank is None:
                    first_rank = rank

        for k in k_list:
            if rank <= k:
                hits_at_k[k] = len(matched_indices)

    mrr = 1.0 / first_rank if first_rank else 0.0

    res: Dict[str, Any] = {
        "candidate_count": len(candidates),
        "scored_case_count": 1,
        "verified_evidence_item_count": total_req,
        "mrr": round(mrr, 4),
    }

    actual_limit = max_k_limit if max_k_limit is not None else len(candidates)

    for k in k_list:
        prefix = "doc_recall" if is_doc_stage else "article_recall"
        key = f"{prefix}_at_{k}"
        if actual_limit is not None and k > actual_limit:
            res[key] = None
            res[f"{key}_reason"] = "k_exceeds_effective_stage_limit"
        else:
            res[key] = round(hits_at_k[k] / total_req, 4)

    return res


def calculate_case_retrieval_metrics(
    gold_evidence: List[GoldEvidence],
    retrieved_chunks: List[CandidateChunk],
    stage_trace: Optional[RetrievalStageTrace] = None,
) -> Dict[str, Any]:
    verified_gold = [g for g in gold_evidence if g.status == "verified"]
    if not verified_gold:
        return {
            "has_gold_labels": False,
            "skip_reason": "no_verified_gold_label"
        }

    required_gold = [g for g in verified_gold if g.required]
    if not required_gold:
        required_gold = verified_gold
    total_req = len(required_gold)

    # Calculate metrics across stage trace if provided
    stage_metrics: Dict[str, Any] = {}
    if stage_trace:
        stage_metrics["pinecone_document_metrics"] = calculate_stage_candidate_metrics(
            required_gold, stage_trace.pinecone_hits, is_doc_stage=True
        )
        stage_metrics["fts_document_metrics"] = calculate_stage_candidate_metrics(
            required_gold, stage_trace.fts_hits, is_doc_stage=True
        )
        stage_metrics["merged_document_metrics"] = calculate_stage_candidate_metrics(
            required_gold, stage_trace.merged_document_candidates, is_doc_stage=True
        )
        stage_metrics["resolved_document_metrics"] = calculate_stage_candidate_metrics(
            required_gold, stage_trace.resolved_document_candidates, is_doc_stage=True
        )

        stage_metrics["structural_chunk_metrics"] = calculate_stage_candidate_metrics(
            required_gold, stage_trace.structural_chunks_generated, is_doc_stage=False
        )
        stage_metrics["local_selection_metrics"] = calculate_stage_candidate_metrics(
            required_gold, stage_trace.locally_selected_chunks, is_doc_stage=False
        )
        stage_metrics["reranker_input_metrics"] = calculate_stage_candidate_metrics(
            required_gold, stage_trace.reranker_input_chunks, is_doc_stage=False
        )
        stage_metrics["reranker_output_metrics"] = calculate_stage_candidate_metrics(
            required_gold, stage_trace.reranker_output_chunks, is_doc_stage=False
        )
        stage_metrics["final_evidence_metrics"] = calculate_stage_candidate_metrics(
            required_gold, stage_trace.final_evidence_chunks, is_doc_stage=False, max_k_limit=3
        )

    # Document Recall @ K using merged/resolved document candidates
    doc_candidates = []
    if stage_trace and stage_trace.merged_document_candidates:
        doc_candidates = stage_trace.merged_document_candidates
    elif stage_trace and stage_trace.resolved_document_candidates:
        doc_candidates = stage_trace.resolved_document_candidates
    else:
        doc_candidates = retrieved_chunks

    doc_hits_at_k: Dict[int, int] = {k: 0 for k in (1, 3, 5, 10, 24)}
    matched_doc_indices: Set[int] = set()
    first_doc_rank: Optional[int] = None

    for rank, cand in enumerate(doc_candidates, start=1):
        for idx, g in enumerate(required_gold):
            doc_m, _, _ = match_gold_to_stage_candidate(g, cand)
            if doc_m:
                matched_doc_indices.add(idx)
                if first_doc_rank is None:
                    first_doc_rank = rank
        for k in doc_hits_at_k:
            if rank <= k and len(matched_doc_indices) > 0:
                doc_hits_at_k[k] = len(matched_doc_indices)

    # Final evidence Article / Clause recall & MRR
    art_hits_at_k: Dict[int, Optional[int]] = {1: 0, 3: 0, 6: None}
    clause_hits_at_k: Dict[int, Optional[int]] = {1: 0, 3: 0, 6: None}
    matched_art_indices: Set[int] = set()
    matched_clause_indices: Set[int] = set()
    first_art_rank: Optional[int] = None
    first_clause_rank: Optional[int] = None

    final_limit = len(retrieved_chunks)

    for rank, chunk in enumerate(retrieved_chunks, start=1):
        for idx, g in enumerate(required_gold):
            doc_m, art_m, cl_m = match_gold_to_stage_candidate(g, chunk)
            if art_m:
                matched_art_indices.add(idx)
                if first_art_rank is None:
                    first_art_rank = rank
            if cl_m:
                matched_clause_indices.add(idx)
                if first_clause_rank is None:
                    first_clause_rank = rank

        for k in (1, 3):
            if rank <= k:
                art_hits_at_k[k] = len(matched_art_indices)
                clause_hits_at_k[k] = len(matched_clause_indices)

    if final_limit >= 6:
        art_hits_at_k[6] = len(matched_art_indices)
        clause_hits_at_k[6] = len(matched_clause_indices)

    mrr_doc = 1.0 / first_doc_rank if first_doc_rank else 0.0
    mrr_art = 1.0 / first_art_rank if first_art_rank else 0.0
    mrr_clause = 1.0 / first_clause_rank if first_clause_rank else 0.0

    # nDCG @ 10
    dcg = 0.0
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(total_req, 10) + 1))
    for rank, chunk in enumerate(retrieved_chunks[:10], start=1):
        is_rel = any(match_gold_to_stage_candidate(g, chunk)[1] for g in required_gold)
        if is_rel:
            dcg += 1.0 / math.log2(rank + 1)
    ndcg_10 = (dcg / idcg) if idcg > 0 else 0.0

    # Gold Evidence Stage Survival & Tracing
    gold_survival: List[Dict[str, Any]] = []
    if stage_trace:
        pipeline_stages = [
            ("merge", stage_trace.merged_document_candidates, True),
            ("resolution", stage_trace.resolved_document_candidates, True),
            ("structural", stage_trace.structural_chunks_generated, False),
            ("local_selection", stage_trace.locally_selected_chunks, False),
            ("reranker_input", stage_trace.reranker_input_chunks, False),
            ("reranker_output", stage_trace.reranker_output_chunks, False),
            ("final_evidence", stage_trace.final_evidence_chunks, False),
        ]

        for idx, g in enumerate(required_gold):
            presence: Dict[str, bool] = {}

            in_pinecone = any(match_gold_to_stage_candidate(g, c)[0] for c in stage_trace.pinecone_hits)
            in_fts = any(match_gold_to_stage_candidate(g, c)[0] for c in stage_trace.fts_hits)
            presence["present_in_pinecone"] = in_pinecone
            presence["present_in_fts"] = in_fts

            if not in_pinecone and not in_fts:
                first_missing_source = "both_missing"
            elif not in_pinecone:
                first_missing_source = "pinecone"
            elif not in_fts:
                first_missing_source = "fts"
            else:
                first_missing_source = "none"

            first_loss_overall = None
            first_loss_after_union = None

            all_stages = [
                ("pinecone", stage_trace.pinecone_hits, True),
                ("fts", stage_trace.fts_hits, True),
            ] + pipeline_stages

            for stage_name, stage_candidates, is_doc_stage in all_stages:
                present = any(
                    match_gold_to_stage_candidate(g, c)[0 if is_doc_stage else 1]
                    for c in stage_candidates
                )
                presence[f"present_in_{stage_name}"] = present
                if not present and first_loss_overall is None:
                    first_loss_overall = stage_name

            for stage_name, stage_candidates, is_doc_stage in pipeline_stages:
                present = any(
                    match_gold_to_stage_candidate(g, c)[0 if is_doc_stage else 1]
                    for c in stage_candidates
                )
                if not present and first_loss_after_union is None:
                    first_loss_after_union = stage_name

            gold_survival.append({
                "gold_index": idx,
                "gold_document_number": g.document_number,
                "gold_article": g.article,
                "presence": presence,
                "first_loss_stage": first_loss_overall or "none",
                "first_missing_source_stage": first_missing_source,
                "first_loss_after_union_stage": first_loss_after_union or "none",
            })

    all_hop_coverage = (len(matched_art_indices) == total_req)
    partial_hop_coverage = (len(matched_art_indices) > 0)
    exact_reference_hit = (len(matched_art_indices) > 0)

    art_rec_out: Dict[int, Any] = {
        1: round(art_hits_at_k[1] / total_req, 4) if art_hits_at_k[1] is not None else None,
        3: round(art_hits_at_k[3] / total_req, 4) if art_hits_at_k[3] is not None else None,
        6: round(art_hits_at_k[6] / total_req, 4) if art_hits_at_k[6] is not None else None,
    }
    cl_rec_out: Dict[int, Any] = {
        1: round(clause_hits_at_k[1] / total_req, 4) if clause_hits_at_k[1] is not None else None,
        3: round(clause_hits_at_k[3] / total_req, 4) if clause_hits_at_k[3] is not None else None,
        6: round(clause_hits_at_k[6] / total_req, 4) if clause_hits_at_k[6] is not None else None,
    }

    return {
        "has_gold_labels": True,
        "doc_recall": {k: round(doc_hits_at_k[k] / total_req, 4) for k in doc_hits_at_k},
        "article_recall": art_rec_out,
        "clause_recall": cl_rec_out,
        "article_recall_at_6_reason": "k_exceeds_effective_stage_limit" if art_rec_out[6] is None else None,
        "mrr_doc": round(mrr_doc, 4),
        "mrr_article": round(mrr_art, 4),
        "mrr_clause": round(mrr_clause, 4),
        "ndcg_10": round(ndcg_10, 4),
        "exact_reference_hit": exact_reference_hit,
        "all_hop_coverage": all_hop_coverage,
        "partial_hop_coverage": partial_hop_coverage,
        "matched_required_count": len(matched_art_indices),
        "total_required_count": total_req,
        "gold_stage_survival": gold_survival,
        "stage_metrics": stage_metrics,
    }


def aggregate_retrieval_metrics(
    case_results: List[Dict[str, Any]]
) -> Dict[str, Any]:
    total_cases = len(case_results)
    scored_cases = [c for c in case_results if c.get("metrics", {}).get("has_gold_labels")]
    skipped_cases = total_cases - len(scored_cases)

    no_candidate_count = sum(1 for c in case_results if c.get("status") == "no_candidate")
    retrieval_error_count = sum(1 for c in case_results if c.get("status") == "retrieval_error")
    reranker_error_count = sum(1 for c in case_results if c.get("status") == "reranker_error")

    if not scored_cases:
        return {
            "total_cases": total_cases,
            "scored_cases_count": 0,
            "skipped_cases_count": skipped_cases,
            "skip_reasons": {"no_verified_gold_label": skipped_cases},
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
    total_verified_evidence_items = sum(c["metrics"]["total_required_count"] for c in scored_cases)

    doc_recall_sums = {k: 0.0 for k in (1, 3, 5, 10, 24)}
    art_recall_sums = {k: 0.0 for k in (1, 3, 6) if any(c["metrics"]["article_recall"].get(k) is not None for c in scored_cases)}
    clause_recall_sums = {k: 0.0 for k in (1, 3, 6) if any(c["metrics"]["clause_recall"].get(k) is not None for c in scored_cases)}

    mrr_sum = 0.0
    ndcg_sum = 0.0
    exact_hit_sum = 0
    all_hop_sum = 0
    partial_hop_sum = 0

    first_loss_distribution: Dict[str, int] = {}
    first_missing_source_distribution: Dict[str, int] = {}
    first_loss_after_union_distribution: Dict[str, int] = {}

    for c in scored_cases:
        m = c["metrics"]
        for k in doc_recall_sums:
            if m["doc_recall"].get(k) is not None:
                doc_recall_sums[k] += m["doc_recall"][k]

        for k in (1, 3, 6):
            if k in art_recall_sums and m["article_recall"].get(k) is not None:
                art_recall_sums[k] += m["article_recall"][k]
            if k in clause_recall_sums and m["clause_recall"].get(k) is not None:
                clause_recall_sums[k] += m["clause_recall"][k]

        mrr_sum += m["mrr_article"]
        ndcg_sum += m["ndcg_10"]
        if m["exact_reference_hit"]:
            exact_hit_sum += 1
        if m["all_hop_coverage"]:
            all_hop_sum += 1
        if m["partial_hop_coverage"]:
            partial_hop_sum += 1

        for g_surv in m.get("gold_stage_survival", []):
            fl = g_surv.get("first_loss_stage", "none")
            fms = g_surv.get("first_missing_source_stage", "none")
            flu = g_surv.get("first_loss_after_union_stage", "none")
            first_loss_distribution[fl] = first_loss_distribution.get(fl, 0) + 1
            first_missing_source_distribution[fms] = first_missing_source_distribution.get(fms, 0) + 1
            first_loss_after_union_distribution[flu] = first_loss_after_union_distribution.get(flu, 0) + 1

    art_recall_out: Dict[int, Any] = {}
    for k in (1, 3, 6):
        if k in art_recall_sums:
            art_recall_out[k] = round(art_recall_sums[k] / denom, 4)
        else:
            art_recall_out[k] = None

    clause_recall_out: Dict[int, Any] = {}
    for k in (1, 3, 6):
        if k in clause_recall_sums:
            clause_recall_out[k] = round(clause_recall_sums[k] / denom, 4)
        else:
            clause_recall_out[k] = None

    return {
        "total_cases": total_cases,
        "scored_cases_count": denom,
        "verified_evidence_item_count": total_verified_evidence_items,
        "skipped_cases_count": skipped_cases,
        "skip_reasons": {"no_verified_gold_label": skipped_cases},
        "coverage": round(denom / total_cases, 4) if total_cases else 0.0,
        "no_candidate_rate": round(no_candidate_count / total_cases, 4) if total_cases else 0.0,
        "no_candidate_count": no_candidate_count,
        "retrieval_error_rate": round(retrieval_error_count / total_cases, 4) if total_cases else 0.0,
        "retrieval_error_count": retrieval_error_count,
        "reranker_error_rate": round(reranker_error_count / total_cases, 4) if total_cases else 0.0,
        "reranker_error_count": reranker_error_count,
        "doc_recall": {k: round(doc_recall_sums[k] / denom, 4) for k in doc_recall_sums},
        "article_recall": art_recall_out,
        "clause_recall": clause_recall_out,
        "article_recall_at_6_reason": "k_exceeds_effective_stage_limit" if art_recall_out[6] is None else None,
        "mrr_article": round(mrr_sum / denom, 4),
        "ndcg_10": round(ndcg_sum / denom, 4),
        "exact_reference_hit_rate": round(exact_hit_sum / denom, 4),
        "all_hop_coverage_rate": round(all_hop_sum / denom, 4),
        "partial_hop_coverage_rate": round(partial_hop_sum / denom, 4),
        "first_loss_distribution": first_loss_distribution,
        "first_missing_source_distribution": first_missing_source_distribution,
        "first_loss_after_union_distribution": first_loss_after_union_distribution,
        "numerator_scored": denom,
        "denominator_total": total_cases,
    }


def _quantile(sorted_vals: List[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = (len(sorted_vals) - 1) * q
    lower = int(idx)
    upper = lower + 1
    weight = idx - lower
    if upper >= len(sorted_vals):
        return sorted_vals[-1]
    return sorted_vals[lower] * (1.0 - weight) + sorted_vals[upper] * weight


def calculate_stage_survival_rates(
    stage_traces: List[RetrievalStageTrace]
) -> Dict[str, Any]:
    if not stage_traces:
        return {}

    total = len(stage_traces)
    stage_list_map = {
        "pinecone_hits": [len(t.pinecone_hits) for t in stage_traces],
        "fts_hits": [len(t.fts_hits) for t in stage_traces],
        "merged_document_candidates": [len(t.merged_document_candidates) for t in stage_traces],
        "resolved_document_candidates": [len(t.resolved_document_candidates) for t in stage_traces],
        "structural_chunks_generated": [len(t.structural_chunks_generated) for t in stage_traces],
        "locally_selected_chunks": [len(t.locally_selected_chunks) for t in stage_traces],
        "reranker_input_chunks": [len(t.reranker_input_chunks) for t in stage_traces],
        "reranker_output_chunks": [len(t.reranker_output_chunks) for t in stage_traces],
        "final_evidence_chunks": [len(t.final_evidence_chunks) for t in stage_traces],
    }

    stage_counts = {stage: sum(1 for cnt in counts if cnt > 0) for stage, counts in stage_list_map.items()}

    stats: Dict[str, Dict[str, Any]] = {}
    for stage, counts in stage_list_map.items():
        active_counts = [c for c in counts if c > 0]
        sorted_all = sorted(counts)
        sorted_active = sorted(active_counts) if active_counts else [0]

        mean_all = sum(counts) / total
        mean_active = sum(active_counts) / len(active_counts) if active_counts else 0.0

        if stage_counts[stage] == total and total > 0 and mean_all <= 0.0:
            raise ValueError(f"Invariant violation: stage '{stage}' active rate is 100% but mean candidates is {mean_all}")

        stats[stage] = {
            "total_candidates": sum(counts),
            "active_query_count": stage_counts[stage],
            "active_rate": round(stage_counts[stage] / total, 4),
            "mean_per_all_queries": round(mean_all, 2),
            "mean_per_active_query": round(mean_active, 2),
            "min": sorted_all[0] if sorted_all else 0,
            "max": sorted_all[-1] if sorted_all else 0,
            "p50": round(_quantile([float(v) for v in sorted_all], 0.50), 2),
            "p95": round(_quantile([float(v) for v in sorted_all], 0.95), 2),
        }

    return {
        "total_queries": total,
        "stage_statistics": stats,
    }
