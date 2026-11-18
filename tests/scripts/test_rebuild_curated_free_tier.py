from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from app.ingestion.content_store import StoredDocument
from app.ingestion.legal_text import DocumentMetadata


def _doc(doc_id: int, num: str, title: str, ltype: str, auth: str, idate: str, content: str) -> StoredDocument:
    return StoredDocument(
        metadata=DocumentMetadata(
            document_id=doc_id,
            document_number=num,
            title=title,
            source_url=f"https://vbpl.vn/{doc_id}",
            legal_type=ltype,
            legal_sectors="Tổng hợp",
            issuing_authority=auth,
            issuance_date=idate,
        ),
        content=content,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        content_store_key=str(doc_id),
        quality_flags=(),
    )


class _MemStore:
    def __init__(self, docs: list[StoredDocument]) -> None:
        self._docs = {d.metadata.document_id: d for d in docs}

    def iter_document_ids(self, *, after_id: int, limit: int) -> list[int]:
        return [i for i in sorted(self._docs) if i > after_id][:limit]

    def get_many(self, document_ids: list[int]) -> dict[int, StoredDocument]:
        return {i: self._docs[i] for i in document_ids if i in self._docs}


def test_plan_audit_computes_curated_stats_without_remote_writes(tmp_path: Path) -> None:
    from scripts.rebuild_curated_free_tier import build_plan_report

    store = _MemStore(
        [
            _doc(
                665872,
                "52/VBHN-VPQH",
                "Văn bản hợp nhất 52/VBHN-VPQH năm 2025 hợp nhất Hiến pháp nước Cộng hòa xã hội chủ nghĩa Việt Nam",
                "Văn bản hợp nhất",
                "Văn phòng quốc hội",
                "2025-07-21",
                "Điều 1. Nước Cộng hòa xã hội chủ nghĩa Việt Nam.",
            ),
            _doc(
                619502,
                "168/2024/NĐ-CP",
                "Nghị định 168/2024/NĐ-CP quy định xử phạt vi phạm hành chính giao thông đường bộ",
                "Nghị định",
                "Chính phủ",
                "2024-12-26",
                "Điều 1. Phạm vi điều chỉnh.\nĐiều 6. Xử phạt người điều khiển xe ô tô.",
            ),
        ]
    )
    out_path = tmp_path / "plan.json"
    report = build_plan_report(
        store,
        repository="vohuutridung/vietnamese-legal-documents",
        revision="rev-1",
        output_path=out_path,
    )

    assert report["total_documents"] == 2
    assert report["total_points"] >= 2
    assert set(report["tier_counts"]) >= {"A", "B"}
    assert out_path.is_file()
    saved = json.loads(out_path.read_text(encoding="utf-8"))
    assert saved["total_documents"] == 2


def test_vector_reuse_cache_roundtrips_1024d_vectors_and_computes_diff(tmp_path: Path) -> None:
    from scripts.rebuild_curated_free_tier import VectorReuseCache, compute_sync_id_diff

    cache = VectorReuseCache(tmp_path / "vec_cache.sqlite3", dimension=1024)
    vec = [1.0] + [0.0] * 1023
    sha = "ab" * 32
    cache.put_many([(sha, vec)])

    loaded = cache.get_many([sha, "cd" * 32])
    assert sha in loaded
    assert len(loaded[sha]) == 1024
    assert loaded[sha][0] == pytest.approx(1.0)
    assert ("cd" * 32) not in loaded
    assert cache.has_many([sha, "cd" * 32]) == {sha}

    to_delete = compute_sync_id_diff(existing_ids={"a", "b", "c"}, target_ids={"b", "d"})
    assert to_delete == ["a", "c"]


