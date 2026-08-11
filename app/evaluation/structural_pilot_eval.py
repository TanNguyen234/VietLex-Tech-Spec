"""Deterministic, retrieval-only evaluation for the opt-in structural pilot."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.evaluation.artifact_io import write_immutable_json
from app.evaluation.provenance import GitProvenance, collect_git_provenance
from app.evaluation.retrieval_metrics import (
    aggregate_retrieval_metrics,
    calculate_case_retrieval_metrics,
    match_gold_to_stage_candidate,
)
from app.evaluation.run_manifest import (
    calculate_configuration_fingerprint,
    prepare_run_directory,
)
from app.evaluation.schemas import (
    EvidenceStatus,
    GoldenCase,
    RequiredLevel,
    RetrievalStageCapacities,
    RetrievalStageTrace,
    StageCandidate,
)
from app.services.structural_retrieval import (
    StructuralCandidate,
    StructuralRetrievalOutcome,
    StructuralRetrievalTrace,
    StructuralSourceHit,
    StructuralTechnicalError,
)


_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_METRIC_STAGE_ALIASES = {
    "pinecone_hits": "dense_hits",
    "fts_hits": "bm25_hits",
    "merged_document_candidates": "fused_hits",
    "resolved_document_candidates": "fused_hits",
    "structural_chunks_generated": "fused_hits",
    "locally_selected_chunks": "reranker_input",
    "reranker_input_chunks": "reranker_input",
    "reranker_output_chunks": "reranker_output",
    "final_evidence_chunks": "final_hits",
}
_TECHNICAL_ERROR_STAGES = (
    "dense",
    "bm25",
    "exact_fts",
    "exact_remote",
    "fusion",
    "reranker",
    "reranker_primary",
    "retrieval",
    "preflight",
)


class StructuralEvaluationError(RuntimeError):
    """Raised when benchmark evidence is malformed or cannot be persisted."""


class StructuralEvaluationBinding(BaseModel):
    """Exact immutable inputs required before any provider is constructed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_revision: str = Field(min_length=1)
    dataset_sha256: str = Field(pattern=_SHA256_PATTERN)
    sidecar_sha256: str = Field(pattern=_SHA256_PATTERN)
    gold_policy: Literal["all-required-verified"]
    selected_case_ids_sha256: str = Field(pattern=_SHA256_PATTERN)
    source_state_sha256: str = Field(pattern=_SHA256_PATTERN)
    collection_name: Literal["vietlex-legal-rag-v2-pilot"]
    plan_sha256: str = Field(pattern=_SHA256_PATTERN)
    creation_receipt_sha256: str = Field(pattern=_SHA256_PATTERN)
    probe_report_sha256: str = Field(pattern=_SHA256_PATTERN)
    upload_report_sha256: str = Field(pattern=_SHA256_PATTERN)
    finalize_receipt_sha256: str = Field(pattern=_SHA256_PATTERN)
    verify_receipt_sha256: str = Field(pattern=_SHA256_PATTERN)
    p2_baseline_sha256: str = Field(pattern=_SHA256_PATTERN)
    dense_vector_name: Literal["dense"] = "dense"
    sparse_vector_name: Literal["bm25"] = "bm25"
    dense_model: Literal["Qwen/Qwen3-Embedding-0.6B"] = (
        "Qwen/Qwen3-Embedding-0.6B"
    )
    dense_model_options: dict[str, object] = Field(default_factory=dict)
    sparse_model: Literal["qdrant/bm25"] = "qdrant/bm25"
    sparse_model_options: dict[str, object] = Field(default_factory=dict)
    dense_size: Literal[1024] = 1024
    query_instruction_version: Literal["vietlex-vn-legal-retrieval-v1"] = (
        "vietlex-vn-legal-retrieval-v1"
    )
    query_instruction: str = Field(min_length=1)
    dense_top_k: int = Field(gt=0)
    bm25_top_k: int = Field(gt=0)
    fused_limit: int = Field(gt=0)
    rrf_k: int = Field(gt=0)
    per_document_limit: int = Field(gt=0)


