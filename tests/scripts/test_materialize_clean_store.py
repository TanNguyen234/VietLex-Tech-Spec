import hashlib
import json
import sqlite3

import pytest
import zstandard

from app.ingestion.content_store import SCHEMA, ContentStore, StoredDocument
from app.ingestion.legal_text import DocumentMetadata
from app.services.body_search import BodySearchIndex


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _document(identifier, text):
    metadata = DocumentMetadata(
        document_id=identifier,
        document_number=f"{identifier}/2020/QH14",
        title=f"Legal document {identifier}",
        source_url=f"https://example.test/{identifier}",
        legal_type="Luật",
        legal_sectors="",
        issuing_authority="Quốc hội",
        issuance_date="2020-01-01",
    )
    return StoredDocument(
        metadata=metadata,
        content=text,
        content_sha256=_sha(text),
        content_store_key=str(identifier),
        quality_flags=(),
    )


def _write_store(path, documents):
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.executemany(
            "INSERT INTO metadata VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    doc.metadata.document_id,
                    doc.metadata.document_number,
                    doc.metadata.title,
                    doc.metadata.source_url,
                    doc.metadata.legal_type,
                    doc.metadata.legal_sectors,
                    doc.metadata.issuing_authority,
                    doc.metadata.issuance_date,
                    "",
                    "[]",
                )
                for doc in documents
            ],
        )
        compressor = zstandard.ZstdCompressor(level=3)
        db.executemany(
            "INSERT INTO contents VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    doc.metadata.document_id,
                    compressor.compress(doc.content.encode("utf-8")),
                    len(doc.content.encode("utf-8")),
                    doc.content_sha256,
                    "shard.parquet",
                    doc.metadata.document_id - 1,
                    7,
                    "[]",
                )
                for doc in documents
            ],
        )
        report = {
            "metadata_count": len(documents),
            "content_count": len(documents),
            "joined_count": len(documents),
            "duplicate_content_hash_count": 0,
            "compressed_bytes": 0,
            "uncompressed_bytes": sum(len(doc.content.encode()) for doc in documents),
            "compression_ratio": 0.0,
            "average_sparse_document_length": 979.1241640033913,
            "quality_flag_counts": {},
            "source_shard_row_counts": {"shard.parquet": len(documents)},
            "schema_version": 1,
            "wall_seconds": 1.0,
        }
        db.executemany(
            "INSERT INTO build_metadata(key,value) VALUES (?,?)",
            [("status", "complete"), ("build_report", json.dumps(report))],
        )


