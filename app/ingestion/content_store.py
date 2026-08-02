from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pyarrow.parquet as parquet
import zstandard

from app.ingestion.legal_text import (
    DocumentMetadata,
    build_sparse_text,
    normalize_legal_text,
)
from app.ingestion.sparse_encoder import normalized_terms


CONTENT_STORE_SCHEMA_VERSION = 1
SPARSE_CALIBRATION_STRIDE = 128
MOJIBAKE_RE = re.compile(
    r"(?:"
    r"\ufffd"
    r"|Ã[\u0080-\u00bf]"
    r"|Â[\u0080-\u00bf]"
    r"|Ä[\u0080-\u00bf\u0192\u2018\u2019]"
    r"|Æ[\u0080-\u00bf]"
    r"|á[º»]"
    r"|â[\u0080-\u00bf\u20ac\u2018-\u2026]"
    r")"
)
QUALITY_FLAGS = frozenset(
    {
        "missing_document_number",
        "missing_title",
        "missing_source_url",
        "invalid_issuance_date",
        "empty_content",
        "encoding_damage",
        "abnormal_length",
        "duplicate_content_hash",
    }
)


class ContentStoreError(RuntimeError):
    """Base error for local legal content storage."""


class DatasetIntegrityError(ContentStoreError):
    """Raised when the metadata/content corpus cannot be joined exactly."""


class ContentIntegrityError(ContentStoreError):
    """Raised when a stored content blob fails its recorded hash."""


@dataclass(frozen=True)
class BuildReport:
    metadata_count: int
    content_count: int
    joined_count: int
    duplicate_content_hash_count: int
    compressed_bytes: int
    uncompressed_bytes: int
    compression_ratio: float
    average_sparse_document_length: float
    quality_flag_counts: dict[str, int]
    source_shard_row_counts: dict[str, int]
    schema_version: int
    wall_seconds: float


@dataclass(frozen=True)
class StoredDocument:
    metadata: DocumentMetadata
    content: str
    content_sha256: str
    content_store_key: str
    quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class QualityRefreshReport:
    scanned_documents: int
    updated_documents: int
    quality_flag_counts: dict[str, int]
    integrity_check: str


@dataclass(frozen=True)
class _PreparedContentChunk:
    rows: list[tuple[object, ...]]
    compressed_bytes: int
    uncompressed_bytes: int
    sparse_token_count: int
    calibration_fast_token_count: int
    calibration_pyvi_token_count: int


