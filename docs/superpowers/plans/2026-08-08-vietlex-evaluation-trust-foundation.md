# VietLex Evaluation Trust Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make VietLex's deterministic evaluation infrastructure contract-correct, provenance-honest, provider-free by default, schema-consistent, and locally verifiable before any retrieval optimization or live benchmark.

**Architecture:** P0 is implemented as eight independently reviewable vertical slices. Runtime adapters remain thin; new focused modules own provenance, immutable artifact persistence, preflight payload construction, and legal-citation parsing. Per-case metrics and aggregate/report schemas are made explicit and tested end-to-end, while historical artifacts remain byte-preserved.

**Tech Stack:** Python 3.10 CI / Python 3.12 local, Pydantic v2, asyncio, FastAPI project services, pytest/pytest-asyncio, Ruff, SQLite-backed local corpus fixtures, Git CLI.

## Global Constraints

- Current source-of-truth precedence is code/tests, `app/config.py`, `docs/PROJECT_CONTEXT.md`, then `docs/CURRENT_ARCHITECTURE.md`.
- Deterministic code metrics are the default; default commands make zero LLM judge calls.
- P0 verification makes zero live Pinecone, Qdrant, LLM, Ragas, ingestion, reindex, migration, or deployment calls.
- Never fabricate provider output, benchmark output, verified gold labels, screenshots, logs, or completion evidence.
- Do not change dense model, dimension, Pinecone metric, embedding prefixes, persistent sparse representation, or durable index schemas in P0.
- Preserve every historical run and report byte-for-byte; add current-status documentation instead of rewriting historical evidence.
- Canonical artifacts are immutable and contain repository-relative POSIX paths; mutable aliases are never audit evidence.
- Full working-tree provenance and source-state fingerprint are separate facts.
- Technical errors are typed and are not classified as hallucinations, honest refusals, or no-candidate outcomes.
- Test doubles are allowed only in tests and strict boundary mocks use `autospec` or `spec_set`.
- Live integration tests remain skipped unless explicitly enabled by their existing environment flag.
- Commit, push, PR, migration, deletion, and external side effects require separate user authorization. Every commit step below is a checkpoint only: if authorization has not been granted, record `NOT RUN (authorization required)` and continue with an uncommitted task diff.
- P0 completion does not mean retrieval quality is acceptable or the system is production-ready.

## Baseline Evidence

Run these before Task 1 and preserve the exact output in the task log:

```powershell
git status --short --branch
python --version
python -m pytest -q tests/test_evaluation_framework.py tests/test_defect_fixes.py tests/services/test_retrieval.py
python -m pytest -q
python -m ruff check --select E4,E7,E9,F app/
python -m compileall -q app tests
git diff --check
```

Expected baseline at audited HEAD `4e40be6ab1871e3b64ca6f560f317bed215e05e1`:

- focused tests: `34 passed`;
- full tests: `140 passed, 1 skipped`;
- Ruff: fails with 9 findings;
- compileall: pass;
- diff check: pass;
- sidecar: 420 cases, 483 evidence items, 0 verified evidence items.

If the baseline differs, stop implementation, record the new HEAD/status and reconcile the plan against the changed source before editing.

## File Responsibility Map

### New production modules

- `app/evaluation/provenance.py`: typed Git working-tree provenance and stable source-state fingerprint.
- `app/evaluation/provider_catalog.py`: public provider/model declarations shared by runtime selection and manifest provenance; contains no credentials.
- `app/evaluation/artifact_io.py`: canonical JSON serialization and immutable/reuse-safe writes.
- `app/evaluation/preflight.py`: pure three-profile preflight payload construction and persistence orchestration.
- `app/evaluation/legal_citations.py`: one shared deterministic legal-citation parser.

### New tests

- `tests/evaluation/test_runtime_contracts.py`: profile, runner, answer, rewrite, factory, and error-status contracts.
- `tests/evaluation/test_provenance.py`: clean/dirty/staged/untracked/generated-artifact and unavailable-Git behavior.
- `tests/evaluation/test_preflight.py`: batch schema, shared fingerprints, relative paths, immutability, collision, and zero-provider blocking.
- `tests/evaluation/test_legal_citations.py`: ordered citation units and structural-verification negative paths.
- `tests/evaluation/test_retrieval_metrics_v3.py`: per-case formulas, level denominators, nDCG, exact references, multi-hop, errors, and first loss.
- `tests/evaluation/test_reporting_v3.py`: aggregate schema, distributions, coverage, skip reasons, technical rates, and report contract.
- `tests/evaluation/test_default_entrypoints.py`: judge-free defaults and legacy entrypoint compatibility.

### Existing files modified

- `app/evaluation/schemas.py`: typed result/provenance/metric fields and metric version.
- `app/evaluation/run_manifest.py`: delegate Git collection, include source fingerprint and typed provenance status.
- `app/services/direct_llm.py`: consume shared generation model constants without changing fallback order.
- `app/evaluation/retrieval_metrics.py`: shared parser import, per-case v3 metrics, aggregation v3.
- `app/evaluation/reporting.py`: validate and render only v3 aggregate schema.
- `app/evaluation/answer_metrics.py`: lint fix and retained deterministic answer contracts.
- `app/evaluation/gold_sidecar.py`: lint-only cleanup.
- `app/evaluation/latency_metrics.py`: lint-only cleanup.
- `app/services/retrieval.py`: import placement and verified reranker diagnostics only.
- `run_retrieval_eval.py`: runtime error observability, preflight delegation, status-aware metrics.
- `run_answer_eval.py`: retain one-retrieval Stage A and judge-free default.
- `run_eval_suite.py`: explicit `--judge none|ragas`, default `none`, deprecated `--skip-ragas` compatibility.
- `audit_golden_dataset.py`: shared parser, not-applicable identity semantics, immutable audit outputs.
- `tests/test_defect_fixes.py`: remove the vacuous `hasattr()` rerank test after a real interaction test replaces it.
- `tests/services/test_remote_reranker.py`: provider-specific return-limit assertions.
- `README.md`: canonical provider-free and opt-in-judge commands.
- `docs/evaluation/CURRENT_STATUS.md`: current non-historical status and verification evidence.
- `.github/workflows/ci-cd.yml`: verify only; retain Python 3.10, Ruff fatal checks, and provider-free `pytest -q`.

---

### Task 1: Restore Runtime Contracts and Make the Static Gate Honest

**Files:**
- Create: `tests/evaluation/test_runtime_contracts.py`
- Modify: `app/evaluation/schemas.py:108-122`
- Modify: `run_retrieval_eval.py:215-296`
- Modify: `app/evaluation/answer_metrics.py:1-6`
- Modify: `app/evaluation/gold_sidecar.py:1-8`
- Modify: `app/evaluation/latency_metrics.py:1-6`
- Modify: `app/evaluation/retrieval_metrics.py:1-14`
- Modify: `app/evaluation/run_manifest.py:1-215`
- Modify: `app/services/retrieval.py:1-180`
- Modify: `tests/test_defect_fixes.py:53-58`
- Modify: `tests/services/test_remote_reranker.py`

**Interfaces:**
- Consumes: `EvaluationProfile`, `LegalRetriever.retrieve_detailed(query, sparse_query=None, *, profile=None)`, `RetrievalOutcome`, `generate_response(original_query, rewritten_query, contexts)`.
- Produces: `RetrievalCaseResult.technical_errors: Dict[str, str]`; `AnswerCaseResult.status` and `AnswerCaseResult.technical_errors`; observable retrieval/rewrite/guardrail technical statuses; strict regression coverage for existing runtime contracts.

- [ ] **Step 1: Add strict profile and retrieval-adapter tests**

Create `tests/evaluation/test_runtime_contracts.py` with these fixtures and assertions:

```python
from dataclasses import FrozenInstanceError, fields
from types import SimpleNamespace
from unittest.mock import AsyncMock, create_autospec, patch

import pytest

from app.evaluation.profiles import EvaluationProfile, get_evaluation_profile
from app.evaluation.schemas import GoldenCase, RetrievalStageTrace
from app.services.retrieval import LegalRetriever, RetrievalOutcome
from run_retrieval_eval import evaluate_single_retrieval_case


def make_case() -> GoldenCase:
    return GoldenCase(
        case_id="case_001",
        question="Điều kiện khấu trừ thuế là gì?",
        question_type="factoid",
        answerable=True,
        reference_answer="",
    )


def make_settings() -> SimpleNamespace:
    return SimpleNamespace(LEGAL_FTS_RESULT_LIMIT=12)


def test_evaluation_profile_is_frozen_and_has_all_runtime_fields() -> None:
    profile = get_evaluation_profile("separated_intent")
    assert {field.name for field in fields(profile)} == {
        "name",
        "retrieval_document_limit",
        "resolved_document_limit",
        "local_chunks_per_document",
        "rerank_input_limit",
        "rerank_return_limit",
        "final_evidence_limit",
        "final_context_token_limit",
        "intent_scoring_enabled",
        "rewrite_mode",
        "reranker_mode",
    }
    with pytest.raises(FrozenInstanceError):
        profile.rerank_input_limit = 99


@pytest.mark.asyncio
async def test_retrieval_adapter_calls_real_contract_once() -> None:
    profile = get_evaluation_profile("separated_intent")
    trace = RetrievalStageTrace()
    retriever = create_autospec(LegalRetriever, instance=True, spec_set=True)
    retriever.retrieve_detailed.return_value = RetrievalOutcome(
        evidence=[],
        latency={},
        status="no_candidate",
        diagnostics={"stage_trace": trace},
    )
    with (
        patch(
            "app.services.retrieval.get_legal_retriever",
            autospec=True,
            return_value=retriever,
        ),
        patch(
            "run_retrieval_eval.calculate_case_retrieval_metrics",
            autospec=True,
            return_value={},
        ) as metric_call,
    ):
        result = await evaluate_single_retrieval_case(
            make_case(), make_settings(), profile
        )
    retriever.retrieve_detailed.assert_awaited_once_with(
        make_case().question,
        sparse_query=make_case().question,
        profile=profile,
    )
    assert result.status == "no_candidate"
    assert result.stage_trace == trace
    metric_call.assert_called_once()
    assert metric_call.call_args.kwargs["stage_trace"] == trace
    assert metric_call.call_args.kwargs["capacities"].model_dump() == {
        "pinecone_document_limit": 24,
        "fts_document_limit": 12,
        "merged_document_limit": 36,
        "resolved_document_limit": 16,
        "structural_chunk_limit": None,
        "local_chunks_limit": 64,
        "rerank_input_limit": 24,
        "rerank_return_limit": 3,
        "final_evidence_limit": 3,
    }


@pytest.mark.asyncio
async def test_retrieval_adapter_returns_typed_error_on_unexpected_exception() -> None:
    profile = get_evaluation_profile("separated_intent")
    retriever = create_autospec(LegalRetriever, instance=True, spec_set=True)
    retriever.retrieve_detailed.side_effect = RuntimeError("provider exploded")
    with patch(
        "app.services.retrieval.get_legal_retriever",
        autospec=True,
        return_value=retriever,
    ):
        result = await evaluate_single_retrieval_case(
            make_case(), make_settings(), profile
        )
    assert result.status == "retrieval_error"
    assert result.error == "RuntimeError: provider exploded"
    assert result.technical_errors == {
        "retrieval": "RuntimeError: provider exploded"
    }
```

- [ ] **Step 2: Add rewrite observability and answer single-retrieval tests**

Append:

```python
from app.evaluation.schemas import CandidateChunk, RetrievalCaseResult
from run_answer_eval import run_stage_a_online


@pytest.mark.asyncio
async def test_rewrite_failure_falls_back_and_is_observable() -> None:
    profile = EvaluationProfile(
        name="rewrite-test",
        retrieval_document_limit=24,
        resolved_document_limit=16,
        local_chunks_per_document=4,
        rerank_input_limit=24,
        rerank_return_limit=3,
        final_evidence_limit=3,
        final_context_token_limit=720,
        intent_scoring_enabled=True,
        rewrite_mode="on",
        reranker_mode="current",
    )
    retriever = create_autospec(LegalRetriever, instance=True, spec_set=True)
    retriever.retrieve_detailed.return_value = RetrievalOutcome(
        evidence=[],
        latency={},
        status="no_candidate",
        diagnostics={"stage_trace": RetrievalStageTrace()},
    )
    rewrite_call = AsyncMock(side_effect=TimeoutError("rewrite timeout"))
    with (
        patch(
            "app.services.retrieval.get_legal_retriever",
            autospec=True,
            return_value=retriever,
        ),
        patch(
            "app.services.query_rewriter.rewrite_query",
            new=rewrite_call,
        ),
    ):
        result = await evaluate_single_retrieval_case(
            make_case(), make_settings(), profile
        )
    assert result.query_used == make_case().question
    assert result.technical_errors == {
        "rewrite": "TimeoutError: rewrite timeout"
    }
    rewrite_call.assert_awaited_once_with(make_case().question)


@pytest.mark.asyncio
async def test_successful_rewrite_is_dense_query_only_and_called_once() -> None:
    profile = EvaluationProfile(
        name="rewrite-success",
        retrieval_document_limit=24,
        resolved_document_limit=16,
        local_chunks_per_document=4,
        rerank_input_limit=24,
        rerank_return_limit=3,
        final_evidence_limit=3,
        final_context_token_limit=720,
        intent_scoring_enabled=True,
        rewrite_mode="on",
        reranker_mode="current",
    )
    retriever = create_autospec(LegalRetriever, instance=True, spec_set=True)
    retriever.retrieve_detailed.return_value = RetrievalOutcome(
        evidence=[],
        latency={},
        status="no_candidate",
        diagnostics={"stage_trace": RetrievalStageTrace()},
    )
    rewrite_call = AsyncMock(return_value="truy vấn đã viết lại")
    with (
        patch(
            "app.services.retrieval.get_legal_retriever",
            autospec=True,
            return_value=retriever,
        ),
        patch(
            "app.services.query_rewriter.rewrite_query",
            new=rewrite_call,
        ),
    ):
        result = await evaluate_single_retrieval_case(
            make_case(), make_settings(), profile
        )
    rewrite_call.assert_awaited_once_with(make_case().question)
    retriever.retrieve_detailed.assert_awaited_once_with(
        "truy vấn đã viết lại",
        sparse_query=make_case().question,
        profile=profile,
    )
    assert result.query_used == "truy vấn đã viết lại"
    assert result.rewritten_query == "truy vấn đã viết lại"


@pytest.mark.asyncio
async def test_answer_stage_uses_one_retrieval_and_three_generation_arguments() -> None:
    profile = get_evaluation_profile("separated_intent")
    chunk = CandidateChunk(
        document_id=1,
        document_number="12/2026/NĐ-CP",
        title="Văn bản mẫu",
        source_url="https://example.invalid/12",
        citation="Điều 2 12/2026/NĐ-CP",
        article="Điều 2",
        text="Nội dung",
        token_count=2,
    )
    retrieval_result = RetrievalCaseResult(
        case_id="case_001",
        question=make_case().question,
        original_query=make_case().question,
        question_type="factoid",
        answerable=True,
        query_used="khấu trừ thuế",
        rewritten_query="khấu trừ thuế",
        status="ok",
        retrieved_evidence=[chunk],
    )
    retrieval_call = AsyncMock(return_value=retrieval_result)
    generation_call = AsyncMock(return_value="Câu trả lời")
    with (
        patch("run_answer_eval.evaluate_single_retrieval_case", retrieval_call),
        patch("app.services.rag_pipeline.generate_response", generation_call),
    ):
        result = await run_stage_a_online(
            make_case(), make_settings(), "off", profile
        )
    retrieval_call.assert_awaited_once()
    generation_call.assert_awaited_once_with(
        make_case().question,
        "khấu trừ thuế",
        result["contexts"],
    )


@pytest.mark.asyncio
async def test_answer_stage_propagates_reranker_error_status() -> None:
    profile = get_evaluation_profile("separated_intent")
    retrieval_result = RetrievalCaseResult(
        case_id="case_001",
        question=make_case().question,
        original_query=make_case().question,
        question_type="factoid",
        answerable=True,
        query_used=make_case().question,
        status="reranker_error",
        retrieved_evidence=[],
        error="TimeoutError: reranker timeout",
        technical_errors={
            "reranker": "TimeoutError: reranker timeout"
        },
    )
    with (
        patch(
            "run_answer_eval.evaluate_single_retrieval_case",
            new=AsyncMock(return_value=retrieval_result),
        ),
        patch(
            "app.services.rag_pipeline.generate_response",
            new=AsyncMock(return_value="Hệ thống chưa thể xử lý."),
        ),
    ):
        result = await run_stage_a_online(
            make_case(), make_settings(), "off", profile
        )
    assert result["status"] == "reranker_error"
    assert result["technical_errors"] == {
        "reranker": "TimeoutError: reranker timeout"
    }


@pytest.mark.asyncio
async def test_input_guardrail_error_is_typed_and_runs_zero_retrieval() -> None:
    profile = get_evaluation_profile("separated_intent")
    retrieval_call = AsyncMock()
    with (
        patch(
            "app.services.guardrails.check_input_guardrails",
            new=AsyncMock(side_effect=TimeoutError("guardrail timeout")),
        ),
        patch("run_answer_eval.evaluate_single_retrieval_case", retrieval_call),
    ):
        result = await run_stage_a_online(
            make_case(), make_settings(), "enforce", profile
        )
    retrieval_call.assert_not_awaited()
    assert result["status"] == "input_guardrail_error"
    assert result["technical_errors"] == {
        "input_guardrail": "TimeoutError: guardrail timeout"
    }
    assert result["retrieval_result"].status == "input_guardrail_error"


@pytest.mark.asyncio
async def test_output_guardrail_error_is_typed_not_a_hallucination_block() -> None:
    profile = get_evaluation_profile("separated_intent")
    retrieval_result = RetrievalCaseResult(
        case_id="case_001",
        question=make_case().question,
        original_query=make_case().question,
        question_type="factoid",
        answerable=True,
        query_used=make_case().question,
        status="ok",
        retrieved_evidence=[],
    )
    with (
        patch(
            "app.services.guardrails.check_input_guardrails",
            new=AsyncMock(return_value=(True, "")),
        ),
        patch(
            "run_answer_eval.evaluate_single_retrieval_case",
            new=AsyncMock(return_value=retrieval_result),
        ),
        patch(
            "app.services.rag_pipeline.generate_response",
            new=AsyncMock(return_value="Câu trả lời đã sinh"),
        ),
        patch(
            "app.services.guardrails.check_output_guardrails",
            new=AsyncMock(side_effect=TimeoutError("guardrail timeout")),
        ),
    ):
        result = await run_stage_a_online(
            make_case(), make_settings(), "enforce", profile
        )
    assert result["status"] == "output_guardrail_error"
    assert result["technical_errors"] == {
        "output_guardrail": "TimeoutError: guardrail timeout"
    }
    assert result["raw_response"] == "Câu trả lời đã sinh"
    assert result["final_response"] == "Câu trả lời đã sinh"
    assert result["output_safe"] is False
```

