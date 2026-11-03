"""Bounded, journaled executor for the approved 16+20 V3 corpus plan.

This script deliberately has no bulk-apply or collection-creation command. It
prepares dense/sparse points locally, then applies or rolls back one planned
document per invocation after rechecking all three remote stores.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Sequence

from app.config import Settings, get_settings, system_ssl_context
from app.ingestion.pinecone_store import FastSparseEncoder
from app.ingestion.structural_index import StructuralRecord
from app.ingestion.structural_qdrant import build_structural_inference_text, point_payload
from app.ingestion.supabase_full_doc import SupabaseFullDocUploader
from app.ingestion.vertex_qdrant_migration import (
    VertexQdrantContract,
    build_vertex_point,
)


_PLAN_SCHEMA = "vietlex-corpus-migration-plan-v1"
_PREPARATION_SCHEMA = "vietlex-corpus-migration-preparation-v1"
_VECTOR_SCHEMA = "vietlex-prepared-vectors-v1"
_PLAN_ARTIFACTS = frozenset(
    {
        "old-structural-records.jsonl",
        "new-structural-records.jsonl",
        "supabase-upserts.jsonl",
        "qdrant-body-points.jsonl",
        "plan.json",
    }
)
_BACKUP_ARTIFACTS = frozenset(
    {
        "contract-comparison.json",
        "qdrant-body-original.json.gz",
        "qdrant-v3-original.jsonl.gz",
        "supabase-contract-comparison.json",
        "supabase-original.json.gz",
        "v3-manifest.json",
    }
)
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SPARSE_AVERAGE = 979.1241640033913
_SPARSE_MAX_NONZERO = 64
_CAPACITY_CEILING = 0.8
_CAPACITY_MAX_AGE_SECONDS = 60 * 60
_CAPACITY_FUTURE_SKEW_SECONDS = 5 * 60
_MAX_DOCUMENT_RECORDS = 16
_MAX_DOCUMENT_POINT_UNION = _MAX_DOCUMENT_RECORDS * 2
_V3_INVENTORY_PAGE_SIZE = 10_000
_V3_INVENTORY_MAX_PAGES = 30
_VECTOR_REL_TOL = 1e-6
_VECTOR_ABS_TOL = 1e-7


class MigrationError(RuntimeError):
    """A stable, non-sensitive migration failure code."""


def _json_bytes(value: object, *, pretty: bool = False) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid_{label}") from error
    if not isinstance(value, dict):
        raise ValueError(f"invalid_{label}")
    return value


def _read_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    raise ValueError(f"blank_{label}_line")
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"invalid_{label}_row")
                rows.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid_{label}") from error
    return rows


def _positive_id(value: object) -> bool:
    return type(value) is int and value > 0


def _valid_hash(value: object) -> bool:
    return isinstance(value, str) and _HASH_RE.fullmatch(value) is not None


def _finite_vector(value: object, *, dimension: int) -> list[float]:
    if not isinstance(value, list) or len(value) != dimension:
        raise ValueError("dense_vector_dimension_mismatch")
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
        raise ValueError("dense_vector_value_invalid")
    values = [float(item) for item in value]
    if not all(math.isfinite(item) for item in values):
        raise ValueError("dense_vector_value_invalid")
    norm = math.sqrt(sum(item * item for item in values))
    if not math.isfinite(norm) or not math.isclose(norm, 1.0, rel_tol=0.02, abs_tol=0.02):
        raise ValueError("dense_vector_not_l2_normalized")
    return values


def _sparse_values(indices: object, values: object) -> tuple[list[int], list[float]]:
    if (
        not isinstance(indices, list)
        or not isinstance(values, list)
        or not 0 < len(indices) <= _SPARSE_MAX_NONZERO
        or len(indices) != len(values)
        or any(type(index) is not int or index < 0 for index in indices)
        or indices != sorted(set(indices))
        or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in values)
    ):
        raise ValueError("sparse_vector_invalid")
    clean_values = [float(item) for item in values]
    if not all(math.isfinite(item) for item in clean_values):
        raise ValueError("sparse_vector_invalid")
    return list(indices), clean_values


def _plain(value: object) -> object:
    if hasattr(value, "model_dump"):
        try:
            value = value.model_dump(mode="json", exclude_none=True)
        except TypeError:
            value = value.model_dump()
    elif hasattr(value, "dict") and callable(value.dict):
        value = value.dict(exclude_none=True)
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if hasattr(value, "indices") and hasattr(value, "values"):
        return {
            "indices": _plain(value.indices),
            "values": _plain(value.values),
        }
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return value


def _point_dict(value: object) -> dict[str, Any]:
    plain = _plain(value)
    if not isinstance(plain, dict):
        raise ValueError("qdrant_point_schema_invalid")
    point_id = plain.get("id")
    payload = plain.get("payload")
    vector = plain.get("vector", {})
    if not isinstance(payload, dict) or not isinstance(vector, dict):
        raise ValueError("qdrant_point_schema_invalid")
    if isinstance(point_id, str):
        try:
            # Preserve Qdrant UUID string IDs exactly.
            point_id = str(point_id)
        except Exception:
            raise ValueError("qdrant_point_id_invalid") from None
    elif type(point_id) is not int:
        raise ValueError("qdrant_point_id_invalid")
    return {"id": point_id, "payload": payload, "vector": vector}


def _point_id(value: object) -> str | int:
    point = _point_dict(value)
    return point["id"]


def _normalize_expected_point(point: dict[str, Any]) -> dict[str, Any]:
    return _point_dict(point)


def _finite_close_values(actual: object, expected: object) -> bool:
    if not isinstance(actual, list) or not isinstance(expected, list) or len(actual) != len(expected):
        return False
    for observed, wanted in zip(actual, expected):
        if (
            isinstance(observed, bool)
            or isinstance(wanted, bool)
            or not isinstance(observed, (int, float))
            or not isinstance(wanted, (int, float))
        ):
            return False
        observed_float, wanted_float = float(observed), float(wanted)
        if not math.isfinite(observed_float) or not math.isfinite(wanted_float):
            return False
        if not math.isclose(
            observed_float,
            wanted_float,
            rel_tol=_VECTOR_REL_TOL,
            abs_tol=_VECTOR_ABS_TOL,
        ):
            return False
    return True


def _unit_dense_for_comparison(value: object, *, provider_norm: bool) -> list[float] | None:
    if not isinstance(value, list) or len(value) != 1024:
        return None
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
        return None
    values = [float(item) for item in value]
    if not all(math.isfinite(item) for item in values):
        return None
    norm = math.sqrt(sum(item * item for item in values))
    if not math.isfinite(norm) or norm <= 0:
        return None
    if provider_norm:
        if not math.isclose(norm, 1.0, rel_tol=0.02, abs_tol=0.02):
            return None
    elif not math.isclose(norm, 1.0, rel_tol=2e-5, abs_tol=2e-5):
        return None
    return [item / norm for item in values]


def _point_matches(actual: object, expected: object) -> bool:
    """Compare exact identity/payload and tolerate Qdrant float32 vector storage."""
    try:
        actual_point = _point_dict(actual)
        expected_point = _point_dict(expected)
    except ValueError:
        return False
    if actual_point["id"] != expected_point["id"] or actual_point["payload"] != expected_point["payload"]:
        return False
    actual_vector, expected_vector = actual_point["vector"], expected_point["vector"]
    if set(actual_vector) != set(expected_vector):
        return False
    for key in actual_vector:
        observed, wanted = actual_vector[key], expected_vector[key]
        if key == "dense":
            observed_unit = _unit_dense_for_comparison(observed, provider_norm=False)
            wanted_unit = _unit_dense_for_comparison(wanted, provider_norm=True)
            if (
                observed_unit is None
                or wanted_unit is None
                or not _finite_close_values(observed_unit, wanted_unit)
            ):
                return False
        elif key == "sparse":
            if not isinstance(observed, dict) or not isinstance(wanted, dict):
                return False
            if set(observed) != {"indices", "values"} or set(wanted) != {"indices", "values"}:
                return False
            if observed["indices"] != wanted["indices"] or not _finite_close_values(
                observed["values"], wanted["values"]
            ):
                return False
        elif observed != wanted:
            return False
    return True


def _group_records(rows: list[dict[str, Any]], label: str) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    record_ids: set[str] = set()
    for row in rows:
        try:
            record = StructuralRecord.model_validate(row)
        except Exception as error:
            raise ValueError(f"invalid_{label}_structural_record") from error
        if record.record_id in record_ids:
            raise ValueError(f"duplicate_{label}_structural_record_id")
        record_ids.add(record.record_id)
        grouped[record.document_id].append(record.model_dump(mode="json"))
    return dict(grouped)


class MigrationBundle:
    def __init__(self, plan_dir: Path) -> None:
        self.plan_dir = Path(plan_dir).resolve()
        if not self.plan_dir.is_dir():
            raise ValueError("plan_directory_missing")
        manifest = _read_json(self.plan_dir / "manifest.json", "plan_manifest")
        artifacts = manifest.get("artifacts")
        if (
            manifest.get("schema_version") != _PREPARATION_SCHEMA
            or manifest.get("remote_writes") is not False
            or manifest.get("provider_calls") != 0
            or manifest.get("legal_validity") != "UNVERIFIED"
            or not isinstance(artifacts, dict)
            or set(artifacts) != _PLAN_ARTIFACTS
        ):
            raise ValueError("plan_manifest_contract_mismatch")
        for name, descriptor in artifacts.items():
            path = self.plan_dir / name
            if (
                Path(name).name != name
                or not isinstance(descriptor, dict)
                or not path.is_file()
                or type(descriptor.get("bytes")) is not int
                or path.stat().st_size != descriptor["bytes"]
                or descriptor.get("sha256") != _sha256_file(path)
            ):
                raise ValueError(f"plan_artifact_hash_mismatch:{name}")
        self.artifacts = artifacts
        self.plan_bytes = (self.plan_dir / "plan.json").read_bytes()
        self.plan_sha256 = _sha256_bytes(self.plan_bytes)
        self.plan = _read_json(self.plan_dir / "plan.json", "plan")
        self._validate_plan()

    def _validate_plan(self) -> None:
        plan = self.plan
        contract = plan.get("embedding_contract")
        dataset = plan.get("dataset")
        if (
            plan.get("schema_version") != _PLAN_SCHEMA
            or not isinstance(contract, dict)
            or contract
            != {
                "collection": "vietlex-legal-rag-v3-vertex-1024",
                "model": "gemini-embedding-2",
                "dimension": 1024,
                "chunk_max_tokens": 320,
                "chunk_overlap_tokens": 32,
                "max_chunks_per_document": 16,
            }
            or not isinstance(dataset, dict)
            or dataset.get("repository") != "vohuutridung/vietnamese-legal-documents"
            or dataset.get("revision") != "4d4e10b201544e8a4c49a1d3fa496595a7d486d0"
            or dataset.get("expected_document_count") != 518255
            or plan.get("remote_writes") is not False
            or plan.get("provider_calls") != 0
            or plan.get("apply_status") != "NOT RUN"
            or plan.get("legal_validity") != "UNVERIFIED"
            or not isinstance(plan.get("affected_online_snapshot"), dict)
            or not _valid_hash(plan["affected_online_snapshot"].get("snapshot_sha256"))
        ):
            raise ValueError("plan_contract_mismatch")
        affected = plan.get("affected_document_ids")
        candidates = plan.get("candidate_document_ids")
        documents = plan.get("documents")
        if (
            not isinstance(affected, list)
            or len(affected) != 16
            or affected != sorted(set(affected))
            or any(not _positive_id(item) for item in affected)
            or not isinstance(candidates, list)
            or len(candidates) != 20
            or len(set(candidates)) != len(candidates)
            or any(not _positive_id(item) for item in candidates)
            or set(affected) & set(candidates)
            or not isinstance(documents, list)
            or len(documents) != 36
        ):
            raise ValueError("plan_scope_mismatch")
        expected_ids = sorted([*affected, *candidates])
        self.documents: dict[int, dict[str, Any]] = {}
        for row in documents:
            if not isinstance(row, dict) or not _positive_id(row.get("document_id")):
                raise ValueError("plan_document_invalid")
            document_id = row["document_id"]
            if document_id in self.documents:
                raise ValueError("plan_document_duplicate")
            expected_action = "replace_cleaned" if document_id in affected else "insert_absent_candidate"
            if (
                row.get("action") != expected_action
                or not _valid_hash(row.get("new_content_sha256"))
                or (expected_action == "replace_cleaned" and not _valid_hash(row.get("old_content_sha256")))
                or (expected_action == "insert_absent_candidate" and row.get("old_content_sha256") is not None)
                or row.get("new_body_point_id") != document_id
                or row.get("old_body_point_id") != (document_id if expected_action == "replace_cleaned" else None)
                or not isinstance(row.get("new_structural_point_ids"), list)
                or not 0 < len(row["new_structural_point_ids"]) <= _MAX_DOCUMENT_RECORDS
                or not isinstance(row.get("old_structural_point_ids"), list)
                or len(row["old_structural_point_ids"]) > _MAX_DOCUMENT_RECORDS
                or len(set(row["new_structural_point_ids"])) != len(row["new_structural_point_ids"])
                or len(set(row["old_structural_point_ids"])) != len(row["old_structural_point_ids"])
            ):
                raise ValueError(f"plan_document_contract_mismatch:{document_id}")
            self.documents[document_id] = row
        if sorted(self.documents) != expected_ids:
            raise ValueError("plan_document_coverage_mismatch")
        self.affected_ids = affected
        self.candidate_ids = candidates
        self.new_records = _group_records(
            _read_jsonl(self.plan_dir / "new-structural-records.jsonl", "new_structural_records"),
            "new",
        )
        self.old_records = _group_records(
            _read_jsonl(self.plan_dir / "old-structural-records.jsonl", "old_structural_records"),
            "old",
        )
        self.rows = _index_rows(
            _read_jsonl(self.plan_dir / "supabase-upserts.jsonl", "supabase_upserts"),
            "document_id",
            "supabase_upserts",
        )
        self.body_points = _index_rows(
            _read_jsonl(self.plan_dir / "qdrant-body-points.jsonl", "body_points"),
            "id",
            "body_points",
        )
        if set(self.new_records) != set(expected_ids) or set(self.rows) != set(expected_ids) or set(self.body_points) != set(expected_ids):
            raise ValueError("plan_artifact_document_coverage_mismatch")
        record_ids: set[str] = set()
        for document_id in expected_ids:
            doc = self.documents[document_id]
            new_group = self.new_records[document_id]
            old_group = self.old_records.get(document_id, [])
            new_ids = [item["record_id"] for item in new_group]
            old_ids = [item["record_id"] for item in old_group]
            if (
                new_ids != doc["new_structural_point_ids"]
                or old_ids != doc["old_structural_point_ids"]
                or any(item["document_id"] != document_id or item["content_sha256"] != doc["new_content_sha256"] for item in new_group)
                or any(item["document_id"] != document_id or item["content_sha256"] != doc["old_content_sha256"] for item in old_group)
                or bool(old_group) != (document_id in self.affected_ids)
                or any(item in record_ids for item in new_ids)
            ):
                raise ValueError(f"plan_structural_record_contract_mismatch:{document_id}")
            record_ids.update(new_ids)
            row = self.rows[document_id]
            body = _point_dict(self.body_points[document_id])
            if (
                row.get("document_id") != document_id
                or row.get("content_sha256") != doc["new_content_sha256"]
                or not isinstance(row.get("content"), str)
                or _sha256_bytes(row["content"].encode("utf-8")) != row["content_sha256"]
                or body["id"] != document_id
                or body["payload"].get("document_id") != document_id
                or body["payload"].get("content_sha256") != doc["new_content_sha256"]
                or body["payload"].get("body") != row["content"]
            ):
                raise ValueError(f"plan_document_payload_mismatch:{document_id}")
        if set(self.old_records) != set(affected):
            raise ValueError("plan_old_structural_coverage_mismatch")
        summary = plan.get("summary")
        if (
            not isinstance(summary, dict)
            or summary.get("affected_replacements") != 16
            or summary.get("candidate_additions") != 20
            or summary.get("planned_new_documents") != 36
            or summary.get("old_structural_records") != sum(map(len, self.old_records.values()))
            or summary.get("new_structural_records") != sum(map(len, self.new_records.values()))
            or summary.get("new_body_points") != 36
            or type(summary.get("serialized_new_structural_payload_bytes")) is not int
            or type(summary.get("dense_vector_bytes_lower_bound")) is not int
            or type(summary.get("serialized_body_qdrant_points_json_bytes")) is not int
            or type(summary.get("serialized_supabase_upserts_json_bytes")) is not int
        ):
            raise ValueError("plan_summary_mismatch")
        self.summary = summary

    def records_for(self, document_id: int) -> list[StructuralRecord]:
        return [StructuralRecord.model_validate(row) for row in self.new_records[document_id]]


def _index_rows(rows: list[dict[str, Any]], key: str, label: str) -> dict[Any, dict[str, Any]]:
    result: dict[Any, dict[str, Any]] = {}
    for row in rows:
        identifier = row.get(key)
        if identifier in result:
            raise ValueError(f"{label}_duplicate_id")
        result[identifier] = row
    return result


class MigrationBackups:
    def __init__(self, bundle: MigrationBundle, backup_dir: Path) -> None:
        self.backup_dir = Path(backup_dir).resolve()
        manifest = _read_json(self.backup_dir / "manifest.json", "backup_manifest")
        artifacts = manifest.get("artifacts")
        if (
            manifest.get("scope")
            != "immutable local backup integrity; remote drift must be rechecked immediately before each write"
            or not isinstance(artifacts, dict)
            or set(artifacts) != _BACKUP_ARTIFACTS
        ):
            raise ValueError("backup_manifest_contract_mismatch")
        for name, descriptor in artifacts.items():
            path = self.backup_dir / name
            if (
                Path(name).name != name
                or not isinstance(descriptor, dict)
                or not path.is_file()
                or type(descriptor.get("bytes")) is not int
                or path.stat().st_size != descriptor["bytes"]
                or descriptor.get("sha256") != _sha256_file(path)
            ):
                raise ValueError(f"backup_artifact_hash_mismatch:{name}")
        self.artifacts = artifacts
        self.v3_manifest = _read_json(self.backup_dir / "v3-manifest.json", "v3_backup_manifest")
        self.v3_comparison = _read_json(self.backup_dir / "contract-comparison.json", "v3_contract_comparison")
        self.supabase_comparison = _read_json(
            self.backup_dir / "supabase-contract-comparison.json",
            "supabase_contract_comparison",
        )
        v3_path = self.backup_dir / "qdrant-v3-original.jsonl.gz"
        if (
            self.v3_manifest.get("scope") != "live read-only Qdrant scroll/retrieve; zero remote writes/providers"
            or self.v3_manifest.get("all_expected_old_ids_match") is not True
            or self.v3_manifest.get("candidate_ids_absent_from_v3") is not True
            or self.v3_manifest.get("backup_sha256") != _sha256_file(v3_path)
            or self.v3_comparison.get("checked_points") != self.v3_manifest.get("backed_up_points")
            or self.v3_comparison.get("mismatches") != []
            or self.v3_comparison.get("average_sparse_document_length") != _SPARSE_AVERAGE
            or self.supabase_comparison.get("checked_documents") != 16
            or self.supabase_comparison.get("mismatches") != []
        ):
            raise ValueError("backup_comparison_not_verified")
        try:
            self.supabase_rows = _index_rows(
                json.loads(gzip.decompress((self.backup_dir / "supabase-original.json.gz").read_bytes())),
                "document_id",
                "backup_supabase_rows",
            )
            self.body_points = {
                point["id"]: _point_dict(point)
                for point in json.loads(gzip.decompress((self.backup_dir / "qdrant-body-original.json.gz").read_bytes()))
            }
            self.v3_points: dict[str, dict[str, Any]] = {}
            with gzip.open(v3_path, "rt", encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        raise ValueError("blank_v3_backup_line")
                    point = _point_dict(json.loads(line))
                    point_id = point["id"]
                    if not isinstance(point_id, str) or point_id in self.v3_points:
                        raise ValueError("duplicate_v3_backup_point")
                    self.v3_points[point_id] = point
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, KeyError) as error:
            raise ValueError("invalid_backup_payload") from error
        self._validate_against_plan(bundle)

    def _validate_against_plan(self, bundle: MigrationBundle) -> None:
        if (
            set(self.supabase_rows) != set(bundle.affected_ids)
            or set(self.body_points) != set(bundle.affected_ids)
            or self.v3_manifest.get("backed_up_documents") != 16
            or self.v3_manifest.get("backed_up_points") != len(self.v3_points)
        ):
            raise ValueError("backup_document_coverage_mismatch")
        expected_ids: set[str] = set()
        for document_id in bundle.affected_ids:
            document = bundle.documents[document_id]
            row = self.supabase_rows[document_id]
            body_point = self.body_points[document_id]
            if (
                row.get("content_sha256") != document["old_content_sha256"]
                or not isinstance(row.get("content"), str)
                or _sha256_bytes(row["content"].encode("utf-8")) != row["content_sha256"]
                or body_point["id"] != document_id
                or body_point["payload"].get("document_id") != document_id
                or body_point["payload"].get("content_sha256") != row["content_sha256"]
                or body_point["payload"].get("body") != row["content"]
                or _sha256_bytes(body_point["payload"]["body"].encode("utf-8")) != row["content_sha256"]
            ):
                raise ValueError(f"backup_source_hash_mismatch:{document_id}")
            first_record = StructuralRecord.model_validate(bundle.old_records[document_id][0])
            if (
                row.get("document_number") != first_record.document_number
                or row.get("title") != first_record.title
                or row.get("source_url") != first_record.source_url
                or row.get("legal_type") != first_record.legal_type
                or row.get("issuance_date") != first_record.issuance_date
            ):
                raise ValueError(f"backup_supabase_metadata_mismatch:{document_id}")
            for record_data in bundle.old_records[document_id]:
                record = StructuralRecord.model_validate(record_data)
                point = self.v3_points.get(record.record_id)
                if point is None:
                    raise ValueError("backup_old_structural_point_missing")
                expected_payload = point_payload(record)
                expected_payload.update(
                    {
                        "embedding_provider": "google_vertex_ai",
                        "embedding_model": "gemini-embedding-2",
                        "embedding_dimension": 1024,
                        "migration_schema": "vietlex-vertex-qdrant-v1",
                    }
                )
                if point["payload"] != expected_payload:
                    raise ValueError("backup_old_structural_payload_mismatch")
                vector = point["vector"]
                if set(vector) != {"dense", "sparse"}:
                    raise ValueError("backup_old_vector_contract_mismatch")
                _finite_vector(vector["dense"], dimension=1024)
                sparse = vector["sparse"]
                if not isinstance(sparse, dict):
                    raise ValueError("backup_old_vector_contract_mismatch")
                _sparse_values(sparse.get("indices"), sparse.get("values"))
                expected_ids.add(record.record_id)
        if set(self.v3_points) != expected_ids:
            raise ValueError("backup_old_structural_coverage_mismatch")


def _vector_header(bundle: MigrationBundle, document_id: int) -> dict[str, Any]:
    return {
        "type": "header",
        "schema_version": _VECTOR_SCHEMA,
        "plan_sha256": bundle.plan_sha256,
        "plan_artifact_sha256": bundle.artifacts["new-structural-records.jsonl"]["sha256"],
        "document_id": document_id,
        "embedding_contract": {
            "collection": "vietlex-legal-rag-v3-vertex-1024",
            "model": "gemini-embedding-2",
            "dimension": 1024,
            "sparse_average_document_length": _SPARSE_AVERAGE,
            "sparse_max_nonzero_terms": _SPARSE_MAX_NONZERO,
        },
    }


def _validate_vector_entry(
    row: dict[str, Any],
    record: StructuralRecord,
) -> dict[str, Any]:
    inference_text = build_structural_inference_text(record)
    inference_hash = _sha256_bytes(inference_text.encode("utf-8"))
    if row.get("record_id") != record.record_id or row.get("inference_text_sha256") != inference_hash:
        raise ValueError("prepared_vector_inference_hash_mismatch")
    dense = _finite_vector(row.get("dense"), dimension=1024)
    sparse_indices, sparse_weights = _sparse_values(
        row.get("sparse_indices"), row.get("sparse_values")
    )
    return {
        "record_id": record.record_id,
        "inference_text_sha256": inference_hash,
        "dense": dense,
        "sparse_indices": sparse_indices,
        "sparse_values": sparse_weights,
    }


def _load_vector_artifact(
    bundle: MigrationBundle,
    document_id: int,
    vectors_path: Path,
) -> dict[str, dict[str, Any]]:
    path = Path(vectors_path)
    if not path.is_file():
        raise ValueError("prepared_vectors_missing")
    rows = _read_jsonl(path, "prepared_vectors")
    if not rows or rows[0] != _vector_header(bundle, document_id):
        raise ValueError("prepared_vectors_header_mismatch")
    expected_records = bundle.records_for(document_id)
    if len(rows) - 1 != len(expected_records):
        raise ValueError("prepared_vectors_incomplete")
    result: dict[str, dict[str, Any]] = {}
    for row, record in zip(rows[1:], expected_records, strict=True):
        if row.get("type") != "vector":
            raise ValueError("prepared_vectors_row_invalid")
        entry = _validate_vector_entry(row, record)
        if entry["record_id"] in result:
            raise ValueError("prepared_vectors_duplicate_id")
        result[entry["record_id"]] = entry
    expected_ids = set(bundle.documents[document_id]["new_structural_point_ids"])
    if set(result) != expected_ids:
        raise ValueError("prepared_vectors_record_coverage_mismatch")
    return result


def _load_preflight_vector(
    bundle: MigrationBundle,
    document_id: int,
    receipt_path: Path | None,
    vector_path: Path | None,
) -> dict[str, Any] | None:
    if receipt_path is None or vector_path is None:
        return None
    receipt_path = Path(receipt_path)
    vector_path = Path(vector_path)
    receipt_exists = receipt_path.is_file()
    vector_exists = vector_path.is_file()
    if not receipt_exists and not vector_exists:
        return None
    if not receipt_exists or not vector_exists:
        raise ValueError("preflight_artifact_pair_incomplete")
    receipt = _read_json(receipt_path, "preflight_receipt")
    if (
        receipt.get("scope") != "live authorized Vertex embedding; zero remote storage writes"
        or receipt.get("status") != "ok"
        or receipt.get("model") != "gemini-embedding-2"
        or receipt.get("dimension") != 1024
        or receipt.get("dimension_observed") != 1024
        or receipt.get("sdk_retries") != 0
        or receipt.get("provider_adapter_calls_started") != 1
        or receipt.get("vector_artifact_sha256") != _sha256_file(vector_path)
    ):
        raise ValueError("preflight_receipt_invalid")
    rows = _read_jsonl(vector_path, "preflight_vector")
    if len(rows) != 1:
        raise ValueError("preflight_vector_artifact_invalid")
    row = rows[0]
    record_data = row.get("record")
    if not isinstance(record_data, dict):
        raise ValueError("preflight_vector_record_invalid")
    try:
        record = StructuralRecord.model_validate(record_data)
    except Exception:
        raise ValueError("preflight_vector_record_invalid") from None
    if record.document_id != document_id:
        return None
    expected = next(
        (candidate for candidate in bundle.records_for(document_id) if candidate.record_id == record.record_id),
        None,
    )
    if expected is None or expected.model_dump(mode="json") != record.model_dump(mode="json"):
        raise ValueError("preflight_vector_record_mismatch")
    inference_hash = _sha256_bytes(build_structural_inference_text(record).encode("utf-8"))
    if (
        receipt.get("record_id") != record.record_id
        or receipt.get("source_sha256") != record.content_sha256
        or receipt.get("inference_text_sha256") != inference_hash
        or row.get("inference_text_sha256") != inference_hash
    ):
        raise ValueError("preflight_vector_inference_hash_mismatch")
    dense = _finite_vector(row.get("values"), dimension=1024)
    observed_norm = _nonnegative_number(receipt.get("l2_norm"), "preflight_l2_norm")
    actual_norm = math.sqrt(sum(item * item for item in dense))
    if not math.isclose(observed_norm, actual_norm, rel_tol=1e-5, abs_tol=1e-5):
        raise ValueError("preflight_vector_norm_mismatch")
    return {
        "record_id": record.record_id,
        "inference_text_sha256": inference_hash,
        "dense": dense,
    }


def _write_failure_receipt(output: Path, phase: str, error: BaseException) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = output.with_name(f"{output.name}.failure-{stamp}.json")
    receipt = {
        "schema_version": "vietlex-corpus-migration-vector-failure-v1",
        "phase": phase,
        "error_type": type(error).__name__,
        "status": "failed",
    }
    try:
        with path.open("xb") as stream:
            stream.write(_json_bytes(receipt, pretty=True))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        # A same-second retry retains the earlier immutable receipt.
        return


async def prepare_vectors(
    *,
    plan_dir: Path,
    document_id: int,
    output: Path,
    settings: Settings | None = None,
    provider_factory: Callable[..., Any] | None = None,
    preflight_receipt: Path | None = None,
    preflight_vector: Path | None = None,
    allow_paid_provider: bool = False,
) -> dict[str, Any]:
    """Prepare one document's dense/sparse vectors; writes only local files."""
    bundle = MigrationBundle(plan_dir)
    if document_id not in bundle.documents:
        raise ValueError("document_not_in_plan")
    settings = settings or get_settings()
    if settings.USE_LEGACY_FREE_PIPELINE:
        raise PermissionError("legacy_pipeline_blocks_vertex_before_client_creation")
    if (
        settings.VERTEX_EMBEDDING_MODEL != "gemini-embedding-2"
        or settings.VERTEX_QDRANT_VECTOR_SIZE != 1024
        or settings.VERTEX_QDRANT_COLLECTION_NAME != "vietlex-legal-rag-v3-vertex-1024"
        or settings.VERTEX_QDRANT_MAX_CHUNKS_PER_DOCUMENT != 16
        or settings.V3_AVERAGE_SPARSE_DOCUMENT_LENGTH != _SPARSE_AVERAGE
    ):
        raise ValueError("configured_embedding_contract_mismatch")
    output = Path(output).resolve()
    if output.is_relative_to(bundle.plan_dir):
        raise ValueError("vector_output_must_be_outside_plan")
    output.parent.mkdir(parents=True, exist_ok=True)
    header = _vector_header(bundle, document_id)
    expected_records = bundle.records_for(document_id)
    encoder = FastSparseEncoder(
        average_document_length=_SPARSE_AVERAGE,
        max_nonzero_terms=_SPARSE_MAX_NONZERO,
    )
    reused = _load_preflight_vector(
        bundle,
        document_id,
        preflight_receipt,
        preflight_vector,
    )

    if output.exists():
        existing_rows = _read_jsonl(output, "prepared_vectors")
        if not existing_rows or existing_rows[0] != header:
            raise ValueError("prepared_vectors_header_mismatch")
        if len(existing_rows) - 1 > len(expected_records):
            raise ValueError("prepared_vectors_exceeds_document_scope")
        for row, record in zip(existing_rows[1:], expected_records, strict=False):
            if row.get("type") != "vector":
                raise ValueError("prepared_vectors_row_invalid")
            _validate_vector_entry(row, record)
    else:
        with output.open("xb") as stream:
            stream.write(_json_bytes(header))
            stream.flush()
            os.fsync(stream.fileno())
        existing_rows = [header]

    existing_ids = {row.get("record_id") for row in existing_rows[1:]}
    prefix_ids = [record.record_id for record in expected_records[: len(existing_ids)]]
    if [row.get("record_id") for row in existing_rows[1:]] != prefix_ids:
        raise ValueError("prepared_vectors_checkpoint_order_mismatch")
    if len(existing_ids) != len(existing_rows) - 1:
        raise ValueError("prepared_vectors_duplicate_id")

    provider = None
    factory = provider_factory
    provider_calls = 0
    preflight_reused_count = 0
    current_phase = "prepare_local_vector"
    try:
        for record in expected_records[len(existing_ids) :]:
            inference_text = build_structural_inference_text(record)
            inference_hash = _sha256_bytes(inference_text.encode("utf-8"))
            if reused is not None and reused["record_id"] == record.record_id and reused["inference_text_sha256"] == inference_hash:
                dense = reused["dense"]
                preflight_reused_count += 1
            else:
                if not allow_paid_provider:
                    raise PermissionError("allow_paid_provider_required")
                if provider is None:
                    current_phase = "create_vertex_provider"
                    if factory is None:
                        from app.services.vertex_ai import VertexAIProvider

                        factory = VertexAIProvider
                    provider_settings = settings.model_copy(update={"VERTEX_MAX_RETRIES": 0})
                    provider = factory(settings=provider_settings)
                current_phase = "vertex_embed_document"
                result = await provider.embed_document(
                    inference_text,
                    title=record.title,
                    output_dimensionality=1024,
                )
                provider_calls += 1
                dense = _finite_vector(list(result.values), dimension=1024)
                if getattr(result, "output_dimensionality", 1024) != 1024:
                    raise ValueError("dense_vector_dimension_mismatch")
            sparse = encoder.encode_document(inference_text)
            sparse_indices, sparse_weights = _sparse_values(
                list(sparse.indices),
                list(sparse.values),
            )
            entry = {
                "type": "vector",
                "record_id": record.record_id,
                "inference_text_sha256": inference_hash,
                "dense": dense,
                "sparse_indices": sparse_indices,
                "sparse_values": sparse_weights,
            }
            _validate_vector_entry(entry, record)
            with output.open("ab") as stream:
                stream.write(_json_bytes(entry))
                stream.flush()
                os.fsync(stream.fileno())
            existing_ids.add(record.record_id)
        if existing_ids != {record.record_id for record in expected_records}:
            raise ValueError("prepared_vectors_incomplete")
    except Exception as error:
        _write_failure_receipt(output, current_phase, error)
        raise
    return {
        "document_id": document_id,
        "prepared_vectors": len(expected_records),
        "output": str(output),
        "plan_sha256": bundle.plan_sha256,
        "provider_calls": provider_calls,
        "preflight_vectors_reused": preflight_reused_count,
        "remote_writes": False,
    }


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("capacity_timestamp_invalid")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("capacity_timestamp_invalid") from error
    if stamp.tzinfo is None:
        raise ValueError("capacity_timestamp_invalid")
    return stamp.astimezone(timezone.utc)


