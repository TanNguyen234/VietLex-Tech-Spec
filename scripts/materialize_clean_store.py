"""Create a separate full clean local store from a pinned base and overlay."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone

import zstandard

from app.config import get_settings
from app.ingestion.content_store import ContentIntegrityError, StoredDocument
from app.ingestion.legal_text import DocumentMetadata
from app.services.body_search import BodySearchIndex, passage_rows


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_BACKUP_PAGES = 256
_DISK_RESERVE_BYTES = 1_000_000_000
_EXPECTED_SPARSE_AVERAGE = 979.1241640033913


def _read_json(path: Path, error_code: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(error_code) from error
    if not isinstance(value, dict):
        raise ValueError(error_code)
    return value


def _file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _verify_artifact(directory: Path, manifest: dict, name: str) -> Path:
    artifact = directory / name
    expected = (manifest.get("artifacts") or {}).get(name)
    if not artifact.is_file() or not isinstance(expected, dict):
        raise ValueError(f"missing_artifact:{name}")
    if (
        expected.get("bytes") != artifact.stat().st_size
        or expected.get("sha256") != _file_sha256(artifact)
    ):
        raise ValueError(f"artifact_hash_mismatch:{name}")
    return artifact


def _validate_overlay(directory: Path, expected_count: int) -> tuple[list[dict], str, Path]:
    manifest_path = directory / "manifest.json"
    manifest = _read_json(manifest_path, "invalid_overlay_manifest")
    if manifest.get("changed_documents") != expected_count:
        raise ValueError("overlay_document_count_mismatch")
    if "overlay" not in str(manifest.get("representation", "")):
        raise ValueError("overlay_representation_invalid")
    changes_path = _verify_artifact(directory, manifest, "changes.jsonl")
    clean_delta_path = _verify_artifact(directory, manifest, "clean-delta.sqlite3")
    changes: list[dict] = []
    try:
        with changes_path.open(encoding="utf-8") as stream:
            for line in stream:
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError("invalid_overlay_change")
                identifier = item.get("document_id")
                if type(identifier) is not int or identifier <= 0:
                    raise ValueError("invalid_overlay_document_id")
                for field in ("base_sha256", "cleaned_sha256"):
                    if not isinstance(item.get(field), str) or not _SHA256_RE.fullmatch(item[field]):
                        raise ValueError("invalid_overlay_hash")
                changes.append(item)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("invalid_overlay_changes") from error
    if len(changes) != expected_count:
        raise ValueError("overlay_changes_count_mismatch")
    identifiers = [item["document_id"] for item in changes]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("duplicate_overlay_document_id")
    overlay_sha256 = _file_sha256(manifest_path)
    return changes, overlay_sha256, clean_delta_path


def _validate_candidate_plan(
    directory: Path,
    *,
    expected_count: int,
    dataset_revision: str,
    dataset_repository: str,
    expected_document_count: int,
    overlay_manifest_sha256: str,
    overlay_document_count: int,
) -> list[int]:
    manifest = _read_json(directory / "manifest.json", "invalid_candidate_manifest")
    plan_path = _verify_artifact(directory, manifest, "plan.json")
    plan = _read_json(plan_path, "invalid_candidate_plan")
    dataset = plan.get("dataset") or {}
    if dataset.get("revision") != dataset_revision:
        raise ValueError("candidate_plan_revision_mismatch")
    if dataset.get("repository") != dataset_repository:
        raise ValueError("candidate_plan_repository_mismatch")
    if dataset.get("expected_document_count") != expected_document_count:
        raise ValueError("candidate_plan_document_count_mismatch")
    overlay = plan.get("clean_overlay") or {}
    if (
        overlay.get("manifest_sha256") != overlay_manifest_sha256
        or overlay.get("changed_documents") != overlay_document_count
    ):
        raise ValueError("candidate_plan_overlay_mismatch")
    candidates = plan.get("candidate_document_ids")
    if not isinstance(candidates, list) or len(candidates) != expected_count:
        raise ValueError("candidate_count_mismatch")
    if any(type(identifier) is not int or identifier <= 0 for identifier in candidates):
        raise ValueError("invalid_candidate_document_id")
    if len(set(candidates)) != len(candidates):
        raise ValueError("duplicate_candidate_document_id")
    return candidates


def _readonly_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def _get_documents(path: Path, document_ids: list[int]) -> dict[int, StoredDocument]:
    if not document_ids:
        return {}
    placeholders = ",".join("?" for _ in document_ids)
    sql = (
        "SELECT m.document_id,m.document_number,m.title,m.source_url,m.legal_type,"
        "m.legal_sectors,m.issuing_authority,m.issuance_date,m.quality_flags,"
        "c.content_zstd,c.content_sha256,c.quality_flags "
        "FROM metadata m JOIN contents c USING(document_id) "
        f"WHERE m.document_id IN ({placeholders})"
    )
    decompressor = zstandard.ZstdDecompressor()
    with closing(_readonly_connection(path)) as db:
        rows = db.execute(sql, document_ids).fetchall()
    documents = {}
    for row in rows:
        identifier = int(row[0])
        content_bytes = decompressor.decompress(row[9])
        digest = hashlib.sha256(content_bytes).hexdigest()
        if digest != row[10]:
            raise ContentIntegrityError(f"Content hash mismatch for document {identifier}.")
        metadata = DocumentMetadata(
            document_id=identifier,
            document_number=str(row[1]),
            title=str(row[2]),
            source_url=str(row[3]),
            legal_type=str(row[4]),
            legal_sectors=str(row[5]),
            issuing_authority=str(row[6]),
            issuance_date=row[7],
        )
        quality_flags = sorted(set(json.loads(row[8])) | set(json.loads(row[11])))
        documents[identifier] = StoredDocument(
            metadata=metadata,
            content=content_bytes.decode("utf-8"),
            content_sha256=digest,
            content_store_key=str(identifier),
            quality_flags=tuple(quality_flags),
        )
    return documents


def _backup_database(source_path: Path, target_path: Path) -> None:
    with closing(_readonly_connection(source_path)) as source:
        with closing(sqlite3.connect(target_path)) as target:
            source.backup(target, pages=_BACKUP_PAGES, sleep=0.05)
            target.commit()


def _validate_full_base(path: Path, expected_document_count: int) -> dict:
    try:
        with closing(_readonly_connection(path)) as db:
            metadata = dict(db.execute("SELECT key,value FROM build_metadata"))
            report = json.loads(metadata["build_report"])
            counts = db.execute(
                "SELECT (SELECT COUNT(*) FROM metadata), "
                "(SELECT COUNT(*) FROM contents), "
                "(SELECT COUNT(*) FROM metadata JOIN contents USING(document_id))"
            ).fetchone()
    except (sqlite3.Error, KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid_base_content_store") from error
    if (
        metadata.get("status") != "complete"
        or not isinstance(report, dict)
        or tuple(map(int, counts)) != (expected_document_count,) * 3
        or report.get("joined_count") != expected_document_count
        or report.get("metadata_count") != expected_document_count
        or report.get("content_count") != expected_document_count
        or float(report.get("average_sparse_document_length", -1))
        != _EXPECTED_SPARSE_AVERAGE
    ):
        raise ValueError("base_document_count_mismatch")
    return report


def _apply_overlay(
    target_path: Path,
    overlay_path: Path,
    changes: list[dict],
    *,
    expected_document_count: int,
    dataset_revision: str,
    base_store_path: Path,
    overlay_manifest_sha256: str,
) -> int:
    decompressor = zstandard.ZstdDecompressor()
    try:
        with closing(sqlite3.connect(target_path)) as target, closing(
            _readonly_connection(overlay_path)
        ) as overlay:
            target.execute("BEGIN IMMEDIATE")
            for item in changes:
                identifier = item["document_id"]
                base_row = target.execute(
                    "SELECT content_zstd,content_bytes,content_sha256,source_shard,"
                    "source_row FROM contents WHERE document_id=?",
                    (identifier,),
                ).fetchone()
                clean_row = overlay.execute(
                    "SELECT content_zstd,content_bytes,content_sha256,source_shard,"
                    "source_row,sparse_token_count,quality_flags FROM contents "
                    "WHERE document_id=?",
                    (identifier,),
                ).fetchone()
                base_metadata = target.execute(
                    "SELECT * FROM metadata WHERE document_id=?", (identifier,)
                ).fetchone()
                clean_metadata = overlay.execute(
                    "SELECT * FROM metadata WHERE document_id=?", (identifier,)
                ).fetchone()
                if base_row is None or clean_row is None or base_metadata is None:
                    raise ValueError(f"overlay_document_missing:{identifier}")
                if clean_metadata is None or tuple(clean_metadata) != tuple(base_metadata):
                    raise ValueError(f"overlay_metadata_mismatch:{identifier}")
                base_bytes = decompressor.decompress(base_row[0])
                clean_bytes = decompressor.decompress(clean_row[0])
                actual_base = hashlib.sha256(base_bytes).hexdigest()
                actual_clean = hashlib.sha256(clean_bytes).hexdigest()
                if (
                    actual_base != item["base_sha256"]
                    or base_row[2] != item["base_sha256"]
                ):
                    raise ValueError(f"overlay_base_hash_mismatch:{identifier}")
                if (
                    actual_clean != item["cleaned_sha256"]
                    or clean_row[2] != item["cleaned_sha256"]
                    or len(clean_bytes) != clean_row[1]
                ):
                    raise ValueError(f"overlay_clean_hash_mismatch:{identifier}")
                if (base_row[3], base_row[4]) != (clean_row[3], clean_row[4]):
                    raise ValueError(f"overlay_source_position_mismatch:{identifier}")
                target.execute(
                    "UPDATE contents SET content_zstd=?,content_bytes=?,content_sha256=?,"
                    "sparse_token_count=?,quality_flags=? WHERE document_id=?",
                    (
                        clean_row[0],
                        clean_row[1],
                        clean_row[2],
                        clean_row[5],
                        clean_row[6],
                        identifier,
                    ),
                )
            original_report_row = target.execute(
                "SELECT value FROM build_metadata WHERE key='build_report'"
            ).fetchone()
            if original_report_row is None:
                raise ValueError("base_build_report_missing")
            raw_build_report = json.loads(original_report_row[0])
            target.execute(
                "INSERT OR REPLACE INTO build_metadata(key,value) VALUES('raw_build_report',?)",
                (json.dumps(raw_build_report, ensure_ascii=False, sort_keys=True),),
            )
            compressed_bytes, uncompressed_bytes = target.execute(
                "SELECT COALESCE(SUM(length(content_zstd)),0),"
                "COALESCE(SUM(content_bytes),0) FROM contents"
            ).fetchone()
            clean_report = dict(raw_build_report)
            clean_report["compressed_bytes"] = int(compressed_bytes)
            clean_report["uncompressed_bytes"] = int(uncompressed_bytes)
            clean_report["compression_ratio"] = int(compressed_bytes) / max(
                1, int(uncompressed_bytes)
            )
            target.execute(
                "UPDATE build_metadata SET value=? WHERE key='build_report'",
                (json.dumps(clean_report, ensure_ascii=False, sort_keys=True),),
            )
            provenance = {
                "clean_derivative_status": "complete",
                "clean_dataset_revision": dataset_revision,
                "clean_base_store_path": str(base_store_path.resolve()),
                "clean_overlay_manifest_sha256": overlay_manifest_sha256,
                "clean_overlay_document_count": str(len(changes)),
            }
            target.executemany(
                "INSERT OR REPLACE INTO build_metadata(key,value) VALUES (?,?)",
                provenance.items(),
            )
            target.commit()
            integrity = target.execute("PRAGMA quick_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError("clean_content_store_quick_check_failed")
            counts = target.execute(
                "SELECT (SELECT COUNT(*) FROM metadata),"
                "(SELECT COUNT(*) FROM contents),"
                "(SELECT COUNT(*) FROM metadata JOIN contents USING(document_id))"
            ).fetchone()
            if tuple(map(int, counts)) != (expected_document_count,) * 3:
                raise ValueError("clean_content_store_count_mismatch")
            return len(changes)
    except (sqlite3.Error, zstandard.ZstdError, UnicodeDecodeError) as error:
        raise ValueError("clean_content_store_update_failed") from error


def _refresh_body_index(
    body_index_path: Path,
    content_store_path: Path,
    *,
    changed_ids: set[int],
    candidate_ids: list[int],
    expected_candidate_count: int,
    expected_refresh_count: int,
    expected_body_document_count: int,
) -> dict:
    with closing(sqlite3.connect(body_index_path)) as db:
        db.row_factory = sqlite3.Row
        indexed_ids = {
            int(row[0]) for row in db.execute("SELECT document_id FROM documents")
        }
        candidates_present = indexed_ids.intersection(candidate_ids)
        if candidates_present:
            raise ValueError("candidate_already_in_body_index")
        base_state_row = db.execute(
            "SELECT value FROM state WHERE key='ready'"
        ).fetchone()
        if base_state_row is None:
            raise ValueError("body_index_base_state_missing")
        try:
            base_coverage = json.loads(base_state_row[0])
        except (TypeError, ValueError) as error:
            raise ValueError("body_index_base_state_invalid") from error
        base_document_count, base_passage_count = db.execute(
            "SELECT (SELECT COUNT(*) FROM documents),"
            "(SELECT COUNT(*) FROM passages)"
        ).fetchone()
        base_fingerprint = hashlib.sha256()
        for identifier, digest in db.execute(
            "SELECT document_id,content_sha256 FROM documents ORDER BY document_id"
        ):
            base_fingerprint.update(f"{int(identifier)}:{digest}\n".encode())
        if (
            base_coverage.get("schema_version") != 1
            or base_coverage.get("overlap_characters") != 240
            or base_coverage.get("document_count") != int(base_document_count)
            or base_coverage.get("passage_count") != int(base_passage_count)
            or base_coverage.get("source_sha256") != base_fingerprint.hexdigest()
        ):
            raise ValueError("body_index_base_coverage_mismatch")
        additions = set(candidate_ids)
        if len(additions) != expected_candidate_count:
            raise ValueError("candidate_count_mismatch")
        refresh_ids = sorted(indexed_ids.intersection(changed_ids))
        if len(refresh_ids) != expected_refresh_count:
            raise ValueError("body_index_refresh_count_mismatch")
        documents = _get_documents(
            content_store_path, sorted(set(refresh_ids) | additions)
        )
        if set(documents) != set(refresh_ids) | additions:
            raise ValueError("body_index_source_document_missing")
        db.execute("BEGIN IMMEDIATE")
        for identifier in refresh_ids:
            old_passages = db.execute(
                "SELECT id,text FROM passages WHERE document_id=? ORDER BY id",
                (identifier,),
            ).fetchall()
            for passage in old_passages:
                db.execute(
                    "INSERT INTO body_fts(body_fts,rowid,text) VALUES('delete',?,?)",
                    (int(passage["id"]), str(passage["text"])),
                )
            db.execute("DELETE FROM passages WHERE document_id=?", (identifier,))
            db.execute("DELETE FROM documents WHERE document_id=?", (identifier,))
        for identifier in sorted(set(refresh_ids) | additions):
            document = documents[identifier]
            metadata = document.metadata
            db.execute(
                "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    metadata.document_number,
                    metadata.title,
                    metadata.legal_type,
                    metadata.issuing_authority,
                    metadata.issuance_date,
                    metadata.source_url,
                    document.content_sha256,
                ),
            )
            for row in passage_rows(document):
                cursor = db.execute(
                    "INSERT INTO passages(document_id,section_id,section_title,source_offset,text) "
                    "VALUES(?,?,?,?,?)",
                    (
                        identifier,
                        row["section_id"],
                        row["section_title"],
                        row["offset"],
                        row["text"],
                    ),
                )
                db.execute(
                    "INSERT INTO body_fts(rowid,text) VALUES(?,?)",
                    (cursor.lastrowid, row["text"]),
                )
        document_count, passage_count = db.execute(
            "SELECT (SELECT COUNT(*) FROM documents),"
            "(SELECT COUNT(*) FROM passages)"
        ).fetchone()
        if int(document_count) != int(base_document_count) + expected_candidate_count:
            raise ValueError("body_index_document_count_mismatch")
        if int(document_count) != expected_body_document_count:
            raise ValueError("body_index_final_count_mismatch")
        fingerprint = hashlib.sha256()
        for identifier, digest in db.execute(
            "SELECT document_id,content_sha256 FROM documents ORDER BY document_id"
        ):
            fingerprint.update(f"{int(identifier)}:{digest}\n".encode())
        source_sha256 = fingerprint.hexdigest()
        coverage = {
            "schema_version": 1,
            "overlap_characters": 240,
            "document_count": int(document_count),
            "passage_count": int(passage_count),
            "built_at": datetime.now(timezone.utc).isoformat(),
            "source_sha256": source_sha256,
        }
        cursor = db.execute(
            "UPDATE state SET value=? WHERE key='ready'",
            (json.dumps(coverage, ensure_ascii=False),),
        )
        if cursor.rowcount != 1:
            raise ValueError("body_index_ready_state_missing")
        db.commit()
        integrity = db.execute("PRAGMA quick_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError("body_index_quick_check_failed")
    with closing(sqlite3.connect(content_store_path)) as db:
        db.executemany(
            "INSERT OR REPLACE INTO build_metadata(key,value) VALUES (?,?)",
            (
                ("clean_body_index_document_count", str(coverage["document_count"])),
                ("clean_body_index_passage_count", str(coverage["passage_count"])),
                ("clean_body_index_source_sha256", source_sha256),
            ),
        )
        db.commit()
    BodySearchIndex(body_index_path).coverage()
    return {
        **coverage,
        "refreshed_existing_documents": len(refresh_ids),
        "added_candidate_documents": len(additions),
    }


def materialize_clean_store(
    *,
    base_store: Path,
    clean_overlay: Path,
    base_body_index: Path,
    candidate_plan_dir: Path,
    output_dir: Path,
    expected_document_count: int,
    expected_overlay_count: int,
    expected_candidate_count: int,
    expected_refresh_count: int,
    expected_body_document_count: int,
    dataset_repository: str,
    dataset_revision: str,
) -> dict:
    """Build and atomically publish a new clean SQLite derivative directory."""
    base_store = Path(base_store).resolve()
    clean_overlay = Path(clean_overlay).resolve()
    base_body_index = Path(base_body_index).resolve()
    candidate_plan_dir = Path(candidate_plan_dir).resolve()
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        raise FileExistsError(output_dir)
    if not output_dir.parent.is_dir():
        raise FileNotFoundError(output_dir.parent)
    if not base_store.is_file() or not base_body_index.is_file():
        raise FileNotFoundError("base_store_or_body_index_missing")
    required_free = (
        base_store.stat().st_size
        + base_body_index.stat().st_size
        + _DISK_RESERVE_BYTES
    )
    if shutil.disk_usage(output_dir.parent).free < required_free:
        raise ValueError("local_disk_reserve_below_required_output")

    base_report = _validate_full_base(base_store, expected_document_count)
    changes, overlay_sha256, overlay_db = _validate_overlay(
        clean_overlay, expected_overlay_count
    )
    candidate_ids = _validate_candidate_plan(
        candidate_plan_dir,
        expected_count=expected_candidate_count,
        dataset_revision=dataset_revision,
        dataset_repository=dataset_repository,
        expected_document_count=expected_document_count,
        overlay_manifest_sha256=overlay_sha256,
        overlay_document_count=len(changes),
    )
    if set(candidate_ids).intersection(item["document_id"] for item in changes):
        raise ValueError("candidate_overlap_with_clean_overlay")

    stage = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.materializing-", dir=output_dir.parent)
    )
    try:
        content_store_path = stage / "content_store.sqlite3"
        body_index_path = stage / "legal_body_fts.sqlite3"
        _backup_database(base_store, content_store_path)
        overlay_count = _apply_overlay(
            content_store_path,
            overlay_db,
            changes,
            expected_document_count=expected_document_count,
            dataset_revision=dataset_revision,
            base_store_path=base_store,
            overlay_manifest_sha256=overlay_sha256,
        )
        _backup_database(base_body_index, body_index_path)
        body_coverage = _refresh_body_index(
            body_index_path,
            content_store_path,
            changed_ids={item["document_id"] for item in changes},
            candidate_ids=candidate_ids,
            expected_candidate_count=expected_candidate_count,
            expected_refresh_count=expected_refresh_count,
            expected_body_document_count=expected_body_document_count,
        )
        for offset in range(0, len(changes), 64):
            chunk = changes[offset : offset + 64]
            documents = _get_documents(
                content_store_path, [item["document_id"] for item in chunk]
            )
            for item in chunk:
                document = documents.get(item["document_id"])
                if document is None or document.content_sha256 != item["cleaned_sha256"]:
                    raise ValueError(f"clean_overlay_readback_mismatch:{item['document_id']}")
        with closing(_readonly_connection(content_store_path)) as db:
            metadata = dict(db.execute("SELECT key,value FROM build_metadata"))
            report = json.loads(metadata["build_report"])
            if report.get("joined_count") != expected_document_count:
                raise ValueError("clean_store_report_count_mismatch")
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("clean_content_store_quick_check_failed")
        if output_dir.exists():
            raise FileExistsError(output_dir)
        stage.rename(output_dir)
        return {
            "output_dir": str(output_dir),
            "document_count": expected_document_count,
            "overlay_documents": overlay_count,
            "candidate_documents": expected_candidate_count,
            "overlay_manifest_sha256": overlay_sha256,
            "base_build_report": base_report,
            "body_index": body_coverage,
        }
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-store", type=Path, required=True)
    parser.add_argument("--clean-overlay", type=Path, required=True)
    parser.add_argument("--base-body-index", type=Path, required=True)
    parser.add_argument("--candidate-plan-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    settings = get_settings()
    base_store = args.base_store.resolve()
    if base_store != settings.CONTENT_STORE_PATH.resolve():
        raise ValueError("base_store_not_configured_pinned_store")
    if args.base_body_index.resolve() != settings.V3_CONTENT_STORE_PATH.with_name(
        "legal_body_fts.sqlite3"
    ).resolve():
        raise ValueError("base_body_index_not_configured_v3_sidecar")
    if args.output_dir.resolve() != settings.CLEAN_CONTENT_STORE_PATH.parent.resolve():
        raise ValueError("output_dir_not_configured_clean_derivative")
    result = materialize_clean_store(
        base_store=base_store,
        clean_overlay=args.clean_overlay,
        base_body_index=args.base_body_index,
        candidate_plan_dir=args.candidate_plan_dir,
        output_dir=args.output_dir,
        expected_document_count=settings.EXPECTED_DOCUMENT_COUNT,
        expected_overlay_count=189,
        expected_candidate_count=20,
        expected_refresh_count=13,
        expected_body_document_count=4989,
        dataset_repository=settings.DATASET_REPOSITORY,
        dataset_revision=settings.DATASET_REVISION,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