- [ ] **Step 3: Restore the remaining non-vacuous regression behaviors**

Append targeted tests, using local imports if that keeps the fixture header small:

```python
def test_run_directory_cannot_overwrite_existing_run(tmp_path) -> None:
    from app.evaluation.run_manifest import prepare_run_directory

    base = tmp_path / "runs"
    created = prepare_run_directory(base, "run_001")
    assert created.is_dir()
    with pytest.raises(FileExistsError, match="cannot be overwritten"):
        prepare_run_directory(base, "run_001")


@pytest.mark.parametrize(
    "run_id",
    ["../escape", "..\\escape", "/absolute", "C:\\absolute"],
)
def test_run_directory_rejects_path_like_run_ids(
    tmp_path, run_id: str
) -> None:
    from app.evaluation.run_manifest import prepare_run_directory

    with pytest.raises(ValueError, match="invalid run_id"):
        prepare_run_directory(tmp_path / "runs", run_id)


def test_verified_only_selection_reports_honest_denominator() -> None:
    from app.evaluation.case_selection import select_evaluation_cases
    from app.evaluation.schemas import EvidenceStatus, GoldEvidence

    verified = make_case().model_copy(
        update={
            "case_id": "verified",
            "gold_evidence": [
                GoldEvidence(
                    evidence_item_id="verified_ev_01",
                    case_id="verified",
                    document_number="12/2026/NĐ-CP",
                    required=True,
                    status=EvidenceStatus.VERIFIED,
                )
            ],
        }
    )
    pending = make_case().model_copy(update={"case_id": "pending"})
    selection = select_evaluation_cases(
        [verified, pending], "all-required-verified"
    )
    assert selection.total_candidate_cases == 2
    assert selection.selected_case_count == 1
    assert selection.excluded_no_verified_label_count == 1


def test_refusal_and_text_metrics_keep_distinct_contracts() -> None:
    from app.evaluation.answer_metrics import calculate_case_answer_metrics

    metrics = calculate_case_answer_metrics(
        pred_response="Thuế thu nhập cá nhân",
        ref_answer="thuế thu nhập cá nhân",
        question_type="factoid",
        retrieved_contexts=["Điều 1"],
    )
    assert metrics["exact_match"] == 1.0
    assert metrics["token_precision"] == 1.0
    assert metrics["token_recall"] == 1.0
    assert metrics["token_f1"] == 1.0
    assert metrics["char_f1"] == 1.0
    assert metrics["refusal_category"] == "normal_answer"


def test_technical_fallback_is_not_an_honest_refusal() -> None:
    from app.evaluation.answer_metrics import classify_response_refusal

    category, is_refusal = classify_response_refusal(
        "Hệ thống chưa thể xử lý do guardrail error.",
        ["Điều 1"],
    )
    assert category == "technical_error"
    assert is_refusal is False
```

These assertions restore the behaviors listed in the approved design. Do not use test-count assertions as substitutes.

- [ ] **Step 4: Add real provider return-limit tests and remove the vacuous test**

Add one Qdrant and one Pinecone assertion to `tests/services/test_remote_reranker.py`, using that file's existing `FakeQdrant` and `FakeInference` classes:

```python
@pytest.mark.asyncio
async def test_pinecone_override_sets_exact_top_n() -> None:
    settings = Settings(_env_file=None)
    qdrant = FakeQdrant()
    inference = FakeInference()
    reranker = RemoteReranker(
        settings=settings,
        qdrant=qdrant,
        pinecone=SimpleNamespace(inference=inference),
    )
    await reranker.rerank(
        "thuế",
        ["Điều 1", "Điều 2", "Điều 3"],
        mode="pinecone-only",
        rerank_return_limit=1,
    )
    assert inference.calls[0]["top_n"] == 1


@pytest.mark.asyncio
async def test_qdrant_override_sets_exact_query_limit() -> None:
    settings = Settings(_env_file=None, QDRANT_RERANK_MAX_RETRIES=1)
    qdrant = FakeQdrant()
    reranker = RemoteReranker(
        settings=settings,
        qdrant=qdrant,
        pinecone=SimpleNamespace(inference=FakeInference()),
    )
    await reranker.rerank(
        "thuế",
        ["Điều 1", "Điều 2", "Điều 3"],
        mode="qdrant-only",
        rerank_return_limit=1,
    )
    assert qdrant.queries[0]["limit"] == 1
```

Delete `test_retriever_respects_rerank_return_limit()` from `tests/test_defect_fixes.py`; it only asserts `hasattr()`.

- [ ] **Step 5: Run the new tests to verify RED**

Run:

```powershell
python -m pytest -q tests/evaluation/test_runtime_contracts.py tests/services/test_remote_reranker.py
```

Expected: runtime adapter tests fail because `technical_errors` and typed unexpected-error handling do not exist. If provider fixture names differ, correct only the fixture wiring; the exact `top_n == 1` and `limit == 1` assertions must remain.

- [ ] **Step 6: Implement observable adapter errors**

Add to `RetrievalCaseResult` in `app/evaluation/schemas.py`:

```python
technical_errors: Dict[str, str] = Field(default_factory=dict)
```

Add to `AnswerCaseResult`:

```python
status: str = "ok"
technical_errors: Dict[str, str] = Field(default_factory=dict)
```

In `evaluate_single_retrieval_case()`, initialize `technical_errors: Dict[str, str] = {}`. Replace the rewrite exception block with:

```python
except Exception as error:
    t_rw = time.perf_counter() - t_rw_start
    query_used = case.question
    technical_errors["rewrite"] = (
        f"{type(error).__name__}: {error}"
    )
```

Wrap `retrieve_detailed()` with:

```python
try:
    outcome = await retriever.retrieve_detailed(
        query_used,
        sparse_query=case.question,
        profile=effective_profile,
    )
except Exception as error:
    message = f"{type(error).__name__}: {error}"
    technical_errors["retrieval"] = message
    return RetrievalCaseResult(
        case_id=case.case_id,
        question=case.question,
        original_query=case.question,
        question_type=case.question_type,
        answerable=case.answerable,
        query_used=query_used,
        rewritten_query=rewritten_q,
        status="retrieval_error",
        stage_trace=RetrievalStageTrace(),
        latency={
            "t_rewrite": round(t_rw, 4),
            "t_retrieval": round(time.perf_counter() - t_ret_start, 4),
            "t_total": round(time.perf_counter() - started, 4),
        },
        metrics={},
        error=message,
        technical_errors=technical_errors,
    )
```

Pass `technical_errors=technical_errors` in the normal result.

When `outcome.status == "retrieval_error"`, set `technical_errors["retrieval"]` to `outcome.error or "retrieval_error_without_error_detail"`. When `outcome.status == "reranker_error"`, set `technical_errors["reranker"]` to `outcome.error or "reranker_error_without_error_detail"`. Pass `error=outcome.error` into the result. Do not recast either status as `no_candidate`.

`RetrievalOutcome` stores the trace in `outcome.diagnostics["stage_trace"]`, not as an `outcome.stage_trace` attribute. Before building candidates, normalize it with:

```python
stage_trace = outcome.diagnostics.get("stage_trace")
if not isinstance(stage_trace, RetrievalStageTrace):
    stage_trace = RetrievalStageTrace()
```

Use this local `stage_trace` for metric calculation and the returned `RetrievalCaseResult`.

In `run_stage_a_online()`, initialize:

```python
online_status = "ok"
technical_errors: Dict[str, str] = {}
```

On an input-guardrail exception, store `f"{type(error).__name__}: {error}"` and set `online_status="input_guardrail_error"`. In `enforce` mode, return immediately with the message `"Hệ thống chưa thể xử lý yêu cầu do lỗi kiểm tra an toàn."`, empty contexts, and a `RetrievalCaseResult` with the same status/error; do not call retrieval. In `shadow` mode, retain the status/error and continue.

Set `online_status="input_guardrail_rejected"` only for an enforced unsafe input, `online_status="output_guardrail_rejected"` only for an enforced unsafe output, and `online_status="output_guardrail_error"` when output guardrail execution raises. Shadow-mode unsafe results set the safety boolean/diagnostics but are not called “rejected.” After retrieval, merge `retrieval_res.technical_errors`; when the current status is still `ok`, propagate `no_candidate`, `retrieval_error`, or `reranker_error` from the retrieval result. On a technical output-guardrail error, retain the generated response, set `output_safe=False`, and never substitute a hallucination/refusal block. Always return `status` and `technical_errors` from Stage A.

In `run_stage_b_offline()`, construct `AnswerCaseResult` with:

```python
status=stage_a_result.get("status", "ok"),
technical_errors=stage_a_result.get("technical_errors", {}),
error=(
    "; ".join(
        [
            *stage_a_result.get("technical_errors", {}).values(),
            *([ragas_error] if ragas_error else []),
        ]
    )
    or None
),
```

Do not label these technical statuses as `pure_refusal` or `no_evidence`; the existing classifier must return `technical_error` for the technical fallback text.

Harden `prepare_run_directory()` before any caller reuses it:

```python
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def prepare_run_directory(base_dir: Path, run_id: str) -> Path:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("invalid run_id: use 1-128 safe filename characters")
    resolved_base = Path(base_dir).resolve()
    run_dir = (resolved_base / run_id).resolve()
    if run_dir.parent != resolved_base:
        raise ValueError("invalid run_id: resolved path escapes base directory")
    if run_dir.exists():
        raise FileExistsError(
            "Run directory already exists and cannot be overwritten: "
            f"{run_dir}"
        )
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir
```

Import `re`. Generated run IDs already satisfy this contract; unsafe user-supplied IDs fail before file creation.

- [ ] **Step 7: Fix the nine Ruff findings without broad ignores**

Apply these exact cleanup classes:

- import `Optional` in `app/evaluation/answer_metrics.py`;
- remove unused `Any` from `gold_sidecar.py` and `latency_metrics.py`;
- remove unused `math` and `GoldenCase` from `retrieval_metrics.py`;
- import `List` in `run_manifest.py` until Task 2 replaces the tuple API;
- move `StageCandidate`/`RetrievalStageTrace` imports to the top import block of `app/services/retrieval.py` and remove the mid-file `E402` import.

Run:

```powershell
python -m ruff check --select E4,E7,E9,F app/
```

Expected: `All checks passed!`

- [ ] **Step 8: Run focused and broader verification**

```powershell
python -m pytest -q tests/evaluation/test_runtime_contracts.py tests/services/test_remote_reranker.py tests/test_evaluation_framework.py tests/test_rag_pipeline.py
python -m compileall -q app tests
git diff --check
```

Expected: all commands exit 0; no live test is enabled.

- [ ] **Step 9: Conditional commit checkpoint**

Only with explicit authorization:

```powershell
git add app/evaluation/schemas.py app/evaluation/answer_metrics.py app/evaluation/gold_sidecar.py app/evaluation/latency_metrics.py app/evaluation/retrieval_metrics.py app/evaluation/run_manifest.py app/services/retrieval.py run_retrieval_eval.py tests/evaluation/test_runtime_contracts.py tests/services/test_remote_reranker.py tests/test_defect_fixes.py
git commit -m "test(eval): restore strict runtime contracts"
```

Otherwise record: `NOT RUN (commit authorization required)`.

---

### Task 2: Separate Working-Tree Provenance from Source-State Fingerprints

**Files:**
- Create: `app/evaluation/provenance.py`
- Create: `app/evaluation/provider_catalog.py`
- Create: `tests/evaluation/test_provenance.py`
- Modify: `app/evaluation/schemas.py:139-170`
- Modify: `app/evaluation/run_manifest.py:1-280`
- Modify: `app/services/direct_llm.py`
- Modify: `run_eval_suite.py`
- Modify: `run_retrieval_eval.py`
- Modify: `run_answer_eval.py`
- Modify: `tests/test_evaluation_framework.py`

**Interfaces:**
- Consumes: a Git repository path, Git CLI output, evaluation mode, judge mode, and public model configuration. It never consumes API-key values.
- Produces: `collect_git_provenance(repo_root: Path | None = None) -> GitProvenance`; compatibility wrapper `get_git_provenance()`; `build_run_configuration()` shared by runners and manifests; manifest fields `source_state_sha256`, `provenance_status`, `provenance_error`, `git_diff_status`, `git_diff_reason`, and `configured_provider_models`. The last field describes declared candidates, not proof that a provider was called.

