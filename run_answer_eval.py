from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure UTF-8 output on Windows
sys.stdout.reconfigure(encoding="utf-8")
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.evaluation.answer_metrics import (
    aggregate_answer_metrics,
    calculate_case_answer_metrics,
    classify_response_refusal,
)
from app.evaluation.latency_metrics import calculate_stage_latency_summary
from app.evaluation.reporting import write_run_report
from app.evaluation.retrieval_metrics import (
    aggregate_retrieval_metrics,
    calculate_case_retrieval_metrics,
    calculate_stage_survival_rates,
)
from app.evaluation.run_manifest import (
    atomic_write_json,
    create_run_manifest,
    generate_unique_run_id,
)
from app.evaluation.schemas import (
    AnswerCaseResult,
    CandidateChunk,
    GoldenCase,
    RetrievalCaseResult,
    RetrievalStageTrace,
)
from run_retrieval_eval import DEFAULT_DATASET_PATH, parse_golden_case


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic full pipeline answer evaluation over VietLex legal dataset."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
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
    rewrite_mode: str,
    reranker_provider: str,
) -> Dict[str, Any]:
    """
    Stage A: Execute online pipeline end-to-end under semaphore.
    Returns raw pipeline output dict and releases semaphore immediately.
    """
    from app.services.guardrails import (
        check_input_guardrails,
        check_output_guardrails,
    )
    from app.services.rag_pipeline import generate_response, run_advanced_rag

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
                return {
                    "case_id": case.case_id,
                    "response": rejection,
                    "final_response": rejection,
                    "contexts": [],
                    "input_safe": False,
                    "output_safe": False,
                    "latency": {"t_total": round(time.perf_counter() - started, 4)},
                    "retrieval_outcome": None,
                }
        except Exception as err:
            input_guardrail_latency = time.perf_counter() - gr_start
            if guardrails_mode == "enforce":
                raise

    # Run advanced RAG pipeline
    bot_response, contexts, rag_latency = await run_advanced_rag(case.question)

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
        **rag_latency,
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
        "rag_latency": rag_latency,
    }


async def run_stage_b_offline(
    case: GoldenCase,
    stage_a_result: Dict[str, Any],
    retrieval_case_res: RetrievalCaseResult,
    settings: Any,
    judge_mode: str,
) -> AnswerCaseResult:
    """
    Stage B: Run offline deterministic metrics and optional Ragas audit outside semaphore.
    """
    raw_response = stage_a_result["raw_response"]
    final_response = stage_a_result["final_response"]
    contexts = stage_a_result["contexts"]
    latency = stage_a_result["latency"]

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
    if judge_mode == "ragas" and contexts and not det_metrics["is_refusal"]:
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

    with dataset_path.open("r", encoding="utf-8") as f:
        raw_dataset = json.load(f)

    cases = [parse_golden_case(item, idx) for idx, item in enumerate(raw_dataset)]
    if args.limit and args.limit > 0:
        cases = cases[: args.limit]

    manifest = create_run_manifest(
        run_id=args.run_id or generate_unique_run_id(prefix="answer"),
        eval_mode="answer",
        judge_mode=args.judge,
        guardrail_mode=args.guardrails,
        rewrite_mode=args.rewrite,
        reranker_provider=args.reranker,
        dataset_path=dataset_path,
        settings=settings,
        command_str=" ".join(sys.argv),
    )

    print("=" * 60)
    print(f"FULL PIPELINE ANSWER EVALUATION RUN: {manifest.run_id}")
    print(f"cases={len(cases)} mode={args.mode} rewrite={args.rewrite} guardrails={args.guardrails}")
    print(f"reranker={args.reranker} concurrency={args.concurrency} judge={args.judge}")
    print("=" * 60)

    semaphore = asyncio.Semaphore(args.concurrency)
    answer_results: List[AnswerCaseResult] = []

    async def evaluate_case(case: GoldenCase) -> AnswerCaseResult:
        # Stage A: Run online under semaphore
        async with semaphore:
            stage_a_res = await run_stage_a_online(
                case, settings, args.guardrails, args.rewrite, args.reranker
            )

        # Semaphore is RELEASED here before Stage B!
        from run_retrieval_eval import evaluate_single_retrieval_case

        retrieval_case_res = await evaluate_single_retrieval_case(
            case, settings, args.rewrite, args.reranker
        )
        return await run_stage_b_offline(
            case, stage_a_res, retrieval_case_res, settings, args.judge
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
    run_dir = PROJECT_ROOT / "docs/evaluation/runs" / manifest.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    atomic_write_json(run_dir / "manifest.json", manifest.model_dump())
    atomic_write_json(run_dir / "configuration.json", manifest.configuration)
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
