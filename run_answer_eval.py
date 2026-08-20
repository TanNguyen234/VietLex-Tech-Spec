from __future__ import annotations

import argparse
import asyncio
import dataclasses
import sys
import time
from pathlib import Path
from typing import Any, Dict

from app.config import get_settings
from app.evaluation.answer_metrics import (
    aggregate_answer_metrics,
    calculate_case_answer_metrics,
)
from app.evaluation.capacities import build_stage_capacities
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
    build_run_configuration,
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
    DEFAULT_SIDECAR_PATH,
    DEFAULT_SUMMARY_PATH,
    evaluate_single_retrieval_case,
    perform_pre_execution_validation,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PROJECT_ROOT = Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic full pipeline answer evaluation over VietLex legal dataset."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--sidecar", type=Path, default=DEFAULT_SIDECAR_PATH)
    parser.add_argument(
        "--audit-summary",
        type=Path,
        default=None,
        help=(
            "Optional machine-readable audit summary matching --sidecar. "
            "The legacy default is used only with the legacy default sidecar."
        ),
    )
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
        "--case-ids",
        nargs="+",
        default=None,
        help="Evaluate exactly these case IDs in the supplied order",
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
        "--judge",
        choices=["none", "ragas"],
        default="none",
        help="LLM judge mode (default: none)",
    )
    parser.add_argument(
        "--require-clean-git",
        action="store_true",
        help="Require clean git status before execution",
    )
    parser.add_argument("--run-id", type=str, default=None, help="Optional custom Run ID")
    return parser


def resolve_audit_summary_path(
    sidecar_path: Path,
    explicit_summary: Path | None,
) -> Path | None:
    if explicit_summary is not None:
        return Path(explicit_summary).resolve()
    if sidecar_path == DEFAULT_SIDECAR_PATH.resolve():
        return DEFAULT_SUMMARY_PATH.resolve()
    return None


def format_candidate_context(chunk: CandidateChunk) -> str:
    parts = []
    if chunk.citation:
        parts.append(f"Dẫn chiếu: {chunk.citation}")
    elif chunk.document_number:
        cite_str = f"Văn bản {chunk.document_number}"
        if chunk.article:
            cite_str = f"{chunk.article} {cite_str}"
        if chunk.clause:
            cite_str = f"{chunk.clause} {cite_str}"
        parts.append(f"Dẫn chiếu: {cite_str}")

    if chunk.title:
        parts.append(f"Tiêu đề: {chunk.title}")
    if chunk.source_url:
        parts.append(f"URL: {chunk.source_url}")
    parts.append(f"Nội dung: {chunk.text}")
    return "\n".join(parts)


