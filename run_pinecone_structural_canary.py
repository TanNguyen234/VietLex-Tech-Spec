"""Run the independent 64-document Pinecone structural P3 canary."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.config import get_settings
from app.evaluation.artifact_io import write_immutable_json
from app.evaluation.pinecone_structural_canary import evaluate_pinecone_canaries
from app.evaluation.provenance import collect_git_provenance
from app.evaluation.structural_model_probe import load_verified_probe_scope
from app.evaluation.structural_pilot_eval import StructuralEvaluationError, load_json_object
from app.ingestion.content_store import ContentStore
from app.ingestion.pinecone_store import create_control_client
from app.ingestion.structural_index import (
    StructuralManifestBuilder,
    iter_structural_records,
    select_structural_document_ids,
)
from app.ingestion.structural_pinecone import validate_pinecone_structural_index
from run_pinecone_structural_pilot import PineconePilotPlan


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StructuralEvaluationError(message)


def _object(path: Path, expected: str) -> dict[str, object]:
    _require(_sha256(path) == expected, f"{path.name} SHA-256 mismatch")
    return load_json_object(path)


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
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-remote-read", action="store_true", required=True)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    _require(arguments.allow_remote_read is True, "remote-read authorization is required")
    _require(not arguments.output.exists(), "canary output already exists")
    _require(_sha256(arguments.plan) == arguments.plan_sha256, "plan SHA-256 mismatch")
    plan = PineconePilotPlan.model_validate_json(arguments.plan.read_text("utf-8"))
    upload = _object(arguments.upload_report, arguments.upload_report_sha256)
    verify = _object(arguments.verify_report, arguments.verify_report_sha256)
    _require(
        upload.get("plan_file_sha256") == arguments.plan_sha256
        and upload.get("upload", {}).get("checkpoint_record_count")
        == plan.manifest.record_count,
        "upload binding mismatch",
    )
    _require(
        verify.get("plan_file_sha256") == arguments.plan_sha256
        and verify.get("upload_report_file_sha256")
        == arguments.upload_report_sha256
        and verify.get("verification", {}).get("status") == "PASS_VERIFY",
        "verification binding mismatch",
    )
    settings = get_settings()
    store = ContentStore(settings.CONTENT_STORE_PATH)
    document_ids = select_structural_document_ids(store)
    builder = StructuralManifestBuilder(
        selected_document_ids=document_ids,
        repository=settings.DATASET_REPOSITORY,
        revision=settings.DATASET_REVISION,
        max_tokens=420,
        overlap_tokens=48,
    )

    def audited_records():
        for record in iter_structural_records(
            store,
            document_ids,
            repository=settings.DATASET_REPOSITORY,
            revision=settings.DATASET_REVISION,
            max_tokens=420,
            overlap_tokens=48,
        ):
            builder.add(record)
            yield record

    scope = load_verified_probe_scope(
        arguments.dataset,
        arguments.sidecar,
        audited_records(),
    )
    _require(builder.build() == plan.manifest, "local structural corpus drift")
    _require(
        len(scope.selection.canary_queries) == 64
        and not scope.selection.canary_skips,
        "independent canary scope is incomplete",
    )
    provenance = collect_git_provenance()
    _require(
        provenance.status == "ok" and provenance.source_state_sha256 is not None,
        "source provenance is unavailable",
    )
    client = create_control_client(settings)
    try:
        validate_pinecone_structural_index(
            client.describe_index(plan.contract.index_name),
            plan.contract,
        )
        report = evaluate_pinecone_canaries(
            client.index(plan.contract.index_name),
            scope.selection.canary_queries,
            contract=plan.contract,
            dataset_sha256=scope.dataset_sha256,
            sidecar_sha256=scope.sidecar_sha256,
            plan_sha256=arguments.plan_sha256,
            upload_report_sha256=arguments.upload_report_sha256,
            verify_report_sha256=arguments.verify_report_sha256,
            source_state_sha256=provenance.source_state_sha256,
        )
        write_immutable_json(arguments.output, report.model_dump(mode="json"))
        print(json.dumps({"output": str(arguments.output), "sha256": _sha256(arguments.output), "status": report.status}))
        return 0 if report.status == "PASS_CANARY" else 3
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    raise SystemExit(main())
