from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import zstandard

from app.config import Settings
from app.ingestion.content_store import SCHEMA
from scripts.prepare_clean_corpus import prepare_delta


REVISION = "4d4e10b201544e8a4c49a1d3fa496595a7d486d0"
REPOSITORY = "vohuutridung/vietnamese-legal-documents"
AD = (
    "Bạn phải đăng nhập hoặc đăng ký Thành Viên TVPL Pro để sử dụng được "
    "đầy đủ các tiện ích gia tăng liên quan đến nội dung TCVN."
)
CONTACT = "Mọi chi tiết xin liên hệ: ĐT: (028) 3930 3279 DĐ: 0906 22 99 66"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _stored_document(
    db: sqlite3.Connection,
    document_id: int,
    content: str,
    *,
    source_shard: str = "source.parquet",
    source_row: int | None = None,
) -> None:
    encoded = content.encode("utf-8")
    compressed = zstandard.ZstdCompressor(level=3).compress(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    db.execute(
        "INSERT INTO metadata VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            document_id,
            f"{document_id}/2026/QH",
            f"Văn bản pháp luật {document_id}",
            f"https://example.invalid/{document_id}",
            "Luật",
            "",
            "Quốc hội",
            "2026-01-02",
            "",
            "[]",
        ),
    )
    db.execute(
        "INSERT INTO contents VALUES (?,?,?,?,?,?,?,?)",
        (
            document_id,
            compressed,
            len(encoded),
            digest,
            source_shard,
            document_id if source_row is None else source_row,
            8,
            "[]",
        ),
    )


