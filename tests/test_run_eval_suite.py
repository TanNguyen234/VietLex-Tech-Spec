import json
import subprocess
import sys
from types import SimpleNamespace

import pytest
import run_eval_suite


def test_help_does_not_boot_the_full_rag_application() -> None:
    completed = subprocess.run(
        [sys.executable, "run_eval_suite.py", "--help"],
        cwd=run_eval_suite.PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0
    assert "--concurrency" in completed.stdout


def _case(kind: str, index: int) -> dict:
    return {
        "question": f"{kind}-{index}",
        "question_type": kind,
        "ground_truth_answer": f"answer-{kind}-{index}",
        "ground_truth_context": [f"context-{kind}-{index}"],
    }


def test_loader_maps_question_schema_and_samples_across_each_group(
    tmp_path,
) -> None:
    dataset = (
        [_case("factoid", index) for index in range(6)]
        + [_case("multi-hop", index) for index in range(3)]
        + [_case("unanswerable", index) for index in range(3)]
    )
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")

    selected = run_eval_suite.load_evaluation_dataset(
        path,
        factoid_count=3,
        multihop_count=2,
        unanswerable_count=2,
    )

    assert [item["query"] for item in selected[:3]] == [
        "factoid-0",
        "factoid-2",
        "factoid-5",
    ]
    assert selected[0]["ground_truth"] == "answer-factoid-0"
    assert selected[0]["reference_contexts"] == ["context-factoid-0"]
    assert selected[-1]["expected"] == "honest_refusal"


def test_cli_defaults_measure_pipeline_without_semantic_cache() -> None:
    arguments = run_eval_suite.build_parser().parse_args([])

    assert arguments.factoids == 12
    assert arguments.multihop == 12
    assert arguments.unanswerable == 6
    assert arguments.concurrency == 2
    assert arguments.use_cache is False
    assert arguments.skip_ragas is False


def test_judge_provider_prefers_configured_openrouter_endpoint() -> None:
    provider = run_eval_suite.select_judge_provider(
        SimpleNamespace(
            OPENROUTER_API_KEY="openrouter-key",
            GEMINI_API_KEY="gemini-key",
            NVIDIA_API_KEY=None,
            GROQ_API_KEY=None,
            LITELLM_MASTER_KEY="gateway-key",
            OMNIGATE_BASE_URL="https://gateway.invalid",
        )
    )

    assert provider == {
        "name": "OpenRouter",
        "model": "meta-llama/llama-3.3-70b-instruct",
        "api_key": "openrouter-key",
        "base_url": "https://openrouter.ai/api/v1",
    }


def test_checkpoint_is_reused_only_for_the_same_evaluation_fingerprint() -> None:
    result = {
        "query": "Điều kiện cấp phép?",
        "evaluation_status": "Generated",
        "response": "Câu trả lời có căn cứ.",
        "input_safe": True,
        "output_safe": True,
        "is_refusal": False,
        "cache_hit": False,
        "faithfulness": 0.9,
        "answer_accuracy": 0.8,
        "context_precision": 0.7,
        "context_recall": 0.6,
        "evaluation_fingerprint": "current",
    }

    assert run_eval_suite.is_valid_checkpoint(result, "current") is True
    assert run_eval_suite.is_valid_checkpoint(result, "old") is False


def test_fingerprint_changes_when_retrieval_configuration_changes() -> None:
    cases = [
        {
            "query": "Điều kiện cấp phép?",
            "ground_truth": "Có đủ điều kiện.",
            "reference_contexts": ["Điều 1"],
        }
    ]

    first = run_eval_suite.evaluation_fingerprint(
        cases,
        run_ragas=True,
        configuration={"rerank_candidate_limit": 24},
    )
    second = run_eval_suite.evaluation_fingerprint(
        cases,
        run_ragas=True,
        configuration={"rerank_candidate_limit": 12},
    )

    assert first != second


@pytest.mark.asyncio
async def test_query_evaluation_bypasses_semantic_cache_by_default(
    monkeypatch,
) -> None:
    async def forbidden_cache(_query: str):
        raise AssertionError("golden evaluation must measure the RAG pipeline")

    async def safe_input(_query: str):
        return True, ""

    async def fake_rag(_query: str):
        return (
            "Câu trả lời có căn cứ.",
            ["[Điều 1] Nội dung căn cứ."],
            {"t_total": 0.1},
        )

    async def safe_output(_response, _contexts, _query):
        return True, ""

    monkeypatch.setattr(
        run_eval_suite,
        "check_semantic_cache",
        forbidden_cache,
    )
    monkeypatch.setattr(
        run_eval_suite,
        "check_input_guardrails",
        safe_input,
    )
    monkeypatch.setattr(run_eval_suite, "run_advanced_rag", fake_rag)
    monkeypatch.setattr(
        run_eval_suite,
        "check_output_guardrails",
        safe_output,
    )

    result = await run_eval_suite.evaluate_single_query(
        {
            "query": "Điều kiện cấp phép?",
            "group": "Factoid",
            "expected": "grounded_answer",
            "ground_truth": "Câu trả lời có căn cứ.",
            "reference_contexts": ["Nội dung căn cứ."],
        },
        settings=SimpleNamespace(),
        ragas_evaluator=None,
        evaluation_fingerprint="fingerprint",
    )

    assert result["cache_hit"] is False
    assert result["evaluation_status"] == "Generated (Ragas skipped)"
    assert result["evaluation_fingerprint"] == "fingerprint"
    assert result["answer_accuracy"] is None
