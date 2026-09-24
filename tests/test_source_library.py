from datetime import datetime, timezone
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_library_counts_readable_unique_pages_without_merging_versions():
    from app.services.workspace_presenter import source_library

    def read(identifier, digest, pages):
        return {
            "analysis_id": identifier,
            "kind": "trusted_sources",
            "result": {
                "sources": [
                    {
                        "url": "https://vanban.chinhphu.vn/?docid=1",
                        "title": "Law",
                        "document_sha256": digest,
                        "page_count": 4,
                        "pages": pages,
                    }
                ]
            },
        }

    result = source_library(
        {
            "analyses": [
                read("a", "v1", [{"page": 1, "text": "One"}, {"page": 2, "text": ""}]),
                read(
                    "b",
                    "v1",
                    [{"page": 1, "text": "One"}, {"page": 3, "text": "Three"}],
                ),
                read("c", "v2", [{"page": 4, "text": "Four"}]),
            ]
        }
    )
    assert len(result) == 2
    old = next(row for row in result if row["document_sha256"] == "v1")
    assert old["read_pages"] == [1, 3]
    assert old["missing_pages"] == [2, 4]
    assert old["readable_count"] == 2
    assert old["unread_pages"] == [4]
    assert old["unreadable_pages"] == [2]
    assert len(old["reads"]) == 2


def test_reopen_source_is_owned_and_never_refetches(monkeypatch):
    import app.api.trusted_source_routes as routes

    app = FastAPI()
    app.include_router(routes.router)
    routes.limiter._storage.reset()
    app.dependency_overrides[routes.optional_user] = lambda: {"_id": "owner"}
    saved = {
        "analysis_id": "a",
        "kind": "trusted_sources",
        "status": "ok",
        "result": {
            "sources": [
                {
                    "url": "https://vanban.chinhphu.vn/a",
                    "title": "Saved source",
                    "text": "Exact saved body",
                }
            ]
        },
    }
    saved["created_at"] = datetime.now(timezone.utc)
    owned = AsyncMock(
        return_value=({"workspace_id": "w", "analyses": [saved]}, "c", "owner")
    )
    monkeypatch.setattr(routes, "_owned_workspace", owned)
    reader = AsyncMock()
    monkeypatch.setattr(routes, "read_source", reader)
    response = TestClient(app).get("/workspaces/w/sources/a")
    assert response.status_code == 200
    assert "Exact saved body" in response.text
    assert response.headers["cache-control"] == "no-store"
    reader.assert_not_awaited()
    owned.assert_awaited_once()
    assert TestClient(app).get("/workspaces/w/sources/missing").status_code == 404



def test_pin_accepts_browser_line_endings_but_preserves_saved_quote(monkeypatch):
    import app.api.trusted_source_routes as routes
    from app.services.trusted_source_reader import official_evidence_id

    app = FastAPI()
    app.include_router(routes.router)
    routes.limiter._storage.reset()
    app.dependency_overrides[routes.optional_user] = lambda: {"_id": "owner"}
    app.dependency_overrides[routes.verify_csrf] = lambda: "csrf"
    source = {"url": "https://vanban.chinhphu.vn/a", "title": "Source",
              "text": "Before\nExact\nquote\nAfter", "sha256": "hash",
              "retrieved_at": "2026-09-14"}
    monkeypatch.setattr(routes, "_owned_workspace", AsyncMock(return_value=(
        {"analyses": [{"analysis_id": "a", "kind": "trusted_sources",
                       "result": {"sources": [source]}}]}, "client", "owner")))
    pin = AsyncMock(return_value=True)
    monkeypatch.setattr(routes, "pin_workspace_evidence", pin)
    client = TestClient(app)
    response = client.post("/workspaces/w/sources/pin", data={
        "analysis_id": "a", "source_index": "0", "quote": "Exact\r\nquote"})
    assert response.status_code == 200
    evidence = pin.await_args.args[1]
    assert evidence["original"] == "Exact\nquote"
    assert evidence["evidence_id"] == official_evidence_id(source, "Exact\nquote")
    pin.reset_mock()
    response = client.post("/workspaces/w/sources/pin", data={
        "analysis_id": "a", "source_index": "0", "quote": "Exact quote"})
    assert response.status_code == 422
    pin.assert_not_awaited()
