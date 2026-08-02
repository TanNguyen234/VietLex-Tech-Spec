import importlib
import json
import sqlite3
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


def _content_store_module():
    return importlib.import_module("app.ingestion.content_store")


def _write_metadata(snapshot: Path, ids: list[int]) -> None:
    (snapshot / "metadata").mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "id": ids,
                "document_number": [f"{item:02d}/QĐ" for item in ids],
                "title": [f"Văn bản {item}" for item in ids],
                "url": [f"https://example/{item}" for item in ids],
                "legal_type": ["Quyết định" for _ in ids],
                "legal_sectors": ["Hành chính" for _ in ids],
                "issuing_authority": [f"Bộ {item}" for item in ids],
                "issuance_date": [
                    f"{item:02d}/01/2026" for item in ids
                ],
                "signers": ["" for _ in ids],
            }
        ),
        snapshot / "metadata" / "data-00000-of-00001.parquet",
    )


def _write_content(
    snapshot: Path,
    ids: list[int],
    contents: list[str],
) -> None:
    (snapshot / "content").mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table({"id": ids, "content": contents}),
        snapshot / "content" / "data-00000-of-00011.parquet",
    )


def test_store_joins_by_id_and_round_trips_compressed_content(
    tmp_path: Path,
) -> None:
    content_store = _content_store_module()
    snapshot = tmp_path / "snapshot"
    _write_metadata(snapshot, [2, 1])
    content_one = "Điều 1. Nội dung một. " * 50
    content_two = "Điều 2. Nội dung hai. " * 50
    _write_content(
        snapshot,
        [1, 2],
        [content_one, content_two],
    )

    database = tmp_path / "store.sqlite3"
    report = content_store.build_content_store(
        snapshot,
        database,
        expected_count=2,
    )
    documents = content_store.ContentStore(database).get_many([1, 2])

    assert report.joined_count == 2
    assert documents[1].metadata.title == "Văn bản 1"
    assert documents[1].content == content_one.strip()
    assert documents[1].metadata.issuance_date == "2026-01-01"
    assert documents[1].content_sha256 != documents[2].content_sha256
    assert report.compressed_bytes < report.uncompressed_bytes


def test_store_rejects_missing_join_before_success_marker(
    tmp_path: Path,
) -> None:
    content_store = _content_store_module()
    snapshot = tmp_path / "snapshot"
    _write_metadata(snapshot, [1, 2])
    _write_content(snapshot, [1], ["Điều 1. Chỉ có một văn bản"])
    database = tmp_path / "store.sqlite3"

    with pytest.raises(
        content_store.DatasetIntegrityError,
        match="join",
    ):
        content_store.build_content_store(
            snapshot,
            database,
            expected_count=2,
        )

    assert not database.exists()


def test_store_supports_bounded_parallel_content_preparation(
    tmp_path: Path,
) -> None:
    content_store = _content_store_module()
    snapshot = tmp_path / "snapshot"
    _write_metadata(snapshot, [1, 2, 3, 4])
    _write_content(
        snapshot,
        [1, 2, 3, 4],
        [f"Điều {item}. Nội dung kiểm thử. " * 20 for item in range(1, 5)],
    )
    database = tmp_path / "parallel.sqlite3"

    report = content_store.build_content_store(
        snapshot,
        database,
        expected_count=4,
        batch_size=2,
        workers=2,
    )

    assert report.joined_count == 4
    assert content_store.ContentStore(database).get_many([1, 4])[4].content


def test_temporary_store_cleanup_removes_sqlite_sidecars(
    tmp_path: Path,
) -> None:
    content_store = _content_store_module()
    temporary = tmp_path / "content.sqlite3.part"
    stale_files = [
        temporary,
        Path(f"{temporary}-wal"),
        Path(f"{temporary}-shm"),
    ]
    for stale_file in stale_files:
        stale_file.write_bytes(b"stale")

    content_store._remove_temporary_store_files(temporary)

    assert all(not stale_file.exists() for stale_file in stale_files)