def _nonnegative_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
        raise ValueError(f"capacity_{label}_invalid")
    return float(value)


def validate_capacity(
    *,
    bundle: MigrationBundle,
    receipt_path: Path,
    estimate_path: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify fresh live evidence and the plan-bound conservative 80% gate."""
    receipt_path = Path(receipt_path)
    estimate_path = Path(estimate_path)
    receipt = _read_json(receipt_path, "capacity_receipt")
    estimate = _read_json(estimate_path, "capacity_estimate")
    observed = _parse_timestamp(receipt.get("observed_at_utc"))
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = (now - observed).total_seconds()
    if age < -_CAPACITY_FUTURE_SKEW_SECONDS:
        raise ValueError("capacity_receipt_from_future")
    if age > _CAPACITY_MAX_AGE_SECONDS:
        raise ValueError("capacity_receipt_stale")
    if estimate.get("physical_receipt_sha256") != _sha256_file(receipt_path):
        raise ValueError("capacity_estimate_receipt_hash_mismatch")
    if (
        receipt.get("evidence_level") != "live authenticated UI; read-only SQL"
        or estimate.get("scope") != "conservative planning assumptions, not measured growth or hard runtime quota enforcement"
        or estimate.get("plan_sha256") != bundle.plan_sha256
        or estimate.get("ceiling_fraction") != _CAPACITY_CEILING
        or estimate.get("canary_required") is not True
        or estimate.get("remote_writes") is not False
        or estimate.get("preparation_gate") is not True
        or not _valid_hash(estimate.get("physical_receipt_sha256"))
    ):
        raise ValueError("capacity_estimate_contract_mismatch")
    summary = bundle.summary
    supabase_allowance = 4 * summary["serialized_supabase_upserts_json_bytes"]
    qdrant_allowance = 8 * (
        summary["serialized_body_qdrant_points_json_bytes"]
        + summary["serialized_new_structural_payload_bytes"]
        + summary["dense_vector_bytes_lower_bound"]
    )
    if (
        estimate.get("supabase_estimated_transient_allowance_bytes") != supabase_allowance
        or estimate.get("qdrant_estimated_transient_allowance_bytes") != qdrant_allowance
    ):
        raise ValueError("capacity_estimate_formula_mismatch")

    qdrant = receipt.get("qdrant")
    supabase = receipt.get("supabase")
    if not isinstance(qdrant, dict) or not isinstance(supabase, dict) or qdrant.get("status") != "HEALTHY":
        raise ValueError("capacity_receipt_status_invalid")
    disk_used_gib = _nonnegative_number(qdrant.get("disk_used_gib_displayed"), "qdrant_disk_used")
    disk_quota_gib = _nonnegative_number(qdrant.get("disk_quota_gib_displayed"), "qdrant_disk_quota")
    ram_used_mib = _nonnegative_number(qdrant.get("ram_used_mib_displayed"), "qdrant_ram_used")
    ram_quota_gib = _nonnegative_number(qdrant.get("ram_quota_gib_displayed"), "qdrant_ram_quota")
    sql_sum = _nonnegative_number(supabase.get("database_sum_bytes_select"), "supabase_sql_bytes")
    sql_dashboard_mb = _nonnegative_number(supabase.get("dashboard_database_mb_displayed"), "supabase_dashboard_bytes")
    sql_quota_mb = _nonnegative_number(supabase.get("dashboard_quota_mb_displayed"), "supabase_quota")
    sql_conservative = _nonnegative_number(
        supabase.get("conservative_baseline_bytes_for_gate"),
        "supabase_conservative_baseline",
    )
    disk_used_bytes = disk_used_gib * (1024**3)
    disk_quota_bytes = disk_quota_gib * (1024**3)
    ram_used_bytes = ram_used_mib * (1024**2)
    ram_quota_bytes = ram_quota_gib * (1024**3)
    sql_used_bytes = max(sql_sum, sql_dashboard_mb * 1_000_000, sql_conservative)
    sql_quota_bytes = sql_quota_mb * 1_000_000
    if min(disk_quota_bytes, ram_quota_bytes, sql_quota_bytes) <= 0:
        raise ValueError("capacity_quota_invalid")
    if (
        disk_used_bytes + qdrant_allowance > _CAPACITY_CEILING * disk_quota_bytes
        or ram_used_bytes + qdrant_allowance > _CAPACITY_CEILING * ram_quota_bytes
        or sql_used_bytes + supabase_allowance > _CAPACITY_CEILING * sql_quota_bytes
    ):
        raise ValueError("capacity_safety_ceiling_exceeded")
    return {
        "receipt_sha256": _sha256_file(receipt_path),
        "estimate_sha256": _sha256_file(estimate_path),
        "observed_at_utc": observed.isoformat().replace("+00:00", "Z"),
        "age_seconds": round(max(0.0, age), 3),
        "observed_datetime_utc": observed.isoformat().replace("+00:00", "Z"),
        "ceiling_fraction": _CAPACITY_CEILING,
        "qdrant_estimated_transient_allowance_bytes": qdrant_allowance,
        "supabase_estimated_transient_allowance_bytes": supabase_allowance,
        "qdrant_disk_projected_bytes": round(disk_used_bytes + qdrant_allowance),
        "qdrant_disk_ceiling_bytes": round(_CAPACITY_CEILING * disk_quota_bytes),
        "qdrant_ram_projected_bytes": round(ram_used_bytes + qdrant_allowance),
        "qdrant_ram_ceiling_bytes": round(_CAPACITY_CEILING * ram_quota_bytes),
        "supabase_projected_bytes": round(sql_used_bytes + supabase_allowance),
        "supabase_ceiling_bytes": round(_CAPACITY_CEILING * sql_quota_bytes),
        "canary_required": True,
    }


def _status_value(value: object) -> str | None:
    raw = getattr(value, "value", value)
    return str(raw).lower() if raw is not None else None


class RemoteStores:
    """Small adapter over the repository's existing Qdrant/Supabase APIs."""

    def __init__(self, settings: Settings) -> None:
        import httpx

        from app.ingestion.structural_qdrant import create_structural_qdrant_client

        self._settings = settings
        self._http = httpx.Client(
            verify=system_ssl_context(),
            trust_env=False,
            timeout=httpx.Timeout(30.0),
        )
        self._supabase_root = settings.SUPABASE_URL.rstrip("/") + "/rest/v1/legal_documents"
        self._supabase_headers = {
            "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
            "authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        }
        self._uploader = SupabaseFullDocUploader(
            url=settings.SUPABASE_URL,
            service_role_key=settings.SUPABASE_SERVICE_ROLE_KEY,
            client=self._http,
        )
        self._qdrant = create_structural_qdrant_client(settings)
        self._contract = VertexQdrantContract(
            collection_name=settings.VERTEX_QDRANT_COLLECTION_NAME,
            embedding_model=settings.VERTEX_EMBEDDING_MODEL,
            vector_size=settings.VERTEX_QDRANT_VECTOR_SIZE,
        )
        self._v3_inventory: dict[int, set[str | int]] | None = None
        self._v3_point_owners: dict[str | int, int] = {}

    def validate_contract(self) -> None:
        info = self._qdrant.get_collection(self._contract.collection_name)
        vectors = info.config.params.vectors
        sparse = info.config.params.sparse_vectors or {}
        dense = vectors.get(self._contract.dense_vector_name) if isinstance(vectors, dict) else None
        distance = _status_value(getattr(dense, "distance", None)) if dense is not None else None
        if dense is None or int(dense.size) != 1024 or distance not in {"cosine", "distance.cosine"}:
            raise ValueError("v3_qdrant_dense_schema_mismatch")
        if self._contract.sparse_vector_name not in sparse:
            raise ValueError("v3_qdrant_sparse_schema_mismatch")
        body = self._qdrant.get_collection(self._settings.QDRANT_FULL_DOC_BODY_COLLECTION)
        body_vectors = body.config.params.vectors
        if body_vectors not in ({}, None):
            raise ValueError("body_qdrant_payload_only_schema_mismatch")

    def get_supabase(self, document_id: int) -> dict[str, Any] | None:
        response = self._http.get(
            self._supabase_root,
            headers=self._supabase_headers,
            params={"select": "*", "document_id": f"eq.{document_id}"},
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list) or len(rows) > 1:
            raise ValueError("supabase_single_row_read_invalid")
        if not rows:
            return None
        if not isinstance(rows[0], dict) or rows[0].get("document_id") != document_id:
            raise ValueError("supabase_row_identity_mismatch")
        return rows[0]

    def _retrieve(self, collection: str, ids: Sequence[str | int]) -> list[dict[str, Any]]:
        if not ids:
            return []
        records = self._qdrant.retrieve(
            collection_name=collection,
            ids=list(ids),
            with_payload=True,
            with_vectors=True,
        )
        return [_point_dict(point) for point in records]

    def get_body(self, document_id: int) -> dict[str, Any] | None:
        points = self._retrieve(self._settings.QDRANT_FULL_DOC_BODY_COLLECTION, [document_id])
        if len(points) > 1:
            raise ValueError("body_qdrant_duplicate_id")
        return points[0] if points else None

    def v3_retrieve(self, ids: list[str]) -> list[dict[str, Any]]:
        return self._retrieve(self._contract.collection_name, ids)

    def _load_v3_inventory(self) -> None:
        if self._v3_inventory is not None:
            return
        documents: dict[int, set[str | int]] = defaultdict(set)
        owners: dict[str | int, int] = {}
        offset: object | None = None
        seen_offsets: set[object] = set()
        for page_index in range(_V3_INVENTORY_MAX_PAGES):
            kwargs: dict[str, Any] = {
                "collection_name": self._contract.collection_name,
                "limit": _V3_INVENTORY_PAGE_SIZE,
                "with_payload": ["document_id"],
                "with_vectors": False,
            }
            if offset is not None:
                kwargs["offset"] = offset
            page, next_offset = self._qdrant.scroll(**kwargs)
            if not isinstance(page, (list, tuple)) or len(page) > _V3_INVENTORY_PAGE_SIZE:
                raise ValueError("v3_inventory_page_invalid")
            if next_offset is not None and (next_offset == offset or next_offset in seen_offsets):
                raise ValueError("v3_inventory_offset_repeated")
            for raw_point in page:
                raw = _plain(raw_point)
                if not isinstance(raw, dict):
                    raise ValueError("v3_inventory_point_invalid")
                point = _point_dict(
                    {
                        "id": raw.get("id"),
                        "payload": raw.get("payload"),
                        "vector": {},
                    }
                )
                document_id = point["payload"].get("document_id")
                if not _positive_id(document_id):
                    raise ValueError("v3_inventory_document_id_invalid")
                point_id = point["id"]
                if point_id in owners:
                    raise ValueError("v3_inventory_duplicate_point_id")
                owners[point_id] = document_id
                documents[document_id].add(point_id)
            if next_offset is None:
                self._v3_inventory = dict(documents)
                self._v3_point_owners = owners
                return
            if not page:
                raise ValueError("v3_inventory_empty_page_with_offset")
            seen_offsets.add(next_offset)
            offset = next_offset
        raise ValueError("v3_inventory_page_limit_exceeded")

    def _track_v3_upsert(self, points: list[dict[str, Any]]) -> None:
        self._load_v3_inventory()
        assert self._v3_inventory is not None
        for raw_point in points:
            point = _point_dict(raw_point)
            document_id = point["payload"].get("document_id")
            if not _positive_id(document_id):
                raise ValueError("v3_upsert_document_id_invalid")
            owner = self._v3_point_owners.get(point["id"])
            if owner is not None and owner != document_id:
                raise ValueError("v3_upsert_point_id_owned_by_other_document")
            self._v3_point_owners[point["id"]] = document_id
            self._v3_inventory.setdefault(document_id, set()).add(point["id"])

    def v3_for_document(self, document_id: int) -> list[dict[str, Any]]:
        if not _positive_id(document_id):
            raise ValueError("v3_document_id_invalid")
        self._load_v3_inventory()
        assert self._v3_inventory is not None
        point_ids = self._v3_inventory.get(document_id, set())
        if len(point_ids) > _MAX_DOCUMENT_POINT_UNION:
            raise ValueError("v3_document_point_union_limit_exceeded")
        ordered_ids = sorted(point_ids, key=lambda item: (type(item).__name__, str(item)))
        points = self._retrieve(self._contract.collection_name, ordered_ids)
        by_id = {point["id"]: point for point in points}
        if len(by_id) != len(points) or set(by_id) - point_ids:
            raise ValueError("v3_document_retrieved_id_mismatch")
        if any(point["payload"].get("document_id") != document_id for point in points):
            raise ValueError("v3_document_retrieved_owner_mismatch")
        return points

    def upsert_v3(self, points: list[dict[str, Any]]) -> None:
        from qdrant_client import models

        self._track_v3_upsert(points)
        built = [
            models.PointStruct(
                id=point["id"],
                vector={
                    "dense": point["vector"]["dense"],
                    "sparse": models.SparseVector(
                        indices=point["vector"]["sparse"]["indices"],
                        values=point["vector"]["sparse"]["values"],
                    ),
                },
                payload=point["payload"],
            )
            for point in points
        ]
        result = self._qdrant.upsert(
            collection_name=self._contract.collection_name,
            points=built,
            wait=True,
        )
        if _status_value(getattr(result, "status", None)) != "completed":
            raise RuntimeError("qdrant_v3_upsert_not_acknowledged")

    def upsert_supabase(self, row: dict[str, Any]) -> None:
        report = self._uploader.upsert_rows([row])
        if report.uploaded_rows != 1:
            raise RuntimeError("supabase_upsert_not_acknowledged")

    def upsert_body(self, point: dict[str, Any]) -> None:
        from qdrant_client import models

        result = self._qdrant.upsert(
            collection_name=self._settings.QDRANT_FULL_DOC_BODY_COLLECTION,
            points=[
                models.PointStruct(
                    id=point["id"],
                    vector={},
                    payload=point["payload"],
                )
            ],
            wait=True,
        )
        if _status_value(getattr(result, "status", None)) != "completed":
            raise RuntimeError("qdrant_body_upsert_not_acknowledged")

    def delete_v3(self, ids: list[str]) -> None:
        from qdrant_client import models

        if not ids:
            return
        self._load_v3_inventory()
        if any(point_id not in self._v3_point_owners for point_id in ids):
            raise ValueError("v3_delete_unknown_point_id")
        result = self._qdrant.delete(
            collection_name=self._contract.collection_name,
            points_selector=models.PointIdsList(points=ids),
            wait=True,
        )
        if _status_value(getattr(result, "status", None)) != "completed":
            raise RuntimeError("qdrant_v3_delete_not_acknowledged")

    def delete_supabase(self, document_id: int) -> None:
        response = self._http.delete(
            self._supabase_root,
            headers={**self._supabase_headers, "prefer": "return=representation"},
            params={"document_id": f"eq.{document_id}"},
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("document_id") != document_id:
            raise RuntimeError("supabase_delete_not_acknowledged")

    def delete_body(self, document_id: int) -> None:
        from qdrant_client import models

        result = self._qdrant.delete(
            collection_name=self._settings.QDRANT_FULL_DOC_BODY_COLLECTION,
            points_selector=models.PointIdsList(points=[document_id]),
            wait=True,
        )
        if _status_value(getattr(result, "status", None)) != "completed":
            raise RuntimeError("qdrant_body_delete_not_acknowledged")

    def close(self) -> None:
        self._http.close()
        self._qdrant.close()


def _validate_storage_settings(settings: Settings) -> None:
    if settings.USE_LEGACY_FREE_PIPELINE:
        raise PermissionError("legacy_pipeline_blocks_v3_storage_before_client_creation")
    if (
        settings.VERTEX_EMBEDDING_MODEL != "gemini-embedding-2"
        or settings.VERTEX_QDRANT_COLLECTION_NAME != "vietlex-legal-rag-v3-vertex-1024"
        or settings.VERTEX_QDRANT_VECTOR_SIZE != 1024
        or settings.VERTEX_QDRANT_MAX_CHUNKS_PER_DOCUMENT != 16
        or settings.V3_AVERAGE_SPARSE_DOCUMENT_LENGTH != _SPARSE_AVERAGE
    ):
        raise ValueError("configured_embedding_contract_mismatch")
    if not settings.QDRANT_URL or not settings.QDRANT_API_KEY:
        raise ValueError("qdrant_credentials_missing")
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise ValueError("supabase_credentials_missing")
    if not settings.SUPABASE_SERVICE_ROLE_KEY.startswith("sb_secret_"):
        raise ValueError("supabase_service_role_key_invalid")


class _Journal:
    def __init__(self, path: Path, *, create: bool) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events: list[dict[str, Any]] = []
        if self.path.exists():
            try:
                self.events = [
                    json.loads(line)
                    for line in self.path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise ValueError("migration_journal_invalid") from error
        elif not create:
            raise FileNotFoundError("migration_journal_missing")

    def append(self, event: str, **fields: Any) -> None:
        row = {
            "schema_version": "vietlex-corpus-migration-journal-v1",
            "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "event": event,
            **fields,
        }
        with self.path.open("ab") as stream:
            stream.write(_json_bytes(row))
            stream.flush()
            os.fsync(stream.fileno())
        self.events.append(row)

    def last(self, event: str) -> dict[str, Any] | None:
        return next((row for row in reversed(self.events) if row.get("event") == event), None)

    def state(self) -> str | None:
        for row in reversed(self.events):
            event = row.get("event")
            if event in {"complete", "rollback_complete", "rollback_failed", "failure"}:
                return event
        return None


def _desired_points(bundle: MigrationBundle, document_id: int, vectors: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    contract = VertexQdrantContract()
    result: list[dict[str, Any]] = []
    for record in bundle.records_for(document_id):
        vector = vectors[record.record_id]
        sparse = SimpleNamespace(
            indices=vector["sparse_indices"],
            values=vector["sparse_values"],
        )
        point = build_vertex_point(
            record,
            dense_vector=vector["dense"],
            sparse_vector=sparse,
            contract=contract,
        )
        result.append(_point_dict(point))
    return result


def _matches_new_row(actual: object, expected: dict[str, Any]) -> bool:
    if not isinstance(actual, dict):
        return False
    extras = set(actual) - set(expected)
    return (
        extras <= {"uploaded_at"}
        and all(actual.get(key) == value for key, value in expected.items())
        and _sha256_bytes(str(actual.get("content", "")).encode("utf-8")) == actual.get("content_sha256")
    )


def _check_initial_state(
    *,
    bundle: MigrationBundle,
    backups: MigrationBackups,
    storage: Any,
    document_id: int,
    desired_points: list[dict[str, Any]],
) -> None:
    document = bundle.documents[document_id]
    expected_old_ids = set(document["old_structural_point_ids"])
    current_points = [_point_dict(point) for point in storage.v3_for_document(document_id)]
    current_ids = [point["id"] for point in current_points]
    if len(current_ids) != len(set(current_ids)):
        raise ValueError("v3_current_duplicate_point_id")
    current_by_id = {point["id"]: point for point in current_points}
    if document["action"] == "insert_absent_candidate":
        if (
            storage.get_supabase(document_id) is not None
            or storage.get_body(document_id) is not None
            or current_points
        ):
            raise ValueError("candidate_collision")
    else:
        if set(current_ids) != expected_old_ids:
            raise ValueError("affected_v3_point_set_drift")
        for point_id in expected_old_ids:
            if not _point_matches(current_by_id[point_id], backups.v3_points[point_id]):
                raise ValueError("affected_v3_backup_drift")
        if storage.get_supabase(document_id) != backups.supabase_rows[document_id]:
            raise ValueError("affected_supabase_backup_drift")
        if _point_dict(storage.get_body(document_id)) != backups.body_points[document_id]:
            raise ValueError("affected_body_backup_drift")

    new_ids = [point["id"] for point in desired_points]
    if len(new_ids) != len(set(new_ids)):
        raise ValueError("new_v3_point_id_duplicate")
    remote_new_points = storage.v3_retrieve(new_ids)
    remote_new_by_id = {_point_id(point): _point_dict(point) for point in remote_new_points}
    if len(remote_new_by_id) != len(remote_new_points):
        raise ValueError("new_v3_point_id_collision")
    allowed_existing = expected_old_ids & set(new_ids)
    if set(remote_new_by_id) - allowed_existing:
        raise ValueError("new_v3_point_id_collision")
    for point_id, point in remote_new_by_id.items():
        if not _point_matches(point, backups.v3_points[point_id]):
            raise ValueError("new_v3_point_id_collision")


def _verify_new_state(
    *,
    bundle: MigrationBundle,
    backups: MigrationBackups,
    storage: Any,
    document_id: int,
    desired_points: list[dict[str, Any]],
    allow_superseded_old: bool = False,
) -> None:
    expected_by_id = {point["id"]: point for point in desired_points}
    current_points = [_point_dict(point) for point in storage.v3_for_document(document_id)]
    current_by_id = {point["id"]: point for point in current_points}
    old_ids = set(bundle.documents[document_id]["old_structural_point_ids"])
    expected_ids = set(expected_by_id)
    allowed_ids = expected_ids | (old_ids - expected_ids if allow_superseded_old else set())
    if len(current_by_id) != len(current_points) or set(current_by_id) != allowed_ids:
        raise ValueError("readback_v3_point_set_mismatch")
    for point_id, expected in expected_by_id.items():
        if not _point_matches(current_by_id[point_id], expected):
            raise ValueError("readback_v3_payload_or_vector_mismatch")
    if allow_superseded_old:
        for point_id in old_ids - expected_ids:
            if not _point_matches(current_by_id[point_id], backups.v3_points[point_id]):
                raise ValueError("readback_old_v3_point_mismatch")
    row = storage.get_supabase(document_id)
    if not _matches_new_row(row, bundle.rows[document_id]):
        raise ValueError("readback_supabase_mismatch")
    body = storage.get_body(document_id)
    if body is None or _point_dict(body) != _point_dict(bundle.body_points[document_id]):
        raise ValueError("readback_body_mismatch")


def _verify_old_state(
    *,
    backups: MigrationBackups,
    storage: Any,
    document_id: int,
) -> None:
    current_points = [_point_dict(point) for point in storage.v3_for_document(document_id)]
    expected_ids = set(
        point_id
        for point_id, point in backups.v3_points.items()
        if point["payload"].get("document_id") == document_id
    )
    by_id = {point["id"]: point for point in current_points}
    if len(by_id) != len(current_points) or set(by_id) != expected_ids:
        raise RuntimeError("rollback_v3_point_set_mismatch")
    for point_id in expected_ids:
        if not _point_matches(by_id[point_id], backups.v3_points[point_id]):
            raise RuntimeError("rollback_v3_backup_readback_mismatch")
    if storage.get_supabase(document_id) != backups.supabase_rows[document_id]:
        raise RuntimeError("rollback_supabase_backup_readback_mismatch")
    if _point_dict(storage.get_body(document_id)) != backups.body_points[document_id]:
        raise RuntimeError("rollback_body_backup_readback_mismatch")


def _verify_candidate_absent(*, storage: Any, document_id: int) -> None:
    if (
        storage.get_supabase(document_id) is not None
        or storage.get_body(document_id) is not None
        or storage.v3_for_document(document_id)
    ):
        raise RuntimeError("rollback_candidate_remains_present")


def _compensate(
    *,
    bundle: MigrationBundle,
    backups: MigrationBackups,
    storage: Any,
    document_id: int,
    desired_points: list[dict[str, Any]],
    journal: _Journal,
) -> None:
    document = bundle.documents[document_id]
    old_ids = set(document["old_structural_point_ids"])
    new_by_id = {point["id"]: point for point in desired_points}
    current_points = [_point_dict(point) for point in storage.v3_for_document(document_id)]
    current_by_id = {point["id"]: point for point in current_points}
    if len(current_by_id) != len(current_points):
        raise RuntimeError("rollback_v3_duplicate_point_id")
    globally_retrieved = [_point_dict(point) for point in storage.v3_retrieve(sorted(new_by_id))]
    global_by_id = {point["id"]: point for point in globally_retrieved}
    if len(global_by_id) != len(globally_retrieved):
        raise RuntimeError("rollback_v3_duplicate_retrieved_id")
    for point_id, point in global_by_id.items():
        if point["payload"].get("document_id") != document_id:
            raise RuntimeError("rollback_v3_point_id_reused_by_other_document")
        allowed = []
        if point_id in old_ids:
            allowed.append(backups.v3_points[point_id])
        if point_id in new_by_id:
            allowed.append(new_by_id[point_id])
        if not any(_point_matches(point, expected) for expected in allowed):
            raise RuntimeError("rollback_v3_unknown_payload_present")
    allowed_ids = old_ids | set(new_by_id)
    if set(current_by_id) - allowed_ids:
        raise RuntimeError("rollback_v3_unknown_point_present")
    for point_id, point in current_by_id.items():
        allowed = []
        if point_id in old_ids:
            allowed.append(backups.v3_points[point_id])
        if point_id in new_by_id:
            allowed.append(new_by_id[point_id])
        if not any(_point_matches(point, expected) for expected in allowed):
            raise RuntimeError("rollback_v3_unknown_payload_present")
        if point_id in new_by_id and not _point_matches(global_by_id.get(point_id), point):
            raise RuntimeError("rollback_v3_point_readback_mismatch")

    current_row = storage.get_supabase(document_id)
    current_body = storage.get_body(document_id)
    if document["action"] == "replace_cleaned":
        if current_row not in (backups.supabase_rows[document_id],) and not _matches_new_row(current_row, bundle.rows[document_id]):
            raise RuntimeError("rollback_supabase_unknown_payload_present")
        if current_body is not None:
            body_dict = _point_dict(current_body)
            if body_dict != backups.body_points[document_id] and body_dict != _point_dict(bundle.body_points[document_id]):
                raise RuntimeError("rollback_body_unknown_payload_present")
        journal.append("rollback_phase_started", phase="restore_v3")
        old_points = [backups.v3_points[item] for item in sorted(old_ids)]
        storage.upsert_v3(old_points)
        journal.append("rollback_phase_acknowledged", phase="restore_v3", point_count=len(old_points))
        new_only_ids = sorted((set(new_by_id) - old_ids) & set(current_by_id))
        if new_only_ids:
            journal.append("rollback_phase_started", phase="remove_new_v3_ids", point_ids=new_only_ids)
            storage.delete_v3(new_only_ids)
            journal.append("rollback_phase_acknowledged", phase="remove_new_v3_ids", point_ids=new_only_ids)
        journal.append("rollback_phase_started", phase="restore_supabase")
        storage.upsert_supabase(backups.supabase_rows[document_id])
        journal.append("rollback_phase_acknowledged", phase="restore_supabase", document_id=document_id)
        journal.append("rollback_phase_started", phase="restore_body")
        storage.upsert_body(backups.body_points[document_id])
        journal.append("rollback_phase_acknowledged", phase="restore_body", document_id=document_id)
        _verify_old_state(backups=backups, storage=storage, document_id=document_id)
    else:
        if current_row is not None and not _matches_new_row(current_row, bundle.rows[document_id]):
            raise RuntimeError("rollback_candidate_supabase_unknown_payload_present")
        expected_body = _point_dict(bundle.body_points[document_id])
        if current_body is not None and _point_dict(current_body) != expected_body:
            raise RuntimeError("rollback_candidate_body_unknown_payload_present")
        new_ids_present = sorted(set(current_by_id) - old_ids)
        if new_ids_present:
            journal.append("rollback_phase_started", phase="remove_candidate_v3", point_ids=new_ids_present)
            storage.delete_v3(new_ids_present)
            journal.append("rollback_phase_acknowledged", phase="remove_candidate_v3", point_ids=new_ids_present)
        if current_row is not None:
            journal.append("rollback_phase_started", phase="remove_candidate_supabase")
            storage.delete_supabase(document_id)
            journal.append("rollback_phase_acknowledged", phase="remove_candidate_supabase", document_id=document_id)
        if current_body is not None:
            journal.append("rollback_phase_started", phase="remove_candidate_body")
            storage.delete_body(document_id)
            journal.append("rollback_phase_acknowledged", phase="remove_candidate_body", document_id=document_id)
        _verify_candidate_absent(storage=storage, document_id=document_id)
    journal.append("rollback_complete", document_id=document_id)


def _journal_path(journal_dir: Path, document_id: int) -> Path:
    if not _positive_id(document_id):
        raise ValueError("document_id_must_be_positive")
    return Path(journal_dir).resolve() / f"{document_id}.jsonl"


def _ensure_new_journal(path: Path) -> _Journal:
    journal = _Journal(path, create=True)
    if journal.events:
        raise MigrationError("journal_exists_recovery_required")
    return journal


def _safe_failure_code(error: BaseException) -> str:
    if isinstance(error, (MigrationError, ValueError, PermissionError)):
        value = str(error)
        if value and re.fullmatch(r"[A-Za-z0-9_:-]{1,160}", value):
            return value
    return type(error).__name__


def _storage_factory(settings: Settings) -> RemoteStores:
    return RemoteStores(settings)


def _assert_deleted_ids_absent(storage: Any, point_ids: list[str]) -> None:
    if point_ids and storage.v3_retrieve(point_ids):
        raise ValueError("superseded_v3_ids_remain_after_delete")


def _successful_operations(journal_dir: Path, plan_sha256: str) -> list[dict[str, Any]]:
    root = Path(journal_dir)
    if not root.exists():
        return []
    successes: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for path in sorted(root.glob("*.jsonl")):
        rows = _read_jsonl(path, "migration_journal")
        if not rows or rows[-1].get("event") != "complete":
            continue
        start = next((row for row in rows if row.get("event") == "start"), None)
        complete = rows[-1]
        if not isinstance(start, dict) or start.get("plan_sha256") != plan_sha256:
            continue
        document_id = start.get("document_id")
        if not _positive_id(document_id) or document_id in seen_ids:
            raise ValueError("canary_journal_identity_invalid")
        seen_ids.add(document_id)
        successes.append(
            {
                "document_id": document_id,
                "action": start.get("action"),
                "completed_at": _parse_timestamp(complete.get("timestamp_utc")),
            }
        )
    return successes


def _canary_progress(
    *,
    bundle: MigrationBundle,
    document_id: int,
    journal_dir: Path,
    capacity: dict[str, Any],
) -> str:
    """Require a clean write, a small addition, then a measured capacity gate."""
    operations = _successful_operations(journal_dir, bundle.plan_sha256)
    current_action = bundle.documents[document_id]["action"]
    completed_ids = {item["document_id"] for item in operations}
    if document_id in completed_ids:
        raise ValueError("document_already_completed")
    if any(
        item["document_id"] not in bundle.documents
        or item["action"] != bundle.documents[item["document_id"]]["action"]
        for item in operations
    ):
        raise ValueError("canary_journal_scope_invalid")
    ordered = sorted(operations, key=lambda item: item["completed_at"])
    if not operations:
        if current_action != "replace_cleaned":
            raise ValueError("cleaned_document_canary_required_first")
        return "cleaned_replacement_canary"
    if len(operations) == 1:
        if ordered[0]["action"] != "replace_cleaned" or current_action != "insert_absent_candidate":
            raise ValueError("small_addition_canary_required_after_cleaning")
        candidate_ids = bundle.candidate_ids
        canary_id = min(
            candidate_ids,
            key=lambda item: (
                bundle.documents[item]["supabase_upsert_json_bytes"]
                + bundle.documents[item]["body_qdrant_point_json_bytes"]
                + bundle.documents[item]["new_structural_payload_json_bytes"]
                + len(bundle.documents[item]["new_structural_point_ids"]) * 1024 * 4,
                item,
            ),
        )
        if document_id != canary_id:
            raise ValueError("smallest_addition_canary_required")
        return "small_absent_addition_canary"
    candidate_ids = bundle.candidate_ids
    canary_id = min(
        candidate_ids,
        key=lambda item: (
            bundle.documents[item]["supabase_upsert_json_bytes"]
            + bundle.documents[item]["body_qdrant_point_json_bytes"]
            + bundle.documents[item]["new_structural_payload_json_bytes"]
            + len(bundle.documents[item]["new_structural_point_ids"]) * 1024 * 4,
            item,
        ),
    )
    if ordered[0]["action"] != "replace_cleaned" or (
        ordered[1]["action"] != "insert_absent_candidate"
        or ordered[1]["document_id"] != canary_id
    ):
        raise ValueError("clean_and_addition_canaries_required")
    canary_completed_at = ordered[1]["completed_at"]
    observed = _parse_timestamp(capacity.get("observed_datetime_utc"))
    if observed <= canary_completed_at:
        raise ValueError("post_canary_capacity_receipt_required")
    return "post_canary_capacity_verified"


def apply_one(
    *,
    plan_dir: Path,
    vectors_path: Path,
    backup_dir: Path,
    capacity_receipt: Path,
    capacity_estimate: Path,
    document_id: int,
    journal_dir: Path,
    settings: Settings | None = None,
    storage: Any | None = None,
    storage_factory: Callable[[Settings], Any] | None = None,
    allow_storage_write: bool = False,
) -> dict[str, Any]:
    """Apply exactly one approved document after fresh cross-store readback."""
    if not allow_storage_write:
        raise PermissionError("allow_storage_write_required")
    journal = _ensure_new_journal(_journal_path(journal_dir, document_id))
    phase = "load_local_plan"
    storage_writes_started = False
    owned_storage = False
    try:
        bundle = MigrationBundle(plan_dir)
        if document_id not in bundle.documents:
            raise ValueError("document_not_in_plan")
        backups = MigrationBackups(bundle, backup_dir)
        vectors = _load_vector_artifact(bundle, document_id, vectors_path)
        desired_points = _desired_points(bundle, document_id, vectors)
        settings = settings or get_settings()
        capacity = validate_capacity(
            bundle=bundle,
            receipt_path=capacity_receipt,
            estimate_path=capacity_estimate,
        )
        canary_progress = _canary_progress(
            bundle=bundle,
            document_id=document_id,
            journal_dir=journal_dir,
            capacity=capacity,
        )
        if storage is None:
            _validate_storage_settings(settings)
        elif settings.USE_LEGACY_FREE_PIPELINE:
            raise PermissionError("legacy_pipeline_blocks_v3_storage_before_client_creation")
        journal.append(
            "start",
            plan_sha256=bundle.plan_sha256,
            backup_manifest_sha256=_sha256_file(Path(backup_dir) / "manifest.json"),
            vector_artifact_sha256=_sha256_file(vectors_path),
            document_id=document_id,
            action=bundle.documents[document_id]["action"],
            capacity_receipt_sha256=capacity["receipt_sha256"],
            capacity_estimate_sha256=capacity["estimate_sha256"],
            canary_progress=canary_progress,
            remote_writes=False,
        )
        phase = "create_storage_clients"
        if storage is None:
            factory = storage_factory or _storage_factory
            storage = factory(settings)
            owned_storage = True
        if hasattr(storage, "validate_contract"):
            phase = "validate_remote_contract"
            journal.append("phase_started", phase=phase)
            storage.validate_contract()
            journal.append("phase_acknowledged", phase=phase)
        phase = "read_initial_state"
        journal.append("phase_started", phase=phase)
        _check_initial_state(
            bundle=bundle,
            backups=backups,
            storage=storage,
            document_id=document_id,
            desired_points=desired_points,
        )
        journal.append(
            "initial_state_verified",
            document_id=document_id,
            old_content_sha256=bundle.documents[document_id]["old_content_sha256"],
            new_content_sha256=bundle.documents[document_id]["new_content_sha256"],
            old_point_ids=bundle.documents[document_id]["old_structural_point_ids"],
            new_point_ids=bundle.documents[document_id]["new_structural_point_ids"],
            candidate_absent_all_three_stores=bundle.documents[document_id]["action"] == "insert_absent_candidate",
        )

        phase = "upsert_v3_points"
        storage_writes_started = True
        journal.append("phase_started", phase=phase, point_ids=[point["id"] for point in desired_points])
        storage.upsert_v3(desired_points)
        journal.append("phase_acknowledged", phase=phase, point_ids=[point["id"] for point in desired_points])

        phase = "upsert_supabase_row"
        journal.append("phase_started", phase=phase, document_id=document_id)
        storage.upsert_supabase(bundle.rows[document_id])
        journal.append("phase_acknowledged", phase=phase, document_id=document_id)

        phase = "upsert_body_point"
        journal.append("phase_started", phase=phase, point_id=document_id)
        storage.upsert_body(_point_dict(bundle.body_points[document_id]))
        journal.append("phase_acknowledged", phase=phase, point_id=document_id)

        phase = "verify_new_readback_before_cleanup"
        journal.append("phase_started", phase=phase)
        _verify_new_state(
            bundle=bundle,
            backups=backups,
            storage=storage,
            document_id=document_id,
            desired_points=desired_points,
            allow_superseded_old=True,
        )
        journal.append("readback_verified", phase=phase)

        old_ids = set(bundle.documents[document_id]["old_structural_point_ids"])
        new_ids = set(bundle.documents[document_id]["new_structural_point_ids"])
        superseded_ids = sorted(old_ids - new_ids)
        if superseded_ids:
            phase = "delete_superseded_v3_ids"
            journal.append("phase_started", phase=phase, point_ids=superseded_ids)
            storage.delete_v3(superseded_ids)
            journal.append("phase_acknowledged", phase=phase, point_ids=superseded_ids)

        phase = "verify_final_state"
        journal.append("phase_started", phase=phase)
        _verify_new_state(
            bundle=bundle,
            backups=backups,
            storage=storage,
            document_id=document_id,
            desired_points=desired_points,
        )
        _assert_deleted_ids_absent(storage, superseded_ids)
        journal.append("complete", document_id=document_id, superseded_point_count=len(superseded_ids))
        return {
            "document_id": document_id,
            "status": "complete",
            "action": bundle.documents[document_id]["action"],
            "new_structural_points": len(desired_points),
            "superseded_structural_points_deleted": len(superseded_ids),
            "cross_store_atomicity": "not available; compensating rollback journaled",
            "remote_writes": True,
        }
    except Exception as error:
        if journal.events and journal.state() not in {"complete", "rollback_complete"}:
            journal.append(
                "failure",
                phase=phase,
                error_code=_safe_failure_code(error),
                error_type=type(error).__name__,
                document_id=document_id,
            )
        if storage_writes_started and storage is not None:
            try:
                journal.append("rollback_started", document_id=document_id, reason_phase=phase)
                _compensate(
                    bundle=bundle,
                    backups=backups,
                    storage=storage,
                    document_id=document_id,
                    desired_points=desired_points,
                    journal=journal,
                )
            except Exception as rollback_error:
                journal.append(
                    "rollback_failed",
                    document_id=document_id,
                    phase="compensation",
                    error_code=_safe_failure_code(rollback_error),
                    error_type=type(rollback_error).__name__,
                )
                raise MigrationError("apply_failed_rollback_incomplete") from None
        if isinstance(error, (ValueError, PermissionError)) and not storage_writes_started:
            raise
        if isinstance(error, MigrationError) and not storage_writes_started:
            raise
        raise MigrationError(f"migration_failed:{phase}") from None
    finally:
        if owned_storage and storage is not None and hasattr(storage, "close"):
            storage.close()


def rollback_one(
    *,
    plan_dir: Path,
    vectors_path: Path,
    backup_dir: Path,
    capacity_receipt: Path,
    capacity_estimate: Path,
    document_id: int,
    journal_dir: Path,
    settings: Settings | None = None,
    storage: Any | None = None,
    storage_factory: Callable[[Settings], Any] | None = None,
    allow_storage_write: bool = False,
) -> dict[str, Any]:
    """Restore one document only when current values match this migration."""
    if not allow_storage_write:
        raise PermissionError("allow_storage_write_required")
    journal = _Journal(_journal_path(journal_dir, document_id), create=False)
    start = journal.last("start")
    initial = journal.last("initial_state_verified")
    if not start or not initial or journal.last("rollback_complete"):
        raise MigrationError("journal_not_eligible_for_rollback")
    phase = "load_local_plan"
    owned_storage = False
    try:
        bundle = MigrationBundle(plan_dir)
        if document_id not in bundle.documents:
            raise ValueError("document_not_in_plan")
        backups = MigrationBackups(bundle, backup_dir)
        vectors = _load_vector_artifact(bundle, document_id, vectors_path)
        desired_points = _desired_points(bundle, document_id, vectors)
        document = bundle.documents[document_id]
        if (
            start.get("document_id") != document_id
            or start.get("plan_sha256") != bundle.plan_sha256
            or start.get("action") != document["action"]
            or start.get("backup_manifest_sha256") != _sha256_file(Path(backup_dir) / "manifest.json")
            or start.get("vector_artifact_sha256") != _sha256_file(vectors_path)
            or initial.get("document_id") != document_id
            or initial.get("old_content_sha256") != document["old_content_sha256"]
            or initial.get("new_content_sha256") != document["new_content_sha256"]
            or initial.get("old_point_ids") != document["old_structural_point_ids"]
            or initial.get("new_point_ids") != document["new_structural_point_ids"]
            or initial.get("candidate_absent_all_three_stores")
            != (document["action"] == "insert_absent_candidate")
        ):
            raise MigrationError("rollback_journal_binding_mismatch")
        settings = settings or get_settings()
        capacity = validate_capacity(
            bundle=bundle,
            receipt_path=capacity_receipt,
            estimate_path=capacity_estimate,
        )
        if storage is None:
            _validate_storage_settings(settings)
        elif settings.USE_LEGACY_FREE_PIPELINE:
            raise PermissionError("legacy_pipeline_blocks_v3_storage_before_client_creation")
        phase = "create_storage_clients"
        if storage is None:
            storage = (storage_factory or _storage_factory)(settings)
            owned_storage = True
        if hasattr(storage, "validate_contract"):
            phase = "validate_remote_contract"
            storage.validate_contract()
        journal.append(
            "rollback_started",
            document_id=document_id,
            plan_sha256=bundle.plan_sha256,
            capacity_receipt_sha256=capacity["receipt_sha256"],
            capacity_estimate_sha256=capacity["estimate_sha256"],
            explicit=True,
        )
        _compensate(
            bundle=bundle,
            backups=backups,
            storage=storage,
            document_id=document_id,
            desired_points=desired_points,
            journal=journal,
        )
        return {
            "document_id": document_id,
            "status": "rollback_complete",
            "remote_writes": True,
            "cross_store_atomicity": "not available; compensating rollback journaled",
        }
    except Exception as error:
        journal.append(
            "rollback_failed",
            document_id=document_id,
            phase=phase,
            error_code=_safe_failure_code(error),
            error_type=type(error).__name__,
        )
        if isinstance(error, (ValueError, PermissionError, MigrationError)):
            raise
        raise MigrationError(f"rollback_failed:{phase}") from None
    finally:
        if owned_storage and storage is not None and hasattr(storage, "close"):
            storage.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare-vectors", help="embed one planned document into a local append-only artifact")
    prepare.add_argument("--plan-dir", type=Path, required=True)
    prepare.add_argument("--document-id", type=int, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--preflight-receipt", type=Path)
    prepare.add_argument("--preflight-vector", type=Path)
    prepare.add_argument("--allow-paid-provider", action="store_true")

    for name in ("apply-one", "rollback-one"):
        command = commands.add_parser(name, help=f"{name.replace('-', ' ')} for one planned document")
        command.add_argument("--plan-dir", type=Path, required=True)
        command.add_argument("--vectors", type=Path, required=True)
        command.add_argument("--backup-dir", type=Path, required=True)
        command.add_argument("--capacity-receipt", type=Path, required=True)
        command.add_argument("--capacity-estimate", type=Path, required=True)
        command.add_argument("--document-id", type=int, required=True)
        command.add_argument("--journal-dir", type=Path, required=True)
        command.add_argument("--allow-storage-write", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "prepare-vectors":
        preflight_receipt = arguments.preflight_receipt or arguments.plan_dir.parent / "embedding-preflight-r2.json"
        preflight_vector = arguments.preflight_vector or arguments.plan_dir.parent / "embedding-preflight-vector-r2.json"
        result = asyncio.run(
            prepare_vectors(
                plan_dir=arguments.plan_dir,
                document_id=arguments.document_id,
                output=arguments.output,
                preflight_receipt=preflight_receipt,
                preflight_vector=preflight_vector,
                allow_paid_provider=arguments.allow_paid_provider,
            )
        )
    elif arguments.command == "apply-one":
        result = apply_one(
            plan_dir=arguments.plan_dir,
            vectors_path=arguments.vectors,
            backup_dir=arguments.backup_dir,
            capacity_receipt=arguments.capacity_receipt,
            capacity_estimate=arguments.capacity_estimate,
            document_id=arguments.document_id,
            journal_dir=arguments.journal_dir,
            allow_storage_write=arguments.allow_storage_write,
        )
    else:
        result = rollback_one(
            plan_dir=arguments.plan_dir,
            vectors_path=arguments.vectors,
            backup_dir=arguments.backup_dir,
            capacity_receipt=arguments.capacity_receipt,
            capacity_estimate=arguments.capacity_estimate,
            document_id=arguments.document_id,
            journal_dir=arguments.journal_dir,
            allow_storage_write=arguments.allow_storage_write,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


