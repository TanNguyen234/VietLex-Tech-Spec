from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# Ensure UTF-8 output on Windows with error handling
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.evaluation.latency_metrics import calculate_stage_latency_summary
from app.evaluation.reporting import write_run_report
from app.evaluation.retrieval_metrics import (
    aggregate_retrieval_metrics,
    calculate_case_retrieval_metrics,
    calculate_stage_survival_rates,
    extract_citations_from_text,
)
from app.evaluation.run_manifest import (
    atomic_write_json,
    create_run_manifest,
    generate_unique_run_id,
)
from app.evaluation.schemas import (
    CandidateChunk,
    GoldEvidence,
    GoldenCase,
    RetrievalCaseResult,
    RetrievalStageTrace,
)

DEFAULT_DATASET_PATH = PROJECT_ROOT / "app/data/namsyntax_legal_qa_420.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic retrieval-only evaluation over VietLex legal dataset."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument(
        "--profile",
        choices=["legacy", "separated_no_intent", "separated_intent"],
        default="separated_intent",
        help="Evaluation profile (default: separated_intent)",
    )
    parser.add_argument(
        "--mode",
        choices=["retrieval-only", "answer"],
        default="retrieval-only",
        help="Evaluation mode (default: retrieval-only)",
    )
    parser.add_argument(
        "--rewrite",
        choices=["off", "on"],
        default="off",
        help="Query rewriting mode (default: off)",
    )
    parser.add_argument(
        "--guardrails",
        choices=["off", "shadow", "enforce"],
        default="off",
        help="Guardrails mode (default: off)",
    )
    parser.add_argument(
        "--reranker",
        choices=["current", "pinecone-bge", "qdrant-colbert"],
        default="current",
        help="Reranker provider selection (default: current)",
    )
    parser.add_argument(
        "--concurrency", type=int, default=1, help="Pipeline concurrency (default: 1)"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit maximum number of cases to evaluate"
    )
    parser.add_argument(
        "--verified-only",
        action="store_true",
        help="Filter evaluation to cases with verified gold evidence in the current corpus",
    )
    parser.add_argument(
        "--judge",
        choices=["none", "ragas"],
        default="none",
        help="LLM judge mode (default: none)",
    )
    parser.add_argument("--run-id", type=str, default=None, help="Optional custom Run ID")
    return parser


def parse_golden_case(raw_item: dict, index: int) -> GoldenCase:
    question = str(raw_item.get("question") or "").strip()
    q_type = str(raw_item.get("question_type") or "factoid")
    answerable = q_type != "unanswerable"
    ref_ans = str(raw_item.get("ground_truth_answer") or "").strip()
    ref_contexts = list(raw_item.get("ground_truth_context") or [])

    gold_evidence_list: List[GoldEvidence] = []
    if "gold_evidence" in raw_item and isinstance(raw_item["gold_evidence"], list):
        for g in raw_item["gold_evidence"]:
            gold_evidence_list.append(GoldEvidence(**g))
    else:
        # Extract citations from ground_truth_context for diagnostic evidence matching
        for ctx in ref_contexts:
            cites = extract_citations_from_text(ctx)
            for cite in cites:
                gold_evidence_list.append(
                    GoldEvidence(
                        document_number=cite.get("document_number"),
                        article=cite.get("article"),
                        clause=cite.get("clause"),
                        required=True,
                        status="missing_gold_label",
                    )
                )

    if not gold_evidence_list:
        gold_evidence_list.append(
            GoldEvidence(
                required=True,
                status="missing_gold_label",
            )
        )

    case_id = str(raw_item.get("case_id") or f"case_{index+1:03d}")

    return GoldenCase(
        case_id=case_id,
        question=question,
        question_type=q_type,
        answerable=answerable,
        reference_answer=ref_ans,
        reference_contexts=ref_contexts,
        gold_evidence=gold_evidence_list,
        expected_numbers=raw_item.get("expected_numbers", []),
        expected_dates=raw_item.get("expected_dates", []),
        expected_entities=raw_item.get("expected_entities", []),
    )


