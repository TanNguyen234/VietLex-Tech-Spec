"""Benchmark the verified isolated Pinecone structural P3 namespace."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.evaluation.case_selection import build_cases, select_evaluation_cases
from app.evaluation.gold_sidecar import load_gold_sidecar
from app.evaluation.provenance import collect_git_provenance
from app.evaluation.structural_pilot_eval import (
    StructuralEvaluationBinding,
    StructuralEvaluationError,
    load_json_object,
    run_structural_pilot_evaluation,
    validate_p2_baseline,
)
from app.ingestion.content_store import ContentStore
from app.ingestion.legal_fts import LegalFtsIndex
from app.ingestion.pinecone_store import create_control_client
from app.ingestion.structural_pinecone import (
    PineconeStructuralContract,
    validate_pinecone_structural_index,
)
from app.services.clients import close_clients, get_remote_reranker
from app.services.pinecone_structural_retrieval import PineconeStructuralRetriever
from run_pinecone_structural_pilot import PineconePilotPlan


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StructuralEvaluationError(message)


def _load_exact_object(path: Path, expected_sha256: str) -> dict[str, object]:
    _require(_sha256(path) == expected_sha256, f"{path.name} SHA-256 mismatch")
    value = load_json_object(path)
    return value


def _load_plan(path: Path, expected_sha256: str) -> PineconePilotPlan:
    _require(_sha256(path) == expected_sha256, "plan SHA-256 mismatch")
    try:
        return PineconePilotPlan.model_validate_json(path.read_text("utf-8"))
    except ValueError as error:
        raise StructuralEvaluationError("plan schema validation failed") from error


def _selection(dataset: Path, sidecar_path: Path):
    dataset_bytes = dataset.read_bytes()
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
    selected = select_evaluation_cases(
        build_cases(raw, sidecar.labels_by_case_id),
        "all-required-verified",
    )
    return dataset_bytes, sidecar, selected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("app/data/namsyntax_legal_qa_420_curated_v1.json"),
    )
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--upload-report", type=Path, required=True)
    parser.add_argument("--upload-report-sha256", required=True)
    parser.add_argument("--verify-report", type=Path, required=True)
    parser.add_argument("--verify-report-sha256", required=True)
    parser.add_argument(
        "--p2-baseline",
        type=Path,
        default=Path("docs/evaluation/comparisons/p2-aa3208c/comparison.json"),
    )
    parser.add_argument("--p2-baseline-sha256", required=True)
    parser.add_argument("--output-root", type=Path, default=Path("docs/evaluation/runs"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--allow-remote-benchmark", action="store_true", required=True)
    return parser


async def _run(arguments: argparse.Namespace) -> int:
    _require(arguments.allow_remote_benchmark is True, "authorization is required")
    plan = _load_plan(arguments.plan, arguments.plan_sha256)
    upload = _load_exact_object(
        arguments.upload_report,
        arguments.upload_report_sha256,
    )
    verify = _load_exact_object(
        arguments.verify_report,
        arguments.verify_report_sha256,
    )
    _require(
        upload.get("plan_file_sha256") == arguments.plan_sha256
        and upload.get("upload", {}).get("status") == "PASS_UPLOAD"
        and upload.get("upload", {}).get("checkpoint_record_count")
        == plan.manifest.record_count,
        "upload report binding mismatch",
    )
    _require(
        verify.get("plan_file_sha256") == arguments.plan_sha256
        and verify.get("upload_report_file_sha256")
        == arguments.upload_report_sha256
        and verify.get("verification", {}).get("status") == "PASS_VERIFY"
        and verify.get("verification", {}).get("remote_record_count")
        == plan.manifest.record_count,
        "verification report binding mismatch",
    )
    dataset_bytes, sidecar, selected = _selection(
        arguments.dataset,
        arguments.sidecar,
    )
    provenance = collect_git_provenance()
    _require(
        provenance.status == "ok" and provenance.source_state_sha256 is not None,
        "evaluation source provenance is unavailable",
    )
    contract = PineconeStructuralContract()
    _require(contract == plan.contract, "runtime Pinecone contract mismatch")
    binding = StructuralEvaluationBinding(
        retrieval_backend="pinecone-integrated",
        dataset_revision=plan.manifest.dataset_revision,
        dataset_sha256=hashlib.sha256(dataset_bytes).hexdigest(),
        sidecar_sha256=sidecar.metadata.sidecar_sha256,
        gold_policy="all-required-verified",
        selected_case_ids_sha256=selected.selected_case_ids_sha256,
        source_state_sha256=plan.source_state_sha256,
        evaluation_source_state_sha256=provenance.source_state_sha256,
        collection_name=f"{contract.index_name}/{contract.namespace}",
        plan_sha256=arguments.plan_sha256,
        upload_report_sha256=arguments.upload_report_sha256,
        verify_receipt_sha256=arguments.verify_report_sha256,
        p2_baseline_sha256=arguments.p2_baseline_sha256,
        dense_vector_name="integrated_dense",
        sparse_vector_name=None,
        dense_model=contract.model,
        dense_model_options={
            "dimension": contract.dimension,
            "input_type": "query",
            "truncate": "END",
        },
        sparse_model=None,
        dense_size=contract.dimension,
        query_instruction_version="pinecone-integrated-query-v1",
        query_instruction=None,
        dense_top_k=contract.dense_top_k,
        bm25_top_k=None,
        fused_limit=contract.fused_limit,
        rrf_k=contract.rrf_k,
        per_document_limit=contract.per_document_limit,
        reranker_mode="pinecone-only",
    )
    _require(
        _sha256(arguments.p2_baseline) == arguments.p2_baseline_sha256,
        "P2 baseline SHA-256 mismatch",
    )
    baseline = validate_p2_baseline(
        load_json_object(arguments.p2_baseline),
        binding,
    )
    _require(not baseline.scope_errors, "P2 baseline scope mismatch")
    settings = get_settings()
    store = ContentStore(settings.CONTENT_STORE_PATH)
    fts = LegalFtsIndex(
        store=store,
        path=settings.LEGAL_FTS_PATH,
        dataset_revision=settings.DATASET_REVISION,
    )
    _require(fts.is_ready(), "local FTS is not ready")
    client = create_control_client(settings)
    try:
        validate_pinecone_structural_index(
            client.describe_index(contract.index_name),
            contract,
        )
        retriever = PineconeStructuralRetriever(
            settings=settings,
            contract=contract,
            index=client.index(contract.index_name),
            fts_index=fts,
            reranker=get_remote_reranker(),
        )
        run = await run_structural_pilot_evaluation(
            selected.selected_cases,
            retriever,
            arguments.output_root,
            run_id=arguments.run_id,
            binding=binding,
            p2_source_document_recall_at_24=(
                baseline.source_document_recall_at_24
            ),
            skipped_cases={},
            provenance=provenance,
            command="python run_pinecone_structural_eval.py "
            + " ".join(sys.argv[1:]),
        )
        print(run.model_dump_json())
        return 0 if run.acceptance == "PASS_PILOT" else 3
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
        await close_clients()


def main() -> int:
    return asyncio.run(_run(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