class StructuralEvaluationTrace(BaseModel):
    """Raw structural names; legacy metric aliases are never serialized here."""

    model_config = ConfigDict(extra="forbid")

    dense_hits: list[StageCandidate] = Field(default_factory=list)
    bm25_hits: list[StageCandidate] = Field(default_factory=list)
    exact_hits: list[StageCandidate] = Field(default_factory=list)
    exact_document_ids: list[int] = Field(default_factory=list)
    fused_hits: list[StageCandidate] = Field(default_factory=list)
    reranker_input: list[StageCandidate] = Field(default_factory=list)
    reranker_output: list[StageCandidate] = Field(default_factory=list)
    final_hits: list[StageCandidate] = Field(default_factory=list)


class P2BaselineValidation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_document_recall_at_24: float = Field(
        ge=0,
        le=1,
        allow_inf_nan=False,
    )
    scope_errors: tuple[str, ...] = ()


class PilotEvaluationRun(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    run_id: str
    run_dir: Path
    acceptance: Literal[
        "PASS_PILOT",
        "FAIL_QUALITY",
        "BLOCKED_TECHNICAL",
        "BLOCKED_SCOPE",
    ]


class _StructuralRetriever(Protocol):
    async def retrieve(self, query: str) -> StructuralRetrievalOutcome: ...


@dataclass(frozen=True)
class _ExecutedCase:
    case: GoldenCase
    outcome: StructuralRetrievalOutcome
    trace: StructuralEvaluationTrace
    metrics: dict[str, Any]
    provider_usage_observation_complete: bool


def _stage_candidate(
    candidate: StructuralCandidate,
    *,
    source: str,
    score: float | None = None,
) -> StageCandidate:
    return StageCandidate(
        document_id=candidate.document_id,
        document_number=candidate.document_number,
        title=candidate.title,
        source_url=candidate.source_url,
        citation=candidate.citation,
        article=candidate.article,
        clause=candidate.clause,
        text=candidate.body,
        score=score,
        source=source,
    )


def _source_candidates(
    hits: Sequence[StructuralSourceHit],
    source: str,
) -> list[StageCandidate]:
    return [
        _stage_candidate(hit.candidate, source=source, score=hit.source_score)
        for hit in hits
    ]


def structural_evaluation_trace(
    trace: StructuralRetrievalTrace,
) -> StructuralEvaluationTrace:
    return StructuralEvaluationTrace(
        dense_hits=_source_candidates(trace.dense_hits, "dense"),
        bm25_hits=_source_candidates(trace.bm25_hits, "bm25"),
        exact_hits=_source_candidates(trace.exact_hits, "exact"),
        exact_document_ids=list(trace.exact_document_ids),
        fused_hits=[
            _stage_candidate(row, source="fused", score=row.fused_score)
            for row in trace.fused_hits
        ],
        reranker_input=[
            _stage_candidate(row, source="reranker_input", score=row.fused_score)
            for row in trace.reranker_input
        ],
        reranker_output=[
            _stage_candidate(
                row,
                source="reranker_output",
                score=row.reranker_score,
            )
            for row in trace.reranker_output
        ],
        final_hits=[
            _stage_candidate(row, source="final", score=row.reranker_score)
            for row in trace.final_hits
        ],
    )


def to_metric_v3_trace(
    trace: StructuralEvaluationTrace,
) -> RetrievalStageTrace:
    """The sole compatibility boundary with metric-v3 legacy field names."""
    return RetrievalStageTrace(
        pinecone_hits=trace.dense_hits,
        fts_hits=trace.bm25_hits,
        merged_document_candidates=trace.fused_hits,
        resolved_document_candidates=trace.fused_hits,
        structural_chunks_generated=trace.fused_hits,
        locally_selected_chunks=trace.reranker_input,
        reranker_input_chunks=trace.reranker_input,
        reranker_output_chunks=trace.reranker_output,
        final_evidence_chunks=trace.final_hits,
    )


def _baseline_metric(profile: Mapping[str, Any]) -> float:
    try:
        metric = profile["aggregate_metrics"]["stages"][
            "source_retrieval_metrics"
        ]["recall"]["document"]["24"]
        value = metric.get("micro", metric.get("value"))
    except (KeyError, TypeError, AttributeError) as error:
        raise StructuralEvaluationError(
            "P2 source Document Recall@24 is missing"
        ) from error
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise StructuralEvaluationError(
            "P2 source Document Recall@24 is malformed"
        )
    return float(value)


def validate_p2_baseline(
    comparison: Mapping[str, Any],
    binding: StructuralEvaluationBinding,
) -> P2BaselineValidation:
    """Compare exact denominator provenance before permitting execution."""
    shared = comparison.get("shared_provenance")
    if not isinstance(shared, Mapping):
        raise StructuralEvaluationError("P2 shared provenance is missing")
    expected = {
        "dataset_revision": binding.dataset_revision,
        "dataset_sha256": binding.dataset_sha256,
        "gold_label_sidecar_sha256": binding.sidecar_sha256,
        "gold_policy": binding.gold_policy,
        "selected_case_ids_sha256": binding.selected_case_ids_sha256,
    }
    scope_errors = tuple(
        f"{field_name}_mismatch"
        for field_name, value in expected.items()
        if shared.get(field_name) != value
    )
    profiles = comparison.get("profiles")
    if not isinstance(profiles, Mapping) or not profiles:
        raise StructuralEvaluationError("P2 profiles are missing")
    values = {_baseline_metric(profile) for profile in profiles.values()}
    if len(values) != 1:
        raise StructuralEvaluationError(
            "P2 profiles disagree on source Document Recall@24"
        )
    return P2BaselineValidation(
        source_document_recall_at_24=next(iter(values)),
        scope_errors=scope_errors,
    )


def decide_pilot_acceptance(
    report: Mapping[str, Any] | BaseModel,
) -> Literal[
    "PASS_PILOT",
    "FAIL_QUALITY",
    "BLOCKED_TECHNICAL",
    "BLOCKED_SCOPE",
]:
    values = (
        report.model_dump(mode="python")
        if isinstance(report, BaseModel)
        else dict(report)
    )
    if int(values.get("scope_error_count", 0)):
        return "BLOCKED_SCOPE"
    if int(values.get("technical_error_count", 0)) or bool(
        values.get("provenance_drift", False)
    ):
        return "BLOCKED_TECHNICAL"
    fused_document = float(values.get("fused_document_recall_at_24", 0.0))
    fused_article = float(values.get("fused_article_recall_at_24", 0.0))
    fused_clause = float(values.get("fused_clause_recall_at_24", 0.0))
    all_required = float(values.get("all_required_coverage", 0.0))
    no_candidate_rate = float(values.get("no_candidate_rate", 0.0))
    retrieval_error_rate = float(values.get("retrieval_error_rate", 0.0))
    reranker_error_rate = float(values.get("reranker_error_rate", 0.0))
    if (
        fused_document == 1.0
        and fused_article >= 0.95
        and fused_clause >= 0.90
        and all_required >= 0.95
        and no_candidate_rate == 0.0
        and retrieval_error_rate == 0.0
        and reranker_error_rate == 0.0
    ):
        return "PASS_PILOT"
    return "FAIL_QUALITY"


def _fused_recall_at_24(
    rows: Sequence[_ExecutedCase],
    level: Literal["document", "article", "clause"],
) -> dict[str, int | float | None]:
    numerator = 0
    denominator = 0
    for row in rows:
        required = [
            item
            for item in row.case.gold_evidence
            if item.required and item.status == EvidenceStatus.VERIFIED
        ]
        if level == "article":
            required = [
                item
                for item in required
                if item.required_level in {RequiredLevel.ARTICLE, RequiredLevel.CLAUSE}
            ]
        elif level == "clause":
            required = [
                item
                for item in required
                if item.required_level == RequiredLevel.CLAUSE
            ]
        denominator += len(required)
        for item in required:
            matched = any(
                {
                    "document": result[0],
                    "article": result[1],
                    "clause": result[2],
                }[level]
                for candidate in row.trace.fused_hits[:24]
                for result in [match_gold_to_stage_candidate(item, candidate)]
            )
            numerator += int(matched)
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": round(numerator / denominator, 4) if denominator else None,
    }


