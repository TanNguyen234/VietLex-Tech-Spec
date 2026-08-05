from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from app.evaluation.schemas import (
    CandidateChunk,
    EvidenceStatus,
    GoldEvidence,
    GoldenCase,
    RequiredLevel,
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
    citations: List[Dict[str, str]] = []
    
    items = []
    for m in re.finditer(r"\b\d{1,4}/\d{4}/[A-ZĐ0-9-]+\b", text, re.IGNORECASE):
        items.append((m.start(), "doc", m.group().upper()))
    for m in re.finditer(r"\bĐiều\s+\d+[A-Za-z]?\b", text, re.IGNORECASE):
        items.append((m.start(), "art", m.group()))
    for m in re.finditer(r"\bKhoản\s+\d+\b", text, re.IGNORECASE):
        items.append((m.start(), "clause", m.group()))
        
    if not items:
        return citations

    items.sort(key=lambda x: x[0])
    
    current_art = ""
    current_cl = ""
    for pos, type_, val in items:
        if type_ == "clause":
            current_cl = val
        elif type_ == "art":
            current_art = val
        elif type_ == "doc":
            cit = {
                "document_number": val,
                "article": current_art,
                "clause": current_cl
            }
            if cit not in citations:
                citations.append(cit)
            current_art = ""
            current_cl = ""
            
    if current_art or current_cl:
        cit = {
            "document_number": "",
            "article": current_art,
            "clause": current_cl
        }
        if cit not in citations:
            citations.append(cit)
            
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


def calculate_case_retrieval_metrics(
    gold_evidence: List[GoldEvidence],
    retrieved_chunks: List[CandidateChunk],
    stage_trace: Optional[RetrievalStageTrace] = None,
    capacities: Optional[RetrievalStageCapacities] = None,
) -> Dict[str, Any]:
    caps = capacities or RetrievalStageCapacities()

    verified_gold = [g for g in gold_evidence if g.status == EvidenceStatus.VERIFIED]
    if not verified_gold:
        return {
            "has_gold_labels": False,
            "skip_reason": "no_verified_gold_label"
        }

    required_gold = [g for g in verified_gold if g.required]
    if not required_gold:
        required_gold = verified_gold
    total_req = len(required_gold)

    doc_gold = [g for g in required_gold if g.status == EvidenceStatus.VERIFIED or g.required_level == RequiredLevel.DOCUMENT]
    art_gold = [g for g in required_gold if g.required_level in (RequiredLevel.ARTICLE, RequiredLevel.CLAUSE)]
    clause_gold = [g for g in required_gold if g.required_level == RequiredLevel.CLAUSE]

    stage_metrics: Dict[str, Any] = {}
    if stage_trace:
        stage_metrics["pinecone_document_metrics"] = calculate_stage_candidate_metrics(
            required_gold, stage_trace.pinecone_hits, is_doc_stage=True, stage_capacity=caps.pinecone_document_limit
        )
        stage_metrics["fts_document_metrics"] = calculate_stage_candidate_metrics(
            required_gold, stage_trace.fts_hits, is_doc_stage=True, stage_capacity=caps.fts_document_limit
        )
        stage_metrics["merged_document_metrics"] = calculate_stage_candidate_metrics(
            required_gold, stage_trace.merged_document_candidates, is_doc_stage=True, stage_capacity=caps.merged_document_limit
        )
        stage_metrics["resolved_document_metrics"] = calculate_stage_candidate_metrics(
            required_gold, stage_trace.resolved_document_candidates, is_doc_stage=True, stage_capacity=caps.resolved_document_limit
        )

        stage_metrics["structural_chunk_metrics"] = calculate_stage_candidate_metrics(
            required_gold, stage_trace.structural_chunks_generated, is_doc_stage=False, stage_capacity=caps.structural_chunk_limit
        )
        stage_metrics["local_selection_metrics"] = calculate_stage_candidate_metrics(
            required_gold, stage_trace.locally_selected_chunks, is_doc_stage=False, stage_capacity=caps.local_chunks_limit
        )
        stage_metrics["reranker_input_metrics"] = calculate_stage_candidate_metrics(
            required_gold, stage_trace.reranker_input_chunks, is_doc_stage=False, stage_capacity=caps.rerank_input_limit
        )
        stage_metrics["reranker_output_metrics"] = calculate_stage_candidate_metrics(
            required_gold, stage_trace.reranker_output_chunks, is_doc_stage=False, stage_capacity=caps.rerank_return_limit
        )
        stage_metrics["final_evidence_metrics"] = calculate_stage_candidate_metrics(
            required_gold, stage_trace.final_evidence_chunks, is_doc_stage=False, stage_capacity=caps.final_evidence_limit
        )

    # Document Recall @ K
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
        for idx, g in enumerate(doc_gold):
            doc_m, _, _ = match_gold_to_stage_candidate(g, cand)
            if doc_m:
                matched_doc_indices.add(idx)
                if first_doc_rank is None:
                    first_doc_rank = rank
        for k in doc_hits_at_k:
            if rank <= k:
                doc_hits_at_k[k] = len(matched_doc_indices)

    doc_recall_res: Dict[int, Optional[float]] = {}
    for k in (1, 3, 5, 10, 24):
        if caps.resolved_document_limit is not None and k > caps.resolved_document_limit:
            doc_recall_res[k] = None
        elif len(doc_gold) == 0:
            doc_recall_res[k] = None
        else:
            doc_recall_res[k] = round(doc_hits_at_k[k] / len(doc_gold), 4)

    # Final evidence Article & Clause Recall / MRR
    art_hits_at_k: Dict[int, Optional[int]] = {1: 0, 3: 0, 6: 0}
    clause_hits_at_k: Dict[int, Optional[int]] = {1: 0, 3: 0, 6: 0}
    matched_art_indices: Set[int] = set()
    matched_clause_indices: Set[int] = set()
    first_art_rank: Optional[int] = None
    first_clause_rank: Optional[int] = None

    for rank, chunk in enumerate(retrieved_chunks, start=1):
        for idx, g in enumerate(art_gold):
            _, art_m, _ = match_gold_to_stage_candidate(g, chunk)
            if art_m:
                matched_art_indices.add(idx)
                if first_art_rank is None:
                    first_art_rank = rank
        for idx, g in enumerate(clause_gold):
            _, _, cl_m = match_gold_to_stage_candidate(g, chunk)
            if cl_m:
                matched_clause_indices.add(idx)
                if first_clause_rank is None:
                    first_clause_rank = rank

        for k in (1, 3, 6):
            if rank <= k:
                art_hits_at_k[k] = len(matched_art_indices)
                clause_hits_at_k[k] = len(matched_clause_indices)

    art_recall_res: Dict[int, Optional[float]] = {}
    clause_recall_res: Dict[int, Optional[float]] = {}
    for k in (1, 3, 6):
        if caps.final_evidence_limit is not None and k > caps.final_evidence_limit:
            art_recall_res[k] = None
            clause_recall_res[k] = None
        else:
            art_recall_res[k] = round(art_hits_at_k[k] / len(art_gold), 4) if art_gold else None
            clause_recall_res[k] = round(clause_hits_at_k[k] / len(clause_gold), 4) if clause_gold else None

    mrr_doc = (round(1.0 / first_doc_rank, 4) if first_doc_rank else 0.0) if doc_gold else None
    mrr_art = (round(1.0 / first_art_rank, 4) if first_art_rank else 0.0) if art_gold else None
    mrr_clause = (round(1.0 / first_clause_rank, 4) if first_clause_rank else 0.0) if clause_gold else None

    all_hop = (len(matched_art_indices) == total_req) if total_req > 0 else False
    partial_hop = (len(matched_art_indices) > 0)

    return {
        "has_gold_labels": True,
        "total_required_labels": total_req,
        "verified_doc_gold_count": len(doc_gold),
        "verified_article_gold_count": len(art_gold),
        "verified_clause_gold_count": len(clause_gold),
        "doc_recall": doc_recall_res,
        "article_recall": art_recall_res,
        "clause_recall": clause_recall_res,
        "mrr_document": mrr_doc,
        "mrr_article": mrr_art,
        "mrr_clause": mrr_clause,
        "all_hop_coverage": all_hop,
        "partial_hop_coverage": partial_hop,
        "stage_metrics": stage_metrics,
    }


def aggregate_retrieval_metrics(
    case_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    total_cases = len(case_results)
    if total_cases == 0:
        return {"total_cases": 0, "scored_cases_count": 0, "coverage": 0.0}

    scored_cases = [c for c in case_results if c.get("metrics", {}).get("has_gold_labels", False)]
    scored_count = len(scored_cases)
    coverage = round(scored_count / total_cases, 4)

    if scored_count == 0:
        return {
            "total_cases": total_cases,
            "scored_cases_count": 0,
            "skipped_cases_count": total_cases - scored_count,
            "coverage": 0.0,
        }

    # Helper for macro averaging optional float metrics
    def macro_avg(metric_fn) -> Optional[float]:
        vals = [metric_fn(c["metrics"]) for c in scored_cases if metric_fn(c["metrics"]) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    result = {
        "total_cases": total_cases,
        "scored_cases_count": scored_count,
        "skipped_cases_count": total_cases - scored_count,
        "coverage": coverage,
        "macro_doc_recall_at_1": macro_avg(lambda m: m.get("doc_recall", {}).get(1)),
        "macro_doc_recall_at_3": macro_avg(lambda m: m.get("doc_recall", {}).get(3)),
        "macro_doc_recall_at_5": macro_avg(lambda m: m.get("doc_recall", {}).get(5)),
        "macro_doc_recall_at_10": macro_avg(lambda m: m.get("doc_recall", {}).get(10)),
        "macro_article_recall_at_1": macro_avg(lambda m: m.get("article_recall", {}).get(1)),
        "macro_article_recall_at_3": macro_avg(lambda m: m.get("article_recall", {}).get(3)),
        "macro_article_recall_at_6": macro_avg(lambda m: m.get("article_recall", {}).get(6)),
        "macro_clause_recall_at_1": macro_avg(lambda m: m.get("clause_recall", {}).get(1)),
        "macro_clause_recall_at_3": macro_avg(lambda m: m.get("clause_recall", {}).get(3)),
        "macro_clause_recall_at_6": macro_avg(lambda m: m.get("clause_recall", {}).get(6)),
        "macro_mrr_document": macro_avg(lambda m: m.get("mrr_document")),
        "macro_mrr_article": macro_avg(lambda m: m.get("mrr_article")),
        "macro_mrr_clause": macro_avg(lambda m: m.get("mrr_clause")),
        "macro_all_hop_coverage": macro_avg(lambda m: 1.0 if m.get("all_hop_coverage") else 0.0),
        "macro_partial_hop_coverage": macro_avg(lambda m: 1.0 if m.get("partial_hop_coverage") else 0.0),
    }

    if scored_count > 0 and scored_cases[0].get("metrics", {}).get("stage_metrics"):
        stage_names = scored_cases[0]["metrics"]["stage_metrics"].keys()
        aggr_stages = {}
        for stage in stage_names:
            aggr_stages[stage] = {
                "avg_scored_case_count": macro_avg(lambda m: m.get("stage_metrics", {}).get(stage, {}).get("scored_case_count")),
            }
            # Only add specific metric keys like candidate_count, recall, etc.
            keys = set()
            for c in scored_cases:
                metrics = c.get("metrics", {})
                sm = metrics.get("stage_metrics", {})
                sm_stage = sm.get(stage, {})
                keys.update(k for k, v in sm_stage.items() if isinstance(v, (int, float)) and k != "scored_case_count" and not k.startswith("micro_"))
            
            for k in keys:
                aggr_stages[stage][f"macro_{k}"] = macro_avg(lambda m: m.get("stage_metrics", {}).get(stage, {}).get(k))

            # Micro metrics for stage survival
            total_gold = sum(c["metrics"].get("stage_metrics", {}).get(stage, {}).get("total_gold_items", 0) for c in scored_cases)
            if total_gold > 0:
                found_doc = sum(c["metrics"].get("stage_metrics", {}).get(stage, {}).get("found_gold_documents", 0) for c in scored_cases)
                found_art = sum(c["metrics"].get("stage_metrics", {}).get(stage, {}).get("found_gold_articles", 0) for c in scored_cases)
                found_clause = sum(c["metrics"].get("stage_metrics", {}).get(stage, {}).get("found_gold_clauses", 0) for c in scored_cases)
                aggr_stages[stage]["micro_doc_survival_rate"] = round(found_doc / total_gold, 4)
                aggr_stages[stage]["micro_article_survival_rate"] = round(found_art / total_gold, 4)
                aggr_stages[stage]["micro_clause_survival_rate"] = round(found_clause / total_gold, 4)

        result["stage_metrics"] = aggr_stages

    return result


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