async def run_stage_a_online(
    case: GoldenCase,
    settings: Any,
    guardrails_mode: str,
    effective_profile: EvaluationProfile,
) -> Dict[str, Any]:
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
    online_status = "ok"
    technical_errors: Dict[str, str] = {}
    capacities = build_stage_capacities(effective_profile, settings)

    # Input guardrails execution
    if guardrails_mode in ("shadow", "enforce"):
        gr_start = time.perf_counter()
        try:
            input_safe, rejection = await check_input_guardrails(case.question)
            input_guardrail_latency = time.perf_counter() - gr_start
            if not input_safe and guardrails_mode == "enforce":
                online_status = "input_guardrail_rejected"
                # STRICT REQUIREMENT: Input guardrail rejection MUST NOT execute retrieval!
                empty_retrieval_res = RetrievalCaseResult(
                    case_id=case.case_id,
                    question=case.question,
                    original_query=case.question,
                    question_type=case.question_type,
                    answerable=case.answerable,
                    query_used=case.question,
                    status="input_guardrail_rejected",
                    retrieved_evidence=[],
                    stage_trace=RetrievalStageTrace(),
                    latency={"t_total": round(time.perf_counter() - started, 4)},
                    metrics=calculate_case_retrieval_metrics(
                        case.gold_evidence,
                        [],
                        stage_trace=RetrievalStageTrace(),
                        capacities=capacities,
                        status=online_status,
                    ),
                )
                return {
                    "case_id": case.case_id,
                    "raw_response": rejection,
                    "final_response": rejection,
                    "contexts": [],
                    "input_safe": False,
                    "output_safe": False,
                    "status": online_status,
                    "technical_errors": technical_errors,
                    "latency": {"t_total": round(time.perf_counter() - started, 4)},
                    "retrieval_result": empty_retrieval_res,
                }
        except Exception as error:
            input_guardrail_latency = time.perf_counter() - gr_start
            input_safe = False
            message = f"{type(error).__name__}: {error}"
            technical_errors["input_guardrail"] = message
            if guardrails_mode == "enforce":
                online_status = "input_guardrail_error"
                fallback = (
                    "Hệ thống chưa thể xử lý yêu cầu do guardrail error."
                )
                empty_retrieval_res = RetrievalCaseResult(
                    case_id=case.case_id,
                    question=case.question,
                    original_query=case.question,
                    question_type=case.question_type,
                    answerable=case.answerable,
                    query_used=case.question,
                    status=online_status,
                    retrieved_evidence=[],
                    stage_trace=RetrievalStageTrace(),
                    latency={
                        "t_total": round(time.perf_counter() - started, 4)
                    },
                    metrics=calculate_case_retrieval_metrics(
                        case.gold_evidence,
                        [],
                        stage_trace=RetrievalStageTrace(),
                        capacities=capacities,
                        status=online_status,
                    ),
                    error=message,
                    technical_errors=technical_errors,
                )
                return {
                    "case_id": case.case_id,
                    "raw_response": fallback,
                    "final_response": fallback,
                    "contexts": [],
                    "input_safe": False,
                    "output_safe": False,
                    "status": online_status,
                    "technical_errors": technical_errors,
                    "latency": {
                        "t_input_guardrail": round(
                            input_guardrail_latency, 4
                        ),
                        "t_total": round(
                            time.perf_counter() - started, 4
                        ),
                    },
                    "retrieval_result": empty_retrieval_res,
                }

    # 1. Single retrieval pass
    retrieval_res = await evaluate_single_retrieval_case(
        case, settings, effective_profile
    )
    technical_errors.update(retrieval_res.technical_errors)
    if online_status == "ok" and retrieval_res.status in {
        "no_candidate",
        "retrieval_error",
        "reranker_error",
    }:
        online_status = retrieval_res.status
    contexts = [format_candidate_context(c) for c in retrieval_res.retrieved_evidence]

    # 2. Real 3-argument generate_response call: (original_query, rewritten_query, contexts)
    rewritten_q = retrieval_res.rewritten_query or retrieval_res.query_used or case.question
    bot_response = await generate_response(case.question, rewritten_q, contexts)

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
                online_status = "output_guardrail_rejected"
                final_response = fallback_response
        except Exception as error:
            output_guardrail_latency = time.perf_counter() - gr_start
            output_safe = False
            technical_errors["output_guardrail"] = (
                f"{type(error).__name__}: {error}"
            )
            if guardrails_mode == "enforce":
                online_status = "output_guardrail_error"

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
        "status": online_status,
        "technical_errors": technical_errors,
        "latency": numeric_latency,
        "retrieval_result": retrieval_res,
    }


async def run_stage_b_offline(
    case: GoldenCase,
    stage_a_result: Dict[str, Any],
    settings: Any,
    judge_mode: str,
) -> AnswerCaseResult:
    raw_response = stage_a_result["raw_response"]
    final_response = stage_a_result["final_response"]
    contexts = stage_a_result["contexts"]
    latency = stage_a_result["latency"]
    retrieval_case_res: RetrievalCaseResult = stage_a_result["retrieval_result"]
    status = stage_a_result.get("status", "ok")

    det_metrics = calculate_case_answer_metrics(
        pred_response=final_response,
        ref_answer=case.reference_answer,
        question_type=case.question_type,
        retrieved_contexts=contexts,
        expected_numbers=case.expected_numbers,
        expected_dates=case.expected_dates,
        expected_entities=case.expected_entities,
        status=status,
    )

    ragas_scores = None
    ragas_error = None
    technical_errors = dict(stage_a_result.get("technical_errors", {}))

    if (
        judge_mode == "ragas"
        and det_metrics["applicable"]
        and contexts
        and not det_metrics.get("is_refusal")
    ):
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
            ragas_error = f"{type(err).__name__}: {err}"
            technical_errors["judge"] = ragas_error

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
        error=(
            "; ".join(
                [
                    *technical_errors.values(),
                ]
            )
            or None
        ),
        status=status,
        technical_errors=technical_errors,
    )


