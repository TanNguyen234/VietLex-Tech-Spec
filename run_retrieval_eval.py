from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.evaluation.case_selection import CaseSelectionResult, build_cases, select_evaluation_cases
from app.evaluation.gold_sidecar import GoldSidecar, load_gold_sidecar
from app.evaluation.latency_metrics import calculate_stage_latency_summary
from app.evaluation.profiles import EvaluationProfile, get_evaluation_profile
from app.evaluation.reporting import write_run_report
from app.evaluation.retrieval_metrics import (
    aggregate_retrieval_metrics,
    calculate_case_retrieval_metrics,
    calculate_stage_survival_rates,
)
from app.evaluation.run_manifest import (
    atomic_write_json,
    calculate_configuration_fingerprint,
    create_run_manifest,
    generate_unique_run_id,
    get_git_provenance,
    prepare_run_directory,
)
from app.evaluation.schemas import (
    CandidateChunk,
    GoldEvidence,
    GoldenCase,
    RetrievalCaseResult,
    RetrievalStageTrace,
)

DEFAULT_DATASET_PATH = PROJECT_ROOT / "app/data/namsyntax_legal_qa_420.json"
DEFAULT_SIDECAR_PATH = PROJECT_ROOT / "docs/evaluation/gold_labels/namsyntax_legal_qa_420_labels_v2.json"
DEFAULT_SUMMARY_PATH = PROJECT_ROOT / "docs/evaluation/gold_labels/namsyntax_legal_qa_420_audit_summary_v2.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic retrieval-only evaluation over VietLex legal dataset."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--sidecar", type=Path, default=DEFAULT_SIDECAR_PATH)
    parser.add_argument(
        "--profile",
        choices=["legacy", "separated_no_intent", "separated_intent"],
        default="separated_intent",
        help="Evaluation profile (default: separated_intent)",
    )
    parser.add_argument(
        "--rewrite",
        choices=["off", "on"],
        default="off",
        help="Query rewriting mode (default: off)",
    )
    parser.add_argument(
        "--reranker",
        choices=["current", "pinecone-only", "qdrant-only"],
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
        "--gold-policy",
        choices=["all-required-verified", "any-verified", "all-verified", "none"],
        default="all-required-verified",
        help="Selection policy for verified cases (default: all-required-verified)",
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Execute offline preflight check without making provider calls or writing run directories",
    )
    parser.add_argument(
        "--require-clean-git",
        action="store_true",
        help="Require clean git status before execution",
    )
    parser.add_argument("--run-id", type=str, default=None, help="Optional custom Run ID")
    return parser


