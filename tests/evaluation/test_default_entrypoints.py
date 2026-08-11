import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import run_answer_eval
import run_eval_suite
import run_retrieval_eval
import run_structural_index_pilot
import run_structural_retrieval_eval
from app.evaluation.structural_pilot_eval import StructuralEvaluationError
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


def test_structural_manifest_console_json_is_windows_safe() -> None:
    payload = {"legal_type": "Hiến pháp"}

    rendered = run_structural_index_pilot._console_json(payload)

    assert rendered.isascii()
    assert json.loads(rendered) == payload


def test_structural_benchmark_requires_exact_remote_authorization() -> None:
    arguments = run_structural_retrieval_eval.build_parser().parse_args(
        [
            "benchmark",
            "--sidecar",
            "labels.json",
            "--plan",
            "plan.json",
            "--plan-sha256",
            "1" * 64,
            "--create-receipt",
            "create.json",
            "--create-receipt-sha256",
            "2" * 64,
            "--probe-report",
            "probe.json",
            "--probe-report-sha256",
            "3" * 64,
            "--upload-report",
            "upload.json",
            "--upload-report-sha256",
            "4" * 64,
            "--finalize-receipt",
            "finalize.json",
            "--finalize-receipt-sha256",
            "5" * 64,
            "--verify-receipt",
            "verify.json",
            "--verify-receipt-sha256",
            "6" * 64,
            "--p2-baseline-sha256",
            "7" * 64,
            "--source-state-sha256",
            "8" * 64,
            "--collection",
            "vietlex-legal-rag-v2-pilot",
            "--run-id",
            "structural-benchmark",
            "--allow-remote-benchmark",
        ]
    )

    assert arguments.dataset == Path(
        "app/data/namsyntax_legal_qa_420_curated_v1.json"
    )
    assert arguments.p2_baseline == Path(
        "docs/evaluation/comparisons/p2-aa3208c/comparison.json"
    )
    assert arguments.allow_remote_benchmark is True


@pytest.mark.asyncio
async def test_structural_benchmark_rejects_programmatic_missing_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_chain(_arguments):
        raise AssertionError("artifact chain was evaluated before authorization")

    monkeypatch.setattr(
        run_structural_retrieval_eval,
        "_validate_chain",
        forbidden_chain,
    )
    with pytest.raises(StructuralEvaluationError, match="authorization"):
        await run_structural_retrieval_eval._run_benchmark(
            SimpleNamespace(allow_remote_benchmark=False)
        )