def test_reclaim_requires_confirmation_and_cleans_dead_cloud_objects(tmp_path: Path) -> None:
    from scripts.rebuild_curated_free_tier import execute_reclaim

    with pytest.raises(PermissionError, match="confirm"):
        execute_reclaim(
            confirm_cleanup=False,
            supabase_url="https://supa.example",
            supabase_service_key="sb_secret_test",
            qdrant_url="https://qdrant.example",
            qdrant_api_key="qdrant-test",
            receipt_path=tmp_path / "pre.json",
        )

    supa_calls: list[tuple[str, str]] = []
    qdrant_calls: list[tuple[str, str]] = []

    def supa_handler(request: httpx.Request) -> httpx.Response:
        supa_calls.append((request.method, str(request.url)))
        path = request.url.path
        if request.method == "HEAD":
            counts = {
                "/rest/v1/legal_body_active": "0-0/0",
                "/rest/v1/legal_body_passages": "0-0/12",
                "/rest/v1/legal_body_runs": "0-0/1",
                "/rest/v1/legal_documents": "0-0/10",
            }
            return httpx.Response(200, headers={"content-range": counts[path]})
        if request.method == "GET" and path == "/rest/v1/legal_body_passages":
            return httpx.Response(200, json=[{"document_id": 9500}])
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json=[])

    def qdrant_handler(request: httpx.Request) -> httpx.Response:
        qdrant_calls.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path == "/collections":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "collections": [
                            {"name": "vietlex-embedding-staging"},
                            {"name": "vietlex-legal-rag-v2-pilot-384"},
                            {"name": "vietlex-rerank-staging"},
                            {"name": "vietlex-legal-rag-v3-vertex-1024"},
                        ]
                    }
                },
            )
        if request.method == "GET" and request.url.path.endswith("/memory"):
            return httpx.Response(200, json={"result": {"total": {"disk_bytes": 1000, "ram_bytes": 100}}})
        if request.method == "GET":
            return httpx.Response(200, json={"result": {"status": "green", "points_count": 5}})
        if request.method in {"DELETE", "PUT"}:
            return httpx.Response(200, json={"result": True, "status": "ok"})
        return httpx.Response(200, json={"result": {}})

    receipt_path = tmp_path / "pre_reclaim.json"
    reclaim_receipt_path = tmp_path / "reclaim_receipt.json"
    result = execute_reclaim(
        confirm_cleanup=True,
        supabase_url="https://supa.example",
        supabase_service_key="sb_secret_test",
        qdrant_url="https://qdrant.example",
        qdrant_api_key="qdrant-test",
        receipt_path=receipt_path,
        reclaim_receipt_path=reclaim_receipt_path,
        supabase_client=httpx.Client(transport=httpx.MockTransport(supa_handler)),
        qdrant_client=httpx.Client(transport=httpx.MockTransport(qdrant_handler)),
    )

    assert receipt_path.is_file()
    assert reclaim_receipt_path.is_file()
    for path_item in (receipt_path, reclaim_receipt_path):
        receipt_text = path_item.read_text(encoding="utf-8")
        assert "sb_secret_test" not in receipt_text
        assert "qdrant-test" not in receipt_text
    assert result["postgrest_observability"]["supabase_db_size_bytes"] == "unobservable_via_postgrest"
    # Protected staging collection must never be deleted
    assert ("DELETE", "/collections/vietlex-embedding-staging") not in qdrant_calls
    assert ("DELETE", "/collections/vietlex-legal-rag-v2-pilot-384") in qdrant_calls
    assert ("DELETE", "/collections/vietlex-rerank-staging") in qdrant_calls
    assert ("PUT", "/collections/vietlex-rerank-staging") in qdrant_calls
    assert any(m == "DELETE" and "legal_body_passages" in u for m, u in supa_calls)
    assert any(m == "DELETE" and "legal_body_runs" in u and "building" in u for m, u in supa_calls)
    assert result["status"] == "reclaimed"


