from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure UTF-8 output on Windows with error handling
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.evaluation.answer_metrics import (
    aggregate_answer_metrics,
    calculate_case_answer_metrics,
    classify_response_refusal,
)
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
    prepare_run_directory,
)
from app.evaluation.schemas import (
    AnswerCaseResult,
    CandidateChunk,
    GoldenCase,
    RetrievalCaseResult,
    RetrievalStageTrace,
)
from run_retrieval_eval import (
    DEFAULT_DATASET_PATH,
    evaluate_single_retrieval_case,
    parse_golden_case,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic full pipeline answer evaluation over VietLex legal dataset."
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
        default="answer",
        help="Evaluation mode (default: answer)",
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
        "--gold-policy",
        choices=["all-required-verified", "any-verified"],
        default="all-required-verified",
        help="Selection policy for verified cases (default: all-required-verified)",
    )
    parser.add_argument(
        "--judge",
        choices=["none", "ragas"],
        default="none",
        help="LLM judge mode (default: none)",
    )
    parser.add_argument("--run-id", type=str, default=None, help="Optional custom Run ID")
    return parser


async def run_stage_a_online(
    case: GoldenCase,
    settings: Any,
    guardrails_mode: str,
    effective_profile: EvaluationProfile,
) -> Dict[str, Any]:
    """
    Stage A: Execute online pipeline end-to-end under semaphore.
    Executes single retrieval pass using effective_profile and returns raw pipeline output.
    """
    from app.services.guardrails import (
        check_input_guardrails,
        check_output_guardrails,
    )
    from app.services.rag_pipeline import generate_response

    started = time.perf_counter()
    input_safe = True
    output_safe = True
    input_guardrail_latency = 0.0
    output_guardrail_latency = 0.0

    # Input guardrails execution
    if guardrails_mode in ("shadow", "enforce"):
        gr_start = time.perf_counter()
        try:
            input_safe, rejection = await check_input_guardrails(case.question)
            input_guardrail_latency = time.perf_counter() - gr_start
            if not input_safe and guardrails_mode == "enforce":
                retrieval_res = await evaluate_single_retrieval_case(
                    case, settings, effective_profile
                )
                return {
                    "case_id": case.case_id,
                    "response": rejection,
                    "final_response": rejection,
                    "contexts": [],
                    "input_safe": False,
                    "output_safe": False,
                    "latency": {"t_total": round(time.perf_counter() - started, 4)},
                    "retrieval_result": retrieval_res,
                }
        except Exception:
            input_guardrail_latency = time.perf_counter() - gr_start
            if guardrails_mode == "enforce":
                raise

    # 1. Single retrieval pass
    retrieval_res = await evaluate_single_retrieval_case(
        case, settings, effective_profile
    )
    contexts = [c.text for c in retrieval_res.retrieved_evidence]

    # 2. Answer Generation
    bot_response = await generate_response(case.question, contexts)

    # Output guardrails execution
    final_response = bot_response
    if guardrails_mode in ("shadow", "enforce"):
        gr_start = time.perf_counter()
        try:
            output_safe, fallback_response = await check_output_guardrails(
                bot_response, contexts, case.question
            )
            output_guardrail_latency = time.perf_counter() - gr_start
            if not output_safe and guardrails_mode == "enforce":
                final_response = fallback_response
        except Exception:
            output_guardrail_latency = time.perf_counter() - gr_start
            if guardrails_mode == "enforce":
                output_safe = False

    t_total = time.perf_counter() - started
    raw_latency = {
        **retrieval_res.latency,
        "t_input_guardrail": input_guardrail_latency,
        "t_output_guardrail": output_guardrail_latency,
        "t_total": t_total,
    }

    numeric_latency = {
        k: round(float(v), 4)
        for k, v in raw_latency.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }

    return {
        "case_id": case.case_id,
        "raw_response": bot_response,
        "final_response": final_response,
        "contexts": contexts,
        "input_safe": input_safe,
        "output_safe": output_safe,
        "latency": numeric_latency,
        "retrieval_result": retrieval_res,
    }


