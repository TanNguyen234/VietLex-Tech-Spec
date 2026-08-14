"""Independent document-title canary evaluation for Pinecone structural P3."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.evaluation.structural_model_probe import ProbeMetric, StructuralCanary
from app.ingestion.structural_pinecone import PineconeStructuralContract


_SHA256 = r"^[0-9a-f]{64}$"


class PineconeCanaryReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    created_at_utc: datetime
    status: Literal["PASS_CANARY", "FAIL_CANARY", "BLOCKED_TECHNICAL"]
    index_name: Literal["llama-text-embed-v2-index"]
    namespace: Literal["national-primary-v2"]
    model: Literal["llama-text-embed-v2"]
    dimension: Literal[1024]
    dataset_sha256: str = Field(pattern=_SHA256)
    sidecar_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    upload_report_sha256: str = Field(pattern=_SHA256)
    verify_report_sha256: str = Field(pattern=_SHA256)
    source_state_sha256: str = Field(pattern=_SHA256)
    canaries: tuple[StructuralCanary, ...]
    metrics: dict[str, ProbeMetric]
    per_canary_first_relevant_rank: dict[str, int | None]
    technical_errors: dict[str, str]
    provider_usage: dict[str, int]
    provider_calls: int = Field(ge=0)
    top_k: Literal[10] = 10

    @model_validator(mode="after")
    def validate_report(self):
        ids = tuple(row.query_id for row in self.canaries)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("canary identities must be unique and sorted")
        if set(self.per_canary_first_relevant_rank) | set(
            self.technical_errors
        ) != set(ids) or set(self.per_canary_first_relevant_rank) & set(
            self.technical_errors
        ):
            raise ValueError("canary outcomes are incomplete")
        return self


def _metrics(ranks: Mapping[str, int | None]) -> dict[str, ProbeMetric]:
    denominator = len(ranks)
    numerators = {
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
            numerator=value,
            denominator=denominator,
            value=value / denominator if denominator else None,
        )
        for name, value in numerators.items()
    }


def _field(hit: object, name: str) -> object:
    if isinstance(hit, Mapping):
        return hit.get(name)
    return getattr(hit, name, None)


def evaluate_pinecone_canaries(
    index: object,
    canaries: Sequence[StructuralCanary],
    *,
    contract: PineconeStructuralContract,
    dataset_sha256: str,
    sidecar_sha256: str,
    plan_sha256: str,
    upload_report_sha256: str,
    verify_report_sha256: str,
    source_state_sha256: str,
) -> PineconeCanaryReport:
    ordered = tuple(sorted(canaries, key=lambda row: row.query_id))
    ranks: dict[str, int | None] = {}
    errors: dict[str, str] = {}
    usage: Counter[str] = Counter()
    calls = 0
    for canary in ordered:
        calls += 1
        try:
            response = index.search(
                namespace=contract.namespace,
                top_k=10,
                inputs={"text": canary.query},
                fields=["document_id"],
                timeout=60.0,
            )
            hits = getattr(getattr(response, "result", None), "hits", None)
            if not isinstance(hits, list) or len(hits) > 10:
                raise ValueError("malformed_hits")
            first_rank = None
            for rank, hit in enumerate(hits, start=1):
                fields = _field(hit, "fields")
                document_id = (
                    fields.get("document_id")
                    if isinstance(fields, Mapping)
                    else None
                )
                if (
                    isinstance(document_id, bool)
                    or not isinstance(document_id, int)
                    or document_id <= 0
                ):
                    raise ValueError("malformed_hits")
                if document_id == canary.document_id and first_rank is None:
                    first_rank = rank
            raw_usage = getattr(response, "usage", None)
            tokens = getattr(raw_usage, "embed_total_tokens", None)
            read_units = getattr(raw_usage, "read_units", None)
            if any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                for value in (tokens, read_units)
            ):
                raise ValueError("malformed_usage")
            usage[contract.model] += tokens
            usage["pinecone_read_units"] += read_units
            ranks[canary.query_id] = first_rank
        except Exception as error:
            category = str(error) if isinstance(error, ValueError) else type(error).__name__
            errors[canary.query_id] = category
    metrics = _metrics(ranks)
    recall = metrics["document_recall_at_10"].value
    status: Literal["PASS_CANARY", "FAIL_CANARY", "BLOCKED_TECHNICAL"]
    if errors:
        status = "BLOCKED_TECHNICAL"
    elif recall is not None and recall >= 0.90:
        status = "PASS_CANARY"
    else:
        status = "FAIL_CANARY"
    return PineconeCanaryReport(
        created_at_utc=datetime.now(timezone.utc),
        status=status,
        index_name=contract.index_name,
        namespace=contract.namespace,
        model=contract.model,
        dimension=contract.dimension,
        dataset_sha256=dataset_sha256,
        sidecar_sha256=sidecar_sha256,
        plan_sha256=plan_sha256,
        upload_report_sha256=upload_report_sha256,
        verify_report_sha256=verify_report_sha256,
        source_state_sha256=source_state_sha256,
        canaries=ordered,
        metrics=metrics,
        per_canary_first_relevant_rank=ranks,
        technical_errors=errors,
        provider_usage=dict(sorted(usage.items())),
        provider_calls=calls,
    )
