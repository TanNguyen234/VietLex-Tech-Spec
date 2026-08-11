"""Transactional record-level checkpointing for structural Qdrant upload."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Annotated, TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from app.ingestion.structural_index import StructuralRecord
from app.ingestion.structural_qdrant import structural_inference_text_sha256

if TYPE_CHECKING:
    from app.evaluation.structural_model_probe import StructuralModelProbeReport


_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_PositiveInt = Annotated[StrictInt, Field(gt=0)]


class StructuralCheckpointError(RuntimeError):
    """Raised when persisted upload acknowledgement cannot be trusted."""


class CheckpointBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["2.0.0"] = "2.0.0"
    collection_name: Literal["vietlex-legal-rag-v2-pilot-384"]
    source_state_sha256: str = Field(pattern=_SHA256_PATTERN)
    plan_sha256: str = Field(pattern=_SHA256_PATTERN)
    creation_receipt_sha256: str = Field(pattern=_SHA256_PATTERN)
    probe_report_sha256: str = Field(pattern=_SHA256_PATTERN)
    dataset_revision: str = Field(min_length=1)
    ordered_record_ids_sha256: str = Field(pattern=_SHA256_PATTERN)
    manifest_record_count: _PositiveInt
    dense_model: Literal["intfloat/multilingual-e5-small"]
    sparse_model: Literal["qdrant/bm25"]
    document_text_version: Literal["vietlex-structural-document-v2"]


class AcknowledgedRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str = Field(min_length=1)
    chunk_sha256: str = Field(pattern=_SHA256_PATTERN)
    inference_text_sha256: str = Field(pattern=_SHA256_PATTERN)


class BatchReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_sha256: str = Field(pattern=_SHA256_PATTERN)
    records: tuple[AcknowledgedRecord, ...]
    usage: dict[str, StrictInt]
    attempts: _PositiveInt
    elapsed_seconds: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )

    @model_validator(mode="after")
    def validate_receipt(self):
        record_ids = [record.record_id for record in self.records]
        if not record_ids or record_ids != sorted(set(record_ids)):
            raise ValueError("batch records must be nonempty, unique, and sorted")
        if self.batch_sha256 != batch_identity_sha256(self.records):
            raise ValueError("batch SHA-256 mismatch")
        if not self.usage or any(
            isinstance(tokens, bool)
            or not isinstance(tokens, int)
            or tokens <= 0
            for tokens in self.usage.values()
        ):
            raise ValueError("batch usage must contain positive token counts")
        return self


def batch_identity_sha256(records: Sequence[AcknowledgedRecord]) -> str:
    payload = [
        {
            "record_id": record.record_id,
            "chunk_sha256": record.chunk_sha256,
            "inference_text_sha256": record.inference_text_sha256,
        }
        for record in records
    ]
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class StructuralCheckpointStore:
    """SQLite checkpoint where one acknowledged batch commits atomically."""

    def __init__(self, path: Path, binding: CheckpointBinding) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.binding = binding
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        binding_json = _canonical_binding_json(self.binding)
        binding_sha256 = hashlib.sha256(binding_json.encode()).hexdigest()
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS binding (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    binding_json TEXT NOT NULL,
                    binding_sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS committed_batches (
                    batch_sha256 TEXT PRIMARY KEY,
                    attempts INTEGER NOT NULL,
                    elapsed_seconds REAL,
                    dense_tokens INTEGER NOT NULL,
                    sparse_tokens INTEGER NOT NULL,
                    committed_at_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS committed_records (
                    record_id TEXT PRIMARY KEY,
                    chunk_sha256 TEXT NOT NULL,
                    inference_text_sha256 TEXT NOT NULL,
                    batch_sha256 TEXT NOT NULL,
                    committed_at_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    dense_tokens INTEGER NOT NULL,
                    sparse_tokens INTEGER NOT NULL,
                    FOREIGN KEY(batch_sha256)
                        REFERENCES committed_batches(batch_sha256)
                );
                """
            )
            row = connection.execute(
                "SELECT binding_json, binding_sha256 FROM binding "
                "WHERE singleton = 1"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO binding(singleton, binding_json, binding_sha256) "
                    "VALUES (1, ?, ?)",
                    (binding_json, binding_sha256),
                )
            elif row != (binding_json, binding_sha256):
                raise StructuralCheckpointError("checkpoint binding mismatch")

    def committed_record_hashes(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT record_id, chunk_sha256 FROM committed_records "
                "ORDER BY record_id"
            ).fetchall()
        return {str(record_id): str(chunk_hash) for record_id, chunk_hash in rows}

    def _committed_record_identities(self) -> dict[str, tuple[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT record_id, chunk_sha256, inference_text_sha256 "
                "FROM committed_records ORDER BY record_id"
            ).fetchall()
        return {
            str(record_id): (str(chunk_hash), str(inference_hash))
            for record_id, chunk_hash, inference_hash in rows
        }

    def committed_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM committed_records"
            ).fetchone()
        return int(row[0])

    def pending(
        self,
        records: Iterable[StructuralRecord],
    ) -> list[StructuralRecord]:
        return list(self.iter_pending(records))

    def iter_pending(
        self,
        records: Iterable[StructuralRecord],
    ) -> Iterable[StructuralRecord]:
        """Yield only unacknowledged records without retaining their bodies."""
        committed = self._committed_record_identities()
        for record in records:
            existing_identity = committed.get(record.record_id)
            if existing_identity is None:
                yield record
            elif existing_identity != (
                record.chunk_sha256,
                structural_inference_text_sha256(record),
            ):
                raise StructuralCheckpointError(
                    "checkpoint record hash mismatch"
                )

    def commit_receipt(self, receipt: BatchReceipt) -> int:
        self._validate_receipt(receipt)
        dense_tokens = receipt.usage[self.binding.dense_model]
        sparse_tokens = receipt.usage[self.binding.sparse_model]
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing_batch = connection.execute(
                "SELECT dense_tokens, sparse_tokens FROM committed_batches "
                "WHERE batch_sha256 = ?",
                (receipt.batch_sha256,),
            ).fetchone()
            existing_rows: dict[str, tuple[str, str, str]] = {}
            record_ids = tuple(record.record_id for record in receipt.records)
            for start in range(0, len(record_ids), 500):
                chunk = record_ids[start : start + 500]
                rows = connection.execute(
                    "SELECT record_id, chunk_sha256, inference_text_sha256, "
                    "batch_sha256 "
                    "FROM committed_records WHERE record_id IN "
                    f"({','.join('?' for _ in chunk)})",
                    chunk,
                ).fetchall()
                existing_rows.update(
                    {
                        str(record_id): (
                            str(chunk_hash),
                            str(inference_hash),
                            str(batch_hash),
                        )
                        for record_id, chunk_hash, inference_hash, batch_hash in rows
                    }
                )
            for record in receipt.records:
                existing = existing_rows.get(record.record_id)
                if existing is not None and existing != (
                    record.chunk_sha256,
                    record.inference_text_sha256,
                    receipt.batch_sha256,
                ):
                    raise StructuralCheckpointError(
                        "checkpoint record hash mismatch"
                    )
            if existing_batch is not None:
                if existing_batch != (dense_tokens, sparse_tokens) or len(
                    existing_rows
                ) != len(receipt.records):
                    raise StructuralCheckpointError(
                        "checkpoint batch acknowledgement mismatch"
                    )
                connection.commit()
                return 0

            connection.execute(
                "INSERT INTO committed_batches("
                "batch_sha256, attempts, elapsed_seconds, dense_tokens, "
                "sparse_tokens) VALUES (?, ?, ?, ?, ?)",
                (
                    receipt.batch_sha256,
                    receipt.attempts,
                    receipt.elapsed_seconds,
                    dense_tokens,
                    sparse_tokens,
                ),
            )
            for index, record in enumerate(receipt.records):
                connection.execute(
                    "INSERT INTO committed_records("
                    "record_id, chunk_sha256, inference_text_sha256, "
                    "batch_sha256, dense_tokens, sparse_tokens) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        record.record_id,
                        record.chunk_sha256,
                        record.inference_text_sha256,
                        receipt.batch_sha256,
                        dense_tokens if index == 0 else 0,
                        sparse_tokens if index == 0 else 0,
                    ),
                )
            connection.commit()
            return len(receipt.records)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def usage_totals(self) -> dict[str, int]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(dense_tokens), 0), "
                "COALESCE(SUM(sparse_tokens), 0) FROM committed_batches"
            ).fetchone()
        return {
            self.binding.dense_model: int(row[0]),
            self.binding.sparse_model: int(row[1]),
        }

    def import_probe_receipt(
        self,
        report: StructuralModelProbeReport,
        *,
        report_sha256: str,
    ) -> int:
        """Seed exact model-probe acknowledgements into a fresh/resumed store."""
        expected = {
            "acceptance": "PASS_MODEL_PROBE",
            "collection_name": self.binding.collection_name,
            "source_state_sha256": self.binding.source_state_sha256,
            "plan_sha256": self.binding.plan_sha256,
            "creation_receipt_sha256": self.binding.creation_receipt_sha256,
            "dataset_revision": self.binding.dataset_revision,
            "candidate_dense_model": self.binding.dense_model,
            "candidate_sparse_model": self.binding.sparse_model,
        }
        if report_sha256 != self.binding.probe_report_sha256 or any(
            getattr(report, field_name, None) != expected_value
            for field_name, expected_value in expected.items()
        ):
            raise StructuralCheckpointError("probe receipt binding mismatch")
        record_ids = tuple(getattr(report, "record_ids", ()))
        record_hashes = getattr(report, "probe_record_hashes", {})
        inference_hashes = getattr(
            report,
            "probe_inference_text_hashes",
            {},
        )
        if (
            not record_ids
            or record_ids != tuple(sorted(set(record_ids)))
            or set(record_hashes) != set(record_ids)
            or set(inference_hashes) != set(record_ids)
        ):
            raise StructuralCheckpointError("probe record identity mismatch")
        acknowledged = tuple(
            AcknowledgedRecord(
                record_id=record_id,
                chunk_sha256=record_hashes[record_id],
                inference_text_sha256=inference_hashes[record_id],
            )
            for record_id in record_ids
        )
        provider_usage = getattr(report, "upsert_provider_usage", {})
        usage = {
            self.binding.dense_model: provider_usage.get(
                self.binding.dense_model,
                0,
            ),
            self.binding.sparse_model: provider_usage.get(
                self.binding.sparse_model,
                0,
            ),
        }
        attempts = len(getattr(report, "upsert_batch_sizes", ()))
        if attempts <= 0:
            raise StructuralCheckpointError(
                "probe receipt acknowledgement mismatch"
            )
        try:
            receipt = BatchReceipt(
                batch_sha256=batch_identity_sha256(acknowledged),
                records=acknowledged,
                usage=usage,
                attempts=attempts,
                elapsed_seconds=None,
            )
        except ValueError as error:
            raise StructuralCheckpointError(
                "probe receipt acknowledgement mismatch"
            ) from error
        return self.commit_receipt(receipt)

    def _validate_receipt(self, receipt: BatchReceipt) -> None:
        if receipt.batch_sha256 != batch_identity_sha256(receipt.records):
            raise StructuralCheckpointError("batch SHA-256 mismatch")
        if set(receipt.usage) != {
            self.binding.dense_model,
            self.binding.sparse_model,
        } or any(value <= 0 for value in receipt.usage.values()):
            raise StructuralCheckpointError("batch model usage mismatch")


def _canonical_binding_json(binding: CheckpointBinding) -> str:
    return json.dumps(
        binding.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
