import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest

from app.ingestion.content_store import StoredDocument
from app.ingestion.legal_fts import LegalFtsIndex
from app.ingestion.legal_text import DocumentMetadata


def _document(
    document_id: int,
    number: str,
    title: str,
    content: str,
) -> StoredDocument:
    return StoredDocument(
        metadata=DocumentMetadata(
            document_id=document_id,
            document_number=number,
            title=title,
            source_url=f"https://example.invalid/{document_id}",
            legal_type="Luật",
            legal_sectors="",
            issuing_authority="Quốc hội",
            issuance_date="2020-01-01",
        ),
        content=content,
        content_sha256=str(document_id) * 64,
        content_store_key=str(document_id),
        quality_flags=(),
    )


class TinyContentStore:
    def __init__(self) -> None:
        self.documents = {
            431147: _document(
                431147,
                "72/2020/QH14",
                "Luật Bảo vệ môi trường",
                "Điều 1. Luật này quy định về hoạt động bảo vệ môi trường.",
            ),
            427301: _document(
                427301,
                "59/2020/QH14",
                "Luật Doanh nghiệp",
                "Điều 1. Luật này quy định việc thành lập doanh nghiệp.",
            ),
        }

    def build_report(self):
        return SimpleNamespace(joined_count=len(self.documents))

    def iter_document_ids(self, *, after_id: int, limit: int):
        return [
            document_id
            for document_id in sorted(self.documents)
            if document_id > after_id
        ][:limit]

    def get_many(self, document_ids: list[int]):
        return {
            document_id: self.documents[document_id]
            for document_id in document_ids
        }


def test_exact_document_number_is_ranked_first(tmp_path) -> None:
    index = LegalFtsIndex(
        store=TinyContentStore(),
        path=tmp_path / "legal_fts.sqlite3",
        dataset_revision="revision-1",
    )
    index.ensure_built(batch_size=1)

    assert index.search(
        "Luật số 72/2020/QH14 Điều 1",
        limit=5,
    )[0] == 431147


def test_body_phrase_finds_relevant_legal_document(tmp_path) -> None:
    index = LegalFtsIndex(
        store=TinyContentStore(),
        path=tmp_path / "legal_fts.sqlite3",
        dataset_revision="revision-1",
    )
    index.ensure_built(batch_size=2)

    assert index.search(
        "xin cho biết hoạt động bảo vệ môi trường áp dụng thế nào",
        limit=1,
    ) == [431147]


def test_build_restores_process_temp_environment(tmp_path, monkeypatch) -> None:
    original = {
        "TEMP": "D:/sentinel/temp",
        "TMP": "D:/sentinel/tmp",
        "TMPDIR": "D:/sentinel/tmpdir",
    }
    for name, value in original.items():
        monkeypatch.setenv(name, value)
    index = LegalFtsIndex(
        store=TinyContentStore(),
        path=tmp_path / "legal_fts.sqlite3",
        dataset_revision="revision-1",
    )

    index.ensure_built(batch_size=2)

    assert {name: __import__("os").environ[name] for name in original} == original


def test_compact_fts_does_not_duplicate_document_bodies(tmp_path) -> None:
    path = tmp_path / "legal_fts.sqlite3"
    index = LegalFtsIndex(
        store=TinyContentStore(),
        path=path,
        dataset_revision="revision-1",
    )

    index.ensure_built(batch_size=2)

    with closing(sqlite3.connect(path)) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        stored_title = connection.execute(
            "SELECT title FROM legal_title_fts LIMIT 1"
        ).fetchone()[0]
    assert "legal_fts" not in tables
    assert stored_title is None
    assert index.search("thành lập doanh nghiệp", limit=1) == [427301]