def perform_pre_execution_validation(
    dataset_path: Path,
    sidecar_path: Path,
    summary_path: Path,
    gold_policy: str,
    verified_only: bool,
    require_clean_git: bool,
    limit: Optional[int] = None,
) -> Tuple[List[GoldenCase], CaseSelectionResult, GoldSidecar, Dict[str, Any]]:
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset file not found: {dataset_path}")

    # 1. Check Git cleanliness if required
    git_sha, git_dirty, _, _, _, diff_sha, _ = get_git_provenance()
    if require_clean_git and git_dirty:
        raise ValueError(
            f"Pre-execution validation failed: git working tree is dirty (SHA {git_sha[:8]}, diff {diff_sha[:8]}). "
            "Clean working tree is required when --require-clean-git is specified."
        )

    # 2. Load sidecar via canonical loader GoldSidecar
    sidecar = load_gold_sidecar(sidecar_path)

    # 3. Load machine-readable audit summary if available
    audit_summary: Dict[str, Any] = {}
    if summary_path.exists():
        try:
            audit_summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if audit_summary.get("total_evidence_items") != sidecar.metadata.total_evidence_items:
                raise ValueError(
                    f"Counter mismatch: audit summary total_evidence_items ({audit_summary.get('total_evidence_items')}) "
                    f"!= sidecar total_evidence_items ({sidecar.metadata.total_evidence_items})"
                )
        except Exception as err:
            raise ValueError(f"Pre-execution validation error reading audit summary {summary_path}: {err}") from err

    # 4. Load dataset and build cases
    raw_dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    all_cases = build_cases(raw_dataset, sidecar.labels_by_case_id)

    # 5. Apply gold policy case selection
    effective_policy = gold_policy if verified_only else "none"
    selection = select_evaluation_cases(all_cases, effective_policy, include_unanswerable=not verified_only)

    selected_cases = selection.selected_cases
    if limit and limit > 0:
        if limit == 30:
            factoids = [c for c in selected_cases if c.question_type == "factoid"][:12]
            multihops = [c for c in selected_cases if c.question_type == "multi-hop"][:12]
            unanswers = [c for c in selected_cases if c.question_type == "unanswerable"][:6]
            selected_cases = factoids + multihops + unanswers
        else:
            selected_cases = selected_cases[:limit]

        selection.selected_cases = selected_cases
        selection.selected_case_ids = [c.case_id for c in selected_cases]
        canonical_json = json.dumps(selection.selected_case_ids, separators=(",", ":"))
        selection.selected_case_ids_sha256 = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        selection.selected_case_count = len(selected_cases)

    # FAIL CLOSED BEFORE PROVIDER CALLS IF SELECTED CASE COUNT IS ZERO (when verified-only)
    if verified_only and selection.selected_case_count == 0:
        print("=" * 60)
        print("PRE-EXECUTION VALIDATION FAILED: Selected case count is ZERO.")
        print(f"Policy: '{gold_policy}', Verified Evidence Items in Sidecar: {sidecar.metadata.total_evidence_items}")
        print("Clean retrieval benchmark is BLOCKED due to 0 verified labels.")
        print("=" * 60)

    return all_cases, selection, sidecar, audit_summary