def _write_overlay(path, base_doc, clean_text):
    path.mkdir()
    clean_db = path / "clean-delta.sqlite3"
    with sqlite3.connect(clean_db) as db:
        db.executescript(SCHEMA)
        doc = base_doc
        db.execute(
            "INSERT INTO metadata VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                doc.metadata.document_id,
                doc.metadata.document_number,
                doc.metadata.title,
                doc.metadata.source_url,
                doc.metadata.legal_type,
                doc.metadata.legal_sectors,
                doc.metadata.issuing_authority,
                doc.metadata.issuance_date,
                "",
                "[]",
            ),
        )
        encoded = clean_text.encode("utf-8")
        db.execute(
            "INSERT INTO contents VALUES (?,?,?,?,?,?,?,?)",
            (
                doc.metadata.document_id,
                zstandard.ZstdCompressor(level=3).compress(encoded),
                len(encoded),
                _sha(clean_text),
                "shard.parquet",
                doc.metadata.document_id - 1,
                5,
                "[]",
            ),
        )
    changes = path / "changes.jsonl"
    changes.write_text(
        json.dumps(
            {
                "document_id": base_doc.metadata.document_id,
                "base_sha256": base_doc.content_sha256,
                "cleaned_sha256": _sha(clean_text),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "changed_documents": 1,
        "representation": "changed-document overlay; base required",
        "artifacts": {
            name: {
                "bytes": artifact.stat().st_size,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            }
            for name, artifact in (("changes.jsonl", changes), ("clean-delta.sqlite3", clean_db))
        },
    }
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _write_candidate_plan(
    path, candidate_ids, *, revision, repository, count, overlay_manifest_sha256
):
    path.mkdir()
    plan = {
        "dataset": {
            "repository": repository,
            "revision": revision,
            "expected_document_count": count,
        },
        "clean_overlay": {
            "manifest_sha256": overlay_manifest_sha256,
            "changed_documents": 1,
        },
        "candidate_document_ids": candidate_ids,
    }
    plan_path = path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "artifacts": {
                    "plan.json": {
                        "bytes": plan_path.stat().st_size,
                        "sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                    }
                }
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def materialization_inputs(tmp_path):
    docs = [
        _document(1, "Điều 1. Raw legal text. TVPL Pro commercial link."),
        _document(2, "Điều 2. Existing body index document."),
        _document(3, "Điều 3. Candidate legal text three."),
        _document(4, "Điều 4. Candidate legal text four."),
    ]
    base = tmp_path / "base.sqlite3"
    _write_store(base, docs)
    body_index = tmp_path / "base-body.sqlite3"
    BodySearchIndex.build(body_index, docs[:2])
    overlay = tmp_path / "overlay"
    _write_overlay(overlay, docs[0], "Điều 1. Raw legal text.")
    candidate_plan = tmp_path / "candidate-plan"
    _write_candidate_plan(
        candidate_plan,
        [3, 4],
        revision="revision-test",
        repository="pinned/test-dataset",
        count=4,
        overlay_manifest_sha256=hashlib.sha256(
            (overlay / "manifest.json").read_bytes()
        ).hexdigest(),
    )
    return base, body_index, overlay, candidate_plan, docs


def test_materializes_atomic_clean_full_store_and_refreshes_only_body_delta(
    tmp_path, materialization_inputs
):
    from scripts.materialize_clean_store import materialize_clean_store

    base, body_index, overlay, candidate_plan, docs = materialization_inputs
    base_before = base.read_bytes()
    output = tmp_path / "clean-v1"

    report = materialize_clean_store(
        base_store=base,
        clean_overlay=overlay,
        base_body_index=body_index,
        candidate_plan_dir=candidate_plan,
        output_dir=output,
        expected_document_count=4,
        expected_overlay_count=1,
        expected_candidate_count=2,
        expected_refresh_count=1,
        expected_body_document_count=4,
        dataset_repository="pinned/test-dataset",
        dataset_revision="revision-test",
    )

    assert base.read_bytes() == base_before
    assert report["document_count"] == 4
    assert report["overlay_documents"] == 1
    assert report["candidate_documents"] == 2
    clean_store = ContentStore(output / "content_store.sqlite3")
    assert clean_store.get_many([1])[1].content == "Điều 1. Raw legal text."
    assert clean_store.get_many([3, 4])[3].content == docs[2].content
    with sqlite3.connect(output / "content_store.sqlite3") as db:
        metadata = dict(db.execute("SELECT key,value FROM build_metadata"))
        build_report = json.loads(metadata["build_report"])
        raw_build_report = json.loads(metadata["raw_build_report"])
        assert metadata["clean_dataset_revision"] == "revision-test"
        assert metadata["clean_base_store_path"] == str(base.resolve())
        assert metadata["clean_overlay_manifest_sha256"] == report["overlay_manifest_sha256"]
        assert build_report["average_sparse_document_length"] == 979.1241640033913
        assert raw_build_report["average_sparse_document_length"] == 979.1241640033913
        assert int(metadata["clean_body_index_document_count"]) == report["body_index"]["document_count"]
        assert int(metadata["clean_body_index_passage_count"]) == report["body_index"]["passage_count"]
        assert metadata["clean_body_index_source_sha256"] == report["body_index"]["source_sha256"]
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"

    body_search = BodySearchIndex(output / "legal_body_fts.sqlite3")
    coverage = body_search.coverage()
    assert coverage["document_count"] == 4
    assert body_search.search("Candidate legal text three")[0]["document_id"] == 3
    assert body_search.search("commercial link") == []

    with pytest.raises(FileExistsError):
        materialize_clean_store(
            base_store=base,
            clean_overlay=overlay,
            base_body_index=body_index,
            candidate_plan_dir=candidate_plan,
            output_dir=output,
            expected_document_count=4,
            expected_overlay_count=1,
            expected_candidate_count=2,
            expected_refresh_count=1,
            expected_body_document_count=4,
            dataset_repository="pinned/test-dataset",
            dataset_revision="revision-test",
        )


def test_materializer_rejects_overlay_base_hash_drift_without_publishing(
    tmp_path, materialization_inputs
):
    from scripts.materialize_clean_store import materialize_clean_store

    base, body_index, overlay, candidate_plan, _docs = materialization_inputs
    with sqlite3.connect(base) as db:
        db.execute(
            "UPDATE contents SET content_sha256=? WHERE document_id=1",
            ("0" * 64,),
        )
    output = tmp_path / "rejected-clean"

    with pytest.raises(ValueError, match="overlay_base_hash_mismatch"):
        materialize_clean_store(
            base_store=base,
            clean_overlay=overlay,
            base_body_index=body_index,
            candidate_plan_dir=candidate_plan,
            output_dir=output,
            expected_document_count=4,
            expected_overlay_count=1,
            expected_candidate_count=2,
            expected_refresh_count=1,
            expected_body_document_count=4,
            dataset_repository="pinned/test-dataset",
            dataset_revision="revision-test",
        )

    assert not output.exists()


def test_materializer_rejects_wrong_candidate_revision(tmp_path, materialization_inputs):
    from scripts.materialize_clean_store import materialize_clean_store

    base, body_index, overlay, candidate_plan, _docs = materialization_inputs
    with (candidate_plan / "plan.json").open("r+", encoding="utf-8") as stream:
        plan = json.load(stream)
        plan["dataset"]["revision"] = "wrong-revision"
        stream.seek(0)
        stream.truncate()
        json.dump(plan, stream)
    manifest = json.loads((candidate_plan / "manifest.json").read_text())
    plan_bytes = (candidate_plan / "plan.json").read_bytes()
    manifest["artifacts"]["plan.json"] = {
        "bytes": len(plan_bytes),
        "sha256": hashlib.sha256(plan_bytes).hexdigest(),
    }
    (candidate_plan / "manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="candidate_plan_revision_mismatch"):
        materialize_clean_store(
            base_store=base,
            clean_overlay=overlay,
            base_body_index=body_index,
            candidate_plan_dir=candidate_plan,
            output_dir=tmp_path / "wrong-revision",
            expected_document_count=4,
            expected_overlay_count=1,
            expected_candidate_count=2,
            expected_refresh_count=1,
            expected_body_document_count=4,
            dataset_repository="pinned/test-dataset",
            dataset_revision="revision-test",
        )
