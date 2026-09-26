"""Copy verified Supabase legal full text to a payload-only Qdrant phrase index.

No embedding or vector ingestion occurs. The source document remains Supabase;
Qdrant is a replaceable search index keyed by the same document ID and SHA-256.
"""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import time

import httpx

from app.config import get_settings, system_ssl_context


COLLECTION = "vietlex-legal-body-search-v1"
FIELDS = "document_id,content,content_sha256,legal_type,issuing_authority,issuance_date"
INDEXES = {
    "body": {
        "type": "text", "tokenizer": "word", "min_token_len": 1,
        "max_token_len": 128, "lowercase": True, "ascii_folding": True,
        "phrase_matching": True, "on_disk": True,
    },
    "legal_type": {"type": "keyword", "on_disk": True},
    "issuing_authority": {"type": "keyword", "on_disk": True},
    "issuance_date": {"type": "datetime", "on_disk": True},
}


def point_from_source(row: dict) -> dict:
    document_id = row.get("document_id")
    content = row.get("content")
    digest = row.get("content_sha256")
    if type(document_id) is not int or document_id <= 0 or not isinstance(content, str) or not content:
        raise ValueError("invalid_source_document")
    if not isinstance(digest, str) or hashlib.sha256(content.encode("utf-8")).hexdigest() != digest:
        raise ValueError("source_hash_mismatch")
    for field in ("legal_type", "issuing_authority", "issuance_date"):
        if not isinstance(row.get(field), str) or not row[field]:
            raise ValueError("invalid_source_metadata")
    if date.fromisoformat(row["issuance_date"]).isoformat() != row["issuance_date"]:
        raise ValueError("invalid_source_date")
    return {
        "id": document_id,
        "vector": {},
        "payload": {
            "document_id": document_id,
            "body": content,
            "content_sha256": digest,
            "legal_type": row["legal_type"],
            "issuing_authority": row["issuing_authority"],
            "issuance_date": row["issuance_date"],
        },
    }


