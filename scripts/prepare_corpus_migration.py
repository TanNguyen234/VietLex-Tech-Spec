"""Build an immutable, provider-free plan for corpus overlay migration."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import pyarrow.parquet as pq

from app.config import get_settings
from app.ingestion.content_store import ContentStore, StoredDocument
from app.ingestion.corpus_cleaning import clean_corpus_text, verify_reconstruction
from app.ingestion.structural_qdrant import point_payload
from app.ingestion.supabase_full_doc import build_supabase_row
from app.ingestion.vertex_qdrant_migration import (
    VertexQdrantContract,
    build_vertex_records,
)
from scripts.audit_online_capacity import (
    CHUNK_MAX_TOKENS,
    CHUNK_OVERLAP_TOKENS,
    MAX_CHUNKS_PER_DOCUMENT,
)
from scripts.build_qdrant_full_doc_index import point_from_source


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OVERLAY_FILES = {
    "changes.jsonl",
    "clean-delta.parquet",
    "clean-delta.sqlite3",
    "original-delta.sqlite3",
}
_BUILDER_EXCLUDED_FLAGS = frozenset(
    {
        "empty_content",
        "encoding_damage",
        "missing_document_number",
        "missing_title",
        "missing_source_url",
    }
)


def _json_bytes(value: object, *, pretty: bool = False) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _jsonl_bytes(values: list[object]) -> bytes:
    return b"".join(_json_bytes(value) for value in values)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid_{label}") from error
    if not isinstance(value, dict):
        raise ValueError(f"invalid_{label}")
    return value


def _positive_id(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _valid_hash(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


class _OverlayStore:
    """Read changed documents from the overlay and others from the base."""

    def __init__(self, overlay: ContentStore, base: ContentStore) -> None:
        self._overlay = overlay
        self._base = base

    def get_many(self, document_ids: list[int]) -> dict[int, StoredDocument]:
        overlay = self._overlay.get_many(document_ids)
        missing = [document_id for document_id in document_ids if document_id not in overlay]
        return overlay | self._base.get_many(missing)


def _validate_overlay(clean_overlay: Path) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    if not clean_overlay.is_dir():
        raise ValueError("clean_overlay_missing")
    manifest = _read_json(clean_overlay / "manifest.json", "overlay_manifest")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != _OVERLAY_FILES:
        raise ValueError("overlay_artifact_manifest_mismatch")
    for name, entry in artifacts.items():
        if Path(name).name != name or not isinstance(entry, dict):
            raise ValueError("overlay_artifact_manifest_mismatch")
        path = clean_overlay / name
        if (
            not path.is_file()
            or path.stat().st_size != entry.get("bytes")
            or _sha256_file(path) != entry.get("sha256")
        ):
            raise ValueError(f"overlay_artifact_hash_mismatch:{name}")
    if (
        manifest.get("representation")
        != "changed-document overlay; base required; original source remains immutable"
        or manifest.get("remote_writes") is not False
        or manifest.get("legal_validity") != "UNVERIFIED"
    ):
        raise ValueError("overlay_provenance_mismatch")

    changes: dict[int, dict[str, Any]] = {}
    try:
        with (clean_overlay / "changes.jsonl").open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("invalid_overlay_change")
                document_id = row.get("document_id")
                spans = row.get("spans")
                if (
                    not _positive_id(document_id)
                    or document_id in changes
                    or not _valid_hash(row.get("base_sha256"))
                    or not _valid_hash(row.get("cleaned_sha256"))
                    or not _valid_hash(row.get("raw_parquet_sha256"))
                    or not isinstance(spans, list)
                    or not spans
                ):
                    raise ValueError("invalid_overlay_change")
                changes[document_id] = row
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid_overlay_changes") from error
    changed_count = manifest.get("changed_documents")
    if (
        not isinstance(changed_count, int)
        or changed_count != len(changes)
        or manifest.get("readback_verified_documents") != changed_count
        or changed_count <= 0
    ):
        raise ValueError("overlay_change_count_mismatch")

    parquet = pq.ParquetFile(clean_overlay / "clean-delta.parquet")
    if parquet.metadata.num_rows != changed_count:
        raise ValueError("overlay_parquet_count_mismatch")
    return manifest, changes


def _validate_inventory(
    inventory: dict[str, Any],
    settings: Any,
) -> tuple[list[int], dict[int, dict[str, Any]]]:
    dataset = inventory.get("dataset")
    online = inventory.get("online_capacity")
    candidate_inventory = inventory.get("candidate_inventory")
    if (
        not isinstance(dataset, dict)
        or dataset.get("repository") != settings.DATASET_REPOSITORY
        or dataset.get("revision") != settings.DATASET_REVISION
        or dataset.get("expected_document_count") != settings.EXPECTED_DOCUMENT_COUNT
        or not isinstance(online, dict)
        or not isinstance(candidate_inventory, dict)
    ):
        raise ValueError("online_inventory_dataset_mismatch")
    consistency = online.get("document_id_consistency")
    if (
        not isinstance(consistency, dict)
        or consistency.get("status") != "ok"
        or any(
            not isinstance(online.get(name), dict)
            or online[name].get("status") != "ok"
            for name in ("qdrant", "supabase")
        )
    ):
        raise ValueError("online_inventory_status_not_ok")

    local = candidate_inventory.get("local_store")
    selection = candidate_inventory.get("candidate_selection")
    if not isinstance(local, dict) or local.get("status") != "ok":
        raise ValueError("candidate_local_store_status_not_ok")
    if not isinstance(selection, dict):
        raise ValueError("candidate_selection_missing")
    selected = selection.get("selected_documents")
    if (
        selection.get("status") != "ok"
        or selection.get("limit") != 20
        or selection.get("selected_count") != 20
        or selection.get("selected_dataset_revision") != settings.DATASET_REVISION
        or selection.get("absent_from")
        != "union_of_qdrant_v3_body_and_supabase_document_ids"
        or selection.get("embeddings_created") is not False
        or selection.get("upload_attempted") is not False
        or not isinstance(selected, list)
        or len(selected) != 20
    ):
        raise ValueError("candidate_selection_not_verified")
    candidate_rows: dict[int, dict[str, Any]] = {}
    candidate_ids: list[int] = []
    for row in selected:
        if not isinstance(row, dict) or not _positive_id(row.get("document_id")):
            raise ValueError("invalid_candidate_row")
        document_id = row["document_id"]
        if document_id in candidate_rows:
            raise ValueError("duplicate_candidate_id")
        if (
            not _valid_hash(row.get("source_content_sha256"))
            or row.get("content_hash_verified") is not True
            or row.get("quality_flags") != []
        ):
            raise ValueError(f"candidate_unusable_quality:{document_id}")
        candidate_rows[document_id] = row
        candidate_ids.append(document_id)

    selection_hash = hashlib.sha256(
        json.dumps(candidate_ids, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if selection.get("ordered_document_ids_sha256") != selection_hash:
        raise ValueError("candidate_selection_hash_mismatch")
    side_effects = inventory.get("side_effects")
    if not isinstance(side_effects, dict) or any(
        side_effects.get(name) is not False
        for name in (
            "embeddings_created",
            "provider_sdk_clients_created",
            "remote_writes_attempted",
        )
    ):
        raise ValueError("inventory_side_effect_provenance_mismatch")
    return candidate_ids, candidate_rows


def _validate_affected(affected: dict[str, Any]) -> tuple[list[int], dict[int, str]]:
    rows = affected.get("rows")
    if (
        affected.get("scope") != "live read-only; no providers or remote writes"
        or not isinstance(rows, list)
        or len(rows) != 16
        or affected.get("online_affected_document_count") != 16
    ):
        raise ValueError("affected_online_snapshot_invalid")
    credentials = affected.get("credential_presence")
    if not isinstance(credentials, dict) or any(
        not isinstance(value, bool) for value in credentials.values()
    ):
        raise ValueError("affected_credential_presence_invalid")
    hashes: dict[int, str] = {}
    for row in rows:
        if (
            not isinstance(row, dict)
            or not _positive_id(row.get("document_id"))
            or not _valid_hash(row.get("content_sha256"))
            or row["document_id"] in hashes
        ):
            raise ValueError("invalid_affected_online_row")
        hashes[row["document_id"]] = row["content_sha256"]
    return sorted(hashes), hashes


def _validate_overlay_documents(
    clean_overlay: Path,
    changes: dict[int, dict[str, Any]],
    document_ids: list[int],
) -> tuple[ContentStore, ContentStore, dict[int, StoredDocument]]:
    original_store = ContentStore(clean_overlay / "original-delta.sqlite3")
    clean_store = ContentStore(clean_overlay / "clean-delta.sqlite3")
    originals = original_store.get_many(document_ids)
    cleaned = clean_store.get_many(document_ids)
    if set(originals) != set(document_ids) or set(cleaned) != set(document_ids):
        raise ValueError("overlay_sqlite_count_mismatch")
    for document_id in document_ids:
        change = changes[document_id]
        original = originals[document_id]
        clean = cleaned[document_id]
        result = clean_corpus_text(original.content)
        expected_spans = [asdict(span) for span in result.deletion_spans]
        if (
            original.content_sha256 != change["base_sha256"]
            or clean.content_sha256 != change["cleaned_sha256"]
            or not verify_reconstruction(original.content, result)
            or result.cleaned_text != clean.content
            or expected_spans != change["spans"]
        ):
            raise ValueError(f"overlay_cleaning_provenance_mismatch:{document_id}")

    parquet = pq.ParquetFile(clean_overlay / "clean-delta.parquet")
    matched_ids: set[int] = set()
    if not {"id", "content", "content_sha256", "base_content_sha256", "raw_parquet_sha256"}.issubset(
        set(parquet.schema_arrow.names)
    ):
        raise ValueError("overlay_parquet_schema_mismatch")
    for batch in parquet.iter_batches(batch_size=16):
        for row in batch.to_pylist():
            document_id = row.get("id")
            if document_id not in originals:
                continue
            if document_id in matched_ids:
                raise ValueError("overlay_parquet_id_mismatch")
            clean = cleaned[document_id]
            change = changes[document_id]
            if (
                row["content"] != clean.content
                or row["content_sha256"] != clean.content_sha256
                or row["base_content_sha256"] != change["base_sha256"]
                or row["raw_parquet_sha256"] != change["raw_parquet_sha256"]
            ):
                raise ValueError(f"overlay_parquet_content_mismatch:{document_id}")
            matched_ids.add(document_id)
    if matched_ids != set(document_ids):
        raise ValueError("overlay_parquet_id_mismatch")
    return original_store, clean_store, originals


def _record_groups(records: list[Any], expected_ids: list[int], label: str) -> dict[int, list[Any]]:
    grouped: dict[int, list[Any]] = defaultdict(list)
    for record in records:
        grouped[record.document_id].append(record)
    if set(grouped) != set(expected_ids) or any(not grouped[item] for item in expected_ids):
        raise ValueError(f"{label}_structural_record_coverage_mismatch")
    return dict(grouped)


def _store_documents(
    store: Any,
    document_ids: list[int],
    label: str,
) -> dict[int, StoredDocument]:
    documents = store.get_many(document_ids)
    if set(documents) != set(document_ids):
        raise ValueError(f"{label}_document_missing")
    for document_id, document in documents.items():
        if _BUILDER_EXCLUDED_FLAGS.intersection(document.quality_flags):
            raise ValueError(f"{label}_unusable_quality:{document_id}")
    return documents


def _records(
    store: Any,
    document_ids: list[int],
    *,
    settings: Any,
) -> list[Any]:
    return build_vertex_records(
        store,
        document_ids,
        repository=settings.DATASET_REPOSITORY,
        revision=settings.DATASET_REVISION,
        max_tokens=CHUNK_MAX_TOKENS,
        overlap_tokens=CHUNK_OVERLAP_TOKENS,
        max_chunks_per_document=settings.VERTEX_QDRANT_MAX_CHUNKS_PER_DOCUMENT,
    )


def _serialized_size(value: object) -> int:
    return len(_json_bytes(value))


def _write_exclusive(output: Path, artifacts: dict[str, bytes]) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    manifest_artifacts: dict[str, dict[str, Any]] = {}
    for name, data in artifacts.items():
        with (output / name).open("xb") as stream:
            stream.write(data)
        manifest_artifacts[name] = {
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    manifest = {
        "schema_version": "vietlex-corpus-migration-preparation-v1",
        "artifacts": manifest_artifacts,
        "remote_writes": False,
        "provider_calls": 0,
        "legal_validity": "UNVERIFIED",
    }
    with (output / "manifest.json").open("xb") as stream:
        stream.write(_json_bytes(manifest, pretty=True))
    return manifest


def prepare_migration(
    *,
    clean_overlay: Path,
    base_store: Path,
    online_inventory: Path,
    affected_online: Path,
    output: Path,
) -> dict[str, Any]:
    """Validate local snapshots and write a new plan directory without APIs."""
    clean_overlay = Path(clean_overlay)
    base_store = Path(base_store)
    online_inventory = Path(online_inventory)
    affected_online = Path(affected_online)
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite migration plan: {output}")
    if output.resolve().is_relative_to(clean_overlay.resolve()):
        raise ValueError("output_must_be_separate_from_clean_overlay")

    settings = get_settings()
    if (
        settings.VERTEX_EMBEDDING_MODEL != "gemini-embedding-2"
        or settings.VERTEX_QDRANT_COLLECTION_NAME != "vietlex-legal-rag-v3-vertex-1024"
        or settings.VERTEX_QDRANT_VECTOR_SIZE != 1024
        or settings.VERTEX_QDRANT_MAX_CHUNKS_PER_DOCUMENT != MAX_CHUNKS_PER_DOCUMENT
    ):
        raise ValueError("v3_embedding_contract_mismatch")
    contract = VertexQdrantContract(
        collection_name=settings.VERTEX_QDRANT_COLLECTION_NAME,
        embedding_model=settings.VERTEX_EMBEDDING_MODEL,
        vector_size=settings.VERTEX_QDRANT_VECTOR_SIZE,
    )

    overlay_manifest, changes = _validate_overlay(clean_overlay)
    inventory = _read_json(online_inventory, "online_inventory")
    candidate_ids, candidate_rows = _validate_inventory(inventory, settings)
    affected = _read_json(affected_online, "affected_online")
    affected_ids, remote_hashes = _validate_affected(affected)
    if len(set(affected_ids) & set(candidate_ids)):
        raise ValueError("candidate_overlap_with_affected_online")
    if len(set(candidate_ids) & set(changes)):
        raise ValueError("candidate_overlap_with_clean_overlay")
    if not set(affected_ids).issubset(changes):
        raise ValueError("affected_documents_missing_from_clean_overlay")
    original_store, clean_store, originals = _validate_overlay_documents(
        clean_overlay, changes, affected_ids
    )
    if not base_store.is_file():
        raise ValueError("base_store_missing")

    base = ContentStore(base_store)
    for document_id in affected_ids:
        if (
            originals[document_id].content_sha256 != remote_hashes[document_id]
            or originals[document_id].content_sha256 != changes[document_id]["base_sha256"]
        ):
            raise ValueError(f"affected_remote_hash_mismatch:{document_id}")

    candidate_documents = _store_documents(base, sorted(candidate_ids), "candidate")
    for document_id, row in candidate_rows.items():
        document = candidate_documents[document_id]
        if document.quality_flags:
            raise ValueError(f"candidate_unusable_quality:{document_id}")
        if (
            document.content_sha256 != row["source_content_sha256"]
            or document.metadata.document_number[:120] != row.get("document_number")
            or document.metadata.title[:240] != row.get("title")
            or document.metadata.legal_type != row.get("legal_type")
            or document.metadata.issuance_date != row.get("issuance_date")
        ):
            raise ValueError(f"candidate_base_provenance_mismatch:{document_id}")
        if clean_corpus_text(document.content).deletion_spans:
            raise ValueError(f"candidate_contains_confirmed_ad:{document_id}")

    planned_ids = sorted(set(affected_ids) | set(candidate_ids))
    new_view = _OverlayStore(clean_store, base)
    new_documents = _store_documents(new_view, planned_ids, "planned")
    for document_id in affected_ids:
        if new_documents[document_id].content_sha256 != changes[document_id]["cleaned_sha256"]:
            raise ValueError(f"affected_cleaned_content_mismatch:{document_id}")

    old_records = _records(original_store, affected_ids, settings=settings)
    new_records = _records(new_view, planned_ids, settings=settings)
    old_groups = _record_groups(old_records, affected_ids, "old")
    new_groups = _record_groups(new_records, planned_ids, "new")
    new_documents = new_view.get_many(planned_ids)
    if set(new_documents) != set(planned_ids):
        raise ValueError("planned_document_missing")

    new_rows = [
        build_supabase_row(new_documents[document_id], dataset_revision=settings.DATASET_REVISION)
        for document_id in planned_ids
    ]
    body_points = [point_from_source(row) for row in new_rows]
    rows_by_id = {row["document_id"]: row for row in new_rows}
    body_points_by_id = {point["id"]: point for point in body_points}
    old_by_id = {document_id: old_groups.get(document_id, []) for document_id in affected_ids}
    new_by_id = {document_id: new_groups[document_id] for document_id in planned_ids}

    documents_plan = []
    for document_id in planned_ids:
        old_document = originals.get(document_id)
        new_document = new_documents[document_id]
        old_for_doc = old_by_id.get(document_id, [])
        new_for_doc = new_by_id[document_id]
        row = rows_by_id[document_id]
        body_point = body_points_by_id[document_id]
        documents_plan.append(
            {
                "document_id": document_id,
                "action": "replace_cleaned" if old_document else "insert_absent_candidate",
                "document_number": new_document.metadata.document_number,
                "legal_type": new_document.metadata.legal_type,
                "issuance_date": new_document.metadata.issuance_date,
                "old_content_sha256": old_document.content_sha256 if old_document else None,
                "new_content_sha256": new_document.content_sha256,
                "old_content_utf8_bytes": len(old_document.content.encode("utf-8")) if old_document else 0,
                "new_content_utf8_bytes": len(new_document.content.encode("utf-8")),
                "old_structural_point_ids": [record.record_id for record in old_for_doc],
                "new_structural_point_ids": [record.record_id for record in new_for_doc],
                "old_body_point_id": document_id if old_document else None,
                "new_body_point_id": body_point["id"],
                "old_structural_record_count": len(old_for_doc),
                "new_structural_record_count": len(new_for_doc),
                "old_structural_record_json_bytes": sum(
                    _serialized_size(record.model_dump(mode="json"))
                    for record in old_for_doc
                ),
                "new_structural_record_json_bytes": sum(
                    _serialized_size(record.model_dump(mode="json"))
                    for record in new_for_doc
                ),
                "old_structural_payload_json_bytes": sum(
                    _serialized_size(point_payload(record)) for record in old_for_doc
                ),
                "supabase_upsert_json_bytes": _serialized_size(row),
                "body_qdrant_point_json_bytes": _serialized_size(body_point),
                "new_structural_payload_json_bytes": sum(
                    _serialized_size(point_payload(record)) for record in new_for_doc
                ),
            }
        )

    old_record_values = [record.model_dump(mode="json") for record in old_records]
    new_record_values = [record.model_dump(mode="json") for record in new_records]
    old_payload_bytes = sum(_serialized_size(point_payload(record)) for record in old_records)
    new_payload_bytes = sum(_serialized_size(point_payload(record)) for record in new_records)
    dense_vector_count = len(new_records)
    dense_vector_bytes = dense_vector_count * contract.vector_size * 4
    selection = inventory["candidate_inventory"]["candidate_selection"]
    capacity_gate = inventory.get("capacity_gate", {})
    summary = {
        "affected_replacements": len(affected_ids),
        "candidate_additions": len(candidate_ids),
        "planned_new_documents": len(planned_ids),
        "old_structural_records": len(old_records),
        "new_structural_records": len(new_records),
        "candidate_structural_records": sum(
            len(new_groups[document_id]) for document_id in candidate_ids
        ),
        "candidate_documents_by_legal_type": dict(
            sorted(Counter(candidate_documents[item].metadata.legal_type for item in candidate_ids).items())
        ),
        "new_body_points": len(body_points),
        "serialized_old_structural_records_json_bytes": len(
            _jsonl_bytes(old_record_values)
        ),
        "serialized_new_structural_records_json_bytes": len(
            _jsonl_bytes(new_record_values)
        ),
        "serialized_new_structural_payload_bytes": new_payload_bytes,
        "serialized_old_structural_payload_bytes": old_payload_bytes,
        "serialized_supabase_upserts_json_bytes": len(_jsonl_bytes(new_rows)),
        "serialized_body_qdrant_points_json_bytes": len(_jsonl_bytes(body_points)),
        "dense_vector_count": dense_vector_count,
        "dense_vector_dimension": contract.vector_size,
        "dense_vector_bytes_lower_bound": dense_vector_bytes,
        "dense_vector_estimate_basis": "float32 dense values only; excludes sparse vectors, payload storage, indexes, replication, WAL, and provider overhead",
    }
    plan = {
        "schema_version": "vietlex-corpus-migration-plan-v1",
        "dataset": {
            "repository": settings.DATASET_REPOSITORY,
            "revision": settings.DATASET_REVISION,
            "expected_document_count": settings.EXPECTED_DOCUMENT_COUNT,
        },
        "embedding_contract": {
            "collection": contract.collection_name,
            "model": contract.embedding_model,
            "dimension": contract.vector_size,
            "chunk_max_tokens": CHUNK_MAX_TOKENS,
            "chunk_overlap_tokens": CHUNK_OVERLAP_TOKENS,
            "max_chunks_per_document": settings.VERTEX_QDRANT_MAX_CHUNKS_PER_DOCUMENT,
        },
        "capacity_gate": {
            **capacity_gate,
            "physical_capacity_inferred": False,
            "source": "read-only capacity audit snapshot; not authorization to apply",
        },
        "online_inventory": {
            "audit_id": inventory.get("audit_id"),
            "source_revision": inventory.get("source_revision"),
            "online_union_count": inventory["online_capacity"]["document_id_consistency"].get(
                "online_union_document_count"
            ),
            "online_union_document_ids_sha256": inventory["online_capacity"][
                "document_id_consistency"
            ].get("online_union_document_ids_sha256"),
            "candidate_selection_method": selection.get("method"),
            "candidate_absence_assertion": selection["absent_from"],
            "candidate_inventory_status": selection["status"],
            "inventory_sha256": _sha256_file(Path(online_inventory)),
        },
        "affected_online_snapshot": {
            "scope": affected["scope"],
            "snapshot_sha256": _sha256_file(Path(affected_online)),
            "credential_presence": affected["credential_presence"],
        },
        "clean_overlay": {
            "manifest_sha256": _sha256_file(clean_overlay / "manifest.json"),
            "changed_documents": overlay_manifest["changed_documents"],
            "artifact_hashes": {
                name: entry["sha256"] for name, entry in overlay_manifest["artifacts"].items()
            },
        },
        "affected_document_ids": affected_ids,
        "candidate_document_ids": candidate_ids,
        "documents": documents_plan,
        "summary": summary,
        "remote_writes": False,
        "provider_calls": 0,
        "apply_status": "NOT RUN",
        "legal_validity": "UNVERIFIED",
        "coverage_note": "The plan covers only the listed replacements and selected absent documents; it makes no claim about corpus-wide coverage or legal validity.",
    }
    output_artifacts = {
        "old-structural-records.jsonl": _jsonl_bytes(old_record_values),
        "new-structural-records.jsonl": _jsonl_bytes(new_record_values),
        "supabase-upserts.jsonl": _jsonl_bytes(new_rows),
        "qdrant-body-points.jsonl": _jsonl_bytes(body_points),
        "plan.json": _json_bytes(plan, pretty=True),
    }
    manifest = _write_exclusive(output, output_artifacts)
    return {
        "output": str(output.resolve()),
        "summary": summary,
        "artifacts": manifest["artifacts"],
        "remote_writes": False,
        "provider_calls": 0,
        "legal_validity": "UNVERIFIED",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean-overlay", type=Path, required=True)
    parser.add_argument("--base-store", type=Path, required=True)
    parser.add_argument("--online-inventory", type=Path, required=True)
    parser.add_argument("--affected-online", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    result = prepare_migration(
        clean_overlay=arguments.clean_overlay,
        base_store=arguments.base_store,
        online_inventory=arguments.online_inventory,
        affected_online=arguments.affected_online,
        output=arguments.output,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