- [ ] **Step 1: Write failing provenance tests**

Create `tests/evaluation/test_provenance.py`:

```python
import subprocess
from pathlib import Path

from app.evaluation.provenance import collect_git_provenance


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def initialized_repo(tmp_path: Path) -> Path:
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "Test User")
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "docs/evaluation/preflight").mkdir(parents=True)
    (tmp_path / "docs/evaluation/preflight/result.json").write_text(
        "{}\n", encoding="utf-8"
    )
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "baseline")
    return tmp_path


def test_clean_repo_has_stable_source_state(tmp_path: Path) -> None:
    repo = initialized_repo(tmp_path)
    first = collect_git_provenance(repo)
    second = collect_git_provenance(repo)
    assert first.status == "ok"
    assert first.git_dirty is False
    assert first.source_state_sha256 == second.source_state_sha256


def test_generated_artifact_is_dirty_but_not_source_state(tmp_path: Path) -> None:
    repo = initialized_repo(tmp_path)
    clean = collect_git_provenance(repo)
    artifact = repo / "docs/evaluation/preflight/result.json"
    artifact.write_text('{"changed": true}\n', encoding="utf-8")
    dirty = collect_git_provenance(repo)
    assert dirty.git_dirty is True
    assert dirty.git_tracked_dirty is True
    assert dirty.git_diff_sha256 != clean.git_diff_sha256
    assert dirty.source_state_sha256 == clean.source_state_sha256


def test_untracked_env_is_dirty_but_secret_content_is_never_hashed(
    tmp_path: Path,
) -> None:
    repo = initialized_repo(tmp_path)
    clean = collect_git_provenance(repo)
    (repo / ".env.local").write_text(
        "API_KEY=do-not-read-or-hash\n", encoding="utf-8"
    )
    dirty = collect_git_provenance(repo)
    assert dirty.git_dirty is True
    assert dirty.git_untracked_dirty is True
    assert dirty.source_state_sha256 == clean.source_state_sha256
    assert dirty.git_diff_sha256 is None
    assert dirty.git_diff_status == "redacted"
    assert dirty.git_diff_reason == "sensitive_content_not_hashed"
    assert "do-not-read-or-hash" not in dirty.model_dump_json()


def test_staged_and_untracked_source_changes_affect_source_state(tmp_path: Path) -> None:
    repo = initialized_repo(tmp_path)
    clean = collect_git_provenance(repo)
    (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    git(repo, "add", "app.py")
    (repo / "new_test.py").write_text("assert True\n", encoding="utf-8")
    dirty = collect_git_provenance(repo)
    assert dirty.git_dirty is True
    assert dirty.git_staged_dirty is True
    assert dirty.git_untracked_dirty is True
    assert dirty.source_state_sha256 != clean.source_state_sha256


def test_non_git_directory_is_typed_unavailable(tmp_path: Path) -> None:
    provenance = collect_git_provenance(tmp_path)
    assert provenance.status == "unavailable"
    assert provenance.git_dirty is False
    assert provenance.source_state_sha256 is None
    assert provenance.error
```

Append a manifest test using a temporary dataset and a `SimpleNamespace` with `DATASET_REVISION`, `DENSE_INFERENCE_MODEL`, `QDRANT_RERANK_MODEL`, and `PINECONE_RERANK_MODEL`. Assert the serialized manifest includes exactly:

```python
assert manifest.configured_provider_models == {
    "dense": {
        "provider": "qdrant-cloud-staging",
        "model": "intfloat/multilingual-e5-small",
    },
    "reranker_primary": {
        "provider": "qdrant",
        "model": "answerdotai/answerai-colbert-small-v1",
    },
    "reranker_fallback": {
        "provider": "pinecone",
        "model": "bge-reranker-v2-m3",
    },
    "generation": {
        "mode": "not_applicable",
        "candidates": [],
    },
    "judge": {
        "mode": "none",
        "candidates": [],
    },
}
```

This retrieval-only test must also assert that no field is named `observed_provider_models`; a configured candidate is not runtime-call evidence. Add a separate answer-mode unit test that expects `generation.mode == "configured_fallback_chain"` and `generation.candidates == [{"provider": item.provider, "model": item.model} for item in GENERATION_PROVIDER_MODELS]`, but still no API keys and no claim about which candidate actually responded. For `judge_mode="ragas"`, assert `judge.candidates == [{"provider": item.provider, "model": item.model} for item in JUDGE_PROVIDER_MODELS]`, independent of API-key availability. Assert the serialized JSON contains none of `API_KEY`, `api_key`, `base_url`, or `Authorization`.

For every manifest fixture, also assert:

```python
assert manifest.configuration_fingerprint == (
    calculate_configuration_fingerprint(manifest.configuration)
)
```

- [ ] **Step 2: Run tests to verify RED**

```powershell
python -m pytest -q tests/evaluation/test_provenance.py
```

Expected: collection fails because `app.evaluation.provenance` does not exist.

- [ ] **Step 3: Add the typed provenance model**

Create `app/evaluation/provenance.py` with this public model and constants:

```python
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel


SOURCE_EXCLUDED_PREFIXES = (
    "docs/evaluation/preflight/",
    "docs/evaluation/runs/",
)
SOURCE_EXCLUDED_SUFFIXES = (".tmp", ".pyc")
GIT_SENSITIVE_EXCLUDES = (
    ":!.env",
    ":!.env.*",
    ":!**/.env",
    ":!**/.env.*",
    ":!**/credentials.json",
    ":!**/secrets.json",
    ":!**/service-account.json",
    ":!**/*.key",
    ":!**/*.pem",
    ":!**/*.p12",
    ":!**/*.pfx",
)


class GitProvenance(BaseModel):
    status: Literal["ok", "unavailable"]
    error: str | None = None
    repository_root: str
    git_sha: str
    git_dirty: bool
    git_tracked_dirty: bool
    git_staged_dirty: bool
    git_untracked_dirty: bool
    git_diff_sha256: str | None
    git_diff_status: Literal["ok", "clean", "redacted", "unavailable"]
    git_diff_reason: str | None = None
    source_state_sha256: str | None


def normalize_git_path(value: str) -> str:
    return PurePosixPath(value.replace("\\", "/")).as_posix()


def is_source_excluded(path: str) -> bool:
    normalized = normalize_git_path(path)
    return normalized.startswith(SOURCE_EXCLUDED_PREFIXES) or normalized.endswith(
        SOURCE_EXCLUDED_SUFFIXES
    ) or "/__pycache__/" in f"/{normalized}/" or normalized.startswith(
        ".pytest_cache/"
    )


def is_sensitive_path(path: str) -> bool:
    normalized = normalize_git_path(path)
    name = PurePosixPath(normalized).name.casefold()
    return (
        name == ".env"
        or name.startswith(".env.")
        or name in {
            "credentials.json",
            "secrets.json",
            "service-account.json",
        }
        or PurePosixPath(name).suffix in {
            ".key",
            ".pem",
            ".p12",
            ".pfx",
        }
    )
```

`is_source_excluded()` must return `True` for `is_sensitive_path(path)` before applying the generated-output rules.

- [ ] **Step 4: Implement deterministic collection**

Implement `collect_git_provenance(repo_root: Path | None = None) -> GitProvenance` with these exact rules:

```python
def _run_git(root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or f"git {' '.join(args)} failed")
    return completed.stdout


def _hash_untracked(root: Path, paths: list[str]) -> bytes:
    lines: list[str] = []
    for relative in sorted(paths):
        path = root / relative
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{normalize_git_path(relative)}:{digest}")
    return "\n".join(lines).encode("utf-8")


def collect_git_provenance(repo_root: Path | None = None) -> GitProvenance:
    requested_root = Path(repo_root or Path.cwd()).resolve()
    try:
        root = Path(
            _run_git(requested_root, "rev-parse", "--show-toplevel")
            .decode("utf-8", errors="replace")
            .strip()
        ).resolve()
        sha = _run_git(root, "rev-parse", "HEAD").decode().strip()
        raw_status = _run_git(
            root,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--no-renames",
        )
        entries = [entry for entry in raw_status.split(b"\0") if entry]
        tracked_dirty = False
        staged_dirty = False
        untracked_paths: list[str] = []
        safe_untracked_paths: list[str] = []
        source_untracked_paths: list[str] = []
        sensitive_dirty = False
        for entry in entries:
            text = entry.decode("utf-8", errors="replace")
            code = text[:2]
            path = text[3:]
            if is_sensitive_path(path):
                sensitive_dirty = True
            if code == "??":
                untracked_paths.append(path)
                if not is_sensitive_path(path):
                    safe_untracked_paths.append(path)
                if not is_source_excluded(path):
                    source_untracked_paths.append(path)
                continue
            staged_dirty = staged_dirty or code[0] not in {" ", "?"}
            tracked_dirty = tracked_dirty or code[1] not in {" ", "?"}
        full_diff = _run_git(
            root,
            "diff",
            "--binary",
            "HEAD",
            "--",
            ".",
            *GIT_SENSITIVE_EXCLUDES,
        )
        full_payload = b"\n".join(
            [sha.encode(), full_diff, _hash_untracked(root, safe_untracked_paths)]
        )
        source_diff = _run_git(
            root,
            "diff",
            "--binary",
            "HEAD",
            "--",
            ".",
            ":!docs/evaluation/preflight",
            ":!docs/evaluation/runs",
            *GIT_SENSITIVE_EXCLUDES,
        )
        source_payload = b"\n".join(
            [sha.encode(), source_diff, _hash_untracked(root, source_untracked_paths)]
        )
        git_dirty = bool(entries)
        return GitProvenance(
            status="ok",
            repository_root=str(root),
            git_sha=sha,
            git_dirty=git_dirty,
            git_tracked_dirty=tracked_dirty,
            git_staged_dirty=staged_dirty,
            git_untracked_dirty=bool(untracked_paths),
            git_diff_sha256=(
                hashlib.sha256(full_payload).hexdigest()
                if git_dirty and not sensitive_dirty
                else None
            ),
            git_diff_status=(
                "redacted"
                if sensitive_dirty
                else ("ok" if git_dirty else "clean")
            ),
            git_diff_reason=(
                "sensitive_content_not_hashed" if sensitive_dirty else None
            ),
            source_state_sha256=hashlib.sha256(source_payload).hexdigest(),
        )
    except Exception as error:
        return GitProvenance(
            status="unavailable",
            error=f"{type(error).__name__}: {error}",
            repository_root=str(requested_root),
            git_sha="unknown_git_sha",
            git_dirty=False,
            git_tracked_dirty=False,
            git_staged_dirty=False,
            git_untracked_dirty=False,
            git_diff_sha256=None,
            git_diff_status="unavailable",
            git_diff_reason="git_command_failed",
            source_state_sha256=None,
        )
```

Do not log file contents or environment values.

- [ ] **Step 5: Wire manifest fields and preserve compatibility**

Create `app/evaluation/provider_catalog.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderModel:
    provider: str
    model: str


OPENROUTER_PRIMARY_MODEL = "meta-llama/llama-3.3-70b-instruct"
GEMINI_PRIMARY_MODEL = "gemini-2.0-flash"
NVIDIA_PRIMARY_MODEL = "meta/llama-3.3-70b-instruct"
GROQ_PRIMARY_MODEL = "llama-3.3-70b-versatile"
GEMINI_SECONDARY_MODEL = "gemini-1.5-flash"
GROQ_SECONDARY_MODEL = "llama3-8b-8192"

GENERATION_PROVIDER_MODELS = (
    ProviderModel("OpenRouter", OPENROUTER_PRIMARY_MODEL),
    ProviderModel("Gemini", GEMINI_PRIMARY_MODEL),
    ProviderModel("NVIDIA NIM", NVIDIA_PRIMARY_MODEL),
    ProviderModel("Groq", GROQ_PRIMARY_MODEL),
    ProviderModel("OpenRouter", OPENROUTER_PRIMARY_MODEL),
    ProviderModel("Gemini", GEMINI_SECONDARY_MODEL),
    ProviderModel("Groq", GROQ_SECONDARY_MODEL),
)

JUDGE_PROVIDER_MODELS = (
    ProviderModel("Gemini", GEMINI_PRIMARY_MODEL),
    ProviderModel("NVIDIA NIM", NVIDIA_PRIMARY_MODEL),
    ProviderModel("Groq", GROQ_PRIMARY_MODEL),
    ProviderModel("OpenRouter", OPENROUTER_PRIMARY_MODEL),
    ProviderModel("OmniGate", "legal-core-model"),
)
```

In `app.services.direct_llm`, import the six named model constants and replace each existing default/call-site literal with its matching constant; do not reorder any of the seven attempts. In `run_eval_suite.configured_judge_providers()`, build the first four runtime tuples by zipping `JUDGE_PROVIDER_MODELS[:4]` with the existing settings-field/base-URL mapping, and use `JUDGE_PROVIDER_MODELS[4]` for OmniGate. The mapping still filters on configured keys at runtime, but the manifest serializes the full public catalog without key-availability information.

Add this exact catalog regression test to `tests/evaluation/test_provenance.py`:

Import `GENERATION_PROVIDER_MODELS` and `JUDGE_PROVIDER_MODELS` from `app.evaluation.provider_catalog`, then add:

```python
def test_provider_catalog_preserves_current_fallback_orders() -> None:
    assert [
        (item.provider, item.model) for item in GENERATION_PROVIDER_MODELS
    ] == [
        ("OpenRouter", "meta-llama/llama-3.3-70b-instruct"),
        ("Gemini", "gemini-2.0-flash"),
        ("NVIDIA NIM", "meta/llama-3.3-70b-instruct"),
        ("Groq", "llama-3.3-70b-versatile"),
        ("OpenRouter", "meta-llama/llama-3.3-70b-instruct"),
        ("Gemini", "gemini-1.5-flash"),
        ("Groq", "llama3-8b-8192"),
    ]
    assert [
        (item.provider, item.model) for item in JUDGE_PROVIDER_MODELS
    ] == [
        ("Gemini", "gemini-2.0-flash"),
        ("NVIDIA NIM", "meta/llama-3.3-70b-instruct"),
        ("Groq", "llama-3.3-70b-versatile"),
        ("OpenRouter", "meta-llama/llama-3.3-70b-instruct"),
        ("OmniGate", "legal-core-model"),
    ]
```

Add fields to `EvaluationRunManifest`:

```python
source_state_sha256: Optional[str] = None
provenance_status: str = "ok"
provenance_error: Optional[str] = None
git_diff_status: str = "clean"
git_diff_reason: Optional[str] = None
configured_provider_models: Dict[str, Any] = Field(default_factory=dict)
```

Add the shared builder:

Import `Sequence` from `typing` plus `ProviderModel`, `GENERATION_PROVIDER_MODELS`, and `JUDGE_PROVIDER_MODELS` from `app.evaluation.provider_catalog`, then add:

```python
def _public_candidates(items: Sequence[ProviderModel]) -> List[Dict[str, str]]:
    return [
        {"provider": item.provider, "model": item.model}
        for item in items
    ]


def build_configured_provider_models(
    *, settings: Any, eval_mode: str, judge_mode: str
) -> Dict[str, Any]:
    return {
        "dense": {
            "provider": "qdrant-cloud-staging",
            "model": settings.DENSE_INFERENCE_MODEL,
        },
        "reranker_primary": {
            "provider": "qdrant",
            "model": settings.QDRANT_RERANK_MODEL,
        },
        "reranker_fallback": {
            "provider": "pinecone",
            "model": settings.PINECONE_RERANK_MODEL,
        },
        "generation": {
            "mode": (
                "configured_fallback_chain"
                if eval_mode == "answer"
                else "not_applicable"
            ),
            "candidates": (
                _public_candidates(GENERATION_PROVIDER_MODELS)
                if eval_mode == "answer"
                else []
            ),
        },
        "judge": {
            "mode": judge_mode,
            "candidates": (
                _public_candidates(JUDGE_PROVIDER_MODELS)
                if judge_mode == "ragas"
                else []
            ),
        },
    }


def build_run_configuration(
    *,
    profile_name: str,
    profile: Dict[str, Any],
    eval_mode: str,
    judge_mode: str,
    guardrail_mode: str,
    rewrite_mode: str,
    reranker_provider: str,
    gold_policy: str,
    selected_case_ids: List[str],
    selected_case_ids_sha256: str,
    settings: Any,
) -> Dict[str, Any]:
    expected_selected_ids_sha = hashlib.sha256(
        json.dumps(
            selected_case_ids,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if selected_case_ids_sha256 != expected_selected_ids_sha:
        raise ValueError(
            "selected_case_ids_sha256 does not match selected_case_ids"
        )
    provider_models = build_configured_provider_models(
        settings=settings,
        eval_mode=eval_mode,
        judge_mode=judge_mode,
    )
    return {
        "profile_name": profile_name,
        "profile": profile,
        "eval_mode": eval_mode,
        "judge_mode": judge_mode,
        "guardrail_mode": guardrail_mode,
        "rewrite_mode": rewrite_mode,
        "reranker_provider": reranker_provider,
        "gold_policy": gold_policy,
        "selected_case_count": len(selected_case_ids),
        "selected_case_ids_sha256": selected_case_ids_sha256,
        "configured_provider_models": provider_models,
    }
```

`build_configured_provider_models()` returns the exact retrieval-only shape tested above; for answer mode it adds the catalog generation candidates, and for Ragas it adds the catalog judge candidates. Add `selected_case_ids_sha256: str` to `create_run_manifest()` and validate it through `build_run_configuration()`; an empty selected list uses the real SHA-256 of canonical `[]`, never `None`. Make `run_manifest.get_git_provenance()` delegate to `collect_git_provenance()` and return its current seven-item tuple for callers not yet migrated. Update `create_run_manifest()` to use the typed provenance object and shared builder, then populate all new fields. Remove the explicit `code_metric_version="2.0.0"` constructor argument so the schema's single default is authoritative. Replace the duplicated `config_dict` construction in `run_retrieval_eval.py` and `run_answer_eval.py` with the same builder before calculating the run-ID fingerprint, and pass `selection.selected_case_ids_sha256` to both the builder and manifest. Do not serialize settings-key names, key availability, URLs containing credentials, raw headers, or environment values. `configured_provider_models` is configuration provenance; only a future typed runtime outcome may populate observed-provider evidence.

Update the existing `create_run_manifest()` fixture in `tests/test_evaluation_framework.py` to pass `selected_case_ids=[]` and `selected_case_ids_sha256=hashlib.sha256(b"[]").hexdigest()`; retain its existing dataset/manifest assertions.

- [ ] **Step 6: Run focused and broader tests**

```powershell
python -m pytest -q tests/evaluation/test_provenance.py tests/test_evaluation_framework.py tests/test_run_eval_suite.py
python -m ruff check --select E4,E7,E9,F app/
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 7: Conditional commit checkpoint**

Only with explicit authorization:

```powershell
git add app/evaluation/provenance.py app/evaluation/provider_catalog.py app/evaluation/schemas.py app/evaluation/run_manifest.py app/services/direct_llm.py run_eval_suite.py run_retrieval_eval.py run_answer_eval.py tests/evaluation/test_provenance.py tests/test_evaluation_framework.py tests/test_run_eval_suite.py
git commit -m "fix(eval): separate working tree and source provenance"
```

Otherwise record the commit as not run.

---

### Task 3: Build Pure, Immutable Three-Profile Preflight Artifacts

**Files:**
- Create: `app/evaluation/artifact_io.py`
- Create: `app/evaluation/preflight.py`
- Create: `tests/evaluation/test_preflight.py`
- Modify: `run_retrieval_eval.py:52-109,299-444`

**Interfaces:**
- Consumes: validated selection, three `EvaluationProfile` objects, `GitProvenance`, dataset/sidecar hashes.
- Produces: `build_preflight_batch` with the exact keyword-only signature in Step 5; `persist_preflight_batch(payload: dict[str, Any], output_dir: Path) -> list[tuple[Path, str]]`; `write_immutable_json(path: Path, data: Any) -> Literal["created", "reused"]`. Persistence validates the entire target set before creating any member.

- [ ] **Step 1: Write failing immutable-write tests**

Create `tests/evaluation/test_preflight.py` with:

```python
import json
from pathlib import Path, PurePosixPath

import pytest

from app.evaluation.artifact_io import ArtifactCollisionError, write_immutable_json


def test_immutable_json_reuses_identical_bytes(tmp_path: Path) -> None:
    target = tmp_path / "artifact.json"
    assert write_immutable_json(target, {"value": 1}) == "created"
    first = target.read_bytes()
    assert write_immutable_json(target, {"value": 1}) == "reused"
    assert target.read_bytes() == first


def test_immutable_json_rejects_different_payload(tmp_path: Path) -> None:
    target = tmp_path / "artifact.json"
    write_immutable_json(target, {"value": 1})
    with pytest.raises(ArtifactCollisionError) as captured:
        write_immutable_json(target, {"value": 2})
    assert captured.value.status == "artifact_collision"
    assert json.loads(target.read_text(encoding="utf-8")) == {"value": 1}
```

- [ ] **Step 2: Write failing batch schema tests**

Add these exact fixtures before the batch tests:

```python
def zero_selection() -> CaseSelectionResult:
    return CaseSelectionResult(
        gold_policy="all-required-verified",
        selected_cases=[],
        selected_case_ids=[],
        selected_case_ids_sha256="e" * 64,
        total_candidate_cases=420,
        selected_case_count=0,
        excluded_no_verified_label_count=245,
        excluded_unanswerable_count=175,
    )


def clean_provenance(tmp_path: Path) -> GitProvenance:
    return GitProvenance(
        status="ok",
        repository_root=str(tmp_path),
        git_sha="a" * 40,
        git_dirty=False,
        git_tracked_dirty=False,
        git_staged_dirty=False,
        git_untracked_dirty=False,
        git_diff_sha256=None,
        git_diff_status="clean",
        source_state_sha256="b" * 64,
    )
```

Import `CaseSelectionResult` and `GitProvenance`. In the batch test set `selection = zero_selection()` and `provenance = clean_provenance(tmp_path)`, then assert:

```python
payload = build_preflight_batch(
    profiles=[
        get_evaluation_profile("legacy"),
        get_evaluation_profile("separated_no_intent"),
        get_evaluation_profile("separated_intent"),
    ],
    selection=selection,
    provenance=provenance,
    dataset_sha256="d" * 64,
    dataset_revision="namsyntax-420-v1",
    sidecar_sha256="s" * 64,
    gold_policy="all-required-verified",
    verified_only=True,
    artifact_prefix=PurePosixPath("docs/evaluation/preflight"),
)
assert set(payload["profiles"]) == {
    "legacy",
    "separated_no_intent",
    "separated_intent",
}
assert payload["meta"]["batch_status"] == "BLOCKED"
assert payload["meta"]["status_code"] == "preflight_blocked"
assert payload["meta"]["blocked_reason"] == (
    "selected_case_count_is_zero_under_verified_only"
)
assert "profile_name" not in payload["meta"]
assert payload["meta"]["provider_calls"] == 0
assert {
    profile["source_state_sha256"]
    for profile in payload["profiles"].values()
} == {provenance.source_state_sha256}
for profile in payload["profiles"].values():
    path = profile["canonical_artifact_path"]
    assert "\\" not in path
    assert not Path(path).is_absolute()
```

Also assert `persist_preflight_batch()` creates one comparison plus three profile artifacts and a second identical persistence returns only `reused` statuses without changing bytes. Add a batch-collision test: pre-create one target with different bytes, call persistence, assert `ArtifactCollisionError`, and assert none of the other previously absent targets was created.

Build a second payload with `rewrite_mode="on"` profiles while keeping dataset, sidecar, selection, and source state fixed. Assert its `batch_configuration_fingerprint` and comparison filename differ from the `rewrite_mode="off"` batch; a legitimate configuration change must create a new canonical identity rather than collide with the previous comparison.

Add a provenance-unavailable case. It must still build a persistable diagnostic payload, but `batch_status == "BLOCKED"`, `blocked_reason == "provenance_unavailable"`, and no profile may claim a source-state hash.

- [ ] **Step 3: Run tests to verify RED**

```powershell
python -m pytest -q tests/evaluation/test_preflight.py
```

Expected: collection fails because both new modules are absent.

- [ ] **Step 4: Implement canonical JSON serialization**

Create `app/evaluation/artifact_io.py`:

```python
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal


class ArtifactCollisionError(FileExistsError):
    status = "artifact_collision"


def canonical_json_bytes(data: Any) -> bytes:
    text = json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return (text + "\n").encode("utf-8")


def write_immutable_json(
    path: Path, data: Any
) -> Literal["created", "reused"]:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(data)
    try:
        file = target.open("xb")
    except FileExistsError:
        if target.read_bytes() == payload:
            return "reused"
        raise ArtifactCollisionError(
            f"Canonical artifact already exists with different bytes: {target}"
        )
    try:
        with file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return "created"
```

- [ ] **Step 5: Implement the pure batch builder**

Create `app/evaluation/preflight.py` with exact signatures:

```python
from __future__ import annotations

import copy
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

from app.evaluation.artifact_io import (
    ArtifactCollisionError,
    canonical_json_bytes,
    write_immutable_json,
)
from app.evaluation.case_selection import CaseSelectionResult
from app.evaluation.profiles import EvaluationProfile
from app.evaluation.provenance import GitProvenance
from app.evaluation.run_manifest import calculate_configuration_fingerprint


def build_preflight_batch(
    *,
    profiles: Sequence[EvaluationProfile],
    selection: CaseSelectionResult,
    provenance: GitProvenance,
    dataset_sha256: str,
    dataset_revision: str,
    sidecar_sha256: str,
    gold_policy: str,
    verified_only: bool,
    artifact_prefix: PurePosixPath,
) -> dict[str, Any]:
    provenance_blocked = (
        provenance.status != "ok" or provenance.source_state_sha256 is None
    )
    zero_selection_blocked = (
        verified_only and selection.selected_case_count == 0
    )
    blocked = provenance_blocked or zero_selection_blocked
    meta = {
        "git_sha": provenance.git_sha,
        "git_dirty": provenance.git_dirty,
        "git_diff_sha256": provenance.git_diff_sha256,
        "source_state_sha256": provenance.source_state_sha256,
        "provenance_status": provenance.status,
        "provenance_error": provenance.error,
        "git_diff_status": provenance.git_diff_status,
        "git_diff_reason": provenance.git_diff_reason,
        "dataset_revision": dataset_revision,
        "dataset_sha256": dataset_sha256,
        "sidecar_sha256": sidecar_sha256,
        "gold_policy": gold_policy,
        "verified_only": verified_only,
        "provider_calls": 0,
        "batch_status": "BLOCKED" if blocked else "OK",
        "status_code": "preflight_blocked" if blocked else "ok",
        "blocked_reason": (
            "provenance_unavailable"
            if provenance_blocked
            else "selected_case_count_is_zero_under_verified_only"
            if zero_selection_blocked
            else None
        ),
    }
    case_selection = {
        "selected_case_count": selection.selected_case_count,
        "selected_case_ids": selection.selected_case_ids,
        "selected_case_ids_sha256": selection.selected_case_ids_sha256,
    }
    profile_payloads: dict[str, Any] = {}
    for profile in profiles:
        config = {
            "profile_name": profile.name,
            "profile": profile.to_dict(),
            "gold_policy": gold_policy,
            "verified_only": verified_only,
            "selected_case_ids_sha256": selection.selected_case_ids_sha256,
            "source_state_sha256": provenance.source_state_sha256,
        }
        fingerprint = calculate_configuration_fingerprint(config)
        filename = (
            f"preflight_{profile.name}_{fingerprint[:8]}_"
            f"{dataset_sha256[:8]}_{sidecar_sha256[:8]}_"
            f"{(provenance.source_state_sha256 or 'unknown')[:8]}.json"
        )
        profile_payloads[profile.name] = {
            "profile_name": profile.name,
            "profile": profile.to_dict(),
            "configuration_fingerprint": fingerprint,
            "selected_case_count": selection.selected_case_count,
            "selected_case_ids_sha256": selection.selected_case_ids_sha256,
            "source_state_sha256": provenance.source_state_sha256,
            "canonical_artifact_path": (artifact_prefix / filename).as_posix(),
        }
    batch_configuration_fingerprint = calculate_configuration_fingerprint(
        {
            "dataset_sha256": dataset_sha256,
            "sidecar_sha256": sidecar_sha256,
            "source_state_sha256": provenance.source_state_sha256,
            "selected_case_ids_sha256": selection.selected_case_ids_sha256,
            "profiles": {
                name: value["configuration_fingerprint"]
                for name, value in profile_payloads.items()
            },
        }
    )
    meta["batch_configuration_fingerprint"] = (
        batch_configuration_fingerprint
    )
    return {
        "schema_version": "3.0.0",
        "meta": meta,
        "case_selection": case_selection,
        "profiles": profile_payloads,
    }


def persist_preflight_batch(
    *, payload: dict[str, Any], output_dir: Path
) -> list[tuple[Path, str]]:
    root = Path(output_dir).resolve()
    planned: list[tuple[Path, dict[str, Any]]] = []
    for name, profile in payload["profiles"].items():
        filename = PurePosixPath(profile["canonical_artifact_path"]).name
        profile_payload = {
            "schema_version": payload["schema_version"],
            "meta": copy.deepcopy(payload["meta"]),
            "case_selection": copy.deepcopy(payload["case_selection"]),
            "profile": copy.deepcopy(profile),
        }
        target = root / filename
        planned.append((target, profile_payload))
    comparison_name = (
        f"preflight_comparison_{payload['meta']['dataset_sha256'][:8]}_"
        f"{payload['meta']['sidecar_sha256'][:8]}_"
        f"{(payload['meta']['source_state_sha256'] or 'unknown')[:8]}_"
        f"{payload['meta']['batch_configuration_fingerprint'][:8]}.json"
    )
    comparison = root / comparison_name
    planned.append((comparison, copy.deepcopy(payload)))

    for target, artifact_payload in planned:
        if target.exists() and target.read_bytes() != canonical_json_bytes(
            artifact_payload
        ):
            raise ArtifactCollisionError(
                f"Canonical artifact already exists with different bytes: {target}"
            )

    return [
        (target, write_immutable_json(target, artifact_payload))
        for target, artifact_payload in planned
    ]
```

Before the write loop, construct the complete ordered `(target, payload)` list and canonical bytes for all four artifacts. Validate every existing target first: identical bytes are reusable; different bytes raise `ArtifactCollisionError`. Only after the whole validation pass succeeds may the function call `write_immutable_json()` for missing targets. This prevents a late profile collision from leaving a partially created batch.

- [ ] **Step 6: Delegate the runner preflight branch**

Add this parser option:

```python
parser.add_argument(
    "--preflight-output-dir",
    type=Path,
    default=PROJECT_ROOT / "docs/evaluation/preflight",
    help="Repository-local output directory for preflight artifacts",
)
```

Resolve and validate it before building the payload:

```python
preflight_dir = Path(args.preflight_output_dir).resolve()
try:
    preflight_relative = preflight_dir.relative_to(PROJECT_ROOT).as_posix()