async def run_stage_b_offline(
    case: GoldenCase,
    stage_a_result: Dict[str, Any],
    settings: Any,
    judge_mode: str,
) -> AnswerCaseResult:
    """
    Stage B: Run offline deterministic metrics and optional Ragas audit outside semaphore.
    Reuses retrieval_result from Stage A directly without retrieving again.
    """
    raw_response = stage_a_result["raw_response"]
    final_response = stage_a_result["final_response"]
    contexts = stage_a_result["contexts"]
    latency = stage_a_result["latency"]
    retrieval_case_res: RetrievalCaseResult = stage_a_result["retrieval_result"]

    # 1. Deterministic code metrics
    det_metrics = calculate_case_answer_metrics(
        pred_response=final_response,
        ref_answer=case.reference_answer,
        question_type=case.question_type,
        retrieved_contexts=contexts,
        expected_numbers=case.expected_numbers,
        expected_dates=case.expected_dates,
        expected_entities=case.expected_entities,
    )

    ragas_scores = None
    ragas_error = None

    # 2. Optional Ragas LLM judge audit (only if --judge ragas)
    if judge_mode == "ragas" and contexts and not det_metrics.get("is_refusal"):
        try:
            from run_eval_suite import build_ragas_evaluator

            evaluator = build_ragas_evaluator(settings, judge_concurrency=1)
            ragas_scores = await evaluator(
                query=case.question,
                response=final_response,
                contexts=contexts,
                reference=case.reference_answer,
            )
        except Exception as err:
            ragas_error = str(err)

    return AnswerCaseResult(
        case_id=case.case_id,
        question=case.question,
        question_type=case.question_type,
        answerable=case.answerable,
        retrieval_result=retrieval_case_res,
        raw_response=raw_response,
        final_response=final_response,
        input_safe=stage_a_result["input_safe"],
        output_safe=stage_a_result["output_safe"],
        refusal_category=det_metrics["refusal_category"],
        latency=latency,
        metrics=det_metrics,
        ragas_metrics=ragas_scores,
        error=ragas_error,
    )