@pytest.mark.asyncio
async def test_structural_benchmark_persists_remote_initialization_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    digest = "a" * 64
    dataset_bytes = b"[]"
    dataset_sha256 = hashlib.sha256(dataset_bytes).hexdigest()
    manifest = SimpleNamespace(dataset_revision="revision-1")
    contract = SimpleNamespace(
        collection_name="vietlex-legal-rag-v2-pilot",
        dense_vector_name="dense",
        sparse_vector_name="bm25",
        dense_model="Qwen/Qwen3-Embedding-0.6B",
        dense_model_options={},
        sparse_model="qdrant/bm25",
        sparse_model_options={},
        dense_size=1024,
        query_instruction_version="vietlex-vn-legal-retrieval-v1",
        query_instruction="query instruction",
        dense_top_k=24,
        bm25_top_k=24,
        fused_limit=24,
        rrf_k=60,
        per_document_limit=3,
        chunk_max_tokens=220,
        chunk_overlap_tokens=24,
    )
    plan = SimpleNamespace(
        manifest=manifest,
        contract=contract,
        source_state_sha256=digest,
        plan_sha256=digest,
    )
    probe = SimpleNamespace(
        dataset_sha256=dataset_sha256,
        sidecar_sha256=digest,
    )
    selected = SimpleNamespace(
        selected_case_ids_sha256=digest,
        selected_cases=(SimpleNamespace(case_id="case-1"),),
        selected_case_ids=("case-1",),
    )
    scope_selection = SimpleNamespace(
        cases=selected.selected_cases,
        skipped_cases={},
        case_ids=("case-1",),
        case_ids_sha256=digest,
    )
    provenance = SimpleNamespace(
        status="ok",
        source_state_sha256=digest,
    )
    settings = SimpleNamespace(
        STRUCTURAL_BACKEND_ENABLED=True,
        CONTENT_STORE_PATH=tmp_path / "content.db",
        DATASET_REPOSITORY="repo",
        DATASET_REVISION="revision-1",
        LEGAL_FTS_PATH=tmp_path / "fts.db",
    )
    recorded: dict[str, object] = {}

    class FakeRun:
        acceptance = "BLOCKED_TECHNICAL"

        @staticmethod
        def model_dump_json() -> str:
            return "{}"

    class FakeBuilder:
        def __init__(self, **_kwargs) -> None:
            pass

        def add(self, _record) -> None:
            pass

        def build(self):
            return manifest

    async def capture_blocked(_cases, _retriever, _root, **kwargs):
        recorded.update(kwargs)
        return FakeRun()

    async def close_no_clients() -> None:
        return None

    monkeypatch.setattr(
        run_structural_retrieval_eval, "_validate_chain", lambda _args: (plan, probe)
    )
    monkeypatch.setattr(
        run_structural_retrieval_eval,
        "_load_dataset_selection",
        lambda *_args: (
            dataset_bytes,
            SimpleNamespace(metadata=SimpleNamespace(sidecar_sha256=digest)),
            selected,
        ),
    )
    monkeypatch.setattr(run_structural_retrieval_eval, "sha256_path", lambda _p: digest)
    monkeypatch.setattr(
        run_structural_retrieval_eval,
        "validate_p2_baseline",
        lambda *_args: SimpleNamespace(
            source_document_recall_at_24=0.1,
            scope_errors=(),
        ),
    )
    monkeypatch.setattr(
        run_structural_retrieval_eval, "load_json_object", lambda _p: {}
    )
    monkeypatch.setattr(
        run_structural_retrieval_eval, "collect_git_provenance", lambda: provenance
    )
    monkeypatch.setattr(run_structural_retrieval_eval, "get_settings", lambda: settings)
    monkeypatch.setattr(
        run_structural_retrieval_eval.StructuralQdrantContract,
        "from_settings",
        lambda _settings: contract,
    )
    monkeypatch.setattr(run_structural_retrieval_eval, "ContentStore", lambda _p: object())
    monkeypatch.setattr(
        run_structural_retrieval_eval,
        "select_structural_document_ids",
        lambda _store: (1,),
    )
    monkeypatch.setattr(
        run_structural_retrieval_eval, "StructuralManifestBuilder", FakeBuilder
    )
    monkeypatch.setattr(
        run_structural_retrieval_eval, "iter_structural_records", lambda *_a, **_k: ()
    )
    monkeypatch.setattr(
        run_structural_retrieval_eval,
        "load_verified_probe_scope",
        lambda *_args: SimpleNamespace(selection=scope_selection),
    )
    monkeypatch.setattr(
        run_structural_retrieval_eval, "_validate_probe_scope", lambda *_args: None
    )
    monkeypatch.setattr(
        run_structural_retrieval_eval,
        "LegalFtsIndex",
        lambda **_kwargs: SimpleNamespace(is_ready=lambda: True),
    )
    monkeypatch.setattr(
        run_structural_retrieval_eval,
        "create_structural_qdrant_client",
        lambda _settings: (_ for _ in ()).throw(RuntimeError("secret detail")),
    )
    monkeypatch.setattr(
        run_structural_retrieval_eval,
        "run_structural_pilot_evaluation",
        capture_blocked,
    )
    monkeypatch.setattr(
        run_structural_retrieval_eval,
        "close_clients",
        close_no_clients,
    )

    arguments = SimpleNamespace(
        allow_remote_benchmark=True,
        dataset=tmp_path / "dataset.json",
        sidecar=tmp_path / "sidecar.json",
        p2_baseline=tmp_path / "baseline.json",
        p2_baseline_sha256=digest,
        source_state_sha256=digest,
        collection="vietlex-legal-rag-v2-pilot",
        output_root=tmp_path,
        run_id="remote-init-blocked",
        create_receipt_sha256=digest,
        probe_report_sha256=digest,
        upload_report_sha256=digest,
        finalize_receipt_sha256=digest,
        verify_receipt_sha256=digest,
    )

    assert await run_structural_retrieval_eval._run_benchmark(arguments) == 2
    assert recorded["technical_preflight_errors"] == [
        "remote_initialization:RuntimeError"
    ]


