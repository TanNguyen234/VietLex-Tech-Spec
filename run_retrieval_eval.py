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
from typing import Any, Dict, List, Optional, Tuple

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
    calculate_dataset_sha256,
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
        help="Execute offline preflight check for a single profile without making provider calls",
    )
    parser.add_argument(
        "--preflight-all-profiles",
        action="store_true",
        help="Execute batch offline preflight check for all profiles without making provider calls",
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

    raw_dataset = json.loads(dataset_path.read_bytes().decode("utf-8"))
    raw_dataset_case_ids = [f"case_{idx:03d}" for idx in range(1, len(raw_dataset) + 1)]

    # 2. Load sidecar via canonical loader GoldSidecar validating exact case-set equality
    sidecar = load_gold_sidecar(sidecar_path, dataset_case_ids=raw_dataset_case_ids)

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

    # 4. Build cases
    all_cases = build_cases(raw_dataset, sidecar.labels_by_case_id)

    # 5. Apply gold policy case selection
    effective_policy = gold_policy if verified_only else "none"
    selection = select_evaluation_cases(
        all_cases, 
        effective_policy, 
        include_unanswerable=not verified_only,
        limit=limit if limit and limit > 0 else None
    )

    return all_cases, selection, sidecar, audit_summary


def parse_golden_case(raw_item: Dict[str, Any], idx: int) -> GoldenCase:
    case_id = f"case_{idx+1:03d}"
    q_type = raw_item.get("question_type", "factoid")
    q_text = raw_item.get("question", "")
    gt_ans = raw_item.get("ground_truth_answer", "")
    gt_contexts = raw_item.get("ground_truth_context", [])

    answerable = not (
        q_type == "unanswerable" or "tài liệu không đề cập" in gt_ans.casefold()
    )

    ev_list: List[GoldEvidence] = []
    for c_idx, ctx in enumerate(gt_contexts, start=1):
        cites = extract_citations_from_text(ctx)
        doc_num = cites[0]["document_number"] if cites else ""
        art = cites[0]["article"] if cites else ""
        cl = cites[0]["clause"] if cites else ""
        req_lvl = "clause" if cl else ("article" if art else "document")

        ev_list.append(
            GoldEvidence(
                evidence_item_id=f"{case_id}_ctx{c_idx:02d}_cit01",
                case_id=case_id,
                context_index=c_idx,
                citation_index=1,
                reference_anchor_hash=hashlib.sha256(ctx.encode("utf-8")).hexdigest()[:16],
                document_number=doc_num or None,
                article=art or None,
                clause=cl or None,
                required=answerable,
                required_level=req_lvl,
                status="unanswerable" if not answerable else "not_found_by_local_deterministic_audit",
            )
        )

    return GoldenCase(
        case_id=case_id,
        question=q_text,
        question_type=q_type,
        answerable=answerable,
        reference_answer=gt_ans,
        reference_contexts=gt_contexts,
        gold_evidence=ev_list,
        expected_numbers=raw_item.get("expected_numbers", []),
        expected_dates=raw_item.get("expected_dates", []),
        expected_entities=raw_item.get("expected_entities", []),
    )


async def evaluate_single_retrieval_case(
    case: GoldenCase,
    settings: Any,
    effective_profile: EvaluationProfile,
) -> RetrievalCaseResult:
    from app.services.retrieval import get_legal_retriever
    from app.evaluation.capacities import build_stage_capacities

    retriever = get_legal_retriever()
    started = time.perf_counter()

    query_used = case.question
    rewritten_q = None

    if effective_profile.rewrite_mode == "on":
        try:
            from app.services.query_rewriter import rewrite_query

            t_rw_start = time.perf_counter()
            rewritten_q = await rewrite_query(case.question)
            t_rw = time.perf_counter() - t_rw_start
            query_used = rewritten_q
        except Exception:
            t_rw = 0.0
            query_used = case.question
    else:
        t_rw = 0.0

    t_ret_start = time.perf_counter()
    outcome = await retriever.retrieve_detailed(
        query_used,
        sparse_query=case.question,
        profile=effective_profile,
    )
    t_ret = time.perf_counter() - t_ret_start

    caps = build_stage_capacities(effective_profile, settings)
    t_total = time.perf_counter() - started

    retrieved_chunks = [
        CandidateChunk(
            document_id=e.document_id,
            document_number=e.document_number,
            title=e.title,
            source_url=e.source_url,
            citation=e.citation,
            article=e.article,
            clause=e.clause,
            text=e.text,
            token_count=e.token_count,
            score=e.score,
        )
        for e in outcome.evidence
    ]

    metrics = calculate_case_retrieval_metrics(
        case.gold_evidence,
        retrieved_chunks,
        stage_trace=outcome.stage_trace,
        capacities=caps,
    )

    latency_dict = {
        "t_rewrite": round(t_rw, 4),
        "t_retrieval": round(t_ret, 4),
        "t_total": round(t_total, 4),
    }

    return RetrievalCaseResult(
        case_id=case.case_id,
        question=case.question,
        original_query=case.question,
        question_type=case.question_type,
        answerable=case.answerable,
        query_used=query_used,
        rewritten_query=rewritten_q,
        status=outcome.status,
        retrieved_evidence=retrieved_chunks,
        stage_trace=outcome.stage_trace,
        latency=latency_dict,
        metrics=metrics,
    )


async def run_retrieval_evaluation(arguments=None) -> Dict[str, Any]:
    args = arguments or build_parser().parse_args()
    if args.concurrency <= 0:
        raise ValueError("concurrency must be positive.")

    if args.preflight_all_profiles and not args.verified_only:
        raise ValueError("Official all-profile preflight requires --verified-only.")

    settings = get_settings()
    dataset_path = Path(args.dataset).resolve()
    sidecar_path = Path(args.sidecar).resolve()
    summary_path = DEFAULT_SUMMARY_PATH

    dataset_sha256 = calculate_dataset_sha256(dataset_path)

    base_profile = get_evaluation_profile(args.profile)
    effective_profile = dataclasses.replace(
        base_profile,
        rewrite_mode=args.rewrite,
        reranker_mode=args.reranker,
    )

    # Perform pre-execution validation
    all_cases, selection, sidecar, audit_summary = perform_pre_execution_validation(
        dataset_path=dataset_path,
        sidecar_path=sidecar_path,
        summary_path=summary_path,
        gold_policy=args.gold_policy,
        verified_only=args.verified_only,
        require_clean_git=args.require_clean_git,
        limit=args.limit,
    )

    git_sha, git_dirty, _, _, _, diff_sha, _ = get_git_provenance()
    code_state_fingerprint = hashlib.sha256(f"{git_sha}:{git_dirty}:{diff_sha}".encode("utf-8")).hexdigest()
    code_state_sha8 = code_state_fingerprint[:8]
    sidecar_sha8 = sidecar.metadata.sidecar_sha256[:8]

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
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "git_diff_sha256": diff_sha,
        "code_state_fingerprint": code_state_fingerprint,
    }
    fp = calculate_configuration_fingerprint(config_dict)
    config_fp8 = fp[:8]

    if args.preflight or args.preflight_all_profiles:
        profiles_to_check = ["legacy", "separated_no_intent", "separated_intent"] if args.preflight_all_profiles else [effective_profile.name]
        
        preflight_dir = PROJECT_ROOT / "docs/evaluation/preflight"
        preflight_dir.mkdir(parents=True, exist_ok=True)
        
        comparison_dict = {
            "meta": {
                "git_sha": git_sha,
                "git_dirty": git_dirty,
                "git_diff_sha256": diff_sha,
                "code_state_fingerprint": code_state_fingerprint,
                "dataset_sha256": dataset_sha256,
                "sidecar_sha256": sidecar.metadata.sidecar_sha256,
                "gold_policy": args.gold_policy,
                "verified_only": args.verified_only,
                "provider_calls": 0,
                "batch_status": "OK",
                "blocked_reason": None,
            },
            "case_selection": {
                "selected_case_count": selection.selected_case_count,
                "selected_case_ids": selection.selected_case_ids,
                "selected_case_ids_sha256": selection.selected_case_ids_sha256,
            },
            "profiles": {}
        }
        
        if args.verified_only and selection.selected_case_count == 0:
            comparison_dict["meta"]["batch_status"] = "BLOCKED"
            comparison_dict["meta"]["blocked_reason"] = "selected_case_count_is_zero_under_verified_only"

        for p_name in profiles_to_check:
            p_obj = get_evaluation_profile(p_name)
            p_eff = dataclasses.replace(p_obj, rewrite_mode=args.rewrite, reranker_mode=args.reranker)
            
            p_config_dict = config_dict.copy()
            p_config_dict["profile_name"] = p_eff.name
            p_config_dict["profile"] = p_eff.to_dict()
            p_fp = calculate_configuration_fingerprint(p_config_dict)
            p_config_fp8 = p_fp[:8]

            print("=" * 60, flush=True)
            print(f"OFFLINE PREFLIGHT CHECK — PROFILE: {p_eff.name}", flush=True)
            print(f"Dataset: {dataset_path} (SHA: {dataset_sha256[:8]})", flush=True)
            print(f"Sidecar: {sidecar_path} (SHA: {sidecar.metadata.sidecar_sha256[:8]})", flush=True)
            print(f"Code State: SHA {git_sha[:8]} | Dirty: {git_dirty} | Fingerprint: {code_state_sha8}", flush=True)
            print(f"Gold Policy: {args.gold_policy} | Verified Only: {args.verified_only}", flush=True)
            print(f"Configuration Fingerprint: {p_fp}", flush=True)
            print(f"Declared Cases: {sidecar.metadata.total_cases} | Declared Evidence Items: {sidecar.metadata.total_evidence_items}", flush=True)
            print(f"Selected Cases ({selection.selected_case_count}): {selection.selected_case_ids}", flush=True)
            print(f"Selected Case IDs SHA-256: {selection.selected_case_ids_sha256}", flush=True)
            print(f"Provider Calls: 0", flush=True)
            print("=" * 60, flush=True)

            comparison_dict["profiles"][p_eff.name] = {
                "profile_name": p_eff.name,
                "configuration_fingerprint": p_fp,
                "selected_case_count": selection.selected_case_count,
                "selected_case_ids_sha256": selection.selected_case_ids_sha256,
                "canonical_artifact_path": str(preflight_dir / f"preflight_{p_eff.name}_{p_config_fp8}_{sidecar_sha8}_{code_state_sha8}.json"),
                "retrieval_document_limit": p_eff.retrieval_document_limit,
                "resolved_document_limit": p_eff.resolved_document_limit,
                "local_chunks_per_document": p_eff.local_chunks_per_document,
                "rerank_input_limit": p_eff.rerank_input_limit,
                "intent_scoring_enabled": p_eff.intent_scoring_enabled,
            }

            preflight_payload = comparison_dict.copy()
            preflight_payload["meta"]["profile_name"] = p_eff.name
            
            profile_preflight_path = preflight_dir / f"preflight_{p_eff.name}_{p_config_fp8}_{sidecar_sha8}_{code_state_sha8}.json"
            atomic_write_json(profile_preflight_path, preflight_payload)
            
            if not args.preflight_all_profiles:
                atomic_write_json(preflight_dir / "latest_preflight.json", preflight_payload)

        comparison_path = preflight_dir / f"preflight_comparison_{sidecar_sha8}_{code_state_sha8}.json"
        atomic_write_json(comparison_path, comparison_dict)
        atomic_write_json(preflight_dir / "preflight_comparison.json", comparison_dict)

        if comparison_dict["meta"]["batch_status"] == "BLOCKED":
            print("Preflight check exited non-zero: 0 selected cases under verified-only policy.")
            sys.exit(1)

        return comparison_dict

    # LIVE RETRIEVAL EVALUATION RUN
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
    for completed_task in asyncio.as_completed(tasks):
        result = await completed_task
        results_map[result.case_id] = result
        print(
            f"-> Completed Case [{result.case_id}]: status={result.status} "
            f"doc_recall@1={result.metrics.get('doc_recall', {}).get(1, 0.0)} latency={result.latency['t_total']:.2f}s",
            flush=True,
        )

    ordered_results = [results_map[c.case_id] for c in cases]
    cases_dict = [res.model_dump() for res in ordered_results]
    retrieval_summary = aggregate_retrieval_metrics(cases_dict)
    stage_traces = [res.stage_trace for res in ordered_results]
    stage_survival_summary = calculate_stage_survival_rates(stage_traces)
    latency_summary = calculate_stage_latency_summary([res.latency for res in ordered_results])

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
    atomic_write_json(run_dir / "retrieval_results.json", cases_dict)

    report_path = write_run_report(
        run_dir=run_dir,
        manifest=manifest,
        retrieval_summary=retrieval_summary,
        stage_survival_summary=stage_survival_summary,
        latency_summary=latency_summary,
        case_results=cases_dict,
    )

    print("=" * 60, flush=True)
    print(f"Retrieval Evaluation Completed. Report saved to:\n{report_path}", flush=True)
    print("=" * 60, flush=True)

    return {
        "manifest": manifest.model_dump(),
        "summary": retrieval_summary,
        "latency": latency_summary,
        "report_path": str(report_path),
    }


if __name__ == "__main__":
    asyncio.run(run_retrieval_evaluation())
