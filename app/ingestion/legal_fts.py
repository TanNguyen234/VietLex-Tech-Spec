from __future__ import annotations

import argparse
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.ingestion.content_store import ContentStore


_NUMBER_RE = re.compile(
    r"(?<!\d)(\d{1,4}\s*/\s*\d{4}\s*/\s*[A-ZĐ][A-ZĐ0-9-]*)",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_BUILD_SCHEMA_VERSION = 2


@contextmanager
def _temporary_environment(path: Path):
    names = ("TEMP", "TMP", "TMPDIR")
    previous = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            os.environ[name] = str(path)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def normalize_document_number(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def extract_legal_references(query: str) -> list[str]:
    return [
        normalize_document_number(match.group(1))
        for match in _NUMBER_RE.finditer(query)
    ]


def _fts_query(query: str) -> str:
    terms: list[str] = []
    seen: set[str] = set()
    for raw in _WORD_RE.findall(query.casefold()):
        if len(raw) < 2 or raw in seen:
            continue
        seen.add(raw)
        terms.append(raw.replace('"', '""'))
        if len(terms) >= 12:
            break
    return " OR ".join(f'"{term}"' for term in terms)


class LegalFtsIndex:
    """Read-optimized legal FTS5 index built from the verified content store."""

    def __init__(
        self,
        *,
        store: Any,
        path: Path,
        dataset_revision: str,
    ) -> None:
        self._store = store
        self.path = Path(path)
        self._dataset_revision = dataset_revision

    def is_ready(self) -> bool:
        if not self.path.exists():
            return False
        try:
            with sqlite3.connect(
                f"file:{self.path}?mode=ro",
                uri=True,
            ) as connection:
                values = dict(
                    connection.execute(
                        "SELECT key, value FROM index_metadata"
                    ).fetchall()
                )
            return (
                values.get("dataset_revision") == self._dataset_revision
                and int(values.get("document_count", "-1"))
                == int(self._store.build_report().joined_count)
            )
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return False

    def ensure_built(self, *, batch_size: int = 256) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive.")
        if self.is_ready():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        sqlite_temp = (self.path.parent / "tmp").resolve()
        sqlite_temp.mkdir(parents=True, exist_ok=True)
        with _temporary_environment(sqlite_temp):
            self._build(batch_size=batch_size)

    def _build(self, *, batch_size: int) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".building")
        temporary_resolved = temporary.resolve()
        if temporary_resolved.parent != self.path.resolve().parent:
            raise RuntimeError("FTS temporary path escaped its target directory.")
        connection: sqlite3.Connection | None = None
        resume = False
        if temporary.exists() and temporary.stat().st_size > 0:
            candidate: sqlite3.Connection | None = None
            try:
                candidate = sqlite3.connect(temporary)
                version = int(
                    candidate.execute("PRAGMA user_version").fetchone()[0]
                )
                revision_row = candidate.execute(
                    "SELECT value FROM index_metadata "
                    "WHERE key = 'build_dataset_revision'"
                ).fetchone()
                if (
                    version == _BUILD_SCHEMA_VERSION
                    and revision_row
                    and revision_row[0] == self._dataset_revision
                ):
                    connection = candidate
                    resume = True
                else:
                    candidate.close()
            except sqlite3.Error:
                if candidate is not None:
                    candidate.close()
                connection = None
        if connection is None:
            if temporary.exists():
                temporary.unlink()
            connection = sqlite3.connect(temporary)
            connection.executescript(
                f"""
                PRAGMA user_version={_BUILD_SCHEMA_VERSION};
                PRAGMA journal_mode=MEMORY;
                PRAGMA synchronous=OFF;
                PRAGMA temp_store=FILE;
                PRAGMA cache_size=-65536;
                CREATE TABLE legal_documents (
                    document_id INTEGER PRIMARY KEY,
                    normalized_number TEXT NOT NULL,
                    document_number TEXT NOT NULL,
                    title TEXT NOT NULL,
                    legal_type TEXT NOT NULL,
                    issuing_authority TEXT NOT NULL
                );
                CREATE INDEX legal_documents_number_idx
                    ON legal_documents(normalized_number);
                CREATE VIRTUAL TABLE legal_fts USING fts5(
                    document_number,
                    title,
                    legal_type,
                    issuing_authority,
                    body,
                    content='',
                    detail=column,
                    tokenize='unicode61 remove_diacritics 0'
                );
                CREATE TABLE index_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            with connection:
                connection.execute(
                    "INSERT INTO index_metadata VALUES (?, ?)",
                    ("build_dataset_revision", self._dataset_revision),
                )
        try:
            inserted, maximum_id = connection.execute(
                "SELECT COUNT(*), MAX(document_id) FROM legal_documents"
            ).fetchone()
            inserted = int(inserted)
            after_id = int(maximum_id) if maximum_id is not None else -1
            if resume:
                print(
                    f"FTS resuming after document_id={after_id} "
                    f"indexed={inserted}",
                    flush=True,
                )
            while True:
                document_ids = self._store.iter_document_ids(
                    after_id=after_id,
                    limit=batch_size,
                )
                if not document_ids:
                    break
                documents = self._store.get_many(document_ids)
                metadata_rows: list[tuple[object, ...]] = []
                fts_rows: list[tuple[object, ...]] = []
                for document_id in document_ids:
                    document = documents[document_id]
                    metadata = document.metadata
                    metadata_rows.append(
                        (
                            document_id,
                            normalize_document_number(
                                metadata.document_number
                            ),
                            metadata.document_number,
                            metadata.title,
                            metadata.legal_type,
                            metadata.issuing_authority,
                        )
                    )
                    fts_rows.append(
                        (
                            document_id,
                            metadata.document_number,
                            metadata.title,
                            metadata.legal_type,
                            metadata.issuing_authority,
                            document.content,
                        )
                    )
                with connection:
                    connection.executemany(
                        "INSERT INTO legal_documents VALUES (?, ?, ?, ?, ?, ?)",
                        metadata_rows,
                    )
                    connection.executemany(
                        "INSERT INTO legal_fts("
                        "rowid, document_number, title, legal_type, "
                        "issuing_authority, body"
                        ") VALUES (?, ?, ?, ?, ?, ?)",
                        fts_rows,
                    )
                inserted += len(document_ids)
                after_id = document_ids[-1]
                print(f"FTS indexed={inserted}", flush=True)

            expected = int(self._store.build_report().joined_count)
            if inserted != expected:
                raise RuntimeError(
                    f"FTS document count mismatch: {inserted} != {expected}."
                )
            with connection:
                connection.executemany(
                    "INSERT OR REPLACE INTO index_metadata VALUES (?, ?)",
                    (
                        ("dataset_revision", self._dataset_revision),
                        ("document_count", str(inserted)),
                        ("created_at", str(int(time.time()))),
                    ),
                )
            integrity = connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"FTS integrity check failed: {integrity}.")
        except Exception:
            connection.close()
            print(
                f"FTS build paused; resumable file retained at {temporary}",
                flush=True,
            )
            raise
        connection.close()
        os.replace(temporary, self.path)

    def search(self, query: str, *, limit: int) -> list[int]:
        if limit <= 0 or not self.is_ready():
            return []
        selected: list[int] = []
        seen: set[int] = set()
        with sqlite3.connect(
            f"file:{self.path}?mode=ro",
            uri=True,
        ) as connection:
            for reference in extract_legal_references(query):
                rows = connection.execute(
                    "SELECT document_id FROM legal_documents "
                    "WHERE normalized_number = ? ORDER BY document_id",
                    (reference,),
                ).fetchall()
                for (document_id,) in rows:
                    value = int(document_id)
                    if value not in seen:
                        selected.append(value)
                        seen.add(value)
                    if len(selected) >= limit:
                        return selected

            expression = _fts_query(query)
            if expression:
                rows = connection.execute(
                    "SELECT rowid FROM legal_fts "
                    "WHERE legal_fts MATCH ? ORDER BY bm25(legal_fts) LIMIT ?",
                    (expression, limit * 2),
                ).fetchall()
                for (document_id,) in rows:
                    value = int(document_id)
                    if value not in seen:
                        selected.append(value)
                        seen.add(value)
                    if len(selected) >= limit:
                        break
        return selected


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the local legal FTS5 index from the content store."
    )
    parser.add_argument("build", nargs="?")
    parser.add_argument("--batch-size", type=int, default=256)
    arguments = parser.parse_args()
    settings = get_settings()
    index = LegalFtsIndex(
        store=ContentStore(settings.CONTENT_STORE_PATH),
        path=settings.LEGAL_FTS_PATH,
        dataset_revision=settings.DATASET_REVISION,
    )
    index.ensure_built(batch_size=arguments.batch_size)
    print(f"FTS ready: {index.path.resolve()}", flush=True)


if __name__ == "__main__":
    main()
