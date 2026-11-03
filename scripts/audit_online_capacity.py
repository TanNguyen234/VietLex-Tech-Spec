"""Read-only inventory of online index capacity and absent local candidates.

Default mode inspects the configured local SQLite content store only. The
opt-in online mode uses Qdrant GET/scroll POST and Supabase HEAD/GET requests;
it does not create SDK clients, embeddings, or remote writes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from typing import Any, Iterable, Mapping
from urllib.parse import quote

import httpx

from app.config import Settings, get_settings, system_ssl_context
from app.ingestion.content_store import ContentStore
from app.ingestion.legal_text import chunk_document
from app.ingestion.vertex_qdrant_migration import (
    DEFAULT_MIGRATION_LEGAL_TYPES,
    select_evenly_spaced_chunks,
)


MAX_CANDIDATES = 100
SCROLL_PAGE_SIZE = 10_000
SCROLL_POINT_LIMIT = 1_000_000
SUPABASE_PAGE_SIZE = 1_000
SUPABASE_ROW_LIMIT = 1_000_000
ONLINE_WALL_BUDGET_SECONDS = 300
CHUNK_MAX_TOKENS = 320
CHUNK_OVERLAP_TOKENS = 32
MAX_CHUNKS_PER_DOCUMENT = 16
VECTOR_DIMENSION = 1_024
# These are exactly the flags build_vertex_records() excludes. Other stored
# flags, including duplicate_content_hash, are retained and reported.
BUILDER_EXCLUDED_FLAGS = frozenset(
    {
        "empty_content",
        "encoding_damage",
        "missing_document_number",
        "missing_title",
        "missing_source_url",
    }
)
MEMORY_FIELDS = {
    "disk_bytes": ("disk_bytes", "disk"),
    "ram_bytes": ("ram_bytes", "ram"),
    "cached_bytes": ("cached_bytes", "cached"),
    "expected_cache_bytes": ("expected_cache_bytes", "expected_cache"),
}


def parse_content_range_total(value: str | None) -> int | None:
    if not value or "/" not in value:
        return None
    total = value.rsplit("/", 1)[1].strip()
    return int(total) if total.isdigit() else None


def candidate_exclusion_reasons(flags: Iterable[str]) -> tuple[str, ...]:
    """Return the current structural-builder exclusion flags in stable order."""
    return tuple(sorted(set(flags) & BUILDER_EXCLUDED_FLAGS))


def balance_candidate_queues(
    queues: Mapping[str, list[dict[str, Any]]],
    *,
    legal_types: Iterable[str] = DEFAULT_MIGRATION_LEGAL_TYPES,
    limit: int,
) -> list[dict[str, Any]]:
    if limit < 0:
        raise ValueError("limit must be non-negative")
    types = tuple(dict.fromkeys(legal_types))
    positions = {legal_type: 0 for legal_type in types}
    chosen: list[dict[str, Any]] = []
    while len(chosen) < limit:
        added = False
        for legal_type in types:
            index = positions[legal_type]
            rows = queues.get(legal_type, [])
            if index >= len(rows):
                continue
            chosen.append(rows[index])
            positions[legal_type] += 1
            added = True
            if len(chosen) == limit:
                break
        if not added:
            break
    return chosen


def qdrant_memory_totals(memory: Mapping[str, Any]) -> dict[str, int | None]:
    """Read the server's total block, or sum component rows if absent."""
    values: dict[str, int | None] = {name: None for name in MEMORY_FIELDS}
    total = memory.get("total")
    if isinstance(total, Mapping) and any(
        alias in total for aliases in MEMORY_FIELDS.values() for alias in aliases
    ):
        for target, aliases in MEMORY_FIELDS.items():
            raw = next(
                (
                    total[key]
                    for key in aliases
                    if isinstance(total.get(key), (int, float)) and not isinstance(total.get(key), bool)
                ),
                None,
            )
            if raw is not None:
                values[target] = int(raw)
        return values
    sums: Counter[str] = Counter()
    found: set[str] = set()
    for component in memory.values():
        if not isinstance(component, Mapping):
            continue
        for target, aliases in MEMORY_FIELDS.items():
            raw = next(
                (
                    component[key]
                    for key in aliases
                    if isinstance(component.get(key), (int, float)) and not isinstance(component.get(key), bool)
                ),
                None,
            )
            if raw is not None:
                sums[target] += int(raw)
                found.add(target)
    for key in found:
        values[key] = int(sums[key])
    return values