async def evaluate_single_retrieval_case(
    case: GoldenCase,
    settings: Any,
    rewrite_mode: str,
    reranker_provider: str,
    profile_name: str = "separated_intent",
) -> RetrievalCaseResult:
    from app.services.rag_pipeline import rewrite_query
    from app.services.retrieval import RetrievalOutcome, get_legal_retriever

    started = time.perf_counter()
    query_used = case.question
    rewritten_query = None
    t_rewrite = 0.0

    if rewrite_mode == "on":
        rw_start = time.perf_counter()
        rewritten_query = await rewrite_query(case.question)
        t_rewrite = time.perf_counter() - rw_start
        query_used = rewritten_query

    retriever = get_legal_retriever()
    
    # Reranker provider override if specified
    if reranker_provider == "pinecone-bge":
        settings.PINECONE_RERANK_MODEL = "bge-reranker-v2-m3"
    elif reranker_provider == "qdrant-colbert":
        settings.QDRANT_RERANK_MODEL = "answerdotai/answerai-colbert-small-v1"

    retrieval_start = time.perf_counter()
    outcome: RetrievalOutcome = await retriever.retrieve_detailed(
        query_used, sparse_query=case.question, profile=profile_name
    )
    t_retrieval = time.perf_counter() - retrieval_start
    t_total = time.perf_counter() - started

    # Extract stage traces
    diag = outcome.diagnostics or {}
    stage_trace = diag.get("stage_trace")
    if stage_trace is None:
        stage_trace = RetrievalStageTrace(
            pinecone_hits=[],
            lexical_hits=[],
            merged_document_candidates=[],
            resolved_document_candidates=[],
            structural_chunks_generated=[],
            locally_selected_chunks=[],
            reranker_input_chunks=[],
            reranker_output_chunks=[],
            final_evidence_chunks=[],
        )

    retrieved_chunks = [
        CandidateChunk(
            document_id=chunk.document_id,
            document_number=chunk.document_number,
            title=chunk.title,
            source_url=chunk.source_url,
            citation=chunk.citation,
            article=chunk.article,
            clause=chunk.clause,
            text=chunk.text,
            token_count=chunk.token_count,
        )
        for chunk in outcome.evidence
    ]

    # Calculate deterministic metrics for this case
    metrics = calculate_case_retrieval_metrics(case.gold_evidence, retrieved_chunks)

    latency = {
        "t_rewrite": round(t_rewrite, 4),
        "t_retrieval": round(t_retrieval, 4),
        "t_total": round(t_total, 4),
        **{k: round(v, 4) for k, v in outcome.latency.items()},
    }

    return RetrievalCaseResult(
        case_id=case.case_id,
        question=case.question,
        question_type=case.question_type,
        answerable=case.answerable,
        query_used=query_used,
        original_query=case.question,
        rewritten_query=rewritten_query,
        status=outcome.status,
        retrieved_evidence=retrieved_chunks,
        stage_trace=stage_trace,
        latency=latency,
        metrics=metrics,
        error=outcome.error,
    )