SCHEMA = """
CREATE TABLE metadata (
    document_id INTEGER PRIMARY KEY,
    document_number TEXT NOT NULL,
    title TEXT NOT NULL,
    source_url TEXT NOT NULL,
    legal_type TEXT NOT NULL,
    legal_sectors TEXT NOT NULL,
    issuing_authority TEXT NOT NULL,
    issuance_date TEXT,
    signers TEXT NOT NULL,
    quality_flags TEXT NOT NULL
);
CREATE TABLE contents (
    document_id INTEGER PRIMARY KEY,
    content_zstd BLOB NOT NULL,
    content_bytes INTEGER NOT NULL,
    content_sha256 TEXT NOT NULL,
    source_shard TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    sparse_token_count INTEGER NOT NULL,
    quality_flags TEXT NOT NULL
);
CREATE INDEX contents_sha256_idx ON contents(content_sha256);
CREATE TABLE build_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _json_flags(flags: Iterable[str]) -> str:
    unknown = set(flags) - QUALITY_FLAGS
    if unknown:
        raise ValueError(f"Unknown quality flags: {sorted(unknown)}")
    return json.dumps(
        sorted(set(flags)),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _normalize_date(value: object) -> tuple[str | None, bool]:
    raw = _clean_text(value)
    if not raw:
        return None, False
    for date_format in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return (
                datetime.strptime(raw, date_format).date().isoformat(),
                False,
            )
        except ValueError:
            continue
    return None, True


def _metadata_row(raw: dict[str, object]) -> tuple[object, ...]:
    document_number = _clean_text(raw.get("document_number"))
    title = _clean_text(raw.get("title"))
    source_url = _clean_text(raw.get("url"))
    issuance_date, invalid_date = _normalize_date(
        raw.get("issuance_date")
    )
    flags: set[str] = set()
    if not document_number:
        flags.add("missing_document_number")
    if not title:
        flags.add("missing_title")
    if not source_url:
        flags.add("missing_source_url")
    if invalid_date:
        flags.add("invalid_issuance_date")
    return (
        int(raw["id"]),
        document_number,
        title,
        source_url,
        _clean_text(raw.get("legal_type")),
        _clean_text(raw.get("legal_sectors")),
        _clean_text(raw.get("issuing_authority")),
        issuance_date,
        _clean_text(raw.get("signers")),
        _json_flags(flags),
    )


def _metadata_for_ids(
    connection: sqlite3.Connection,
    document_ids: list[int],
) -> dict[int, DocumentMetadata]:
    placeholders = ",".join("?" for _ in document_ids)
    rows = connection.execute(
        "SELECT document_id, document_number, title, source_url, "
        "legal_type, legal_sectors, issuing_authority, issuance_date "
        f"FROM metadata WHERE document_id IN ({placeholders})",
        document_ids,
    ).fetchall()
    return {
        int(row[0]): DocumentMetadata(
            document_id=int(row[0]),
            document_number=str(row[1]),
            title=str(row[2]),
            source_url=str(row[3]),
            legal_type=str(row[4]),
            legal_sectors=str(row[5]),
            issuing_authority=str(row[6]),
            issuance_date=row[7],
        )
        for row in rows
    }


def _content_quality_flags(content: str) -> set[str]:
    flags: set[str] = set()
    if not content:
        flags.add("empty_content")
    if MOJIBAKE_RE.search(content):
        flags.add("encoding_damage")
    if content and (len(content) < 20 or len(content) > 20_000_000):
        flags.add("abnormal_length")
    return flags


def _prepare_content_chunk(
    items: list[
        tuple[int, str, DocumentMetadata | None, str, int]
    ],
) -> _PreparedContentChunk:
    compressor = zstandard.ZstdCompressor(level=3)
    rows: list[tuple[object, ...]] = []
    compressed_bytes = 0
    uncompressed_bytes = 0
    sparse_token_count = 0
    calibration_fast_token_count = 0
    calibration_pyvi_token_count = 0
    for document_id, raw_content, metadata, source_shard, source_row in items:
        normalized = normalize_legal_text(raw_content)
        content_bytes = normalized.encode("utf-8")
        compressed = compressor.compress(content_bytes)
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        flags = _content_quality_flags(normalized)
        document_sparse_tokens = 0
        if metadata is not None:
            sparse_text = build_sparse_text(
                metadata,
                normalized,
                content_is_normalized=True,
            )
            document_sparse_tokens = len(sparse_text.split())
            if document_id % SPARSE_CALIBRATION_STRIDE == 0:
                calibration_fast_token_count += document_sparse_tokens
                calibration_pyvi_token_count += len(
                    normalized_terms(sparse_text)
                )
        rows.append(
            (
                document_id,
                compressed,
                len(content_bytes),
                content_hash,
                source_shard,
                source_row,
                document_sparse_tokens,
                _json_flags(flags),
            )
        )
        compressed_bytes += len(compressed)
        uncompressed_bytes += len(content_bytes)
        sparse_token_count += document_sparse_tokens
    return _PreparedContentChunk(
        rows=rows,
        compressed_bytes=compressed_bytes,
        uncompressed_bytes=uncompressed_bytes,
        sparse_token_count=sparse_token_count,
        calibration_fast_token_count=calibration_fast_token_count,
        calibration_pyvi_token_count=calibration_pyvi_token_count,
    )


def _chunks(
    items: list[tuple[int, str, DocumentMetadata | None, str, int]],
    chunk_size: int,
) -> Iterable[
    list[tuple[int, str, DocumentMetadata | None, str, int]]
]:
    for start in range(0, len(items), chunk_size):
        yield items[start : start + chunk_size]


def _remove_temporary_store_files(temporary_path: Path) -> None:
    for candidate in (
        temporary_path,
        Path(f"{temporary_path}-wal"),
        Path(f"{temporary_path}-shm"),
    ):
        if candidate.exists():
            candidate.unlink()


def _default_content_workers() -> int:
    return min(3, max(1, (os.cpu_count() or 2) - 1))


def _import_metadata(
    connection: sqlite3.Connection,
    metadata_path: Path,
    batch_size: int,
) -> int:
    source = parquet.ParquetFile(metadata_path)
    count = 0
    try:
        for batch in source.iter_batches(batch_size=batch_size):
            rows = [_metadata_row(raw) for raw in batch.to_pylist()]
            with connection:
                connection.executemany(
                    "INSERT INTO metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
            count += len(rows)
    except sqlite3.IntegrityError as error:
        raise DatasetIntegrityError(
            "Duplicate metadata ID detected."
        ) from error
    return count


def _import_contents(
    connection: sqlite3.Connection,
    content_paths: list[Path],
    content_batch_size: int,
    workers: int,
) -> tuple[int, int, int, int, int, int, dict[str, int]]:
    content_count = 0
    compressed_bytes = 0
    uncompressed_bytes = 0
    sparse_token_total = 0
    calibration_fast_token_total = 0
    calibration_pyvi_token_total = 0
    shard_counts: dict[str, int] = {}
    executor = (
        ProcessPoolExecutor(max_workers=workers)
        if workers > 1
        else None
    )
    try:
        for content_path in content_paths:
            source = parquet.ParquetFile(content_path)
            shard_row = 0
            shard_count = 0
            for batch in source.iter_batches(
                batch_size=content_batch_size
            ):
                raw_rows = batch.to_pylist()
                document_ids = [int(raw["id"]) for raw in raw_rows]
                metadata_by_id = _metadata_for_ids(
                    connection,
                    document_ids,
                )
                items = [
                    (
                        int(raw["id"]),
                        str(raw.get("content") or ""),
                        metadata_by_id.get(int(raw["id"])),
                        content_path.name,
                        shard_row + offset,
                    )
                    for offset, raw in enumerate(raw_rows)
                ]
                work_chunks = list(_chunks(items, chunk_size=64))
                if executor is None:
                    prepared_chunks = map(
                        _prepare_content_chunk,
                        work_chunks,
                    )
                else:
                    prepared_chunks = executor.map(
                        _prepare_content_chunk,
                        work_chunks,
                        chunksize=1,
                    )
                prepared_rows: list[tuple[object, ...]] = []
                for prepared in prepared_chunks:
                    prepared_rows.extend(prepared.rows)
                    compressed_bytes += prepared.compressed_bytes
                    uncompressed_bytes += prepared.uncompressed_bytes
                    sparse_token_total += prepared.sparse_token_count
                    calibration_fast_token_total += (
                        prepared.calibration_fast_token_count
                    )
                    calibration_pyvi_token_total += (
                        prepared.calibration_pyvi_token_count
                    )
                with connection:
                    connection.executemany(
                        "INSERT INTO contents VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        prepared_rows,
                    )
                batch_count = len(prepared_rows)
                shard_row += batch_count
                shard_count += batch_count
                content_count += batch_count
            shard_counts[content_path.name] = shard_count
    except sqlite3.IntegrityError as error:
        raise DatasetIntegrityError(
            "Duplicate content ID detected."
        ) from error
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
    return (
        content_count,
        compressed_bytes,
        uncompressed_bytes,
        sparse_token_total,
        calibration_fast_token_total,
        calibration_pyvi_token_total,
        shard_counts,
    )


def _flag_duplicate_hashes(
    connection: sqlite3.Connection,
) -> int:
    duplicate_hashes = [
        row[0]
        for row in connection.execute(
            "SELECT content_sha256 FROM contents "
            "GROUP BY content_sha256 HAVING COUNT(*) > 1"
        )
    ]
    for content_hash in duplicate_hashes:
        rows = connection.execute(
            "SELECT document_id, quality_flags FROM contents "
            "WHERE content_sha256 = ?",
            (content_hash,),
        ).fetchall()
        updates = []
        for document_id, raw_flags in rows:
            flags = set(json.loads(raw_flags))
            flags.add("duplicate_content_hash")
            updates.append((_json_flags(flags), document_id))
        with connection:
            connection.executemany(
                "UPDATE contents SET quality_flags = ? "
                "WHERE document_id = ?",
                updates,
            )
    return len(duplicate_hashes)


def _quality_counts(
    connection: sqlite3.Connection,
) -> dict[str, int]:
    counts = {flag: 0 for flag in sorted(QUALITY_FLAGS)}
    for table in ("metadata", "contents"):
        for (raw_flags,) in connection.execute(
            f"SELECT quality_flags FROM {table}"
        ):
            for flag in json.loads(raw_flags):
                counts[flag] += 1
    return counts


def refresh_content_quality_flags(
    database_path: Path,
    *,
    batch_size: int = 2_048,
) -> QualityRefreshReport:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive.")
    decompressor = zstandard.ZstdDecompressor()
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    scanned_documents = 0
    updated_documents = 0
    after_id = -1
    try:
        connection.execute("BEGIN IMMEDIATE")
        while True:
            rows = connection.execute(
                "SELECT document_id, content_zstd, quality_flags "
                "FROM contents WHERE document_id > ? "
                "ORDER BY document_id LIMIT ?",
                (after_id, batch_size),
            ).fetchall()
            if not rows:
                break
            updates: list[tuple[str, int]] = []
            for document_id, content_zstd, raw_flags in rows:
                content = decompressor.decompress(content_zstd).decode(
                    "utf-8"
                )
                stored_flags = set(json.loads(raw_flags))
                refreshed_flags = _content_quality_flags(content)
                if "duplicate_content_hash" in stored_flags:
                    refreshed_flags.add("duplicate_content_hash")
                encoded_flags = _json_flags(refreshed_flags)
                if encoded_flags != raw_flags:
                    updates.append((encoded_flags, int(document_id)))
            if updates:
                connection.executemany(
                    "UPDATE contents SET quality_flags = ? "
                    "WHERE document_id = ?",
                    updates,
                )
            scanned_documents += len(rows)
            updated_documents += len(updates)
            after_id = int(rows[-1][0])

        quality_counts = _quality_counts(connection)
        report_row = connection.execute(
            "SELECT value FROM build_metadata "
            "WHERE key = 'build_report'"
        ).fetchone()
        if report_row is None:
            raise ContentIntegrityError(
                "Content store build report is missing."
            )
        report = json.loads(report_row[0])
        report["quality_flag_counts"] = quality_counts
        connection.execute(
            "UPDATE build_metadata SET value = ? "
            "WHERE key = 'build_report'",
            (
                json.dumps(
                    report,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        )
        integrity = str(
            connection.execute("PRAGMA integrity_check").fetchone()[0]
        )
        if integrity != "ok":
            raise ContentIntegrityError(
                f"SQLite integrity check failed: {integrity}."
            )
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return QualityRefreshReport(
            scanned_documents=scanned_documents,
            updated_documents=updated_documents,
            quality_flag_counts=quality_counts,
            integrity_check=integrity,
        )
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _validate_join(
    connection: sqlite3.Connection,
    expected_count: int,
) -> tuple[int, int, int]:
    metadata_count = connection.execute(
        "SELECT COUNT(*) FROM metadata"
    ).fetchone()[0]
    content_count = connection.execute(
        "SELECT COUNT(*) FROM contents"
    ).fetchone()[0]
    joined_count = connection.execute(
        "SELECT COUNT(*) FROM metadata "
        "INNER JOIN contents USING(document_id)"
    ).fetchone()[0]
    missing_content = connection.execute(
        "SELECT COUNT(*) FROM metadata m LEFT JOIN contents c "
        "USING(document_id) WHERE c.document_id IS NULL"
    ).fetchone()[0]
    missing_metadata = connection.execute(
        "SELECT COUNT(*) FROM contents c LEFT JOIN metadata m "
        "USING(document_id) WHERE m.document_id IS NULL"
    ).fetchone()[0]
    empty_content = connection.execute(
        "SELECT COUNT(*) FROM contents WHERE content_bytes = 0"
    ).fetchone()[0]
    if (
        metadata_count != expected_count
        or content_count != expected_count
        or joined_count != expected_count
        or missing_content
        or missing_metadata
        or empty_content
    ):
        raise DatasetIntegrityError(
            "Dataset join integrity failed: "
            f"metadata={metadata_count}, content={content_count}, "
            f"joined={joined_count}, missing_content={missing_content}, "
            f"missing_metadata={missing_metadata}, "
            f"empty_content={empty_content}, expected={expected_count}."
        )
    return metadata_count, content_count, joined_count


def build_content_store(
    snapshot_path: Path,
    database_path: Path,
    expected_count: int,
    *,
    batch_size: int = 2_048,
    content_batch_size: int = 512,
    workers: int | None = None,
) -> BuildReport:
    started = time.perf_counter()
    resolved_workers = workers
    if resolved_workers is None:
        resolved_workers = _default_content_workers()
    if not 1 <= resolved_workers <= 4:
        raise ValueError("workers must be between 1 and 4.")
    if batch_size <= 0 or content_batch_size <= 0:
        raise ValueError("batch sizes must be positive.")
    metadata_paths = sorted(
        (snapshot_path / "metadata").glob("*.parquet")
    )
    content_paths = sorted(
        (snapshot_path / "content").glob("*.parquet")
    )
    if len(metadata_paths) != 1 or not content_paths:
        raise DatasetIntegrityError(
            "Snapshot must contain one metadata shard and content shards."
        )

    database_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = Path(f"{database_path}.part")
    _remove_temporary_store_files(temporary_path)

    connection = sqlite3.connect(temporary_path)
    try:
        connection.executescript(
            "PRAGMA journal_mode=WAL;"
            "PRAGMA synchronous=NORMAL;"
            "PRAGMA temp_store=MEMORY;"
            + SCHEMA
        )
        _import_metadata(
            connection,
            metadata_paths[0],
            batch_size,
        )
        (
            _,
            compressed_bytes,
            uncompressed_bytes,
            sparse_token_total,
            calibration_fast_token_total,
            calibration_pyvi_token_total,
            shard_counts,
        ) = _import_contents(
            connection,
            content_paths,
            content_batch_size,
            resolved_workers,
        )
        metadata_count, content_count, joined_count = _validate_join(
            connection,
            expected_count,
        )
        duplicate_hash_count = _flag_duplicate_hashes(connection)
        quality_counts = _quality_counts(connection)
        report = BuildReport(
            metadata_count=metadata_count,
            content_count=content_count,
            joined_count=joined_count,
            duplicate_content_hash_count=duplicate_hash_count,
            compressed_bytes=compressed_bytes,
            uncompressed_bytes=uncompressed_bytes,
            compression_ratio=(
                compressed_bytes / max(1, uncompressed_bytes)
            ),
            average_sparse_document_length=(
                (
                    sparse_token_total
                    * calibration_pyvi_token_total
                    / calibration_fast_token_total
                )
                / max(1, content_count)
                if calibration_fast_token_total
                else sparse_token_total / max(1, content_count)
            ),
            quality_flag_counts=quality_counts,
            source_shard_row_counts=shard_counts,
            schema_version=CONTENT_STORE_SCHEMA_VERSION,
            wall_seconds=time.perf_counter() - started,
        )
        with connection:
            connection.execute(
                "INSERT INTO build_metadata(key, value) VALUES (?, ?)",
                (
                    "build_report",
                    json.dumps(
                        asdict(report),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            )
            connection.execute(
                "INSERT INTO build_metadata(key, value) VALUES (?, ?)",
                ("status", "complete"),
            )
        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]
        if integrity != "ok":
            raise ContentIntegrityError(
                f"SQLite integrity check failed: {integrity}."
            )
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.close()
        os.replace(temporary_path, database_path)
        return report
    except Exception:
        connection.close()
        _remove_temporary_store_files(temporary_path)
        raise


class ContentStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._decompressor = zstandard.ZstdDecompressor()

    def get_many(
        self,
        document_ids: list[int],
    ) -> dict[int, StoredDocument]:
        if not document_ids:
            return {}
        placeholders = ",".join("?" for _ in document_ids)
        sql = (
            "SELECT m.document_id, m.document_number, m.title, "
            "m.source_url, m.legal_type, m.legal_sectors, "
            "m.issuing_authority, m.issuance_date, "
            "m.quality_flags, c.content_zstd, c.content_sha256, "
            "c.quality_flags "
            "FROM metadata m INNER JOIN contents c USING(document_id) "
            f"WHERE m.document_id IN ({placeholders})"
        )
        with sqlite3.connect(
            f"file:{self.path}?mode=ro",
            uri=True,
        ) as connection:
            rows = connection.execute(sql, document_ids).fetchall()

        documents: dict[int, StoredDocument] = {}
        for row in rows:
            content_bytes = self._decompressor.decompress(row[9])
            digest = hashlib.sha256(content_bytes).hexdigest()
            if digest != row[10]:
                raise ContentIntegrityError(
                    f"Content hash mismatch for document {row[0]}."
                )
            flags = sorted(
                set(json.loads(row[8]))
                | set(json.loads(row[11]))
            )
            document_id = int(row[0])
            documents[document_id] = StoredDocument(
                metadata=DocumentMetadata(
                    document_id=document_id,
                    document_number=str(row[1]),
                    title=str(row[2]),
                    source_url=str(row[3]),
                    legal_type=str(row[4]),
                    legal_sectors=str(row[5]),
                    issuing_authority=str(row[6]),
                    issuance_date=row[7],
                ),
                content=content_bytes.decode("utf-8"),
                content_sha256=digest,
                content_store_key=str(document_id),
                quality_flags=tuple(flags),
            )
        return documents

    def get_metadata_many(
        self,
        document_ids: list[int],
    ) -> dict[int, DocumentMetadata]:
        """Read metadata without decompressing document bodies."""
        if not document_ids:
            return {}
        with sqlite3.connect(
            f"file:{self.path}?mode=ro",
            uri=True,
        ) as connection:
            return _metadata_for_ids(connection, document_ids)

    def iter_document_ids(
        self,
        *,
        after_id: int,
        limit: int,
    ) -> list[int]:
        with sqlite3.connect(
            f"file:{self.path}?mode=ro",
            uri=True,
        ) as connection:
            rows = connection.execute(
                "SELECT document_id FROM metadata "
                "WHERE document_id > ? ORDER BY document_id LIMIT ?",
                (after_id, limit),
            ).fetchall()
        return [int(row[0]) for row in rows]

    def build_report(self) -> BuildReport:
        with sqlite3.connect(
            f"file:{self.path}?mode=ro",
            uri=True,
        ) as connection:
            row = connection.execute(
                "SELECT value FROM build_metadata "
                "WHERE key = 'build_report'"
            ).fetchone()
        if row is None:
            raise ContentIntegrityError(
                "Content store build report is missing."
            )
        return BuildReport(**json.loads(row[0]))