def test_structural_benchmark_rejects_probe_contract_drift() -> None:
    plan = SimpleNamespace(
        manifest=SimpleNamespace(dataset_revision="revision-1"),
        contract=SimpleNamespace(
            dense_model="Qwen/Qwen3-Embedding-0.6B",
            sparse_model="qdrant/bm25",
            dense_model_options={"truncate": False},
            sparse_model_options={"language": "vi"},
            query_instruction_version="vietlex-vn-legal-retrieval-v1",
        ),
    )
    probe = SimpleNamespace(
        dataset_revision="revision-1",
        candidate_dense_model="Qwen/Qwen3-Embedding-0.6B",
        candidate_sparse_model="qdrant/bm25",
        candidate_dense_model_options={"truncate": True},
        candidate_sparse_model_options={"language": "vi"},
        query_instruction_version="vietlex-vn-legal-retrieval-v1",
    )

    with pytest.raises(StructuralEvaluationError, match="model contract"):
        run_structural_retrieval_eval._validate_probe_contract(plan, probe)


def test_structural_benchmark_rejects_probe_scope_drift() -> None:
    selection = SimpleNamespace(
        case_ids=("case-1",),
        case_ids_sha256="a" * 64,
        skipped_cases={"case-2": "outside_primary_legislation_scope"},
    )
    probe = SimpleNamespace(
        case_ids=("case-1",),
        case_ids_sha256="b" * 64,
        skipped_cases={"case-2": "outside_primary_legislation_scope"},
    )

    with pytest.raises(StructuralEvaluationError, match="scope binding"):
        run_structural_retrieval_eval._validate_probe_scope(selection, probe)


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


def test_structural_probe_entrypoint_requires_bound_live_scope() -> None:
    arguments = run_structural_index_pilot.build_parser().parse_args(
        [
            "probe-model",
            "--plan",
            "plan.json",
            "--create-receipt",
            "create-receipt.json",
            "--create-receipt-sha256",
            "c" * 64,
            "--sidecar",
            "promoted-labels.json",
            "--plan-sha256",
            "a" * 64,
            "--source-state-sha256",
            "b" * 64,
            "--collection",
            "vietlex-legal-rag-v2-pilot",
            "--allow-remote-write",
        ]
    )

    assert arguments.command_name == "probe-model"
    assert arguments.dataset == Path(
        "app/data/namsyntax_legal_qa_420_curated_v1.json"
    )
    assert arguments.sidecar == Path("promoted-labels.json")
    assert arguments.reference_probe is None


@pytest.mark.parametrize(
    ("command_name", "upstream_flags"),
    [
        (
            "upload",
            [
                "--create-receipt",
                "create.json",
                "--create-receipt-sha256",
                "c" * 64,
                "--probe-report",
                "probe.json",
                "--probe-report-sha256",
                "d" * 64,
                "--checkpoint",
                "state.sqlite3",
            ],
        ),
        (
            "finalize",
            [
                "--create-receipt",
                "create.json",
                "--create-receipt-sha256",
                "c" * 64,
                "--probe-report",
                "probe.json",
                "--probe-report-sha256",
                "d" * 64,
                "--upload-report",
                "upload.json",
                "--upload-report-sha256",
                "e" * 64,
            ],
        ),
        (
            "verify",
            [
                "--create-receipt",
                "create.json",
                "--create-receipt-sha256",
                "c" * 64,
                "--probe-report",
                "probe.json",
                "--probe-report-sha256",
                "d" * 64,
                "--upload-report",
                "upload.json",
                "--upload-report-sha256",
                "e" * 64,
                "--finalize-receipt",
                "finalize.json",
                "--finalize-receipt-sha256",
                "f" * 64,
            ],
        ),
    ],
)
def test_structural_remote_phases_require_exact_artifact_chain(
    command_name: str,
    upstream_flags: list[str],
) -> None:
    arguments = run_structural_index_pilot.build_parser().parse_args(
        [
            command_name,
            "--plan",
            "plan.json",
            *upstream_flags,
            "--plan-sha256",
            "a" * 64,
            "--source-state-sha256",
            "b" * 64,
            "--collection",
            "vietlex-legal-rag-v2-pilot",
            "--allow-remote-write",
        ]
    )

    assert arguments.command_name == command_name
    assert arguments.allow_remote_write is True


@pytest.mark.parametrize("command_name", ["upload", "finalize", "verify"])
def test_structural_remote_phase_rejects_missing_bindings(
    command_name: str,
) -> None:
    with pytest.raises(SystemExit):
        run_structural_index_pilot.build_parser().parse_args([command_name])


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