async def run_retrieval_evaluation(arguments=None) -> Dict[str, Any]:
    args = arguments or build_parser().parse_args()
    if args.concurrency <= 0:
        raise ValueError("concurrency must be positive.")

    settings = get_settings()
    dataset_path = Path(args.dataset).resolve()
    if not dataset_path.exists():
        raise FileNotFoundError(f"Could not find dataset at: {dataset_path}")

    import json

    raw_dataset = json.loads(dataset_path.read_text(encoding="utf-8"))

    sidecar_path = PROJECT_ROOT / "docs/evaluation/gold_labels/namsyntax_legal_qa_420_labels.json"
    sidecar_labels: dict[str, list[dict]] = {}
    if sidecar_path.exists():
        raw_labels = json.loads(sidecar_path.read_text(encoding="utf-8"))
        if isinstance(raw_labels, list):
            for label in raw_labels:
                cid = label.get("case_id")
                if cid:
                    sidecar_labels.setdefault(cid, []).append(label)
        elif isinstance(raw_labels, dict):
            sidecar_labels = raw_labels

    cases = []
    for idx, item in enumerate(raw_dataset):
        case_id = str(item.get("case_id") or f"case_{idx+1:03d}")
        if case_id in sidecar_labels:
            item["gold_evidence"] = sidecar_labels[case_id]
        cases.append(parse_golden_case(item, idx))
    if args.verified_only:
        cases = [
            c for c in cases
            if any(g.status == "verified" for g in c.gold_evidence)
        ]

    if args.limit and args.limit > 0:
        # Sample evenly across groups if limit matches 30 (12 factoid, 12 multi-hop, 6 unanswerable)
        if args.limit == 30:
            factoids = [c for c in cases if c.question_type == "factoid"][:12]
            multihops = [c for c in cases if c.question_type == "multi-hop"][:12]
            unanswers = [c for c in cases if c.question_type == "unanswerable"][:6]
            cases = factoids + multihops + unanswers
        else:
            cases = cases[: args.limit]

    manifest = create_run_manifest(
        run_id=args.run_id or generate_unique_run_id(prefix="retrieval"),
        eval_mode="retrieval-only",
        judge_mode=args.judge,
        guardrail_mode=args.guardrails,
        rewrite_mode=args.rewrite,
        reranker_provider=args.reranker,
        dataset_path=dataset_path,
        settings=settings,
        command_str=" ".join(sys.argv),
    )

    print("=" * 60, flush=True)
    print(f"RETRIEVAL EVALUATION RUN: {manifest.run_id}", flush=True)
    print(f"cases={len(cases)} mode={args.mode} rewrite={args.rewrite} guardrails={args.guardrails}", flush=True)
    print(f"reranker={args.reranker} concurrency={args.concurrency} judge={args.judge}", flush=True)
    print("=" * 60, flush=True)

    semaphore = asyncio.Semaphore(args.concurrency)
    results: List[RetrievalCaseResult] = []

    async def worker(case: GoldenCase) -> RetrievalCaseResult:
        # Acquire online pipeline semaphore strictly during online retrieval execution
        async with semaphore:
            return await evaluate_single_retrieval_case(
                case,
                settings,
                args.rewrite,
                args.reranker,
                profile_name=args.profile,
            )

    tasks = [asyncio.create_task(worker(case)) for case in cases]
    completed_count = 0
    for completed_task in asyncio.as_completed(tasks):
        result = await completed_task
        results.append(result)
        completed_count += 1
        print(f"[{completed_count}/{len(cases)}] Completed Case [{result.case_id}]: status={result.status} latency={result.latency['t_retrieval']:.2f}s", flush=True)

    # Offline Metric Computation (after semaphore release!)
    case_results_dict = [res.model_dump() for res in results]
    retrieval_summary = aggregate_retrieval_metrics(case_results_dict)
    stage_traces = [res.stage_trace for res in results]
    stage_survival_summary = calculate_stage_survival_rates(stage_traces)
    latency_summary = calculate_stage_latency_summary([res.latency for res in results])

    # Atomic write run artifacts into docs/evaluation/runs/<run-id>/
    run_dir = PROJECT_ROOT / "docs/evaluation/runs" / manifest.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    atomic_write_json(run_dir / "manifest.json", manifest.model_dump())
    atomic_write_json(run_dir / "configuration.json", manifest.configuration)
    atomic_write_json(run_dir / "retrieval_results.json", case_results_dict)

    report_path = write_run_report(
        run_dir=run_dir,
        manifest=manifest,
        retrieval_summary=retrieval_summary,
        stage_survival_summary=stage_survival_summary,
        latency_summary=latency_summary,
        answer_summary=None,
        case_results=case_results_dict,
    )

    print("=" * 60)
    print(f"Retrieval Evaluation Completed. Report saved to:\n{report_path}")
    print("=" * 60)

    return {
        "manifest": manifest.model_dump(),
        "summary": retrieval_summary,
        "stage_survival": stage_survival_summary,
        "latency": latency_summary,
        "report_path": str(report_path),
    }


if __name__ == "__main__":
    asyncio.run(run_retrieval_evaluation())
