from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

from app.ingestion.content_store import (
    CONTENT_STORE_SCHEMA_VERSION,
    QUALITY_FLAGS,
    BuildReport,
    ContentStore,
    SCHEMA,
)


def document_ids_sha256(document_ids: Sequence[int]) -> str:
    payload = json.dumps(
        list(document_ids),
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def audit_qdrant_document_ids(
    client: object,
    collection: str,
    *,
    batch_size: int = 1_000,
) -> dict[str, Any]:
    if not collection.strip() or batch_size <= 0:
        raise ValueError("collection and batch size must be valid")
    offset: object | None = None
    point_count = 0
    document_ids: set[int] = set()
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            limit=batch_size,
            offset=offset,
            with_payload=["document_id"],
            with_vectors=False,
        )
        point_count += len(points)
        for point in points:
            value = (getattr(point, "payload", None) or {}).get(
                "document_id"
            )
            if value is None:
                raise ValueError("v3 point is missing document_id")
            document_ids.add(int(value))
        if offset is None:
            break
    ordered = sorted(document_ids)
    return {
        "schema_version": "vietlex-v3-document-set-v1",
        "collection": collection,
        "point_count": point_count,
        "document_count": len(ordered),
        "document_ids_sha256": document_ids_sha256(ordered),
        "document_ids": ordered,
    }


def _rows_for_ids(
    connection: sqlite3.Connection,
    table: str,
    document_ids: Sequence[int],
) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for start in range(0, len(document_ids), 900):
        batch = list(document_ids[start : start + 900])
        placeholders = ",".join("?" for _ in batch)
        rows.extend(
            connection.execute(
                f"SELECT * FROM {table} WHERE document_id IN ({placeholders}) "
                "ORDER BY document_id",
                batch,
            ).fetchall()
        )
    return rows


def export_content_store_subset(
    *,
    source_path: Path,
    output_path: Path,
    document_ids: Sequence[int],
    collection: str,
    point_count: int,
    dataset_revision: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    ordered = list(document_ids)
    if (
        ordered != sorted(set(ordered))
        or not ordered
        or any(document_id <= 0 for document_id in ordered)
    ):
        raise ValueError("document IDs must be nonempty, positive, unique, and sorted")
    output_path = Path(output_path)
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing bundle: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".building")
    if temporary.exists():
        temporary.unlink()

    source_store = ContentStore(Path(source_path))
    source_report = source_store.build_report()
    source = sqlite3.connect(
        f"file:{Path(source_path).resolve().as_posix()}?mode=ro",
        uri=True,
    )
    target = sqlite3.connect(temporary)
    try:
        metadata_rows = _rows_for_ids(source, "metadata", ordered)
        content_rows = _rows_for_ids(source, "contents", ordered)
        found_ids = {int(row[0]) for row in metadata_rows} & {
            int(row[0]) for row in content_rows
        }
        missing = set(ordered) - found_ids
        if missing:
            raise ValueError(
                f"source store is missing {len(missing)} requested documents"
            )
        target.executescript(SCHEMA)
        target.executemany(
            "INSERT INTO metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            metadata_rows,
        )
        target.executemany(
            "INSERT INTO contents VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            content_rows,
        )

        quality_counts: Counter[str] = Counter()
        for row in metadata_rows:
            quality_counts.update(json.loads(row[9]))
        for row in content_rows:
            quality_counts.update(json.loads(row[7]))
        shard_counts = Counter(str(row[4]) for row in content_rows)
        compressed_bytes = sum(len(row[1]) for row in content_rows)
        uncompressed_bytes = sum(int(row[2]) for row in content_rows)
        content_hash_counts = Counter(str(row[3]) for row in content_rows)
        duplicate_hashes = sum(
            1 for count in content_hash_counts.values() if count > 1
        )
        report = BuildReport(
            metadata_count=len(metadata_rows),
            content_count=len(content_rows),
            joined_count=len(found_ids),
            duplicate_content_hash_count=max(0, duplicate_hashes),
            compressed_bytes=compressed_bytes,
            uncompressed_bytes=uncompressed_bytes,
            compression_ratio=compressed_bytes / max(1, uncompressed_bytes),
            average_sparse_document_length=(
                source_report.average_sparse_document_length
            ),
            quality_flag_counts={
                flag: quality_counts.get(flag, 0)
                for flag in sorted(QUALITY_FLAGS)
            },
            source_shard_row_counts=dict(sorted(shard_counts.items())),
            schema_version=CONTENT_STORE_SCHEMA_VERSION,
            wall_seconds=time.perf_counter() - started,
        )
        metadata = {
            "build_report": json.dumps(
                asdict(report),
                ensure_ascii=False,
                sort_keys=True,
            ),
            "status": "complete",
            "dataset_revision": dataset_revision,
            "source_collection": collection,
            "qdrant_point_count": str(point_count),
            "document_ids_sha256": document_ids_sha256(ordered),
        }
        target.executemany(
            "INSERT INTO build_metadata(key, value) VALUES (?, ?)",
            metadata.items(),
        )
        target.commit()
        integrity = str(target.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise RuntimeError(f"bundle integrity check failed: {integrity}")
        target.close()
        source.close()
        os.replace(temporary, output_path)
        return {
            "output_path": str(output_path),
            "document_count": len(found_ids),
            "document_ids_sha256": document_ids_sha256(ordered),
            "point_count": point_count,
            "integrity_check": integrity,
            "bytes": output_path.stat().st_size,
        }
    except Exception:
        target.close()
        source.close()
        if temporary.exists():
            temporary.unlink()
        raise
