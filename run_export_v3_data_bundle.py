from __future__ import annotations

import argparse
import json
from pathlib import Path

from qdrant_client import QdrantClient

from app.config import get_settings, system_ssl_context
from app.ingestion.content_store import ContentStore
from app.ingestion.legal_fts import LegalFtsIndex
from app.ingestion.v3_data_bundle import (
    audit_qdrant_document_ids,
    document_ids_sha256,
    export_content_store_subset,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit and build the exact local full-document bundle for Qdrant v3."
    )
    parser.add_argument("--audit-qdrant", action="store_true")
    parser.add_argument("--allow-live-read", action="store_true")
    parser.add_argument("--build", action="store_true")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/v3/document_set.json"),
    )
    parser.add_argument(
        "--content-output",
        type=Path,
        default=Path("data/v3/content_store.sqlite3"),
    )
    parser.add_argument(
        "--fts-output",
        type=Path,
        default=Path("data/v3/legal_fts.sqlite3"),
    )
    return parser


def _write_new_json(path: Path, payload: dict) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing manifest: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    args = build_parser().parse_args()
    if not args.audit_qdrant and not args.build:
        raise ValueError("select --audit-qdrant and/or --build")
    settings = get_settings()
    result: dict[str, object] = {}
    if args.audit_qdrant:
        if not args.allow_live_read:
            raise PermissionError("--allow-live-read is required for Qdrant audit")
        client = QdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY,
            timeout=60,
            verify=system_ssl_context(),
            check_compatibility=False,
        )
        try:
            manifest = audit_qdrant_document_ids(
                client,
                settings.VERTEX_QDRANT_COLLECTION_NAME,
            )
        finally:
            client.close()
        manifest.update(
            {
                "dataset_repository": settings.DATASET_REPOSITORY,
                "dataset_revision": settings.DATASET_REVISION,
                "dataset_license": "CC-BY-4.0",
            }
        )
        _write_new_json(args.manifest, manifest)
        result["audit"] = {
            key: value
            for key, value in manifest.items()
            if key != "document_ids"
        }

    if args.build:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        document_ids = [int(value) for value in manifest["document_ids"]]
        if manifest.get("document_ids_sha256") != document_ids_sha256(
            document_ids
        ):
            raise ValueError("document manifest SHA-256 mismatch")
        if int(manifest.get("document_count", -1)) != len(document_ids):
            raise ValueError("document manifest count mismatch")
        bundle = export_content_store_subset(
            source_path=settings.CONTENT_STORE_PATH,
            output_path=args.content_output,
            document_ids=document_ids,
            collection=str(manifest["collection"]),
            point_count=int(manifest["point_count"]),
            dataset_revision=str(manifest["dataset_revision"]),
        )
        subset_store = ContentStore(args.content_output)
        fts = LegalFtsIndex(
            store=subset_store,
            path=args.fts_output,
            dataset_revision=str(manifest["dataset_revision"]),
        )
        fts.ensure_built(batch_size=256)
        if not fts.is_ready():
            raise RuntimeError("v3 bundle FTS verification failed")
        bundle["fts_output"] = str(args.fts_output)
        bundle["fts_bytes"] = args.fts_output.stat().st_size
        result["build"] = bundle

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