except ValueError as error:
    raise ValueError(
        "--preflight-output-dir must remain inside the repository"
    ) from error
```

Replace the inline profile loop in `run_retrieval_eval.py` with:

```python
provenance = collect_git_provenance(PROJECT_ROOT)
profiles = (
    [
        dataclasses.replace(
            get_evaluation_profile(name),
            rewrite_mode=args.rewrite,
            reranker_mode=args.reranker,
        )
        for name in ("legacy", "separated_no_intent", "separated_intent")
    ]
    if args.preflight_all_profiles
    else [effective_profile]
)
payload = build_preflight_batch(
    profiles=profiles,
    selection=selection,
    provenance=provenance,
    dataset_sha256=dataset_sha256,
    dataset_revision=getattr(settings, "DATASET_REVISION", "unknown"),
    sidecar_sha256=sidecar.metadata.sidecar_sha256,
    gold_policy=args.gold_policy,
    verified_only=args.verified_only,
    artifact_prefix=PurePosixPath(preflight_relative),
)
persist_preflight_batch(payload=payload, output_dir=preflight_dir)
if payload["meta"]["batch_status"] == "BLOCKED":
    raise SystemExit(1)
return payload
```

Place this branch immediately after deterministic dataset/sidecar/case validation and output-path validation. Delete the old pre-branch `code_state_fingerprint`, shallow `config_dict.copy()`, per-profile write loop, `latest_preflight.json`, and `preflight_comparison.json` alias logic. Live-run configuration/run-ID creation occurs only after the preflight branch returns. Do not create a retriever, Qdrant client, Pinecone client, LLM client, run directory, or mutable `latest` alias in this branch.

- [ ] **Step 7: Add a zero-provider CLI integration test**

In the test, monkeypatch `run_retrieval_eval.PROJECT_ROOT` to `tmp_path`, pass explicit fixture dataset/sidecar paths, and use `tmp_path/docs/evaluation/preflight` as `--preflight-output-dir`; this keeps the production repository-root validation active instead of bypassing it. Patch `run_retrieval_eval.perform_pre_execution_validation()` to return the deterministic zero-selection fixture, patch `run_retrieval_eval.collect_git_provenance()` to return a complete typed fixture, and patch `app.services.retrieval.get_legal_retriever` with `side_effect=AssertionError("provider called")`. Run `run_retrieval_evaluation(args)`, assert `SystemExit.code == 1`, assert the provenance collector was called exactly once, assert the provider factory was not called, and assert the comparison artifact reports `provider_calls == 0` and three profiles. Add a separate argument test proving a preflight output path outside the monkeypatched project root raises `ValueError` before persistence.

- [ ] **Step 8: Run focused and broader verification**

```powershell
python -m pytest -q tests/evaluation/test_preflight.py tests/evaluation/test_provenance.py tests/test_evaluation_framework.py
python -m ruff check --select E4,E7,E9,F app/
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 9: Conditional commit checkpoint**

Only with authorization:

```powershell
git add app/evaluation/artifact_io.py app/evaluation/preflight.py run_retrieval_eval.py tests/evaluation/test_preflight.py
git commit -m "fix(eval): make preflight pure and immutable"
```

---

### Task 4: Unify Citation Parsing and Make Audit Outputs Non-Destructive

**Files:**
- Create: `app/evaluation/legal_citations.py`
- Create: `tests/evaluation/test_legal_citations.py`
- Modify: `app/evaluation/retrieval_metrics.py:20-70`
- Modify: `audit_golden_dataset.py:1-536`

**Interfaces:**
- Consumes: arbitrary Vietnamese legal text and optional real identity hints.
- Produces: `parse_legal_citations(text: str) -> list[LegalCitation]`; immutable audit run directories; `not_applicable` identity semantics.

- [ ] **Step 1: Write ordered citation-unit tests**

Create `tests/evaluation/test_legal_citations.py`:

```python
from app.evaluation.legal_citations import LegalCitation, parse_legal_citations


def test_two_documents_are_paired_by_position() -> None:
    text = (
        "Khoản 1 Điều 2 văn bản 12/2026/NĐ-CP và "
        "Khoản 3 Điều 4 văn bản 13/2026/NĐ-CP"
    )
    assert parse_legal_citations(text) == [
        LegalCitation(
            document_number="12/2026/NĐ-CP",
            article="Điều 2",
            clause="Khoản 1",
        ),
        LegalCitation(
            document_number="13/2026/NĐ-CP",
            article="Điều 4",
            clause="Khoản 3",
        ),
    ]


def test_second_article_inherits_shared_document_number() -> None:
    text = (
        "Khoản 1 Điều 2 văn bản 12/2026/NĐ-CP và "
        "Khoản 3 Điều 4 cùng văn bản"
    )
    assert parse_legal_citations(text) == [
        LegalCitation("12/2026/NĐ-CP", "Điều 2", "Khoản 1"),
        LegalCitation("12/2026/NĐ-CP", "Điều 4", "Khoản 3"),
    ]


def test_multiple_articles_without_document_are_preserved() -> None:
    assert parse_legal_citations("Khoản 1 Điều 2 và Khoản 3 Điều 4") == [
        LegalCitation("", "Điều 2", "Khoản 1"),
        LegalCitation("", "Điều 4", "Khoản 3"),
    ]


def test_repeated_units_are_deduplicated_stably() -> None:
    text = "Điều 2 12/2026/NĐ-CP; Điều 2 12/2026/NĐ-CP"
    assert parse_legal_citations(text) == [
        LegalCitation("12/2026/NĐ-CP", "Điều 2", "")
    ]


def test_shared_trailing_document_applies_without_cartesian_product() -> None:
    text = "Khoản 1 Điều 2 và Khoản 3 Điều 4 văn bản 12/2026/NĐ-CP"
    assert parse_legal_citations(text) == [
        LegalCitation("12/2026/NĐ-CP", "Điều 2", "Khoản 1"),
        LegalCitation("12/2026/NĐ-CP", "Điều 4", "Khoản 3"),
    ]


def test_multiple_clauses_for_one_article_are_preserved() -> None:
    text = "Khoản 1 và Khoản 2 Điều 3 văn bản 12/2026/NĐ-CP"
    assert parse_legal_citations(text) == [
        LegalCitation("12/2026/NĐ-CP", "Điều 3", "Khoản 1"),
        LegalCitation("12/2026/NĐ-CP", "Điều 3", "Khoản 2"),
    ]
```

- [ ] **Step 2: Write audit negative-path tests**

Append tests importing `decide_evidence_verification()` and `resolve_document_identity()`:

```python
from app.evaluation.schemas import EvidenceStatus, RequiredLevel
from audit_golden_dataset import decide_evidence_verification


def test_missing_structural_chunk_never_verifies_hint() -> None:
    status, article, clause = decide_evidence_verification(
        RequiredLevel.CLAUSE,
        "Điều 5",
        "Khoản 2",
        None,
    )
    assert status == EvidenceStatus.STRUCTURAL_ANCHOR_NOT_FOUND
    assert article is None
    assert clause is None
```

Add these SQLite in-memory tests; import `sqlite3`, `create_autospec` from `unittest.mock`, and `LegalFtsIndex` from `app.ingestion.legal_fts`:

```python
def identity_db() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE metadata ("
        "document_id INTEGER PRIMARY KEY, "
        "source_url TEXT, document_number TEXT)"
    )
    connection.execute(
        "INSERT INTO metadata VALUES (?, ?, ?)",
        (7, "https://example.invalid/doc-7", "12/2026/NĐ-CP"),
    )
    return connection


def test_identity_without_real_hints_is_not_applicable() -> None:
    connection = identity_db()
    fts = create_autospec(LegalFtsIndex, instance=True, spec_set=True)
    assert resolve_document_identity(
        connection, fts, None, None, None
    ) == ([], "not_applicable", [], True)
    fts.search.assert_not_called()


def test_identity_id_and_url_branches_require_supplied_hints() -> None:
    connection = identity_db()
    fts = create_autospec(LegalFtsIndex, instance=True, spec_set=True)
    assert resolve_document_identity(
        connection, fts, 7, None, None
    ) == ([7], "exact_doc_id", ["dataset_reference_doc_id"], True)
    assert resolve_document_identity(
        connection,
        fts,
        None,
        "https://example.invalid/doc-7",
        None,
    ) == (
        [7],
        "exact_source_url",
        ["dataset_reference_source_url"],
        True,
    )
    fts.search.assert_not_called()
```

- [ ] **Step 3: Run tests to verify RED**

```powershell
python -m pytest -q tests/evaluation/test_legal_citations.py
```

Expected: module import fails; after a minimal module exists, the shared-document test fails against current audit behavior.

- [ ] **Step 4: Implement a single positional parser**

Create `app/evaluation/legal_citations.py`:

```python
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


DOC_PATTERN = re.compile(
    r"\b\d{1,4}/\d{4}/[A-ZĐ0-9-]+\b", re.IGNORECASE
)
ARTICLE_PATTERN = re.compile(r"\bĐiều\s+\d+[A-Za-z]?\b", re.IGNORECASE)
CLAUSE_PATTERN = re.compile(r"\bKhoản\s+\d+\b", re.IGNORECASE)


@dataclass(frozen=True)
class LegalCitation:
    document_number: str = ""
    article: str = ""
    clause: str = ""


def _canonical_locator(value: str, prefix: str) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    return f"{prefix} {normalized.split(maxsplit=1)[1]}"


def _nearest_index(
    items: list[tuple[int, str]], position: int
) -> int | None:
    if not items:
        return None
    return min(
        range(len(items)),
        key=lambda index: (
            abs(items[index][0] - position),
            0 if items[index][0] <= position else 1,
            items[index][0],
        ),
    )


def parse_legal_citations(text: str) -> list[LegalCitation]:
    documents = [
        (match.start(), match.group().upper())
        for match in DOC_PATTERN.finditer(text)
    ]
    articles = [
        (match.start(), _canonical_locator(match.group(), "Điều"))
        for match in ARTICLE_PATTERN.finditer(text)
    ]
    clauses = [
        (match.start(), _canonical_locator(match.group(), "Khoản"))
        for match in CLAUSE_PATTERN.finditer(text)
    ]
    positioned: list[tuple[int, LegalCitation]] = []
    used_documents: set[int] = set()

    if articles:
        clauses_by_article: dict[int, list[tuple[int, str]]] = {
            index: [] for index in range(len(articles))
        }
        for clause_position, clause in clauses:
            article_index = _nearest_index(articles, clause_position)
            assert article_index is not None
            clauses_by_article[article_index].append((clause_position, clause))

        for article_index, (article_position, article) in enumerate(articles):
            document_index = _nearest_index(documents, article_position)
            if document_index is None:
                document_position, document = article_position, ""
            else:
                document_position, document = documents[document_index]
                used_documents.add(document_index)
            linked_clauses = clauses_by_article[article_index]
            if linked_clauses:
                for clause_position, clause in linked_clauses:
                    positioned.append(
                        (
                            min(article_position, clause_position, document_position),
                            LegalCitation(document, article, clause),
                        )
                    )
            else:
                positioned.append(
                    (
                        min(article_position, document_position),
                        LegalCitation(document, article, ""),
                    )
                )
    else:
        for clause_position, clause in clauses:
            document_index = _nearest_index(documents, clause_position)
            if document_index is None:
                document_position, document = clause_position, ""
            else:
                document_position, document = documents[document_index]
                used_documents.add(document_index)
            positioned.append(
                (
                    min(clause_position, document_position),
                    LegalCitation(document, "", clause),
                )
            )

    for document_index, (document_position, document) in enumerate(documents):
        if document_index not in used_documents:
            positioned.append(
                (document_position, LegalCitation(document_number=document))
            )

    positioned.sort(key=lambda item: item[0])
    deduplicated: list[LegalCitation] = []
    seen: set[LegalCitation] = set()
    for _, unit in positioned:
        if unit not in seen:
            seen.add(unit)
            deduplicated.append(unit)
    return deduplicated
```

If a focused test exposes a boundary error, fix this one parser rather than reintroducing parallel regex implementations.

- [ ] **Step 5: Replace both old parsers with the shared parser**

In `retrieval_metrics.py`, keep a compatibility function returning dictionaries:

```python
def extract_citations_from_text(text: str) -> List[Dict[str, str]]:
    return [
        {
            "document_number": item.document_number,
            "article": item.article,
            "clause": item.clause,
        }
        for item in parse_legal_citations(text)
    ]
```

In `audit_golden_dataset.py`, delete `extract_legal_citations_from_text()` and call `parse_legal_citations()`. Convert each dataclass to explicit fields when building labels.

- [ ] **Step 6: Make audit output immutable**

Change the public entry point to:

```python
def audit_golden_dataset(
    *,
    output_root: Path = Path("docs/evaluation/gold_labels/audit_runs"),
    run_id: str | None = None,
) -> Dict[str, Any]:
```

Reserve and write the output with:

```python
provenance = collect_git_provenance()
if provenance.status != "ok":
    raise RuntimeError(provenance.error or "Git provenance unavailable")
repository_root = Path(provenance.repository_root)
effective_run_id = run_id or generate_unique_run_id(prefix="gold-audit")
resolved_output_root = Path(output_root).resolve()
try:
    resolved_output_root.relative_to(repository_root)
except ValueError as error:
    raise ValueError("Audit output_root must remain inside the repository") from error
run_dir = prepare_run_directory(resolved_output_root, effective_run_id)
sidecar_path = run_dir / "labels_v2.json"
summary_path = run_dir / "audit_summary_v2.json"
write_immutable_json(sidecar_path, sidecar_payload)
summary_payload["artifact_paths"] = {
    "sidecar": sidecar_path.relative_to(repository_root).as_posix(),
    "summary": summary_path.relative_to(repository_root).as_posix(),
}
write_immutable_json(summary_path, summary_payload)
return summary_payload
```

Do not update the current canonical sidecar; P1 adjudication owns promotion.

- [ ] **Step 7: Run focused and broader verification**

```powershell
python -m pytest -q tests/evaluation/test_legal_citations.py tests/test_defect_fixes.py tests/test_evaluation_framework.py
python -m ruff check --select E4,E7,E9,F app/
git diff --check
```

Expected: all commands exit 0; no audit is run against the 3.3 GB content store during unit verification.

- [ ] **Step 8: Conditional commit checkpoint**

Only with authorization:

```powershell
git add app/evaluation/legal_citations.py app/evaluation/retrieval_metrics.py audit_golden_dataset.py tests/evaluation/test_legal_citations.py tests/test_defect_fixes.py
git commit -m "fix(eval): unify citation and audit contracts"
```

---

### Task 5: Implement Correct Per-Case Retrieval Metrics V3

**Files:**
- Create: `tests/evaluation/test_retrieval_metrics_v3.py`
- Modify: `app/evaluation/schemas.py`
- Modify: `app/evaluation/retrieval_metrics.py:75-397`
- Modify: `app/evaluation/run_manifest.py`
- Modify: `run_retrieval_eval.py:248-260`
- Modify: `run_answer_eval.py`

**Interfaces:**
- Consumes: verified `GoldEvidence`, final `CandidateChunk`, full `RetrievalStageTrace`, `RetrievalStageCapacities`, typed retrieval status.
- Produces: `calculate_case_retrieval_metrics(gold_evidence: List[GoldEvidence], retrieved_chunks: List[CandidateChunk], stage_trace: Optional[RetrievalStageTrace] = None, capacities: Optional[RetrievalStageCapacities] = None, *, status: str = "ok") -> Dict[str, Any]` with `metric_version="3.0.0"`, level-specific counts, nDCG@10, exact reference, multi-hop coverage, stage evidence counts, first-loss, and technical flags.

