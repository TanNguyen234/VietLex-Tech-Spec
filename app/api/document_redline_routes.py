from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import optional_user, verify_csrf
from app.api.workspace_routes import _owned_workspace, _workspace_document
from app.config import get_settings
from app.rate_limit import limiter
from app.research_database import save_workspace_analysis
from app.services.document_redline import compare_documents


router = APIRouter()
settings = get_settings()


@router.post("/workspaces/{workspace_id}/analyses/redline")
@limiter.limit(settings.CHAT_RATE_LIMIT)
async def document_redline(
    request: Request,
    workspace_id: str,
    document_a_id: str = Form(..., min_length=1, max_length=100),
    document_b_id: str = Form(..., min_length=1, max_length=100),
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    if document_a_id == document_b_id:
        raise HTTPException(status_code=422, detail="different_document_ids_required")
    document_a = _workspace_document(workspace, document_a_id)
    document_b = _workspace_document(workspace, document_b_id)
    try:
        result = compare_documents(document_a, document_b)
    except ValueError as error:
        raise HTTPException(
            status_code=422, detail="invalid_redline_documents"
        ) from error

    document_ids = sorted((document_a_id, document_b_id))
    analysis = {
        "analysis_id": str(uuid.uuid4()),
        "kind": "document_redline",
        "status": "ok",
        "workspace_document_ids": document_ids,
        "document_a_id": document_a_id,
        "document_b_id": document_b_id,
        "result": result,
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
        raise HTTPException(status_code=409, detail="workspace_changed")
    return JSONResponse(analysis, headers={"Cache-Control": "no-store"})