def _stage_recall(
    rows: Sequence[_ExecutedCase],
    *,
    stage: Literal["reranker_input", "reranker_output"],
    level: Literal["document", "article", "clause"],
) -> dict[str, int | float | None]:
    numerator = 0
    denominator = 0
    for row in rows:
        required = [
            item
            for item in row.case.gold_evidence
            if item.required and item.status == EvidenceStatus.VERIFIED
        ]
        if level == "article":
            required = [
                item
                for item in required
                if item.required_level in {RequiredLevel.ARTICLE, RequiredLevel.CLAUSE}
            ]
        elif level == "clause":
            required = [
                item
                for item in required
                if item.required_level == RequiredLevel.CLAUSE
            ]
        candidates = getattr(row.trace, stage)
        denominator += len(required)
        for item in required:
            matched = any(
                {
                    "document": result[0],
                    "article": result[1],
                    "clause": result[2],
                }[level]
                for candidate in candidates
                for result in [match_gold_to_stage_candidate(item, candidate)]
            )
            numerator += int(matched)
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": round(numerator / denominator, 4) if denominator else None,
    }


def _reranker_contribution(
    rows: Sequence[_ExecutedCase],
) -> dict[str, dict[str, Any]]:
    contribution: dict[str, dict[str, Any]] = {}
    for level in ("document", "article", "clause"):
        before = _stage_recall(rows, stage="reranker_input", level=level)
        after = _stage_recall(rows, stage="reranker_output", level=level)
        before_value = before["value"]
        after_value = after["value"]
        delta = (
            round(float(after_value) - float(before_value), 4)
            if before_value is not None and after_value is not None
            else None
        )
        contribution[level] = {
            "input": before,
            "output": after,
            "delta": delta,
        }
    return contribution


