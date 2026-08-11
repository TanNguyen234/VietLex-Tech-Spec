"""Verified-gold, same-denominator model probe for the structural pilot."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.evaluation.artifact_io import write_immutable_json
from app.evaluation.case_selection import build_cases, select_evaluation_cases
from app.evaluation.gold_sidecar import load_gold_sidecar
from app.evaluation.retrieval_metrics import matches_required_level
from app.evaluation.schemas import CandidateChunk, GoldEvidence, GoldenCase
from app.ingestion.structural_index import StructuralRecord
from app.ingestion.structural_pilot import (
    CollectionCreationReceipt,
    StructuralPilotPlan,
    _validate_collection_readback,
)
from app.ingestion.structural_qdrant import (
    InferenceUsageReceipt,
    StructuralQdrantTransport,
    dense_query_document,
    point_from_record,
    point_payload,
    build_structural_inference_text,
    structural_inference_text_sha256,
)


_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_REFERENCE_MODEL = "llama-text-embed-v2"
_REFERENCE_DIMENSION = 1024
_PROBE_BATCH_SIZE = 64
_REFERENCE_BATCH_SIZE = 96
_PROBE_SAMPLING_VERSION = "primary-scope-hard-negatives-v1"
_CANARY_LIMIT = 64


class StructuralModelProbeError(RuntimeError):
    """Raised for deterministic probe-contract violations."""


class ProbeMetric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    numerator: float = Field(ge=0)
    denominator: int = Field(ge=0)
    value: float | None = Field(
        default=None,
        ge=0,
        le=1,
        allow_inf_nan=False,
    )

    @model_validator(mode="after")
    def validate_ratio(self):
        if self.denominator == 0:
            if self.numerator != 0 or self.value is not None:
                raise ValueError("zero-denominator probe metric must be null")
            return self
        expected = self.numerator / self.denominator
        if self.value is None or not math.isclose(
            self.value,
            expected,
            abs_tol=1e-12,
        ):
            raise ValueError("probe metric ratio is inconsistent")
        return self


class StructuralCanary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    document_id: int = Field(gt=0)
    legal_type: str = Field(min_length=1)


@dataclass(frozen=True)
class StructuralProbeSelection:
    """In-memory real records and cases; reports retain identities only."""

    cases: tuple[GoldenCase, ...]
    records: tuple[StructuralRecord, ...]
    skipped_cases: Mapping[str, str]
    relevant_record_ids: tuple[str, ...] = ()
    hard_negative_record_ids: tuple[str, ...] = ()
    canary_queries: tuple[StructuralCanary, ...] = ()
    canary_skips: Mapping[str, str] = field(default_factory=dict)
    sampling_version: str = _PROBE_SAMPLING_VERSION
    synthetic_records: Literal[0] = 0

    def __post_init__(self) -> None:
        case_ids = [case.case_id for case in self.cases]
        record_ids = [record.record_id for record in self.records]
        if case_ids != sorted(set(case_ids)):
            raise StructuralModelProbeError(
                "probe case IDs must be unique and sorted"
            )
        if record_ids != sorted(set(record_ids)):
            raise StructuralModelProbeError(
                "probe record IDs must be unique and sorted"
            )
        if not isinstance(self.skipped_cases, Mapping):
            raise StructuralModelProbeError("skipped cases must be a mapping")
        relevant = set(self.relevant_record_ids)
        negatives = set(self.hard_negative_record_ids)
        if (
            relevant & negatives
            or relevant | negatives != set(record_ids)
            or self.relevant_record_ids != tuple(sorted(relevant))
            or self.hard_negative_record_ids != tuple(sorted(negatives))
        ):
            raise StructuralModelProbeError(
                "probe relevant/negative record partition is invalid"
            )
        canary_ids = [canary.query_id for canary in self.canary_queries]
        if canary_ids != sorted(set(canary_ids)):
            raise StructuralModelProbeError(
                "probe canary IDs must be unique and sorted"
            )
        if self.sampling_version != _PROBE_SAMPLING_VERSION:
            raise StructuralModelProbeError("probe sampling version mismatch")

    @classmethod
    def from_resolved(
        cls,
        *,
        cases: Sequence[GoldenCase],
        records: Sequence[StructuralRecord],
        skipped_cases: Mapping[str, str],
        relevant_record_ids: Sequence[str] | None = None,
        hard_negative_record_ids: Sequence[str] | None = None,
        canary_queries: Sequence[StructuralCanary] = (),
        canary_skips: Mapping[str, str] | None = None,
    ) -> StructuralProbeSelection:
        ordered_records = tuple(
            sorted(records, key=lambda record: record.record_id)
        )
        relevant = tuple(
            sorted(
                relevant_record_ids
                if relevant_record_ids is not None
                else (record.record_id for record in ordered_records)
            )
        )
        negatives = tuple(sorted(hard_negative_record_ids or ()))
        return cls(
            cases=tuple(sorted(cases, key=lambda case: case.case_id)),
            records=ordered_records,
            skipped_cases=dict(sorted(skipped_cases.items())),
            relevant_record_ids=relevant,
            hard_negative_record_ids=negatives,
            canary_queries=tuple(
                sorted(canary_queries, key=lambda canary: canary.query_id)
            ),
            canary_skips=dict(sorted((canary_skips or {}).items())),
        )

    @property
    def case_ids(self) -> tuple[str, ...]:
        return tuple(case.case_id for case in self.cases)

    @property
    def record_ids(self) -> tuple[str, ...]:
        return tuple(record.record_id for record in self.records)

    @property
    def case_ids_sha256(self) -> str:
        return _canonical_sha256(self.case_ids)

    @property
    def record_ids_sha256(self) -> str:
        return _canonical_sha256(self.record_ids)

    @property
    def text_sha256(self) -> str:
        return _canonical_sha256(
            [
                {
                    "record_id": record.record_id,
                    "inference_text_sha256": (
                        structural_inference_text_sha256(record)
                    ),
                }
                for record in self.records
            ]
        )


@dataclass(frozen=True)
class StructuralModelProbeInput:
    plan: StructuralPilotPlan
    creation_receipt: CollectionCreationReceipt
    creation_receipt_sha256: str
    selection: StructuralProbeSelection
    dataset_sha256: str
    sidecar_sha256: str
    output_path: Path | None = None

    def __post_init__(self) -> None:
        for name in (
            "creation_receipt_sha256",
            "dataset_sha256",
            "sidecar_sha256",
        ):
            value = getattr(self, name)
            if not _is_sha256(value):
                raise StructuralModelProbeError(f"{name} is malformed")

    def with_selection(
        self,
        selection: StructuralProbeSelection,
    ) -> StructuralModelProbeInput:
        return replace(self, selection=selection)


@dataclass(frozen=True)
class LoadedStructuralProbeScope:
    selection: StructuralProbeSelection
    dataset_sha256: str
    sidecar_sha256: str


class PineconeReferenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: Literal["llama-text-embed-v2"]
    dimension: Literal[1024]
    dataset_sha256: str = Field(pattern=_SHA256_PATTERN)
    sidecar_sha256: str = Field(pattern=_SHA256_PATTERN)
    source_state_sha256: str = Field(pattern=_SHA256_PATTERN)
    case_ids_sha256: str = Field(pattern=_SHA256_PATTERN)
    record_ids_sha256: str = Field(pattern=_SHA256_PATTERN)
    text_sha256: str = Field(pattern=_SHA256_PATTERN)
    metrics: dict[str, ProbeMetric]
    per_query_first_relevant_rank: dict[str, int | None]
    provider_usage: dict[str, int]
    passage_input_count: int = Field(gt=0)
    query_input_count: int = Field(gt=0)
    provider_calls: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_reference_contract(self):
        if set(self.metrics) != {"recall_at_1", "recall_at_3", "mrr"}:
            raise ValueError("reference metric set mismatch")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in self.provider_usage.values()
        ):
            raise ValueError("reference provider usage is malformed")
        return self


class StructuralModelProbeReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["2.0.0"] = "2.0.0"
    created_at_utc: datetime
    acceptance: Literal[
        "PASS_MODEL_PROBE",
        "FAIL_QUALITY",
        "BLOCKED_TECHNICAL",
        "BLOCKED_SCOPE",
    ]
    collection_name: Literal["vietlex-legal-rag-v2-pilot"]
    dataset_revision: str = Field(min_length=1)
    dataset_sha256: str = Field(pattern=_SHA256_PATTERN)
    sidecar_sha256: str = Field(pattern=_SHA256_PATTERN)
    source_state_sha256: str = Field(pattern=_SHA256_PATTERN)
    plan_sha256: str = Field(pattern=_SHA256_PATTERN)
    creation_receipt_sha256: str = Field(pattern=_SHA256_PATTERN)
    candidate_dense_model: Literal["Qwen/Qwen3-Embedding-0.6B"]
    candidate_sparse_model: Literal["qdrant/bm25"]
    candidate_dense_model_options: dict[str, object]
    candidate_sparse_model_options: dict[str, object]
    query_instruction_version: Literal["vietlex-vn-legal-retrieval-v1"]
    case_ids: tuple[str, ...]
    record_ids: tuple[str, ...]
    sampling_version: Literal["primary-scope-hard-negatives-v1"]
    relevant_record_ids: tuple[str, ...]
    hard_negative_record_ids: tuple[str, ...]
    canary_queries: tuple[StructuralCanary, ...]
    canary_skips: dict[str, str]
    probe_record_hashes: dict[str, str]
    probe_inference_text_hashes: dict[str, str]
    case_ids_sha256: str = Field(pattern=_SHA256_PATTERN)
    record_ids_sha256: str = Field(pattern=_SHA256_PATTERN)
    text_sha256: str = Field(pattern=_SHA256_PATTERN)
    skipped_cases: dict[str, str]
    synthetic_records: Literal[0]
    selected_case_count: int = Field(ge=0)
    skipped_case_count: int = Field(ge=0)
    coverage: ProbeMetric
    metrics: dict[str, ProbeMetric]
    per_query_first_relevant_rank: dict[str, int | None]
    gold_document_metrics: dict[str, ProbeMetric]
    gold_structural_metrics: dict[str, ProbeMetric]
    per_query_first_document_rank: dict[str, int | None]
    per_query_first_structural_rank: dict[str, int | None]
    canary_metrics: dict[str, ProbeMetric]
    per_canary_first_relevant_rank: dict[str, int | None]
    reference: PineconeReferenceResult | None
    provider_usage: dict[str, int]
    upsert_provider_usage: dict[str, int]
    query_provider_usage: dict[str, int]
    upsert_batch_sizes: tuple[int, ...]
    upserted_record_count: int = Field(ge=0)
    retrieved_vector_count: int = Field(ge=0)
    vector_validation: Literal["passed", "not_completed"]
    elapsed_seconds: float = Field(ge=0, allow_inf_nan=False)
    technical_errors: dict[str, str]
    provider_cleanup_calls: Literal[0] = 0

    @model_validator(mode="after")
    def validate_report_contract(self):
        if self.case_ids != tuple(sorted(set(self.case_ids))):
            raise ValueError("report case IDs are not unique and sorted")
        if self.record_ids != tuple(sorted(set(self.record_ids))):
            raise ValueError("report record IDs are not unique and sorted")
        relevant = set(self.relevant_record_ids)
        negatives = set(self.hard_negative_record_ids)
        if (
            relevant & negatives
            or relevant | negatives != set(self.record_ids)
            or self.relevant_record_ids != tuple(sorted(relevant))
            or self.hard_negative_record_ids != tuple(sorted(negatives))
        ):
            raise ValueError("report probe record partition is inconsistent")
        canary_ids = tuple(canary.query_id for canary in self.canary_queries)
        if canary_ids != tuple(sorted(set(canary_ids))):
            raise ValueError("report canary identities are inconsistent")
        if set(self.per_canary_first_relevant_rank) != set(canary_ids):
            raise ValueError("report canary ranks are inconsistent")
        if self.canary_metrics != _canary_metrics_from_ranks(
            self.per_canary_first_relevant_rank
        ):
            raise ValueError("report canary metrics do not match ranks")
        if set(self.per_query_first_document_rank) != set(self.case_ids) or set(
            self.per_query_first_structural_rank
        ) != set(self.case_ids):
            raise ValueError("report absolute gold ranks are incomplete")
        if self.gold_document_metrics != _rank_metrics_at_10(
            self.per_query_first_document_rank
        ) or self.gold_structural_metrics != _rank_metrics_at_10(
            self.per_query_first_structural_rank
        ):
            raise ValueError("report absolute gold metrics do not match ranks")
        if set(self.case_ids) & set(self.skipped_cases):
            raise ValueError("included and skipped cases overlap")
        if self.selected_case_count != len(self.case_ids) or (
            self.skipped_case_count != len(self.skipped_cases)
        ):
            raise ValueError("report case counts are inconsistent")
        if self.case_ids_sha256 != _canonical_sha256(self.case_ids) or (
            self.record_ids_sha256 != _canonical_sha256(self.record_ids)
        ):
            raise ValueError("report identity hash mismatch")
        if set(self.probe_record_hashes) != set(self.record_ids) or any(
            not _is_sha256(value) for value in self.probe_record_hashes.values()
        ):
            raise ValueError("report probe record hashes are inconsistent")
        if set(self.probe_inference_text_hashes) != set(self.record_ids) or any(
            not _is_sha256(value)
            for value in self.probe_inference_text_hashes.values()
        ):
            raise ValueError(
                "report probe inference text hashes are inconsistent"
            )
        if any(size <= 0 or size > _PROBE_BATCH_SIZE for size in self.upsert_batch_sizes):
            raise ValueError("report upsert batch size is invalid")
        if sum(self.upsert_batch_sizes) != self.upserted_record_count:
            raise ValueError("report upsert count is inconsistent")
        if self.acceptance in {"PASS_MODEL_PROBE", "FAIL_QUALITY"}:
            if self.technical_errors:
                raise ValueError("valid execution cannot contain technical errors")
            if self.vector_validation != "passed":
                raise ValueError("valid execution requires vector readback")
            if (
                self.upserted_record_count != len(self.record_ids)
                or self.retrieved_vector_count != len(self.record_ids)
            ):
                raise ValueError("valid execution record counts are incomplete")
            expected_usage = {
                "Qwen/Qwen3-Embedding-0.6B",
                "qdrant/bm25",
            }
            if self.reference is not None:
                expected_usage.add("llama-text-embed-v2")
            if set(self.provider_usage) != expected_usage or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                for value in self.provider_usage.values()
            ):
                raise ValueError("valid execution provider usage is incomplete")
            if set(self.upsert_provider_usage) != {
                self.candidate_dense_model,
                self.candidate_sparse_model,
            } or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                for value in self.upsert_provider_usage.values()
            ):
                raise ValueError("valid execution upsert usage is incomplete")
            if set(self.query_provider_usage) != {
                self.candidate_dense_model
            } or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                for value in self.query_provider_usage.values()
            ):
                raise ValueError("valid execution query usage is incomplete")
            expected_candidate_usage = {
                self.candidate_dense_model: (
                    self.upsert_provider_usage[self.candidate_dense_model]
                    + self.query_provider_usage[self.candidate_dense_model]
                ),
                self.candidate_sparse_model: self.upsert_provider_usage[
                    self.candidate_sparse_model
                ],
            }
            if any(
                self.provider_usage[model_name] != tokens
                for model_name, tokens in expected_candidate_usage.items()
            ):
                raise ValueError("valid execution staged usage is inconsistent")
            if set(self.per_query_first_relevant_rank) != set(self.case_ids):
                raise ValueError("valid execution per-query ranks are incomplete")
            if self.metrics != _metrics_from_ranks(
                self.per_query_first_relevant_rank
            ):
                raise ValueError("valid execution metrics do not match ranks")
            if self.reference is not None:
                reference_binding = {
                    "dataset_sha256": self.dataset_sha256,
                    "sidecar_sha256": self.sidecar_sha256,
                    "source_state_sha256": self.source_state_sha256,
                    "case_ids_sha256": self.case_ids_sha256,
                    "record_ids_sha256": self.record_ids_sha256,
                    "text_sha256": self.text_sha256,
                }
                if any(
                    getattr(self.reference, name) != value
                    for name, value in reference_binding.items()
                ):
                    raise ValueError(
                        "valid execution reference binding mismatch"
                    )
            expected_acceptance = decide_model_probe_acceptance(
                gold_document_recall_at_10=(
                    self.gold_document_metrics["recall_at_10"].value
                ),
                gold_structural_recall_at_10=(
                    self.gold_structural_metrics["recall_at_10"].value
                ),
                canary_document_recall_at_10=(
                    self.canary_metrics["document_recall_at_10"].value
                ),
                technical_error_count=0,
            )
            if self.acceptance != expected_acceptance:
                raise ValueError("probe acceptance does not match quality gates")
        if self.acceptance == "BLOCKED_TECHNICAL" and not self.technical_errors:
            raise ValueError("blocked technical report requires an error")
        return self


def select_model_probe_records(
    cases: Sequence[GoldenCase],
    records: Iterable[StructuralRecord],
) -> StructuralProbeSelection:
    """Resolve only all-required-verified evidence to real structural rows."""
    selected = select_evaluation_cases(
        list(cases),
        "all-required-verified",
    ).selected_cases
    required_by_case: dict[str, tuple[GoldEvidence, ...]] = {}
    labels_by_document: dict[int, list[tuple[str, GoldEvidence]]] = {}
    invalid_document_cases: set[str] = set()
    for case in selected:
        labels = tuple(
            label
            for label in case.gold_evidence
            if label.required and label.status == "verified"
        )
        required_by_case[case.case_id] = labels
        for label in labels:
            document_id = _positive_document_id(label.document_id)
            if document_id is None:
                invalid_document_cases.add(case.case_id)
                continue
            labels_by_document.setdefault(document_id, []).append(
                (case.case_id, label)
            )

    seen_document_ids: set[int] = set()
    matched_evidence: dict[str, set[str]] = {
        case.case_id: set() for case in selected
    }
    matched_records: dict[str, dict[str, StructuralRecord]] = {
        case.case_id: {} for case in selected
    }
    representatives: dict[int, StructuralRecord] = {}
    for record in records:
        seen_document_ids.add(record.document_id)
        current = representatives.get(record.document_id)
        if current is None or _probe_record_sampling_key(record) < (
            _probe_record_sampling_key(current)
        ):
            representatives[record.document_id] = record
        labels = labels_by_document.get(record.document_id, ())
        if not labels:
            continue
        candidate = _candidate_from_record(record)
        for case_id, label in labels:
            if matches_required_level(label, candidate):
                matched_evidence[case_id].add(label.evidence_item_id)
                matched_records[case_id][record.record_id] = record

    included_cases: list[GoldenCase] = []
    selected_records: dict[str, StructuralRecord] = {}
    skipped: dict[str, str] = {}
    for case in sorted(selected, key=lambda item: item.case_id):
        labels = required_by_case[case.case_id]
        label_document_ids = {
            value
            for value in (_positive_document_id(label.document_id) for label in labels)
            if value is not None
        }
        if (
            case.case_id in invalid_document_cases
            or not label_document_ids.issubset(seen_document_ids)
        ):
            skipped[case.case_id] = "outside_primary_legislation_scope"
            continue
        expected_evidence_ids = {label.evidence_item_id for label in labels}
        if matched_evidence[case.case_id] != expected_evidence_ids:
            skipped[case.case_id] = "verified_structure_not_resolved"
            continue
        included_cases.append(case)
        selected_records.update(matched_records[case.case_id])

    relevant_record_ids = tuple(sorted(selected_records))
    hard_negative_records = tuple(
        record
        for document_id, record in sorted(representatives.items())
        if document_id not in labels_by_document
    )
    selected_records.update(
        (record.record_id, record) for record in hard_negative_records
    )
    canaries, canary_skips = _select_structural_canaries(
        hard_negative_records,
    )

    return StructuralProbeSelection.from_resolved(
        cases=included_cases,
        records=tuple(selected_records.values()),
        skipped_cases=skipped,
        relevant_record_ids=relevant_record_ids,
        hard_negative_record_ids=tuple(
            record.record_id for record in hard_negative_records
        ),
        canary_queries=canaries,
        canary_skips=canary_skips,
    )


def _probe_record_sampling_key(record: StructuralRecord) -> str:
    return hashlib.sha256(
        f"{_PROBE_SAMPLING_VERSION}:{record.record_id}".encode("utf-8")
    ).hexdigest()


def _select_structural_canaries(
    records: Sequence[StructuralRecord],
) -> tuple[tuple[StructuralCanary, ...], dict[str, str]]:
    by_type: dict[str, list[StructuralRecord]] = {}
    for record in records:
        by_type.setdefault(record.legal_type, []).append(record)

    strata: dict[tuple[str, int], list[StructuralRecord]] = {}
    for legal_type, type_records in sorted(by_type.items()):
        ordered = sorted(type_records, key=lambda record: record.document_id)
        count = len(ordered)
        for index, record in enumerate(ordered):
            quantile = min(3, index * 4 // count)
            strata.setdefault((legal_type, quantile), []).append(record)
    for rows in strata.values():
        rows.sort(
            key=lambda record: hashlib.sha256(
                (
                    f"{_PROBE_SAMPLING_VERSION}:canary:"
                    f"{record.document_id}:{record.title}"
                ).encode("utf-8")
            ).hexdigest()
        )

    selected: list[StructuralRecord] = []
    keys = sorted(strata)
    while keys and len(selected) < _CANARY_LIMIT:
        remaining: list[tuple[str, int]] = []
        for key in keys:
            rows = strata[key]
            if rows and len(selected) < _CANARY_LIMIT:
                selected.append(rows.pop(0))
            if rows:
                remaining.append(key)
        keys = remaining

    canaries: list[StructuralCanary] = []
    skips: dict[str, str] = {}
    seen_queries: set[str] = set()
    for record in selected:
        query = re.sub(
            re.escape(record.document_number),
            " ",
            record.title,
            flags=re.IGNORECASE,
        )
        query = " ".join(query.split())
        skip_id = f"document-{record.document_id}"
        if not query:
            skips[skip_id] = "blank_title_after_reference_removal"
            continue
        identity = query.casefold()
        if identity in seen_queries:
            skips[skip_id] = "duplicate_title_query"
            continue
        seen_queries.add(identity)
        query_id = "canary-" + hashlib.sha256(
            f"{record.document_id}:{query}".encode("utf-8")
        ).hexdigest()[:16]
        canaries.append(
            StructuralCanary(
                query_id=query_id,
                query=query,
                document_id=record.document_id,
                legal_type=record.legal_type,
            )
        )
    return tuple(sorted(canaries, key=lambda row: row.query_id)), skips


def load_verified_probe_scope(
    dataset_path: Path,
    sidecar_path: Path,
    records: Iterable[StructuralRecord],
) -> LoadedStructuralProbeScope:
    """Load exact source bytes and resolve the verified scope without fallback."""
    dataset_bytes = Path(dataset_path).read_bytes()
    try:
        raw_dataset = json.loads(dataset_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StructuralModelProbeError("evaluation dataset is malformed") from error
    if not isinstance(raw_dataset, list) or any(
        not isinstance(item, dict) for item in raw_dataset
    ):
        raise StructuralModelProbeError(
            "evaluation dataset must be an array of objects"
        )
    case_ids = [
        item.get("case_id", f"case_{index:03d}")
        for index, item in enumerate(raw_dataset, start=1)
    ]
    if any(
        not isinstance(case_id, str) or not case_id.strip()
        for case_id in case_ids
    ) or len(case_ids) != len(set(case_ids)):
        raise StructuralModelProbeError(
            "evaluation dataset case IDs are malformed"
        )
    sidecar = load_gold_sidecar(
        sidecar_path,
        dataset_case_ids=case_ids,
    )
    cases = build_cases(raw_dataset, sidecar.labels_by_case_id)
    selection = select_model_probe_records(cases, records)
    return LoadedStructuralProbeScope(
        selection=selection,
        dataset_sha256=hashlib.sha256(dataset_bytes).hexdigest(),
        sidecar_sha256=sidecar.metadata.sidecar_sha256,
    )


class PineconeReferenceEmbedder:
    """Inference-only Pinecone reference; this class has no storage client."""

    def __init__(self, inference: object) -> None:
        self._inference = inference

    def evaluate(
        self,
        probe: StructuralModelProbeInput,
    ) -> PineconeReferenceResult:
        selection = probe.selection
        if not selection.cases or not selection.records:
            raise StructuralModelProbeError("reference scope is empty")
        passage_vectors, passage_tokens, passage_calls = self._embed(
            [build_structural_inference_text(record) for record in selection.records],
            input_type="passage",
        )
        query_vectors, query_tokens, query_calls = self._embed(
            [case.question for case in selection.cases],
            input_type="query",
        )
        ranks = _cosine_first_relevant_ranks(
            selection,
            query_vectors=query_vectors,
            passage_vectors=passage_vectors,
        )
        return PineconeReferenceResult(
            model=_REFERENCE_MODEL,
            dimension=_REFERENCE_DIMENSION,
            dataset_sha256=probe.dataset_sha256,
            sidecar_sha256=probe.sidecar_sha256,
            source_state_sha256=probe.plan.source_state_sha256,
            case_ids_sha256=selection.case_ids_sha256,
            record_ids_sha256=selection.record_ids_sha256,
            text_sha256=selection.text_sha256,
            metrics=_metrics_from_ranks(ranks),
            per_query_first_relevant_rank=ranks,
            provider_usage={
                _REFERENCE_MODEL: passage_tokens + query_tokens
            },
            passage_input_count=len(selection.records),
            query_input_count=len(selection.cases),
            provider_calls=passage_calls + query_calls,
        )

    def _embed(
        self,
        texts: Sequence[str],
        *,
        input_type: Literal["passage", "query"],
    ) -> tuple[list[list[float]], int, int]:
        vectors: list[list[float]] = []
        tokens = 0
        calls = 0
        for batch in _batches(texts, _REFERENCE_BATCH_SIZE):
            try:
                response = self._inference.embed(
                    model=_REFERENCE_MODEL,
                    inputs=list(batch),
                    parameters={
                        "input_type": input_type,
                        "dimension": _REFERENCE_DIMENSION,
                        "truncate": "END",
                    },
                )
            except Exception as error:
                raise StructuralModelProbeError(
                    "Pinecone reference inference failed "
                    f"({type(error).__name__})"
                ) from error
            if getattr(response, "model", None) != _REFERENCE_MODEL:
                raise StructuralModelProbeError(
                    "Pinecone reference model response mismatch"
                )
            data = getattr(response, "data", None)
            if not isinstance(data, list) or len(data) != len(batch):
                raise StructuralModelProbeError(
                    "Pinecone reference vector count mismatch"
                )
            batch_vectors = [getattr(item, "values", None) for item in data]
            for vector in batch_vectors:
                _validate_dense_vector(vector, stage="Pinecone reference")
            usage = getattr(response, "usage", None)
            total_tokens = getattr(usage, "total_tokens", None)
            if (
                isinstance(total_tokens, bool)
                or not isinstance(total_tokens, int)
                or total_tokens <= 0
            ):
                raise StructuralModelProbeError(
                    "Pinecone reference usage is missing"
                )
            vectors.extend(batch_vectors)
            tokens += total_tokens
            calls += 1
        return vectors, tokens, calls


def run_structural_model_probe(
    transport: StructuralQdrantTransport,
    probe: StructuralModelProbeInput,
    reference_embedder: object | None = None,
) -> StructuralModelProbeReport:
    """Run a bounded real probe and always preserve a typed final artifact."""
    started = time.perf_counter()
    if probe.output_path is not None and Path(probe.output_path).exists():
        raise StructuralModelProbeError("model probe artifact already exists")
    selection = probe.selection
    metrics = _zero_metrics(len(selection.cases))
    ranks: dict[str, int | None] = {}
    document_ranks: dict[str, int | None] = {
        case.case_id: None for case in selection.cases
    }
    structural_ranks: dict[str, int | None] = dict(document_ranks)
    gold_document_metrics = _rank_metrics_at_10(document_ranks)
    gold_structural_metrics = _rank_metrics_at_10(structural_ranks)
    canary_ranks: dict[str, int | None] = {
        canary.query_id: None for canary in selection.canary_queries
    }
    canary_metrics = _canary_metrics_from_ranks(canary_ranks)
    reference: PineconeReferenceResult | None = None
    usage: dict[str, int] = {}
    upsert_usage: dict[str, int] = {}
    query_usage: dict[str, int] = {}
    batch_sizes: list[int] = []
    upserted_count = 0
    vector_count = 0
    vector_validation: Literal["passed", "not_completed"] = "not_completed"
    technical_errors: dict[str, str] = {}
    acceptance: Literal[
        "PASS_MODEL_PROBE",
        "FAIL_QUALITY",
        "BLOCKED_TECHNICAL",
        "BLOCKED_SCOPE",
    ] = "BLOCKED_TECHNICAL"
    stage = "preflight"

    try:
        _validate_probe_bindings(probe, transport)
        if not selection.cases or not selection.records:
            acceptance = "BLOCKED_SCOPE"
            technical_errors = {
                "scope": "no_verified_in_scope_structural_probe_cases"
            }
        else:
            if reference_embedder is not None:
                stage = "reference"
                reference = reference_embedder.evaluate(probe)
                _validate_reference_binding(reference, probe)
                _merge_usage(usage, reference.provider_usage)

            stage = "upsert"
            _validate_live_probe_schema(
                transport,
                probe,
                expected_points_count=None,
            )
            for record_batch in _batches(selection.records, _PROBE_BATCH_SIZE):
                points = [
                    point_from_record(record, transport.contract)
                    for record in record_batch
                ]
                receipt = transport.upsert_with_usage(points)
                _validate_qdrant_usage(
                    receipt,
                    expected={
                        transport.contract.dense_model,
                        transport.contract.sparse_model,
                    },
                    stage="upsert",
                )
                _merge_usage(usage, receipt.model_tokens)
                _merge_usage(upsert_usage, receipt.model_tokens)
                batch_sizes.append(len(points))
                upserted_count += len(points)

            _validate_live_probe_schema(
                transport,
                probe,
                expected_points_count=len(selection.records),
            )

            stage = "vector_readback"
            vector_count = _validate_probe_vectors(transport, selection.records)
            vector_validation = "passed"

            stage = "candidate_queries"
            document_ranks, structural_ranks = _qdrant_gold_ranks(
                transport,
                selection,
                query_usage,
            )
            ranks = structural_ranks
            canary_ranks = _qdrant_canary_ranks(
                transport,
                selection.canary_queries,
                query_usage,
            )
            _merge_usage(usage, query_usage)
            metrics = _metrics_from_ranks(ranks)
            gold_document_metrics = _rank_metrics_at_10(document_ranks)
            gold_structural_metrics = _rank_metrics_at_10(structural_ranks)
            canary_metrics = _canary_metrics_from_ranks(canary_ranks)
            if reference is not None:
                _validate_comparable_denominator(metrics, reference.metrics)
            acceptance = decide_model_probe_acceptance(
                gold_document_recall_at_10=(
                    gold_document_metrics["recall_at_10"].value
                ),
                gold_structural_recall_at_10=(
                    gold_structural_metrics["recall_at_10"].value
                ),
                canary_document_recall_at_10=(
                    canary_metrics["document_recall_at_10"].value
                ),
                technical_error_count=0,
            )
    except Exception as error:
        acceptance = "BLOCKED_TECHNICAL"
        technical_errors = {
            stage: (
                str(error)
                if isinstance(error, StructuralModelProbeError)
                else type(error).__name__
            )
        }

    report = StructuralModelProbeReport(
        created_at_utc=datetime.now(timezone.utc),
        acceptance=acceptance,
        collection_name=probe.plan.contract.collection_name,
        dataset_revision=probe.plan.manifest.dataset_revision,
        dataset_sha256=probe.dataset_sha256,
        sidecar_sha256=probe.sidecar_sha256,
        source_state_sha256=probe.plan.source_state_sha256,
        plan_sha256=probe.plan.plan_sha256,
        creation_receipt_sha256=probe.creation_receipt_sha256,
        candidate_dense_model=probe.plan.contract.dense_model,
        candidate_sparse_model=probe.plan.contract.sparse_model,
        candidate_dense_model_options=dict(
            probe.plan.contract.dense_model_options
        ),
        candidate_sparse_model_options=dict(
            probe.plan.contract.sparse_model_options
        ),
        query_instruction_version=(
            probe.plan.contract.query_instruction_version
        ),
        case_ids=selection.case_ids,
        record_ids=selection.record_ids,
        sampling_version=selection.sampling_version,
        relevant_record_ids=selection.relevant_record_ids,
        hard_negative_record_ids=selection.hard_negative_record_ids,
        canary_queries=selection.canary_queries,
        canary_skips=dict(selection.canary_skips),
        probe_record_hashes={
            record.record_id: record.chunk_sha256
            for record in selection.records
        },
        probe_inference_text_hashes={
            record.record_id: structural_inference_text_sha256(record)
            for record in selection.records
        },
        case_ids_sha256=selection.case_ids_sha256,
        record_ids_sha256=selection.record_ids_sha256,
        text_sha256=selection.text_sha256,
        skipped_cases=dict(selection.skipped_cases),
        synthetic_records=selection.synthetic_records,
        selected_case_count=len(selection.cases),
        skipped_case_count=len(selection.skipped_cases),
        coverage=_coverage_metric(selection),
        metrics=metrics,
        per_query_first_relevant_rank=ranks,
        gold_document_metrics=gold_document_metrics,
        gold_structural_metrics=gold_structural_metrics,
        per_query_first_document_rank=document_ranks,
        per_query_first_structural_rank=structural_ranks,
        canary_metrics=canary_metrics,
        per_canary_first_relevant_rank=canary_ranks,
        reference=reference,
        provider_usage=usage,
        upsert_provider_usage=upsert_usage,
        query_provider_usage=query_usage,
        upsert_batch_sizes=tuple(batch_sizes),
        upserted_record_count=upserted_count,
        retrieved_vector_count=vector_count,
        vector_validation=vector_validation,
        elapsed_seconds=time.perf_counter() - started,
        technical_errors=technical_errors,
    )
    if probe.output_path is not None:
        write_immutable_json(
            probe.output_path,
            report.model_dump(mode="json"),
        )
    return report


def load_matching_reference_probe(
    path: Path,
    probe: StructuralModelProbeInput,
) -> PineconeReferenceResult:
    try:
        reference = PineconeReferenceResult.model_validate_json(
            Path(path).read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as error:
        raise StructuralModelProbeError(
            "immutable reference probe is invalid"
        ) from error
    _validate_reference_binding(reference, probe)
    return reference


class StaticReferenceEmbedder:
    def __init__(self, reference: PineconeReferenceResult) -> None:
        self.reference = reference

    def evaluate(
        self,
        _probe: StructuralModelProbeInput,
    ) -> PineconeReferenceResult:
        return self.reference


def _validate_probe_bindings(
    probe: StructuralModelProbeInput,
    transport: StructuralQdrantTransport,
) -> None:
    receipt = probe.creation_receipt
    plan = probe.plan
    if receipt.status != "CREATED":
        raise StructuralModelProbeError("creation receipt is not successful")
    if (
        receipt.collection_name != plan.contract.collection_name
        or receipt.plan_sha256 != plan.plan_sha256
        or receipt.source_state_sha256 != plan.source_state_sha256
    ):
        raise StructuralModelProbeError("creation receipt binding mismatch")
    if transport.contract != plan.contract:
        raise StructuralModelProbeError("Qdrant transport contract mismatch")
    if any(
        record.dataset_revision != plan.manifest.dataset_revision
        for record in probe.selection.records
    ):
        raise StructuralModelProbeError("probe record dataset revision mismatch")


def _validate_reference_binding(
    reference: PineconeReferenceResult,
    probe: StructuralModelProbeInput,
) -> None:
    selection = probe.selection
    expected = {
        "dataset_sha256": probe.dataset_sha256,
        "sidecar_sha256": probe.sidecar_sha256,
        "source_state_sha256": probe.plan.source_state_sha256,
        "case_ids_sha256": selection.case_ids_sha256,
        "record_ids_sha256": selection.record_ids_sha256,
        "text_sha256": selection.text_sha256,
    }
    if any(getattr(reference, name) != value for name, value in expected.items()):
        raise StructuralModelProbeError(
            "reference candidate denominator or source binding mismatch"
        )
    if (
        reference.passage_input_count != len(selection.records)
        or reference.query_input_count != len(selection.cases)
    ):
        raise StructuralModelProbeError("reference input count mismatch")
    if (
        set(reference.provider_usage) != {_REFERENCE_MODEL}
        or reference.provider_usage.get(_REFERENCE_MODEL, 0) <= 0
    ):
        raise StructuralModelProbeError("reference provider usage is missing")
    expected_case_ids = set(selection.case_ids)
    if set(reference.per_query_first_relevant_rank) != expected_case_ids or any(
        rank is not None
        and (
            isinstance(rank, bool)
            or not isinstance(rank, int)
            or rank <= 0
        )
        for rank in reference.per_query_first_relevant_rank.values()
    ):
        raise StructuralModelProbeError("reference per-query ranks mismatch")
    expected_metrics = _metrics_from_ranks(
        reference.per_query_first_relevant_rank
    )
    if reference.metrics != expected_metrics or any(
        metric.denominator != len(selection.cases)
        for metric in reference.metrics.values()
    ):
        raise StructuralModelProbeError("reference metrics are inconsistent")


def _validate_qdrant_usage(
    receipt: InferenceUsageReceipt,
    *,
    expected: set[str],
    stage: str,
) -> None:
    if set(receipt.model_tokens) != expected or any(
        value <= 0 for value in receipt.model_tokens.values()
    ):
        raise StructuralModelProbeError(
            f"Qdrant {stage} model usage mismatch"
        )


def _validate_probe_vectors(
    transport: StructuralQdrantTransport,
    records: Sequence[StructuralRecord],
) -> int:
    expected = {record.record_id: record for record in records}
    observed: set[str] = set()
    for id_batch in _batches(tuple(expected), _PROBE_BATCH_SIZE):
        try:
            rows = transport.client.retrieve(
                collection_name=transport.contract.collection_name,
                ids=list(id_batch),
                with_payload=True,
                with_vectors=[
                    transport.contract.dense_vector_name,
                    transport.contract.sparse_vector_name,
                ],
                timeout=int(transport.contract.timeout_seconds),
            )
        except Exception as error:
            raise StructuralModelProbeError(
                f"Qdrant probe vector readback failed ({type(error).__name__})"
            ) from error
        if not isinstance(rows, list):
            raise StructuralModelProbeError("Qdrant probe readback is malformed")
        for row in rows:
            record_id = str(getattr(row, "id", ""))
            record = expected.get(record_id)
            if record is None or record_id in observed:
                raise StructuralModelProbeError(
                    "Qdrant probe record identity mismatch"
                )
            if getattr(row, "payload", None) != point_payload(record):
                raise StructuralModelProbeError(
                    "Qdrant probe payload hash or provenance mismatch"
                )
            vectors = getattr(row, "vector", None)
            if not isinstance(vectors, Mapping):
                raise StructuralModelProbeError(
                    "Qdrant probe vectors are missing"
                )
            _validate_dense_vector(
                vectors.get(transport.contract.dense_vector_name),
                stage="Qdrant probe",
            )
            sparse = vectors.get(transport.contract.sparse_vector_name)
            indices = (
                getattr(sparse, "indices", None)
                if sparse is not None
                else None
            )
            values = (
                getattr(sparse, "values", None)
                if sparse is not None
                else None
            )
            if (
                not isinstance(indices, list)
                or not isinstance(values, list)
                or not indices
                or len(indices) != len(values)
                or any(
                    isinstance(index, bool)
                    or not isinstance(index, int)
                    or index < 0
                    for index in indices
                )
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    for value in values
                )
            ):
                raise StructuralModelProbeError(
                    "Qdrant probe sparse vector is malformed"
                )
            observed.add(record_id)
    if observed != set(expected):
        raise StructuralModelProbeError("Qdrant probe records are missing")
    return len(observed)


def _validate_live_probe_schema(
    transport: StructuralQdrantTransport,
    probe: StructuralModelProbeInput,
    *,
    expected_points_count: int | None,
) -> None:
    try:
        readback = transport.client.get_collection(
            transport.contract.collection_name
        )
    except Exception as error:
        raise StructuralModelProbeError(
            f"Qdrant probe schema readback failed ({type(error).__name__})"
        ) from error
    try:
        _validate_collection_readback(
            readback,
            contract=transport.contract,
            shard_number=probe.plan.capacity.shard_count,
            expected_points_count=expected_points_count,
        )
    except Exception as error:
        raise StructuralModelProbeError(
            "Qdrant probe collection schema mismatch"
        ) from error
    if expected_points_count is None:
        points_count = getattr(readback, "points_count", None)
        if (
            isinstance(points_count, bool)
            or not isinstance(points_count, int)
            or points_count < 0
            or points_count > len(probe.selection.records)
        ):
            raise StructuralModelProbeError(
                "Qdrant probe collection contains unexpected points"
            )


def _qdrant_gold_ranks(
    transport: StructuralQdrantTransport,
    selection: StructuralProbeSelection,
    usage: dict[str, int],
) -> tuple[dict[str, int | None], dict[str, int | None]]:
    document_result: dict[str, int | None] = {}
    structural_result: dict[str, int | None] = {}
    for case in selection.cases:
        hits, receipt = transport.query_with_usage(
            document=dense_query_document(case.question, transport.contract),
            using=transport.contract.dense_vector_name,
            limit=10,
        )
        _validate_qdrant_usage(
            receipt,
            expected={transport.contract.dense_model},
            stage="query",
        )
        _merge_usage(usage, receipt.model_tokens)
        required = _required_verified(case)
        required_document_ids = {
            document_id
            for document_id in (
                _positive_document_id(label.document_id) for label in required
            )
            if document_id is not None
        }
        first_document_rank: int | None = None
        first_structural_rank: int | None = None
        for rank, hit in enumerate(hits, start=1):
            candidate = _candidate_from_payload(getattr(hit, "payload", None))
            if (
                first_document_rank is None
                and candidate.document_id in required_document_ids
            ):
                first_document_rank = rank
            if first_structural_rank is None and any(
                matches_required_level(label, candidate) for label in required
            ):
                first_structural_rank = rank
            if first_document_rank is not None and first_structural_rank is not None:
                break
        document_result[case.case_id] = first_document_rank
        structural_result[case.case_id] = first_structural_rank
    return document_result, structural_result


def _qdrant_canary_ranks(
    transport: StructuralQdrantTransport,
    canaries: Sequence[StructuralCanary],
    usage: dict[str, int],
) -> dict[str, int | None]:
    result: dict[str, int | None] = {}
    for canary in canaries:
        hits, receipt = transport.query_with_usage(
            document=dense_query_document(canary.query, transport.contract),
            using=transport.contract.dense_vector_name,
            limit=10,
        )
        _validate_qdrant_usage(
            receipt,
            expected={transport.contract.dense_model},
            stage="canary query",
        )
        _merge_usage(usage, receipt.model_tokens)
        first_rank: int | None = None
        for rank, hit in enumerate(hits, start=1):
            candidate = _candidate_from_payload(getattr(hit, "payload", None))
            if candidate.document_id == canary.document_id:
                first_rank = rank
                break
        result[canary.query_id] = first_rank
    return result


def _cosine_first_relevant_ranks(
    selection: StructuralProbeSelection,
    *,
    query_vectors: Sequence[Sequence[float]],
    passage_vectors: Sequence[Sequence[float]],
) -> dict[str, int | None]:
    if len(query_vectors) != len(selection.cases) or len(passage_vectors) != len(
        selection.records
    ):
        raise StructuralModelProbeError("reference vector denominator mismatch")
    result: dict[str, int | None] = {}
    for case, query in zip(selection.cases, query_vectors, strict=True):
        ranked = sorted(
            zip(selection.records, passage_vectors, strict=True),
            key=lambda item: (
                -_cosine(query, item[1]),
                item[0].record_id,
            ),
        )
        required = _required_verified(case)
        first_rank = next(
            (
                rank
                for rank, (record, _vector) in enumerate(ranked, start=1)
                if any(
                    matches_required_level(label, _candidate_from_record(record))
                    for label in required
                )
            ),
            None,
        )
        result[case.case_id] = first_rank
    return result


def _metrics_from_ranks(ranks: Mapping[str, int | None]) -> dict[str, ProbeMetric]:
    denominator = len(ranks)
    if denominator <= 0:
        raise StructuralModelProbeError("probe metric denominator is empty")
    recall_1 = sum(rank == 1 for rank in ranks.values())
    recall_3 = sum(rank is not None and rank <= 3 for rank in ranks.values())
    reciprocal = sum(
        0.0 if rank is None else 1.0 / rank for rank in ranks.values()
    )
    return {
        "recall_at_1": ProbeMetric(
            numerator=recall_1,
            denominator=denominator,
            value=recall_1 / denominator,
        ),
        "recall_at_3": ProbeMetric(
            numerator=recall_3,
            denominator=denominator,
            value=recall_3 / denominator,
        ),
        "mrr": ProbeMetric(
            numerator=reciprocal,
            denominator=denominator,
            value=reciprocal / denominator,
        ),
    }


def _zero_metrics(denominator: int) -> dict[str, ProbeMetric]:
    return {
        name: ProbeMetric(
            numerator=0,
            denominator=denominator,
            value=0 if denominator else None,
        )
        for name in ("recall_at_1", "recall_at_3", "mrr")
    }


def _canary_metrics_from_ranks(
    ranks: Mapping[str, int | None],
) -> dict[str, ProbeMetric]:
    denominator = len(ranks)
    values = {
        "document_recall_at_1": sum(rank == 1 for rank in ranks.values()),
        "document_recall_at_3": sum(
            rank is not None and rank <= 3 for rank in ranks.values()
        ),
        "document_recall_at_10": sum(
            rank is not None and rank <= 10 for rank in ranks.values()
        ),
    }
    return {
        name: ProbeMetric(
            numerator=numerator,
            denominator=denominator,
            value=(numerator / denominator if denominator else None),
        )
        for name, numerator in values.items()
    }


def _rank_metrics_at_10(
    ranks: Mapping[str, int | None],
) -> dict[str, ProbeMetric]:
    denominator = len(ranks)
    reciprocal = sum(
        0.0 if rank is None else 1.0 / rank for rank in ranks.values()
    )
    numerators: dict[str, float] = {
        "recall_at_1": sum(rank == 1 for rank in ranks.values()),
        "recall_at_3": sum(
            rank is not None and rank <= 3 for rank in ranks.values()
        ),
        "recall_at_10": sum(
            rank is not None and rank <= 10 for rank in ranks.values()
        ),
        "mrr": reciprocal,
    }
    return {
        name: ProbeMetric(
            numerator=numerator,
            denominator=denominator,
            value=(numerator / denominator if denominator else None),
        )
        for name, numerator in numerators.items()
    }


def decide_model_probe_acceptance(
    *,
    gold_document_recall_at_10: float | None,
    gold_structural_recall_at_10: float | None,
    canary_document_recall_at_10: float | None,
    technical_error_count: int,
) -> Literal[
    "PASS_MODEL_PROBE",
    "FAIL_QUALITY",
    "BLOCKED_TECHNICAL",
    "BLOCKED_SCOPE",
]:
    if technical_error_count:
        return "BLOCKED_TECHNICAL"
    values = (
        gold_document_recall_at_10,
        gold_structural_recall_at_10,
        canary_document_recall_at_10,
    )
    if any(value is None for value in values):
        return "BLOCKED_SCOPE"
    if (
        gold_document_recall_at_10 == 1.0
        and gold_structural_recall_at_10 >= 0.95
        and canary_document_recall_at_10 >= 0.90
    ):
        return "PASS_MODEL_PROBE"
    return "FAIL_QUALITY"


def _coverage_metric(selection: StructuralProbeSelection) -> ProbeMetric:
    numerator = len(selection.cases)
    denominator = numerator + len(selection.skipped_cases)
    return ProbeMetric(
        numerator=numerator,
        denominator=denominator,
        value=(numerator / denominator if denominator else None),
    )


def _validate_comparable_denominator(
    candidate: Mapping[str, ProbeMetric],
    reference: Mapping[str, ProbeMetric],
) -> None:
    if set(candidate) != set(reference) or any(
        candidate[name].denominator != reference[name].denominator
        for name in candidate
    ):
        raise StructuralModelProbeError("candidate/reference denominator mismatch")


def _passes_quality(
    candidate: Mapping[str, ProbeMetric],
    reference: Mapping[str, ProbeMetric],
) -> bool:
    return (
        candidate["recall_at_1"].value
        >= max(0.975, reference["recall_at_1"].value)
        and candidate["recall_at_3"].value == 1.0
        and candidate["recall_at_3"].value
        >= reference["recall_at_3"].value
        and candidate["mrr"].value
        >= max(0.9833, reference["mrr"].value)
    )


def _candidate_from_record(record: StructuralRecord) -> CandidateChunk:
    return CandidateChunk(
        document_id=record.document_id,
        document_number=record.document_number,
        title=record.title,
        source_url=record.source_url,
        citation=record.citation,
        article=record.article,
        clause=record.clause,
        text=record.body,
        token_count=record.token_count,
    )


def _candidate_from_payload(payload: object) -> CandidateChunk:
    if not isinstance(payload, Mapping):
        raise StructuralModelProbeError("Qdrant query payload is missing")
    try:
        return CandidateChunk(
            document_id=payload["document_id"],
            document_number=payload["document_number"],
            title=payload["title"],
            source_url=payload["source_url"],
            citation=payload["citation"],
            article=payload.get("article"),
            clause=payload.get("clause"),
            text=payload["body"],
            token_count=payload["token_count"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise StructuralModelProbeError(
            "Qdrant query payload contract mismatch"
        ) from error


def _required_verified(case: GoldenCase) -> tuple[GoldEvidence, ...]:
    return tuple(
        label
        for label in case.gold_evidence
        if label.required and label.status == "verified"
    )


def _validate_dense_vector(vector: object, *, stage: str) -> None:
    if (
        not isinstance(vector, list)
        or len(vector) != _REFERENCE_DIMENSION
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in vector
        )
    ):
        raise StructuralModelProbeError(
            f"{stage} dense vector is not finite 1024-dimensional float data"
        )


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise StructuralModelProbeError("reference embedding has zero norm")
    return dot / (left_norm * right_norm)


def _merge_usage(target: dict[str, int], addition: Mapping[str, int]) -> None:
    for model_name, tokens in addition.items():
        target[model_name] = target.get(model_name, 0) + tokens


def _positive_document_id(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _batches(values: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