async def evaluate_single_retrieval_case(
    case: GoldenCase,
    settings: Any,
    effective_profile: EvaluationProfile,
) -> RetrievalCaseResult:
    from app.services.rag_pipeline import rewrite_query
    from app.services.retrieval import RetrievalOutcome, get_legal_retriever

    started = time.perf_counter()
    query_used = case.question
    rewritten_query = None
    t_rewrite = 0.0

    if effective_profile.rewrite_mode == "on":
        rw_start = time.perf_counter()
        rewritten_query = await rewrite_query(case.question)
        t_rewrite = time.perf_counter() - rw_start
        query_used = rewritten_query

    retriever = get_legal_retriever()

    retrieval_start = time.perf_counter()
    outcome: RetrievalOutcome = await retriever.retrieve_detailed(
        query_used, sparse_query=case.question, profile=effective_profile
    )
    t_retrieval = time.perf_counter() - retrieval_start
    t_total = time.perf_counter() - started

    diag = outcome.diagnostics or {}
    stage_trace = diag.get("stage_trace")
    if stage_trace is None:
        stage_trace = RetrievalStageTrace(
            pinecone_hits=[],
            fts_hits=[],
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

    metrics = calculate_case_retrieval_metrics(
        case.gold_evidence,
        retrieved_chunks,
        stage_trace=stage_trace,
    )

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
    sidecar_path = Path(args.sidecar).resolve()
    summary_path = DEFAULT_SUMMARY_PATH

    base_profile = get_evaluation_profile(args.profile)
    effective_profile = dataclasses.replace(
        base_profile,
        rewrite_mode=args.rewrite,
        reranker_mode=args.reranker,
    )

    # Perform shared pre-execution validation
    all_cases, selection, sidecar, audit_summary = perform_pre_execution_validation(
        dataset_path=dataset_path,
        sidecar_path=sidecar_path,
        summary_path=summary_path,
        gold_policy=args.gold_policy,
        verified_only=args.verified_only,
        require_clean_git=args.require_clean_git,
        limit=args.limit,
    )

    dataset_sha256 = hashlib.sha256(dataset_path.read_bytes()).hexdigest()

    config_dict = {
        "profile_name": effective_profile.name,
        "profile": effective_profile.to_dict(),
        "eval_mode": "retrieval-only",
        "judge_mode": "none",
        "guardrail_mode": "off",
        "rewrite_mode": effective_profile.rewrite_mode,
        "reranker_provider": effective_profile.reranker_mode,
        "gold_policy": args.gold_policy,
        "selected_case_count": selection.selected_case_count,
        "selected_case_ids_sha256": selection.selected_case_ids_sha256,
    }
    fp = calculate_configuration_fingerprint(config_dict)

    # -------------------------------------------------------------
    # PREFLIGHT EXECUTION MODE (ZERO PROVIDER CALLS, NO RUN DIRS)
    # -------------------------------------------------------------
    if args.preflight:
        print("=" * 60, flush=True)
        print(f"OFFLINE PREFLIGHT CHECK — PROFILE: {effective_profile.name}", flush=True)
        print(f"Dataset: {dataset_path} (SHA: {dataset_sha256[:8]})", flush=True)
        print(f"Sidecar: {sidecar_path} (SHA: {sidecar.metadata.sidecar_sha256[:8]})", flush=True)
        print(f"Gold Policy: {args.gold_policy} | Verified Only: {args.verified_only}", flush=True)
        print(f"Configuration Fingerprint: {fp}", flush=True)
        print(f"Declared Cases: {sidecar.metadata.total_cases} | Declared Evidence Items: {sidecar.metadata.total_evidence_items}", flush=True)
        print(f"Selected Cases ({selection.selected_case_count}): {selection.selected_case_ids}", flush=True)
        print(f"Selected Case IDs SHA-256: {selection.selected_case_ids_sha256}", flush=True)
        print(f"Provider Calls: 0", flush=True)
        print("=" * 60, flush=True)

        preflight_dir = PROJECT_ROOT / "docs/evaluation/preflight"
        preflight_dir.mkdir(parents=True, exist_ok=True)

        preflight_payload = {
            "dataset_sha256": dataset_sha256,
            "sidecar_sha256": sidecar.metadata.sidecar_sha256,
            "sidecar_schema_version": sidecar.metadata.schema_version,
            "declared_total_cases": sidecar.metadata.total_cases,
            "declared_total_evidence_items": sidecar.metadata.total_evidence_items,
            "loaded_label_count": len(sidecar.labels),
            "unique_labeled_case_count": len(sidecar.labels_by_case_id),
            "gold_policy": args.gold_policy,
            "verified_only": args.verified_only,
            "selected_case_count": selection.selected_case_count,
            "selected_case_ids": selection.selected_case_ids,
            "selected_case_ids_sha256": selection.selected_case_ids_sha256,
            "answerable_selected_count": selection.answerable_selected_count,
            "fully_verified_factoid_count": selection.fully_verified_factoid_count,
            "fully_verified_multihop_count": selection.fully_verified_multihop_count,
            "partial_verified_multihop_count": selection.partial_verified_multihop_count,
            "excluded_unanswerable_count": selection.excluded_unanswerable_count,
            "excluded_no_verified_label_count": selection.excluded_no_verified_label_count,
            "verified_evidence_item_count": selection.verified_evidence_item_count,
            "profile_name": effective_profile.name,
            "profile": effective_profile.to_dict(),
            "configuration_fingerprint": fp,
            "provider_calls": 0,
        }

        # Immutable preflight artifact per profile
        profile_preflight_path = preflight_dir / f"preflight_{effective_profile.name}.json"
        atomic_write_json(profile_preflight_path, preflight_payload)

        # Convenience copy latest_preflight.json
        latest_preflight_path = preflight_dir / "latest_preflight.json"
        atomic_write_json(latest_preflight_path, preflight_payload)

        # Build / update comparison artifact preflight_comparison.json across profiles
        comparison_path = preflight_dir / "preflight_comparison.json"
        comparison_dict: Dict[str, Any] = {}
        if comparison_path.exists():
            try:
                comparison_dict = json.loads(comparison_path.read_text(encoding="utf-8"))
            except Exception:
                comparison_dict = {}

        comparison_dict[effective_profile.name] = {
            "profile_name": effective_profile.name,
            "configuration_fingerprint": fp,
            "selected_case_count": selection.selected_case_count,
            "selected_case_ids_sha256": selection.selected_case_ids_sha256,
            "retrieval_document_limit": effective_profile.retrieval_document_limit,
            "resolved_document_limit": effective_profile.resolved_document_limit,
            "local_chunks_per_document": effective_profile.local_chunks_per_document,
            "rerank_input_limit": effective_profile.rerank_input_limit,
            "intent_scoring_enabled": effective_profile.intent_scoring_enabled,
        }
        atomic_write_json(comparison_path, comparison_dict)

        # Exit non-zero if selected_case_count == 0 when verified-only is specified
        if args.verified_only and selection.selected_case_count == 0:
            print("Preflight check exited non-zero: 0 selected cases under verified-only policy.")
            sys.exit(1)

        return preflight_payload

    # -------------------------------------------------------------
    # LIVE RETRIEVAL EVALUATION RUN
    # -------------------------------------------------------------
    if args.verified_only and selection.selected_case_count == 0:
        raise ValueError("Cannot execute retrieval evaluation: selected case count is ZERO.")

    cases = selection.selected_cases

    run_id = args.run_id or generate_unique_run_id(
        prefix="retrieval", config_fingerprint=fp
    )

    manifest = create_run_manifest(
        run_id=run_id,
        eval_mode="retrieval-only",
        judge_mode="none",
        guardrail_mode="off",
        rewrite_mode=effective_profile.rewrite_mode,
        reranker_provider=effective_profile.reranker_mode,
        dataset_path=dataset_path,
        settings=settings,
        command_str=" ".join(sys.argv),
        profile_name=effective_profile.name,
        gold_sidecar_path=sidecar_path,
        profile_obj=effective_profile,
        gold_policy=args.gold_policy,
        selected_case_ids=selection.selected_case_ids,
    )

    runs_base_dir = PROJECT_ROOT / "docs/evaluation/runs"
    run_dir = prepare_run_directory(runs_base_dir, manifest.run_id)

    print("=" * 60, flush=True)
    print(f"RETRIEVAL EVALUATION RUN: {manifest.run_id}", flush=True)
    print(
        f"cases={len(cases)} profile={effective_profile.name} rewrite={effective_profile.rewrite_mode}",
        flush=True,
    )
    print(
        f"reranker={effective_profile.reranker_mode} concurrency={args.concurrency} gold_policy={args.gold_policy}",
        flush=True,
    )
    print("=" * 60, flush=True)

    semaphore = asyncio.Semaphore(args.concurrency)
    results_map: Dict[str, RetrievalCaseResult] = {}

    async def worker(case: GoldenCase) -> RetrievalCaseResult:
        async with semaphore:
            return await evaluate_single_retrieval_case(
                case,
                settings,
                effective_profile,
            )

    tasks = [asyncio.create_task(worker(case)) for case in cases]
    completed_count = 0
    for completed_task in asyncio.as_completed(tasks):
        result = await completed_task
        results_map[result.case_id] = result
        completed_count += 1
        print(
            f"[{completed_count}/{len(cases)}] Completed Case [{result.case_id}]: status={result.status} latency={result.latency['t_retrieval']:.2f}s",
            flush=True,
        )

    # Preserve dataset case ordering
    ordered_results: List[RetrievalCaseResult] = [results_map[c.case_id] for c in cases]
    case_results_dict = [res.model_dump() for res in ordered_results]
    retrieval_summary = aggregate_retrieval_metrics(case_results_dict)
    stage_traces = [res.stage_trace for res in ordered_results]
    stage_survival_summary = calculate_stage_survival_rates(stage_traces)
    latency_summary = calculate_stage_latency_summary(
        [res.latency for res in ordered_results]
    )

    atomic_write_json(run_dir / "manifest.json", manifest.model_dump())
    atomic_write_json(run_dir / "configuration.json", manifest.configuration)
    atomic_write_json(
        run_dir / "evaluation_case_set.json",
        {
            "selected_case_count": selection.selected_case_count,
            "selected_case_ids": selection.selected_case_ids,
            "selected_case_ids_sha256": selection.selected_case_ids_sha256,
        },
    )
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
