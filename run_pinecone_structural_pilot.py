"""Audit and resumably upload the isolated Pinecone structural P3 pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.evaluation.artifact_io import write_immutable_json
from app.evaluation.provenance import collect_git_provenance
from app.ingestion.content_store import ContentStore
from app.ingestion.pinecone_store import create_control_client
from app.ingestion.structural_index import (
    StructuralCorpusManifest,
    StructuralManifestBuilder,
    iter_structural_records,
    select_structural_document_ids,
)
from app.ingestion.structural_pinecone import (
    PineconeCheckpointBinding,
    PineconeStructuralCheckpoint,
    PineconeStructuralContract,
    upload_pinecone_structural_records,
    validate_pinecone_structural_index,
    verify_pinecone_structural_namespace,
)


class PineconePilotError(RuntimeError):
    pass


class PineconePilotPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    git_sha: str = Field(min_length=40, max_length=40)
    git_dirty: bool
    git_diff_sha256: str | None
    source_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract: PineconeStructuralContract
    manifest: StructuralCorpusManifest


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_plan(path: Path, expected_sha256: str) -> PineconePilotPlan:
    if _sha256(path) != expected_sha256:
        raise PineconePilotError("plan SHA-256 mismatch")
    try:
        return PineconePilotPlan.model_validate_json(Path(path).read_text("utf-8"))
    except ValueError as error:
        raise PineconePilotError("plan schema validation failed") from error


def _records(store, settings, document_ids):
    return iter_structural_records(
        store,
        document_ids,
        repository=settings.DATASET_REPOSITORY,
        revision=settings.DATASET_REVISION,
        max_tokens=420,
        overlap_tokens=48,
    )


def _manifest(store, settings, document_ids) -> StructuralCorpusManifest:
    builder = StructuralManifestBuilder(
        selected_document_ids=document_ids,
        repository=settings.DATASET_REPOSITORY,
        revision=settings.DATASET_REVISION,
        max_tokens=420,
        overlap_tokens=48,
    )
    for record in _records(store, settings, document_ids):
        builder.add(record)
    return builder.build()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit", help="create a provider-free bound plan")
    audit.add_argument("--output", type=Path, required=True)
    upload = commands.add_parser("upload", help="resume the isolated namespace upload")
    upload.add_argument("--plan", type=Path, required=True)
    upload.add_argument("--plan-sha256", required=True)
    upload.add_argument("--checkpoint", type=Path, required=True)
    upload.add_argument("--output", type=Path, required=True)
    upload.add_argument("--allow-remote-write", action="store_true", required=True)
    verify = commands.add_parser("verify", help="verify count and sampled identities")
    verify.add_argument("--plan", type=Path, required=True)
    verify.add_argument("--plan-sha256", required=True)
    verify.add_argument("--upload-report", type=Path, required=True)
    verify.add_argument("--upload-report-sha256", required=True)
    verify.add_argument("--output", type=Path, required=True)
    verify.add_argument("--allow-remote-read", action="store_true", required=True)
    return parser


def _audit(arguments: argparse.Namespace) -> int:
    if arguments.output.exists():
        raise PineconePilotError("plan output already exists")
    settings = get_settings()
    store = ContentStore(settings.CONTENT_STORE_PATH)
    document_ids = select_structural_document_ids(store)
    provenance = collect_git_provenance()
    if provenance.status != "ok" or provenance.source_state_sha256 is None:
        raise PineconePilotError("Git source provenance is unavailable")
    plan = PineconePilotPlan(
        git_sha=provenance.git_sha,
        git_dirty=provenance.git_dirty,
        git_diff_sha256=provenance.git_diff_sha256,
        source_state_sha256=provenance.source_state_sha256,
        contract=PineconeStructuralContract(),
        manifest=_manifest(store, settings, document_ids),
    )
    write_immutable_json(arguments.output, plan.model_dump(mode="json"))
    print(json.dumps({"plan": str(arguments.output), "sha256": _sha256(arguments.output), "records": plan.manifest.record_count}))
    return 0


def _upload(arguments: argparse.Namespace) -> int:
    if arguments.allow_remote_write is not True:
        raise PineconePilotError("remote-write authorization is required")
    if arguments.output.exists():
        raise PineconePilotError("upload output already exists")
    plan = _load_plan(arguments.plan, arguments.plan_sha256)
    settings = get_settings()
    if plan.manifest.dataset_revision != settings.DATASET_REVISION:
        raise PineconePilotError("dataset revision mismatch")
    store = ContentStore(settings.CONTENT_STORE_PATH)
    document_ids = select_structural_document_ids(store)
    current_manifest = _manifest(store, settings, document_ids)
    if current_manifest != plan.manifest:
        raise PineconePilotError("local structural manifest mismatch")
    client = create_control_client(settings)
    try:
        description = client.describe_index(plan.contract.index_name)
        validate_pinecone_structural_index(description, plan.contract)
        index = client.index(plan.contract.index_name)
        checkpoint = PineconeStructuralCheckpoint(
            arguments.checkpoint,
            PineconeCheckpointBinding(
                manifest_sha256=hashlib.sha256(
                    json.dumps(
                        plan.manifest.model_dump(mode="json"),
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
                dataset_revision=plan.manifest.dataset_revision,
                ordered_record_ids_sha256=plan.manifest.ordered_record_ids_sha256,
                manifest_record_count=plan.manifest.record_count,
            ),
        )
        report = upload_pinecone_structural_records(
            index,
            _records(store, settings, document_ids),
            checkpoint=checkpoint,
            contract=plan.contract,
        )
        if report.checkpoint_record_count != plan.manifest.record_count:
            raise PineconePilotError("upload checkpoint count mismatch")
        payload = {
            "plan_file_sha256": arguments.plan_sha256,
            "source_state_sha256": plan.source_state_sha256,
            "manifest": plan.manifest.model_dump(mode="json"),
            "upload": report.model_dump(mode="json"),
        }
        write_immutable_json(arguments.output, payload)
        print(json.dumps({"output": str(arguments.output), "sha256": _sha256(arguments.output), "records": report.checkpoint_record_count}))
        return 0
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def _verify(arguments: argparse.Namespace) -> int:
    if arguments.allow_remote_read is not True:
        raise PineconePilotError("remote-read authorization is required")
    if arguments.output.exists():
        raise PineconePilotError("verification output already exists")
    plan = _load_plan(arguments.plan, arguments.plan_sha256)
    if _sha256(arguments.upload_report) != arguments.upload_report_sha256:
        raise PineconePilotError("upload report SHA-256 mismatch")
    upload = json.loads(arguments.upload_report.read_text("utf-8"))
    if (
        upload.get("plan_file_sha256") != arguments.plan_sha256
        or upload.get("upload", {}).get("status") != "PASS_UPLOAD"
        or upload.get("upload", {}).get("checkpoint_record_count")
        != plan.manifest.record_count
    ):
        raise PineconePilotError("upload report binding mismatch")
    settings = get_settings()
    store = ContentStore(settings.CONTENT_STORE_PATH)
    document_ids = select_structural_document_ids(store)
    positions = {
        round(index * (plan.manifest.record_count - 1) / 15)
        for index in range(16)
    }
    samples = [
        record
        for index, record in enumerate(_records(store, settings, document_ids))
        if index in positions
    ]
    if len(samples) != len(positions):
        raise PineconePilotError("verification sample selection mismatch")
    client = create_control_client(settings)
    try:
        validate_pinecone_structural_index(
            client.describe_index(plan.contract.index_name),
            plan.contract,
        )
        index = client.index(plan.contract.index_name)
        report = verify_pinecone_structural_namespace(
            index,
            samples,
            expected_count=plan.manifest.record_count,
            contract=plan.contract,
        )
        payload = {
            "plan_file_sha256": arguments.plan_sha256,
            "upload_report_file_sha256": arguments.upload_report_sha256,
            "source_state_sha256": plan.source_state_sha256,
            "verification": report.model_dump(mode="json"),
        }
        write_immutable_json(arguments.output, payload)
        print(json.dumps({"output": str(arguments.output), "sha256": _sha256(arguments.output), "records": report.remote_record_count}))
        return 0
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def main() -> int:
    arguments = build_parser().parse_args()
    if arguments.command == "audit":
        return _audit(arguments)
    if arguments.command == "upload":
        return _upload(arguments)
    return _verify(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
