"""Dry-run-first incremental Vertex AI -> Qdrant migration lane."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections import Counter

from qdrant_client import AsyncQdrantClient

from app.config import get_settings, system_ssl_context
from app.ingestion.content_store import ContentStore
from app.ingestion.pinecone_store import FastSparseEncoder
from app.ingestion.vertex_qdrant_migration import (
    DEFAULT_MIGRATION_LEGAL_TYPES,
    MigrationCheckpoint,
    VertexQdrantContract,
    build_vertex_records,
    ensure_migration_collection,
    query_vertex_records,
    select_diverse_document_ids,
    upload_vertex_records,
)
from app.services.vertex_ai import get_vertex_provider


def _sha256(values: list[str | int]) -> str:
    payload = json.dumps(values, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-documents", type=int, default=12)
    parser.add_argument("--max-points", type=int, default=24)
    parser.add_argument("--max-chunks-per-document", type=int)
    parser.add_argument("--chunk-max-tokens", type=int, default=320)
    parser.add_argument("--chunk-overlap-tokens", type=int, default=32)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--progress-every",
        type=int,
        default=25,
        help="Print upload progress to stderr every N batches (default: 25).",
    )
    parser.add_argument(
        "--probe-query",
        help="Optional live hybrid/RRF query after upload; no answer generation.",
    )
    parser.add_argument(
        "--legal-type",
        action="append",
        dest="legal_types",
        help="Repeat to override the balanced default legal-type set.",
    )
    parser.add_argument("--allow-create", action="store_true")
    parser.add_argument("--allow-remote-write", action="store_true")
    return parser


async def _run(args: argparse.Namespace) -> dict[str, object]:
    settings = get_settings()
    if min(args.max_documents, args.max_points, args.batch_size, args.concurrency) <= 0:
        raise ValueError("document, point, batch, and concurrency limits must be positive")
    if args.progress_every <= 0:
        raise ValueError("progress interval must be positive")
    if args.allow_create and not args.allow_remote_write:
        raise PermissionError("--allow-create also requires --allow-remote-write")
    max_chunks = (
        args.max_chunks_per_document
        or settings.VERTEX_QDRANT_MAX_CHUNKS_PER_DOCUMENT
    )
    contract = VertexQdrantContract(
        collection_name=settings.VERTEX_QDRANT_COLLECTION_NAME,
        embedding_model=settings.VERTEX_EMBEDDING_MODEL,
        vector_size=settings.VERTEX_QDRANT_VECTOR_SIZE,
    )
    store = ContentStore(settings.CONTENT_STORE_PATH)
    legal_types = tuple(args.legal_types or DEFAULT_MIGRATION_LEGAL_TYPES)
    document_ids = select_diverse_document_ids(
        store,
        legal_types=legal_types,
        limit=args.max_documents,
    )
    print(
        f"[vertex-qdrant] selected_documents={len(document_ids)}",
        file=sys.stderr,
        flush=True,
    )
    records = build_vertex_records(
        store,
        document_ids,
        repository=settings.DATASET_REPOSITORY,
        revision=settings.DATASET_REVISION,
        max_tokens=args.chunk_max_tokens,
        overlap_tokens=args.chunk_overlap_tokens,
        max_chunks_per_document=max_chunks,
    )
    planned_records = records[: args.max_points]
    print(
        "[vertex-qdrant] "
        f"records_before_point_cap={len(records)} planned_points={len(planned_records)}",
        file=sys.stderr,
        flush=True,
    )
    base = {
        "mode": "remote" if args.allow_remote_write else "dry-run",
        "collection": contract.collection_name,
        "embedding_provider": "google_vertex_ai",
        "embedding_model": contract.embedding_model,
        "vector_size": contract.vector_size,
        "selected_documents": len(document_ids),
        "selected_legal_types": dict(
            sorted(Counter(record.legal_type for record in records).items())
        ),
        "records_before_point_cap": len(records),
        "planned_points": len(planned_records),
        "document_ids_sha256": _sha256(document_ids),
        "record_ids_sha256": _sha256(
            [record.record_id for record in planned_records]
        ),
        "estimated_dense_bytes": len(planned_records) * contract.vector_size * 4,
        "production_retrieval_changed": False,
    }
    if not args.allow_remote_write:
        return base

    client = AsyncQdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
        timeout=120,
        verify=system_ssl_context(),
        check_compatibility=False,
    )
    try:
        created = await ensure_migration_collection(
            client,
            contract,
            allow_create=args.allow_create,
        )
        sparse_encoder = FastSparseEncoder(
            average_document_length=store.build_report().average_sparse_document_length,
            max_nonzero_terms=settings.PINECONE_SPARSE_MAX_NONZERO,
        )
        provider = get_vertex_provider()
        progress_seen = 0

        def report_progress(progress: dict[str, int]) -> None:
            nonlocal progress_seen
            progress_seen += 1
            if progress_seen % args.progress_every != 0 and (
                progress["uploaded"] < progress["pending"]
            ):
                return
            print(
                "[vertex-qdrant] "
                f"uploaded={progress['uploaded']}/{progress['pending']} "
                f"skipped={progress['skipped']}",
                file=sys.stderr,
                flush=True,
            )

        report = await upload_vertex_records(
            planned_records,
            provider=provider,
            client=client,
            sparse_encoder=sparse_encoder,
            checkpoint=MigrationCheckpoint(
                settings.VERTEX_QDRANT_CHECKPOINT_PATH,
                contract,
            ),
            contract=contract,
            batch_size=args.batch_size,
            concurrency=args.concurrency,
            allow_remote_write=True,
            progress_callback=report_progress,
        )
        info = await client.get_collection(contract.collection_name)
        base.update(
            {
                "collection_created": created,
                "upload": report,
                "remote_points": info.points_count,
                "remote_status": str(info.status),
            }
        )
        if args.probe_query:
            hits = await query_vertex_records(
                args.probe_query,
                provider=provider,
                client=client,
                sparse_encoder=sparse_encoder,
                contract=contract,
                limit=5,
            )
            base["probe"] = {
                "hit_count": len(hits),
                "hits": [
                    {
                        "id": str(hit.id),
                        "score": hit.score,
                        "document_id": (hit.payload or {}).get("document_id"),
                        "citation": (hit.payload or {}).get("citation"),
                    }
                    for hit in hits
                ],
            }
        return base
    finally:
        await client.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    result = asyncio.run(_run(_parser().parse_args()))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
