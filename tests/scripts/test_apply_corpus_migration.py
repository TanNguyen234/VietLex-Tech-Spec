from __future__ import annotations

import gzip
import hashlib
import json
import struct
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5
from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.ingestion.structural_index import StructuralRecord
from app.ingestion.structural_qdrant import point_payload
from app.ingestion.vertex_qdrant_migration import (
    VertexQdrantContract,
    build_vertex_point,
)


REPOSITORY = "vohuutridung/vietnamese-legal-documents"
REVISION = "4d4e10b201544e8a4c49a1d3fa496595a7d486d0"
PLAN_SCHEMA = "vietlex-corpus-migration-plan-v1"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _record(document_id: int, label: str, content_hash: str) -> dict:
    body = f"Nội dung Điều {document_id} {label}."
    return {
        "record_id": str(uuid5(NAMESPACE_URL, f"corpus-migration-test:{label}")),
        "body": body,
        "document_id": document_id,
        "document_number": f"{document_id}/2026/QH15",
        "title": f"Văn bản thử {document_id}",
        "source_url": f"https://example.test/{document_id}",
        "legal_type": "Luật",
        "issuing_authority": "Quốc hội",
        "issuance_date": "2026-01-01",
        "article": f"Điều {document_id}",
        "clause": None,
        "heading_path": f"Điều {document_id}",
        "citation": f"{document_id}/2026/QH15, Điều {document_id}",
        "token_count": 5,
        "dataset_revision": REVISION,
        "content_sha256": content_hash,
        "chunk_sha256": _sha(body),
        "embedding": None,
    }


def _row(document_id: int, content: str, content_hash: str) -> dict:
    return {
        "document_id": document_id,
        "document_number": f"{document_id}/2026/QH15",
        "title": f"Văn bản thử {document_id}",
        "source_url": f"https://example.test/{document_id}",
        "legal_type": "Luật",
        "legal_sectors": "Thử nghiệm",
        "issuing_authority": "Quốc hội",
        "issuance_date": "2026-01-01",
        "content": content,
        "content_sha256": content_hash,
        "content_store_key": str(document_id),
        "quality_flags": [],
        "dataset_revision": REVISION,
    }


def _body_point(document_id: int, content: str, content_hash: str) -> dict:
    row = _row(document_id, content, content_hash)
    return {
        "id": document_id,
        "vector": {},
        "payload": {
            "document_id": document_id,
            "body": row["content"],
            "content_sha256": row["content_sha256"],
            "legal_type": row["legal_type"],
            "issuing_authority": row["issuing_authority"],
            "issuance_date": row["issuance_date"],
        },
    }


def _dense_vector() -> list[float]:
    return [1.0 / 32.0] * 1024


def _backup_point(record: dict) -> dict:
    parsed = StructuralRecord.model_validate(record)
    sparse = SimpleNamespace(indices=[17, 29], values=[0.25, 0.5])
    built = build_vertex_point(
        parsed,
        dense_vector=_dense_vector(),
        sparse_vector=sparse,
        contract=VertexQdrantContract(),
    )
    return {
        "id": parsed.record_id,
        "payload": built.payload,
        "vector": {
            "dense": _dense_vector(),
            "sparse": {"indices": [17, 29], "values": [0.25, 0.5]},
        },
    }