- [ ] **Step 1: Add reusable synthetic fixtures**

Create `tests/evaluation/test_retrieval_metrics_v3.py` with helpers that build:

```python
def gold(
    evidence_id: str,
    *,
    document_id: int,
    document_number: str | None = None,
    article: str | None = None,
    clause: str | None = None,
    level: str = "document",
) -> GoldEvidence:
    return GoldEvidence(
        evidence_item_id=evidence_id,
        case_id="case_001",
        document_id=document_id,
        document_number=document_number,
        article=article,
        clause=clause,
        required=True,
        required_level=level,
        status="verified",
    )


def candidate(
    document_id: int,
    *,
    article: str | None = None,
    clause: str | None = None,
    citation: str = "",
) -> StageCandidate:
    return StageCandidate(
        document_id=document_id,
        article=article,
        clause=clause,
        citation=citation,
    )


def chunk(
    document_id: int,
    *,
    document_number: str,
    article: str | None = None,
    clause: str | None = None,
    citation: str = "",
) -> CandidateChunk:
    return CandidateChunk(
        document_id=document_id,
        document_number=document_number,
        title="Synthetic legal document",
        source_url=f"https://example.invalid/{document_id}",
        citation=citation,
        article=article,
        clause=clause,
        text="Synthetic evidence text",
        token_count=3,
    )
```

Import both `StageCandidate` and `CandidateChunk`. Use `candidate()` only inside stage traces and `chunk()` for the `retrieved_chunks` argument so the tests enforce the production types rather than relying on duck typing.

- [ ] **Step 2: Write failing level-denominator and multi-hop tests**

Assert one document-only gold and one clause gold produce:

```python
assert metrics["applicable_gold_counts"] == {
    "document": 2,
    "article": 1,
    "clause": 1,
}
assert metrics["matched_gold_counts"] == {
    "document": 2,
    "article": 1,
    "clause": 1,
}
assert metrics["multi_hop"]["all_required"] is True
assert metrics["multi_hop"]["matched_required_items"] == 2
assert metrics["multi_hop"]["required_items"] == 2
```

This must fail current code because current multi-hop coverage counts article matches against all required labels and drops document-only items.

- [ ] **Step 3: Write failing nDCG, exact-reference, error, and first-loss tests**

Use two relevant documents ranked at positions 1 and 3 and assert `ndcg_at_10` equals the formula below rounded to 4 decimals. Assert exact citation match uses normalized document number/article/clause identity, not substring overlap. Assert `status="retrieval_error"` yields `retrieval_technical_error=True`, `applicable=False`, and `skip_reason="retrieval_error"`; assert the same skip behavior and the distinct flag for `status="reranker_error"`. Assert `status="no_candidate"` remains applicable and contributes zero matches rather than being skipped.

For first loss, make the gold appear in Pinecone, merged, resolved, and structural stages, then disappear at local selection; assert:

```python
assert metrics["first_loss_by_evidence"] == {
    "case_001_ev_01": "local_selection_metrics"
}
```

- [ ] **Step 4: Run tests to verify RED**

```powershell
python -m pytest -q tests/evaluation/test_retrieval_metrics_v3.py
```

Expected: failures for missing v3 keys, nDCG, status parameter, and correct multi-hop matching.

- [ ] **Step 5: Implement exact reusable formulas**

Import `ConfigDict` and define the strict per-case schema in `schemas.py` before implementing formulas:

```python
class RatioMetricV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numerator: float
    denominator: float
    value: Optional[float] = None
    reason: Optional[str] = None


class MultiHopCaseMetricsV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    all_required: bool
    matched_required_items: int
    required_items: int
    all_required_metric: RatioMetricV3
    partial_metric: RatioMetricV3


class StageCaseMetricsV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configured_capacity: Optional[int] = None
    candidate_count: int
    scored_case_count: int
    applicable_gold_counts: Dict[str, int]
    matched_gold_counts: Dict[str, int]
    recall: Dict[str, Dict[int, RatioMetricV3]]
    mrr: Dict[str, RatioMetricV3]
    null_reason_counts: Dict[str, int] = Field(default_factory=dict)


class RetrievalCaseMetricsV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_version: Literal["3.0.0"] = "3.0.0"
    relevance_definition: Literal[
        "binary_unique_required_evidence_v1"
    ] = "binary_unique_required_evidence_v1"
    status: str
    applicable: bool
    skip_reason: Optional[str] = None
    applicable_gold_counts: Dict[str, int]
    matched_gold_counts: Dict[str, int]
    document_recall: Dict[int, RatioMetricV3]
    article_recall: Dict[int, RatioMetricV3]
    clause_recall: Dict[int, RatioMetricV3]
    mrr: Dict[str, RatioMetricV3]
    ndcg_at_10: RatioMetricV3
    exact_reference_hit: RatioMetricV3
    multi_hop: MultiHopCaseMetricsV3
    no_candidate: bool = False
    retrieval_technical_error: bool = False
    reranker_technical_error: bool = False
    stages: Dict[str, StageCaseMetricsV3]
    first_loss_by_evidence: Dict[str, str] = Field(default_factory=dict)
```

Import `Literal` from `typing`. `calculate_case_retrieval_metrics()` constructs this model and returns `model_dump(mode="json")`; technical/skipped cases must still produce the complete schema with explicit zero-denominator reasons rather than an ad hoc short dictionary.

Add helpers:

```python
def ratio(
    numerator: float, denominator: float, reason: str
) -> Dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": (
            round(numerator / denominator, 4) if denominator else None
        ),
        "reason": None if denominator else reason,
    }


def reciprocal_rank(first_rank: Optional[int], applicable: int) -> Dict[str, Any]:
    reciprocal = 1.0 / first_rank if first_rank is not None else 0.0
    return {
        "numerator": round(reciprocal, 6) if applicable else 0.0,
        "denominator": 1 if applicable else 0,
        "value": (
            round(reciprocal, 4)
            if first_rank is not None
            else (0.0 if applicable else None)
        ),
        "reason": None if applicable else "no_applicable_gold",
    }


def ndcg_at_k(relevant_ranks: List[int], relevant_count: int, k: int) -> Dict[str, Any]:
    dcg = sum(1.0 / math.log2(rank + 1) for rank in relevant_ranks if rank <= k)
    ideal = sum(
        1.0 / math.log2(rank + 1)
        for rank in range(1, min(relevant_count, k) + 1)
    )
    return {
        "numerator": round(dcg, 6),
        "denominator": round(ideal, 6),
        "value": round(dcg / ideal, 4) if ideal else None,
        "reason": None if ideal else "no_applicable_gold",
    }
```

Reintroduce `math` only because nDCG now uses it.

For multi-hop, `all_required_metric` has numerator `1` only when every required item matched and denominator `1` when at least one required item is applicable. `partial_metric` has numerator `matched_required_items` and denominator `required_items`. This makes macro partial coverage the average case coverage and micro partial coverage the total matched required evidence divided by total required evidence.

Use binary relevance over unique applicable required evidence. Match ranked candidates to unmatched gold items greedily in rank order; after one gold item has contributed a relevant rank, duplicate candidates for that same item add no gain. Therefore `relevant_ranks` contains at most one rank per applicable gold item and `relevant_count` is the number of applicable unique required items. Record this relevance definition in the metric payload alongside `metric_version="3.0.0"`.

`nDCG_at_10` evaluates the final ranked evidence list with unreturned positions treated as zero gain; it remains applicable even when final capacity is below 10 and therefore measures the capacity's effect. This is intentionally different from Recall@K applicability, which is null when K exceeds configured capacity. State this distinction in the report notes.

- [ ] **Step 6: Implement required-level matching**

Add:

```python
def matches_required_level(gold_item: GoldEvidence, candidate_item: Any) -> bool:
    document_match, article_match, clause_match = match_gold_to_stage_candidate(
        gold_item, candidate_item
    )
    if gold_item.required_level == RequiredLevel.DOCUMENT:
        return document_match
    if gold_item.required_level == RequiredLevel.ARTICLE:
        return article_match
    return clause_match
```

Use this function for multi-hop counts and final exact required-evidence survival. Document applicability includes every verified required item; article applicability includes ARTICLE and CLAUSE items; clause applicability includes CLAUSE items only.

First-loss matching is stage-aware. Add:

```python
DOCUMENT_ONLY_STAGES = {
    "pinecone_document_metrics",
    "fts_document_metrics",
    "source_retrieval_metrics",
    "merged_document_metrics",
    "resolved_document_metrics",
}


def evidence_survives_stage(
    gold_item: GoldEvidence,
    candidate_item: Any,
    stage_name: str,
) -> bool:
    document_match, _, _ = match_gold_to_stage_candidate(
        gold_item, candidate_item
    )
    if stage_name in DOCUMENT_ONLY_STAGES:
        return document_match
    return matches_required_level(gold_item, candidate_item)
```

At a document-only stage, document recall uses all applicable required items, while article/clause Recall@K and MRR have denominator zero and reason `stage_does_not_expose_structural_locators`. Structural and later chunk stages use the normal document/article/clause denominators. This prevents an Article requirement from being declared lost before the pipeline has produced Article-bearing chunks.

Define exact legal-reference hit separately from document recall. It is applicable only when at least one verified gold item contains a normalized document number and every locator required by that item's `required_level`. A case hit is `1` when at least one final-evidence candidate matches one applicable gold item on document number plus all required locators (document only; document+article; or document+article+clause), otherwise `0`. Its per-case denominator is `1` when applicable and `0` with reason `no_exact_reference_gold` otherwise. Title, URL, citation substring, and document-ID fallback may support retrieval matching but must never satisfy this exact-reference metric.

For every Recall@K field, use configured capacity rather than observed candidate count to decide applicability. When K is no greater than configured capacity, return a numeric ratio even if fewer candidates were observed. When K exceeds configured capacity, return `numerator=0`, `denominator=0`, `value=None`, and reason `k_exceeds_configured_capacity`; when capacity itself is unknown, use the same zero denominator and reason `configured_capacity_unknown`. This policy prevents aggregate micro denominators from counting an unavailable K and must have focused assertions for both the numeric-short-result case and the null-over-capacity case.

- [ ] **Step 7: Emit complete stage counts**

For every stage return:

```python
{
    "configured_capacity": stage_capacity,
    "candidate_count": len(candidates),
    "scored_case_count": 1,
    "applicable_gold_counts": {
        "document": len(document_gold),
        "article": len(article_gold),
        "clause": len(clause_gold),
    },
    "matched_gold_counts": {
        "document": len(matched_documents),
        "article": len(matched_articles),
        "clause": len(matched_clauses),
    },
    "recall": {
        "document": document_recall_by_k,
        "article": article_recall_by_k,
        "clause": clause_recall_by_k,
    },
    "mrr": {
        "document": document_mrr,
        "article": article_mrr,
        "clause": clause_mrr,
    },
}
```

Emit metrics in this exact order:

```python
STAGE_METRIC_SEQUENCE = (
    "pinecone_document_metrics",
    "fts_document_metrics",
    "source_retrieval_metrics",
    "merged_document_metrics",
    "resolved_document_metrics",
    "structural_chunk_metrics",
    "local_selection_metrics",
    "reranker_input_metrics",
    "reranker_output_metrics",
    "final_evidence_metrics",
)
```

Build `source_retrieval_metrics` from a stable document-identity union of Pinecone and FTS candidates before merge-specific processing. Pinecone and FTS remain separately reported parallel branches; neither is considered “after” the other.

Compute first loss only over the sequential path:

```python
FIRST_LOSS_SEQUENCE = (
    "source_retrieval_metrics",
    "merged_document_metrics",
    "resolved_document_metrics",
    "structural_chunk_metrics",
    "local_selection_metrics",
    "reranker_input_metrics",
    "reranker_output_metrics",
    "final_evidence_metrics",
)
```

For each required item, use `evidence_survives_stage()` and record the first stage in this sequence where it no longer survives after having been eligible at the previous stage. If it is absent from the source union, record `source_retrieval_metrics`. Never record loss at the Pinecone branch merely because FTS supplied the document, or vice versa.

- [ ] **Step 8: Add status-aware output and runner wiring**

Change the signature:

```python
def calculate_case_retrieval_metrics(
    gold_evidence: List[GoldEvidence],
    retrieved_chunks: List[CandidateChunk],
    stage_trace: Optional[RetrievalStageTrace] = None,
    capacities: Optional[RetrievalStageCapacities] = None,
    *,
    status: str = "ok",
) -> Dict[str, Any]:
```

Return technical flags from status and pass `status=outcome.status` from `evaluate_single_retrieval_case()`.

In a retrieval run, `retrieval_error` and `reranker_error` suppress quality scoring. In an answer run, pre-retrieval `input_guardrail_rejected` and `input_guardrail_error` also suppress retrieval quality with their exact status as skip reason because retrieval was not run. `no_candidate` is a successfully completed retrieval with zero candidates, so verified-gold recall/MRR/nDCG denominators remain applicable and its values are zero. A rewrite fallback recorded in `technical_errors` does not suppress retrieval-quality metrics when retrieval itself completed.

In both the normal and caught-exception branches of `evaluate_single_retrieval_case()`, call the v3 calculator with the exact status; the caught branch passes empty chunks, an empty trace, and effective capacities instead of returning `metrics={}`. In `run_stage_a_online()` input-guardrail early returns, build the same complete v3 metrics with empty candidates and `status="input_guardrail_rejected"` or `status="input_guardrail_error"`. No serialized `RetrievalCaseResult` produced by a runner may contain an empty or legacy metric dictionary.

Set `EvaluationRunManifest.code_metric_version` to `"3.0.0"` in `schemas.py` and never override it in `create_run_manifest()`. Add `assert EvaluationRunManifest.model_fields["code_metric_version"].default == "3.0.0"` to the v3 test file and assert every per-case and aggregate fixture emits the same version.

- [ ] **Step 9: Run focused and broader verification**

```powershell
python -m pytest -q tests/evaluation/test_retrieval_metrics_v3.py tests/test_evaluation_framework.py tests/services/test_retrieval.py
python -m ruff check --select E4,E7,E9,F app/
git diff --check
```

- [ ] **Step 10: Conditional commit checkpoint**

Only with authorization:

```powershell
git add app/evaluation/schemas.py app/evaluation/retrieval_metrics.py app/evaluation/run_manifest.py run_retrieval_eval.py run_answer_eval.py tests/evaluation/test_retrieval_metrics_v3.py
git commit -m "feat(eval): add deterministic retrieval metrics v3"
```

---

### Task 6: Make Aggregation and Reporting Share One V3 Contract

**Files:**
- Create: `tests/evaluation/test_reporting_v3.py`
- Modify: `app/evaluation/schemas.py`
- Modify: `app/evaluation/retrieval_metrics.py:398-520`
- Modify: `app/evaluation/reporting.py:1-177`

**Interfaces:**
- Consumes: serialized per-case v3 metrics and case status.
- Produces: `RetrievalAggregateMetrics`; validated v3 Markdown report with no legacy-key fallback.

- [ ] **Step 1: Add aggregate schema models**

Add to `schemas.py`:

Import `Literal` from `typing` and `ConfigDict` from Pydantic, then add:

