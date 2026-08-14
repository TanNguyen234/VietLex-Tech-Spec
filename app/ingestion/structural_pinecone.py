"""Isolated Pinecone-hosted structural index contract and resume state."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import islice
from pathlib import Path
from typing import Annotated, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.ingestion.structural_index import StructuralRecord
from app.ingestion.structural_qdrant import (
    build_structural_inference_text,
    point_payload,
    structural_inference_text_sha256,
)


_SHA256 = r"^[0-9a-f]{64}$"
_PositiveInt = Annotated[StrictInt, Field(gt=0)]
_RATE_LIMIT_RETRY_STAGGER_SECONDS = 6.0


class PineconeStructuralError(RuntimeError):
    """Raised when the isolated Pinecone structural contract is violated."""


class PineconeStructuralContract(BaseModel):
    """Exact immutable contract for the P3 Pinecone replacement pilot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    index_name: Literal["llama-text-embed-v2-index"] = (
        "llama-text-embed-v2-index"
    )
    namespace: Literal["national-primary-v2"] = "national-primary-v2"
    model: Literal["llama-text-embed-v2"] = "llama-text-embed-v2"
    dimension: Literal[1024] = 1024
    metric: Literal["cosine"] = "cosine"
    text_field: Literal["text"] = "text"
    batch_size: Literal[96] = 96
    max_workers: Annotated[StrictInt, Field(gt=0, le=32)] = 16
    dense_top_k: _PositiveInt = 48
    exact_top_k: _PositiveInt = 24
    fused_limit: _PositiveInt = 48
    rrf_k: _PositiveInt = 60
    per_document_limit: _PositiveInt = 8


class PineconeCheckpointBinding(BaseModel):
    """Immutable identities that make a resumed upload fail closed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    index_name: Literal["llama-text-embed-v2-index"] = (
        "llama-text-embed-v2-index"
    )
    namespace: Literal["national-primary-v2"] = "national-primary-v2"
    model: Literal["llama-text-embed-v2"] = "llama-text-embed-v2"
    dimension: Literal[1024] = 1024
    manifest_sha256: str = Field(pattern=_SHA256)
    dataset_revision: str = Field(min_length=1)
    ordered_record_ids_sha256: str = Field(pattern=_SHA256)
    manifest_record_count: _PositiveInt
    document_text_version: Literal["vietlex-structural-document-v2"] = (
        "vietlex-structural-document-v2"
    )


class PineconeStructuralUploadReport(BaseModel):
    """Observable upload result; remote count verification remains separate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["PASS_UPLOAD"] = "PASS_UPLOAD"
    index_name: Literal["llama-text-embed-v2-index"]
    namespace: Literal["national-primary-v2"]
    submitted_records: int = Field(ge=0)
    committed_records: int = Field(ge=0)
    checkpoint_record_count: int = Field(ge=0)
    provider_calls: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    response_semantics: Literal["client_submitted_count_only"] = (
        "client_submitted_count_only"
    )


class PineconeStructuralVerificationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["PASS_VERIFY"] = "PASS_VERIFY"
    index_name: Literal["llama-text-embed-v2-index"]
    namespace: Literal["national-primary-v2"]
    remote_record_count: _PositiveInt
    sample_count: _PositiveInt
    sample_record_ids_sha256: str = Field(pattern=_SHA256)
    provider_calls: _PositiveInt


