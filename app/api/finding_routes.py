from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from app.api.dependencies import optional_user, verify_csrf
from app.api.workspace_routes import _owned_workspace, _validate_id, _workspace_page
from app.config import get_settings
from app.rate_limit import limiter
from app.research_database import update_finding_review

router = APIRouter()
settings = get_settings()


async def _review(request, workspace_id, analysis_id, current_user):
    _validate_id(analysis_id, "analysis")
    workspace, client_id, user_id = await _owned_workspace(request, workspace_id, current_user)
    analysis = next((item for item in workspace.get("analyses", []) if item.get("analysis_id") == analysis_id
                     and item.get("kind") in {"contract_review", "full_document_review"}), None)
    if analysis is None:
        raise HTTPException(404, "review_not_found")
    return analysis, client_id, user_id


@router.get("/workspaces/{workspace_id}/findings/{analysis_id}")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def finding_board(request: Request, workspace_id: str, analysis_id: str, current_user=Depends(optional_user)):
    analysis, _, _ = await _review(request, workspace_id, analysis_id, current_user)
    return _workspace_page(request, "finding_board.html", {"analysis": analysis, "workspace_id": workspace_id})


@router.post("/workspaces/{workspace_id}/findings/{analysis_id}/{finding_index}")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def finding_update(request: Request, workspace_id: str, analysis_id: str, finding_index: int,
                         status: Literal["open", "accepted", "dismissed", "resolved"] = Form(...),
                         revision: int = Form(..., ge=0), note: str = Form("", max_length=2_000),
                         suggested_revision: str = Form("", max_length=4_000), category: str = Form("", max_length=80),
                         _csrf: str = Depends(verify_csrf), current_user=Depends(optional_user)):
    analysis, client_id, user_id = await _review(request, workspace_id, analysis_id, current_user)
    findings = (analysis.get("result") or {}).get("findings") or []
    if not 0 <= finding_index < min(len(findings), 30):
        raise HTTPException(404, "finding_not_found")
    previous = (analysis.get("finding_reviews") or {}).get(str(finding_index)) or {}
    if previous.get("version", 0) != revision:
        raise HTTPException(409, "finding_changed_reload")
    event = {"status": status, "note": note, "suggested_revision": suggested_revision, "category": category,
             "reviewer_id": user_id or client_id, "reviewed_at": datetime.now(timezone.utc).isoformat(), "version": revision + 1}
    state = {**event, "history": [*(previous.get("history") or [])[-19:], event]}
    if not await update_finding_review(workspace_id, analysis_id, finding_index, state, client_id,
                                       user_id=user_id, expected_version=revision):
        raise HTTPException(409, "finding_changed_reload")
    return RedirectResponse(f"/workspaces/{workspace_id}/findings/{analysis_id}#finding-{finding_index}",
                            status_code=303, headers={"Cache-Control": "no-store"})