def _latency_summary(rows: Sequence[_ExecutedCase]) -> dict[str, Any]:
    values: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for stage, value in row.outcome.latency.items():
            values[stage].append(value)
    return {
        stage: {
            "count": len(stage_values),
            "total_seconds": round(sum(stage_values), 6),
            "mean_seconds": round(sum(stage_values) / len(stage_values), 6),
            "max_seconds": round(max(stage_values), 6),
        }
        for stage, stage_values in sorted(values.items())
    }


def _technical_error_summary(rows: Sequence[_ExecutedCase]) -> dict[str, int]:
    counts: Counter[str] = Counter(
        {stage: 0 for stage in _TECHNICAL_ERROR_STAGES}
    )
    for row in rows:
        counts.update(row.outcome.technical_errors.keys())
    counts["total"] = sum(
        count for stage, count in counts.items() if stage != "total"
    )
    return dict(sorted(counts.items()))


def _is_reranker_error(stage: str) -> bool:
    return stage == "reranker" or stage.startswith("reranker_")


def _operational_error_rate(
    rows: Sequence[_ExecutedCase],
    *,
    reranker: bool,
) -> dict[str, Any]:
    numerator = sum(
        any(_is_reranker_error(stage) is reranker for stage in row.outcome.technical_errors)
        for row in rows
    )
    denominator = len(rows)
    value = round(numerator / denominator, 4) if denominator else None
    return {
        "macro": value,
        "micro": value,
        "numerator": numerator,
        "denominator": denominator,
        "scored_cases": denominator,
        "skipped_cases": 0,
        "skip_reasons": {},
        "reason": None if denominator else "no_cases",
    }


def _provider_usage(rows: Sequence[_ExecutedCase]) -> dict[str, int]:
    usage: Counter[str] = Counter()
    for row in rows:
        usage.update(row.outcome.provider_usage)
    return dict(sorted(usage.items()))


def _configuration(binding: StructuralEvaluationBinding) -> dict[str, Any]:
    return {
        "eval_mode": "retrieval-only",
        "judge_mode": "none",
        "generation_mode": "off",
        "guardrail_mode": "off",
        "rewrite_mode": "off",
        "metric_version": "3.0.0",
        "metric_stage_aliases": _METRIC_STAGE_ALIASES,
        "collection_name": binding.collection_name,
        "dense_vector": {
            "name": binding.dense_vector_name,
            "dimension": binding.dense_size,
            "distance": "cosine",
            "model": binding.dense_model,
            "model_options": binding.dense_model_options,
        },
        "sparse_vector": {
            "name": binding.sparse_vector_name,
            "modifier": "idf",
            "model": binding.sparse_model,
            "model_options": binding.sparse_model_options,
        },
        "query_instruction_version": binding.query_instruction_version,
        "query_instruction": binding.query_instruction,
        "dense_top_k": binding.dense_top_k,
        "bm25_top_k": binding.bm25_top_k,
        "fused_limit": binding.fused_limit,
        "rrf_k": binding.rrf_k,
        "per_document_limit": binding.per_document_limit,
        "comparison_limit": 24,
    }


