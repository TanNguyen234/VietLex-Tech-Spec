from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.ingestion.content_store import ContentStore
from app.ingestion.supabase_full_doc import (
    SupabaseFullDocUploader,
    full_document_table_sql,
    report_to_json,
    upload_full_documents,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upload bounded full legal documents from local SQLite to Supabase REST."
    )
    parser.add_argument("--max-documents", type=int, default=50_000)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--table", default="legal_documents")
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("data/migration/supabase-full-doc-checkpoint.json"),
    )
    parser.add_argument(
        "--print-schema",
        action="store_true",
        help="Print required Supabase SQL schema and exit without uploading.",
    )
    parser.add_argument(
        "--check-connection",
        action="store_true",
        help="Check Supabase connectivity and table presence without uploading.",
    )
    parser.add_argument(
        "--allow-remote-write",
        action="store_true",
        help="Required confirmation before document upserts.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.print_schema:
        print(full_document_table_sql(args.table))
        return 0

    settings = get_settings()
    url = (settings.SUPABASE_URL or "").strip()
    key = (settings.SUPABASE_SERVICE_ROLE_KEY or "").strip()
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required in .env."
        )

    uploader = SupabaseFullDocUploader(
        url=url,
        service_role_key=key,
        table=args.table,
    )

    if args.check_connection:
        check = uploader.check_connection()
        print(report_to_json(check))
        return 0 if check.get("ok") else 1

    if not args.allow_remote_write:
        raise PermissionError("--allow-remote-write is required for Supabase upserts")

    report = upload_full_documents(
        store=ContentStore(settings.CONTENT_STORE_PATH),
        uploader=uploader,
        dataset_revision=settings.DATASET_REVISION,
        max_documents=args.max_documents,
        batch_size=args.batch_size,
        checkpoint_path=args.checkpoint,
    )
    print(report_to_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
