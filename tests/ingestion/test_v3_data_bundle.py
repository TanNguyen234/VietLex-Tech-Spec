import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import zstandard
import pytest

from app.ingestion.content_store import ContentStore, SCHEMA


def _source_store(path: Path) -> None:
    compressor = zstandard.ZstdCompressor()
    report = {
        "metadata_count": 3,
        "content_count": 3,
        "joined_count": 3,
        "duplicate_content_hash_count": 0,
        "compressed_bytes": 30,
        "uncompressed_bytes": 60,
        "compression_ratio": 0.5,
        "average_sparse_document_length": 42.5,
        "quality_flag_counts": {},
        "source_shard_row_counts": {"source.parquet": 3},
        "schema_version": 1,
        "wall_seconds": 1.0,
    }
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        for document_id in (1, 2, 3):
            content = f"Nội dung văn bản {document_id}.".encode()
            digest = hashlib.sha256(content).hexdigest()
            connection.execute(
                "INSERT INTO metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    document_id,
                    f"{document_id}/2026/QH15",
                    f"Luật {document_id}",
                    f"https://example.test/{document_id}",
                    "Luật",
                    "",
                    "Quốc hội",
                    None,
                    "",
                    "[]",
                ),
            )
            connection.execute(
                "INSERT INTO contents VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    document_id,
                    compressor.compress(content),
                    len(content),
                    digest,
                    "source.parquet",
                    document_id,
                    10,
                    "[]",
                ),
            )
        connection.execute(
            "INSERT INTO build_metadata VALUES ('build_report', ?)",
            (json.dumps(report),),
        )
        connection.execute(
            "INSERT INTO build_metadata VALUES ('status', 'complete')"
        )


def test_qdrant_audit_collects_unique_document_ids() -> None:
    from app.ingestion.v3_data_bundle import audit_qdrant_document_ids

    class Client:
        def scroll(self, **kwargs):
            if kwargs.get("offset") is None:
                return (
                    [
                        SimpleNamespace(payload={"document_id": 3}),
                        SimpleNamespace(payload={"document_id": 1}),
                    ],
                    "next",
                )
            return ([SimpleNamespace(payload={"document_id": 3})], None)

    manifest = audit_qdrant_document_ids(Client(), "v3")

    assert manifest["point_count"] == 3
    assert manifest["document_count"] == 2
    assert manifest["document_ids"] == [1, 3]


def test_export_content_store_subset_is_exact_and_compatible(tmp_path: Path) -> None:
    from app.ingestion.v3_data_bundle import export_content_store_subset

    source = tmp_path / "source.sqlite3"
    target = tmp_path / "subset.sqlite3"
    _source_store(source)

    report = export_content_store_subset(
        source_path=source,
        output_path=target,
        document_ids=[1, 3],
        collection="v3",
        point_count=3,
        dataset_revision="rev",
    )

    store = ContentStore(target)
    assert sorted(store.get_many([1, 2, 3])) == [1, 3]
    assert store.build_report().joined_count == 2
    assert store.build_report().average_sparse_document_length == 42.5
    assert report["document_count"] == 2
    assert report["integrity_check"] == "ok"
    with pytest.raises(FileExistsError):
        export_content_store_subset(
            source_path=source,
            output_path=target,
            document_ids=[1, 3],
            collection="v3",
            point_count=3,
            dataset_revision="rev",
        )


def test_export_rejects_ids_missing_from_source(tmp_path: Path) -> None:
    from app.ingestion.v3_data_bundle import export_content_store_subset

    source = tmp_path / "source.sqlite3"
    _source_store(source)

    with pytest.raises(ValueError, match="missing 1 requested documents"):
        export_content_store_subset(
            source_path=source,
            output_path=tmp_path / "subset.sqlite3",
            document_ids=[1, 99],
            collection="v3",
            point_count=2,
            dataset_revision="rev",
        )