async def run_structural_pilot_evaluation(
    cases: Sequence[GoldenCase],
    retriever: _StructuralRetriever,
    output_root: Path,
    *,
    run_id: str,
    binding: StructuralEvaluationBinding,
    p2_source_document_recall_at_24: float,
    skipped_cases: Mapping[str, str] | None = None,
    provenance: GitProvenance | None = None,
    scope_errors: Sequence[str] = (),
    technical_preflight_errors: Sequence[str] = (),
    command: str = "structural pilot evaluation",
) -> PilotEvaluationRun:
    """Execute online retrieval, then compute/write all evidence offline."""
    if (
        isinstance(p2_source_document_recall_at_24, bool)
        or not isinstance(p2_source_document_recall_at_24, (int, float))
        or not 0 <= p2_source_document_recall_at_24 <= 1
    ):
        raise StructuralEvaluationError("P2 baseline metric is malformed")
    if len({case.case_id for case in cases}) != len(cases):
        raise StructuralEvaluationError("evaluation case IDs are not unique")
    skipped = dict(sorted((skipped_cases or {}).items()))
    if set(skipped) & {case.case_id for case in cases}:
        raise StructuralEvaluationError("included and skipped cases overlap")
    git = provenance or collect_git_provenance()
    provenance_drift = (
        git.status != "ok"
        or git.source_state_sha256 != binding.source_state_sha256
    )
    run_dir = prepare_run_directory(Path(output_root), run_id)
    executed: list[_ExecutedCase] = []
    if not scope_errors and not provenance_drift and not technical_preflight_errors:
        for case in cases:
            started = time.perf_counter()
            provider_usage_observation_complete = True
            try:
                outcome = await retriever.retrieve(case.question)
            except Exception as error:
                provider_usage_observation_complete = False
                outcome = StructuralRetrievalOutcome(
                    status="retrieval_error",
                    evidence=[],
                    trace=StructuralRetrievalTrace(),
                    latency={"total": time.perf_counter() - started},
                    technical_errors={
                        "retrieval": StructuralTechnicalError(
                            stage="retrieval",
                            category=type(error).__name__,
                            error_type=type(error).__name__,
                            transient=isinstance(error, TimeoutError),
                        )
                    },
                    provider_usage={},
                )
            trace = structural_evaluation_trace(outcome.trace)
            metrics = calculate_case_retrieval_metrics(
                case.gold_evidence,
                trace.final_hits,
                to_metric_v3_trace(trace),
                RetrievalStageCapacities(),
                status=outcome.status,
            )
            metrics["retrieval_technical_error"] = any(
                not _is_reranker_error(stage)
                for stage in outcome.technical_errors
            )
            metrics["reranker_technical_error"] = any(
                _is_reranker_error(stage)
                for stage in outcome.technical_errors
            )
            provider_usage_observation_complete = (
                provider_usage_observation_complete
                and not outcome.technical_errors
            )
            executed.append(
                _ExecutedCase(
                    case=case,
                    outcome=outcome,
                    trace=trace,
                    metrics=metrics,
                    provider_usage_observation_complete=(
                        provider_usage_observation_complete
                    ),
                )
            )

    raw_cases = [
        {
            "case_id": row.case.case_id,
            "question": row.case.question,
            "status": row.outcome.status,
            "trace": row.trace.model_dump(mode="json"),
            "latency": row.outcome.latency,
            "provider_usage": row.outcome.provider_usage,
            "provider_usage_observation_complete": (
                row.provider_usage_observation_complete
            ),
            "technical_errors": {
                key: value.model_dump(mode="json")
                for key, value in row.outcome.technical_errors.items()
            },
            "metrics": row.metrics,
        }
        for row in executed
    ]
    aggregate = aggregate_retrieval_metrics(
        [
            {"status": row.outcome.status, "metrics": row.metrics}
            for row in executed
        ]
    )
    aggregate["retrieval_technical_error_rate"] = _operational_error_rate(
        executed,
        reranker=False,
    )
    aggregate["reranker_technical_error_rate"] = _operational_error_rate(
        executed,
        reranker=True,
    )
    fused_document = _fused_recall_at_24(executed, "document")
    fused_article = _fused_recall_at_24(executed, "article")
    fused_clause = _fused_recall_at_24(executed, "clause")
    technical_errors = _technical_error_summary(executed)
    if technical_preflight_errors:
        technical_errors["preflight"] = len(technical_preflight_errors)
        technical_errors["total"] = technical_errors.get("total", 0) + len(
            technical_preflight_errors
        )
    acceptance_values = {
        "scope_error_count": len(scope_errors),
        "technical_error_count": technical_errors.get("total", 0),
        "provenance_drift": provenance_drift,
        "fused_document_recall_at_24": fused_document["value"] or 0.0,
        "p2_source_document_recall_at_24": p2_source_document_recall_at_24,
        "fused_article_recall_at_24": fused_article["value"] or 0.0,
        "fused_clause_recall_at_24": fused_clause["value"] or 0.0,
        "all_required_coverage": (
            aggregate["multi_hop_all_required"]["macro"] or 0.0
        ),
        "no_candidate_rate": aggregate["no_candidate_rate"]["macro"] or 0.0,
        "retrieval_error_rate": (
            aggregate["retrieval_technical_error_rate"]["macro"] or 0.0
        ),
        "reranker_error_rate": (
            aggregate["reranker_technical_error_rate"]["macro"] or 0.0
        ),
    }
    acceptance = decide_pilot_acceptance(acceptance_values)
    skipped_reason_counts = Counter(skipped.values())
    provider_usage_observation_complete = all(
        row.provider_usage_observation_complete for row in executed
    )
    case_statuses = {
        case_id: f"skipped:{reason}" for case_id, reason in skipped.items()
    }
    case_statuses.update(
        {row.case.case_id: row.outcome.status for row in executed}
    )
    if len(executed) != len(cases):
        blocked_status = (
            "blocked_scope"
            if scope_errors
            else "blocked_technical"
        )
        for case in cases:
            case_statuses.setdefault(case.case_id, blocked_status)
    case_statuses = dict(sorted(case_statuses.items()))
    configuration = _configuration(binding)
    report = {
        "schema_version": "1.0.0",
        "acceptance": acceptance,
        "production_cutover_authorized": False,
        "scope_errors": list(scope_errors),
        "technical_preflight_errors": list(technical_preflight_errors),
        "provenance_drift": provenance_drift,
        "coverage": {
            "selected_case_count": len(cases) + len(skipped),
            "scored_case_count": len(executed),
            "skipped_case_count": len(skipped),
            "value": (
                round(len(executed) / (len(cases) + len(skipped)), 4)
                if cases or skipped
                else None
            ),
            "skipped_cases": list(skipped),
            "skip_reasons": dict(sorted(skipped_reason_counts.items())),
        },
        "metrics": {
            "fused_document_recall_at_24": fused_document,
            "fused_article_recall_at_24": fused_article,
            "fused_clause_recall_at_24": fused_clause,
            "p2_source_document_recall_at_24": p2_source_document_recall_at_24,
            "metric_v3": aggregate,
        },
        "technical_errors": technical_errors,
        "latency": _latency_summary(executed),
        "provider_usage": _provider_usage(executed),
        "provider_usage_observation_complete": (
            provider_usage_observation_complete
        ),
        "metric_stage_aliases": _METRIC_STAGE_ALIASES,
        "reranker_contribution": _reranker_contribution(executed),
    }
    timestamp = datetime.now(timezone.utc).isoformat()
    manifest = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "utc_timestamp": timestamp,
        "command": command,
        "git": git.model_dump(mode="json"),
        **binding.model_dump(mode="json"),
        "selected_case_ids": list(case_statuses),
        "metric_version": "3.0.0",
        "configuration_fingerprint": calculate_configuration_fingerprint(
            configuration
        ),
        "provider_usage": _provider_usage(executed),
        "provider_usage_observation_complete": (
            provider_usage_observation_complete
        ),
        "case_statuses": case_statuses,
        "acceptance": acceptance,
    }
    raw = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "cases": raw_cases,
        "skipped_cases": skipped,
        "scope_errors": list(scope_errors),
        "technical_preflight_errors": list(technical_preflight_errors),
    }
    for name, payload in (
        ("manifest.json", manifest),
        ("configuration.json", configuration),
        ("raw_results.json", raw),
        ("report.json", report),
    ):
        write_immutable_json(run_dir / name, payload)
    return PilotEvaluationRun(
        run_id=run_id,
        run_dir=run_dir,
        acceptance=acceptance,
    )


def sha256_path(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StructuralEvaluationError(
            f"unable to load JSON artifact: {type(error).__name__}"
        ) from error
    if not isinstance(value, dict):
        raise StructuralEvaluationError("JSON artifact must be an object")
    return value
