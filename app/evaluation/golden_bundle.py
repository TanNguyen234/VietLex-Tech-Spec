from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from app.evaluation.run_manifest import (
    atomic_write_json,
    calculate_dataset_sha256,
)


def _case_id(raw_case: dict[str, Any], index: int) -> str:
    return str(raw_case.get("case_id") or f"case_{index:03d}")


def export_golden_subset(
    *,
    dataset_path: Path,
    sidecar_path: Path,
    selected_case_ids: Sequence[str],
    output_dir: Path,
) -> dict[str, Any]:
    requested = list(selected_case_ids)
    if not requested or len(requested) != len(set(requested)):
        raise ValueError("selected case IDs must be nonempty and unique")
    raw_dataset = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    raw_sidecar = json.loads(Path(sidecar_path).read_text(encoding="utf-8"))
    indexed_cases = {
        _case_id(raw_case, index): {"case_id": _case_id(raw_case, index), **raw_case}
        for index, raw_case in enumerate(raw_dataset, start=1)
    }
    missing = [case_id for case_id in requested if case_id not in indexed_cases]
    if missing:
        raise ValueError(f"unknown selected case IDs: {missing}")
    runtime_case_ids = [
        f"case_{index:03d}" for index in range(1, len(requested) + 1)
    ]
    runtime_by_source = dict(zip(requested, runtime_case_ids, strict=True))
    cases = []
    for source_case_id in requested:
        raw_case = dict(indexed_cases[source_case_id])
        raw_case.pop("case_id", None)
        cases.append(
            {
                "case_id": runtime_by_source[source_case_id],
                "source_case_id": source_case_id,
                **raw_case,
            }
        )
    requested_set = set(requested)
    source_labels = [
        item
        for item in raw_sidecar.get("labels", [])
        if item.get("case_id") in requested_set
    ]
    labels_by_case: dict[str, list[dict[str, Any]]] = {
        case_id: [] for case_id in requested
    }
    for item in source_labels:
        labels_by_case[str(item["case_id"])].append(item)
    any_verified = 0
    all_required_verified = 0
    verified_items = 0
    for case_id in requested:
        case_labels = labels_by_case[case_id]
        verified = [item for item in case_labels if item.get("status") == "verified"]
        required = [item for item in case_labels if item.get("required") is True]
        verified_items += len(verified)
        if verified:
            any_verified += 1
        if required and all(item.get("status") == "verified" for item in required):
            all_required_verified += 1

    selected_sha = hashlib.sha256(
        json.dumps(requested, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    labels = [
        {
            **item,
            "case_id": runtime_by_source[str(item["case_id"])],
            "source_case_id": str(item["case_id"]),
        }
        for item in source_labels
    ]
    report = {
        "schema_version": "vietlex-golden-subset-v1",
        "selected_case_count": len(cases),
        "selected_case_ids": requested,
        "selected_case_ids_sha256": selected_sha,
        "runtime_case_ids": runtime_case_ids,
        "any_verified_case_count": any_verified,
        "all_required_verified_case_count": all_required_verified,
        "cases_without_verified_retrieval_gold": len(cases) - any_verified,
        "verified_evidence_item_count": verified_items,
        "source_dataset_sha256": calculate_dataset_sha256(Path(dataset_path)),
        "source_sidecar_sha256": calculate_dataset_sha256(Path(sidecar_path)),
    }
    output_dir = Path(output_dir)
    output_paths = [
        output_dir / "cases.json",
        output_dir / "labels.json",
        output_dir / "manifest.json",
    ]
    existing = [path.name for path in output_paths if path.exists()]
    if existing:
        raise FileExistsError(
            f"refusing to overwrite golden bundle artifacts: {existing}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output_dir / "cases.json", cases)
    atomic_write_json(
        output_dir / "labels.json",
        {
            "dataset_name": raw_sidecar.get("dataset_name", "vietlex-golden-subset"),
            "schema_version": "2.0.0",
            "total_cases": len(cases),
            "total_evidence_items": len(labels),
            "labels": labels,
        },
    )
    atomic_write_json(output_dir / "manifest.json", report)
    return report