def _parse_flags(value: object) -> set[str]:
    try:
        decoded = json.loads(str(value or "[]"))
    except (TypeError, ValueError):
        return {"invalid_quality_flags"}
    if not isinstance(decoded, list) or any(not isinstance(item, str) for item in decoded):
        return {"invalid_quality_flags"}
    return set(decoded)


def _read_only_sqlite(path: Path) -> sqlite3.Connection:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError("content_store_missing")
    return sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)


def _hash_ids(values: Iterable[int], *, ordered: bool = False) -> str:
    items = [int(value) for value in values]
    if not ordered:
        items = sorted(set(items))
    data = json.dumps(items, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(data).hexdigest()


def _local_counts(path: Path, root: Path) -> dict[str, Any]:
    try:
        with _read_only_sqlite(path) as db:
            result = {
                "status": "ok",
                "path": path.resolve().relative_to(root.resolve()).as_posix()
                if path.resolve().is_relative_to(root.resolve())
                else path.name,
                "metadata_rows": db.execute("SELECT COUNT(*) FROM metadata").fetchone()[0],
                "content_rows": db.execute("SELECT COUNT(*) FROM contents").fetchone()[0],
                "joined_rows": db.execute(
                    "SELECT COUNT(*) FROM metadata m JOIN contents c USING(document_id)"
                ).fetchone()[0],
                "metadata_only_rows": db.execute(
                    "SELECT COUNT(*) FROM metadata m LEFT JOIN contents c USING(document_id) "
                    "WHERE c.document_id IS NULL"
                ).fetchone()[0],
                "content_only_rows": db.execute(
                    "SELECT COUNT(*) FROM contents c LEFT JOIN metadata m USING(document_id) "
                    "WHERE m.document_id IS NULL"
                ).fetchone()[0],
            }
            row = db.execute(
                "SELECT value FROM build_metadata WHERE key='build_report'"
            ).fetchone()
        if row:
            try:
                report = json.loads(str(row[0]))
                result["build_report"] = {
                    key: report.get(key)
                    for key in (
                        "compressed_bytes",
                        "uncompressed_bytes",
                        "duplicate_content_hash_count",
                        "quality_flag_counts",
                    )
                }
            except (TypeError, ValueError):
                result["build_report"] = {"status": "invalid_build_report"}
        else:
            result["build_report"] = None
        return result
    except FileNotFoundError:
        return {"status": "missing"}
    except (OSError, sqlite3.Error) as error:
        return {"status": "error", "error_kind": type(error).__name__}


def _candidate_queues(
    path: Path,
    online_ids: set[int],
    *,
    limit: int,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    legal_types = DEFAULT_MIGRATION_LEGAL_TYPES
    marks = ",".join("?" for _ in legal_types)
    query = (
        "SELECT m.document_id,m.legal_type,m.issuance_date,m.title,m.document_number,"
        "m.quality_flags,c.quality_flags,c.content_bytes,c.content_sha256 "
        "FROM metadata m JOIN contents c USING(document_id) "
        f"WHERE m.legal_type IN ({marks}) "
        "ORDER BY CASE WHEN m.issuance_date IS NULL OR m.issuance_date='' THEN 1 ELSE 0 END, "
        "m.issuance_date DESC,m.document_id ASC"
    )
    queues = {kind: [] for kind in legal_types}
    eligible = Counter()
    excluded = Counter()
    flag_counts = Counter()
    with _read_only_sqlite(path) as db:
        cursor = db.execute(query, legal_types)
        while rows := cursor.fetchmany(2_000):
            for row in rows:
                document_id, kind = int(row[0]), str(row[1] or "")
                if document_id in online_ids:
                    continue
                flags = _parse_flags(row[5]) | _parse_flags(row[6])
                for flag in flags:
                    flag_counts[(kind, flag)] += 1
                reasons = candidate_exclusion_reasons(flags)
                if reasons:
                    for reason in reasons:
                        excluded[(kind, reason)] += 1
                    continue
                eligible[kind] += 1
                if len(queues[kind]) < limit:
                    queues[kind].append(
                        {
                            "document_id": document_id,
                            "legal_type": kind,
                            "issuance_date": str(row[2]) if row[2] else None,
                            "title": str(row[3] or "")[:240],
                            "document_number": str(row[4] or "")[:120],
                            "stored_content_bytes": int(row[7] or 0),
                            "content_sha256_in_metadata": str(row[8] or ""),
                        }
                    )
    return queues, {
        "eligible_absent_by_legal_type": dict(eligible),
        "excluded_absent_by_legal_type_and_flag": {
            f"{kind}|{flag}": count for (kind, flag), count in sorted(excluded.items())
        },
        "all_flags_seen_absent_by_legal_type": {
            f"{kind}|{flag}": count for (kind, flag), count in sorted(flag_counts.items())
        },
    }


def _read_json(response: httpx.Response) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if response.status_code >= 400:
        return None, {"status": "error", "http_status": response.status_code, "error_kind": "http_status"}
    try:
        payload = response.json()
    except ValueError:
        return None, {"status": "error", "http_status": response.status_code, "error_kind": "invalid_json"}
    if not isinstance(payload, dict):
        return None, {"status": "error", "http_status": response.status_code, "error_kind": "invalid_response_schema"}
    return payload, None


def _request_error(error: BaseException) -> dict[str, Any]:
    return {
        "status": "error",
        "error_kind": "timeout" if isinstance(error, httpx.TimeoutException) else type(error).__name__,
    }


def _remaining_timeout(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


def _bounded_request_timeout(client: Any, remaining: float) -> float | httpx.Timeout:
    """Cap each request by both the configured HTTPX phase timeouts and remaining budget."""
    configured = getattr(client, "timeout", None)
    if isinstance(configured, httpx.Timeout):
        def cap(value: float | None) -> float:
            return min(remaining, value) if value is not None else remaining

        return httpx.Timeout(
            remaining,
            connect=cap(configured.connect),
            read=cap(configured.read),
            write=cap(configured.write),
            pool=cap(configured.pool),
        )
    if isinstance(configured, (int, float)) and configured > 0:
        return min(remaining, float(configured))
    # Test doubles and compatible injected clients may not expose timeout metadata.
    return remaining


def _qdrant_get(client: httpx.Client, base: str, key: str, path: str, deadline: float):
    remaining = _remaining_timeout(deadline)
    if remaining <= 0:
        return None, {"status": "error", "error_kind": "audit_deadline"}
    try:
        response = client.get(
            f"{base.rstrip('/')}{path}",
            headers={"api-key": key},
            timeout=_bounded_request_timeout(client, remaining),
        )
    except httpx.HTTPError as error:
        return None, _request_error(error)
    return _read_json(response)


def _scroll_ids(
    client: httpx.Client, base: str, key: str, collection: str, deadline: float
) -> dict[str, Any]:
    url = f"{base.rstrip('/')}/collections/{quote(collection, safe='')}/points/scroll"
    offset = None
    offsets: set[str] = set()
    ids: set[int] = set()
    points = pages = missing = 0
    status = "ok"
    while points < SCROLL_POINT_LIMIT:
        remaining = _remaining_timeout(deadline)
        if remaining <= 0:
            status = "partial_audit_deadline"
            break
        payload = {"limit": SCROLL_PAGE_SIZE, "with_payload": ["document_id"], "with_vector": False}
        if offset is not None:
            payload["offset"] = offset
        try:
            response = client.post(
                url,
                headers={"api-key": key},
                json=payload,
                timeout=_bounded_request_timeout(client, remaining),
            )
        except httpx.HTTPError as error:
            return {**_request_error(error), "pages": pages, "point_count": points, "unique_document_count": len(ids)}
        data, error = _read_json(response)
        if error:
            return {**error, "pages": pages, "point_count": points, "unique_document_count": len(ids)}
        result = data.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("points"), list):
            return {"status": "error", "http_status": response.status_code, "error_kind": "invalid_scroll_schema", "pages": pages, "point_count": points, "unique_document_count": len(ids)}
        rows = result["points"]
        pages += 1
        points += len(rows)
        for row in rows:
            values = row.get("payload") if isinstance(row, dict) else None
            try:
                ids.add(int(values["document_id"]))
            except (TypeError, ValueError, KeyError):
                missing += 1
        offset = result.get("next_page_offset")
        if offset is None:
            break
        marker = json.dumps(offset, sort_keys=True, separators=(",", ":"))
        if marker in offsets:
            status = "partial_repeated_offset"
            break
        offsets.add(marker)
        if not rows:
            status = "partial_empty_page_with_offset"
            break
    else:
        status = "partial_point_limit"
    if points >= SCROLL_POINT_LIMIT and offset is not None:
        status = "partial_point_limit"
    return {
        "status": status,
        "pages": pages,
        "point_count": points,
        "unique_document_count": len(ids),
        "missing_document_id_points": missing,
        "document_ids_sha256": _hash_ids(ids),
        "_document_ids": ids,
    }


def _audit_qdrant(client: httpx.Client, settings: Settings, deadline: float) -> dict[str, Any]:
    base, key = str(settings.QDRANT_URL or "").rstrip("/"), str(settings.QDRANT_API_KEY or "")
    if not base or not key:
        return {"status": "not_configured", "collections": [], "scrolls": {}}
    listed, error = _qdrant_get(client, base, key, "/collections", deadline)
    if error:
        return {**error, "collections": [], "scrolls": {}}
    result = listed.get("result")
    rows = result.get("collections") if isinstance(result, dict) else None
    if not isinstance(rows, list):
        return {"status": "error", "error_kind": "invalid_collection_list_schema", "collections": [], "scrolls": {}}
    collections = []
    for row in rows:
        name = row.get("name") if isinstance(row, dict) else None
        if not isinstance(name, str):
            continue
        encoded = quote(name, safe="")
        info, info_error = _qdrant_get(client, base, key, f"/collections/{encoded}", deadline)
        memory, memory_error = _qdrant_get(client, base, key, f"/collections/{encoded}/memory", deadline)
        detail = info.get("result") if isinstance(info, dict) else None
        memory_result = memory.get("result") if isinstance(memory, dict) else None
        collections.append(
            {
                "name": name,
                "info_status": "ok" if info_error is None else info_error,
                "points_count": detail.get("points_count") if isinstance(detail, dict) else None,
                "indexed_vectors_count": detail.get("indexed_vectors_count") if isinstance(detail, dict) else None,
                "collection_status": detail.get("status") if isinstance(detail, dict) else None,
                "memory_status": "ok" if memory_error is None else memory_error,
                "memory": qdrant_memory_totals(memory_result) if isinstance(memory_result, dict) else None,
            }
        )
    known = {item["name"] for item in collections}
    scrolls = {
        name: _scroll_ids(client, base, key, name, deadline) if name in known else {"status": "missing_collection"}
        for name in (settings.VERTEX_QDRANT_COLLECTION_NAME, settings.QDRANT_FULL_DOC_BODY_COLLECTION)
    }
    sums: dict[str, int | None] = {}
    for key_name in ("disk_bytes", "ram_bytes", "cached_bytes"):
        values = [row["memory"].get(key_name) if row.get("memory") else None for row in collections]
        sums[key_name] = sum(values) if values and all(isinstance(v, int) for v in values) else None
    return {
        "status": "ok",
        "collection_count": len(collections),
        "collections": collections,
        "collection_memory_sum": {
            **sums,
            "scope": "sum_of_reported_collections_only_not_whole_filesystem_or_quota",
        },
        "scrolls": scrolls,
    }


def _audit_supabase(client: httpx.Client, settings: Settings, deadline: float) -> dict[str, Any]:
    base, key = str(settings.SUPABASE_URL or "").rstrip("/"), str(settings.SUPABASE_PUBLISHABLE_KEY or "")
    if not base or not key:
        return {"status": "not_configured", "exact_document_count": None, "document_ids": None}
    url = f"{base}/rest/v1/legal_documents"
    common = {"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "count=exact", "Range-Unit": "items"}
    remaining = _remaining_timeout(deadline)
    if remaining <= 0:
        return {"status": "error", "error_kind": "audit_deadline", "exact_document_count": None, "document_ids": None}
    try:
        head = client.head(
            url,
            params={"select": "document_id"},
            headers={**common, "Range": "0-0"},
            timeout=_bounded_request_timeout(client, remaining),
        )
    except httpx.HTTPError as error:
        return {**_request_error(error), "exact_document_count": None, "document_ids": None}
    if head.status_code >= 400:
        return {"status": "error", "http_status": head.status_code, "error_kind": "http_status", "exact_document_count": None, "document_ids": None}
    total = parse_content_range_total(head.headers.get("content-range"))
    if total is None:
        return {"status": "count_unavailable", "http_status": head.status_code, "exact_document_count": None, "document_ids": None}
    if total > SUPABASE_ROW_LIMIT:
        return {"status": "partial_row_limit", "http_status": head.status_code, "exact_document_count": total, "document_ids": None}
    ids: set[int] = set()
    fetched = pages = 0
    for start in range(0, total, SUPABASE_PAGE_SIZE):
        remaining = _remaining_timeout(deadline)
        if remaining <= 0:
            return {"status": "partial_audit_deadline", "exact_document_count": total, "pages": pages, "fetched_row_count": fetched, "document_ids": None}
        end = min(total - 1, start + SUPABASE_PAGE_SIZE - 1)
        headers = {**common, "Range": f"{start}-{end}"}
        try:
            response = client.get(
                url,
                params={"select": "document_id", "order": "document_id.asc"},
                headers=headers,
                timeout=_bounded_request_timeout(client, remaining),
            )
        except httpx.HTTPError as error:
            return {**_request_error(error), "exact_document_count": total, "pages": pages, "fetched_row_count": fetched, "document_ids": None}
        if response.status_code >= 400:
            return {"status": "error", "http_status": response.status_code, "error_kind": "http_status", "exact_document_count": total, "pages": pages, "fetched_row_count": fetched, "document_ids": None}
        try:
            rows = response.json()
        except ValueError:
            rows = None
        if not isinstance(rows, list) or any(not isinstance(row, dict) or set(row) != {"document_id"} for row in rows):
            return {"status": "error", "http_status": response.status_code, "error_kind": "invalid_document_id_page_schema", "exact_document_count": total, "pages": pages, "fetched_row_count": fetched, "document_ids": None}
        pages += 1
        fetched += len(rows)
        try:
            ids.update(int(row["document_id"]) for row in rows)
        except (TypeError, ValueError):
            return {"status": "error", "http_status": response.status_code, "error_kind": "invalid_document_id", "exact_document_count": total, "pages": pages, "fetched_row_count": fetched, "document_ids": None}
        if len(rows) != end - start + 1:
            return {"status": "partial_page", "http_status": response.status_code, "exact_document_count": total, "pages": pages, "fetched_row_count": fetched, "unique_document_count": len(ids), "document_ids": None}
    status = "ok" if fetched == total and len(ids) == total else "count_mismatch"
    return {
        "status": status,
        "http_status": head.status_code,
        "exact_document_count": total,
        "pages": pages,
        "fetched_row_count": fetched,
        "unique_document_count": len(ids),
        "document_ids_sha256": _hash_ids(ids),
        "database_size_bytes": None,
        "database_size_status": "unknown_not_available_from_rest_count",
        "document_ids": ids if status == "ok" else None,
    }


def _online_union(qdrant: Mapping[str, Any], supabase: Mapping[str, Any], settings: Settings):
    scrolls = qdrant.get("scrolls") if isinstance(qdrant, Mapping) else None
    v3 = scrolls.get(settings.VERTEX_QDRANT_COLLECTION_NAME) if isinstance(scrolls, Mapping) else None
    body = scrolls.get(settings.QDRANT_FULL_DOC_BODY_COLLECTION) if isinstance(scrolls, Mapping) else None
    supa_ids = supabase.get("document_ids")
    v3_ids = v3.get("_document_ids") if isinstance(v3, Mapping) else None
    body_ids = body.get("_document_ids") if isinstance(body, Mapping) else None
    if not (
        isinstance(v3_ids, set) and isinstance(body_ids, set) and isinstance(supa_ids, set)
        and v3.get("status") == body.get("status") == supabase.get("status") == "ok"
    ):
        return None, {"status": "unavailable", "reason": "complete_qdrant_v3_body_and_supabase_id_sets_required"}
    union = v3_ids | body_ids | supa_ids
    return union, {
        "status": "ok",
        "qdrant_v3_document_count": len(v3_ids),
        "qdrant_body_document_count": len(body_ids),
        "supabase_document_count": len(supa_ids),
        "v3_not_in_supabase_count": len(v3_ids - supa_ids),
        "body_not_in_supabase_count": len(body_ids - supa_ids),
        "supabase_not_in_body_count": len(supa_ids - body_ids),
        "online_union_document_count": len(union),
        "online_union_document_ids_sha256": _hash_ids(union),
    }


def collect_online_capacity(settings: Settings, *, timeout_seconds: float = 20.0):
    """Perform only metadata reads; reject ambient proxy configuration."""
    deadline = time.monotonic() + ONLINE_WALL_BUDGET_SECONDS
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            verify=system_ssl_context(),
            trust_env=False,
            follow_redirects=False,
        ) as client:
            qdrant = _audit_qdrant(client, settings, deadline)
            supabase = _audit_supabase(client, settings, deadline)
    except (OSError, httpx.HTTPError, ValueError) as error:
        status = {"status": "error", "error_kind": type(error).__name__}
        return ({"qdrant": status, "supabase": status, "document_id_consistency": {"status": "unavailable", "reason": "online_client_setup_failed"}}, None)
    ids, consistency = _online_union(qdrant, supabase, settings)
    public_qdrant = {key: value for key, value in qdrant.items() if key != "scrolls"}
    public_qdrant["scrolls"] = {
        name: {key: value for key, value in summary.items() if key != "_document_ids"}
        for name, summary in qdrant.get("scrolls", {}).items()
    }
    public_supabase = {key: value for key, value in supabase.items() if key != "document_ids"}
    return ({
        "request_limits": {
            "admission_deadline_budget_seconds": ONLINE_WALL_BUDGET_SECONDS,
            "deadline_semantics": "checked before each synchronous request; not a hard overall wall-clock limit",
            "per_request_timeout_seconds": timeout_seconds,
            "per_request_timeout_semantics": "capped by configured HTTPX phase timeouts and remaining admission deadline",
            "scroll_page_size": SCROLL_PAGE_SIZE,
            "scroll_point_limit": SCROLL_POINT_LIMIT,
            "supabase_page_size": SUPABASE_PAGE_SIZE,
            "supabase_row_limit": SUPABASE_ROW_LIMIT,
        },
        "qdrant": public_qdrant,
        "supabase": public_supabase,
        "document_id_consistency": consistency,
    }, ids)


def _candidate_inventory(
    path: Path,
    *,
    root: Path,
    limit: int,
    online_ids: set[int] | None,
    online_status: str,
    revision: str,
) -> dict[str, Any]:
    local = _local_counts(path, root)
    selection: dict[str, Any] = {
        "status": "not_evaluated",
        "limit": limit,
        "method": "round_robin_12_types_sorted_issue_date_desc_document_id_asc",
        "absent_from": "union_of_qdrant_v3_body_and_supabase_document_ids",
        "online_union_count": len(online_ids) if online_ids is not None else None,
        "eligible_absent_by_legal_type": {},
        "excluded_absent_by_legal_type_and_flag": {},
        "all_flags_seen_absent_by_legal_type": {},
        "ordered_document_ids_sha256": None,
        "selected_documents": [],
        "potential_v3_points": 0,
        "dense_float32_bytes_lower_bound": 0,
        "storage_estimate": "not an estimate; excludes sparse vectors, payload, index, replication, WAL and provider overhead",
        "embeddings_created": False,
        "upload_attempted": False,
    }
    if local.get("status") != "ok":
        selection.update(status="local_store_unavailable", reason=local.get("status"))
    elif online_ids is None:
        selection.update(status="not_evaluated", reason=online_status)
    else:
        try:
            queues, counts = _candidate_queues(path, online_ids, limit=limit)
            selection.update(counts)
            chosen = balance_candidate_queues(queues, limit=limit)
            ids = [int(row["document_id"]) for row in chosen]
            documents = ContentStore(path).get_many(ids)
            selected = []
            point_total = 0
            for row in chosen:
                document_id = int(row["document_id"])
                document = documents.get(document_id)
                if document is None:
                    continue
                chunks = chunk_document(
                    document.metadata,
                    document.content,
                    max_tokens=CHUNK_MAX_TOKENS,
                    overlap_tokens=CHUNK_OVERLAP_TOKENS,
                )
                kept = select_evenly_spaced_chunks(chunks, limit=MAX_CHUNKS_PER_DOCUMENT)
                encoded = document.content.encode("utf-8")
                row_hash = row["content_sha256_in_metadata"]
                point_total += len(kept)
                selected.append(
                    {
                        "document_id": document_id,
                        "document_number": row["document_number"],
                        "legal_type": row["legal_type"],
                        "issuance_date": row["issuance_date"],
                        "title": row["title"],
                        "source_content_sha256": document.content_sha256,
                        "content_hash_verified": document.content_sha256 == row_hash,
                        "content_utf8_bytes": len(encoded),
                        "stored_content_bytes": row["stored_content_bytes"],
                        "all_chunks_320_32": len(chunks),
                        "selected_points_cap_16": len(kept),
                        "quality_flags": list(document.quality_flags),
                    }
                )
            selection.update(
                status="ok",
                selected_count=len(selected),
                ordered_document_ids_sha256=_hash_ids(
                    (row["document_id"] for row in selected), ordered=True
                ),
                selected_documents=selected,
                potential_v3_points=point_total,
                dense_float32_bytes_lower_bound=point_total * VECTOR_DIMENSION * 4,
                selected_dataset_revision=revision,
            )
        except (OSError, sqlite3.Error, ValueError) as error:
            selection.update(status="error", error_kind=type(error).__name__)
        except Exception as error:
            # Integrity/decompression failures are reported by type only.
            selection.update(status="error", error_kind=type(error).__name__)
    return {"local_store": local, "candidate_selection": selection}


def _git_proof(root: Path) -> dict[str, Any]:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
            text=True, timeout=10, check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=root, capture_output=True, timeout=10, check=True,
        ).stdout
        diff = subprocess.run(
            ["git", "diff", "--binary", "HEAD"], cwd=root,
            capture_output=True, timeout=30, check=False,
        ).stdout
        script_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        return {
            "head": head if len(head) == 40 else None,
            "git_dirty": bool(status),
            "status_sha256": hashlib.sha256(status).hexdigest(),
            "status_line_count": len(status.splitlines()),
            "git_diff_sha256": hashlib.sha256(diff).hexdigest(),
            "tracked_diff_sha256": hashlib.sha256(diff).hexdigest(),
            "audit_script_sha256": script_hash,
        }
    except (OSError, subprocess.SubprocessError):
        return {"head": None, "git_dirty": None, "status": "unavailable"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only online capacity audit; no embeddings or writes.")
    parser.add_argument("--output-dir", required=True, type=Path, help="A new directory; existing directories are refused.")
    parser.add_argument("--candidate-limit", type=int, default=MAX_CANDIDATES, help="Balanced candidates to inventory (1-100).")
    parser.add_argument("--read-online", action="store_true", help="Opt in to Qdrant GET/scroll and Supabase HEAD/GET requests.")
    return parser


def run_audit(arguments: argparse.Namespace, *, settings: Settings | None = None, root: Path | None = None) -> dict[str, Any]:
    if not 1 <= arguments.candidate_limit <= MAX_CANDIDATES:
        raise ValueError("candidate_limit_out_of_range")
    settings = settings or get_settings()
    root = (root or Path(__file__).resolve().parents[1]).resolve()
    output = arguments.output_dir.expanduser().resolve()
    if output.exists():
        raise FileExistsError("output_directory_exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    if arguments.read_online:
        online, online_ids = collect_online_capacity(settings)
        remote_status = online["document_id_consistency"].get("reason", online["document_id_consistency"].get("status"))
    else:
        online = {"status": "NOT RUN", "reason": "read_online_not_requested"}
        online_ids = None
        remote_status = "read_online_not_requested"
    candidates = _candidate_inventory(
        Path(settings.CONTENT_STORE_PATH), root=root, limit=arguments.candidate_limit,
        online_ids=online_ids, online_status=str(remote_status), revision=settings.DATASET_REVISION,
    )
    payload = {
        "schema_version": 1,
        "audit_id": datetime.now(UTC).strftime("online-capacity-%Y%m%dT%H%M%SZ"),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "git": _git_proof(root),
        "dataset": {
            "repository": settings.DATASET_REPOSITORY,
            "revision": settings.DATASET_REVISION,
            "expected_document_count": settings.EXPECTED_DOCUMENT_COUNT,
        },
        "command": {"read_online": arguments.read_online, "candidate_limit": arguments.candidate_limit},
        "online_capacity": online,
        "candidate_inventory": candidates,
        "capacity_gate": {
            "status": "blocked",
            "reasons": ["zero_cost_proof_missing", "qdrant_plan_quota_unknown", "supabase_database_size_unknown"],
            "candidate_ids_are_not_an_upload_or_reingestion_approval": True,
        },
        "side_effects": {
            "remote_methods": ["GET", "POST(points/scroll)", "HEAD"] if arguments.read_online else [],
            "supabase_key_scope": "publishable_read_key_only",
            "service_role_key_used": False,
            "provider_sdk_clients_created": False,
            "embeddings_created": False,
            "remote_writes_attempted": False,
        },
    }
    payload["git_dirty"] = payload["git"].get("git_dirty")
    payload["git_diff_sha256"] = payload["git"].get("git_diff_sha256")
    payload["source_revision"] = payload["git"].get("head")
    (output / "capacity_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_audit(args)
    except (FileExistsError, ValueError) as error:
        print(f"audit_not_run:{type(error).__name__}", file=sys.stderr)
        return 2
    print(json.dumps({
        "audit_id": result["audit_id"],
        "candidate_status": result["candidate_inventory"]["candidate_selection"]["status"],
        "read_online": result["command"]["read_online"],
        "remote_writes_attempted": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
