from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import httpx

from app.config import system_ssl_context
from app.ingestion.content_store import ContentStore, StoredDocument


@dataclass(frozen=True)
class SupabaseUpsertReport:
    uploaded_rows: int


class SupabaseUploadError(RuntimeError):
    """Raised when Supabase rejects the full-document upload."""


def build_supabase_row(
    document: StoredDocument,
    *,
    dataset_revision: str,
) -> dict[str, Any]:
    metadata = document.metadata
    return {
        "document_id": metadata.document_id,
        "document_number": metadata.document_number,
        "title": metadata.title,
        "source_url": metadata.source_url,
        "legal_type": metadata.legal_type,
        "legal_sectors": metadata.legal_sectors,
        "issuing_authority": metadata.issuing_authority,
        "issuance_date": metadata.issuance_date,
        "content": document.content,
        "content_sha256": document.content_sha256,
        "content_store_key": document.content_store_key,
        "quality_flags": list(document.quality_flags),
        "dataset_revision": dataset_revision,
    }


class SupabaseFullDocUploader:
    def __init__(
        self,
        *,
        url: str,
        service_role_key: str,
        table: str = "legal_documents",
        client: httpx.Client | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        if not service_role_key.startswith("sb_secret_"):
            raise ValueError("a Supabase service-role key is required for backend writes")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table) is None:
            raise ValueError("table must be a safe SQL identifier")
        self._service_role_key = service_role_key
        self._table = table
        self._client = client or httpx.Client(
            verify=system_ssl_context(),
            timeout=httpx.Timeout(60.0),
        )

    def check_connection(self) -> dict[str, Any]:
        """Verify endpoint connectivity and table accessibility."""
        try:
            response = self._client.get(
                f"{self._url}/rest/v1/{self._table}",
                params={"select": "document_id", "limit": "1"},
                headers={
                    "apikey": self._service_role_key,
                    "authorization": f"Bearer {self._service_role_key}",
                },
            )
        except Exception as error:
            return {
                "ok": False,
                "status_code": None,
                "error": f"Network / connection error: {error}",
            }
        if response.status_code == 200:
            return {
                "ok": True,
                "status_code": 200,
                "table": self._table,
                "message": "Connection and table verified successfully.",
            }
        if response.status_code == 404 and "PGRST205" in response.text:
            return {
                "ok": False,
                "status_code": 404,
                "error": (
                    f"Table '{self._table}' does not exist on Supabase. "
                    "Please run 'python run_supabase_full_doc_upload.py --print-schema' "
                    "and execute the SQL script in Supabase SQL Editor."
                ),
            }
        return {
            "ok": False,
            "status_code": response.status_code,
            "error": f"Supabase responded with status {response.status_code}: {response.text[:300]}",
        }

    def upsert_rows(self, rows: list[dict[str, Any]]) -> SupabaseUpsertReport:
        if not rows:
            return SupabaseUpsertReport(uploaded_rows=0)
        response = self._client.post(
            f"{self._url}/rest/v1/{self._table}",
            params={"on_conflict": "document_id"},
            headers={
                "apikey": self._service_role_key,
                "authorization": f"Bearer {self._service_role_key}",
                "content-type": "application/json",
                "prefer": "resolution=merge-duplicates,return=minimal",
            },
            json=rows,
        )
        if response.status_code not in {200, 201, 204}:
            if response.status_code == 404 and "PGRST205" in response.text:
                raise SupabaseUploadError(
                    f"Table '{self._table}' does not exist on Supabase. "
                    "Please run 'python run_supabase_full_doc_upload.py --print-schema' "
                    "and execute the SQL schema in Supabase SQL Editor to create it."
                )
            raise SupabaseUploadError(
                "Supabase upsert failed "
                f"status={response.status_code}: {response.text[:500]}"
            )
        return SupabaseUpsertReport(uploaded_rows=len(rows))


def load_checkpoint(path: Path) -> dict[str, int | str | None]:
    if not path.exists():
        return {
            "last_document_id": 0,
            "uploaded_rows": 0,
            "selection_sha256": None,
        }
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        "last_document_id": int(raw.get("last_document_id", 0)),
        "uploaded_rows": int(raw.get("uploaded_rows", 0)),
        "selection_sha256": raw.get("selection_sha256"),
    }


