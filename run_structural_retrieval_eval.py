"""Fail-closed benchmark entrypoint for the opt-in Qdrant structural pilot."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from app.config import get_settings
from app.evaluation.case_selection import build_cases, select_evaluation_cases
from app.evaluation.gold_sidecar import load_gold_sidecar
from app.evaluation.provenance import collect_git_provenance
from app.evaluation.structural_model_probe import (
    StructuralModelProbeReport,
    load_verified_probe_scope,
)
from app.evaluation.structural_pilot_eval import (
    StructuralEvaluationBinding,
    StructuralEvaluationError,
    load_json_object,
    run_structural_pilot_evaluation,
    sha256_path,
    validate_p2_baseline,
)
from app.ingestion.content_store import ContentStore
from app.ingestion.legal_fts import LegalFtsIndex
from app.ingestion.structural_index import (
    StructuralManifestBuilder,
    iter_structural_records,
    select_structural_document_ids,
)
from app.ingestion.structural_pilot import (
    CollectionCreationReceipt,
    CollectionFinalizeReceipt,
    CollectionVerificationReceipt,
    StructuralPilotError,
    load_bound_plan,
)
from app.ingestion.structural_qdrant import (
    StructuralQdrantContract,
    create_structural_qdrant_client,
)
from app.ingestion.structural_upload import StructuralUploadReport
from app.services.clients import close_clients, get_remote_reranker
from app.services.structural_retrieval import build_structural_retriever


_Artifact = TypeVar("_Artifact", bound=BaseModel)


class _BlockedRetriever:
    async def retrieve(self, _query: str):
        raise AssertionError("blocked benchmark constructed a retrieval call")


def _exact_artifact(
    path: Path,
    expected_sha256: str,
    model: type[_Artifact],
    label: str,
) -> _Artifact:
    try:
        payload = Path(path).read_bytes()
    except OSError as error:
        raise StructuralEvaluationError(
            f"unable to read {label}: {type(error).__name__}"
        ) from error
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise StructuralEvaluationError(f"{label} SHA-256 mismatch")
    try:
        return model.model_validate_json(payload)
    except ValueError as error:
        raise StructuralEvaluationError(
            f"{label} schema validation failed"
        ) from error


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StructuralEvaluationError(message)


def _validate_probe_contract(plan, probe) -> None:
    expected = {
        "dataset_revision": plan.manifest.dataset_revision,
        "candidate_dense_model": plan.contract.dense_model,
        "candidate_sparse_model": plan.contract.sparse_model,
        "candidate_dense_model_options": dict(
            plan.contract.dense_model_options
        ),
        "candidate_sparse_model_options": dict(
            plan.contract.sparse_model_options
        ),
        "query_instruction_version": (
            plan.contract.query_instruction_version
        ),
    }
    if any(
        getattr(probe, field_name, None) != value
        for field_name, value in expected.items()
    ):
        raise StructuralEvaluationError("probe model contract mismatch")


def _validate_probe_scope(selection, probe) -> None:
    if (
        tuple(probe.case_ids) != tuple(selection.case_ids)
        or probe.case_ids_sha256 != selection.case_ids_sha256
        or dict(probe.skipped_cases) != dict(selection.skipped_cases)
    ):
        raise StructuralEvaluationError("probe scope binding mismatch")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark the verified opt-in Qdrant structural pilot.",
    )
    commands = parser.add_subparsers(dest="command_name", required=True)
    benchmark = commands.add_parser(
        "benchmark",
        help="run deterministic retrieval-only evaluation after PASS_VERIFY",
    )
    benchmark.add_argument(
        "--dataset",
        type=Path,
        default=Path("app/data/namsyntax_legal_qa_420_curated_v1.json"),
    )
    benchmark.add_argument("--sidecar", type=Path, required=True)
    benchmark.add_argument("--plan", type=Path, required=True)
    benchmark.add_argument("--plan-sha256", required=True)
    for name in (
        "create-receipt",
        "probe-report",
        "upload-report",
        "finalize-receipt",
        "verify-receipt",
    ):
        benchmark.add_argument(f"--{name}", type=Path, required=True)
        benchmark.add_argument(f"--{name}-sha256", required=True)
    benchmark.add_argument(
        "--p2-baseline",
        type=Path,
        default=Path(
            "docs/evaluation/comparisons/p2-aa3208c/comparison.json"
        ),
    )
    benchmark.add_argument("--p2-baseline-sha256", required=True)
    benchmark.add_argument("--source-state-sha256", required=True)
    benchmark.add_argument(
        "--evaluation-source-state-sha256",
        required=True,
        help="exact source-state SHA-256 of the evaluator/runtime code",
    )
    benchmark.add_argument(
        "--allow-separate-evaluation-source",
        action="store_true",
        help="allow evaluator fixes newer than the immutable index source",
    )
    benchmark.add_argument(
        "--collection",
        choices=["vietlex-legal-rag-v2-pilot-384"],
        required=True,
    )
    benchmark.add_argument(
        "--output-root",
        type=Path,
        default=Path("docs/evaluation/runs"),
    )
    benchmark.add_argument("--run-id", required=True)
    benchmark.add_argument(
        "--allow-remote-benchmark",
        action="store_true",
        required=True,
        help="authorize Qdrant inference/reads and remote reranker staging",
    )
    return parser


def _load_dataset_selection(dataset_path: Path, sidecar_path: Path):
    dataset_bytes = Path(dataset_path).read_bytes()
    try:
        raw = json.loads(dataset_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StructuralEvaluationError("evaluation dataset is malformed") from error
    if not isinstance(raw, list) or any(not isinstance(row, dict) for row in raw):
        raise StructuralEvaluationError("evaluation dataset must be an array")
    case_ids = [
        row.get("case_id", f"case_{index:03d}")
        for index, row in enumerate(raw, start=1)
    ]
    sidecar = load_gold_sidecar(sidecar_path, dataset_case_ids=case_ids)
    selection = select_evaluation_cases(
        build_cases(raw, sidecar.labels_by_case_id),
        "all-required-verified",
    )
    return dataset_bytes, sidecar, selection


def _validate_chain(arguments: argparse.Namespace):
    plan = load_bound_plan(arguments.plan)
    _require(plan.plan_sha256 == arguments.plan_sha256, "plan SHA-256 mismatch")
    _require(
        plan.source_state_sha256 == arguments.source_state_sha256,
        "plan source-state SHA-256 mismatch",
    )
    _require(plan.capacity.status == "PASS_CAPACITY", "plan is not PASS_CAPACITY")
    _require(
        plan.contract.collection_name == arguments.collection,
        "plan collection mismatch",
    )
    creation = _exact_artifact(
        arguments.create_receipt,
        arguments.create_receipt_sha256,
        CollectionCreationReceipt,
        "creation receipt",
    )
    probe = _exact_artifact(
        arguments.probe_report,
        arguments.probe_report_sha256,
        StructuralModelProbeReport,
        "model probe report",
    )
    upload = _exact_artifact(
        arguments.upload_report,
        arguments.upload_report_sha256,
        StructuralUploadReport,
        "upload report",
    )
    finalize = _exact_artifact(
        arguments.finalize_receipt,
        arguments.finalize_receipt_sha256,
        CollectionFinalizeReceipt,
        "finalize receipt",
    )
    verify = _exact_artifact(
        arguments.verify_receipt,
        arguments.verify_receipt_sha256,
        CollectionVerificationReceipt,
        "verification receipt",
    )
    _require(probe.acceptance == "PASS_MODEL_PROBE", "probe is not PASS_MODEL_PROBE")
    _validate_probe_contract(plan, probe)
    _require(upload.status == "UPLOAD_COMPLETE", "upload is not complete")
    _require(finalize.status == "PASS_FINALIZE", "finalize is not PASS_FINALIZE")
    _require(verify.status == "PASS_VERIFY", "verification is not PASS_VERIFY")
    common = {
        "collection_name": plan.contract.collection_name,
        "source_state_sha256": plan.source_state_sha256,
        "plan_sha256": plan.plan_sha256,
    }
    for label, artifact in (
        ("creation", creation),
        ("probe", probe),
        ("upload", upload),
        ("finalize", finalize),
        ("verify", verify),
    ):
        _require(
            all(getattr(artifact, field) == value for field, value in common.items()),
            f"{label} binding mismatch",
        )
    _require(
        probe.creation_receipt_sha256 == arguments.create_receipt_sha256,
        "probe creation binding mismatch",
    )
    _require(
        upload.creation_receipt_sha256 == arguments.create_receipt_sha256
        and upload.probe_report_sha256 == arguments.probe_report_sha256,
        "upload upstream binding mismatch",
    )
    _require(
        finalize.creation_receipt_sha256 == arguments.create_receipt_sha256
        and finalize.probe_report_sha256 == arguments.probe_report_sha256
        and finalize.upload_report_sha256 == arguments.upload_report_sha256,
        "finalize upstream binding mismatch",
    )
    _require(
        verify.creation_receipt_sha256 == arguments.create_receipt_sha256
        and verify.probe_report_sha256 == arguments.probe_report_sha256
        and verify.upload_report_sha256 == arguments.upload_report_sha256
        and verify.finalize_receipt_sha256
        == arguments.finalize_receipt_sha256,
        "verification upstream binding mismatch",
    )
    for label, artifact in (("upload", upload), ("verify", verify)):
        _require(
            artifact.dataset_revision == plan.manifest.dataset_revision
            and artifact.ordered_record_ids_sha256
            == plan.manifest.ordered_record_ids_sha256,
            f"{label} corpus binding mismatch",
        )
    _require(
        upload.manifest_record_count == plan.manifest.record_count
        and verify.points_count == plan.manifest.record_count,
        "remote point count does not match the plan",
    )
    return plan, probe


async def _run_benchmark(arguments: argparse.Namespace) -> int:
    _require(
        getattr(arguments, "allow_remote_benchmark", False) is True,
        "remote benchmark authorization is required",
    )
    plan, probe = _validate_chain(arguments)
    dataset_bytes, sidecar, selected = _load_dataset_selection(
        arguments.dataset,
        arguments.sidecar,
    )
    binding = StructuralEvaluationBinding(
        dataset_revision=plan.manifest.dataset_revision,
        dataset_sha256=hashlib.sha256(dataset_bytes).hexdigest(),
        sidecar_sha256=sidecar.metadata.sidecar_sha256,
        gold_policy="all-required-verified",
        selected_case_ids_sha256=selected.selected_case_ids_sha256,
        source_state_sha256=plan.source_state_sha256,
        evaluation_source_state_sha256=(
            arguments.evaluation_source_state_sha256
        ),
        collection_name=plan.contract.collection_name,
        plan_sha256=plan.plan_sha256,
        creation_receipt_sha256=arguments.create_receipt_sha256,
        probe_report_sha256=arguments.probe_report_sha256,
        upload_report_sha256=arguments.upload_report_sha256,
        finalize_receipt_sha256=arguments.finalize_receipt_sha256,
        verify_receipt_sha256=arguments.verify_receipt_sha256,
        p2_baseline_sha256=arguments.p2_baseline_sha256,
        dense_vector_name=plan.contract.dense_vector_name,
        sparse_vector_name=plan.contract.sparse_vector_name,
        dense_model=plan.contract.dense_model,
        dense_model_options=dict(plan.contract.dense_model_options),
        sparse_model=plan.contract.sparse_model,
        sparse_model_options=dict(plan.contract.sparse_model_options),
        dense_size=plan.contract.dense_size,
        query_instruction_version=plan.contract.query_instruction_version,
        query_instruction=plan.contract.query_instruction,
        dense_top_k=plan.contract.dense_top_k,
        bm25_top_k=plan.contract.bm25_top_k,
        fused_limit=plan.contract.fused_limit,
        rrf_k=plan.contract.rrf_k,
        per_document_limit=plan.contract.per_document_limit,
    )
    _require(
        probe.dataset_sha256 == binding.dataset_sha256
        and probe.sidecar_sha256 == binding.sidecar_sha256,
        "probe evaluation-scope binding mismatch",
    )
    if sha256_path(arguments.p2_baseline) != arguments.p2_baseline_sha256:
        raise StructuralEvaluationError("P2 baseline SHA-256 mismatch")
    baseline = validate_p2_baseline(
        load_json_object(arguments.p2_baseline),
        binding,
    )
    provenance = collect_git_provenance()
    _require(
        binding.evaluation_source_state_sha256 == binding.source_state_sha256
        or getattr(arguments, "allow_separate_evaluation_source", False)
        is True,
        "separate evaluation source authorization is required",
    )
    command = "python run_structural_retrieval_eval.py " + " ".join(sys.argv[1:])

    async def persist_blocked(
        cases,
        skipped_cases,
        *,
        scope_errors=(),
        technical_preflight_errors=(),
        current_provenance=provenance,
    ) -> int:
        run = await run_structural_pilot_evaluation(
            cases,
            _BlockedRetriever(),
            arguments.output_root,
            run_id=arguments.run_id,
            binding=binding,
            p2_source_document_recall_at_24=(
                baseline.source_document_recall_at_24
            ),
            skipped_cases=skipped_cases,
            provenance=current_provenance,
            scope_errors=scope_errors,
            technical_preflight_errors=technical_preflight_errors,
            command=command,
        )
        print(run.model_dump_json())
        return 5 if run.acceptance == "BLOCKED_SCOPE" else 2

    if baseline.scope_errors:
        return await persist_blocked(
            selected.selected_cases,
            {},
            scope_errors=baseline.scope_errors,
        )

    try:
        settings = get_settings()
        configured_contract = StructuralQdrantContract.from_settings(settings)
    except Exception as error:
        return await persist_blocked(
            selected.selected_cases,
            {},
            technical_preflight_errors=[
                f"local_settings:{type(error).__name__}"
            ],
        )
    if configured_contract != plan.contract:
        return await persist_blocked(
            selected.selected_cases,
            {},
            technical_preflight_errors=["configured_contract_mismatch"],
        )
    if not settings.STRUCTURAL_BACKEND_ENABLED:
        return await persist_blocked(
            selected.selected_cases,
            {},
            technical_preflight_errors=["structural_backend_disabled"],
        )

    try:
        store = ContentStore(settings.CONTENT_STORE_PATH)
        document_ids = select_structural_document_ids(store)
        builder = StructuralManifestBuilder(
            selected_document_ids=document_ids,
            repository=settings.DATASET_REPOSITORY,
            revision=settings.DATASET_REVISION,
            max_tokens=plan.contract.chunk_max_tokens,
            overlap_tokens=plan.contract.chunk_overlap_tokens,
        )

        def audited_records():
            for record in iter_structural_records(
                store,
                document_ids,
                repository=settings.DATASET_REPOSITORY,
                revision=settings.DATASET_REVISION,
                max_tokens=plan.contract.chunk_max_tokens,
                overlap_tokens=plan.contract.chunk_overlap_tokens,
            ):
                builder.add(record)
                yield record

        scope = load_verified_probe_scope(
            arguments.dataset,
            arguments.sidecar,
            audited_records(),
        )
        current_manifest = builder.build()
    except Exception as error:
        return await persist_blocked(
            selected.selected_cases,
            {},
            technical_preflight_errors=[
                f"local_scope_preflight:{type(error).__name__}"
            ],
        )
    if current_manifest != plan.manifest:
        return await persist_blocked(
            scope.selection.cases,
            scope.selection.skipped_cases,
            technical_preflight_errors=["local_structural_corpus_drift"],
        )
    resolved_case_ids = set(scope.selection.case_ids) | set(
        scope.selection.skipped_cases
    )
    if resolved_case_ids != set(selected.selected_case_ids):
        missing = set(selected.selected_case_ids) - resolved_case_ids
        skipped = dict(scope.selection.skipped_cases)
        skipped.update(
            {case_id: "scope_resolution_mismatch" for case_id in missing}
        )
        return await persist_blocked(
            scope.selection.cases,
            skipped,
            scope_errors=["resolved_structural_evaluation_scope_mismatch"],
        )
    try:
        _validate_probe_scope(scope.selection, probe)
    except StructuralEvaluationError:
        return await persist_blocked(
            scope.selection.cases,
            scope.selection.skipped_cases,
            scope_errors=["probe_scope_binding_mismatch"],
        )
    try:
        fts = LegalFtsIndex(
            store=store,
            path=settings.LEGAL_FTS_PATH,
            dataset_revision=settings.DATASET_REVISION,
        )
        fts_ready = fts.is_ready()
    except Exception as error:
        return await persist_blocked(
            scope.selection.cases,
            scope.selection.skipped_cases,
            technical_preflight_errors=[
                f"local_fts:{type(error).__name__}"
            ],
        )
    if not fts_ready:
        return await persist_blocked(
            scope.selection.cases,
            scope.selection.skipped_cases,
            technical_preflight_errors=["local_fts_not_ready"],
        )
    latest_provenance = collect_git_provenance()
    if (
        latest_provenance.status != "ok"
        or latest_provenance.source_state_sha256
        != binding.evaluation_source_state_sha256
    ):
        return await persist_blocked(
            scope.selection.cases,
            scope.selection.skipped_cases,
            current_provenance=latest_provenance,
        )
    client = None
    try:
        client = create_structural_qdrant_client(settings)
        retriever = build_structural_retriever(
            settings,
            client=client,
            fts_index=fts,
            reranker=get_remote_reranker(),
        )
    except Exception as error:
        initialization_errors = [
            f"remote_initialization:{type(error).__name__}"
        ]
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception as close_error:
                initialization_errors.append(
                    f"remote_cleanup:{type(close_error).__name__}"
                )
        try:
            await close_clients()
        except Exception as close_error:
            initialization_errors.append(
                f"remote_cleanup:{type(close_error).__name__}"
            )
        return await persist_blocked(
            scope.selection.cases,
            scope.selection.skipped_cases,
            technical_preflight_errors=initialization_errors,
            current_provenance=latest_provenance,
        )
    try:
        run = await run_structural_pilot_evaluation(
            scope.selection.cases,
            retriever,
            arguments.output_root,
            run_id=arguments.run_id,
            binding=binding,
            p2_source_document_recall_at_24=(
                baseline.source_document_recall_at_24
            ),
            skipped_cases=scope.selection.skipped_cases,
            provenance=latest_provenance,
            command=command,
        )
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
        await close_clients()
    print(run.model_dump_json())
    return {
        "PASS_PILOT": 0,
        "FAIL_QUALITY": 4,
        "BLOCKED_TECHNICAL": 2,
        "BLOCKED_SCOPE": 5,
    }[run.acceptance]


def run(arguments: argparse.Namespace) -> int:
    if arguments.command_name != "benchmark":
        raise StructuralEvaluationError("unsupported command")
    return asyncio.run(_run_benchmark(arguments))


def main() -> int:
    try:
        return run(build_parser().parse_args())
    except (StructuralEvaluationError, StructuralPilotError, OSError) as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
