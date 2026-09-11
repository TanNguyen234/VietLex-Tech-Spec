from datetime import datetime, timezone
import asyncio
from typing import Literal
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from app.api.dependencies import require_admin, verify_csrf
from app.api.routes import _admin_response
from app.api.workspace_routes import _validate_id
from app.config import get_settings
from app.database import get_admin_logs, get_interaction, get_db
from app.rate_limit import limiter
from app.services.admin_observability import AdminDataUnavailable, present_interaction
from pymongo.errors import PyMongoError

router = APIRouter()
settings = get_settings()
Category = Literal["wrong_citation", "outdated_law", "missing_provision", "unsupported_conclusion", "poor_retrieval", "ux_issue"]


@router.get("/admin/corpus")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def corpus_queue(request: Request, issue: Literal["missing_date", "missing_source"] = "missing_date",
                       skip: int = Query(0, ge=0, le=100_000), _admin=Depends(require_admin)):
    from app.api.legal_routes import _get_browser
    from app.services.legal_browser import LegalBrowserBackendError
    try:
        rows = await asyncio.to_thread(_get_browser().quality_queue, issue, offset=skip)
    except LegalBrowserBackendError:
        raise HTTPException(503, "corpus_metadata_unavailable") from None
    return _admin_response(request, "admin_corpus_queue.html", "corpus", "Chất lượng corpus", {
        "rows": rows, "issue": issue, "skip": skip, "has_next": len(rows) == 50,
        "backend": "Supabase online" if settings.SERVERLESS_ONLINE_ONLY else "SQLite local"})


async def save_feedback_triage(trace_id: str, state: dict, expected_version: int) -> bool:
    query = {"_id": trace_id}
    field = "feedback.triage.version"
    if expected_version:
        query[field] = expected_version
    else:
        query["$or"] = [{field: 0}, {field: {"$exists": False}}]
    try:
        result = await get_db().evaluation_logs.update_one(query, {"$set": {"feedback.triage": state}})
        return result.modified_count > 0
    except (PyMongoError, RuntimeError) as error:
        raise AdminDataUnavailable("feedback_write_unavailable") from error


async def _interaction(trace_id):
    _validate_id(trace_id, "trace")
    try:
        record = await get_interaction(trace_id, strict=True)
    except AdminDataUnavailable:
        raise HTTPException(503, "feedback_unavailable") from None
    if record is None:
        raise HTTPException(404, "feedback_not_found")
    return record


@router.get("/admin/feedback")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def feedback_queue(request: Request, skip: int = Query(0, ge=0, le=100_000), _admin=Depends(require_admin)):
    try:
        rows = await get_admin_logs(limit=25, skip=skip, feedback="down")
    except AdminDataUnavailable:
        raise HTTPException(503, "feedback_unavailable") from None
    return _admin_response(request, "admin_feedback_queue.html", "feedback", "Xử lý feedback", {
        "rows": [present_interaction(row) for row in rows], "skip": skip, "has_next": len(rows) == 25})


@router.post("/admin/feedback/{trace_id}")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def feedback_triage(request: Request, trace_id: str, category: Category = Form(...),
                          status: Literal["open", "investigating", "resolved"] = Form(...),
                          revision: int = Form(..., ge=0), note: str = Form("", max_length=2_000),
                          assignee: str = Form("", max_length=100), _csrf=Depends(verify_csrf), admin=Depends(require_admin)):
    record = await _interaction(trace_id)
    previous = (record.get("feedback") or {}).get("triage") or {}
    if previous.get("version", 0) != revision:
        raise HTTPException(409, "feedback_changed_reload")
    event = {"category": category, "status": status, "note": note, "assignee": assignee,
             "reviewer_id": str(admin.get("_id") or "legacy-admin"),
             "reviewed_at": datetime.now(timezone.utc).isoformat(), "version": revision + 1}
    state = {**event, "history": [*(previous.get("history") or [])[-19:], event]}
    try:
        changed = await save_feedback_triage(trace_id, state, revision)
    except AdminDataUnavailable:
        raise HTTPException(503, "feedback_unavailable") from None
    if not changed:
        raise HTTPException(409, "feedback_changed_reload")
    return RedirectResponse("/admin/feedback", status_code=303, headers={"Cache-Control": "no-store"})


@router.get("/admin/feedback/{trace_id}/regression-draft")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def regression_draft(request: Request, trace_id: str, _admin=Depends(require_admin)):
    record = present_interaction(await _interaction(trace_id))
    return JSONResponse({"schema": "vietlex-feedback-draft-v1", "source_trace_id": trace_id,
        "status": "needs_human_adjudication", "question": record.get("user_query"),
        "observed_answer": record.get("bot_response"), "expected_answer": None,
        "expected_references": [], "source_contexts_redacted": record.get("contexts"),
        "triage": (record.get("feedback") or {}).get("triage"),
        "golden_dataset_promoted": False}, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f'attachment; filename="feedback-{trace_id}-draft.json"'})
