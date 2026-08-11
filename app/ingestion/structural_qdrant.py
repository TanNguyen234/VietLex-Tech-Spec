"""Exact Qdrant Cloud Inference contract for the structural pilot."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator
from qdrant_client import QdrantClient, models

from app.config import Settings, system_ssl_context
from app.ingestion.structural_index import StructuralRecord


class StructuralQdrantError(ValueError):
    """Raised when the structural Qdrant contract is invalid."""


class StructuralProviderError(RuntimeError):
    """Typed, non-secret provider failure for observable evaluation."""

    def __init__(
        self,
        *,
        stage: str,
        category: str,
        message: str,
        transient: bool,
        attempts: int = 1,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.category = category
        self.transient = transient
        self.attempts = attempts


class InferenceUsageReceipt(BaseModel):
    """Acknowledgement and provider token evidence retained from raw APIs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["acknowledged", "completed"]
    elapsed_seconds: float | None = Field(default=None, ge=0)
    model_tokens: Mapping[str, int]
    attempts: int = Field(default=1, gt=0)

    @model_validator(mode="after")
    def freeze_model_tokens(self) -> Self:
        if not self.model_tokens or any(
            not isinstance(model, str)
            or not model
            or isinstance(tokens, bool)
            or not isinstance(tokens, int)
            or tokens <= 0
            for model, tokens in self.model_tokens.items()
        ):
            raise ValueError("model_tokens must contain positive token counts")
        object.__setattr__(
            self,
            "model_tokens",
            MappingProxyType(dict(self.model_tokens)),
        )
        return self

    @field_serializer("model_tokens")
    def serialize_model_tokens(
        self,
        value: Mapping[str, int],
    ) -> dict[str, int]:
        return dict(value)


