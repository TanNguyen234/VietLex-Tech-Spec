"""Owner-scoped, provider-free timeline from explicit dates in selected evidence."""

import uuid
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from app.api.dependencies import optional_user, verify_csrf
from app.api.workspace_routes import _owned_workspace, _selected, _evidence_snapshot
from app.config import get_settings
from app.rate_limit import limiter
from app.research_database import save_workspace_analysis
from app.services.legal_timeline import build_legal_timeline

router = APIRouter()


@router.post("/workspaces/{workspace_id}/analyses/timeline")
@limiter.limit(get_settings().SESSION_RATE_LIMIT)
async def timeline(
    request: Request,
    workspace_id: str,
    evidence_ids: str = Form(..., max_length=2000),
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    evidence = _selected(workspace, evidence_ids)
    try:
        result = build_legal_timeline(evidence)
    except ValueError as error:
        raise HTTPException(422, detail="invalid_timeline_scope") from error
    document_ids = sorted(
        {
            str(item["workspace_document_id"])
            for item in evidence
            if item.get("workspace_document_id")
        }
    )
    analysis = {
        "analysis_id": str(uuid.uuid4()),
        "kind": "legal_timeline",
        "status": "ok",
        "result": result,
        "evidence_snapshot": _evidence_snapshot(evidence),
        "workspace_document_ids": document_ids,
        "provider": None,
        "model": None,
    }
    if not await save_workspace_analysis(
        workspace_id,
        analysis,
        client_id,
        user_id=user_id,
        required_document_ids=document_ids,
    ):
        raise HTTPException(409, detail="workspace_changed")
    return JSONResponse(analysis, headers={"Cache-Control": "no-store"})