async def run_answer_evaluation(arguments=None) -> Dict[str, Any]:
    args = arguments or build_parser().parse_args()
    if args.concurrency <= 0:
        raise ValueError("concurrency must be positive.")

    settings = get_settings()
    dataset_path = Path(args.dataset).resolve()
    if not dataset_path.exists():
        raise FileNotFoundError(f"Could not find dataset at: {dataset_path}")

    base_profile = get_evaluation_profile(args.profile)
    effective_profile = dataclasses.replace(
        base_profile,
        rewrite_mode=args.rewrite,
        reranker_mode=args.reranker,
    )

    with dataset_path.open("r", encoding="utf-8") as f:
        raw_dataset = json.load(f)

    cases = [parse_golden_case(item, idx) for idx, item in enumerate(raw_dataset)]
    if args.limit and args.limit > 0:
        cases = cases[: args.limit]

    selected_case_ids = [c.case_id for c in cases]
    selected_case_ids_sha256 = hashlib.sha256(
        json.dumps(selected_case_ids).encode("utf-8")
    ).hexdigest()

    config_dict = {
        "profile_name": effective_profile.name,
        "profile": effective_profile.to_dict(),
        "eval_mode": "answer",
        "judge_mode": args.judge,
        "guardrail_mode": args.guardrails,
        "rewrite_mode": effective_profile.rewrite_mode,
        "reranker_provider": effective_profile.reranker_mode,
        "gold_policy": args.gold_policy,
        "selected_case_count": len(selected_case_ids),
        "selected_case_ids_sha256": selected_case_ids_sha256,
    }
    fp = calculate_configuration_fingerprint(config_dict)

    run_id = args.run_id or generate_unique_run_id(
        prefix="answer", config_fingerprint=fp
    )

    manifest = create_run_manifest(
        run_id=run_id,
        eval_mode="answer",
        judge_mode=args.judge,
        guardrail_mode=args.guardrails,
        rewrite_mode=effective_profile.rewrite_mode,
        reranker_provider=effective_profile.reranker_mode,
        dataset_path=dataset_path,
        settings=settings,
        command_str=" ".join(sys.argv),
        profile_name=effective_profile.name,
        profile_obj=effective_profile,
        gold_policy=args.gold_policy,
        selected_case_ids=selected_case_ids,
    )

    runs_base_dir = PROJECT_ROOT / "docs/evaluation/runs"
    run_dir = prepare_run_directory(runs_base_dir, manifest.run_id)

    print("=" * 60)
    print(f"FULL PIPELINE ANSWER EVALUATION RUN: {manifest.run_id}")
    print(
        f"cases={len(cases)} mode={args.mode} profile={effective_profile.name} rewrite={effective_profile.rewrite_mode} guardrails={args.guardrails}"
    )
    print(
        f"reranker={effective_profile.reranker_mode} concurrency={args.concurrency} judge={args.judge}"
    )
    print("=" * 60)

    semaphore = asyncio.Semaphore(args.concurrency)
    answer_results: List[AnswerCaseResult] = []

    async def evaluate_case(case: GoldenCase) -> AnswerCaseResult:
        # Stage A: Run online under semaphore (single retrieval + generation)
        async with semaphore:
            stage_a_res = await run_stage_a_online(
                case, settings, args.guardrails, effective_profile
            )

        # Stage B: Offline metrics outside semaphore (reusing Stage A retrieval_result)
        return await run_stage_b_offline(
            case, stage_a_res, settings, args.judge
        )

    tasks = [asyncio.create_task(evaluate_case(case)) for case in cases]
    for completed_task in asyncio.as_completed(tasks):
        res = await completed_task
        answer_results.append(res)
        print(
            f"-> Completed Case [{res.case_id}]: category={res.refusal_category} "
            f"token_f1={res.metrics.get('token_f1', 0.0):.2f} latency={res.latency['t_total']:.2f}s"
        )

    # Summaries
    retrieval_cases_dict = [res.retrieval_result.model_dump() for res in answer_results]
    retrieval_summary = aggregate_retrieval_metrics(retrieval_cases_dict)
    stage_traces = [res.retrieval_result.stage_trace for res in answer_results]
    stage_survival_summary = calculate_stage_survival_rates(stage_traces)
    latency_summary = calculate_stage_latency_summary([res.latency for res in answer_results])

    answer_cases_dict = [res.model_dump() for res in answer_results]
    answer_summary = aggregate_answer_metrics(answer_cases_dict)

    # Atomic write run artifacts
    atomic_write_json(run_dir / "manifest.json", manifest.model_dump())
    atomic_write_json(run_dir / "configuration.json", manifest.configuration)
    atomic_write_json(
        run_dir / "evaluation_case_set.json",
        {
            "selected_case_count": len(selected_case_ids),
            "selected_case_ids": selected_case_ids,
            "selected_case_ids_sha256": selected_case_ids_sha256,
        },
    )
    atomic_write_json(run_dir / "retrieval_results.json", retrieval_cases_dict)
    atomic_write_json(run_dir / "answer_results.json", answer_cases_dict)

    report_path = write_run_report(
        run_dir=run_dir,
        manifest=manifest,
        retrieval_summary=retrieval_summary,
        stage_survival_summary=stage_survival_summary,
        latency_summary=latency_summary,
        answer_summary=answer_summary,
        case_results=answer_cases_dict,
    )

    print("=" * 60)
    print(f"Full Answer Evaluation Completed. Report saved to:\n{report_path}")
    print("=" * 60)

    return {
        "manifest": manifest.model_dump(),
        "retrieval_summary": retrieval_summary,
        "answer_summary": answer_summary,
        "latency": latency_summary,
        "report_path": str(report_path),
    }


if __name__ == "__main__":
    asyncio.run(run_answer_evaluation())