def _fixture(root: Path) -> dict[str, Path | list[int]]:
    root.mkdir(parents=True, exist_ok=True)
    base = root / "base.sqlite3"
    affected_ids = list(range(1, 17))
    candidate_ids = list(range(100, 120))
    source_rows = []
    with sqlite3.connect(base) as db:
        db.executescript(SCHEMA)
        for index, document_id in enumerate(affected_ids):
            body = (
                f"Điều 1. Nội dung của văn bản {document_id}.\n\n"
                + AD
                + "\n\n"
                + CONTACT
                + f"\n\nĐiều 2. Quy định tiếp theo {document_id}."
            )
            _stored_document(
                db,
                document_id,
                body,
                source_shard="part-000.parquet",
                source_row=index,
            )
            source_rows.append({"id": document_id, "content": body})
        for document_id in candidate_ids:
            _stored_document(
                db,
                document_id,
                f"Điều 1. Văn bản sạch đủ điều kiện số {document_id} quy định rõ phạm vi và trách nhiệm.",
            )

    source_dir = root / "raw-source"
    source_dir.mkdir()
    pq.write_table(pa.Table.from_pylist(source_rows), source_dir / "part-000.parquet")
    source_inventory = [
        {
            "document_id": row["id"],
            "raw_sha256": _sha(row["content"]),
            "shard": "part-000.parquet",
            "row_zero_based": index,
        }
        for index, row in enumerate(source_rows)
    ]
    clean_overlay = root / "clean-overlay"
    prepare_delta(base, source_inventory, clean_overlay, source_dir=source_dir)

    candidates = []
    for document_id in candidate_ids:
        content = f"Điều 1. Văn bản sạch đủ điều kiện số {document_id} quy định rõ phạm vi và trách nhiệm."
        candidates.append(
            {
                "document_id": document_id,
                "document_number": f"{document_id}/2026/QH",
                "title": f"Văn bản pháp luật {document_id}",
                "legal_type": "Luật",
                "issuance_date": "2026-01-02",
                "source_content_sha256": _sha(content),
                "quality_flags": [],
                "content_hash_verified": True,
                "content_utf8_bytes": len(content.encode("utf-8")),
                "selected_points_cap_16": 1,
            }
        )
    candidate_selection = {
        "status": "ok",
        "limit": 20,
        "selected_count": 20,
        "selected_dataset_revision": REVISION,
        "absent_from": "union_of_qdrant_v3_body_and_supabase_document_ids",
        "embeddings_created": False,
        "upload_attempted": False,
        "selected_documents": candidates,
        "ordered_document_ids_sha256": hashlib.sha256(
            json.dumps(candidate_ids, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }
    online_inventory = root / "capacity_audit.json"
    _write_json(
        online_inventory,
        {
            "audit_id": "test-audit",
            "schema_version": 1,
            "dataset": {
                "repository": REPOSITORY,
                "revision": REVISION,
                "expected_document_count": 518255,
            },
            "online_capacity": {
                "document_id_consistency": {"status": "ok"},
                "qdrant": {"status": "ok"},
                "supabase": {"status": "ok"},
            },
            "candidate_inventory": {
                "candidate_selection": candidate_selection,
                "local_store": {"status": "ok"},
            },
            "capacity_gate": {"status": "blocked", "reasons": ["zero_cost_proof_missing"]},
            "side_effects": {
                "embeddings_created": False,
                "provider_sdk_clients_created": False,
                "remote_writes_attempted": False,
            },
        },
    )

    affected_online = root / "affected-online-readonly.json"
    _write_json(
        affected_online,
        {
            "scope": "live read-only; no providers or remote writes",
            "online_affected_document_count": len(affected_ids),
            "rows": [
                {"document_id": document_id, "content_sha256": _sha(source_rows[index]["content"])}
                for index, document_id in enumerate(affected_ids)
            ],
            "credential_presence": {"qdrant": True, "supabase_read": True},
        },
    )
    return {
        "clean_overlay": clean_overlay,
        "base_store": base,
        "online_inventory": online_inventory,
        "affected_online": affected_online,
        "output": root / "migration-plan",
        "affected_ids": affected_ids,
        "candidate_ids": candidate_ids,
    }


def _prepare(paths: dict[str, Path | list[int]]) -> dict:
    from scripts.prepare_corpus_migration import prepare_migration

    return prepare_migration(
        clean_overlay=paths["clean_overlay"],
        base_store=paths["base_store"],
        online_inventory=paths["online_inventory"],
        affected_online=paths["affected_online"],
        output=paths["output"],
    )


def _patch_settings(monkeypatch, migration) -> None:
    monkeypatch.setattr(
        migration,
        "get_settings",
        lambda: Settings(
            DATASET_REPOSITORY=REPOSITORY,
            DATASET_REVISION=REVISION,
            VERTEX_EMBEDDING_MODEL="gemini-embedding-2",
            VERTEX_QDRANT_COLLECTION_NAME="vietlex-legal-rag-v3-vertex-1024",
            VERTEX_QDRANT_VECTOR_SIZE=1024,
            VERTEX_QDRANT_MAX_CHUNKS_PER_DOCUMENT=16,
        ),
    )


def test_prepares_exact_plan_and_payloads_without_remote_side_effects(tmp_path, monkeypatch):
    from scripts import prepare_corpus_migration as migration

    paths = _fixture(tmp_path)
    _patch_settings(monkeypatch, migration)

    report = _prepare(paths)

    plan = json.loads((paths["output"] / "plan.json").read_text(encoding="utf-8"))
    assert report["remote_writes"] is False
    assert report["provider_calls"] == 0
    assert plan["summary"]["affected_replacements"] == 16
    assert plan["summary"]["candidate_additions"] == 20
    assert plan["summary"]["planned_new_documents"] == 36
    assert plan["summary"]["candidate_structural_records"] > 0
    assert plan["summary"]["dense_vector_bytes_lower_bound"] == (
        plan["summary"]["new_structural_records"] * 1024 * 4
    )
    assert plan["capacity_gate"]["status"] == "blocked"
    assert plan["capacity_gate"]["physical_capacity_inferred"] is False
    assert plan["legal_validity"] == "UNVERIFIED"
    assert len(plan["documents"]) == 36
    assert set(plan["candidate_document_ids"]) == set(paths["candidate_ids"])
    assert set(plan["affected_document_ids"]) == set(paths["affected_ids"])
    assert (paths["output"] / "old-structural-records.jsonl").is_file()
    assert (paths["output"] / "new-structural-records.jsonl").is_file()
    assert (paths["output"] / "supabase-upserts.jsonl").is_file()
    assert (paths["output"] / "qdrant-body-points.jsonl").is_file()
    manifest = json.loads((paths["output"] / "manifest.json").read_text(encoding="utf-8"))
    for name, entry in manifest["artifacts"].items():
        data = (paths["output"] / name).read_bytes()
        assert len(data) == entry["bytes"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    with pytest.raises(FileExistsError):
        _prepare(paths)


def test_rejects_overlay_artifact_hash_drift_before_creating_output(tmp_path, monkeypatch):
    from scripts import prepare_corpus_migration as migration

    paths = _fixture(tmp_path)
    _patch_settings(monkeypatch, migration)
    with (paths["clean_overlay"] / "changes.jsonl").open("a", encoding="utf-8") as stream:
        stream.write("{}\n")

    with pytest.raises(ValueError, match="overlay_artifact_hash_mismatch"):
        _prepare(paths)

    assert not paths["output"].exists()


def test_rejects_remote_affected_hash_drift(tmp_path, monkeypatch):
    from scripts import prepare_corpus_migration as migration

    paths = _fixture(tmp_path)
    _patch_settings(monkeypatch, migration)
    affected = json.loads(paths["affected_online"].read_text(encoding="utf-8"))
    affected["rows"][0]["content_sha256"] = "0" * 64
    _write_json(paths["affected_online"], affected)

    with pytest.raises(ValueError, match="affected_remote_hash_mismatch"):
        _prepare(paths)

    assert not paths["output"].exists()


def test_rejects_overlap_or_unusable_candidate_without_silently_skipping(tmp_path, monkeypatch):
    from scripts import prepare_corpus_migration as migration

    paths = _fixture(tmp_path)
    _patch_settings(monkeypatch, migration)
    audit = json.loads(paths["online_inventory"].read_text(encoding="utf-8"))
    audit["candidate_inventory"]["candidate_selection"]["selected_documents"][0][
        "document_id"
    ] = paths["affected_ids"][0]
    selected_ids = [
        row["document_id"]
        for row in audit["candidate_inventory"]["candidate_selection"][
            "selected_documents"
        ]
    ]
    audit["candidate_inventory"]["candidate_selection"][
        "ordered_document_ids_sha256"
    ] = hashlib.sha256(
        json.dumps(selected_ids, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    _write_json(paths["online_inventory"], audit)

    with pytest.raises(ValueError, match="candidate_overlap"):
        _prepare(paths)

    assert not paths["output"].exists()


def test_rejects_candidate_quality_flag(tmp_path, monkeypatch):
    from scripts import prepare_corpus_migration as migration

    paths = _fixture(tmp_path)
    _patch_settings(monkeypatch, migration)
    audit = json.loads(paths["online_inventory"].read_text(encoding="utf-8"))
    audit["candidate_inventory"]["candidate_selection"]["selected_documents"][0][
        "quality_flags"
    ] = ["encoding_damage"]
    _write_json(paths["online_inventory"], audit)

    with pytest.raises(ValueError, match="candidate_unusable_quality"):
        _prepare(paths)

    assert not paths["output"].exists()


def test_rejects_confirmed_ad_in_candidate_base_text(tmp_path, monkeypatch):
    from scripts import prepare_corpus_migration as migration

    paths = _fixture(tmp_path)
    _patch_settings(monkeypatch, migration)
    document_id = paths["candidate_ids"][0]
    with sqlite3.connect(paths["base_store"]) as db:
        row = db.execute(
            "SELECT content_zstd FROM contents WHERE document_id=?",
            (document_id,),
        ).fetchone()
        old = zstandard.ZstdDecompressor().decompress(row[0]).decode("utf-8")
        content = old + "\n\n" + AD
        encoded = content.encode("utf-8")
        db.execute(
            "UPDATE contents SET content_zstd=?, content_bytes=?, content_sha256=? "
            "WHERE document_id=?",
            (
                zstandard.ZstdCompressor(level=3).compress(encoded),
                len(encoded),
                hashlib.sha256(encoded).hexdigest(),
                document_id,
            ),
        )
    audit = json.loads(paths["online_inventory"].read_text(encoding="utf-8"))
    candidate = audit["candidate_inventory"]["candidate_selection"][
        "selected_documents"
    ][0]
    candidate["source_content_sha256"] = hashlib.sha256(encoded).hexdigest()
    candidate["content_utf8_bytes"] = len(encoded)
    _write_json(paths["online_inventory"], audit)

    with pytest.raises(ValueError, match="candidate_contains_confirmed_ad"):
        _prepare(paths)

    assert not paths["output"].exists()


def test_fails_if_record_builder_silently_skips_an_expected_candidate(
    tmp_path,
    monkeypatch,
):
    from scripts import prepare_corpus_migration as migration

    paths = _fixture(tmp_path)
    _patch_settings(monkeypatch, migration)
    original_builder = migration.build_vertex_records
    skipped_id = paths["candidate_ids"][0]

    def skip_candidate(store, document_ids, **kwargs):
        records = original_builder(store, document_ids, **kwargs)
        return [record for record in records if record.document_id != skipped_id]

    monkeypatch.setattr(migration, "build_vertex_records", skip_candidate)
    with pytest.raises(ValueError, match="new_structural_record_coverage_mismatch"):
        _prepare(paths)

    assert not paths["output"].exists()