```python
class StrictMetricModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvaluationSchemaError(ValueError):
    status = "schema_error"


class AggregateMetric(StrictMetricModel):
    macro: Optional[float] = None
    micro: Optional[float] = None
    numerator: float = 0.0
    denominator: float = 0.0
    scored_cases: int = 0
    skipped_cases: int = 0
    skip_reasons: Dict[str, int] = Field(default_factory=dict)
    reason: Optional[str] = None


class CandidateDistribution(StrictMetricModel):
    count: int
    min: Optional[float] = None
    mean: Optional[float] = None
    p50: Optional[float] = None
    p95: Optional[float] = None
    max: Optional[float] = None


class StageAggregateMetrics(StrictMetricModel):
    configured_capacity: Optional[int] = None
    scored_case_count: int
    applicable_gold_counts: Dict[str, int]
    matched_gold_counts: Dict[str, int]
    recall: Dict[str, Dict[int, AggregateMetric]]
    mrr: Dict[str, AggregateMetric]
    candidates: CandidateDistribution
    first_loss_evidence_count: int = 0
    null_reason_counts: Dict[str, int] = Field(default_factory=dict)


class RetrievalAggregateMetrics(StrictMetricModel):
    metric_version: Literal["3.0.0"] = "3.0.0"
    total_cases: int
    scored_cases: int
    skipped_cases: int
    coverage: AggregateMetric
    skip_reason_counts: Dict[str, int]
    document_recall: Dict[int, AggregateMetric]
    article_recall: Dict[int, AggregateMetric]
    clause_recall: Dict[int, AggregateMetric]
    mrr: Dict[str, AggregateMetric]
    ndcg_at_10: AggregateMetric
    exact_reference_hit: AggregateMetric
    multi_hop_all_required: AggregateMetric
    multi_hop_partial: AggregateMetric
    no_candidate_rate: AggregateMetric
    retrieval_technical_error_rate: AggregateMetric
    reranker_technical_error_rate: AggregateMetric
    stages: Dict[str, StageAggregateMetrics]
```

- [ ] **Step 2: Write failing aggregate tests with known answers**

Import `RetrievalCaseMetricsV3` and add these exact synthetic row helpers:

```python
def r(
    numerator: float,
    denominator: float,
    value: float | None,
    reason: str | None = None,
) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": value,
        "reason": reason,
    }


def scored_row(
    case_id: str,
    candidate_count: int,
    *,
    first_loss: bool = False,
) -> dict:
    document_ratio = r(1, 1, 1.0)
    not_applicable = r(0, 0, None, "no_applicable_gold")
    stage = {
        "configured_capacity": 3,
        "candidate_count": candidate_count,
        "scored_case_count": 1,
        "applicable_gold_counts": {
            "document": 1, "article": 0, "clause": 0
        },
        "matched_gold_counts": {
            "document": 1, "article": 0, "clause": 0
        },
        "recall": {
            "document": {3: document_ratio},
            "article": {},
            "clause": {},
        },
        "mrr": {
            "document": document_ratio,
            "article": not_applicable,
            "clause": not_applicable,
        },
        "null_reason_counts": {},
    }
    metrics = RetrievalCaseMetricsV3(
        status="ok",
        applicable=True,
        applicable_gold_counts={
            "document": 1, "article": 0, "clause": 0
        },
        matched_gold_counts={
            "document": 1, "article": 0, "clause": 0
        },
        document_recall={3: document_ratio},
        article_recall={},
        clause_recall={},
        mrr={
            "document": document_ratio,
            "article": not_applicable,
            "clause": not_applicable,
        },
        ndcg_at_10=document_ratio,
        exact_reference_hit=document_ratio,
        multi_hop={
            "all_required": True,
            "matched_required_items": 1,
            "required_items": 1,
            "all_required_metric": document_ratio,
            "partial_metric": document_ratio,
        },
        stages={
            "local_selection_metrics": {**stage, "candidate_count": 1},
            "final_evidence_metrics": stage,
        },
        first_loss_by_evidence=(
            {f"{case_id}_ev_01": "local_selection_metrics"}
            if first_loss
            else {}
        ),
    )
    return {
        "case_id": case_id,
        "status": "ok",
        "metrics": metrics.model_dump(mode="json"),
    }


def skipped_row() -> dict:
    unavailable = r(0, 0, None, "no_verified_gold_label")
    metrics = RetrievalCaseMetricsV3(
        status="ok",
        applicable=False,
        skip_reason="no_verified_gold_label",
        applicable_gold_counts={
            "document": 0, "article": 0, "clause": 0
        },
        matched_gold_counts={
            "document": 0, "article": 0, "clause": 0
        },
        document_recall={},
        article_recall={},
        clause_recall={},
        mrr={
            "document": unavailable,
            "article": unavailable,
            "clause": unavailable,
        },
        ndcg_at_10=unavailable,
        exact_reference_hit=unavailable,
        multi_hop={
            "all_required": False,
            "matched_required_items": 0,
            "required_items": 0,
            "all_required_metric": unavailable,
            "partial_metric": unavailable,
        },
        stages={},
    )
    return {
        "case_id": "case_003",
        "status": "ok",
        "metrics": metrics.model_dump(mode="json"),
    }
```

Create `cases = [scored_row("case_001", 1, first_loss=True), scored_row("case_002", 3), skipped_row()]`. Assert:

```python
summary = RetrievalAggregateMetrics.model_validate(
    aggregate_retrieval_metrics(cases)
)
assert summary.total_cases == 3
assert summary.scored_cases == 2
assert summary.skipped_cases == 1
assert summary.coverage.numerator == 2
assert summary.coverage.denominator == 3
assert summary.coverage.micro == pytest.approx(2 / 3, abs=1e-4)
assert summary.skip_reason_counts == {"no_verified_gold_label": 1}
assert summary.stages["final_evidence_metrics"].candidates.model_dump() == {
    "count": 2,
    "min": 1.0,
    "mean": 2.0,
    "p50": 2.0,
    "p95": 2.9,
    "max": 3.0,
}
assert summary.stages["local_selection_metrics"].first_loss_evidence_count == 1
```

Use candidate counts `[1, 3]`; linear-interpolation percentile semantics below intentionally make `p50=2.0` and `p95=2.9`.

Add a capacity-consistency test with two scored cases whose `local_selection_metrics.configured_capacity` values are `4` and `6`. Assert `EvaluationSchemaError("inconsistent configured capacity for local_selection_metrics")`; aggregation must not silently choose the first, last, minimum, or maximum value. Add a second assertion using `None` and `4`, which must aggregate to `4` without conflict.

Add an empty-input test and require `RetrievalAggregateMetrics.model_validate(aggregate_retrieval_metrics([]))` to return zero cases, zero coverage denominator, empty stages, and no invented `0.0` quality metric.

- [ ] **Step 3: Write failing report contract tests**

Add this manifest fixture and golden report test:

```python
def report_manifest() -> EvaluationRunManifest:
    return EvaluationRunManifest(
        run_id="synthetic_v3",
        utc_timestamp="2026-08-08T00:00:00+00:00",
        git_sha="a" * 40,
        repository_root="D:/synthetic-repository",
        dataset_revision="synthetic-v1",
        dataset_sha256="d" * 64,
        evaluation_dataset_sha256="d" * 64,
        configuration_fingerprint="f" * 64,
        command="python -m synthetic",
        eval_mode="retrieval-only",
        judge_mode="none",
        guardrail_mode="off",
        rewrite_mode="off",
        reranker_provider="current",
        profile_name="separated_intent",
    )


def test_report_renders_only_valid_v3_contract() -> None:
    summary = RetrievalAggregateMetrics.model_validate(
        aggregate_retrieval_metrics(
            [
                scored_row("case_001", 1, first_loss=True),
                scored_row("case_002", 3),
                skipped_row(),
            ]
        )
    )
    text = generate_markdown_report(
        report_manifest(),
        summary.model_dump(mode="json"),
        {},
        {},
    )
    for expected in (
        "Metric schema: `3.0.0`",
        "Scored / Total: `2 / 3`",
        "Document Recall @ 3",
        "Numerator / Denominator",
        "Retrieval technical-error rate",
        "Candidate p50 / p95",
        "First-loss evidence count",
    ):
        assert expected in text


def test_report_rejects_legacy_metric_keys() -> None:
    with pytest.raises(EvaluationSchemaError) as captured:
        generate_markdown_report(
            report_manifest(),
            {"doc_recall": {1: 1.0}},
            {},
            {},
        )
    assert captured.value.status == "schema_error"
```

Import `EvaluationSchemaError`, the manifest/aggregate models, `aggregate_retrieval_metrics`, and `generate_markdown_report`. The expected report strings are:

```text
Metric schema: `3.0.0`
Scored / Total: `2 / 3`
Document Recall @ 3
Numerator / Denominator
Retrieval technical-error rate
Candidate p50 / p95
First-loss evidence count
```

- [ ] **Step 4: Run tests to verify RED**

```powershell
python -m pytest -q tests/evaluation/test_reporting_v3.py
```

Expected: missing schema models/keys and reporter mismatch failures.

- [ ] **Step 5: Implement deterministic aggregate helpers**

Add:

```python
def percentile(values: List[int], quantile: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return float(ordered[lower])
    weight = index - lower
    return round(
        ordered[lower] * (1.0 - weight) + ordered[upper] * weight,
        4,
    )


def candidate_distribution(values: List[int]) -> CandidateDistribution:
    return CandidateDistribution(
        count=len(values),
        min=float(min(values)) if values else None,
        mean=round(sum(values) / len(values), 4) if values else None,
        p50=percentile(values, 0.50),
        p95=percentile(values, 0.95),
        max=float(max(values)) if values else None,
    )
```

For an empty list, return a fully valid `RetrievalAggregateMetrics` with `macro=None`, `micro=None`, zero numerator/denominator, and explicit reason `no_cases` for undefined quality metrics.

- [ ] **Step 6: Aggregate ratios without nonexistent keys**

At the start of aggregation, require each serialized row to contain `status` and `metrics`, then validate `metrics = RetrievalCaseMetricsV3.model_validate(row["metrics"])`. Catch `KeyError`, `TypeError`, and Pydantic `ValidationError` and raise `EvaluationSchemaError("invalid per-case retrieval metric schema")` from the original error. Raise `EvaluationSchemaError("case status does not match metrics status")` when `row["status"] != metrics.status`. For every per-case ratio object, sum its explicit numerator/denominator. Macro-average only non-`None` values. Build stage micro recall from `applicable_gold_counts` and `matched_gold_counts`; never read the removed nonexistent keys `total_gold_items` or `found_gold_*`.

Use case `status` for no-candidate and technical-error rates. For each of these operational rates, the denominator is every case handed to aggregation, including quality-skipped cases; numerators are mutually classified from the exact status. Keep skipped quality cases in `skip_reason_counts` and do not remove them from operational-rate denominators.

For each stage, collect all non-null `configured_capacity` values. Emit the sole unique value, emit `None` when none were reported, and raise the tested `EvaluationSchemaError` when more than one distinct capacity exists. This turns a mixed-profile or corrupted aggregate into a typed schema failure instead of a misleading report.

Aggregate each per-case `first_loss_by_evidence` value into the matching stage's `first_loss_evidence_count`. Evidence present through final output has no loss entry and adds no loss count. Reject unknown first-loss stage names with a schema error instead of silently adding an ad hoc report column.

- [ ] **Step 7: Validate report input and render v3 fields only**

At the top of `generate_markdown_report()`, validate and translate the public error:

```python
try:
    summary = RetrievalAggregateMetrics.model_validate(retrieval_summary)
except ValidationError as error:
    raise EvaluationSchemaError(
        "invalid aggregate retrieval metric schema"
    ) from error
```

Render from `summary.document_recall`, `summary.stages`, and the typed rate fields. Remove reads of `doc_recall`, `article_recall`, `ndcg_10`, `exact_reference_hit_rate`, `avg_scored_case_count`, and `micro_doc_survival_rate` legacy names.

- [ ] **Step 8: Run focused and broader verification**

```powershell
python -m pytest -q tests/evaluation/test_reporting_v3.py tests/evaluation/test_retrieval_metrics_v3.py tests/test_evaluation_framework.py
python -m ruff check --select E4,E7,E9,F app/
git diff --check
```

- [ ] **Step 9: Conditional commit checkpoint**

Only with authorization:

```powershell
git add app/evaluation/schemas.py app/evaluation/retrieval_metrics.py app/evaluation/reporting.py tests/evaluation/test_reporting_v3.py
git commit -m "fix(eval): unify metric aggregation and reporting"
```

---

### Task 7: Make Judge-Free Evaluation the Documented Default

**Files:**
- Create: `tests/evaluation/test_default_entrypoints.py`
- Create: `docs/evaluation/CURRENT_STATUS.md`
- Modify: `run_eval_suite.py:161-178,1160-1210`
- Modify: `README.md:31-45,216-241`

**Interfaces:**
- Consumes: CLI arguments.
- Produces: `judge_enabled(arguments) -> bool`; default `--judge none`; explicit `--judge ragas`; deprecated `--skip-ragas` remains accepted but hidden.

- [ ] **Step 1: Write failing parser/default tests**

Create `tests/evaluation/test_default_entrypoints.py`:

```python
from run_answer_eval import (
    build_parser as build_answer_parser,
    run_stage_b_offline,
)
from run_eval_suite import build_parser as build_legacy_parser, judge_enabled
from run_retrieval_eval import build_parser as build_retrieval_parser


def test_answer_evaluator_defaults_to_no_judge() -> None:
    assert build_answer_parser().parse_args([]).judge == "none"


def test_retrieval_evaluator_has_no_judge_mode() -> None:
    assert not hasattr(build_retrieval_parser().parse_args([]), "judge")


def test_legacy_evaluator_defaults_to_no_judge() -> None:
    args = build_legacy_parser().parse_args([])
    assert args.judge == "none"
    assert judge_enabled(args) is False


def test_ragas_requires_explicit_opt_in() -> None:
    args = build_legacy_parser().parse_args(["--judge", "ragas"])
    assert judge_enabled(args) is True


def test_deprecated_skip_ragas_overrides_opt_in() -> None:
    args = build_legacy_parser().parse_args(
        ["--judge", "ragas", "--skip-ragas"]
    )
    assert judge_enabled(args) is False
```

Add an async integration test that runs the legacy suite with zero selected cases, temporary checkpoint/report paths, and provider-bearing functions patched to fail:

```python
@pytest.mark.asyncio
async def test_legacy_default_executes_zero_judge_calls(tmp_path) -> None:
    args = build_legacy_parser().parse_args(
        [
            "--factoids", "0",
            "--multihop", "0",
            "--unanswerable", "0",
            "--checkpoint", str(tmp_path / "checkpoint.json"),
            "--report", str(tmp_path / "report.md"),
        ]
    )
    with (
        patch("run_eval_suite.verify_evaluation_fts", new=AsyncMock()),
        patch("run_eval_suite.warm_evaluation_guardrails", new=AsyncMock()),
        patch(
            "run_eval_suite.build_ragas_evaluator",
            side_effect=AssertionError("judge provider called"),
        ) as judge_factory,
    ):
        results = await run_suite(args)
    assert results == []
    judge_factory.assert_not_called()
```

Import `AsyncMock`, `patch`, and `run_suite`. The repository-wide no-network autouse fixture remains active; this test proves the default control flow, not merely parser defaults.

Add an answer Stage-B control-flow test with a synthetic `GoldenCase`, a successful `RetrievalCaseResult`, non-empty contexts, and `judge_mode=build_answer_parser().parse_args([]).judge`. Patch `run_eval_suite.build_ragas_evaluator` to raise `AssertionError("judge provider called")`; assert `run_stage_b_offline()` returns deterministic metrics and the patched factory is not called. Non-empty contexts are required so the test proves judge-mode gating rather than context gating.

- [ ] **Step 2: Run tests to verify RED**

```powershell
python -m pytest -q tests/evaluation/test_default_entrypoints.py
```

Expected: `judge` and `judge_enabled` do not exist in `run_eval_suite.py`.

- [ ] **Step 3: Implement explicit judge selection**

Replace the public default with:

