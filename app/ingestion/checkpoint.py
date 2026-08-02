from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    revision TEXT NOT NULL,
    batch_id INTEGER NOT NULL,
    first_document_id INTEGER NOT NULL,
    last_document_id INTEGER NOT NULL,
    point_count INTEGER NOT NULL,
    seconds REAL NOT NULL,
    completed_at TEXT NOT NULL,
    PRIMARY KEY (revision, batch_id)
);
CREATE TABLE IF NOT EXISTS failures (
    revision TEXT NOT NULL,
    document_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (revision, document_id, stage)
);
CREATE TABLE IF NOT EXISTS metrics (
    revision TEXT NOT NULL,
    name TEXT NOT NULL,
    value REAL NOT NULL,
    recorded_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class FailureRecord:
    revision: str
    document_id: int
    stage: str
    category: str
    message: str
    attempts: int
    created_at: str


class CheckpointStore:
    def __init__(
        self,
        path: Path,
        *,
        revision: str,
        secrets: Iterable[str | None] = (),
    ) -> None:
        self.path = path
        self.revision = revision
        self._secrets = tuple(
            secret for secret in secrets if secret
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _sanitize(self, message: str) -> str:
        sanitized = message
        for secret in self._secrets:
            sanitized = sanitized.replace(secret, "[REDACTED]")
        return sanitized

    def mark_completed(
        self,
        *,
        batch_id: int,
        first_id: int,
        last_id: int,
        point_count: int,
        seconds: float,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO batches VALUES "
                "(?, ?, ?, ?, ?, ?, ?)",
                (
                    self.revision,
                    batch_id,
                    first_id,
                    last_id,
                    point_count,
                    seconds,
                    self._now(),
                ),
            )

    def completed_batch_ids(self) -> set[int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT batch_id FROM batches WHERE revision = ?",
                (self.revision,),
            ).fetchall()
        return {int(row[0]) for row in rows}

    def next_incomplete(
        self,
        batch_ids: Iterable[int],
    ) -> int | None:
        completed = self.completed_batch_ids()
        return next(
            (
                batch_id
                for batch_id in batch_ids
                if batch_id not in completed
            ),
            None,
        )

    def record_failure(
        self,
        *,
        document_id: int,
        stage: str,
        category: str,
        message: str,
        attempts: int,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO failures VALUES "
                "(?, ?, ?, ?, ?, ?, ?)",
                (
                    self.revision,
                    document_id,
                    stage,
                    category,
                    self._sanitize(message),
                    attempts,
                    self._now(),
                ),
            )

    def failures(self) -> list[FailureRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT revision, document_id, stage, category, "
                "message, attempts, created_at FROM failures "
                "WHERE revision = ? ORDER BY document_id, stage",
                (self.revision,),
            ).fetchall()
        return [FailureRecord(*row) for row in rows]

    def clear_failures(
        self,
        *,
        document_ids: Iterable[int],
        stage: str,
    ) -> None:
        rows = [
            (self.revision, int(document_id), stage)
            for document_id in document_ids
        ]
        if not rows:
            return
        with self._connect() as connection:
            connection.executemany(
                "DELETE FROM failures WHERE revision = ? "
                "AND document_id = ? AND stage = ?",
                rows,
            )

    def record_metric(self, name: str, value: float) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO metrics VALUES (?, ?, ?, ?)",
                (self.revision, name, value, self._now()),
            )

    def metrics(self) -> dict[str, list[float]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT name, value FROM metrics "
                "WHERE revision = ? ORDER BY recorded_at",
                (self.revision,),
            ).fetchall()
        metrics: dict[str, list[float]] = {}
        for name, value in rows:
            metrics.setdefault(str(name), []).append(float(value))
        return metrics