def test_interrupted_build_is_retained_and_resumed(tmp_path) -> None:
    class InterruptingStore(TinyContentStore):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def get_many(self, document_ids: list[int]):
            self.calls += 1
            if self.calls == 2:
                raise OSError("simulated interruption")
            return super().get_many(document_ids)

    path = tmp_path / "legal_fts.sqlite3"
    interrupted = LegalFtsIndex(
        store=InterruptingStore(),
        path=path,
        dataset_revision="revision-1",
    )

    with pytest.raises(OSError, match="simulated interruption"):
        interrupted.ensure_built(batch_size=1)

    building = path.with_suffix(path.suffix + ".building")
    assert building.exists()
    with closing(sqlite3.connect(building)) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM legal_documents"
        ).fetchone()[0] == 1

    resumed = LegalFtsIndex(
        store=TinyContentStore(),
        path=path,
        dataset_revision="revision-1",
    )
    resumed.ensure_built(batch_size=1)

    assert resumed.is_ready()
    assert resumed.search("bảo vệ môi trường", limit=1) == [431147]


def test_title_rank_ignores_common_terms_in_unrelated_body(tmp_path) -> None:
    class TitleRankingStore(TinyContentStore):
        def __init__(self) -> None:
            self.documents = {
                1: _document(
                    1,
                    "01/2020/QĐ-UBND",
                    "Quyết định về phụ cấp",
                    (
                        "Luật bảo vệ môi trường giấy phép được định nghĩa "
                        "trong tài liệu tham khảo không liên quan."
                    ),
                ),
                2: _document(
                    2,
                    "72/2020/QH14",
                    "Luật Bảo vệ môi trường 2020",
                    "Quy định chung.",
                ),
            }

    index = LegalFtsIndex(
        store=TitleRankingStore(),
        path=tmp_path / "legal_fts.sqlite3",
        dataset_revision="revision-1",
    )
    index.ensure_built(batch_size=2)

    assert index.search(
        "Giấy phép môi trường theo Luật Bảo vệ môi trường",
        limit=1,
    ) == [2]


def test_title_rank_discards_long_polite_prefix(tmp_path) -> None:
    index = LegalFtsIndex(
        store=TinyContentStore(),
        path=tmp_path / "legal_fts.sqlite3",
        dataset_revision="revision-1",
    )
    index.ensure_built(batch_size=2)

    assert index.search(
        (
            "Xin vui lòng cho tôi biết theo quy định hiện hành thì câu hỏi "
            "của tôi về Luật Bảo vệ môi trường"
        ),
        limit=1,
    ) == [431147]


def test_complete_legacy_body_index_is_compacted_atomically(tmp_path) -> None:
    path = tmp_path / "legal_fts.sqlite3"
    store = TinyContentStore()
    index = LegalFtsIndex(
        store=store,
        path=path,
        dataset_revision="revision-1",
    )
    index.ensure_built(batch_size=2)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA user_version=3")
        connection.execute(
            "CREATE VIRTUAL TABLE legal_fts USING fts5("
            "body, content='', detail=column)"
        )
        connection.executemany(
            "INSERT INTO legal_fts(rowid, body) VALUES (?, ?)",
            [(431147, "body duplicated"), (427301, "body duplicated")],
        )
        connection.commit()

    migrated = LegalFtsIndex(
        store=store,
        path=path,
        dataset_revision="revision-1",
    )
    migrated.ensure_built(batch_size=2)

    assert migrated.is_ready()
    with closing(sqlite3.connect(path)) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert version == 4
    assert "legal_fts" not in tables
    assert migrated.search("Luật Bảo vệ môi trường", limit=1) == [431147]


def test_fresh_build_reads_metadata_without_decompressing_bodies(
    tmp_path,
) -> None:
    class MetadataOnlyStore(TinyContentStore):
        def get_metadata_many(self, document_ids: list[int]):
            return {
                document_id: self.documents[document_id].metadata
                for document_id in document_ids
            }

        def get_many(self, document_ids: list[int]):
            raise AssertionError("FTS title build must not read document bodies")

    index = LegalFtsIndex(
        store=MetadataOnlyStore(),
        path=tmp_path / "legal_fts.sqlite3",
        dataset_revision="revision-1",
    )

    index.ensure_built(batch_size=2)

    assert index.is_ready()