```python
parser.add_argument(
    "--judge",
    choices=["none", "ragas"],
    default="none",
    help="Optional LLM judge audit (default: none)",
)
parser.add_argument(
    "--skip-ragas",
    action="store_true",
    help=argparse.SUPPRESS,
)
```

Add:

```python
def judge_enabled(arguments) -> bool:
    return (
        getattr(arguments, "judge", "none") == "ragas"
        and not getattr(arguments, "skip_ragas", False)
    )
```

Replace `run_ragas = not args.skip_ragas` with `run_ragas = judge_enabled(args)`.

Change `EVALUATION_VERSION` from `golden-v3-ragas-0.4` to `golden-v3-deterministic-1.0`; `evaluation_fingerprint()` already includes `run_ragas`, so explicit Ragas audits remain distinguishable. Existing legacy checkpoints with the old evaluator version must be ignored by the existing fingerprint validation, not silently reused.

- [ ] **Step 4: Update README canonical commands**

Make these the first evaluation commands:

```powershell
python -u run_retrieval_eval.py --preflight-all-profiles --verified-only --gold-policy all-required-verified --rewrite off --reranker current
python -u run_retrieval_eval.py --profile separated_intent --verified-only --gold-policy all-required-verified --rewrite off --reranker current
python -u run_answer_eval.py --profile separated_intent --verified-only --judge none --guardrails off
```

State explicitly that current preflight exits non-zero because verified case count is zero. Move legacy `run_eval_suite.py` to a compatibility section and show `--judge ragas` only under optional audit with cost warning.

- [ ] **Step 5: Create current status without rewriting history**

Create `docs/evaluation/CURRENT_STATUS.md` containing:

```markdown
# VietLex Evaluation Current Status

**Status:** P0 implementation pending final verification

- Historical 2026-08-03 retrieval runs remain invalid for decision-making.
- Current sidecar: 420 cases, 483 evidence items, 0 verified evidence items.
- Clean live retrieval baseline: BLOCKED until verified gold exists and P0 is committed/clean.
- Ragas: optional audit only; disabled by default.
- Production readiness: NOT DEMONSTRATED.

## Evidence policy

Only immutable runs with dataset, sidecar, source-state, configuration, provider/model, command, and metric-version provenance may be used for decisions.
```

Task 8 updates only the status/evidence section after commands actually run.

- [ ] **Step 6: Run focused documentation/default checks**

```powershell
python -m pytest -q tests/evaluation/test_default_entrypoints.py tests/test_run_eval_suite.py
python -m ruff check --select E4,E7,E9,F app/
git diff --check
```

Use `rg` to verify README does not call Ragas the default:

```powershell
rg -n "skip-ragas|judge ragas|run_eval_suite" README.md
```

Review every match; compatibility/optional-audit references are allowed, default recommendations are not.

- [ ] **Step 7: Conditional commit checkpoint**

Only with authorization:

```powershell
git add run_eval_suite.py README.md docs/evaluation/CURRENT_STATUS.md tests/evaluation/test_default_entrypoints.py
git commit -m "docs(eval): make deterministic evaluation the default"
```

---

### Task 8: Run the P0 Verification Matrix and Record Honest Status

**Files:**
- Modify: `docs/evaluation/CURRENT_STATUS.md`
- Verify only: all P0 production/test files

**Interfaces:**
- Consumes: completed Tasks 1-7.
- Produces: exact verification evidence; no live calls; no production-readiness claim.

- [ ] **Step 1: Run every focused P0 test file**

```powershell
python -m pytest -q tests/evaluation/test_runtime_contracts.py tests/evaluation/test_provenance.py tests/evaluation/test_preflight.py tests/evaluation/test_legal_citations.py tests/evaluation/test_retrieval_metrics_v3.py tests/evaluation/test_reporting_v3.py tests/evaluation/test_default_entrypoints.py
```

Expected: exit 0. Record the exact pass count and duration; do not reuse the plan's baseline count.

- [ ] **Step 2: Run the broader evaluation/retrieval suite**

```powershell
python -m pytest -q tests/test_evaluation_framework.py tests/test_run_eval_suite.py tests/test_rag_pipeline.py tests/services/test_retrieval.py tests/services/test_remote_reranker.py
```

Expected: exit 0 with no live-provider calls.

- [ ] **Step 3: Run the full provider-free suite**

```powershell
python -m pytest -q
```

Expected: exit 0; the live reranker integration remains skipped unless the existing opt-in environment flag was explicitly set. Do not set it in P0.

- [ ] **Step 4: Run static gates**

```powershell
python -m ruff check --select E4,E7,E9,F app/
python -m compileall -q app tests
git diff --check
rg -n "python-version: '3.10'|ruff check --select E4,E7,E9,F app/|pytest -q" .github/workflows/ci-cd.yml
```

Expected: all exit 0 and the final search returns all three existing CI contracts. Do not add a live-provider flag or secret to CI.

- [ ] **Step 5: Execute one provider-free blocked preflight**

Use a fresh repository-relative temporary directory so emitted canonical paths remain POSIX/repository-relative:

```powershell
$p0RunId = "p0-verify-" + [guid]::NewGuid().ToString("N")
$p0Output = Resolve-Path -LiteralPath 'docs\evaluation\preflight'
$p0Target = Join-Path $p0Output.Path $p0RunId
New-Item -ItemType Directory -Path $p0Target | Out-Null
python -u run_retrieval_eval.py --preflight-all-profiles --verified-only --gold-policy all-required-verified --rewrite off --reranker current --preflight-output-dir $p0Target
if ($LASTEXITCODE -ne 1) { throw "Expected BLOCKED preflight exit code 1" }
Get-ChildItem -LiteralPath $p0Target -File | Sort-Object Name
```

Task 3 must add `--preflight-output-dir` as a `Path` option and compute its repository-relative POSIX artifact prefix. Reject output directories outside `PROJECT_ROOT` with `ValueError`. Do not delete this verification artifact; it is an honest dirty-tree P0 artifact and must not be mistaken for the future clean baseline.

Inspect the comparison JSON and assert manually:

- `batch_status == "BLOCKED"`;
- `provider_calls == 0`;
- exactly three profiles;
- identical source-state SHA and selected-case hash across profiles;
- all canonical paths are relative POSIX paths;
- current working-tree dirty state is recorded truthfully.

- [ ] **Step 6: Record exact verification evidence**

Update `docs/evaluation/CURRENT_STATUS.md` only after Steps 1-5. If every gate passes, change status to:

```markdown
**Status:** P0 verified locally; clean committed baseline NOT RUN
```

Add the exact command summary lines copied from the console, the P0 preflight artifact path, current Git SHA, `git_dirty`, source-state SHA, provider calls `0`, remote data modified `no`, and live benchmark `NOT RUN`.

If any gate fails, keep `P0 implementation pending final verification`, record the exact failing command/output, and return to the owning task instead of editing around the failure.

- [ ] **Step 7: Check final worktree and preserved artifacts**

```powershell
git status --short --branch
git diff --stat
git diff --check
```

Compare historical run checksums using the existing `test_historical_runs_checksum_preservation` and confirm `git diff --name-only -- docs/evaluation/runs` prints no paths from any existing historical run directory.

- [ ] **Step 8: Conditional final P0 commit checkpoint**

Only after explicit authorization and only if every verification gate passes:

```powershell
git add app/evaluation app/services/retrieval.py run_retrieval_eval.py run_answer_eval.py run_eval_suite.py audit_golden_dataset.py tests README.md docs/evaluation/CURRENT_STATUS.md docs/superpowers/specs/2026-08-08-vietlex-evaluation-trust-foundation-design.md docs/superpowers/plans/2026-08-08-vietlex-evaluation-trust-foundation.md
git commit -m "fix(eval): establish trustworthy deterministic evaluation"
```

Do not add generated P0 preflight artifacts to the commit unless the user separately authorizes preserving that exact dirty-tree evidence in Git.

After a commit is authorized and created, rerun provider-free preflight from the clean commit before P1/P2. That clean preflight is a separate future action, not evidence retroactively inferred from the dirty-tree P0 run.

## Gated Project Completion Roadmap After P0

P0 is the only implementation scope in Tasks 1-8. The remaining project is deliberately split into separately specified, reviewable phases so evidence discovered in one phase cannot force repeated rewrites across every subsystem. At the end of each phase, use `superpowers:brainstorming` to confirm the evidence-dependent design and `superpowers:writing-plans` to create the named phase plan before editing that phase's code.

### P1 — Verified Gold Adjudication

**Entry gate:** P0 passes locally; an authorized clean commit/preflight exists; historical artifacts are unchanged.

**Separate plan:** `docs/superpowers/plans/YYYY-MM-DD-vietlex-verified-gold-adjudication.md`.

**Required delivery:**

- Build an immutable, stratified adjudication queue of 30-50 answerable cases using deterministic candidate generation only.
- Each row contains case ID, question, reference answer/context hash, parsed citation units, candidate document IDs/numbers/URLs, matched structural Article/Clause, anchor diagnostics, corpus revision, source-state SHA, auditor decision, confidence, notes, and reviewer identity/time.
- Candidate generation may expose possibilities; only a recorded human decision may promote evidence to `verified`.
- Preserve rejected, corpus-missing, ambiguous, and insufficient-evidence decisions instead of forcing the target count.
- Promotion writes a new versioned sidecar and audit summary; it never overwrites the current sidecar. Promotion requires explicit user approval after a diff/report of status changes.

**Exit gate:** exact case-set validation passes; every promoted item has resolved document identity plus structural evidence at its required level; sidecar hashes and provenance are recorded. Preferred sample size is 30-50 verified cases, but if the corpus cannot support 30, exit `BLOCKED` with honest adjudication evidence rather than weakening verification.

### P2 — Clean Three-Profile Retrieval Baseline

**Entry gate:** P1 produced a promoted, approved sidecar with sufficient verified evidence; Git is clean; dataset/corpus revisions are pinned; user explicitly authorizes live Pinecone/Qdrant/reranker calls and their cost.

**Separate plan:** `docs/superpowers/plans/YYYY-MM-DD-vietlex-clean-retrieval-baseline.md`.

**Required delivery:**

- Freeze one selected-case ID list and one provider/model catalog before the first run.
- Run `legacy`, `separated_no_intent`, and `separated_intent` against the same commit, dataset, sidecar, selected cases, corpus revision, rewrite/reranker policy, and metric version.
- Store one immutable run directory per profile plus one comparison artifact. Record observed provider/model outcomes per case, not merely configured candidates.
- Compare document/article/clause Recall@K, MRR, nDCG@10, exact-reference hit, multi-hop coverage, first-loss counts, candidate distributions, latency, no-candidate rate, and retrieval/reranker technical-error rates.
- Do not call Ragas and do not modify ingestion or persistent vectors.

**Exit gate:** all three runs validate against the v3 schema, share identical comparison invariants, and have no unexplained schema/provenance error. This establishes a baseline; it does not by itself establish acceptable quality.

### P3 — Evidence-Driven Retrieval Optimization

**Entry gate:** P2 comparison identifies measured loss stages or technical bottlenecks.

**Separate plan:** one plan per experiment family under `docs/superpowers/plans/`, never one plan that changes multiple independent retrieval variables.

**Experiment protocol:**

- Pre-register one changed variable, primary metric, guardrail metrics, identical case set, input hash, provider versions, and rollback condition.
- Start with non-ingestion variables indicated by first loss: Pinecone/FTS limits, merge/resolution capacity, local structural selection, intent scoring, reranker input/return limits, or reranker provider.
- Any reranker A/B uses byte-identical reranker inputs. Any provider switch records observed provider/model and technical errors.
- Accept a change only when the primary deterministic metric improves without an unapproved regression in required-level recall, technical-error rate, or latency guardrail; retain both immutable runs and the comparison.
- E5 prefix/model/dimension, Pinecone metric, sparse document representation, metadata filter contract, and vector hierarchy changes cross the reingestion boundary. They require a migration design, benchmark justification, explicit authorization, rollback plan, and separately scheduled ingestion.

**Exit gate:** selected retrieval configuration is supported by reproducible comparisons, or the phase records that no tested change beat baseline. Update `app/config.py`, current architecture docs, and runbooks only for the configuration actually selected.

### P4 — Answer, Citation, Refusal, and Guardrail Evaluation

**Entry gate:** P3 selects a stable retrieval configuration and retrieval evidence coverage is sufficient for answer testing.

**Separate plan:** `docs/superpowers/plans/YYYY-MM-DD-vietlex-answer-guardrail-evaluation.md`.

**Required delivery:**

- Curate expected numbers, dates, entities, citations, answerability, and refusal labels for the approved subset with provenance.
- Keep online Stage A (retrieval, generation, optional guardrails) outside offline Stage B deterministic metrics; never hold the online semaphore during offline metrics, report writes, checkpoints, or judge audits.
- Evaluate normalized exact match, token precision/recall/F1, character F1, secondary ROUGE-L/CHRF, expected field precision/recall, legal citation precision/recall/coverage, invalid-citation rate, refusal precision/recall, and mixed-claim-plus-refusal rate.
- Run guardrails in `off`, `shadow`, and `enforce` on identical inputs. Report rejection separately from guardrail technical error; a technical failure is never a hallucination block.
- Ragas, if explicitly authorized, runs only as a small opt-in audit after deterministic results and records cost/provider failures separately.

**Exit gate:** immutable answer runs and comparison reports pass schema validation, deterministic denominators are complete, guardrail modes are distinguishable, and all provider calls/cost-bearing audits are explicitly recorded.

### P5 — Delivery Readiness

**Entry gate:** retrieval and answer/guardrail evaluations meet acceptance thresholds defined from P2-P4 evidence; no unresolved P0 schema/provenance defects remain.

**Separate plans:** security/privacy review, load/SLO validation, deployment verification, corpus/index drift monitoring, and user-facing demo/frontend are independent plans.

**Required delivery:**

- Run focused security tests for authentication, CSRF, CORS, rate limits, secret handling, private-log redaction, and typed provider/database failures.
- Run authorized load tests with pinned corpus/index versions; report latency distributions, error budgets, resource limits, and recovery behavior.
- Define SLOs and alerts for API latency/errors, retrieval/reranker failures, no-candidate drift, corpus/index revision mismatch, content-store resolution failures, and guardrail technical errors.
- Verify deployment, backup/restore, rollback, and drift checks without deleting or recreating durable indexes.
- Build or finish a user-facing frontend only if product scope requires it, after API/evaluation contracts stabilize.

**Exit gate:** deployment and rollback are actually exercised, monitoring evidence exists, known limitations are documented, and a reproducible benchmark supports any production-readiness claim. Without all four, status remains `NOT DEMONSTRATED`.

## Execution Stop Conditions

Stop and request user direction if any of these occur:

- a fix would change the persistent embedding or sparse document contract;
- a command would ingest/reindex/delete/recreate remote or local durable data;
- live provider calls become necessary;
- verified gold must be promoted without human adjudication evidence;
- historical artifacts would need modification;
- a commit/push/PR is needed and authorization is absent;
- current HEAD diverges materially from the audited design and invalidates interfaces in this plan.

Ordinary test failures are not stop conditions. Diagnose them with `superpowers:systematic-debugging`, fix the owning task, and rerun its focused gate.

## P0 Completion Report Contract

The final P0 report must list:

- files changed;
- exact commands executed;
- focused unit tests, broader tests, full tests, and live tests separately;
- exact pass/fail/skip counts;
- Ruff/compile/diff results;
- provider calls and remote modifications;
- Git SHA, dirty flags, diff SHA, source-state SHA;
- artifact paths and whether each is canonical, reused, blocked, or mutable;
- anything `NOT RUN`;
- remaining limitations, especially 0 verified gold and no clean live baseline;
- confirmation that production readiness remains unproven.
