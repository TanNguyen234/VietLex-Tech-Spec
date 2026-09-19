"""Additive, read-only-at-runtime passage FTS. Does not replace retrieval indexes."""

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time

from app.services.document_structure import document_sections


class BodySearchUnavailable(RuntimeError):
    pass


def passage_rows(document):
    """Exact windows retain the reader's section anchor; no source rewriting."""
    for section in document_sections(document.content):
        text = section["text"]
        start = 0
        while start < len(text):
            end = min(start + 2400, len(text))
            if end < len(text):
                boundary = text.rfind(" ", start + 1800, end)
                if boundary > start:
                    end = boundary + 1
            yield {
                "section_id": section["id"],
                "section_title": section["title"],
                "offset": start,
                "text": text[start:end],
            }
            if end == len(text):
                break
            start = max(start + 1, end - 240)


def _parts(marked):
    # Plain text spans, never mark source-provided HTML as safe.
    parts, active = [], False
    for piece in re.split("([\ue000\ue001])", marked):
        if piece == "\ue000":
            active = True
        elif piece == "\ue001":
            active = False
        elif piece:
            parts.append({"text": piece, "match": active})
    return parts


class BodySearchIndex:
    def __init__(self, path):
        self.path = Path(path)

    @classmethod
    def build(cls, path, documents):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create protects existing indexes even if a build is interrupted.
        with path.open("xb"):
            pass
        with closing(sqlite3.connect(path)) as db:
            db.executescript("""
                CREATE TABLE documents(document_id INTEGER PRIMARY KEY, document_number TEXT,
                    title TEXT, legal_type TEXT, issuing_authority TEXT, issuance_date TEXT,
                    source_url TEXT, content_sha256 TEXT);
                CREATE TABLE passages(id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL,
                    section_id TEXT, section_title TEXT, source_offset INTEGER, text TEXT);
                CREATE VIRTUAL TABLE body_fts USING fts5(text, content='passages',
                    content_rowid='id', tokenize='unicode61 remove_diacritics 2');
                CREATE TABLE state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE INDEX passages_document ON passages(document_id);
            """)
            count = passages = 0
            fingerprint = hashlib.sha256()
            with db:
                for document in documents:
                    actual = hashlib.sha256(document.content.encode()).hexdigest()
                    if actual != document.content_sha256:
                        raise ValueError("body_source_hash_mismatch")
                    item = document.metadata
                    db.execute(
                        "INSERT INTO documents VALUES(?,?,?,?,?,?,?,?)",
                        (
                            item.document_id,
                            item.document_number,
                            item.title,
                            item.legal_type,
                            item.issuing_authority,
                            item.issuance_date,
                            item.source_url,
                            actual,
                        ),
                    )
                    fingerprint.update(f"{item.document_id}:{actual}\n".encode())
                    for row in passage_rows(document):
                        cursor = db.execute(
                            "INSERT INTO passages(document_id,section_id,section_title,source_offset,text) VALUES(?,?,?,?,?)",
                            (
                                item.document_id,
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
                        passages += 1
                    count += 1
                coverage = {
                    "schema_version": 1,
                    "overlap_characters": 240,
                    "document_count": count,
                    "passage_count": passages,
                    "built_at": datetime.now(timezone.utc).isoformat(),
                    "source_sha256": fingerprint.hexdigest(),
                }
                db.execute(
                    "INSERT INTO state VALUES('ready',?)", (json.dumps(coverage),)
                )
        return cls(path)

    def _connect(self):
        try:
            db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
            db.row_factory = sqlite3.Row
            deadline = time.monotonic() + 3
            db.set_progress_handler(lambda: time.monotonic() > deadline, 10000)
            return db
        except sqlite3.Error as error:
            raise BodySearchUnavailable("body_index_unavailable") from error

    def coverage(self):
        try:
            with closing(self._connect()) as db:
                row = db.execute("SELECT value FROM state WHERE key='ready'").fetchone()
                if row is None:
                    raise BodySearchUnavailable("body_index_incomplete")
                value = json.loads(row[0])
                if (
                    value.get("schema_version") != 1
                    or value.get("overlap_characters") != 240
                ):
                    raise BodySearchUnavailable("body_index_version")
                return value
        except (sqlite3.Error, ValueError) as error:
            raise BodySearchUnavailable("body_index_unavailable") from error

    def search(self, query, *, filters=None, limit=20, offset=0):
        self.coverage()
        terms = re.findall(r"[^\W_]+", query[:200], re.UNICODE)
        if not terms:
            return []
        match = '"' + " ".join(terms) + '"'
        clauses, values = ["body_fts MATCH ?"], [match]
        if filters:
            for field, operator, value in [
                ("legal_type", "=", filters.legal_type),
                ("issuing_authority", "=", filters.authority),
                ("issuance_date", ">=", filters.issued_from),
                ("issuance_date", "<=", filters.issued_to),
            ]:
                if value:
                    clauses.append(f"d.{field} {operator} ?")
                    values.append(value)
        sort = getattr(filters, "sort", "default")
        order = {
            "default": "body_fts.rank, p.id",
            "newest": "d.issuance_date IS NULL, d.issuance_date DESC, body_fts.rank, p.id",
            "oldest": "d.issuance_date IS NULL, d.issuance_date ASC, body_fts.rank, p.id",
        }[sort]
        sql = (
            """SELECT d.*, p.section_id, p.section_title, p.source_offset,
                 snippet(body_fts,0,char(57344),char(57345),' … ',48) AS marked
                 FROM body_fts JOIN passages p ON p.id=body_fts.rowid
                 JOIN documents d ON d.document_id=p.document_id WHERE """
            + " AND ".join(clauses)
            + f" ORDER BY {order} LIMIT ? OFFSET ?"
        )
        try:
            with closing(self._connect()) as db:
                rows = db.execute(
                    sql,
                    [
                        *values,
                        max(1, min(int(limit), 51)),
                        max(0, min(int(offset), 1000)),
                    ],
                ).fetchall()
            return [
                {**dict(row), "snippet_parts": _parts(row["marked"])} for row in rows
            ]
        except sqlite3.Error as error:
            raise BodySearchUnavailable("body_search_failed") from error
