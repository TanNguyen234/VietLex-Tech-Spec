from pathlib import Path
from types import SimpleNamespace

import pytest

import run_answer_eval
import run_eval_suite
import run_retrieval_eval
import run_structural_index_pilot
from app.evaluation.schemas import (
    GoldenCase,
    RetrievalCaseResult,
    RetrievalStageTrace,
)


def test_retrieval_entrypoint_has_no_judge_mode() -> None:
    arguments = run_retrieval_eval.build_parser().parse_args([])

    assert not hasattr(arguments, "judge")


def test_structural_pilot_entrypoint_defaults_are_provider_free() -> None:
    audit = run_structural_index_pilot.build_parser().parse_args(["audit"])
    plan = run_structural_index_pilot.build_parser().parse_args(["plan"])

    assert audit.command_name == "audit"
    assert plan.command_name == "plan"
    assert plan.disk_bytes is None
    assert plan.ram_bytes is None
    assert plan.vcpu is None
    assert plan.existing_disk_bytes is None
    assert plan.shards is None


def test_structural_create_entrypoint_requires_exact_authorization() -> None:
    arguments = run_structural_index_pilot.build_parser().parse_args(
        [
            "create",
            "--plan",
            "plan.json",
            "--plan-sha256",
            "a" * 64,
            "--source-state-sha256",
            "b" * 64,
            "--collection",
            "vietlex-legal-rag-v2-pilot",
            "--allow-remote-write",
        ]
    )

    assert arguments.command_name == "create"
    assert arguments.allow_remote_write is True
    assert arguments.collection == "vietlex-legal-rag-v2-pilot"


def test_answer_entrypoint_disables_llm_judge_by_default() -> None:
    arguments = run_answer_eval.build_parser().parse_args([])

    assert arguments.judge == "none"


def test_legacy_entrypoint_disables_llm_judge_by_default() -> None:
    arguments = run_eval_suite.build_parser().parse_args([])

    assert arguments.judge == "none"
    assert arguments.skip_ragas is False
    assert run_eval_suite.judge_enabled(arguments) is False


def test_legacy_entrypoint_requires_explicit_ragas_opt_in() -> None:
    arguments = run_eval_suite.build_parser().parse_args(["--judge", "ragas"])

    assert run_eval_suite.judge_enabled(arguments) is True


def test_deprecated_skip_ragas_flag_overrides_explicit_judge() -> None:
    arguments = run_eval_suite.build_parser().parse_args(
        ["--judge", "ragas", "--skip-ragas"]
    )

    assert run_eval_suite.judge_enabled(arguments) is False


@pytest.mark.asyncio
async def test_legacy_default_run_does_not_construct_ragas_evaluator(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text("[]\n", encoding="utf-8")

    async def no_op(_settings=None) -> None:
        return None

    def forbidden_ragas_factory(*_args, **_kwargs):
        raise AssertionError("default execution must not construct an LLM judge")

    monkeypatch.setattr(run_eval_suite, "get_settings", SimpleNamespace)
    monkeypatch.setattr(run_eval_suite, "verify_evaluation_fts", no_op)
    monkeypatch.setattr(run_eval_suite, "warm_evaluation_guardrails", no_op)
    monkeypatch.setattr(
        run_eval_suite,
        "build_ragas_evaluator",
        forbidden_ragas_factory,
    )

    arguments = run_eval_suite.build_parser().parse_args(
        [
            "--dataset",
            str(dataset),
            "--factoids",
            "0",
            "--multihop",
            "0",
            "--unanswerable",
            "0",
            "--fresh",
            "--checkpoint",
            str(tmp_path / "checkpoint.json"),
            "--report",
            str(tmp_path / "report.md"),
        ]
    )

    assert await run_eval_suite.run_suite(arguments) == []


@pytest.mark.asyncio
async def test_answer_default_stage_b_does_not_construct_ragas_evaluator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_ragas_factory(*_args, **_kwargs):
        raise AssertionError("default execution must not construct an LLM judge")

    monkeypatch.setattr(
        run_eval_suite,
        "build_ragas_evaluator",
        forbidden_ragas_factory,
    )
    case = GoldenCase(
        case_id="case_001",
        question="Điều kiện pháp lý là gì?",
        question_type="factoid",
        answerable=True,
        reference_answer="Câu trả lời có căn cứ.",
        reference_contexts=["Căn cứ pháp lý."],
    )
    retrieval_result = RetrievalCaseResult(
        case_id=case.case_id,
        question=case.question,
        question_type=case.question_type,
        answerable=case.answerable,
        query_used=case.question,
        original_query=case.question,
        status="ok",
        stage_trace=RetrievalStageTrace(),
    )
    stage_a_result = {
        "raw_response": case.reference_answer,
        "final_response": case.reference_answer,
        "contexts": case.reference_contexts,
        "input_safe": True,
        "output_safe": True,
        "status": "ok",
        "technical_errors": {},
        "latency": {"t_total": 0.01},
        "retrieval_result": retrieval_result,
    }

    result = await run_answer_eval.run_stage_b_offline(
        case,
        stage_a_result,
        SimpleNamespace(),
        run_answer_eval.build_parser().parse_args([]).judge,
    )

    assert result.ragas_metrics is None
    assert result.error is None