async def run_answer_evaluation(arguments=None) -> Dict[str, Any]:
    args = arguments or build_parser().parse_args()
    if args.concurrency <= 0:
        raise ValueError("concurrency must be positive.")
    if args.case_ids and args.limit is not None:
        raise ValueError("--case-ids and --limit cannot be used together.")

    settings = get_settings()
    if args.guardrails in {"shadow", "enforce"}:
        from app.services.guardrails import warm_guardrails

        await warm_guardrails()
    dataset_path = Path(args.dataset).resolve()
    sidecar_path = Path(args.sidecar).resolve()
    summary_path = resolve_audit_summary_path(
        sidecar_path,
        args.audit_summary,
    )

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
        requested_case_ids=args.case_ids,
    )

    if args.verified_only and selection.selected_case_count == 0:
        raise ValueError("Cannot execute answer evaluation: selected case count is ZERO.")

    cases = selection.selected_cases
    selected_case_ids = selection.selected_case_ids

    config_dict = build_run_configuration(
        profile_name=effective_profile.name,
        profile=effective_profile.to_dict(),
        eval_mode="answer",
        judge_mode=args.judge,
        guardrail_mode=args.guardrails,
        rewrite_mode=effective_profile.rewrite_mode,
        reranker_provider=effective_profile.reranker_mode,
        gold_policy=args.gold_policy,
        selected_case_ids=selected_case_ids,
        selected_case_ids_sha256=selection.selected_case_ids_sha256,
        settings=settings,
    )
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
        selected_case_ids_sha256=selection.selected_case_ids_sha256,
        profile_name=effective_profile.name,
        gold_sidecar_path=sidecar_path,
        profile_obj=effective_profile,
        gold_policy=args.gold_policy,
        selected_case_ids=selected_case_ids,
    )

    runs_base_dir = PROJECT_ROOT / "docs/evaluation/runs"
    run_dir = prepare_run_directory(runs_base_dir, manifest.run_id)

    print("=" * 60)
    print(f"FULL PIPELINE ANSWER EVALUATION RUN: {manifest.run_id}")
    print(
        f"cases={len(cases)} profile={effective_profile.name} rewrite={effective_profile.rewrite_mode} guardrails={args.guardrails}"
    )
    print(
        f"reranker={effective_profile.reranker_mode} concurrency={args.concurrency} judge={args.judge}"
    )
    print("=" * 60)

    semaphore = asyncio.Semaphore(args.concurrency)
    answer_results_map: Dict[str, AnswerCaseResult] = {}

    async def evaluate_case(case: GoldenCase) -> AnswerCaseResult:
        async with semaphore:
            stage_a_res = await run_stage_a_online(
                case, settings, args.guardrails, effective_profile
            )

        return await run_stage_b_offline(
            case, stage_a_res, settings, args.judge
        )

    tasks = [asyncio.create_task(evaluate_case(case)) for case in cases]
    for completed_task in asyncio.as_completed(tasks):
        res = await completed_task
        answer_results_map[res.case_id] = res
        print(
            f"-> Completed Case [{res.case_id}]: category={res.refusal_category} "
            f"token_f1={res.metrics.get('token_f1', 0.0):.2f} latency={res.latency['t_total']:.2f}s"
        )

    # Preserve dataset case ordering
    ordered_answer_results = [answer_results_map[c.case_id] for c in cases]
    retrieval_cases_dict = [res.retrieval_result.model_dump() for res in ordered_answer_results]
    retrieval_summary = aggregate_retrieval_metrics(retrieval_cases_dict)
    stage_traces = [res.retrieval_result.stage_trace for res in ordered_answer_results]
    stage_survival_summary = calculate_stage_survival_rates(stage_traces)
    latency_summary = calculate_stage_latency_summary([res.latency for res in ordered_answer_results])

    answer_cases_dict = [res.model_dump() for res in ordered_answer_results]
    answer_summary = aggregate_answer_metrics(answer_cases_dict)

    atomic_write_json(run_dir / "manifest.json", manifest.model_dump())
    atomic_write_json(run_dir / "configuration.json", manifest.configuration)
    atomic_write_json(
        run_dir / "evaluation_case_set.json",
        {
            "selected_case_count": selection.selected_case_count,
            "selected_case_ids": selected_case_ids,
            "selected_case_ids_sha256": selection.selected_case_ids_sha256,
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
