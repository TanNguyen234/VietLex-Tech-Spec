"""Provider-free audit and capacity-plan entrypoint for structural indexing."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from app.config import get_settings
from app.evaluation.provenance import collect_git_provenance
from app.ingestion.content_store import ContentStore
from app.ingestion.structural_pilot import (
    CapacityEnvelope,
    CollectionCreationReceipt,
    CollectionFinalizeReceipt,
    RemoteWriteAuthorization,
    StructuralPilotError,
    audit_structural_corpus,
    build_structural_pilot_plan,
    create_structural_collection,
    finalize_structural_collection,
    load_bound_plan,
    validate_remote_write_authorization,
    verify_structural_collection,
)
from app.ingestion.structural_qdrant import (
    StructuralQdrantContract,
    StructuralQdrantTransport,
    create_structural_qdrant_client,
)


_ArtifactModel = TypeVar("_ArtifactModel", bound=BaseModel)


def _console_json(value: object) -> str:
    """Render CLI JSON safely on legacy Windows consoles."""
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _print_console_model(model: BaseModel) -> None:
    print(_console_json(model.model_dump(mode="json")))


def _load_exact_artifact(
    path: Path,
    expected_sha256: str,
    model: type[_ArtifactModel],
    *,
    label: str,
) -> _ArtifactModel:
    try:
        payload = Path(path).read_bytes()
    except OSError as error:
        raise StructuralPilotError(
            f"unable to read {label}: {type(error).__name__}"
        ) from error
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if actual_sha256 != expected_sha256:
        raise StructuralPilotError(f"{label} SHA-256 mismatch")
    try:
        return model.model_validate_json(payload)
    except ValueError as error:
        raise StructuralPilotError(
            f"{label} schema validation failed"
        ) from error


def _artifact_directory(plan_path: Path) -> Path:
    path = Path(plan_path)
    return path if path.is_dir() else path.parent


def _authorization_from_arguments(
    arguments: argparse.Namespace,
) -> RemoteWriteAuthorization:
    return RemoteWriteAuthorization(
        allow_remote_write=arguments.allow_remote_write,
        collection_name=arguments.collection,
        plan_sha256=arguments.plan_sha256,
        source_state_sha256=arguments.source_state_sha256,
    )


def _validated_remote_context(arguments: argparse.Namespace):
    plan = load_bound_plan(arguments.plan)
    authorization = _authorization_from_arguments(arguments)
    provenance = collect_git_provenance()
    validate_remote_write_authorization(plan, authorization, provenance)
    settings = get_settings()
    configured_contract = StructuralQdrantContract.from_settings(settings)
    if configured_contract != plan.contract:
        raise StructuralPilotError(
            "configured structural contract does not match the bound plan"
        )
    return plan, authorization, provenance, settings


def _load_optional_reference_embedder(
    arguments: argparse.Namespace,
    probe: object,
) -> object | None:
    """Load only an explicitly supplied immutable reference artifact."""
    if arguments.reference_probe is None:
        return None
    from app.evaluation.structural_model_probe import (
        StaticReferenceEmbedder,
        load_matching_reference_probe,
    )

    return StaticReferenceEmbedder(
        load_matching_reference_probe(arguments.reference_probe, probe)
    )


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative integer")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return parsed


def _add_remote_binding_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--source-state-sha256", required=True)
    parser.add_argument(
        "--collection",
        choices=["vietlex-legal-rag-v2-pilot"],
        required=True,
    )
    parser.add_argument(
        "--allow-remote-write",
        action="store_true",
        required=True,
    )


def _add_create_probe_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--create-receipt", type=Path, required=True)
    parser.add_argument("--create-receipt-sha256", required=True)
    parser.add_argument("--probe-report", type=Path, required=True)
    parser.add_argument("--probe-report-sha256", required=True)


def _add_upload_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--upload-report", type=Path, required=True)
    parser.add_argument("--upload-report-sha256", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit and plan the opt-in Qdrant structural pilot.",
    )
    subparsers = parser.add_subparsers(dest="command_name", required=True)
    audit = subparsers.add_parser(
        "audit",
        help="stream and hash the local corpus without provider calls",
    )
    plan = subparsers.add_parser(
        "plan",
        help="bind corpus evidence to explicit cluster capacity",
    )
    for command in (audit, plan):
        command.add_argument(
            "--output-root",
            type=Path,
            default=Path("docs/evaluation/index-pilots"),
        )
        command.add_argument("--run-id")
    plan.add_argument("--disk-bytes", type=_positive_int)
    plan.add_argument("--ram-bytes", type=_positive_int)
    plan.add_argument("--vcpu", type=_positive_float)
    plan.add_argument("--existing-disk-bytes", type=_nonnegative_int)
    plan.add_argument("--shards", type=_positive_int)
    create = subparsers.add_parser(
        "create",
        help="create the authorized empty pilot collection",
    )
    _add_remote_binding_arguments(create)
    probe = subparsers.add_parser(
        "probe-model",
        help="probe the real verified-gold structural subset",
    )
    probe.add_argument("--plan", type=Path, required=True)
    probe.add_argument("--create-receipt", type=Path, required=True)
    probe.add_argument("--create-receipt-sha256", required=True)
    probe.add_argument(
        "--dataset",
        type=Path,
        default=Path(
            "app/data/namsyntax_legal_qa_420_curated_v1.json"
        ),
    )
    probe.add_argument("--sidecar", type=Path, required=True)
    probe.add_argument("--reference-probe", type=Path)
    probe.add_argument("--output", type=Path)
    probe.add_argument("--plan-sha256", required=True)
    probe.add_argument("--source-state-sha256", required=True)
    probe.add_argument(
        "--collection",
        choices=["vietlex-legal-rag-v2-pilot"],
        required=True,
    )
    probe.add_argument(
        "--allow-remote-write",
        action="store_true",
        required=True,
    )
    upload = subparsers.add_parser(
        "upload",
        help="resume the exact authorized structural upload",
    )
    _add_remote_binding_arguments(upload)
    _add_create_probe_arguments(upload)
    upload.add_argument("--checkpoint", type=Path, required=True)
    upload.add_argument("--output", type=Path)
    finalize = subparsers.add_parser(
        "finalize",
        help="activate HNSW after exact upload completion",
    )
    _add_remote_binding_arguments(finalize)
    _add_create_probe_arguments(finalize)
    _add_upload_arguments(finalize)
    finalize.add_argument("--output", type=Path)
    finalize.add_argument("--max-polls", type=_positive_int, default=60)
    finalize.add_argument(
        "--poll-interval-seconds",
        type=_nonnegative_float,
        default=5.0,
    )
    verify = subparsers.add_parser(
        "verify",
        help="verify exact schema, count, hashes, and deterministic samples",
    )
    _add_remote_binding_arguments(verify)
    _add_create_probe_arguments(verify)
    _add_upload_arguments(verify)
    verify.add_argument("--finalize-receipt", type=Path, required=True)
    verify.add_argument("--finalize-receipt-sha256", required=True)
    verify.add_argument("--output", type=Path)
    return parser


def _validate_creation_probe_chain(
    plan,
    creation_receipt: CollectionCreationReceipt,
    creation_sha256: str,
    probe_report,
) -> None:
    if (
        creation_receipt.status not in {"CREATED", "ADOPTED_EMPTY"}
        or creation_receipt.collection_name != plan.contract.collection_name
        or creation_receipt.source_state_sha256 != plan.source_state_sha256
        or creation_receipt.plan_sha256 != plan.plan_sha256
    ):
        raise StructuralPilotError("creation receipt binding mismatch")
    expected = {
        "acceptance": "PASS_MODEL_PROBE",
        "collection_name": plan.contract.collection_name,
        "source_state_sha256": plan.source_state_sha256,
        "plan_sha256": plan.plan_sha256,
        "creation_receipt_sha256": creation_sha256,
        "dataset_revision": plan.manifest.dataset_revision,
        "candidate_dense_model": plan.contract.dense_model,
        "candidate_sparse_model": plan.contract.sparse_model,
    }
    if any(
        getattr(probe_report, field_name, None) != value
        for field_name, value in expected.items()
    ):
        raise StructuralPilotError("model probe binding mismatch")


def _iter_plan_records(store, settings, plan):
    from app.ingestion.structural_index import (
        iter_structural_records,
        select_structural_document_ids,
    )

    document_ids = select_structural_document_ids(store)
    yield from iter_structural_records(
        store,
        document_ids,
        repository=settings.DATASET_REPOSITORY,
        revision=settings.DATASET_REVISION,
        max_tokens=plan.contract.chunk_max_tokens,
        overlap_tokens=plan.contract.chunk_overlap_tokens,
    )


def _run_upload(arguments: argparse.Namespace) -> int:
    from app.evaluation.structural_model_probe import StructuralModelProbeReport
    from app.ingestion.structural_checkpoint import (
        CheckpointBinding,
        StructuralCheckpointStore,
    )
    from app.ingestion.structural_qdrant import point_from_record
    from app.ingestion.structural_upload import (
        AdaptiveUploadController,
        StructuralGrpcUploadTransport,
        select_upload_transport,
        upload_structural_records,
    )

    plan, authorization, _provenance, settings = _validated_remote_context(
        arguments
    )
    creation = _load_exact_artifact(
        arguments.create_receipt,
        arguments.create_receipt_sha256,
        CollectionCreationReceipt,
        label="creation receipt",
    )
    probe = _load_exact_artifact(
        arguments.probe_report,
        arguments.probe_report_sha256,
        StructuralModelProbeReport,
        label="model probe",
    )
    _validate_creation_probe_chain(
        plan,
        creation,
        arguments.create_receipt_sha256,
        probe,
    )
    output = arguments.output or (
        _artifact_directory(arguments.plan) / "upload-report.json"
    )
    if output.exists():
        raise StructuralPilotError("upload report already exists")

    store = ContentStore(settings.CONTENT_STORE_PATH)
    audit = audit_structural_corpus(store, settings=settings)
    if audit.manifest != plan.manifest:
        raise StructuralPilotError(
            "local structural corpus no longer matches the bound plan"
        )
    checkpoint = StructuralCheckpointStore(
        arguments.checkpoint,
        CheckpointBinding(
            collection_name=plan.contract.collection_name,
            source_state_sha256=plan.source_state_sha256,
            plan_sha256=plan.plan_sha256,
            creation_receipt_sha256=arguments.create_receipt_sha256,
            probe_report_sha256=arguments.probe_report_sha256,
            dataset_revision=plan.manifest.dataset_revision,
            ordered_record_ids_sha256=(
                plan.manifest.ordered_record_ids_sha256
            ),
            manifest_record_count=plan.manifest.record_count,
            dense_model=plan.contract.dense_model,
            sparse_model=plan.contract.sparse_model,
            document_text_version=plan.contract.document_text_version,
        ),
    )
    checkpoint.import_probe_receipt(
        probe,
        report_sha256=arguments.probe_report_sha256,
    )
    probe_record_id = probe.record_ids[0]
    probe_record = next(
        (
            record
            for record in _iter_plan_records(store, settings, plan)
            if record.record_id == probe_record_id
        ),
        None,
    )
    if (
        probe_record is None
        or probe_record.chunk_sha256
        != probe.probe_record_hashes[probe_record_id]
    ):
        raise StructuralPilotError("model probe record binding mismatch")

    validate_remote_write_authorization(
        plan,
        authorization,
        collect_git_provenance(),
    )
    client = create_structural_qdrant_client(settings)
    rest_transport = StructuralQdrantTransport(client, plan.contract)
    probe_points = [point_from_record(probe_record, plan.contract)]
    if plan.contract.upload_prefer_grpc:
        grpc_transport = StructuralGrpcUploadTransport(client, plan.contract)
        transport, preflight_receipt, fallback_reason = select_upload_transport(
            grpc_transport,
            rest_transport,
            probe_points,
        )
        transport_name = "rest" if fallback_reason else "grpc"
    else:
        transport = rest_transport
        preflight_receipt = rest_transport.upsert_with_usage(probe_points)
        fallback_reason = None
        transport_name = "rest"
    controller = AdaptiveUploadController.from_contract(
        plan.contract,
        shard_count=plan.capacity.shard_count,
    )
    report = upload_structural_records(
        transport,
        _iter_plan_records(store, settings, plan),
        checkpoint,
        controller,
        manifest_record_count=plan.manifest.record_count,
        transport_name=transport_name,
        transport_fallback_reason=fallback_reason,
        preflight_usage=dict(preflight_receipt.model_tokens),
        report_path=output,
    )
    _print_console_model(report)
    return 0 if report.completed else 3


def _run_finalize(arguments: argparse.Namespace) -> int:
    from app.evaluation.structural_model_probe import StructuralModelProbeReport
    from app.ingestion.structural_upload import StructuralUploadReport

    plan, authorization, provenance, settings = _validated_remote_context(
        arguments
    )
    creation = _load_exact_artifact(
        arguments.create_receipt,
        arguments.create_receipt_sha256,
        CollectionCreationReceipt,
        label="creation receipt",
    )
    probe = _load_exact_artifact(
        arguments.probe_report,
        arguments.probe_report_sha256,
        StructuralModelProbeReport,
        label="model probe",
    )
    upload = _load_exact_artifact(
        arguments.upload_report,
        arguments.upload_report_sha256,
        StructuralUploadReport,
        label="upload report",
    )
    output = arguments.output or (
        _artifact_directory(arguments.plan) / "finalize-receipt.json"
    )
    client = create_structural_qdrant_client(settings)
    receipt = finalize_structural_collection(
        client,
        plan,
        authorization,
        provenance,
        creation_receipt=creation,
        creation_receipt_sha256=arguments.create_receipt_sha256,
        probe_report=probe,
        probe_report_sha256=arguments.probe_report_sha256,
        upload_report=upload,
        upload_report_sha256=arguments.upload_report_sha256,
        receipt_path=output,
        max_polls=arguments.max_polls,
        poll_interval_seconds=arguments.poll_interval_seconds,
    )
    _print_console_model(receipt)
    return 0 if receipt.status == "PASS_FINALIZE" else 2


def _run_verify(arguments: argparse.Namespace) -> int:
    from app.evaluation.structural_model_probe import StructuralModelProbeReport
    from app.ingestion.structural_upload import StructuralUploadReport

    plan, authorization, provenance, settings = _validated_remote_context(
        arguments
    )
    creation = _load_exact_artifact(
        arguments.create_receipt,
        arguments.create_receipt_sha256,
        CollectionCreationReceipt,
        label="creation receipt",
    )
    probe = _load_exact_artifact(
        arguments.probe_report,
        arguments.probe_report_sha256,
        StructuralModelProbeReport,
        label="model probe",
    )
    upload = _load_exact_artifact(
        arguments.upload_report,
        arguments.upload_report_sha256,
        StructuralUploadReport,
        label="upload report",
    )
    finalize = _load_exact_artifact(
        arguments.finalize_receipt,
        arguments.finalize_receipt_sha256,
        CollectionFinalizeReceipt,
        label="finalize receipt",
    )
    output = arguments.output or (
        _artifact_directory(arguments.plan) / "verify.json"
    )
    store = ContentStore(settings.CONTENT_STORE_PATH)
    client = create_structural_qdrant_client(settings)
    receipt = verify_structural_collection(
        client,
        plan,
        authorization,
        provenance,
        _iter_plan_records(store, settings, plan),
        creation_receipt=creation,
        creation_receipt_sha256=arguments.create_receipt_sha256,
        probe_report=probe,
        probe_report_sha256=arguments.probe_report_sha256,
        upload_report=upload,
        upload_report_sha256=arguments.upload_report_sha256,
        finalize_receipt=finalize,
        finalize_receipt_sha256=arguments.finalize_receipt_sha256,
        receipt_path=output,
    )
    _print_console_model(receipt)
    return 0 if receipt.status == "PASS_VERIFY" else 2


def run(arguments: argparse.Namespace) -> int:
    if arguments.command_name == "upload":
        return _run_upload(arguments)
    if arguments.command_name == "finalize":
        return _run_finalize(arguments)
    if arguments.command_name == "verify":
        return _run_verify(arguments)

    if arguments.command_name == "probe-model":
        from app.evaluation.structural_model_probe import (
            StructuralModelProbeInput,
            load_verified_probe_scope,
            run_structural_model_probe,
        )
        from app.ingestion.structural_index import (
            StructuralManifestBuilder,
            iter_structural_records,
            select_structural_document_ids,
        )
        from app.ingestion.structural_qdrant import StructuralQdrantTransport

        plan = load_bound_plan(arguments.plan)
        authorization = RemoteWriteAuthorization(
            allow_remote_write=arguments.allow_remote_write,
            collection_name=arguments.collection,
            plan_sha256=arguments.plan_sha256,
            source_state_sha256=arguments.source_state_sha256,
        )
        provenance = collect_git_provenance()
        validate_remote_write_authorization(plan, authorization, provenance)

        receipt_bytes = Path(arguments.create_receipt).read_bytes()
        receipt_sha256 = hashlib.sha256(receipt_bytes).hexdigest()
        if receipt_sha256 != arguments.create_receipt_sha256:
            raise StructuralPilotError("creation receipt SHA-256 mismatch")
        try:
            creation_receipt = CollectionCreationReceipt.model_validate_json(
                receipt_bytes
            )
        except ValueError as error:
            raise StructuralPilotError(
                "creation receipt schema validation failed"
            ) from error
        if (
            creation_receipt.plan_sha256 != plan.plan_sha256
            or creation_receipt.source_state_sha256
            != plan.source_state_sha256
            or creation_receipt.collection_name
            != plan.contract.collection_name
        ):
            raise StructuralPilotError("creation receipt binding mismatch")

        plan_path = Path(arguments.plan)
        artifact_dir = plan_path if plan_path.is_dir() else plan_path.parent
        output_path = arguments.output or artifact_dir / "model-probe.json"
        if output_path.exists():
            raise StructuralPilotError("model probe artifact already exists")

        settings = get_settings()
        configured_contract = StructuralQdrantContract.from_settings(settings)
        if configured_contract != plan.contract:
            raise StructuralPilotError(
                "configured structural contract does not match the bound plan"
            )
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
        if builder.build() != plan.manifest:
            raise StructuralPilotError(
                "local structural corpus no longer matches the bound plan"
            )
        probe = StructuralModelProbeInput(
            plan=plan,
            creation_receipt=creation_receipt,
            creation_receipt_sha256=receipt_sha256,
            selection=scope.selection,
            dataset_sha256=scope.dataset_sha256,
            sidecar_sha256=scope.sidecar_sha256,
            output_path=output_path,
        )
        reference = _load_optional_reference_embedder(arguments, probe)

        qdrant = create_structural_qdrant_client(settings)
        transport = StructuralQdrantTransport(qdrant, plan.contract)
        report = run_structural_model_probe(
            transport,
            probe,
            reference,
        )
        _print_console_model(report)
        return {
            "PASS_MODEL_PROBE": 0,
            "FAIL_QUALITY": 4,
            "BLOCKED_SCOPE": 5,
            "BLOCKED_TECHNICAL": 2,
        }[report.acceptance]

    if arguments.command_name == "create":
        plan = load_bound_plan(arguments.plan)
        authorization = RemoteWriteAuthorization(
            allow_remote_write=arguments.allow_remote_write,
            collection_name=arguments.collection,
            plan_sha256=arguments.plan_sha256,
            source_state_sha256=arguments.source_state_sha256,
        )
        provenance = collect_git_provenance()
        validate_remote_write_authorization(plan, authorization, provenance)
        settings = get_settings()
        configured_contract = StructuralQdrantContract.from_settings(settings)
        if configured_contract != plan.contract:
            raise StructuralPilotError(
                "configured structural contract does not match the bound plan"
            )
        client = create_structural_qdrant_client(settings)
        plan_path = Path(arguments.plan)
        artifact_dir = plan_path if plan_path.is_dir() else plan_path.parent
        receipt = create_structural_collection(
            client,
            plan,
            authorization,
            provenance,
            receipt_path=artifact_dir / "create-receipt.json",
        )
        _print_console_model(receipt)
        return 0

    settings = get_settings()
    store = ContentStore(settings.CONTENT_STORE_PATH)
    capacity = (
        CapacityEnvelope()
        if arguments.command_name == "audit"
        else CapacityEnvelope(
            disk_bytes=arguments.disk_bytes,
            ram_bytes=arguments.ram_bytes,
            vcpu=arguments.vcpu,
            existing_disk_bytes=arguments.existing_disk_bytes,
            shard_count=arguments.shards,
        )
    )
    plan = build_structural_pilot_plan(
        store=store,
        settings=settings,
        output_root=arguments.output_root,
        capacity=capacity,
        run_id=arguments.run_id,
        command="python run_structural_index_pilot.py " + " ".join(sys.argv[1:]),
    )
    print(
        _console_json(plan.manifest.model_dump(mode="json"))
    )
    if arguments.command_name == "plan" and plan.capacity.status != "PASS_CAPACITY":
        print(
            "BLOCKED_CAPACITY: "
            + ", ".join(plan.capacity.missing_capacity_inputs),
            file=sys.stderr,
        )
        return 3
    return 0


def main() -> int:
    try:
        return run(build_parser().parse_args())
    except (StructuralPilotError, OSError, ValueError) as error:
        print(f"STRUCTURAL_PILOT_ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