def test_content_preparation_does_not_run_pyvi_for_every_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content_store = _content_store_module()
    metadata = content_store.DocumentMetadata(
        document_id=1,
        document_number="01/QĐ",
        title="Văn bản thử nghiệm",
        source_url="https://example/1",
        legal_type="Quyết định",
        legal_sectors="Hành chính",
        issuing_authority="Bộ thử nghiệm",
        issuance_date="2026-01-01",
    )

    def fail_if_called(_: str) -> list[str]:
        raise AssertionError("PyVi must only run on the calibration sample")

    monkeypatch.setattr(content_store, "normalized_terms", fail_if_called)

    prepared = content_store._prepare_content_chunk(
        [(1, "Điều 1. Nội dung kiểm thử.", metadata, "content.parquet", 0)]
    )

    assert prepared.sparse_token_count > 0


def test_content_preparation_calibrates_fast_count_on_stable_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content_store = _content_store_module()
    metadata = content_store.DocumentMetadata(
        document_id=128,
        document_number="128/QĐ",
        title="Văn bản hiệu chỉnh",
        source_url="https://example/128",
        legal_type="Quyết định",
        legal_sectors="Hành chính",
        issuing_authority="Bộ thử nghiệm",
        issuance_date="2026-01-01",
    )
    monkeypatch.setattr(
        content_store,
        "normalized_terms",
        lambda _: ["một", "hai", "ba"],
    )

    prepared = content_store._prepare_content_chunk(
        [
            (
                128,
                "Điều 1. Nội dung hiệu chỉnh.",
                metadata,
                "content.parquet",
                0,
            )
        ]
    )

    assert prepared.calibration_pyvi_token_count == 3
    assert (
        prepared.calibration_fast_token_count
        == prepared.sparse_token_count
    )


def test_default_content_workers_leave_one_core_for_orchestration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content_store = _content_store_module()
    monkeypatch.setattr(content_store.os, "cpu_count", lambda: 4)

    assert content_store._default_content_workers() == 3


def test_encoding_detector_accepts_valid_vietnamese_uppercase() -> None:
    content_store = _content_store_module()
    valid = (
        "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM. "
        "ỦY BAN NHÂN DÂN XÃ ĐÃ BAN HÀNH QUYẾT ĐỊNH."
    )

    assert "encoding_damage" not in content_store._content_quality_flags(
        valid
    )


def test_encoding_detector_rejects_common_utf8_mojibake() -> None:
    content_store = _content_store_module()
    mojibake = "Quyáº¿t Ä‘á»‹nh vá» quáº£n lÃ½ hÃ nh chÃ­nh"

    assert "encoding_damage" in content_store._content_quality_flags(
        mojibake
    )


def test_quality_refresh_replaces_stale_encoding_flags(
    tmp_path: Path,
) -> None:
    content_store = _content_store_module()
    snapshot = tmp_path / "snapshot"
    _write_metadata(snapshot, [1, 2])
    _write_content(
        snapshot,
        [1, 2],
        [
            "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM.",
            "Quyáº¿t Ä‘á»‹nh vá» quáº£n lÃ½.",
        ],
    )
    database = tmp_path / "store.sqlite3"
    content_store.build_content_store(
        snapshot,
        database,
        expected_count=2,
        workers=1,
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE contents SET quality_flags = ?",
            ('["encoding_damage"]',),
        )
        raw_report = connection.execute(
            "SELECT value FROM build_metadata WHERE key = 'build_report'"
        ).fetchone()[0]
        report = json.loads(raw_report)
        report["quality_flag_counts"]["encoding_damage"] = 2
        connection.execute(
            "UPDATE build_metadata SET value = ? "
            "WHERE key = 'build_report'",
            (json.dumps(report),),
        )

    refreshed = content_store.refresh_content_quality_flags(database)
    documents = content_store.ContentStore(database).get_many([1, 2])

    assert refreshed.scanned_documents == 2
    assert refreshed.updated_documents == 1
    assert refreshed.quality_flag_counts["encoding_damage"] == 1
    assert "encoding_damage" not in documents[1].quality_flags
    assert "encoding_damage" in documents[2].quality_flags
    assert (
        content_store.ContentStore(database)
        .build_report()
        .quality_flag_counts["encoding_damage"]
        == 1
    )
