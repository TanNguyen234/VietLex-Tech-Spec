from unittest.mock import AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.dependencies import require_admin, verify_csrf


def test_admin_quality_pages_render_records_and_backend_failures(monkeypatch):
    from types import SimpleNamespace
    from app.api import product_quality_routes as routes, legal_routes
    from app.services.legal_browser import LegalBrowserBackendError
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[require_admin] = lambda: {"_id": "admin", "role": "admin"}
    monkeypatch.setattr(routes, "get_admin_logs", AsyncMock(return_value=[{
        "_id": "t-1", "user_query": "Question", "bot_response": "Answer", "feedback": {"rating": "down"}}]))
    monkeypatch.setattr(legal_routes, "browser", SimpleNamespace(quality_queue=lambda *args, **kwargs: [
        {"document_id": 7, "document_number": "7/2026", "title": "Source", "issuing_authority": "Agency", "issuance_date": None}]))
    client = TestClient(app)
    feedback = client.get("/admin/feedback")
    assert feedback.status_code == 200 and "/admin/details/t-1" in feedback.text
    corpus = client.get("/admin/corpus")
    assert corpus.status_code == 200 and "/documents/7" in corpus.text
    def unavailable(*args, **kwargs):
        raise LegalBrowserBackendError("unavailable")
    legal_routes.browser.quality_queue = unavailable
    assert client.get("/admin/corpus").status_code == 503


def test_feedback_triage_requires_admin_and_exports_only_unverified_draft(monkeypatch):
    from app.api import product_quality_routes as routes
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)
    assert client.get("/admin/feedback").status_code == 401
    app.dependency_overrides[require_admin] = lambda: {"_id": "admin", "role": "admin"}
    app.dependency_overrides[verify_csrf] = lambda: "ok"
    monkeypatch.setattr(routes, "get_interaction", AsyncMock(return_value={"_id": "t-1", "user_query": "Question", "bot_response": "Wrong answer", "feedback": {"rating": "down"}}))
    save = AsyncMock(return_value=True)
    monkeypatch.setattr(routes, "save_feedback_triage", save)
    response = client.post("/admin/feedback/t-1", data={"category": "outdated_law", "status": "investigating", "revision": "0", "note": "Check source"}, follow_redirects=False)
    assert response.status_code == 303
    assert save.await_args.args[1]["reviewer_id"] == "admin"
    draft = client.get("/admin/feedback/t-1/regression-draft")
    assert draft.status_code == 200 and draft.headers["cache-control"] == "no-store"
    assert draft.json()["expected_answer"] is None
    assert draft.json()["status"] == "needs_human_adjudication"
    save.return_value = False
    assert client.post("/admin/feedback/t-1", data={"category": "outdated_law", "status": "resolved", "revision": "0"}).status_code == 409