def _value(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def validate_pinecone_structural_index(
    description: object,
    contract: PineconeStructuralContract,
) -> None:
    """Validate the live integrated-index model contract before any write."""
    status = _value(description, "status")
    if _value(status, "ready") is not True:
        raise PineconeStructuralError("Pinecone structural index is not ready")
    exact = {
        "name": contract.index_name,
        "dimension": contract.dimension,
        "metric": contract.metric,
    }
    for name, expected in exact.items():
        if _value(description, name) != expected:
            raise PineconeStructuralError(
                f"Pinecone structural index {name} mismatch"
            )
    embed = _value(description, "embed")
    embed_exact = {
        "model": contract.model,
        "dimension": contract.dimension,
        "metric": contract.metric,
        "field_map": {"text": contract.text_field},
    }
    for name, expected in embed_exact.items():
        if _value(embed, name) != expected:
            raise PineconeStructuralError(
                f"Pinecone structural embed {name} mismatch"
            )
    for name, input_type in (
        ("read_parameters", "query"),
        ("write_parameters", "passage"),
    ):
        parameters = _value(embed, name)
        expected = {
            "dimension": contract.dimension,
            "input_type": input_type,
            "truncate": "END",
        }
        if not isinstance(parameters, Mapping) or dict(parameters) != expected:
            raise PineconeStructuralError(
                f"Pinecone structural {name} mismatch"
            )


def pinecone_structural_record(record: StructuralRecord) -> dict[str, object]:
    """Map one validated structural record to the integrated text API."""
    payload = {
        key: value
        for key, value in point_payload(record).items()
        if value is not None
    }
    return {
        "_id": record.record_id,
        "text": build_structural_inference_text(record),
        **payload,
    }


def _canonical_binding(binding: PineconeCheckpointBinding) -> str:
    return json.dumps(
        binding.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class PineconeStructuralCheckpoint:
    """Transactional record acknowledgements for idempotent resume."""

    def __init__(
        self,
        path: Path,
        binding: PineconeCheckpointBinding,
    ) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.binding = binding
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        binding_json = _canonical_binding(self.binding)
        binding_sha256 = hashlib.sha256(binding_json.encode()).hexdigest()
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS binding (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    binding_json TEXT NOT NULL,
                    binding_sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS committed_records (
                    record_id TEXT PRIMARY KEY,
                    chunk_sha256 TEXT NOT NULL,
                    inference_text_sha256 TEXT NOT NULL,
                    committed_at_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            row = connection.execute(
                "SELECT binding_json, binding_sha256 FROM binding "
                "WHERE singleton = 1"
            ).fetchone()
            expected = (binding_json, binding_sha256)
            if row is None:
                connection.execute(
                    "INSERT INTO binding(singleton, binding_json, binding_sha256) "
                    "VALUES (1, ?, ?)",
                    expected,
                )
            elif row != expected:
                raise PineconeStructuralError("checkpoint binding mismatch")

    def _identities(self) -> dict[str, tuple[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT record_id, chunk_sha256, inference_text_sha256 "
                "FROM committed_records ORDER BY record_id"
            ).fetchall()
        return {
            str(record_id): (str(chunk_hash), str(text_hash))
            for record_id, chunk_hash, text_hash in rows
        }

    def committed_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM committed_records"
            ).fetchone()
        return int(row[0])

    def iter_pending(
        self,
        records: Iterable[StructuralRecord],
    ) -> Iterable[StructuralRecord]:
        committed = self._identities()
        for record in records:
            identity = (
                record.chunk_sha256,
                structural_inference_text_sha256(record),
            )
            existing = committed.get(record.record_id)
            if existing is None:
                yield record
            elif existing != identity:
                raise PineconeStructuralError("checkpoint record hash mismatch")

    def pending(
        self,
        records: Iterable[StructuralRecord],
    ) -> list[StructuralRecord]:
        return list(self.iter_pending(records))

    def commit(self, records: Sequence[StructuralRecord]) -> int:
        if not records:
            raise PineconeStructuralError("checkpoint batch must not be empty")
        normalized = sorted(records, key=lambda row: row.record_id)
        if len({row.record_id for row in normalized}) != len(normalized):
            raise PineconeStructuralError("checkpoint batch IDs must be unique")
        inserted = 0
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            for record in normalized:
                identity = (
                    record.chunk_sha256,
                    structural_inference_text_sha256(record),
                )
                existing = connection.execute(
                    "SELECT chunk_sha256, inference_text_sha256 "
                    "FROM committed_records WHERE record_id = ?",
                    (record.record_id,),
                ).fetchone()
                if existing is None:
                    connection.execute(
                        "INSERT INTO committed_records("
                        "record_id, chunk_sha256, inference_text_sha256) "
                        "VALUES (?, ?, ?)",
                        (record.record_id, *identity),
                    )
                    inserted += 1
                elif existing != identity:
                    raise PineconeStructuralError(
                        "checkpoint record hash mismatch"
                    )
            connection.commit()
            return inserted
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def _transient_provider_error(error: Exception) -> bool:
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    return status in {408, 429, 500, 502, 503, 504} or isinstance(
        error,
        TimeoutError,
    )


def _provider_status_code(error: Exception) -> int | None:
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    return status if isinstance(status, int) and not isinstance(status, bool) else None


def _record_batches(
    records: Iterable[StructuralRecord],
    size: int,
) -> Iterable[list[StructuralRecord]]:
    iterator = iter(records)
    while batch := list(islice(iterator, size)):
        yield batch


def _upsert_batch(
    index: object,
    batch: Sequence[StructuralRecord],
    *,
    contract: PineconeStructuralContract,
    sleep: Callable[[float], None],
    rate_limit_retry_offset: float = 0.0,
) -> tuple[tuple[StructuralRecord, ...], int]:
    attempts = 0
    while attempts < 30:
        attempts += 1
        try:
            response = index.upsert_records(
                namespace=contract.namespace,
                records=[pinecone_structural_record(record) for record in batch],
                timeout=120.0,
            )
        except Exception as error:
            if attempts >= 30 or not _transient_provider_error(error):
                raise PineconeStructuralError(
                    "Pinecone structural upsert failed "
                    f"({type(error).__name__})"
                ) from error
            delay = (
                60.0 + rate_limit_retry_offset
                if _provider_status_code(error) == 429
                else min(8.0, 0.5 * (2 ** (attempts - 1)))
            )
            sleep(delay)
            continue
        count = getattr(response, "record_count", None)
        if isinstance(count, bool) or count != len(batch):
            raise PineconeStructuralError(
                "Pinecone structural response record count mismatch"
            )
        return tuple(batch), attempts
    raise AssertionError("unreachable Pinecone retry loop")


def upload_pinecone_structural_records(
    index: object,
    records: Iterable[StructuralRecord],
    *,
    checkpoint: PineconeStructuralCheckpoint,
    contract: PineconeStructuralContract,
    sleep: Callable[[float], None] = time.sleep,
) -> PineconeStructuralUploadReport:
    """Upload bounded waves and commit only successful batch identities."""
    pending = checkpoint.iter_pending(records)
    batches = iter(_record_batches(pending, contract.batch_size))
    submitted = 0
    committed = 0
    provider_calls = 0
    retry_count = 0
    while wave := list(islice(batches, contract.max_workers)):
        with ThreadPoolExecutor(max_workers=len(wave)) as executor:
            futures = [
                executor.submit(
                    _upsert_batch,
                    index,
                    batch,
                    contract=contract,
                    sleep=sleep,
                    rate_limit_retry_offset=(
                        position * _RATE_LIMIT_RETRY_STAGGER_SECONDS
                    ),
                )
                for position, batch in enumerate(wave)
            ]
            for future in as_completed(futures):
                batch, attempts = future.result()
                submitted += len(batch)
                provider_calls += attempts
                retry_count += attempts - 1
                committed += checkpoint.commit(batch)
    return PineconeStructuralUploadReport(
        index_name=contract.index_name,
        namespace=contract.namespace,
        submitted_records=submitted,
        committed_records=committed,
        checkpoint_record_count=checkpoint.committed_count(),
        provider_calls=provider_calls,
        retry_count=retry_count,
    )


def verify_pinecone_structural_namespace(
    index: object,
    samples: Sequence[StructuralRecord],
    *,
    expected_count: int,
    contract: PineconeStructuralContract,
) -> PineconeStructuralVerificationReport:
    """Verify exact namespace count and deterministic record identities."""
    if (
        isinstance(expected_count, bool)
        or not isinstance(expected_count, int)
        or expected_count <= 0
        or not samples
    ):
        raise PineconeStructuralError("verification inputs are invalid")
    stats = index.describe_index_stats()
    namespaces = getattr(stats, "namespaces", None)
    if not isinstance(namespaces, Mapping):
        raise PineconeStructuralError("Pinecone namespace stats are malformed")
    summary = namespaces.get(contract.namespace)
    count = _value(summary, "vector_count")
    if count != expected_count:
        raise PineconeStructuralError(
            "Pinecone namespace record count mismatch"
        )
    record_ids: list[str] = []
    for record in samples:
        response = index.search(
            namespace=contract.namespace,
            id=record.record_id,
            top_k=1,
            fields=[
                "document_id",
                "dataset_revision",
                "chunk_sha256",
                "inference_text_sha256",
            ],
            timeout=60.0,
        )
        hits = getattr(getattr(response, "result", None), "hits", None)
        if not isinstance(hits, list) or len(hits) != 1:
            raise PineconeStructuralError(
                "Pinecone verification sample is missing"
            )
        hit = hits[0]
        hit_fields = _value(hit, "fields")
        if (
            _value(hit, "_id") != record.record_id
            or not isinstance(hit_fields, Mapping)
            or hit_fields.get("document_id") != record.document_id
            or hit_fields.get("dataset_revision") != record.dataset_revision
            or hit_fields.get("chunk_sha256") != record.chunk_sha256
            or hit_fields.get("inference_text_sha256")
            != structural_inference_text_sha256(record)
        ):
            raise PineconeStructuralError(
                "Pinecone verification sample identity mismatch"
            )
        usage = getattr(response, "usage", None)
        read_units = getattr(usage, "read_units", None)
        if (
            isinstance(read_units, bool)
            or not isinstance(read_units, int)
            or read_units <= 0
        ):
            raise PineconeStructuralError(
                "Pinecone verification usage is malformed"
            )
        record_ids.append(record.record_id)
    return PineconeStructuralVerificationReport(
        index_name=contract.index_name,
        namespace=contract.namespace,
        remote_record_count=count,
        sample_count=len(samples),
        sample_record_ids_sha256=hashlib.sha256(
            json.dumps(
                record_ids,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        provider_calls=1 + len(samples),
    )
