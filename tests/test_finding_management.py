from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.dependencies import optional_user, verify_csrf


def test_finding_update_preserves_model_output_and_rejects_stale_revision(monkeypatch):
    from app.api.finding_routes import router
    app = FastAPI()
    app.dependency_overrides[verify_csrf] = lambda: "ok"
    app.dependency_overrides[optional_user] = lambda: None
    app.include_router(router)
    original = {"clause_id": "c-1", "issue": "Issue", "recommendation": "Check", "risk_level": "high"}
    workspace = {"analyses": [{"analysis_id": "a-1", "kind": "contract_review", "result": {"findings": [original]}}]}
    monkeypatch.setattr("app.api.workspace_routes.get_workspace", AsyncMock(return_value=workspace))
    save = AsyncMock(return_value=True)
    monkeypatch.setattr("app.api.finding_routes.update_finding_review", save)
    client = TestClient(app)
    page = client.get("/workspaces/w-1/findings/a-1")
    assert page.status_code == 200 and "Issue" in page.text
    response = client.post("/workspaces/w-1/findings/a-1/0", data={"status": "resolved", "note": "Checked version 2", "revision": "0"}, follow_redirects=False)
    assert response.status_code == 303
    assert save.await_args.args[3]["status"] == "resolved"
    assert save.await_args.args[3]["version"] == 1
    assert workspace["analyses"][0]["result"]["findings"][0] == original
    save.return_value = False
    assert client.post("/workspaces/w-1/findings/a-1/0", data={"status": "resolved", "revision": "0"}).status_code == 409
    assert client.post("/workspaces/w-1/findings/a-1/99", data={"status": "open", "revision": "0"}).status_code == 404


@pytest.mark.asyncio
async def test_finding_write_checks_owner_expiry_and_version(monkeypatch):
    from app import research_database as db
    update = AsyncMock(return_value=SimpleNamespace(modified_count=1))
    monkeypatch.setattr(db, "get_db", lambda: SimpleNamespace(research_workspaces=SimpleNamespace(update_one=update)))
    assert await db.update_finding_review("w", "a", 0, {"version": 2}, "client", user_id="user", expected_version=1)
    query, mutation = update.await_args.args
    assert query["user_id"] == "user" and "expires_at" in query
    assert query["analyses"]["$elemMatch"]["finding_reviews.0.version"] == 1
    assert "analyses.$.finding_reviews.0" in mutation["$set"]