class StructuralQdrantContract(BaseModel):
    """Immutable collection, inference, and throughput contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    collection_name: str
    dense_vector_name: str
    sparse_vector_name: str
    dense_model: str
    dense_model_options: Mapping[str, object]
    sparse_model: str
    sparse_model_options: Mapping[str, object]
    dense_size: int
    document_text_version: str
    query_instruction_version: str
    query_instruction: str
    chunk_max_tokens: int
    chunk_overlap_tokens: int
    dense_top_k: int
    bm25_top_k: int
    fused_limit: int
    rrf_k: int
    per_document_limit: int
    timeout_seconds: float
    max_retries: int
    retry_base_seconds: float
    retry_max_seconds: float
    upload_batch_min: int
    upload_batch_max: int
    upload_max_workers: int
    upload_prefer_grpc: bool

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(
            collection_name=settings.STRUCTURAL_COLLECTION_NAME,
            dense_vector_name=settings.STRUCTURAL_DENSE_VECTOR_NAME,
            sparse_vector_name=settings.STRUCTURAL_SPARSE_VECTOR_NAME,
            dense_model=settings.STRUCTURAL_DENSE_MODEL,
            dense_model_options=dict(settings.STRUCTURAL_DENSE_MODEL_OPTIONS),
            sparse_model=settings.STRUCTURAL_SPARSE_MODEL,
            sparse_model_options=dict(settings.STRUCTURAL_SPARSE_MODEL_OPTIONS),
            dense_size=settings.STRUCTURAL_VECTOR_SIZE,
            document_text_version=settings.STRUCTURAL_DOCUMENT_TEXT_VERSION,
            query_instruction_version=(
                settings.STRUCTURAL_QUERY_INSTRUCTION_VERSION
            ),
            query_instruction=settings.STRUCTURAL_QUERY_INSTRUCTION,
            chunk_max_tokens=settings.STRUCTURAL_CHUNK_MAX_TOKENS,
            chunk_overlap_tokens=(
                settings.STRUCTURAL_CHUNK_OVERLAP_TOKENS
            ),
            dense_top_k=settings.STRUCTURAL_DENSE_TOP_K,
            bm25_top_k=settings.STRUCTURAL_BM25_TOP_K,
            fused_limit=settings.STRUCTURAL_FUSED_LIMIT,
            rrf_k=settings.STRUCTURAL_RRF_K,
            per_document_limit=settings.STRUCTURAL_PER_DOCUMENT_LIMIT,
            timeout_seconds=settings.STRUCTURAL_QDRANT_TIMEOUT_SECONDS,
            max_retries=settings.STRUCTURAL_QDRANT_MAX_RETRIES,
            retry_base_seconds=(
                settings.STRUCTURAL_QDRANT_RETRY_BASE_SECONDS
            ),
            retry_max_seconds=(
                settings.STRUCTURAL_QDRANT_RETRY_MAX_SECONDS
            ),
            upload_batch_min=settings.STRUCTURAL_UPLOAD_BATCH_MIN,
            upload_batch_max=settings.STRUCTURAL_UPLOAD_BATCH_MAX,
            upload_max_workers=settings.STRUCTURAL_UPLOAD_MAX_WORKERS,
            upload_prefer_grpc=settings.STRUCTURAL_UPLOAD_PREFER_GRPC,
        )

    @model_validator(mode="after")
    def validate_exact_contract(self) -> Self:
        exact_values = {
            "collection_name": "vietlex-legal-rag-v2-pilot",
            "dense_vector_name": "dense",
            "sparse_vector_name": "bm25",
            "dense_model": "Qwen/Qwen3-Embedding-0.6B",
            "sparse_model": "qdrant/bm25",
            "dense_size": 1024,
            "document_text_version": "vietlex-structural-document-v2",
            "query_instruction_version": "vietlex-vn-legal-retrieval-v1",
            "query_instruction": (
                "Given a Vietnamese legal question, retrieve relevant "
                "statutory provisions and preserve exact legal references."
            ),
            "chunk_max_tokens": 420,
            "chunk_overlap_tokens": 48,
        }
        labels = {
            "collection_name": "collection",
            "dense_vector_name": "dense vector",
            "sparse_vector_name": "sparse vector",
            "dense_model": "dense model",
            "sparse_model": "sparse model",
            "dense_size": "dense size must be 1024",
            "document_text_version": "document text version",
            "query_instruction_version": "instruction version",
            "query_instruction": "query instruction",
            "chunk_max_tokens": "chunk maximum",
            "chunk_overlap_tokens": "chunk overlap",
        }
        for field_name, expected in exact_values.items():
            if getattr(self, field_name) != expected:
                raise StructuralQdrantError(
                    f"{labels[field_name]} contract mismatch"
                )
        if not self.query_instruction.strip():
            raise StructuralQdrantError("query instruction must be nonblank")
        positive_values = (
            self.dense_top_k,
            self.bm25_top_k,
            self.fused_limit,
            self.rrf_k,
            self.per_document_limit,
            self.timeout_seconds,
            self.max_retries,
            self.retry_base_seconds,
            self.retry_max_seconds,
            self.upload_max_workers,
        )
        if any(value <= 0 for value in positive_values):
            raise StructuralQdrantError("structural tuning values must be positive")
        if (
            self.upload_batch_min < 64
            or self.upload_batch_max > 256
            or self.upload_batch_min > self.upload_batch_max
        ):
            raise StructuralQdrantError("upload batch range must stay within 64-256")
        if self.retry_base_seconds > self.retry_max_seconds:
            raise StructuralQdrantError("retry delay range is invalid")
        object.__setattr__(
            self,
            "dense_model_options",
            _freeze_mapping(self.dense_model_options),
        )
        object.__setattr__(
            self,
            "sparse_model_options",
            _freeze_mapping(self.sparse_model_options),
        )
        return self

    @field_serializer("dense_model_options", "sparse_model_options")
    def serialize_model_options(
        self,
        value: Mapping[str, object],
    ) -> dict[str, object]:
        return _thaw_mapping(value)


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    return value


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType(
        {key: _freeze_value(item) for key, item in value.items()}
    )


def _thaw_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _thaw_mapping(value)
    if isinstance(value, tuple):
        return [_thaw_value(item) for item in value]
    return value


def _thaw_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return {key: _thaw_value(item) for key, item in value.items()}


def build_structural_inference_text(record: StructuralRecord) -> str:
    """Build the exact versioned text sent to dense and BM25 inference."""
    structure = record.heading_path.strip() or record.citation.strip()
    fields = (
        ("Tiêu đề", record.title),
        ("Số văn bản", record.document_number),
        ("Loại văn bản", record.legal_type),
        ("Cấu trúc", structure),
        ("Trích dẫn", record.citation),
    )
    header = "\n".join(
        f"{name}: {' '.join(value.split())}"
        for name, value in fields
        if value.strip()
    )
    return f"{header}\nNội dung:\n{record.body}"


def structural_inference_text_sha256(record: StructuralRecord) -> str:
    return hashlib.sha256(
        build_structural_inference_text(record).encode("utf-8")
    ).hexdigest()


def point_payload(record: StructuralRecord) -> dict[str, object]:
    """Return the exact body and provenance payload stored in Qdrant."""
    return {
        "body": record.body,
        "document_id": record.document_id,
        "document_number": record.document_number,
        "title": record.title,
        "source_url": record.source_url,
        "legal_type": record.legal_type,
        "issuing_authority": record.issuing_authority,
        "issuance_date": record.issuance_date,
        "article": record.article,
        "clause": record.clause,
        "heading_path": record.heading_path,
        "citation": record.citation,
        "token_count": record.token_count,
        "dataset_revision": record.dataset_revision,
        "content_sha256": record.content_sha256,
        "chunk_sha256": record.chunk_sha256,
        "inference_text_sha256": structural_inference_text_sha256(record),
    }


def point_from_record(
    record: StructuralRecord,
    contract: StructuralQdrantContract,
) -> models.PointStruct:
    """Create one server-side dense and BM25 inference point."""
    inference_text = build_structural_inference_text(record)
    return models.PointStruct(
        id=record.record_id,
        vector={
            contract.dense_vector_name: models.Document(
                text=inference_text,
                model=contract.dense_model,
                options=_thaw_mapping(contract.dense_model_options),
            ),
            contract.sparse_vector_name: models.Document(
                text=inference_text,
                model=contract.sparse_model,
                options=_thaw_mapping(contract.sparse_model_options),
            ),
        },
        payload=point_payload(record),
    )


def _normalized_query(query: str) -> str:
    if not isinstance(query, str):
        raise StructuralQdrantError("query must be a string")
    normalized = " ".join(query.split())
    if not normalized:
        raise StructuralQdrantError("query must be nonblank")
    return normalized


def dense_query_document(
    query: str,
    contract: StructuralQdrantContract,
) -> models.Document:
    """Build the exact instruction-aware dense query input."""
    normalized = _normalized_query(query)
    return models.Document(
        text=f"Instruct: {contract.query_instruction}\nQuery:{normalized}",
        model=contract.dense_model,
        options=_thaw_mapping(contract.dense_model_options),
    )


def sparse_query_document(
    query: str,
    contract: StructuralQdrantContract,
) -> models.Document:
    """Build a raw normalized BM25 query with no dense instruction."""
    return models.Document(
        text=_normalized_query(query),
        model=contract.sparse_model,
        options=_thaw_mapping(contract.sparse_model_options),
    )


_TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_TRANSIENT_ERROR_NAMES = {
    "ConnectError",
    "ConnectTimeout",
    "ReadTimeout",
    "ResponseHandlingException",
    "TimeoutException",
}


def _is_transient_provider_error(error: Exception) -> bool:
    if isinstance(error, TimeoutError):
        return True
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        status_code = getattr(getattr(error, "response", None), "status_code", None)
    return (
        status_code in _TRANSIENT_STATUS_CODES
        or type(error).__name__ in _TRANSIENT_ERROR_NAMES
    )


def _status_text(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw).strip().casefold()


def _validated_usage_receipt(
    response: Any,
    *,
    expected_models: set[str],
    stage: str,
    update_operation: bool,
) -> InferenceUsageReceipt:
    if response is None:
        raise StructuralProviderError(
            stage=stage,
            category="invalid_response",
            message="Qdrant response is missing",
            transient=False,
        )
    raw_status = (
        getattr(getattr(response, "result", None), "status", None)
        if update_operation
        else getattr(response, "status", None)
    )
    status = _status_text(raw_status)
    if status == "ok":
        status = "completed"
    if status not in {"acknowledged", "completed"}:
        raise StructuralProviderError(
            stage=stage,
            category="invalid_status",
            message=f"Qdrant {stage} status is not acknowledged: {status or 'missing'}",
            transient=False,
        )

    inference = getattr(getattr(response, "usage", None), "inference", None)
    raw_models = getattr(inference, "models", None)
    if not isinstance(raw_models, dict) or not raw_models:
        raise StructuralProviderError(
            stage=stage,
            category="missing_inference_usage",
            message=f"Qdrant {stage} inference usage is missing",
            transient=False,
        )
    model_tokens: dict[str, int] = {}
    for model_name, usage in raw_models.items():
        tokens = getattr(usage, "tokens", None)
        if (
            not isinstance(model_name, str)
            or not model_name
            or isinstance(tokens, bool)
            or not isinstance(tokens, int)
            or tokens <= 0
        ):
            raise StructuralProviderError(
                stage=stage,
                category="invalid_inference_usage",
                message=f"Qdrant {stage} inference usage is malformed",
                transient=False,
            )
        model_tokens[model_name] = tokens
    if set(model_tokens) != expected_models:
        raise StructuralProviderError(
            stage=stage,
            category="model_usage_mismatch",
            message=f"Qdrant {stage} inference model usage mismatch",
            transient=False,
        )

    elapsed = getattr(response, "time", None)
    if elapsed is not None and (
        isinstance(elapsed, bool)
        or not isinstance(elapsed, (int, float))
        or elapsed < 0
    ):
        raise StructuralProviderError(
            stage=stage,
            category="invalid_response",
            message=f"Qdrant {stage} elapsed time is malformed",
            transient=False,
        )
    return InferenceUsageReceipt(
        status=status,
        elapsed_seconds=float(elapsed) if elapsed is not None else None,
        model_tokens=model_tokens,
    )


class StructuralQdrantTransport:
    """Raw public REST operations that retain top-level inference usage."""

    def __init__(
        self,
        client: QdrantClient,
        contract: StructuralQdrantContract,
    ) -> None:
        self.client = client
        self.contract = contract

    def upsert_with_usage(
        self,
        points: Sequence[models.PointStruct],
    ) -> InferenceUsageReceipt:
        normalized_points = list(points)
        if not normalized_points:
            raise StructuralQdrantError("upsert points must not be empty")
        try:
            response = self.client.http.points_api.upsert_points(
                collection_name=self.contract.collection_name,
                wait=True,
                timeout=int(self.contract.timeout_seconds),
                point_insert_operations=models.PointsList(
                    points=normalized_points
                ),
            )
            return _validated_usage_receipt(
                response,
                expected_models={
                    self.contract.dense_model,
                    self.contract.sparse_model,
                },
                stage="upsert",
                update_operation=True,
            )
        except StructuralProviderError:
            raise
        except Exception as error:
            raise StructuralProviderError(
                stage="upsert",
                category=type(error).__name__,
                message=f"Qdrant upsert failed: {type(error).__name__}",
                transient=_is_transient_provider_error(error),
            ) from error

    def query_with_usage(
        self,
        *,
        document: models.Document,
        using: str,
        limit: int,
        query_filter: models.Filter | None = None,
        with_vectors: bool = False,
    ) -> tuple[list[models.ScoredPoint], InferenceUsageReceipt]:
        expected_model = {
            self.contract.dense_vector_name: self.contract.dense_model,
            self.contract.sparse_vector_name: self.contract.sparse_model,
        }.get(using)
        if expected_model is None or document.model != expected_model:
            raise StructuralQdrantError("query vector/model contract mismatch")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise StructuralQdrantError("query limit must be positive")
        stage = f"query:{using}"
        try:
            response = self.client.http.search_api.query_points(
                collection_name=self.contract.collection_name,
                timeout=int(self.contract.timeout_seconds),
                query_request=models.QueryRequest(
                    query=document,
                    using=using,
                    filter=query_filter,
                    limit=limit,
                    with_payload=True,
                    with_vector=with_vectors,
                ),
            )
            receipt = _validated_usage_receipt(
                response,
                expected_models={expected_model},
                stage=stage,
                update_operation=False,
            )
            result = getattr(response, "result", None)
            points = getattr(result, "points", None)
            if not isinstance(points, list):
                raise StructuralProviderError(
                    stage=stage,
                    category="invalid_response",
                    message=f"Qdrant {stage} result is missing",
                    transient=False,
                )
            return points, receipt
        except StructuralProviderError:
            raise
        except Exception as error:
            raise StructuralProviderError(
                stage=stage,
                category=type(error).__name__,
                message=f"Qdrant {stage} failed: {type(error).__name__}",
                transient=_is_transient_provider_error(error),
            ) from error


def create_structural_qdrant_client(settings: Settings) -> QdrantClient:
    """Create the remote-only client without making a provider call."""
    return QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
        cloud_inference=True,
        prefer_grpc=settings.STRUCTURAL_UPLOAD_PREFER_GRPC,
        timeout=settings.STRUCTURAL_QDRANT_TIMEOUT_SECONDS,
        verify=system_ssl_context(),
        check_compatibility=False,
    )
