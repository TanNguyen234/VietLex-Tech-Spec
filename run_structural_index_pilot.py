"""Provider-free audit and capacity-plan entrypoint for structural indexing."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.evaluation.provenance import collect_git_provenance
from app.ingestion.content_store import ContentStore
from app.ingestion.structural_pilot import (
    CapacityEnvelope,
    CollectionCreationReceipt,
    RemoteWriteAuthorization,
    StructuralPilotError,
    build_structural_pilot_plan,
    create_structural_collection,
    load_bound_plan,
    validate_remote_write_authorization,
)
from app.ingestion.structural_qdrant import (
    StructuralQdrantContract,
    create_structural_qdrant_client,
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
    create.add_argument("--plan", type=Path, required=True)
    create.add_argument("--plan-sha256", required=True)
    create.add_argument("--source-state-sha256", required=True)
    create.add_argument(
        "--collection",
        choices=["vietlex-legal-rag-v2-pilot"],
        required=True,
    )
    create.add_argument(
        "--allow-remote-write",
        action="store_true",
        required=True,
    )
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
        default=Path("app/data/namsyntax_legal_qa_420.json"),
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
    return parser


def run(arguments: argparse.Namespace) -> int:
    if arguments.command_name == "probe-model":
        from pinecone import Pinecone

        from app.config import install_system_trust_store
        from app.evaluation.structural_model_probe import (
            PineconeReferenceEmbedder,
            StaticReferenceEmbedder,
            StructuralModelProbeInput,
            load_matching_reference_probe,
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
        if arguments.reference_probe is not None:
            reference = StaticReferenceEmbedder(
                load_matching_reference_probe(
                    arguments.reference_probe,
                    probe,
                )
            )
        else:
            if not settings.pinecone_api_key:
                raise StructuralPilotError(
                    "Pinecone inference credentials or --reference-probe are required"
                )
            install_system_trust_store()
            pinecone = Pinecone(
                api_key=settings.pinecone_api_key,
                timeout=settings.PINECONE_RERANK_TIMEOUT_SECONDS,
            )
            reference = PineconeReferenceEmbedder(pinecone.inference)

        qdrant = create_structural_qdrant_client(settings)
        transport = StructuralQdrantTransport(qdrant, plan.contract)
        report = run_structural_model_probe(transport, reference, probe)
        print(report.model_dump_json())
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
        print(receipt.model_dump_json())
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
        json.dumps(
            plan.manifest.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        )
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