def _jsonl(rows: list[dict]) -> bytes:
    return b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        for row in rows
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _fixture(tmp_path: Path, *, doc2_overlap: bool = True) -> dict:
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()

    old_records: list[dict] = []
    new_records: list[dict] = []
    old_rows: list[dict] = []
    old_body: list[dict] = []
    old_points: list[dict] = []
    documents: list[dict] = []
    rows: list[dict] = []
    bodies: list[dict] = []

    for document_id in range(1, 37):
        old_hash = _sha(f"old content {document_id}") if document_id <= 16 else None
        new_hash = _sha(f"new content {document_id}")
        old_content = f"old content {document_id}" if old_hash else None
        new_content = f"new content {document_id}"
        old_for_doc: list[dict] = []
        new_for_doc: list[dict] = []
        if document_id <= 16:
            if document_id == 2 and doc2_overlap:
                old_for_doc = [
                    _record(document_id, "shared-2", old_hash),
                    _record(document_id, "stale-2", old_hash),
                ]
                new_for_doc = [
                    _record(document_id, "shared-2", new_hash),
                    _record(document_id, "fresh-2", new_hash),
                ]
            else:
                old_for_doc = [_record(document_id, f"old-{document_id}", old_hash)]
                new_for_doc = [_record(document_id, f"new-{document_id}", new_hash)]
            old_records.extend(old_for_doc)
            old_row = _row(document_id, old_content, old_hash)
            old_row["uploaded_at"] = "2026-10-01T00:00:00+00:00"
            old_rows.append(old_row)
            old_body.append(_body_point(document_id, old_content, old_hash))
            old_points.extend(_backup_point(record) for record in old_for_doc)
        else:
            new_for_doc = [_record(document_id, f"new-{document_id}", new_hash)]
        new_records.extend(new_for_doc)
        row = _row(document_id, new_content, new_hash)
        rows.append(row)
        bodies.append(_body_point(document_id, new_content, new_hash))
        documents.append(
            {
                "document_id": document_id,
                "action": "replace_cleaned" if document_id <= 16 else "insert_absent_candidate",
                "new_content_sha256": new_hash,
                "old_content_sha256": old_hash,
                "old_structural_point_ids": [item["record_id"] for item in old_for_doc],
                "new_structural_point_ids": [item["record_id"] for item in new_for_doc],
                "old_body_point_id": document_id if document_id <= 16 else None,
                "new_body_point_id": document_id,
                "old_structural_record_count": len(old_for_doc),
                "new_structural_record_count": len(new_for_doc),
                "old_structural_record_json_bytes": 1,
                "new_structural_record_json_bytes": 1,
                "old_structural_payload_json_bytes": 1,
                "supabase_upsert_json_bytes": len(json.dumps(row).encode()),
                "body_qdrant_point_json_bytes": len(json.dumps(bodies[-1]).encode()),
                "new_structural_payload_json_bytes": 1,
            }
        )

    artifact_values = {
        "old-structural-records.jsonl": _jsonl(old_records),
        "new-structural-records.jsonl": _jsonl(new_records),
        "supabase-upserts.jsonl": _jsonl(rows),
        "qdrant-body-points.jsonl": _jsonl(bodies),
    }
    summary = {
        "affected_replacements": 16,
        "candidate_additions": 20,
        "planned_new_documents": 36,
        "old_structural_records": len(old_records),
        "new_structural_records": len(new_records),
        "new_body_points": 36,
        "serialized_body_qdrant_points_json_bytes": len(artifact_values["qdrant-body-points.jsonl"]),
        "serialized_new_structural_payload_bytes": sum(
            len(json.dumps(point_payload(StructuralRecord.model_validate(record)), ensure_ascii=False, separators=(",", ":")).encode())
            for record in new_records
        ),
        "dense_vector_bytes_lower_bound": len(new_records) * 1024 * 4,
        "serialized_supabase_upserts_json_bytes": len(artifact_values["supabase-upserts.jsonl"]),
    }
    plan = {
        "schema_version": PLAN_SCHEMA,
        "dataset": {
            "repository": REPOSITORY,
            "revision": REVISION,
            "expected_document_count": 518255,
        },
        "embedding_contract": {
            "collection": "vietlex-legal-rag-v3-vertex-1024",
            "model": "gemini-embedding-2",
            "dimension": 1024,
            "chunk_max_tokens": 320,
            "chunk_overlap_tokens": 32,
            "max_chunks_per_document": 16,
        },
        "capacity_gate": {"physical_capacity_inferred": False},
        "affected_online_snapshot": {"snapshot_sha256": "c" * 64},
        "affected_document_ids": list(range(1, 17)),
        "candidate_document_ids": list(range(17, 37)),
        "documents": documents,
        "summary": summary,
        "remote_writes": False,
        "provider_calls": 0,
        "apply_status": "NOT RUN",
        "legal_validity": "UNVERIFIED",
    }
    artifact_values["plan.json"] = (
        json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    manifest = {
        "schema_version": "vietlex-corpus-migration-preparation-v1",
        "artifacts": {
            name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in artifact_values.items()
        },
        "remote_writes": False,
        "provider_calls": 0,
        "legal_validity": "UNVERIFIED",
    }
    for name, data in artifact_values.items():
        (plan_dir / name).write_bytes(data)
    _write_json(plan_dir / "manifest.json", manifest)

    backup_files = {
        "supabase-original.json.gz": gzip.compress(
            json.dumps(old_rows, ensure_ascii=False, sort_keys=True).encode()
        ),
        "qdrant-body-original.json.gz": gzip.compress(
            json.dumps(old_body, ensure_ascii=False, sort_keys=True).encode()
        ),
        "qdrant-v3-original.jsonl.gz": gzip.compress(_jsonl(old_points)),
    }
    for name, data in backup_files.items():
        (backup_dir / name).write_bytes(data)
    v3_hash = hashlib.sha256(backup_files["qdrant-v3-original.jsonl.gz"]).hexdigest()
    _write_json(
        backup_dir / "v3-manifest.json",
        {
            "scope": "live read-only Qdrant scroll/retrieve; zero remote writes/providers",
            "backed_up_points": len(old_points),
            "backed_up_documents": 16,
            "all_expected_old_ids_match": True,
            "backup_sha256": v3_hash,
            "candidate_ids_absent_from_v3": True,
        },
    )
    _write_json(backup_dir / "contract-comparison.json", {
        "checked_points": len(old_points),
        "mismatches": [],
        "average_sparse_document_length": 979.1241640033913,
    })
    _write_json(backup_dir / "supabase-contract-comparison.json", {
        "checked_documents": 16,
        "mismatches": [],
    })
    backup_artifacts = {}
    for name in [
        "contract-comparison.json",
        "qdrant-body-original.json.gz",
        "qdrant-v3-original.jsonl.gz",
        "supabase-contract-comparison.json",
        "supabase-original.json.gz",
        "v3-manifest.json",
    ]:
        data = (backup_dir / name).read_bytes()
        backup_artifacts[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    _write_json(backup_dir / "manifest.json", {
        "scope": "immutable local backup integrity; remote drift must be rechecked immediately before each write",
        "artifacts": backup_artifacts,
    })
    capacity = {
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "evidence_level": "live authenticated UI; read-only SQL",
        "qdrant": {
            "status": "HEALTHY",
            "disk_used_gib_displayed": 2.19,
            "disk_quota_gib_displayed": 4,
            "ram_used_mib_displayed": 613.77,
            "ram_quota_gib_displayed": 1,
        },
        "supabase": {
            "database_sum_bytes_select": 365112994,
            "dashboard_database_mb_displayed": 373,
            "dashboard_quota_mb_displayed": 500,
            "conservative_baseline_bytes_for_gate": 373000000,
        },
    }
    capacity_path = tmp_path / "capacity.json"
    _write_json(capacity_path, capacity)
    plan_sha = hashlib.sha256(artifact_values["plan.json"]).hexdigest()
    estimate = {
        "scope": "conservative planning assumptions, not measured growth or hard runtime quota enforcement",
        "physical_receipt_sha256": hashlib.sha256(capacity_path.read_bytes()).hexdigest(),
        "plan_sha256": plan_sha,
        "ceiling_fraction": 0.8,
        "supabase_estimated_transient_allowance_bytes": 4 * summary["serialized_supabase_upserts_json_bytes"],
        "qdrant_estimated_transient_allowance_bytes": 8 * (
            summary["serialized_body_qdrant_points_json_bytes"]
            + summary["serialized_new_structural_payload_bytes"]
            + summary["dense_vector_bytes_lower_bound"]
        ),
        "canary_required": True,
        "remote_writes": False,
        "preparation_gate": True,
    }
    estimate_path = tmp_path / "capacity-estimate.json"
    _write_json(estimate_path, estimate)
    return {
        "plan_dir": plan_dir,
        "backup_dir": backup_dir,
        "capacity_path": capacity_path,
        "estimate_path": estimate_path,
        "plan": plan,
        "old_records": old_records,
        "new_records": new_records,
        "old_rows": old_rows,
        "old_body": old_body,
        "old_points": old_points,
    }


def _settings(*, legacy: bool = False) -> Settings:
    return Settings(
        _env_file=None,
        DATASET_REPOSITORY=REPOSITORY,
        DATASET_REVISION=REVISION,
        EXPECTED_DOCUMENT_COUNT=518255,
        USE_LEGACY_FREE_PIPELINE=legacy,
    )


class _FakeProvider:
    def __init__(self, *, values: list[float] | None = None) -> None:
        self.calls: list[tuple[str, str | None, int]] = []
        self.values = values or _dense_vector()

    async def embed_document(self, text: str, *, title: str, output_dimensionality: int):
        self.calls.append((text, title, output_dimensionality))
        return SimpleNamespace(values=self.values, output_dimensionality=len(self.values))


class _FakeStores:
    def __init__(
        self,
        fixture: dict,
        *,
        mismatch_after_upsert: bool = False,
        qdrant_float32: bool = False,
    ) -> None:
        self.fixture = fixture
        self.plan = fixture["plan"]
        self.document_id = None
        self.supabase: dict[int, dict] = {
            row["document_id"]: row for row in fixture["old_rows"]
        }
        self.body: dict[int, dict] = {
            point["id"]: point for point in fixture["old_body"]
        }
        self.v3: dict[str, dict] = {
            point["id"]: point for point in fixture["old_points"]
        }
        self.mismatch_after_upsert = mismatch_after_upsert
        self.qdrant_float32 = qdrant_float32
        self.fail_next_supabase_write = False
        self.corrupt_next_body_read = False
        self.writes: list[tuple[str, object]] = []
        self.deletes: list[tuple[str, list]] = []
        self.reads = 0

    def get_supabase(self, document_id: int):
        return self.supabase.get(document_id)

    def get_body(self, document_id: int):
        point = self.body.get(document_id)
        if self.mismatch_after_upsert and self.corrupt_next_body_read and point is not None:
            self.corrupt_next_body_read = False
            point = json.loads(json.dumps(point))
            point["payload"]["body"] = "corrupted readback"
        return point

    def v3_for_document(self, document_id: int):
        return [
            point for point in self.v3.values()
            if point["payload"]["document_id"] == document_id
        ]

    def v3_retrieve(self, ids: list[str]):
        return [self.v3[item] for item in ids if item in self.v3]

    def upsert_v3(self, points: list[dict]) -> None:
        self.writes.append(("v3", [point["id"] for point in points]))
        for point in points:
            stored = json.loads(json.dumps(point))
            if self.qdrant_float32:
                for index, value in enumerate(stored["vector"]["dense"]):
                    stored["vector"]["dense"][index] = struct.unpack("!f", struct.pack("!f", value))[0]
                norm = sum(value * value for value in stored["vector"]["dense"]) ** 0.5
                stored["vector"]["dense"] = [
                    struct.unpack("!f", struct.pack("!f", value / norm))[0]
                    for value in stored["vector"]["dense"]
                ]
                for index, value in enumerate(stored["vector"]["sparse"]["values"]):
                    stored["vector"]["sparse"]["values"][index] = struct.unpack("!f", struct.pack("!f", value))[0]
            self.v3[point["id"]] = stored

    def upsert_supabase(self, row: dict) -> None:
        self.writes.append(("supabase", row["document_id"]))
        if self.fail_next_supabase_write:
            self.fail_next_supabase_write = False
            raise RuntimeError("simulated_process_interruption")
        self.supabase[row["document_id"]] = row

    def upsert_body(self, point: dict) -> None:
        self.writes.append(("body", point["id"]))
        self.body[point["id"]] = point
        if self.mismatch_after_upsert and point["payload"]["content_sha256"] == self.plan["documents"][0]["new_content_sha256"]:
            self.corrupt_next_body_read = True

    def delete_v3(self, ids: list[str]) -> None:
        self.deletes.append(("v3", list(ids)))
        for item in ids:
            self.v3.pop(item, None)

    def delete_supabase(self, document_id: int) -> None:
        self.deletes.append(("supabase", [document_id]))
        self.supabase.pop(document_id, None)

    def delete_body(self, document_id: int) -> None:
        self.deletes.append(("body", [document_id]))
        self.body.pop(document_id, None)


def _write_vector_artifact(
    fixture: dict,
    document_id: int,
    path: Path,
    *,
    dense_values: list[float] | None = None,
) -> Path:
    from app.ingestion.structural_qdrant import build_structural_inference_text
    from app.ingestion.pinecone_store import FastSparseEncoder

    plan_dir = fixture["plan_dir"]
    manifest = json.loads((plan_dir / "manifest.json").read_text(encoding="utf-8"))
    plan_bytes = (plan_dir / "plan.json").read_bytes()
    contract = VertexQdrantContract()
    header = {
        "type": "header",
        "schema_version": "vietlex-prepared-vectors-v1",
        "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "plan_artifact_sha256": manifest["artifacts"]["new-structural-records.jsonl"]["sha256"],
        "document_id": document_id,
        "embedding_contract": {
            "collection": contract.collection_name,
            "model": contract.embedding_model,
            "dimension": contract.vector_size,
            "sparse_average_document_length": 979.1241640033913,
            "sparse_max_nonzero_terms": 64,
        },
    }
    records = [r for r in fixture["new_records"] if r["document_id"] == document_id]
    encoder = FastSparseEncoder(average_document_length=979.1241640033913, max_nonzero_terms=64)
    lines = [json.dumps(header, ensure_ascii=False, sort_keys=True)]
    for record in records:
        parsed = StructuralRecord.model_validate(record)
        inference_text = build_structural_inference_text(parsed)
        sparse = encoder.encode_document(inference_text)
        lines.append(json.dumps({
            "type": "vector",
            "record_id": parsed.record_id,
            "inference_text_sha256": _sha(inference_text),
            "dense": dense_values if dense_values is not None else _dense_vector(),
            "sparse_indices": sparse.indices,
            "sparse_values": sparse.values,
        }, ensure_ascii=False, sort_keys=True))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _apply_clean_canary(fixture: dict, stores: _FakeStores, journal_dir: Path) -> None:
    from scripts.apply_corpus_migration import apply_one

    vectors = _write_vector_artifact(
        fixture,
        1,
        journal_dir.parent / "clean-canary-vectors.jsonl",
    )
    apply_one(
        plan_dir=fixture["plan_dir"],
        vectors_path=vectors,
        backup_dir=fixture["backup_dir"],
        capacity_receipt=fixture["capacity_path"],
        capacity_estimate=fixture["estimate_path"],
        document_id=1,
        journal_dir=journal_dir,
        settings=_settings(),
        storage=stores,
        allow_storage_write=True,
    )


@pytest.mark.asyncio
async def test_legacy_guard_runs_before_provider_construction(tmp_path) -> None:
    from scripts.apply_corpus_migration import prepare_vectors

    fixture = _fixture(tmp_path)
    provider_calls: list[object] = []
    with pytest.raises(PermissionError, match="legacy"):
        await prepare_vectors(
            plan_dir=fixture["plan_dir"],
            document_id=17,
            output=tmp_path / "vectors.jsonl",
            settings=_settings(legacy=True),
            provider_factory=lambda **_: provider_calls.append(object()),
            allow_paid_provider=True,
        )
    assert provider_calls == []


@pytest.mark.asyncio
async def test_prepare_vectors_rejects_invalid_dimension_and_records_failure(tmp_path) -> None:
    from scripts.apply_corpus_migration import prepare_vectors

    fixture = _fixture(tmp_path)
    provider = _FakeProvider(values=[0.0] * 1023)
    target = tmp_path / "vectors.jsonl"
    with pytest.raises(ValueError, match="dimension"):
        await prepare_vectors(
            plan_dir=fixture["plan_dir"],
            document_id=17,
            output=target,
            settings=_settings(),
            provider_factory=lambda **_: provider,
            allow_paid_provider=True,
        )
    assert len(provider.calls) == 1
    assert len(target.read_text(encoding="utf-8").splitlines()) == 1
    assert list(tmp_path.glob("vectors.jsonl.failure-*.json"))


@pytest.mark.asyncio
async def test_paid_provider_flag_is_required_before_provider_construction(tmp_path) -> None:
    from scripts.apply_corpus_migration import prepare_vectors

    fixture = _fixture(tmp_path)
    provider_created: list[bool] = []
    with pytest.raises(PermissionError, match="allow_paid_provider"):
        await prepare_vectors(
            plan_dir=fixture["plan_dir"],
            document_id=17,
            output=tmp_path / "vectors.jsonl",
            settings=_settings(),
            provider_factory=lambda **_: provider_created.append(True),
            allow_paid_provider=False,
        )
    assert provider_created == []


@pytest.mark.asyncio
async def test_matching_preflight_vector_is_reused_without_provider(tmp_path) -> None:
    from app.ingestion.structural_qdrant import build_structural_inference_text
    from scripts.apply_corpus_migration import prepare_vectors

    fixture = _fixture(tmp_path)
    record = StructuralRecord.model_validate(
        next(item for item in fixture["new_records"] if item["document_id"] == 17)
    )
    inference_hash = _sha(build_structural_inference_text(record))
    vector_path = tmp_path / "preflight-vector.jsonl"
    vector = {
        "record": record.model_dump(mode="json"),
        "values": _dense_vector(),
        "inference_text_sha256": inference_hash,
    }
    vector_path.write_text(json.dumps(vector, ensure_ascii=False) + "\n", encoding="utf-8")
    receipt_path = tmp_path / "preflight-receipt.json"
    _write_json(receipt_path, {
        "scope": "live authorized Vertex embedding; zero remote storage writes",
        "model": "gemini-embedding-2",
        "dimension": 1024,
        "dimension_observed": 1024,
        "sdk_retries": 0,
        "record_id": record.record_id,
        "source_sha256": record.content_sha256,
        "inference_text_sha256": inference_hash,
        "provider_adapter_calls_started": 1,
        "status": "ok",
        "l2_norm": 1.0,
        "vector_artifact_sha256": hashlib.sha256(vector_path.read_bytes()).hexdigest(),
    })
    provider_created: list[bool] = []
    result = await prepare_vectors(
        plan_dir=fixture["plan_dir"],
        document_id=17,
        output=tmp_path / "vectors.jsonl",
        settings=_settings(),
        provider_factory=lambda **_: provider_created.append(True),
        preflight_receipt=receipt_path,
        preflight_vector=vector_path,
        allow_paid_provider=False,
    )
    assert provider_created == []
    assert result["provider_calls"] == 0
    assert result["preflight_vectors_reused"] == 1
    assert len((tmp_path / "vectors.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_plan_artifact_hash_is_checked_before_storage_factory(tmp_path) -> None:
    from scripts.apply_corpus_migration import apply_one

    fixture = _fixture(tmp_path)
    vectors = _write_vector_artifact(fixture, 17, tmp_path / "vectors.jsonl")
    with (fixture["plan_dir"] / "supabase-upserts.jsonl").open("ab") as stream:
        stream.write(b"tampered")
    storage_created: list[bool] = []
    with pytest.raises(ValueError, match="artifact_hash"):
        apply_one(
            plan_dir=fixture["plan_dir"],
            vectors_path=vectors,
            backup_dir=fixture["backup_dir"],
            capacity_receipt=fixture["capacity_path"],
            capacity_estimate=fixture["estimate_path"],
            document_id=17,
            journal_dir=tmp_path / "journal",
            settings=_settings(),
            storage_factory=lambda _settings: storage_created.append(True),
            allow_storage_write=True,
        )
    assert storage_created == []


def test_candidate_collision_stops_before_any_write(tmp_path) -> None:
    from scripts.apply_corpus_migration import apply_one

    fixture = _fixture(tmp_path)
    vectors = _write_vector_artifact(fixture, 17, tmp_path / "vectors.jsonl")
    stores = _FakeStores(fixture)
    _apply_clean_canary(fixture, stores, tmp_path / "journal")
    writes_before = list(stores.writes)
    deletes_before = list(stores.deletes)
    stores.supabase[17] = _row(17, "unexpected", _sha("unexpected"))
    with pytest.raises(ValueError, match="candidate_collision"):
        apply_one(
            plan_dir=fixture["plan_dir"],
            vectors_path=vectors,
            backup_dir=fixture["backup_dir"],
            capacity_receipt=fixture["capacity_path"],
            capacity_estimate=fixture["estimate_path"],
            document_id=17,
            journal_dir=tmp_path / "journal",
            settings=_settings(),
            storage=stores,
            allow_storage_write=True,
        )
    assert stores.writes == writes_before
    assert stores.deletes == deletes_before


def test_apply_one_deletes_only_superseded_ids_after_readback(tmp_path) -> None:
    from scripts.apply_corpus_migration import apply_one

    fixture = _fixture(tmp_path, doc2_overlap=True)
    vectors = _write_vector_artifact(fixture, 2, tmp_path / "vectors.jsonl")
    stores = _FakeStores(fixture)
    result = apply_one(
        plan_dir=fixture["plan_dir"],
        vectors_path=vectors,
        backup_dir=fixture["backup_dir"],
        capacity_receipt=fixture["capacity_path"],
        capacity_estimate=fixture["estimate_path"],
        document_id=2,
        journal_dir=tmp_path / "journal",
        settings=_settings(),
        storage=stores,
        allow_storage_write=True,
    )
    document = next(item for item in fixture["plan"]["documents"] if item["document_id"] == 2)
    expected_delete = sorted(set(document["old_structural_point_ids"]) - set(document["new_structural_point_ids"]))
    assert result["status"] == "complete"
    assert stores.deletes == ([ ("v3", expected_delete) ] if expected_delete else [])
    assert set(stores.v3_for_document(2)[i]["id"] for i in range(len(stores.v3_for_document(2)))) == set(document["new_structural_point_ids"])


def test_remaining_documents_wait_for_post_canary_capacity_receipt(tmp_path) -> None:
    from scripts.apply_corpus_migration import apply_one

    fixture = _fixture(tmp_path)
    stores = _FakeStores(fixture)
    journal_dir = tmp_path / "journal"
    _apply_clean_canary(fixture, stores, journal_dir)
    candidate_vectors = _write_vector_artifact(fixture, 17, tmp_path / "candidate-vectors.jsonl")
    apply_one(
        plan_dir=fixture["plan_dir"],
        vectors_path=candidate_vectors,
        backup_dir=fixture["backup_dir"],
        capacity_receipt=fixture["capacity_path"],
        capacity_estimate=fixture["estimate_path"],
        document_id=17,
        journal_dir=journal_dir,
        settings=_settings(),
        storage=stores,
        allow_storage_write=True,
    )
    writes_after_canaries = list(stores.writes)
    with pytest.raises(ValueError, match="post_canary_capacity_receipt_required"):
        new_vectors = _write_vector_artifact(fixture, 18, tmp_path / "next-vectors.jsonl")
        apply_one(
            plan_dir=fixture["plan_dir"],
            vectors_path=new_vectors,
            backup_dir=fixture["backup_dir"],
            capacity_receipt=fixture["capacity_path"],
            capacity_estimate=fixture["estimate_path"],
            document_id=18,
            journal_dir=journal_dir,
            settings=_settings(),
            storage=stores,
            allow_storage_write=True,
        )
    assert stores.writes == writes_after_canaries

    capacity = json.loads(fixture["capacity_path"].read_text(encoding="utf-8"))
    capacity["observed_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_json(fixture["capacity_path"], capacity)
    estimate = json.loads(fixture["estimate_path"].read_text(encoding="utf-8"))
    estimate["physical_receipt_sha256"] = hashlib.sha256(fixture["capacity_path"].read_bytes()).hexdigest()
    _write_json(fixture["estimate_path"], estimate)
    for document_id in (18, 19, 20):
        new_vectors = _write_vector_artifact(
            fixture, document_id, tmp_path / f"next-vectors-{document_id}.jsonl"
        )
        result = apply_one(
            plan_dir=fixture["plan_dir"],
            vectors_path=new_vectors,
            backup_dir=fixture["backup_dir"],
            capacity_receipt=fixture["capacity_path"],
            capacity_estimate=fixture["estimate_path"],
            document_id=document_id,
            journal_dir=journal_dir,
            settings=_settings(),
            storage=stores,
            allow_storage_write=True,
        )
        assert result["status"] == "complete"


def test_canary_chronology_uses_completion_time_when_document_ids_sort_earlier(tmp_path) -> None:
    from scripts.apply_corpus_migration import _canary_progress

    plan_sha256 = "a" * 64
    document_ids = (387595, 697645, 2468, 2503)
    documents = {
        document_id: {
            "action": "replace_cleaned" if document_id == 387595 else "insert_absent_candidate",
            "supabase_upsert_json_bytes": 1 if document_id == 697645 else 10,
            "body_qdrant_point_json_bytes": 1 if document_id == 697645 else 10,
            "new_structural_payload_json_bytes": 1 if document_id == 697645 else 10,
            "new_structural_point_ids": ["point"] if document_id == 697645 else ["point-a", "point-b"],
        }
        for document_id in document_ids
    }
    bundle = SimpleNamespace(
        plan_sha256=plan_sha256,
        documents=documents,
        candidate_ids={697645, 2468, 2503},
    )
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    completed = (
        (387595, "replace_cleaned", "2026-10-27T01:00:00Z"),
        (697645, "insert_absent_candidate", "2026-10-27T02:00:00Z"),
        (2468, "insert_absent_candidate", "2026-10-27T03:00:00Z"),
    )
    for document_id, action, completed_at in completed:
        rows = [
            {"event": "start", "plan_sha256": plan_sha256, "document_id": document_id, "action": action},
            {"event": "complete", "timestamp_utc": completed_at},
        ]
        (journal_dir / f"{document_id}.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n",
            encoding="utf-8",
        )

    progress = _canary_progress(
        bundle=bundle,
        document_id=2503,
        journal_dir=journal_dir,
        capacity={"observed_datetime_utc": "2026-10-27T04:00:00Z"},
    )
    assert progress == "post_canary_capacity_verified"


def test_readback_mismatch_triggers_compensating_restore_and_failure_journal(tmp_path) -> None:
    from scripts.apply_corpus_migration import apply_one

    fixture = _fixture(tmp_path)
    vectors = _write_vector_artifact(fixture, 1, tmp_path / "vectors.jsonl")
    stores = _FakeStores(fixture, mismatch_after_upsert=True)
    original_body = next(item for item in fixture["old_body"] if item["id"] == 1)
    with pytest.raises(RuntimeError, match="readback"):
        apply_one(
            plan_dir=fixture["plan_dir"],
            vectors_path=vectors,
            backup_dir=fixture["backup_dir"],
            capacity_receipt=fixture["capacity_path"],
            capacity_estimate=fixture["estimate_path"],
            document_id=1,
            journal_dir=tmp_path / "journal",
            settings=_settings(),
            storage=stores,
            allow_storage_write=True,
        )
    assert stores.body[1] == original_body
    journal = tmp_path / "journal" / "1.jsonl"
    events = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert any(item.get("event") == "failure" for item in events)
    assert any(item.get("event") == "rollback_complete" for item in events)


def test_stale_capacity_receipt_is_rejected_before_storage_creation(tmp_path) -> None:
    from scripts.apply_corpus_migration import apply_one

    fixture = _fixture(tmp_path)
    vectors = _write_vector_artifact(fixture, 17, tmp_path / "vectors.jsonl")
    capacity = json.loads(fixture["capacity_path"].read_text(encoding="utf-8"))
    capacity["observed_at_utc"] = "2020-01-01T00:00:00Z"
    _write_json(fixture["capacity_path"], capacity)
    storage_created: list[bool] = []
    with pytest.raises(ValueError, match="capacity_receipt_stale"):
        apply_one(
            plan_dir=fixture["plan_dir"],
            vectors_path=vectors,
            backup_dir=fixture["backup_dir"],
            capacity_receipt=fixture["capacity_path"],
            capacity_estimate=fixture["estimate_path"],
            document_id=17,
            journal_dir=tmp_path / "journal",
            settings=_settings(),
            storage_factory=lambda _settings: storage_created.append(True),
            allow_storage_write=True,
        )
    assert storage_created == []


def test_capacity_projection_over_eighty_percent_stops_before_storage_creation(tmp_path) -> None:
    from scripts.apply_corpus_migration import apply_one

    fixture = _fixture(tmp_path)
    vectors = _write_vector_artifact(fixture, 17, tmp_path / "vectors.jsonl")
    capacity = json.loads(fixture["capacity_path"].read_text(encoding="utf-8"))
    capacity["qdrant"]["disk_used_gib_displayed"] = 3.2
    _write_json(fixture["capacity_path"], capacity)
    estimate = json.loads(fixture["estimate_path"].read_text(encoding="utf-8"))
    estimate["physical_receipt_sha256"] = hashlib.sha256(fixture["capacity_path"].read_bytes()).hexdigest()
    _write_json(fixture["estimate_path"], estimate)
    storage_created: list[bool] = []
    with pytest.raises(ValueError, match="capacity_safety_ceiling"):
        apply_one(
            plan_dir=fixture["plan_dir"],
            vectors_path=vectors,
            backup_dir=fixture["backup_dir"],
            capacity_receipt=fixture["capacity_path"],
            capacity_estimate=fixture["estimate_path"],
            document_id=17,
            journal_dir=tmp_path / "journal",
            settings=_settings(),
            storage_factory=lambda _settings: storage_created.append(True),
            allow_storage_write=True,
        )
    assert storage_created == []


def test_manual_rollback_restores_exact_old_v3_ids_and_supabase_body(tmp_path) -> None:
    from scripts.apply_corpus_migration import apply_one, rollback_one

    fixture = _fixture(tmp_path)
    vectors = _write_vector_artifact(fixture, 1, tmp_path / "vectors.jsonl")
    stores = _FakeStores(fixture)
    apply_one(
        plan_dir=fixture["plan_dir"],
        vectors_path=vectors,
        backup_dir=fixture["backup_dir"],
        capacity_receipt=fixture["capacity_path"],
        capacity_estimate=fixture["estimate_path"],
        document_id=1,
        journal_dir=tmp_path / "journal",
        settings=_settings(),
        storage=stores,
        allow_storage_write=True,
    )
    rollback_one(
        plan_dir=fixture["plan_dir"],
        vectors_path=vectors,
        backup_dir=fixture["backup_dir"],
        capacity_receipt=fixture["capacity_path"],
        capacity_estimate=fixture["estimate_path"],
        document_id=1,
        journal_dir=tmp_path / "journal",
        settings=_settings(),
        storage=stores,
        allow_storage_write=True,
    )
    assert stores.supabase[1] == next(row for row in fixture["old_rows"] if row["document_id"] == 1)
    assert stores.body[1] == next(point for point in fixture["old_body"] if point["id"] == 1)
    expected_ids = {point["id"] for point in fixture["old_points"] if point["payload"]["document_id"] == 1}
    assert {point["id"] for point in stores.v3_for_document(1)} == expected_ids


def test_qdrant_float32_readback_is_accepted_for_dense_and_sparse_vectors(tmp_path) -> None:
    from scripts.apply_corpus_migration import apply_one

    fixture = _fixture(tmp_path)
    vectors = _write_vector_artifact(
        fixture,
        1,
        tmp_path / "vectors.jsonl",
        dense_values=[value * 0.99 for value in _dense_vector()],
    )
    stores = _FakeStores(fixture, qdrant_float32=True)
    result = apply_one(
        plan_dir=fixture["plan_dir"],
        vectors_path=vectors,
        backup_dir=fixture["backup_dir"],
        capacity_receipt=fixture["capacity_path"],
        capacity_estimate=fixture["estimate_path"],
        document_id=1,
        journal_dir=tmp_path / "journal",
        settings=_settings(),
        storage=stores,
        allow_storage_write=True,
    )
    assert result["status"] == "complete"


def test_point_readback_comparison_rejects_vector_drift_nan_and_metadata_drift() -> None:
    from scripts.apply_corpus_migration import _point_matches

    expected = _backup_point(_record(909, "comparison", _sha("comparison")))
    rounded = json.loads(json.dumps(expected))
    rounded["vector"]["dense"] = [
        struct.unpack("!f", struct.pack("!f", value))[0]
        for value in rounded["vector"]["dense"]
    ]
    rounded["vector"]["sparse"]["values"] = [
        struct.unpack("!f", struct.pack("!f", value))[0]
        for value in rounded["vector"]["sparse"]["values"]
    ]
    assert _point_matches(rounded, expected)

    changed_direction = json.loads(json.dumps(expected))
    changed_direction["vector"]["dense"][0] += 0.01
    assert not _point_matches(changed_direction, expected)

    nonfinite = json.loads(json.dumps(expected))
    nonfinite["vector"]["sparse"]["values"][0] = float("nan")
    assert not _point_matches(nonfinite, expected)

    changed_payload = json.loads(json.dumps(expected))
    changed_payload["payload"]["article"] = "Điều giả"
    assert not _point_matches(changed_payload, expected)


def test_rollback_can_resume_after_restore_v3_write_was_acknowledged(tmp_path) -> None:
    from scripts.apply_corpus_migration import MigrationError, apply_one, rollback_one

    fixture = _fixture(tmp_path)
    vectors = _write_vector_artifact(fixture, 1, tmp_path / "vectors.jsonl")
    stores = _FakeStores(fixture)
    kwargs = {
        "plan_dir": fixture["plan_dir"],
        "vectors_path": vectors,
        "backup_dir": fixture["backup_dir"],
        "capacity_receipt": fixture["capacity_path"],
        "capacity_estimate": fixture["estimate_path"],
        "document_id": 1,
        "journal_dir": tmp_path / "journal",
        "settings": _settings(),
        "storage": stores,
        "allow_storage_write": True,
    }
    apply_one(**kwargs)
    stores.fail_next_supabase_write = True
    with pytest.raises(MigrationError, match="rollback_failed"):
        rollback_one(**kwargs)
    assert stores.writes[-2][0] == "v3"
    journal_path = tmp_path / "journal" / "1.jsonl"
    events = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    assert events[-1]["event"] == "rollback_failed"
    # A process interruption after the acknowledged V3 restore has no failure receipt.
    journal_path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False, sort_keys=True) for event in events[:-1]) + "\n",
        encoding="utf-8",
    )
    result = rollback_one(**kwargs)
    assert result["status"] == "rollback_complete"


def test_remote_v3_scan_is_unfiltered_bounded_and_supports_old_new_union() -> None:
    from scripts.apply_corpus_migration import RemoteStores

    document_id = 909
    points = [
        {
            "id": f"point-{index}",
            "payload": {"document_id": document_id},
            "vector": {
                "dense": _dense_vector(),
                "sparse": {"indices": [index], "values": [0.5]},
            },
        }
        for index in range(32)
    ]

    class StrictQdrant:
        def __init__(self):
            self.scans = 0
            self.offsets = []
            self.retrieves = []

        def scroll(self, **kwargs):
            assert "scroll_filter" not in kwargs
            assert kwargs["limit"] == 10000
            assert kwargs["with_payload"] == ["document_id"]
            assert kwargs["with_vectors"] is False
            self.scans += 1
            self.offsets.append(kwargs.get("offset"))
            start = 0 if kwargs.get("offset") is None else 16
            page = points[start : start + 16]
            return (
                [{"id": p["id"], "payload": p["payload"]} for p in page],
                "cursor-1" if kwargs.get("offset") is None else None,
            )

        def retrieve(self, **kwargs):
            self.retrieves.append(kwargs["ids"])
            return [points[int(point_id.split("-")[1])] for point_id in kwargs["ids"]]

    remote = object.__new__(RemoteStores)
    remote._qdrant = StrictQdrant()
    remote._contract = SimpleNamespace(collection_name="v3")
    remote._v3_inventory = None
    remote._v3_point_owners = {}
    first = remote.v3_for_document(document_id)
    second = remote.v3_for_document(document_id)
    assert len(first) == len(second) == 32
    assert remote._qdrant.scans == 2
    assert remote._qdrant.offsets == [None, "cursor-1"]
    assert len(remote._qdrant.retrieves) == 2


def test_remote_v3_document_union_is_bounded_to_old_plus_new_maximum() -> None:
    from scripts.apply_corpus_migration import RemoteStores

    class StrictQdrant:
        def scroll(self, **kwargs):
            return (
                [
                    {"id": f"point-{index}", "payload": {"document_id": 909}}
                    for index in range(33)
                ],
                None,
            )

        def retrieve(self, **kwargs):
            raise AssertionError("must not retrieve an over-limit inventory")

    remote = object.__new__(RemoteStores)
    remote._qdrant = StrictQdrant()
    remote._contract = SimpleNamespace(collection_name="v3")
    remote._v3_inventory = None
    remote._v3_point_owners = {}
    with pytest.raises(ValueError, match="v3_document_point_union_limit_exceeded"):
        remote.v3_for_document(909)


def test_remote_v3_inventory_tracks_upserts_and_keeps_deleted_ids_for_readback() -> None:
    from scripts.apply_corpus_migration import RemoteStores

    document_id = 909
    old_points = {
        f"old-{index}": {
            "id": f"old-{index}",
            "payload": {"document_id": document_id},
            "vector": {"dense": _dense_vector(), "sparse": {"indices": [index], "values": [0.5]}},
        }
        for index in range(16)
    }

    class MutableQdrant:
        def __init__(self):
            self.points = dict(old_points)

        def scroll(self, **kwargs):
            assert "scroll_filter" not in kwargs
            return ([{"id": point["id"], "payload": point["payload"]} for point in self.points.values()], None)

        def retrieve(self, **kwargs):
            return [self.points[item] for item in kwargs["ids"] if item in self.points]

        def upsert(self, **kwargs):
            for point in kwargs["points"]:
                self.points[point.id] = point.model_dump(mode="json", exclude_none=True)
            return SimpleNamespace(status="completed")

        def delete(self, **kwargs):
            for point_id in kwargs["points_selector"].points:
                self.points.pop(point_id, None)
            return SimpleNamespace(status="completed")

    remote = object.__new__(RemoteStores)
    remote._qdrant = MutableQdrant()
    remote._contract = SimpleNamespace(collection_name="v3", dense_vector_name="dense", sparse_vector_name="sparse")
    remote._v3_inventory = None
    remote._v3_point_owners = {}
    assert len(remote.v3_for_document(document_id)) == 16

    new_points = []
    for index in range(16):
        point_id = str(uuid5(NAMESPACE_URL, f"migration-upsert-{index}"))
        new_points.append({
            "id": point_id,
            "payload": {"document_id": document_id},
            "vector": {"dense": _dense_vector(), "sparse": {"indices": [index], "values": [0.75]}},
        })
    remote.upsert_v3(new_points)
    assert {point["id"] for point in remote.v3_for_document(document_id)} == set(old_points) | {
        point["id"] for point in new_points
    }

    new_ids = [point["id"] for point in new_points]
    remote.delete_v3(new_ids)
    assert {point["id"] for point in remote.v3_for_document(document_id)} == set(old_points)
    assert len(remote._v3_inventory[document_id]) == 32


@pytest.mark.parametrize("corruption", ["duplicate", "foreign"])
def test_remote_v3_inventory_rejects_duplicate_or_foreign_point_ids(corruption: str) -> None:
    from scripts.apply_corpus_migration import RemoteStores

    point = {
        "id": "known-id",
        "payload": {"document_id": 909},
        "vector": {"dense": _dense_vector(), "sparse": {"indices": [1], "values": [0.5]}},
    }

    class StrictQdrant:
        def scroll(self, **kwargs):
            assert "scroll_filter" not in kwargs
            metadata = {"id": point["id"], "payload": point["payload"]}
            if corruption == "duplicate":
                return [metadata, metadata], None
            return [metadata], None

        def retrieve(self, **kwargs):
            foreign = json.loads(json.dumps(point))
            foreign["payload"]["document_id"] = 910
            return [foreign]

    remote = object.__new__(RemoteStores)
    remote._qdrant = StrictQdrant()
    remote._contract = SimpleNamespace(collection_name="v3")
    remote._v3_inventory = None
    remote._v3_point_owners = {}
    with pytest.raises(ValueError, match="v3_inventory|v3_document|v3_retrieved"):
        remote.v3_for_document(909)


def test_manual_candidate_rollback_removes_only_that_documents_additions(tmp_path) -> None:
    from scripts.apply_corpus_migration import apply_one, rollback_one

    fixture = _fixture(tmp_path)
    vectors = _write_vector_artifact(fixture, 17, tmp_path / "vectors.jsonl")
    stores = _FakeStores(fixture)
    _apply_clean_canary(fixture, stores, tmp_path / "journal")
    apply_one(
        plan_dir=fixture["plan_dir"],
        vectors_path=vectors,
        backup_dir=fixture["backup_dir"],
        capacity_receipt=fixture["capacity_path"],
        capacity_estimate=fixture["estimate_path"],
        document_id=17,
        journal_dir=tmp_path / "journal",
        settings=_settings(),
        storage=stores,
        allow_storage_write=True,
    )
    rollback_one(
        plan_dir=fixture["plan_dir"],
        vectors_path=vectors,
        backup_dir=fixture["backup_dir"],
        capacity_receipt=fixture["capacity_path"],
        capacity_estimate=fixture["estimate_path"],
        document_id=17,
        journal_dir=tmp_path / "journal",
        settings=_settings(),
        storage=stores,
        allow_storage_write=True,
    )
    assert stores.get_supabase(17) is None
    assert stores.get_body(17) is None
    assert stores.v3_for_document(17) == []
