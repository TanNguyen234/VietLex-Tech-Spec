from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field

from app.evaluation.schemas import GoldEvidence


class GoldSidecarMetadata(BaseModel):
    schema_version: str = "2.0.0"
    dataset_name: str = "namsyntax_legal_qa_420"
    total_cases: int = 420
    total_evidence_items: int = 0
    sidecar_sha256: str = ""


class GoldSidecar(BaseModel):
    metadata: GoldSidecarMetadata
    labels: List[GoldEvidence]
    labels_by_case_id: Dict[str, List[GoldEvidence]] = Field(default_factory=dict)


def load_gold_sidecar(
    path: Path | str, dataset_case_ids: Optional[Set[str] | List[str]] = None
) -> GoldSidecar:
    sidecar_path = Path(path).resolve()
    if not sidecar_path.exists():
        raise FileNotFoundError(f"Gold sidecar file not found at: {sidecar_path}")

    raw_bytes = sidecar_path.read_bytes()
    sha256_hash = hashlib.sha256(raw_bytes).hexdigest()

    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except Exception as err:
        raise ValueError(f"Malformed JSON in gold sidecar {sidecar_path}: {err}") from err

    if not isinstance(data, dict):
        raise ValueError(f"Invalid sidecar structure in {sidecar_path}: expected JSON object.")

    schema_version = data.get("schema_version")
    if schema_version != "2.0.0":
        raise ValueError(
            f"Unsupported gold sidecar schema_version '{schema_version}' in {sidecar_path}. "
            "Expected '2.0.0'. Silent fallback to legacy schema is prohibited."
        )

    labels_raw = data.get("labels")
    if not isinstance(labels_raw, list):
        raise ValueError(f"Malformed gold sidecar {sidecar_path}: 'labels' field must be a list.")

    declared_total_cases = data.get("total_cases")
    declared_total_items = data.get("total_evidence_items")

    if declared_total_items is not None and declared_total_items != len(labels_raw):
        raise ValueError(
            f"Sidecar evidence count mismatch in {sidecar_path}: declared {declared_total_items}, "
            f"but found {len(labels_raw)} labels in array."
        )

    validated_labels: List[GoldEvidence] = []
    labels_by_case: Dict[str, List[GoldEvidence]] = {}
    seen_evidence_ids: set[str] = set()

    for idx, item in enumerate(labels_raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Label item at index {idx} in {sidecar_path} is not a dict.")

        case_id = item.get("case_id")
        if not case_id or not isinstance(case_id, str):
            raise ValueError(f"Label item at index {idx} in {sidecar_path} missing non-empty 'case_id'.")

        evidence_id = item.get("evidence_item_id")
        if not evidence_id or not isinstance(evidence_id, str):
            raise ValueError(
                f"Label item at index {idx} in {sidecar_path} missing non-empty 'evidence_item_id'. "
                "Fallback generation is prohibited in V2.1."
            )

        status_val = item.get("status")
        if not status_val or not isinstance(status_val, str):
            raise ValueError(f"Label item at index {idx} in {sidecar_path} missing non-empty 'status'.")

        if "required" not in item or item.get("required") is None:
            raise ValueError(f"Label item at index {idx} in {sidecar_path} missing explicit 'required' boolean.")

        if evidence_id in seen_evidence_ids:
            raise ValueError(
                f"Duplicate evidence_item_id '{evidence_id}' found at label index {idx} in {sidecar_path}."
            )
        seen_evidence_ids.add(evidence_id)

        try:
            label_obj = GoldEvidence.model_validate(item)
        except Exception as err:
            raise ValueError(f"Failed to validate GoldEvidence at index {idx} in {sidecar_path}: {err}") from err

        validated_labels.append(label_obj)
        labels_by_case.setdefault(case_id, []).append(label_obj)

    sidecar_case_ids = set(labels_by_case.keys())
    if dataset_case_ids is not None:
        expected_set = set(dataset_case_ids)
        if sidecar_case_ids != expected_set:
            diff_missing = expected_set - sidecar_case_ids
            diff_extra = sidecar_case_ids - expected_set
            raise ValueError(
                f"Case ID set mismatch between dataset and sidecar: missing in sidecar={diff_missing}, "
                f"extra in sidecar={diff_extra}"
            )

    unique_case_count = len(labels_by_case)
    if declared_total_cases is not None and unique_case_count > declared_total_cases:
        raise ValueError(
            f"Unique case count ({unique_case_count}) exceeds declared total_cases ({declared_total_cases}) in {sidecar_path}."
        )

    meta = GoldSidecarMetadata(
        schema_version="2.0.0",
        dataset_name=data.get("dataset_name", "namsyntax_legal_qa_420"),
        total_cases=declared_total_cases or unique_case_count,
        total_evidence_items=len(validated_labels),
        sidecar_sha256=sha256_hash,
    )

    return GoldSidecar(
        metadata=meta,
        labels=validated_labels,
        labels_by_case_id=labels_by_case,
    )


def index_labels_by_case_id(sidecar: GoldSidecar) -> Dict[str, List[GoldEvidence]]:
    return sidecar.labels_by_case_id