def save_checkpoint(
    path: Path,
    *,
    last_document_id: int,
    uploaded_rows: int,
    selection_sha256: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {
                "last_document_id": last_document_id,
                "uploaded_rows": uploaded_rows,
                **(
                    {"selection_sha256": selection_sha256}
                    if selection_sha256 is not None
                    else {}
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def _ordered_documents(
    store: ContentStore,
    document_ids: Iterable[int],
) -> list[StoredDocument]:
    ids = list(document_ids)
    by_id = store.get_many(ids)
    return [by_id[document_id] for document_id in ids if document_id in by_id]


def upload_full_documents(
    *,
    store: ContentStore,
    uploader: SupabaseFullDocUploader,
    dataset_revision: str,
    max_documents: int,
    batch_size: int,
    checkpoint_path: Path,
    document_ids: Iterable[int] | None = None,
) -> dict[str, int | str]:
    if max_documents <= 0 or batch_size <= 0:
        raise ValueError("max_documents and batch_size must be positive")

    checkpoint_exists = checkpoint_path.exists()
    checkpoint = load_checkpoint(checkpoint_path)
    last_document_id = int(checkpoint["last_document_id"])
    uploaded_total = int(checkpoint["uploaded_rows"])
    selected_ids: list[int] | None = None
    selection_sha256: str | None = None
    if document_ids is not None:
        selected_ids = [int(document_id) for document_id in document_ids]
        if (
            selected_ids != sorted(set(selected_ids))
            or any(document_id <= 0 for document_id in selected_ids)
        ):
            raise ValueError("document ID selection must be positive, unique, and sorted")
        selected_ids = selected_ids[:max_documents]
        selection_sha256 = hashlib.sha256(
            json.dumps(selected_ids, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        recorded_selection = checkpoint.get("selection_sha256")
        if checkpoint_exists and recorded_selection != selection_sha256:
            raise ValueError("checkpoint belongs to a different document selection")
    attempted = 0

    while attempted < max_documents:
        limit = min(batch_size, max_documents - attempted)
        if selected_ids is None:
            batch_ids = store.iter_document_ids(
                after_id=last_document_id,
                limit=limit,
            )
        else:
            batch_ids = [
                document_id
                for document_id in selected_ids
                if document_id > last_document_id
            ][:limit]
        if not batch_ids:
            break
        documents = _ordered_documents(store, batch_ids)
        rows = [
            build_supabase_row(document, dataset_revision=dataset_revision)
            for document in documents
        ]
        report = uploader.upsert_rows(rows)
        attempted += len(rows)
        uploaded_total += report.uploaded_rows
        last_document_id = max(batch_ids)
        save_checkpoint(
            checkpoint_path,
            last_document_id=last_document_id,
            uploaded_rows=uploaded_total,
            selection_sha256=selection_sha256,
        )

    return {
        "mode": "supabase-full-doc-upload",
        "attempted_rows": attempted,
        "uploaded_rows": uploaded_total - checkpoint["uploaded_rows"],
        "total_uploaded_rows_with_checkpoint": uploaded_total,
        "last_document_id": last_document_id,
        **(
            {
                "selected_document_count": len(selected_ids),
                "selection_sha256": selection_sha256,
            }
            if selected_ids is not None and selection_sha256 is not None
            else {}
        ),
    }


def full_document_table_sql(table: str = "legal_documents") -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table) is None:
        raise ValueError("table must be a safe SQL identifier")
    return f"""create table if not exists public.{table} (
  document_id bigint primary key,
  document_number text not null,
  title text not null,
  source_url text not null,
  legal_type text not null,
  legal_sectors text not null,
  issuing_authority text not null,
  issuance_date text,
  content text not null,
  content_sha256 text not null,
  content_store_key text not null,
  quality_flags jsonb not null default '[]'::jsonb,
  dataset_revision text not null,
  uploaded_at timestamptz not null default now()
);
create index if not exists {table}_document_number_idx
  on public.{table} (document_number);
create index if not exists {table}_content_sha256_idx
  on public.{table} (content_sha256);
alter table public.{table} enable row level security;
"""


def report_to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)