def _request(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    for attempt in range(4):
        try:
            response = client.request(method, url, **kwargs)
            if response.status_code not in (429, 500, 502, 503, 504):
                response.raise_for_status()
                return response
        except httpx.TransportError:
            if attempt == 3:
                raise
        if attempt == 3:
            response.raise_for_status()
        time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def _source_page(client: httpx.Client, endpoint: str, headers: dict, after: int, *, full: bool) -> list[dict]:
    fields = FIELDS if full else "document_id,content_sha256"
    response = _request(client, "GET", endpoint, headers=headers, params={
        "select": fields,
        "document_id": f"gt.{after}",
        "order": "document_id.asc",
        "limit": "100",
    })
    rows = response.json()
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("invalid_source_page")
    previous = after
    for row in rows:
        if not isinstance(row, dict) or type(row.get("document_id")) is not int or row["document_id"] <= previous:
            raise ValueError("invalid_source_order")
        previous = row["document_id"]
    return rows


def _source_count(client: httpx.Client, endpoint: str, headers: dict) -> int:
    response = _request(client, "HEAD", endpoint, headers={**headers, "Prefer": "count=exact"},
                        params={"select": "document_id", "limit": "0"})
    count = response.headers.get("content-range", "").split("/")[-1]
    if not count.isdecimal() or int(count) <= 0:
        raise ValueError("invalid_source_count")
    return int(count)


def _collection(client: httpx.Client, root: str, headers: dict) -> dict:
    response = _request(client, "GET", root + "/collections/" + COLLECTION, headers=headers)
    value = response.json().get("result")
    if not isinstance(value, dict) or value.get("config", {}).get("params", {}).get("vectors") != {}:
        raise ValueError("unexpected_collection_contract")
    return value


def _save_checkpoint(path: Path, *, last_id: int, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({"collection": COLLECTION, "last_id": last_id, "count": count}), encoding="utf-8")
    temporary.replace(path)


def _load_checkpoint(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("collection") != COLLECTION or type(value.get("last_id")) is not int or type(value.get("count")) is not int:
        raise ValueError("invalid_checkpoint")
    return value["last_id"], value["count"]


def build(client: httpx.Client, *, supabase_url: str, supabase_key: str,
          qdrant_url: str, qdrant_key: str, checkpoint: Path) -> dict:
    source = supabase_url.rstrip("/") + "/rest/v1/legal_documents"
    target = qdrant_url.rstrip("/")
    source_headers = {"apikey": supabase_key, "authorization": "Bearer " + supabase_key}
    target_headers = {"api-key": qdrant_key}
    expected = _source_count(client, source, source_headers)
    collection = _collection(client, target, target_headers)
    for field, schema in INDEXES.items():
        existing = collection.get("payload_schema", {}).get(field)
        if existing is None:
            _request(client, "PUT", target + "/collections/" + COLLECTION + "/index?wait=true",
                     headers=target_headers, json={"field_name": field, "field_schema": schema})
        elif any(existing.get("params", {}).get(key) != value for key, value in schema.items()):
            raise ValueError("unexpected_index_contract:" + field)
    last_id, count = _load_checkpoint(checkpoint)
    while True:
        rows = _source_page(client, source, source_headers, last_id, full=True)
        if not rows:
            break
        points = [point_from_source(row) for row in rows]
        upsert = _request(client, "PUT", target + "/collections/" + COLLECTION + "/points?wait=true",
                          headers=target_headers, json={"points": points})
        if upsert.json().get("result", {}).get("status") != "completed":
            raise ValueError("qdrant_upsert_incomplete")
        last_id = points[-1]["id"]
        count += len(points)
        _save_checkpoint(checkpoint, last_id=last_id, count=count)
        if count % 1000 == 0 or count == expected:
            index_bytes = _request(client, "GET", target + "/collections/" + COLLECTION + "/memory",
                                   headers=target_headers).json()["result"]["total"]["disk_bytes"]
            vector_bytes = _request(client, "GET", target + "/collections/" + get_settings().VERTEX_QDRANT_COLLECTION_NAME + "/memory",
                                    headers=target_headers).json()["result"]["total"]["disk_bytes"]
            if index_bytes + vector_bytes >= 3_200_000_000:
                raise ValueError("qdrant_disk_safety_limit")
            print(json.dumps({"stage": "ingest", "count": count, "expected": expected, "last_id": last_id}))
        if count > expected:
            raise ValueError("source_count_changed")
    if count != expected:
        raise ValueError("source_count_changed")
    return {"expected": expected, "ingested": count, "last_id": last_id}


def verify(client: httpx.Client, *, supabase_url: str, supabase_key: str,
           qdrant_url: str, qdrant_key: str) -> dict:
    source = supabase_url.rstrip("/") + "/rest/v1/legal_documents"
    target = qdrant_url.rstrip("/") + "/collections/" + COLLECTION
    source_headers = {"apikey": supabase_key, "authorization": "Bearer " + supabase_key}
    target_headers = {"api-key": qdrant_key}
    expected = _source_count(client, source, source_headers)
    hashes = {}
    last_id = 0
    while True:
        rows = _source_page(client, source, source_headers, last_id, full=False)
        if not rows:
            break
        for row in rows:
            hashes[row["document_id"]] = row["content_sha256"]
        last_id = rows[-1]["document_id"]
    if len(hashes) != expected:
        raise ValueError("source_count_changed")
    seen = set()
    offset = None
    while True:
        payload = {"limit": 100, "with_payload": ["document_id", "body", "content_sha256"],
                   "with_vector": False}
        if offset is not None:
            payload["offset"] = offset
        response = _request(client, "POST", target + "/points/scroll", headers=target_headers, json=payload)
        result = response.json().get("result", {})
        points = result.get("points", [])
        for point in points:
            document_id = point.get("id")
            fields = point.get("payload", {})
            body = fields.get("body")
            if (type(document_id) is not int or document_id in seen or fields.get("document_id") != document_id
                    or not isinstance(body, str) or hashes.get(document_id) != fields.get("content_sha256")
                    or hashlib.sha256(body.encode("utf-8")).hexdigest() != hashes.get(document_id)):
                raise ValueError("destination_mismatch")
            seen.add(document_id)
        offset = result.get("next_page_offset")
        if offset is None:
            break
    collection = _collection(client, qdrant_url.rstrip("/"), target_headers)
    body_index = collection.get("payload_schema", {}).get("body", {})
    if len(seen) != expected or collection.get("points_count") != expected or body_index.get("points") != expected:
        raise ValueError("index_incomplete")
    memory = _request(client, "GET", target + "/memory", headers=target_headers).json()["result"]
    return {"verified_documents": len(seen), "indexed_points": body_index["points"],
            "collection_disk_bytes": memory["total"]["disk_bytes"],
            "body_index_disk_bytes": next((item["usage"]["disk_bytes"] for item in memory["payload_index"]
                                           if item["name"] == "body"), None)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=Path("data/ingestion/full_doc_text_index_checkpoint.json"))
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    with httpx.Client(verify=system_ssl_context(), timeout=60) as client:
        kwargs = {"supabase_url": settings.SUPABASE_URL, "supabase_key": settings.SUPABASE_PUBLISHABLE_KEY,
                  "qdrant_url": settings.QDRANT_URL, "qdrant_key": settings.QDRANT_API_KEY}
        if not args.verify_only:
            print(json.dumps(build(client, checkpoint=args.checkpoint, **kwargs)))
        print(json.dumps(verify(client, **kwargs)))


if __name__ == "__main__":
    main()
