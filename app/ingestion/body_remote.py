"""Prepare bounded, immutable passage batches; upload only by explicit CLI action."""

import argparse
import hashlib
import json
from pathlib import Path
import uuid
import httpx
from app.services.body_search import passage_rows
from app.services.document_structure import document_sections


def prepare_body_bundle(folder, documents, *, max_documents):
    if not 1 <= max_documents <= 15000:
        raise ValueError("invalid_document_limit")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    batch = str(uuid.uuid4())
    count = 0
    seen = set()
    source_hash = hashlib.sha256()
    file_hash = hashlib.sha256()
    with (folder / "passages.jsonl").open("wb") as output:
        for document in documents:
            identifier = document.metadata.document_id
            if identifier in seen or len(seen) >= max_documents:
                raise ValueError("duplicate_or_document_limit")
            digest = hashlib.sha256(document.content.encode()).hexdigest()
            if digest != document.content_sha256:
                raise ValueError("source_hash_mismatch")
            seen.add(identifier)
            source_hash.update(f"{identifier}:{digest}\n".encode())
            offsets = {}
            position = 0
            for section in document_sections(document.content):
                offsets[section["id"]] = position
                position += len(section["text"])
            if position != len(document.content):
                raise ValueError("source_sections_mismatch")
            for row in passage_rows(document):
                offset = offsets[row["section_id"]] + row["offset"]
                if document.content[offset : offset + len(row["text"])] != row["text"]:
                    raise ValueError("source_offset_mismatch")
                record = dict(
                    batch_id=batch,
                    document_id=identifier,
                    section_id=row["section_id"],
                    section_title=row["section_title"],
                    document_offset=offset,
                    content_sha256=digest,
                    body=row["text"],
                )
                raw = (
                    json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
                ).encode()
                output.write(raw)
                file_hash.update(raw)
                count += 1
    if not seen or not count:
        raise ValueError("empty_body_bundle")
    manifest = dict(
        batch_id=batch,
        expected_documents=len(seen),
        expected_passages=count,
        source_sha256=source_hash.hexdigest(),
        passages_sha256=file_hash.hexdigest(),
    )
    (folder / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def upload_body_bundle(
    folder, *, url, service_key, client=None, resume=False, publish=False
):
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256()
    count = 0
    documents = set()
    with (folder / "passages.jsonl").open("rb") as source:
        for raw in source:
            digest.update(raw)
            row = json.loads(raw)
            if row.get("batch_id") != manifest["batch_id"]:
                raise ValueError("bundle_batch_mismatch")
            documents.add(row["document_id"])
            count += 1
    if (
        digest.hexdigest() != manifest["passages_sha256"]
        or count != manifest["expected_passages"]
        or len(documents) != manifest["expected_documents"]
        or not 1 <= len(documents) <= 15000
    ):
        raise ValueError("bundle_integrity_mismatch")
    from app.config import system_ssl_context

    owned = client is None
    client = client or httpx.Client(verify=system_ssl_context(), timeout=30)
    client.headers.update(
        {"apikey": service_key, "authorization": "Bearer " + service_key}
    )
    endpoint = url.rstrip("/") + "/rest/v1/"
    record = {
        key: manifest[key]
        for key in (
            "batch_id",
            "expected_documents",
            "expected_passages",
            "source_sha256",
        )
    }
    try:
        if resume:
            response = client.get(
                endpoint + "legal_body_runs",
                params={
                    "batch_id": "eq." + manifest["batch_id"],
                    "select": "batch_id,expected_documents,expected_passages,source_sha256",
                },
            )
            response.raise_for_status()
            if response.json() != [record]:
                raise ValueError("remote_batch_mismatch")
        else:
            response = client.post(endpoint + "legal_body_runs", json=record)
            response.raise_for_status()

        def send(rows):
            response = client.post(
                endpoint + "legal_body_passages",
                params={"on_conflict": "batch_id,document_id,document_offset"},
                headers={"Prefer": "resolution=ignore-duplicates,return=minimal"},
                json=rows,
            )
            response.raise_for_status()

        with (folder / "passages.jsonl").open(encoding="utf-8") as source:
            rows = []
            for line in source:
                rows.append(json.loads(line))
                if len(rows) == 100:
                    send(rows)
                    rows = []
            if rows:
                send(rows)
        if publish:
            response = client.post(
                endpoint + "rpc/publish_legal_body",
                json={"batch": manifest["batch_id"]},
            )
            response.raise_for_status()
            response = client.post(endpoint + "rpc/legal_body_coverage", json={})
            response.raise_for_status()
            if (response.json() or {}).get("batch_id") != manifest["batch_id"]:
                raise ValueError("published_batch_not_active")
        return dict(
            batch_id=manifest["batch_id"], attempted_passages=count, published=publish
        )
    finally:
        if owned:
            client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--store", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--limit", type=int, required=True)
    upload = sub.add_parser("upload")
    upload.add_argument("--bundle", type=Path, required=True)
    upload.add_argument("--resume", action="store_true")
    upload.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        from app.ingestion.content_store import ContentStore

        if not args.store.is_file() or not 1 <= args.limit <= 15000:
            parser.error("existing store and --limit 1..15000 required")
        store = ContentStore(args.store)

        def documents():
            after, total = -1, 0
            while total < args.limit:
                ids = store.iter_document_ids(
                    after_id=after, limit=min(50, args.limit - total)
                )
                if not ids:
                    break
                values = store.get_many(ids)
                for identifier in ids:
                    yield values[identifier]
                after, total = ids[-1], total + len(ids)

        result = prepare_body_bundle(args.output, documents(), max_documents=args.limit)
    else:
        from app.config import get_settings

        settings = get_settings()
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            parser.error("Supabase URL/service-role key required in server settings")
        result = upload_body_bundle(
            args.bundle,
            url=settings.SUPABASE_URL,
            service_key=settings.SUPABASE_SERVICE_ROLE_KEY,
            resume=args.resume,
            publish=args.publish,
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
