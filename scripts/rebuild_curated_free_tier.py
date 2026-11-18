"""Checkpointed Free-Tier cloud reclamation and curated modern normative re-indexer.

Subcommands:
  plan    - Provider-free local byte, chunk, and 1:1:1 eligibility audit.
  reclaim - Clean dead Supabase passages/runs and dormant/bloated Qdrant staging collections.
  sync    - Reuse existing V3 1024d vectors, batch-embed missing chunks on Vertex AI,
            and synchronize Qdrant V3, Supabase legal_documents, and Qdrant Body Search to 1:1:1 parity.
  verify  - Cryptographic 1:1:1 ID & SHA-256 parity, QdrantFullDocBodySearch.coverage(),
            disk/RAM quotas, and live statute article-count verification.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import struct
import sys
import time
from typing import Any, Iterable, Sequence

import httpx
from qdrant_client import models

# Allow running directly as `python scripts/rebuild_curated_free_tier.py ...`
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.config import Settings, get_settings, system_ssl_context  # noqa: E402
from app.ingestion.content_store import ContentStore  # noqa: E402
from app.ingestion.curated_normative_corpus import (  # noqa: E402
    CURATED_V3_POINT_BUDGET,
    build_structural_records_from_prepared,
    select_and_chunk_curated_corpus,
)
from app.ingestion.pinecone_store import FastSparseEncoder  # noqa: E402
from app.ingestion.structural_qdrant import (  # noqa: E402
    build_structural_inference_text,
    structural_inference_text_sha256,
)
from app.ingestion.supabase_full_doc import (  # noqa: E402
    SupabaseFullDocUploader,
    build_supabase_row,
)
from app.ingestion.vertex_qdrant_migration import (  # noqa: E402
    MigrationCheckpoint,
    VertexQdrantContract,
    build_vertex_point,
)
from app.services.legal_browser import SupabaseLegalStore  # noqa: E402
from app.services.qdrant_full_doc_body_search import QdrantFullDocBodySearch  # noqa: E402
from app.services.vertex_ai import VertexAIProvider  # noqa: E402
from scripts.build_qdrant_full_doc_index import (  # noqa: E402
    COLLECTION as BODY_SEARCH_COLLECTION,
    INDEXES as BODY_SEARCH_INDEXES,
    point_from_source,
)


PROTECTED_NEVER_TOUCH_QDRANT = frozenset({"vietlex-embedding-staging"})
DORMANT_PILOT_COLLECTION = "vietlex-legal-rag-v2-pilot-384"
RERANK_STAGING_COLLECTION = "vietlex-rerank-staging"

DEFAULT_PLAN_PATH = Path("data/ingestion/curated_v4_plan.json")
DEFAULT_PRE_RECLAIM_RECEIPT = Path("data/ingestion/curated_v4_pre_reclaim_receipt.json")
DEFAULT_RECLAIM_RECEIPT = Path("data/ingestion/curated_v4_reclaim_receipt.json")
DEFAULT_VECTOR_CACHE_PATH = Path("data/ingestion/curated_v4_vector_cache.sqlite3")
DEFAULT_V3_CHECKPOINT_PATH = Path("data/ingestion/curated_v4_checkpoint.sqlite3")
DEFAULT_SYNC_RECEIPT = Path("data/ingestion/curated_v4_sync_receipt.json")
DEFAULT_VERIFY_RECEIPT = Path("data/ingestion/curated_v4_verify_receipt.json")

V3_PAYLOAD_INDEXES: dict[str, dict[str, Any]] = {
    "document_id": {"type": "integer", "on_disk": True},
    "issuance_year": {"type": "integer", "on_disk": True},
    "legal_type": {"type": "keyword", "on_disk": True},
    "validity_hint": {"type": "keyword", "on_disk": True},
}

KEY_VERIFICATION_DOCUMENTS: tuple[tuple[int, str, int | None], ...] = (
    (296215, "91/2015/QH13 (BLDS 2015)", 689),
    (333670, "45/2019/QH14 (BLLĐ 2019)", 220),
    (296661, "100/2015/QH13 (BLHS 2015)", 425),
    (523642, "31/2024/QH15 (Luật Đất đai 2024)", 260),
    (557190, "41/2024/QH15 (Luật BHXH 2024)", 141),
    (619502, "168/2024/NĐ-CP", 50),  # >= 50 articles (exact 55)
    (665866, "293/2025/NĐ-CP", 1),
    (665872, "52/VBHN-VPQH (Hiến pháp hợp nhất 2025)", 1),
    (655275, "203/2025/QH15", 1),
    (665865, "110/2025/UBTVQH15", 1),
    (675268, "108/2025/QH15 (Luật Quản lý thuế 2025)", 1),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def resolve_content_store_path(settings: Settings) -> Path:
    clean_path = getattr(settings, "CLEAN_CONTENT_STORE_PATH", None)
    if clean_path is not None and Path(clean_path).is_file():
        return Path(clean_path)
    return Path(settings.CONTENT_STORE_PATH)


def compute_sync_id_diff(
    *,
    existing_ids: Iterable[Any],
    target_ids: Iterable[Any],
) -> list[Any]:
    return sorted(set(existing_ids) - set(target_ids))


class VectorReuseCache:
    """Compact binary float32 SQLite cache keyed by inference_text_sha256."""

    def __init__(self, path: Path, *, dimension: int = 1024) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.path = Path(path)
        self.dimension = dimension
        self._pack_fmt = f"<{dimension}f"
        self._expected_bytes = dimension * 4
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS vector_cache ("
                "inference_text_sha256 TEXT PRIMARY KEY, "
                "dense_f32 BLOB NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS cache_meta ("
                "key TEXT PRIMARY KEY, "
                "value TEXT NOT NULL)"
            )

    def is_scroll_complete(self) -> bool:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT value FROM cache_meta WHERE key = 'v3_remote_scroll_complete'"
            ).fetchone()
        return bool(row and row[0] == "true")

    def mark_scroll_complete(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache_meta(key, value) "
                "VALUES ('v3_remote_scroll_complete', 'true')"
            )

    def count(self) -> int:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM vector_cache").fetchone()
        return int(row[0]) if row else 0

    def put_many(self, items: Sequence[tuple[str, Sequence[float]]]) -> int:
        if not items:
            return 0
        rows: list[tuple[str, bytes]] = []
        for sha, values in items:
            if len(values) != self.dimension:
                raise ValueError("vector dimension mismatch for cache")
            blob = struct.pack(self._pack_fmt, *(float(v) for v in values))
            rows.append((str(sha), blob))
        with sqlite3.connect(self.path) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO vector_cache(inference_text_sha256, dense_f32) "
                "VALUES (?, ?)",
                rows,
            )
        return len(rows)

    def has_many(self, hashes: Sequence[str]) -> set[str]:
        unique = list(dict.fromkeys(str(h) for h in hashes if h))
        if not unique:
            return set()
        found: set[str] = set()
        with sqlite3.connect(self.path) as conn:
            for offset in range(0, len(unique), 800):
                batch = unique[offset : offset + 800]
                placeholders = ",".join("?" for _ in batch)
                rows = conn.execute(
                    "SELECT inference_text_sha256 FROM vector_cache "
                    f"WHERE length(dense_f32) = ? AND inference_text_sha256 IN ({placeholders})",
                    [self._expected_bytes, *batch],
                ).fetchall()
                for (sha,) in rows:
                    found.add(str(sha))
        return found

    def get_many(self, hashes: Sequence[str]) -> dict[str, list[float]]:
        unique = list(dict.fromkeys(str(h) for h in hashes if h))
        if not unique:
            return {}
        found: dict[str, list[float]] = {}
        with sqlite3.connect(self.path) as conn:
            for offset in range(0, len(unique), 800):
                batch = unique[offset : offset + 800]
                placeholders = ",".join("?" for _ in batch)
                rows = conn.execute(
                    "SELECT inference_text_sha256, dense_f32 FROM vector_cache "
                    f"WHERE inference_text_sha256 IN ({placeholders})",
                    batch,
                ).fetchall()
                for sha, blob in rows:
                    if isinstance(blob, (bytes, memoryview)) and len(blob) == self._expected_bytes:
                        found[str(sha)] = list(struct.unpack(self._pack_fmt, blob))
        return found


def _request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    max_attempts: int = 4,
    **kwargs: Any,
) -> httpx.Response:
    for attempt in range(max_attempts):
        try:
            response = client.request(method, url, **kwargs)
            if response.status_code not in {429, 500, 502, 503, 504}:
                response.raise_for_status()
                return response
        except httpx.TransportError:
            if attempt + 1 == max_attempts:
                raise
        if attempt + 1 == max_attempts:
            response.raise_for_status()
        time.sleep(1.5 * (2**attempt))
    raise AssertionError("unreachable")


def _upsert_supabase_rows_adaptive(
    uploader: Any,
    rows: list[dict[str, Any]],
    *,
    max_bytes: int = 750_000,
    max_single_attempts: int = 4,
    sleep_fn: Any = time.sleep,
) -> int:
    if not rows:
        return 0
    total_bytes = sum(len(str(r.get("content") or "").encode("utf-8")) for r in rows)
    if len(rows) > 1 and total_bytes > max_bytes:
        mid = len(rows) // 2
        return _upsert_supabase_rows_adaptive(
            uploader,
            rows[:mid],
            max_bytes=max_bytes,
            max_single_attempts=max_single_attempts,
            sleep_fn=sleep_fn,
        ) + _upsert_supabase_rows_adaptive(
            uploader,
            rows[mid:],
            max_bytes=max_bytes,
            max_single_attempts=max_single_attempts,
            sleep_fn=sleep_fn,
        )

    attempts = max_single_attempts if len(rows) == 1 else 1
    for attempt in range(attempts):
        try:
            report = uploader.upsert_rows(rows)
            return int(report.uploaded_rows)
        except Exception:
            if len(rows) > 1:
                mid = len(rows) // 2
                return _upsert_supabase_rows_adaptive(
                    uploader,
                    rows[:mid],
                    max_bytes=max_bytes,
                    max_single_attempts=max_single_attempts,
                    sleep_fn=sleep_fn,
                ) + _upsert_supabase_rows_adaptive(
                    uploader,
                    rows[mid:],
                    max_bytes=max_bytes,
                    max_single_attempts=max_single_attempts,
                    sleep_fn=sleep_fn,
                )
            if attempt + 1 == attempts:
                raise
            sleep_fn(1.5 * (2**attempt))
    raise AssertionError("unreachable")


def _delete_supabase_ids_adaptive(
    client: httpx.Client,
    *,
    supa_root: str,
    supa_headers: dict[str, str],
    document_ids: Sequence[int | str],
    max_single_attempts: int = 4,
    sleep_fn: Any = time.sleep,
) -> int:
    ids = list(document_ids)
    if not ids:
        return 0
    attempts = max_single_attempts if len(ids) == 1 else 1
    csv_ids = ",".join(str(i) for i in ids)
    for attempt in range(attempts):
        try:
            resp = client.delete(
                f"{supa_root}/rest/v1/legal_documents",
                headers=supa_headers,
                params={"document_id": f"in.({csv_ids})"},
            )
            if resp.status_code not in {429, 500, 502, 503, 504}:
                resp.raise_for_status()
                return len(ids)
            if len(ids) == 1 and attempt + 1 == attempts:
                resp.raise_for_status()
        except httpx.TransportError:
            if len(ids) == 1 and attempt + 1 == attempts:
                raise
        if len(ids) > 1:
            mid = len(ids) // 2
            return _delete_supabase_ids_adaptive(
                client,
                supa_root=supa_root,
                supa_headers=supa_headers,
                document_ids=ids[:mid],
                max_single_attempts=max_single_attempts,
                sleep_fn=sleep_fn,
            ) + _delete_supabase_ids_adaptive(
                client,
                supa_root=supa_root,
                supa_headers=supa_headers,
                document_ids=ids[mid:],
                max_single_attempts=max_single_attempts,
                sleep_fn=sleep_fn,
            )
        sleep_fn(1.5 * (2**attempt))
    raise AssertionError("unreachable")


def _supabase_exact_count(
    client: httpx.Client,
    supa_root: str,
    headers: dict[str, str],
    table: str,
) -> int:
    resp = _request_with_retry(
        client,
        "HEAD",
        f"{supa_root}/rest/v1/{table}",
        headers={**headers, "Prefer": "count=exact"},
        params={"select": "*", "limit": "0"},
    )
    raw = resp.headers.get("content-range", "").split("/")[-1]
    if not raw.isdecimal():
        raise ValueError(f"invalid_supabase_count:{table}:{raw}")
    return int(raw)


def _snapshot_cloud_state(
    *,
    supa_client: httpx.Client,
    supa_root: str,
    supa_headers: dict[str, str],
    qdrant_client: httpx.Client,
    qdrant_root: str,
    qdrant_headers: dict[str, str],
) -> dict[str, Any]:
    qdrant_collections: dict[str, Any] = {}
    cols_resp = _request_with_retry(
        qdrant_client,
        "GET",
        f"{qdrant_root}/collections",
        headers=qdrant_headers,
    ).json()
    total_disk = 0
    total_ram = 0
    for item in cols_resp.get("result", {}).get("collections", []):
        name = str(item["name"])
        info = (
            _request_with_retry(
                qdrant_client,
                "GET",
                f"{qdrant_root}/collections/{name}",
                headers=qdrant_headers,
            )
            .json()
            .get("result", {})
        )
        disk_b = 0
        ram_b = 0
        try:
            mem = (
                _request_with_retry(
                    qdrant_client,
                    "GET",
                    f"{qdrant_root}/collections/{name}/memory",
                    headers=qdrant_headers,
                )
                .json()
                .get("result", {})
                .get("total", {})
            )
            disk_b = int(mem.get("disk_bytes", 0))
            ram_b = int(mem.get("ram_bytes", 0))
        except Exception:
            pass
        total_disk += disk_b
        total_ram += ram_b
        qdrant_collections[name] = {
            "status": info.get("status"),
            "points_count": info.get("points_count"),
            "disk_bytes": disk_b,
            "ram_bytes": ram_b,
            "payload_schema_keys": sorted((info.get("payload_schema") or {}).keys()),
        }

    supabase_tables = {
        tbl: _supabase_exact_count(supa_client, supa_root, supa_headers, tbl)
        for tbl in (
            "legal_documents",
            "legal_body_passages",
            "legal_body_runs",
            "legal_body_active",
        )
    }
    return {
        "captured_at": _utc_now(),
        "qdrant_collections": qdrant_collections,
        "qdrant_total_disk_bytes": total_disk,
        "qdrant_total_ram_bytes": total_ram,
        "supabase_table_counts": supabase_tables,
    }


def build_plan_report(
    store: Any,
    *,
    repository: str,
    revision: str,
    output_path: Path | None = None,
    max_total_points: int = CURATED_V3_POINT_BUDGET,
) -> dict[str, Any]:
    started = time.perf_counter()
    plan, _ = select_and_chunk_curated_corpus(
        store,
        max_total_points=max_total_points,
    )
    by_id = {entry.document_id: entry for entry in plan.entries}
    key_checks: dict[str, Any] = {}
    for doc_id, label, min_articles in KEY_VERIFICATION_DOCUMENTS:
        entry = by_id.get(doc_id)
        key_checks[str(doc_id)] = {
            "label": label,
            "present": entry is not None,
            "distinct_articles": entry.distinct_article_count if entry else 0,
            "chunk_count": entry.chunk_count if entry else 0,
            "tier": entry.tier if entry else None,
            "validity_hint": entry.validity_hint if entry else None,
            "min_expected_articles": min_articles,
        }

    est_v3_disk = int(plan.total_points * 7_850)
    est_body_disk = int(plan.total_utf8_bytes * 0.95)
    est_supa_bytes = int(plan.total_utf8_bytes * 0.48)
    superseded_count = sum(
        1 for entry in plan.entries if entry.validity_hint == "superseded"
    )

    report: dict[str, Any] = {
        "schema": "vietlex-curated-v4-plan-v1",
        "generated_at": _utc_now(),
        "repository": repository,
        "dataset_revision": revision,
        "selection_sha256": plan.selection_sha256,
        "total_documents": plan.total_documents,
        "total_points": plan.total_points,
        "total_utf8_bytes": plan.total_utf8_bytes,
        "total_utf8_mb": round(plan.total_utf8_bytes / 1_000_000, 2),
        "superseded_tagged_documents": superseded_count,
        "tier_counts": plan.tier_counts,
        "tier_points": plan.tier_points,
        "skipped_counts": plan.skipped_counts,
        "english_387595_excluded": 387595 not in by_id,
        "estimates": {
            "qdrant_v3_disk_bytes": est_v3_disk,
            "qdrant_v3_disk_gib": round(est_v3_disk / (1024**3), 3),
            "qdrant_body_search_disk_bytes": est_body_disk,
            "supabase_estimated_bytes": est_supa_bytes,
            "supabase_estimated_mb": round(est_supa_bytes / 1_000_000, 2),
        },
        "key_documents": key_checks,
        "wall_seconds": round(time.perf_counter() - started, 2),
    }
    if output_path is not None:
        _write_json_atomic(output_path, report)
    return report


POSTGREST_OBSERVABILITY_NOTE: dict[str, str] = {
    "supabase_db_size_bytes": "unobservable_via_postgrest",
    "gin_indexes_dropped": "requires_sql_admin_connection",
}


def execute_reclaim(
    *,
    confirm_cleanup: bool,
    supabase_url: str,
    supabase_service_key: str,
    qdrant_url: str,
    qdrant_api_key: str,
    receipt_path: Path | None = None,
    reclaim_receipt_path: Path | None = None,
    supabase_client: httpx.Client | None = None,
    qdrant_client: httpx.Client | None = None,
    settings: Any | None = None,
) -> dict[str, Any]:
    if not confirm_cleanup:
        raise PermissionError(
            "Pass --confirm-free-tier-cleanup to authorize cloud storage reclamation."
        )
    if not supabase_url or not supabase_service_key.startswith("sb_secret_"):
        raise ValueError("Valid SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
    if not qdrant_url or not qdrant_api_key:
        raise ValueError("Valid QDRANT_URL and QDRANT_API_KEY are required")

    cfg = settings or get_settings()
    supa_root = supabase_url.rstrip("/")
    qdrant_root = qdrant_url.rstrip("/")
    supa_headers = {
        "apikey": supabase_service_key,
        "authorization": f"Bearer {supabase_service_key}",
    }
    qdrant_headers = {"api-key": qdrant_api_key}

    own_supa = supabase_client is None
    own_qdrant = qdrant_client is None
    s_client = supabase_client or httpx.Client(
        verify=system_ssl_context(),
        timeout=httpx.Timeout(60.0),
    )
    q_client = qdrant_client or httpx.Client(
        verify=system_ssl_context(),
        timeout=httpx.Timeout(60.0),
    )

    try:
        pre_state = _snapshot_cloud_state(
            supa_client=s_client,
            supa_root=supa_root,
            supa_headers=supa_headers,
            qdrant_client=q_client,
            qdrant_root=qdrant_root,
            qdrant_headers=qdrant_headers,
        )
        if receipt_path is not None:
            _write_json_atomic(receipt_path, pre_state)

        active_rows = pre_state["supabase_table_counts"]["legal_body_active"]
        if active_rows != 0:
            raise RuntimeError(
                f"Refusing to delete legal_body_passages: legal_body_active has {active_rows} rows"
            )

        # Determine max document_id in legal_body_passages
        max_id_resp = _request_with_retry(
            s_client,
            "GET",
            f"{supa_root}/rest/v1/legal_body_passages",
            headers=supa_headers,
            params={
                "select": "document_id",
                "order": "document_id.desc",
                "limit": "1",
            },
        ).json()
        max_passage_doc_id = 750_000
        if isinstance(max_id_resp, list) and max_id_resp:
            observed_max = int(max_id_resp[0].get("document_id") or 0)
            max_passage_doc_id = max(max_passage_doc_id, observed_max + 1000)

        windows_deleted = 0
        if pre_state["supabase_table_counts"]["legal_body_passages"] > 0:
            for lo in range(0, max_passage_doc_id + 1, 5000):
                hi = lo + 4999
                _request_with_retry(
                    s_client,
                    "DELETE",
                    f"{supa_root}/rest/v1/legal_body_passages",
                    headers=supa_headers,
                    params=[
                        ("document_id", f"gte.{lo}"),
                        ("document_id", f"lte.{hi}"),
                    ],
                )
                windows_deleted += 1

        _request_with_retry(
            s_client,
            "DELETE",
            f"{supa_root}/rest/v1/legal_body_runs",
            headers=supa_headers,
            params={"state": "eq.building"},
        )

        existing_qdrant = set(pre_state["qdrant_collections"])
        dropped_collections: list[str] = []
        for target_col in (DORMANT_PILOT_COLLECTION, RERANK_STAGING_COLLECTION):
            if target_col in PROTECTED_NEVER_TOUCH_QDRANT:
                raise AssertionError("protected staging collection cannot be touched")
            if target_col in existing_qdrant:
                _request_with_retry(
                    q_client,
                    "DELETE",
                    f"{qdrant_root}/collections/{target_col}",
                    headers=qdrant_headers,
                )
                dropped_collections.append(target_col)

        # Recreate vietlex-rerank-staging clean with exact RemoteReranker schema
        rerank_vec_name = getattr(cfg, "QDRANT_RERANK_VECTOR_NAME", "colbert")
        rerank_vec_size = int(getattr(cfg, "QDRANT_RERANK_VECTOR_SIZE", 96))
        create_rerank_spec = models.CreateCollection(
            vectors={
                rerank_vec_name: models.VectorParams(
                    size=rerank_vec_size,
                    distance=models.Distance.COSINE,
                    hnsw_config=models.HnswConfigDiff(m=0),
                    on_disk=True,
                    multivector_config=models.MultiVectorConfig(
                        comparator=models.MultiVectorComparator.MAX_SIM
                    ),
                )
            },
            optimizers_config=models.OptimizersConfigDiff(indexing_threshold=0),
            on_disk_payload=True,
        ).model_dump(mode="json", exclude_none=True)

        _request_with_retry(
            q_client,
            "PUT",
            f"{qdrant_root}/collections/{RERANK_STAGING_COLLECTION}",
            headers=qdrant_headers,
            json=create_rerank_spec,
        )
        for field_name, field_schema in (
            ("request_id", "keyword"),
            ("created_at", "integer"),
        ):
            _request_with_retry(
                q_client,
                "PUT",
                f"{qdrant_root}/collections/{RERANK_STAGING_COLLECTION}/index?wait=true",
                headers=qdrant_headers,
                json={"field_name": field_name, "field_schema": field_schema},
            )

        post_state = _snapshot_cloud_state(
            supa_client=s_client,
            supa_root=supa_root,
            supa_headers=supa_headers,
            qdrant_client=q_client,
            qdrant_root=qdrant_root,
            qdrant_headers=qdrant_headers,
        )
        summary = {
            "status": "reclaimed",
            "completed_at": _utc_now(),
            "passage_delete_windows": windows_deleted,
            "dropped_qdrant_collections": dropped_collections,
            "recreated_qdrant_collections": [RERANK_STAGING_COLLECTION],
            "pre_reclaim_receipt": str(receipt_path) if receipt_path is not None else None,
            "postgrest_observability": dict(POSTGREST_OBSERVABILITY_NOTE),
            "pre_state": pre_state,
            "post_state": post_state,
        }
        if reclaim_receipt_path is not None:
            _write_json_atomic(reclaim_receipt_path, summary)
        return summary
    finally:
        if own_supa:
            s_client.close()
        if own_qdrant:
            q_client.close()


def _scroll_existing_v3_into_cache(
    qdrant_client: httpx.Client,
    *,
    qdrant_root: str,
    qdrant_headers: dict[str, str],
    collection_name: str,
    cache: VectorReuseCache,
) -> tuple[set[str], dict[str, tuple[str, str | None, int | None, int | None]], int]:
    """Scroll remote V3 points, caching dense vectors by inference_text_sha256."""
    existing_ids: set[str] = set()
    remote_meta_by_id: dict[str, tuple[str, str | None, int | None, int | None]] = {}
    cached_count = 0
    offset: Any = None
    buffer: list[tuple[str, Sequence[float]]] = []
    # Scroll dense vectors until one full remote V3 scroll has completed and been recorded
    need_vectors = not cache.is_scroll_complete()
    page_limit = 256 if need_vectors else 1000

    while True:
        req: dict[str, Any] = {
            "limit": page_limit,
            "with_payload": [
                "inference_text_sha256",
                "validity_hint",
                "issuance_year",
                "normative_rank",
            ],
            "with_vector": need_vectors,
        }
        if offset is not None:
            req["offset"] = offset
        resp = _request_with_retry(
            qdrant_client,
            "POST",
            f"{qdrant_root}/collections/{collection_name}/points/scroll",
            headers=qdrant_headers,
            json=req,
        ).json()
        result = resp.get("result", {})
        points = result.get("points", [])
        for pt in points:
            pt_id = str(pt["id"])
            existing_ids.add(pt_id)
            payload = pt.get("payload") or {}
            inf_sha = payload.get("inference_text_sha256")
            if isinstance(inf_sha, str) and len(inf_sha) == 64:
                remote_meta_by_id[pt_id] = (
                    inf_sha,
                    payload.get("validity_hint"),
                    payload.get("issuance_year"),
                    payload.get("normative_rank"),
                )
                if need_vectors:
                    vec_obj = pt.get("vector")
                    dense = vec_obj.get("dense") if isinstance(vec_obj, dict) else vec_obj
                    if isinstance(dense, list) and len(dense) == cache.dimension:
                        buffer.append((inf_sha, dense))
            if len(buffer) >= 1024:
                cached_count += cache.put_many(buffer)
                buffer.clear()
        offset = result.get("next_page_offset")
        if offset is None:
            break

    if buffer:
        cached_count += cache.put_many(buffer)
    if need_vectors:
        cache.mark_scroll_complete()
    return existing_ids, remote_meta_by_id, cached_count


def _ensure_qdrant_indexes(
    qdrant_client: httpx.Client,
    *,
    qdrant_root: str,
    qdrant_headers: dict[str, str],
    collection_name: str,
    indexes: dict[str, dict[str, Any]],
) -> None:
    info = (
        _request_with_retry(
            qdrant_client,
            "GET",
            f"{qdrant_root}/collections/{collection_name}",
            headers=qdrant_headers,
        )
        .json()
        .get("result", {})
    )
    existing_schema = info.get("payload_schema") or {}
    for field_name, schema in indexes.items():
        if field_name not in existing_schema:
            _request_with_retry(
                qdrant_client,
                "PUT",
                f"{qdrant_root}/collections/{collection_name}/index?wait=true",
                headers=qdrant_headers,
                json={"field_name": field_name, "field_schema": schema},
            )


def _scroll_supabase_hashes(
    supa_client: httpx.Client,
    *,
    supa_root: str,
    supa_headers: dict[str, str],
) -> dict[int, str]:
    hashes: dict[int, str] = {}
    after_id = 0
    while True:
        rows = _request_with_retry(
            supa_client,
            "GET",
            f"{supa_root}/rest/v1/legal_documents",
            headers=supa_headers,
            params={
                "select": "document_id,content_sha256",
                "document_id": f"gt.{after_id}",
                "order": "document_id.asc",
                "limit": "1000",
            },
        ).json()
        if not rows:
            break
        for row in rows:
            doc_id = int(row["document_id"])
            hashes[doc_id] = str(row["content_sha256"])
        after_id = int(rows[-1]["document_id"])
    return hashes


def _scroll_body_search_hashes(
    qdrant_client: httpx.Client,
    *,
    qdrant_root: str,
    qdrant_headers: dict[str, str],
    collection_name: str,
) -> dict[int, str]:
    hashes: dict[int, str] = {}
    offset: Any = None
    while True:
        req: dict[str, Any] = {
            "limit": 500,
            "with_payload": ["document_id", "content_sha256"],
            "with_vector": False,
        }
        if offset is not None:
            req["offset"] = offset
        result = (
            _request_with_retry(
                qdrant_client,
                "POST",
                f"{qdrant_root}/collections/{collection_name}/points/scroll",
                headers=qdrant_headers,
                json=req,
            )
            .json()
            .get("result", {})
        )
        for pt in result.get("points", []):
            doc_id = int(pt["id"])
            payload = pt.get("payload") or {}
            hashes[doc_id] = str(payload.get("content_sha256") or "")
        offset = result.get("next_page_offset")
        if offset is None:
            break
    return hashes


async def _batch_embed_missing_vectors(
    missing_items: list[tuple[str, str, str]],
    *,
    provider: VertexAIProvider,
    cache: VectorReuseCache,
    vector_size: int,
    batch_size: int = 64,
    concurrency: int = 6,
) -> int:
    if not missing_items:
        return 0
    sub_batches: list[list[tuple[str, str, str]]] = []
    cur: list[tuple[str, str, str]] = []
    cur_words = 0
    for sha, inf_text, title in missing_items:
        words = len(inf_text.split())
        if cur and (len(cur) >= batch_size or cur_words + words > 12_000):
            sub_batches.append(cur)
            cur = []
            cur_words = 0
        cur.append((sha, inf_text, title))
        cur_words += words
    if cur:
        sub_batches.append(cur)

    semaphore = asyncio.Semaphore(concurrency)
    cache_lock = asyncio.Lock()
    embedded_total = 0
    started = time.perf_counter()

    async def worker(batch: list[tuple[str, str, str]]) -> None:
        nonlocal embedded_total
        async with semaphore:
            results = await provider.embed_documents_batch(
                [(text, title) for _, text, title in batch],
                output_dimensionality=vector_size,
            )
        to_store = [
            (sha, res.values)
            for (sha, _, _), res in zip(batch, results, strict=True)
        ]
        async with cache_lock:
            cache.put_many(to_store)
            embedded_total += len(to_store)
            if embedded_total % 4096 < len(to_store) or embedded_total == len(missing_items):
                elapsed = max(0.001, time.perf_counter() - started)
                print(
                    json.dumps(
                        {
                            "stage": "vertex_batch_embed",
                            "embedded": embedded_total,
                            "total_missing": len(missing_items),
                            "chunks_per_sec": round(embedded_total / elapsed, 1),
                        }
                    ),
                    flush=True,
                )

    await asyncio.gather(*(worker(b) for b in sub_batches))
    return embedded_total


async def _upsert_v3_points_async(
    pending_records: list[tuple[Any, dict[str, object], str]],
    *,
    cache: VectorReuseCache,
    sparse_encoder: FastSparseEncoder,
    contract: VertexQdrantContract,
    checkpoint: MigrationCheckpoint | None,
    qdrant_root: str,
    qdrant_headers: dict[str, str],
    batch_size: int = 128,
    concurrency: int = 4,
) -> int:
    if not pending_records:
        return 0
    uploaded = 0
    started = time.perf_counter()
    semaphore = asyncio.Semaphore(concurrency)
    ckpt_lock = asyncio.Lock()

    async with httpx.AsyncClient(
        verify=system_ssl_context(),
        timeout=httpx.Timeout(90.0),
        headers=qdrant_headers,
    ) as aclient:

        async def upload_batch(batch: list[tuple[Any, dict[str, object], str]]) -> None:
            nonlocal uploaded
            shas = [sha for _, _, sha in batch]
            vec_map = cache.get_many(shas)
            points_json: list[dict[str, Any]] = []
            for record, extra_payload, sha in batch:
                dense = vec_map.get(sha)
                if dense is None:
                    raise RuntimeError(f"missing cached vector for sha={sha}")
                inf_text = build_structural_inference_text(record)
                sparse = sparse_encoder.encode_document(inf_text)
                pt = build_vertex_point(
                    record,
                    dense_vector=dense,
                    sparse_vector=sparse,
                    contract=contract,
                    extra_payload=extra_payload,
                )
                points_json.append(pt.model_dump(mode="json", exclude_none=False))

            async with semaphore:
                for attempt in range(4):
                    try:
                        resp = await aclient.put(
                            f"{qdrant_root}/collections/{contract.collection_name}/points?wait=true",
                            json={"points": points_json},
                        )
                        if resp.status_code not in {429, 500, 502, 503, 504}:
                            resp.raise_for_status()
                            break
                    except httpx.TransportError:
                        if attempt == 3:
                            raise
                    if attempt == 3:
                        resp.raise_for_status()
                    await asyncio.sleep(1.5 * (2**attempt))

            async with ckpt_lock:
                if checkpoint is not None:
                    checkpoint.acknowledge([rec.record_id for rec, _, _ in batch])
                uploaded += len(batch)
                if uploaded % 5120 < len(batch) or uploaded == len(pending_records):
                    elapsed = max(0.001, time.perf_counter() - started)
                    print(
                        json.dumps(
                            {
                                "stage": "qdrant_v3_upsert",
                                "uploaded": uploaded,
                                "total_pending": len(pending_records),
                                "points_per_sec": round(uploaded / elapsed, 1),
                            }
                        ),
                        flush=True,
                    )

        batches = [
            pending_records[offset : offset + batch_size]
            for offset in range(0, len(pending_records), batch_size)
        ]
        # Process in bounded waves of 16 batches so memory stays tiny
        wave_size = 16
        for w_start in range(0, len(batches), wave_size):
            await asyncio.gather(*(upload_batch(b) for b in batches[w_start : w_start + wave_size]))

    return uploaded


def _wait_for_qdrant_green(
    qdrant_client: httpx.Client,
    *,
    qdrant_root: str,
    qdrant_headers: dict[str, str],
    collection_name: str,
    expected_points: int,
    require_body_schema_count: bool = False,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_info: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_info = (
            _request_with_retry(
                qdrant_client,
                "GET",
                f"{qdrant_root}/collections/{collection_name}",
                headers=qdrant_headers,
            )
            .json()
            .get("result", {})
        )
        status_ok = last_info.get("status") == "green"
        pts_ok = last_info.get("points_count") == expected_points
        body_pts = (
            last_info.get("payload_schema", {}).get("body", {}).get("points")
            if require_body_schema_count
            else expected_points
        )
        if status_ok and pts_ok and body_pts == expected_points:
            return last_info
        time.sleep(2.0)
    return last_info


async def execute_sync_async(
    *,
    settings: Settings,
    vector_cache_path: Path = DEFAULT_VECTOR_CACHE_PATH,
    checkpoint_path: Path | None = None,
    receipt_path: Path | None = None,
    max_total_points: int = CURATED_V3_POINT_BUDGET,
) -> dict[str, Any]:
    started = time.perf_counter()
    store_path = resolve_content_store_path(settings)
    store = ContentStore(store_path)

    print(json.dumps({"stage": "select_curated_corpus", "store": str(store_path)}), flush=True)
    plan, prepared = select_and_chunk_curated_corpus(
        store,
        max_total_points=max_total_points,
    )
    records_with_extra = build_structural_records_from_prepared(
        plan,
        prepared,
        repository=settings.DATASET_REPOSITORY,
        revision=settings.DATASET_REVISION,
    )
    print(
        json.dumps(
            {
                "stage": "curated_corpus_ready",
                "documents": plan.total_documents,
                "points": len(records_with_extra),
                "tier_counts": plan.tier_counts,
                "tier_points": plan.tier_points,
            }
        ),
        flush=True,
    )

    contract = VertexQdrantContract(
        collection_name=settings.VERTEX_QDRANT_COLLECTION_NAME,
        embedding_model=settings.VERTEX_EMBEDDING_MODEL,
        vector_size=settings.VERTEX_QDRANT_VECTOR_SIZE,
    )
    cache = VectorReuseCache(vector_cache_path, dimension=contract.vector_size)
    checkpoint = (
        MigrationCheckpoint(checkpoint_path, contract)
        if checkpoint_path is not None
        else None
    )
    sparse_encoder = FastSparseEncoder(
        average_document_length=settings.V3_AVERAGE_SPARSE_DOCUMENT_LENGTH,
    )

    qdrant_root = (settings.QDRANT_URL or "").rstrip("/")
    qdrant_key = settings.QDRANT_API_KEY or ""
    supa_root = (settings.SUPABASE_URL or "").rstrip("/")
    supa_service_key = settings.SUPABASE_SERVICE_ROLE_KEY or ""
    if not (qdrant_root and qdrant_key and supa_root and supa_service_key):
        raise ValueError("Qdrant and Supabase service credentials are required for sync")

    qdrant_headers = {"api-key": qdrant_key}
    supa_headers = {
        "apikey": supa_service_key,
        "authorization": f"Bearer {supa_service_key}",
    }

    with (
        httpx.Client(verify=system_ssl_context(), timeout=httpx.Timeout(90.0)) as q_client,
        httpx.Client(verify=system_ssl_context(), timeout=httpx.Timeout(90.0)) as s_client,
    ):
        # Step 1: Ensure V3 Free-Tier-safe segment bounds, payload indexes & scroll existing V3 vectors into SQLite cache
        _request_with_retry(
            q_client,
            "PATCH",
            f"{qdrant_root}/collections/{contract.collection_name}",
            headers=qdrant_headers,
            json={
                "optimizers_config": {
                    "default_segment_number": 6,
                    "max_segment_size": 180000,
                }
            },
        )
        _ensure_qdrant_indexes(
            q_client,
            qdrant_root=qdrant_root,
            qdrant_headers=qdrant_headers,
            collection_name=contract.collection_name,
            indexes=V3_PAYLOAD_INDEXES,
        )
        existing_v3_ids, remote_meta_by_id, newly_cached = _scroll_existing_v3_into_cache(
            q_client,
            qdrant_root=qdrant_root,
            qdrant_headers=qdrant_headers,
            collection_name=contract.collection_name,
            cache=cache,
        )
        print(
            json.dumps(
                {
                    "stage": "v3_remote_inventory_scrolled",
                    "existing_v3_points": len(existing_v3_ids),
                    "scrolled_into_cache": newly_cached,
                    "total_cached_vectors": cache.count(),
                }
            ),
            flush=True,
        )

        # Determine which records need embedding and/or upserting
        all_shas: list[str] = []
        enriched_records: list[tuple[Any, dict[str, object], str]] = []
        for record, extra in records_with_extra:
            inf_sha = structural_inference_text_sha256(record)
            all_shas.append(inf_sha)
            enriched_records.append((record, extra, inf_sha))

        cached_shas = cache.has_many(all_shas)
        unique_missing_by_sha: dict[str, tuple[str, str]] = {}
        for record, _, inf_sha in enriched_records:
            if inf_sha not in cached_shas and inf_sha not in unique_missing_by_sha:
                unique_missing_by_sha[inf_sha] = (
                    build_structural_inference_text(record),
                    record.title,
                )

        missing_embed_list = [
            (sha, text, title)
            for sha, (text, title) in unique_missing_by_sha.items()
        ]
        reused_vector_count = len(set(all_shas)) - len(missing_embed_list)
        print(
            json.dumps(
                {
                    "stage": "v3_vector_diff",
                    "unique_target_hashes": len(set(all_shas)),
                    "reused_cached_hashes": reused_vector_count,
                    "missing_vertex_hashes": len(missing_embed_list),
                }
            ),
            flush=True,
        )

        # Step 2a: Batch-embed missing chunks via Vertex AI
        embedded_count = 0
        if missing_embed_list:
            provider = VertexAIProvider(settings=settings)
            try:
                embedded_count = await _batch_embed_missing_vectors(
                    missing_embed_list,
                    provider=provider,
                    cache=cache,
                    vector_size=contract.vector_size,
                    batch_size=64,
                    concurrency=3,
                )
            finally:
                await provider.close()

        # Step 2b: Upsert pending V3 records (skip only if already in remote V3 with identical sha & v4 metadata)
        pending_v3: list[tuple[Any, dict[str, object], str]] = []
        for record, extra, inf_sha in enriched_records:
            remote_meta = remote_meta_by_id.get(record.record_id)
            if (
                remote_meta is not None
                and remote_meta[0] == inf_sha
                and remote_meta[1] == extra["validity_hint"]
                and remote_meta[2] == extra["issuance_year"]
                and remote_meta[3] == extra["normative_rank"]
            ):
                continue
            pending_v3.append((record, extra, inf_sha))

        upserted_v3 = await _upsert_v3_points_async(
            pending_v3,
            cache=cache,
            sparse_encoder=sparse_encoder,
            contract=contract,
            checkpoint=checkpoint,
            qdrant_root=qdrant_root,
            qdrant_headers=qdrant_headers,
            batch_size=128,
            concurrency=4,
        )

        # Step 2c: Delete stale V3 point IDs
        target_v3_ids = {rec.record_id for rec, _, _ in enriched_records}
        stale_v3_ids = compute_sync_id_diff(
            existing_ids=existing_v3_ids,
            target_ids=target_v3_ids,
        )
        for offset in range(0, len(stale_v3_ids), 500):
            batch_del = stale_v3_ids[offset : offset + 500]
            _request_with_retry(
                q_client,
                "POST",
                f"{qdrant_root}/collections/{contract.collection_name}/points/delete?wait=true",
                headers=qdrant_headers,
                json={"points": batch_del},
            )
        print(
            json.dumps(
                {
                    "stage": "v3_sync_complete",
                    "upserted_v3": upserted_v3,
                    "deleted_stale_v3": len(stale_v3_ids),
                }
            ),
            flush=True,
        )

        # Step 3: Sync Supabase public.legal_documents (prune stale first to preserve 500MB headroom & shrink indexes)
        curated_sha_by_id = {
            entry.document_id: entry.content_sha256 for entry in plan.entries
        }
        curated_ids = list(plan.document_ids)
        existing_supa = _scroll_supabase_hashes(
            s_client,
            supa_root=supa_root,
            supa_headers=supa_headers,
        )
        stale_supa_ids = compute_sync_id_diff(
            existing_ids=existing_supa.keys(),
            target_ids=curated_ids,
        )
        deleted_supa = 0
        for offset in range(0, len(stale_supa_ids), 100):
            batch_del = stale_supa_ids[offset : offset + 100]
            deleted_supa += _delete_supabase_ids_adaptive(
                s_client,
                supa_root=supa_root,
                supa_headers=supa_headers,
                document_ids=batch_del,
            )
            if deleted_supa % 1000 < len(batch_del) or deleted_supa == len(stale_supa_ids):
                print(
                    json.dumps(
                        {
                            "stage": "supabase_prune_stale",
                            "deleted": deleted_supa,
                            "total_stale": len(stale_supa_ids),
                        }
                    ),
                    flush=True,
                )

        missing_supa_ids = [
            doc_id
            for doc_id in curated_ids
            if existing_supa.get(doc_id) != curated_sha_by_id[doc_id]
        ]
        uploader = SupabaseFullDocUploader(
            url=supa_root,
            service_role_key=supa_service_key,
            table="legal_documents",
            client=s_client,
        )
        upserted_supa = 0
        for offset in range(0, len(missing_supa_ids), 20):
            batch_ids = missing_supa_ids[offset : offset + 20]
            loaded_docs = store.get_many(batch_ids)
            rows = [
                build_supabase_row(
                    loaded_docs[doc_id],
                    dataset_revision=settings.DATASET_REVISION,
                )
                for doc_id in batch_ids
            ]
            upserted_supa += _upsert_supabase_rows_adaptive(uploader, rows)
            if upserted_supa % 400 < len(rows) or upserted_supa == len(missing_supa_ids):
                print(
                    json.dumps(
                        {
                            "stage": "supabase_upsert",
                            "upserted": upserted_supa,
                            "total_missing": len(missing_supa_ids),
                        }
                    ),
                    flush=True,
                )
        print(
            json.dumps(
                {
                    "stage": "supabase_sync_complete",
                    "upserted_supabase": upserted_supa,
                    "deleted_stale_supabase": len(stale_supa_ids),
                }
            ),
            flush=True,
        )

        # Step 4: Sync Qdrant vietlex-legal-body-search-v1 (prune stale first)
        body_collection = settings.QDRANT_FULL_DOC_BODY_COLLECTION or BODY_SEARCH_COLLECTION
        _ensure_qdrant_indexes(
            q_client,
            qdrant_root=qdrant_root,
            qdrant_headers=qdrant_headers,
            collection_name=body_collection,
            indexes=BODY_SEARCH_INDEXES,
        )
        existing_body = _scroll_body_search_hashes(
            q_client,
            qdrant_root=qdrant_root,
            qdrant_headers=qdrant_headers,
            collection_name=body_collection,
        )
        stale_body_ids = compute_sync_id_diff(
            existing_ids=existing_body.keys(),
            target_ids=curated_ids,
        )
        for offset in range(0, len(stale_body_ids), 500):
            batch_del = stale_body_ids[offset : offset + 500]
            _request_with_retry(
                q_client,
                "POST",
                f"{qdrant_root}/collections/{body_collection}/points/delete?wait=true",
                headers=qdrant_headers,
                json={"points": batch_del},
            )

        missing_body_ids = [
            doc_id
            for doc_id in curated_ids
            if existing_body.get(doc_id) != curated_sha_by_id[doc_id]
        ]
        upserted_body = 0
        for offset in range(0, len(missing_body_ids), 25):
            batch_ids = missing_body_ids[offset : offset + 25]
            loaded_docs = store.get_many(batch_ids)
            points = [
                point_from_source(
                    {
                        "document_id": doc_id,
                        "content": loaded_docs[doc_id].content,
                        "content_sha256": loaded_docs[doc_id].content_sha256,
                        "legal_type": loaded_docs[doc_id].metadata.legal_type.strip(),
                        "issuing_authority": loaded_docs[doc_id].metadata.issuing_authority.strip(),
                        "issuance_date": loaded_docs[doc_id].metadata.issuance_date,
                    }
                )
                for doc_id in batch_ids
            ]
            payload_len = sum(len(p["payload"]["body"].encode("utf-8")) for p in points)
            if payload_len > 2_500_000 and len(points) > 1:
                for sub_off in range(0, len(points), 4):
                    _request_with_retry(
                        q_client,
                        "PUT",
                        f"{qdrant_root}/collections/{body_collection}/points?wait=true",
                        headers=qdrant_headers,
                        json={"points": points[sub_off : sub_off + 4]},
                    )
            else:
                _request_with_retry(
                    q_client,
                    "PUT",
                    f"{qdrant_root}/collections/{body_collection}/points?wait=true",
                    headers=qdrant_headers,
                    json={"points": points},
                )
            upserted_body += len(points)
            if upserted_body % 400 < len(points) or upserted_body == len(missing_body_ids):
                print(
                    json.dumps(
                        {
                            "stage": "qdrant_body_upsert",
                            "upserted": upserted_body,
                            "total_missing": len(missing_body_ids),
                        }
                    ),
                    flush=True,
                )

        _wait_for_qdrant_green(
            q_client,
            qdrant_root=qdrant_root,
            qdrant_headers=qdrant_headers,
            collection_name=body_collection,
            expected_points=len(curated_ids),
            require_body_schema_count=True,
            timeout_seconds=120.0,
        )
        _wait_for_qdrant_green(
            q_client,
            qdrant_root=qdrant_root,
            qdrant_headers=qdrant_headers,
            collection_name=contract.collection_name,
            expected_points=len(records_with_extra),
            require_body_schema_count=False,
            timeout_seconds=120.0,
        )

    receipt = {
        "status": "synced",
        "completed_at": _utc_now(),
        "selection_sha256": plan.selection_sha256,
        "curated_documents": plan.total_documents,
        "curated_v3_points": len(records_with_extra),
        "vertex_embedded_new_hashes": embedded_count,
        "reused_cached_hashes": reused_vector_count,
        "v3_upserted_points": upserted_v3,
        "v3_deleted_stale_points": len(stale_v3_ids),
        "supabase_upserted_docs": upserted_supa,
        "supabase_deleted_stale_docs": len(stale_supa_ids),
        "body_search_upserted_docs": upserted_body,
        "body_search_deleted_stale_docs": len(stale_body_ids),
        "wall_seconds": round(time.perf_counter() - started, 2),
    }
    if receipt_path is not None:
        _write_json_atomic(receipt_path, receipt)
    return receipt


def execute_verify(
    *,
    settings: Settings,
    receipt_path: Path | None = None,
    max_total_points: int = CURATED_V3_POINT_BUDGET,
) -> dict[str, Any]:
    started = time.perf_counter()
    store_path = resolve_content_store_path(settings)
    store = ContentStore(store_path)
    plan, _ = select_and_chunk_curated_corpus(
        store,
        max_total_points=max_total_points,
    )
    expected_ids = set(plan.document_ids)
    expected_shas = {
        entry.document_id: entry.content_sha256 for entry in plan.entries
    }

    qdrant_root = (settings.QDRANT_URL or "").rstrip("/")
    qdrant_key = settings.QDRANT_API_KEY or ""
    supa_root = (settings.SUPABASE_URL or "").rstrip("/")
    supa_service_key = settings.SUPABASE_SERVICE_ROLE_KEY or ""
    supa_pub_key = settings.SUPABASE_PUBLISHABLE_KEY or supa_service_key

    qdrant_headers = {"api-key": qdrant_key}
    supa_headers = {
        "apikey": supa_service_key,
        "authorization": f"Bearer {supa_service_key}",
    }
    v3_collection = settings.VERTEX_QDRANT_COLLECTION_NAME
    body_collection = settings.QDRANT_FULL_DOC_BODY_COLLECTION or BODY_SEARCH_COLLECTION

    with (
        httpx.Client(verify=system_ssl_context(), timeout=httpx.Timeout(90.0)) as q_client,
        httpx.Client(verify=system_ssl_context(), timeout=httpx.Timeout(90.0)) as s_client,
    ):
        _wait_for_qdrant_green(
            q_client,
            qdrant_root=qdrant_root,
            qdrant_headers=qdrant_headers,
            collection_name=body_collection,
            expected_points=len(expected_ids),
            require_body_schema_count=True,
            timeout_seconds=120.0,
        )
        _wait_for_qdrant_green(
            q_client,
            qdrant_root=qdrant_root,
            qdrant_headers=qdrant_headers,
            collection_name=v3_collection,
            expected_points=plan.total_points,
            require_body_schema_count=False,
            timeout_seconds=120.0,
        )

        # Scroll V3 to verify exact document_id set & distinct article counts
        v3_doc_ids: set[int] = set()
        v3_articles_by_doc: dict[int, set[str]] = {}
        v3_total_scrolled = 0
        v3_missing_metadata = 0
        offset: Any = None
        while True:
            req: dict[str, Any] = {
                "limit": 1000,
                "with_payload": [
                    "document_id",
                    "article",
                    "validity_hint",
                    "issuance_year",
                    "normative_rank",
                ],
                "with_vector": False,
            }
            if offset is not None:
                req["offset"] = offset
            result = (
                _request_with_retry(
                    q_client,
                    "POST",
                    f"{qdrant_root}/collections/{v3_collection}/points/scroll",
                    headers=qdrant_headers,
                    json=req,
                )
                .json()
                .get("result", {})
            )
            for pt in result.get("points", []):
                v3_total_scrolled += 1
                payload = pt.get("payload") or {}
                doc_id = int(payload["document_id"])
                v3_doc_ids.add(doc_id)
                art = payload.get("article")
                if isinstance(art, str) and art.strip():
                    v3_articles_by_doc.setdefault(doc_id, set()).add(art.strip().casefold())
                if (
                    payload.get("validity_hint") not in {"active_candidate", "superseded"}
                    or not isinstance(payload.get("issuance_year"), int)
                    or not isinstance(payload.get("normative_rank"), int)
                ):
                    v3_missing_metadata += 1
            offset = result.get("next_page_offset")
            if offset is None:
                break

        supa_hashes = _scroll_supabase_hashes(
            s_client,
            supa_root=supa_root,
            supa_headers=supa_headers,
        )
        body_hashes = _scroll_body_search_hashes(
            q_client,
            qdrant_root=qdrant_root,
            qdrant_headers=qdrant_headers,
            collection_name=body_collection,
        )

        cloud_state = _snapshot_cloud_state(
            supa_client=s_client,
            supa_root=supa_root,
            supa_headers=supa_headers,
            qdrant_client=q_client,
            qdrant_root=qdrant_root,
            qdrant_headers=qdrant_headers,
        )

        # Verify QdrantFullDocBodySearch.coverage() live
        supa_store = SupabaseLegalStore(
            url=supa_root,
            publishable_key=supa_pub_key,
        )
        body_search = QdrantFullDocBodySearch(
            url=qdrant_root,
            api_key=qdrant_key,
            collection=body_collection,
            store=supa_store,
            client=q_client,
        )
        coverage_result = body_search.coverage()

    parity_v3_vs_curated = v3_doc_ids == expected_ids
    parity_supa_vs_curated = set(supa_hashes) == expected_ids
    parity_body_vs_curated = set(body_hashes) == expected_ids
    sha_parity_supa = supa_hashes == expected_shas
    sha_parity_body = body_hashes == expected_shas
    coverage_ok = coverage_result == {
        "document_count": len(expected_ids),
        "index_version": 1,
    }
    passages_zero = cloud_state["supabase_table_counts"]["legal_body_passages"] == 0
    disk_bytes = int(cloud_state["qdrant_total_disk_bytes"])
    ram_bytes = int(cloud_state["qdrant_total_ram_bytes"])
    disk_ok = disk_bytes < int(2.8 * (1024**3))
    ram_ok = ram_bytes < 600 * (1024**2)

    live_article_checks: dict[str, Any] = {}
    all_articles_ok = True
    for doc_id, label, expected_articles in KEY_VERIFICATION_DOCUMENTS:
        present = doc_id in v3_doc_ids
        distinct_count = len(v3_articles_by_doc.get(doc_id, set()))
        if doc_id == 619502:
            ok = present and distinct_count >= expected_articles
        elif expected_articles and expected_articles > 1:
            ok = present and distinct_count == expected_articles
        else:
            ok = present
        if not ok:
            all_articles_ok = False
        live_article_checks[str(doc_id)] = {
            "label": label,
            "present": present,
            "live_distinct_articles": distinct_count,
            "expected": f">={expected_articles}" if doc_id == 619502 else expected_articles,
            "ok": ok,
        }

    english_387595_absent = 387595 not in v3_doc_ids
    v3_green = (
        cloud_state["qdrant_collections"].get(v3_collection, {}).get("status")
        == "green"
    )
    body_green = (
        cloud_state["qdrant_collections"].get(body_collection, {}).get("status")
        == "green"
    )
    all_passed = all(
        (
            parity_v3_vs_curated,
            parity_supa_vs_curated,
            parity_body_vs_curated,
            sha_parity_supa,
            sha_parity_body,
            v3_total_scrolled == plan.total_points,
            v3_missing_metadata == 0,
            coverage_ok,
            passages_zero,
            disk_ok,
            ram_ok,
            v3_green,
            body_green,
            all_articles_ok,
            english_387595_absent,
        )
    )

    receipt = {
        "schema": "vietlex-curated-v4-verify-receipt-v1",
        "verified_at": _utc_now(),
        "status": "passed" if all_passed else "failed",
        "selection_sha256": plan.selection_sha256,
        "expected_documents": len(expected_ids),
        "expected_v3_points": plan.total_points,
        "observed_v3_points": v3_total_scrolled,
        "observed_v3_unique_documents": len(v3_doc_ids),
        "observed_supabase_documents": len(supa_hashes),
        "observed_body_search_documents": len(body_hashes),
        "v3_missing_v4_payload_fields": v3_missing_metadata,
        "parity": {
            "v3_equals_curated": parity_v3_vs_curated,
            "supabase_equals_curated": parity_supa_vs_curated,
            "body_search_equals_curated": parity_body_vs_curated,
            "supabase_sha256_exact": sha_parity_supa,
            "body_search_sha256_exact": sha_parity_body,
            "english_387595_absent": english_387595_absent,
        },
        "body_search_coverage": coverage_result,
        "quotas": {
            "supabase_legal_body_passages": cloud_state["supabase_table_counts"]["legal_body_passages"],
            "qdrant_total_disk_bytes": disk_bytes,
            "qdrant_total_disk_gib": round(disk_bytes / (1024**3), 3),
            "qdrant_disk_under_2_8_gib": disk_ok,
            "qdrant_total_ram_bytes": ram_bytes,
            "qdrant_total_ram_mib": round(ram_bytes / (1024**2), 2),
            "qdrant_ram_under_600_mib": ram_ok,
        },
        "postgrest_observability": dict(POSTGREST_OBSERVABILITY_NOTE),
        "cloud_state": cloud_state,
        "live_article_checks": live_article_checks,
        "wall_seconds": round(time.perf_counter() - started, 2),
    }
    if receipt_path is not None:
        _write_json_atomic(receipt_path, receipt)
    if not all_passed:
        raise RuntimeError(f"Curated V4 verification failed; inspect {receipt_path}")
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="Provider-free local byte & point audit")
    p_plan.add_argument("--output", type=Path, default=DEFAULT_PLAN_PATH)
    p_plan.add_argument("--max-points", type=int, default=CURATED_V3_POINT_BUDGET)

    p_reclaim = sub.add_parser("reclaim", help="Clean dead Free-Tier cloud storage")
    p_reclaim.add_argument(
        "--confirm-free-tier-cleanup",
        action="store_true",
        dest="confirm_cleanup",
    )
    p_reclaim.add_argument("--receipt", type=Path, default=DEFAULT_PRE_RECLAIM_RECEIPT)
    p_reclaim.add_argument("--reclaim-receipt", type=Path, default=DEFAULT_RECLAIM_RECEIPT)

    p_sync = sub.add_parser("sync", help="Batch-embed and sync Qdrant V3 + Body Search + Supabase")
    p_sync.add_argument("--max-points", type=int, default=CURATED_V3_POINT_BUDGET)
    p_sync.add_argument("--receipt", type=Path, default=DEFAULT_SYNC_RECEIPT)
    p_sync.add_argument("--checkpoint", type=Path, default=DEFAULT_V3_CHECKPOINT_PATH)

    p_verify = sub.add_parser("verify", help="Verify 1:1:1 parity, quotas, and live articles")
    p_verify.add_argument("--max-points", type=int, default=CURATED_V3_POINT_BUDGET)
    p_verify.add_argument("--receipt", type=Path, default=DEFAULT_VERIFY_RECEIPT)

    args = parser.parse_args(list(argv) if argv is not None else None)
    settings = get_settings()

    if args.command == "plan":
        store = ContentStore(resolve_content_store_path(settings))
        report = build_plan_report(
            store,
            repository=settings.DATASET_REPOSITORY,
            revision=settings.DATASET_REVISION,
            output_path=args.output,
            max_total_points=args.max_points,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.command == "reclaim":
        report = execute_reclaim(
            confirm_cleanup=bool(args.confirm_cleanup),
            supabase_url=settings.SUPABASE_URL or "",
            supabase_service_key=settings.SUPABASE_SERVICE_ROLE_KEY or "",
            qdrant_url=settings.QDRANT_URL or "",
            qdrant_api_key=settings.QDRANT_API_KEY or "",
            receipt_path=args.receipt,
            reclaim_receipt_path=args.reclaim_receipt,
            settings=settings,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.command == "sync":
        report = asyncio.run(
            execute_sync_async(
                settings=settings,
                checkpoint_path=args.checkpoint,
                receipt_path=args.receipt,
                max_total_points=args.max_points,
            )
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.command == "verify":
        report = execute_verify(
            settings=settings,
            receipt_path=args.receipt,
            max_total_points=args.max_points,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
