from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_review_preserves_quote_and_rejects_stale_revision(monkeypatch):
    import app.api.trusted_source_routes as routes

    app = FastAPI()
    app.include_router(routes.router)
    routes.limiter._storage.reset()
    app.dependency_overrides[routes.optional_user] = lambda: {"_id": "u"}
    app.dependency_overrides[routes.verify_csrf] = lambda: "ok"
    evidence = {
        "evidence_id": "e",
        "excerpt": "Original OCR",
        "legal_effect_status": "unverified",
    }
    monkeypatch.setattr(
        routes,
        "_owned_workspace",
        AsyncMock(return_value=({"evidence": [evidence]}, "c", "u")),
    )
    save = AsyncMock(return_value=True)
    monkeypatch.setattr(routes, "update_evidence_review", save, raising=False)
    client = TestClient(app)
    path = "/workspaces/w/evidence/e/review"
    response = client.post(
        path,
        data={"status": "follow_up", "note": "Check page 2", "revision": 0},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert save.await_args.args[2]["note"] == "Check page 2"
    assert save.await_args.args[2]["version"] == 1
    assert evidence == {
        "evidence_id": "e",
        "excerpt": "Original OCR",
        "legal_effect_status": "unverified",
    }
    evidence["review"] = {"version": 1}
    assert (
        client.post(path, data={"status": "text_checked", "revision": 0}).status_code
        == 409
    )
    assert (
        client.post(
            path, data={"status": "legally_verified", "revision": 1}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/workspaces/w/evidence/absent/review",
            data={"status": "to_check", "revision": 0},
        ).status_code
        == 404
    )


@pytest.mark.asyncio
async def test_review_storage_checks_expiry_owner_and_same_array_revision(monkeypatch):
    from app import research_database as db

    update = AsyncMock(return_value=SimpleNamespace(modified_count=1))
    monkeypatch.setattr(
        db,
        "get_db",
        lambda: SimpleNamespace(research_workspaces=SimpleNamespace(update_one=update)),
    )
    assert await db.update_evidence_review(
        "w", "e", {"version": 2}, "c", user_id="u", expected_version=1
    )
    query, mutation = update.await_args.args
    assert query["user_id"] == "u" and "expires_at" in query
    assert query["evidence"]["$elemMatch"] == {"evidence_id": "e", "review.version": 1}
    assert "evidence.$.review" in mutation["$set"]
    assert "excerpt" not in str(mutation)