def test_default_library_calls_never_touch_repo_receipts_and_scroll_flag_tracks_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import inspect
    from scripts import rebuild_curated_free_tier as rcf

    assert inspect.signature(rcf.execute_reclaim).parameters["reclaim_receipt_path"].default is None
    assert inspect.signature(rcf.execute_reclaim).parameters["receipt_path"].default is None
    assert inspect.signature(rcf.build_plan_report).parameters["output_path"].default is None

    cache = rcf.VectorReuseCache(tmp_path / "partial_cache.sqlite3", dimension=4)
    cache.put_many([(f"{i:064x}", [1.0, 0.0, 0.0, 0.0]) for i in range(10)])
    assert cache.is_scroll_complete() is False

    seen_with_vector: list[bool] = []

    def qdrant_scroll_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen_with_vector.append(bool(body.get("with_vector")))
        return httpx.Response(
            200,
            json={
                "result": {
                    "points": [
                        {
                            "id": "pt-1",
                            "payload": {"inference_text_sha256": "f" * 64, "validity_hint": "active_candidate", "issuance_year": 2025, "normative_rank": 4},
                            "vector": {"dense": [0.0, 1.0, 0.0, 0.0]} if body.get("with_vector") else None,
                        }
                    ],
                    "next_page_offset": None,
                }
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(qdrant_scroll_handler))
    rcf._scroll_existing_v3_into_cache(
        client,
        qdrant_root="https://qdrant.example",
        qdrant_headers={"api-key": "k"},
        collection_name="vietlex-legal-rag-v3-vertex-1024",
        cache=cache,
    )
    assert seen_with_vector == [True]
    assert cache.is_scroll_complete() is True
    assert ("f" * 64) in cache.get_many(["f" * 64])

    seen_with_vector.clear()
    rcf._scroll_existing_v3_into_cache(
        client,
        qdrant_root="https://qdrant.example",
        qdrant_headers={"api-key": "k"},
        collection_name="vietlex-legal-rag-v3-vertex-1024",
        cache=cache,
    )
    assert seen_with_vector == [False]


def test_supabase_adaptive_upsert_and_delete_split_on_statement_timeout() -> None:
    from app.ingestion.supabase_full_doc import SupabaseUploadError, SupabaseUpsertReport
    from scripts.rebuild_curated_free_tier import (
        _delete_supabase_ids_adaptive,
        _upsert_supabase_rows_adaptive,
    )

    seen_batch_sizes: list[int] = []

    class _FakeUploader:
        def upsert_rows(self, rows: list[dict]) -> SupabaseUpsertReport:
            seen_batch_sizes.append(len(rows))
            if len(rows) > 2:
                raise SupabaseUploadError(
                    'Supabase upsert failed status=500: {"code":"57014","message":"canceling statement due to statement timeout"}'
                )
            return SupabaseUpsertReport(uploaded_rows=len(rows))

    rows = [{"document_id": idx, "content": f"Điều {idx}"} for idx in range(1, 9)]
    uploaded = _upsert_supabase_rows_adaptive(_FakeUploader(), rows, max_bytes=1_000_000, sleep_fn=lambda _: None)
    assert uploaded == 8
    assert seen_batch_sizes[0] == 8
    assert all(size <= 2 for size in seen_batch_sizes if size <= 2)

    del_batches: list[list[str]] = []

    def del_handler(request: httpx.Request) -> httpx.Response:
        raw = request.url.params.get("document_id", "")
        ids = raw[3:-1].split(",") if raw.startswith("in.(") and raw.endswith(")") else []
        del_batches.append(ids)
        if len(ids) > 2:
            return httpx.Response(500, json={"code": "57014", "message": "statement timeout"})
        return httpx.Response(204)

    client = httpx.Client(transport=httpx.MockTransport(del_handler))
    deleted = _delete_supabase_ids_adaptive(
        client,
        supa_root="https://supa.example",
        supa_headers={"apikey": "sb_secret_x", "authorization": "Bearer sb_secret_x"},
        document_ids=[10, 20, 30, 40, 50],
        sleep_fn=lambda _: None,
    )
    assert deleted == 5
    assert sum(len(b) for b in del_batches if len(b) <= 2) == 5

