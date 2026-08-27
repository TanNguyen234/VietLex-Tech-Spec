from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx

from app.ingestion.content_store import StoredDocument
from app.ingestion.legal_text import DocumentMetadata


def _document(document_id: int) -> StoredDocument:
    content = f"Dieu 1. Noi dung van ban {document_id}."
    return StoredDocument(
        metadata=DocumentMetadata(
            document_id=document_id,
            document_number=f"{document_id}/2026/QH15",
            title=f"Luat thu nghiem {document_id}",
            source_url=f"https://example.test/{document_id}",
            legal_type="Luat",
            legal_sectors="Thu nghiem",
            issuing_authority="Quoc hoi",
            issuance_date="2026-01-01",
        ),
        content=content,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        content_store_key=str(document_id),
        quality_flags=("synthetic",),
    )


def test_build_supabase_row_preserves_full_document_body() -> None:
    from app.ingestion.supabase_full_doc import build_supabase_row

    row = build_supabase_row(_document(12), dataset_revision="rev")

    assert row["document_id"] == 12
    assert row["document_number"] == "12/2026/QH15"
    assert row["content"] == "Dieu 1. Noi dung van ban 12."
    assert row["content_sha256"] == hashlib.sha256(
        row["content"].encode("utf-8")
    ).hexdigest()
    assert row["dataset_revision"] == "rev"
    assert row["quality_flags"] == ["synthetic"]


def test_uploader_uses_server_side_supabase_rest_upsert_headers(tmp_path: Path) -> None:
    from app.ingestion.supabase_full_doc import (
        SupabaseFullDocUploader,
        build_supabase_row,
    )

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            201,
            headers={"content-range": "0-1/*"},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    uploader = SupabaseFullDocUploader(
        url="https://example.supabase.co",
        service_role_key="sb_secret_test",
        table="legal_documents",
        client=client,
    )

    report = uploader.upsert_rows(
        [build_supabase_row(_document(1), dataset_revision="rev") for _ in range(2)]
    )

    assert report.uploaded_rows == 2
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == (
        "https://example.supabase.co/rest/v1/legal_documents"
        "?on_conflict=document_id"
    )
    assert request.headers["apikey"] == "sb_secret_test"
    assert request.headers["authorization"] == "Bearer sb_secret_test"
    assert request.headers["prefer"] == "resolution=merge-duplicates,return=minimal"


def test_connection_check_reports_missing_supabase_table() -> None:
    from app.ingestion.supabase_full_doc import SupabaseFullDocUploader

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            text='{"code":"PGRST205"}',
            request=request,
        )

    uploader = SupabaseFullDocUploader(
        url="https://example.supabase.co",
        service_role_key="sb_secret_test",
        table="legal_documents",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    report = uploader.check_connection()

    assert report["ok"] is False
    assert report["status_code"] == 404
    assert "does not exist" in report["error"]


def test_uploader_rejects_publishable_key() -> None:
    from app.ingestion.supabase_full_doc import SupabaseFullDocUploader

    try:
        SupabaseFullDocUploader(
            url="https://example.supabase.co",
            service_role_key="sb_publishable_example",
        )
    except ValueError as error:
        assert "service-role" in str(error)
    else:
        raise AssertionError("publishable key must not authorize backend writes")


def test_schema_enables_rls_without_anon_write_policy() -> None:
    from app.ingestion.supabase_full_doc import full_document_table_sql

    sql = full_document_table_sql()

    assert "enable row level security" in sql.casefold()
    assert "create policy" not in sql.casefold()


def test_schema_rejects_unsafe_table_identifier() -> None:
    from app.ingestion.supabase_full_doc import full_document_table_sql

    try:
        full_document_table_sql("legal_documents; drop table users")
    except ValueError as error:
        assert "identifier" in str(error)
    else:
        raise AssertionError("unsafe SQL identifier must be rejected")


def test_upload_documents_resumes_after_checkpoint(tmp_path: Path) -> None:
    from app.ingestion.supabase_full_doc import upload_full_documents

    class Store:
        def __init__(self) -> None:
            self.get_calls: list[list[int]] = []

        def iter_document_ids(self, *, after_id: int, limit: int) -> list[int]:
            assert limit == 2
            values = [1, 2, 3, 4]
            return [value for value in values if value > after_id][:limit]

        def get_many(self, document_ids: list[int]):
            self.get_calls.append(document_ids)
            return {document_id: _document(document_id) for document_id in document_ids}

    class Uploader:
        def __init__(self) -> None:
            self.batches: list[list[int]] = []

        def upsert_rows(self, rows):
            self.batches.append([row["document_id"] for row in rows])
            return SimpleNamespace(uploaded_rows=len(rows))

    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(
        json.dumps({"last_document_id": 2, "uploaded_rows": 2}),
        encoding="utf-8",
    )

    uploader = Uploader()
    report = upload_full_documents(
        store=Store(),
        uploader=uploader,
        dataset_revision="rev",
        max_documents=2,
        batch_size=2,
        checkpoint_path=checkpoint,
    )

    assert report["attempted_rows"] == 2
    assert report["uploaded_rows"] == 2
    assert report["last_document_id"] == 4
    assert uploader.batches == [[3, 4]]
    assert json.loads(checkpoint.read_text(encoding="utf-8")) == {
        "last_document_id": 4,
        "uploaded_rows": 4,
    }
