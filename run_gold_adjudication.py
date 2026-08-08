"""Provider-free, immutable human gold-evidence adjudication workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


@dataclass(frozen=True)
class RuntimeDependencies:
    build_cases: Callable[..., Any]
    load_gold_sidecar: Callable[..., Any]
    ContentStore: type
    LegalFtsIndex: type
    discover_adjudication_candidates: Callable[..., Any]
    select_stratified_case_ids: Callable[..., Any]
    build_queue_payload: Callable[..., Any]
    build_decision_template: Callable[..., Any]
    build_promotion_preview: Callable[..., Any]
    build_promotion_summary: Callable[..., Any]
    validate_preview_approval: Callable[..., Any]
    canonical_sha256: Callable[..., str]
    artifact_sha256: Callable[..., str]
    write_immutable_json: Callable[..., Any]
    prepare_run_directory: Callable[..., Path]
    generate_unique_run_id: Callable[..., str]
    collect_git_provenance: Callable[..., Any]
    GitProvenance: type
    get_settings: Callable[..., Any]


def repository_root() -> Path:
    return Path(__file__).resolve().parent


def _runtime_dependencies() -> RuntimeDependencies:
    """Import evaluation and local-corpus code only after command validation."""
    from app.config import get_settings
    from app.evaluation.adjudication import (
        build_decision_template,
        build_promotion_preview,
        build_promotion_summary,
        canonical_sha256,
        artifact_sha256,
        select_stratified_case_ids,
        validate_preview_approval,
        build_queue_payload,
    )
    from app.evaluation.adjudication_candidates import discover_adjudication_candidates
    from app.evaluation.artifact_io import write_immutable_json
    from app.evaluation.case_selection import build_cases
    from app.evaluation.gold_sidecar import load_gold_sidecar
    from app.evaluation.provenance import GitProvenance, collect_git_provenance
    from app.evaluation.run_manifest import generate_unique_run_id, prepare_run_directory
    from app.ingestion.content_store import ContentStore
    from app.ingestion.legal_fts import LegalFtsIndex

    return RuntimeDependencies(
        build_cases=build_cases,
        load_gold_sidecar=load_gold_sidecar,
        ContentStore=ContentStore,
        LegalFtsIndex=LegalFtsIndex,
        discover_adjudication_candidates=discover_adjudication_candidates,
        select_stratified_case_ids=select_stratified_case_ids,
        build_queue_payload=build_queue_payload,
        build_decision_template=build_decision_template,
        build_promotion_preview=build_promotion_preview,
        build_promotion_summary=build_promotion_summary,
        validate_preview_approval=validate_preview_approval,
        canonical_sha256=canonical_sha256,
        artifact_sha256=artifact_sha256,
        write_immutable_json=write_immutable_json,
        prepare_run_directory=prepare_run_directory,
        generate_unique_run_id=generate_unique_run_id,
        collect_git_provenance=collect_git_provenance,
        GitProvenance=GitProvenance,
        get_settings=get_settings,
    )


def build_parser() -> argparse.ArgumentParser:
    root = repository_root()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    def common(command: argparse.ArgumentParser, output_root: Path) -> None:
        command.add_argument("--dataset", type=Path, default=root / "app/data/namsyntax_legal_qa_420.json")
        command.add_argument("--sidecar", type=Path, default=root / "docs/evaluation/gold_labels/namsyntax_legal_qa_420_labels_v2.json")
        command.add_argument("--output-root", type=Path, default=output_root)
        command.add_argument("--run-id")

    queue = commands.add_parser("queue", help="build a deterministic local review queue")
    common(queue, root / "docs/evaluation/adjudication/queues")
    queue.add_argument("--content-store", type=Path, default=root / "data/huggingface/content_store.sqlite3")
    queue.add_argument("--fts", type=Path, default=root / "data/huggingface/legal_fts.sqlite3")
    queue.add_argument("--target-cases", type=int, default=40)
    queue.add_argument("--candidate-limit", type=int, default=12)

    preview = commands.add_parser("preview", help="rebuild an immutable promotion preview")
    common(preview, root / "docs/evaluation/adjudication/previews")
    preview.add_argument("--queue", type=Path, required=True)
    preview.add_argument("--decisions", type=Path, required=True)

    promote = commands.add_parser("promote", help="write a new approved sidecar version")
    common(promote, root / "docs/evaluation/adjudication/promotions")
    promote.add_argument("--queue", type=Path, required=True)
    promote.add_argument("--decisions", type=Path, required=True)
    promote.add_argument("--preview", type=Path, required=True)
    promote.add_argument("--approve-preview-sha256", required=True)
    return parser


def _read_json(path: Path, name: str) -> tuple[Any, str]:
    target = _require_file(path, name)
    raw = target.read_bytes()
    try:
        return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"malformed {name} JSON") from error


def _require_file(path: Path, name: str) -> Path:
    target = Path(path).resolve()
    if not target.is_file():
        raise FileNotFoundError(f"{name} file not found: {target}")
    return target


def _output_root(value: Path, root: Path) -> Path:
    output_root = Path(value).resolve()
    try:
        output_root.relative_to(root)
    except ValueError as error:
        raise ValueError("output_root must remain inside the repository") from error
    return output_root


def _planned_run_dir(output_root: Path, run_id: str) -> Path:
    if _RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("invalid run_id: use 1-128 safe filename characters")
    planned = (output_root / run_id).resolve()
    if planned.parent != output_root or planned.exists():
        raise FileExistsError("run directory already exists or escapes output root")
    return planned


def _relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _safe_provenance(dependencies: RuntimeDependencies, root: Path) -> Any:
    provenance = dependencies.collect_git_provenance(root)
    return provenance.model_copy(update={"repository_root": "."})


def _contains_raw_adjudication_notes(value: Any) -> bool:
    if isinstance(value, dict):
        return "adjudication_notes" in value or any(
            _contains_raw_adjudication_notes(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_raw_adjudication_notes(item) for item in value)
    return False


def _load_sources(
    args: argparse.Namespace, dependencies: RuntimeDependencies,
) -> tuple[list[Any], Any, dict[str, Any], str, list[str]]:
    dataset_payload, dataset_sha256 = _read_json(args.dataset, "dataset")
    if not isinstance(dataset_payload, list) or not all(isinstance(item, dict) for item in dataset_payload):
        raise ValueError("dataset must be a JSON array of objects")
    provisional_cases = dependencies.build_cases(dataset_payload, {})
    dataset_case_ids = [case.case_id for case in provisional_cases]
    if not dataset_case_ids or len(dataset_case_ids) != len(set(dataset_case_ids)):
        raise ValueError("dataset case IDs must be nonempty and unique")
    sidecar_payload, sidecar_sha256 = _read_json(args.sidecar, "sidecar")
    if not isinstance(sidecar_payload, dict):
        raise ValueError("sidecar must be a JSON object")
    if _contains_raw_adjudication_notes(sidecar_payload):
        raise ValueError("source sidecar contains legacy raw adjudication_notes")
    sidecar = dependencies.load_gold_sidecar(args.sidecar, dataset_case_ids=dataset_case_ids)
    if sidecar.metadata.sidecar_sha256 != sidecar_sha256:
        raise ValueError("sidecar SHA-256 changed while loading")
    cases = dependencies.build_cases(dataset_payload, sidecar.labels_by_case_id)
    if [case.case_id for case in cases] != dataset_case_ids:
        raise ValueError("dataset case IDs changed while building cases")
    return cases, sidecar, sidecar_payload, dataset_sha256, dataset_case_ids


def _queue_hashes(
    queue_payload: Any,
    queue_file_sha256: str,
    dataset_sha256: str,
    sidecar_sha256: str,
    dependencies: RuntimeDependencies,
) -> str:
    if not isinstance(queue_payload, dict):
        raise ValueError("queue must be a JSON object")
    if dependencies.artifact_sha256(queue_payload) != queue_file_sha256:
        raise ValueError(
            "queue file SHA-256 does not match canonical immutable artifact bytes"
        )
    if queue_payload.get("dataset_sha256") != dataset_sha256:
        raise ValueError("queue dataset SHA-256 does not match dataset")
    provenance = queue_payload.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("sidecar_sha256") != sidecar_sha256:
        raise ValueError("queue sidecar SHA-256 does not match sidecar")
    return queue_file_sha256


def _queue_provenance(queue_payload: dict[str, Any], dependencies: RuntimeDependencies) -> Any:
    provenance = queue_payload.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("queue is missing provenance")
    return dependencies.GitProvenance.model_validate(provenance)


def _cmd_queue(args: argparse.Namespace) -> int:
    root = repository_root().resolve()
    output_root = _output_root(args.output_root, root)
    _require_file(args.content_store, "content store")
    _require_file(args.fts, "FTS")
    dependencies = _runtime_dependencies()
    cases, sidecar, _, dataset_sha256, _ = _load_sources(args, dependencies)
    if args.candidate_limit <= 0:
        raise ValueError("candidate_limit must be positive")
    selected_case_ids = dependencies.select_stratified_case_ids(
        cases, sidecar.labels_by_case_id, target_cases=args.target_cases
    )
    settings = dependencies.get_settings()
    store = dependencies.ContentStore(Path(args.content_store))
    fts_index = dependencies.LegalFtsIndex(
        store=store, path=Path(args.fts), dataset_revision=settings.DATASET_REVISION
    )
    candidates_by_case = dependencies.discover_adjudication_candidates(
        cases_by_id={case.case_id: case for case in cases},
        labels_by_case_id=sidecar.labels_by_case_id,
        selected_case_ids=selected_case_ids,
        content_store=store,
        fts_index=fts_index,
        candidate_limit=args.candidate_limit,
    )
    candidates_by_evidence: dict[str, list[Any]] = {}
    for candidates in candidates_by_case.values():
        for candidate in candidates:
            if candidate.evidence_item_id:
                candidates_by_evidence.setdefault(candidate.evidence_item_id, []).append(candidate)
    provenance = _safe_provenance(dependencies, root)
    queue_payload = dependencies.build_queue_payload(
        cases=cases,
        sidecar=sidecar,
        candidates_by_evidence_id=candidates_by_evidence,
        selected_case_ids=selected_case_ids,
        dataset_sha256=dataset_sha256,
        corpus_revision=settings.DATASET_REVISION,
        provenance=provenance,
        command=["run_gold_adjudication.py", "queue"],
        candidate_limit=args.candidate_limit,
        selection_seed="vietlex-p1-v1",
        target_case_count=args.target_cases,
    )
    queue_sha256 = dependencies.artifact_sha256(queue_payload)
    template = dependencies.build_decision_template(queue_payload, queue_sha256)
    run_id = args.run_id or dependencies.generate_unique_run_id("gold-adjudication-queue")
    planned_run = _planned_run_dir(output_root, run_id)
    paths = {
        "queue": _relative_path(planned_run / "queue.json", root),
        "decision_template": _relative_path(planned_run / "decision_template.json", root),
        "queue_summary": _relative_path(planned_run / "queue_summary.json", root),
    }
    summary = {
        "command": ["run_gold_adjudication.py", "queue"],
        "run_id": run_id,
        "artifact_paths": paths,
        "artifact_hashes": {
            "queue_sha256": queue_sha256,
            "decision_template_sha256": dependencies.artifact_sha256(template),
        },
        "target_case_count": queue_payload["target_case_count"],
        "selected_case_count": queue_payload["selected_case_count"],
        "queue_status": queue_payload["queue_status"],
        "selection_diagnostics": queue_payload["selection_diagnostics"],
        "provider_calls": queue_payload["provider_calls"],
        "dataset_sha256": dataset_sha256,
        "source_sidecar_sha256": sidecar.metadata.sidecar_sha256,
        "provenance": provenance.model_dump(mode="json"),
    }
    run_dir = dependencies.prepare_run_directory(output_root, run_id)
    dependencies.write_immutable_json(run_dir / "queue.json", queue_payload)
    dependencies.write_immutable_json(run_dir / "decision_template.json", template)
    dependencies.write_immutable_json(run_dir / "queue_summary.json", summary)
    return 0


def _build_preview(args: argparse.Namespace, dependencies: RuntimeDependencies) -> tuple[dict[str, Any], dict[str, Any], str]:
    cases, sidecar, sidecar_payload, dataset_sha256, dataset_case_ids = _load_sources(args, dependencies)
    del cases
    queue_payload, queue_file_sha256 = _read_json(args.queue, "queue")
    decisions_payload, decisions_file_sha256 = _read_json(args.decisions, "decisions")
    queue_sha256 = _queue_hashes(
        queue_payload,
        queue_file_sha256,
        dataset_sha256,
        sidecar.metadata.sidecar_sha256,
        dependencies,
    )
    if dependencies.artifact_sha256(decisions_payload) != decisions_file_sha256:
        raise ValueError(
            "decisions file SHA-256 does not match canonical immutable artifact bytes"
        )
    preview = dependencies.build_promotion_preview(
        queue_payload=queue_payload,
        queue_sha256=queue_sha256,
        decisions_payload=decisions_payload,
        decisions_sha256=decisions_file_sha256,
        source_sidecar_payload=sidecar_payload,
        source_sidecar_sha256=sidecar.metadata.sidecar_sha256,
        dataset_case_ids=dataset_case_ids,
        provenance=_queue_provenance(queue_payload, dependencies),
    )
    return preview, queue_payload, queue_sha256


def _cmd_preview(args: argparse.Namespace) -> int:
    root = repository_root().resolve()
    output_root = _output_root(args.output_root, root)
    dependencies = _runtime_dependencies()
    preview, _, _ = _build_preview(args, dependencies)
    run_id = args.run_id or dependencies.generate_unique_run_id("gold-adjudication-preview")
    _planned_run_dir(output_root, run_id)
    run_dir = dependencies.prepare_run_directory(output_root, run_id)
    dependencies.write_immutable_json(run_dir / "preview.json", preview)
    return 0


def _cmd_promote(args: argparse.Namespace) -> int:
    root = repository_root().resolve()
    output_root = _output_root(args.output_root, root)
    dependencies = _runtime_dependencies()
    preview, _, _ = _build_preview(args, dependencies)
    supplied_preview, _ = _read_json(args.preview, "preview")
    if dependencies.canonical_sha256(supplied_preview) != dependencies.canonical_sha256(preview):
        raise ValueError("supplied preview does not match the rebuilt preview")
    dependencies.validate_preview_approval(preview, args.approve_preview_sha256)
    summary = dependencies.build_promotion_summary(preview)
    run_id = args.run_id or dependencies.generate_unique_run_id("gold-adjudication-promotion")
    _planned_run_dir(output_root, run_id)
    run_dir = dependencies.prepare_run_directory(output_root, run_id)
    dependencies.write_immutable_json(run_dir / "labels_v2.json", preview["proposed_sidecar"])
    dependencies.write_immutable_json(run_dir / "promotion_summary.json", summary)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "queue":
        return _cmd_queue(args)
    if args.command == "preview":
        return _cmd_preview(args)
    if args.command == "promote":
        return _cmd_promote(args)
    raise ValueError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error
