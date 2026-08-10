"""Provider-free audit and capacity-plan entrypoint for structural indexing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.evaluation.provenance import collect_git_provenance
from app.ingestion.content_store import ContentStore
from app.ingestion.structural_pilot import (
    CapacityEnvelope,
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
    return parser


def run(arguments: argparse.Namespace) -> int:
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
