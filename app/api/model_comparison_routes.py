from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import require_user, verify_csrf
from app.api.workspace_routes import _evidence_snapshot, _owned_workspace, _selected
from app.config import get_settings
from app.database import log_interaction, update_interaction_request_status
from app.rate_limit import limiter
from app.research_database import save_workspace_analysis
from app.services.model_comparison import available_model_choices, compare_models
from app.services.provider_runtime import capture_provider_usage, current_provider_calls


router = APIRouter()
settings = get_settings()


def available_comparison_models() -> list[dict[str, str]]:
    """Server-safe configured model choices for the workspace UI."""

    return available_model_choices()


@router.post("/workspaces/{workspace_id}/analyses/models")
@limiter.limit(settings.CHAT_RATE_LIMIT)
@capture_provider_usage
async def model_comparison(
    request: Request,
    workspace_id: str,
    question: str = Form(..., min_length=1, max_length=2_000),
    evidence_ids: str = Form(..., min_length=1, max_length=2_000),
    model_a: str = Form(..., min_length=1, max_length=100),
    model_b: str = Form(..., min_length=1, max_length=100),
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(require_user),
):
    if not current_user.get("email_verified"):
        raise HTTPException(status_code=403, detail="verified_account_required")
    if current_user.get("role", "user") != "admin":
        raise HTTPException(status_code=403, detail="admin_required")
    workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    evidence = _selected(workspace, evidence_ids)
    try:
        result = await compare_models(question, evidence, model_a, model_b)
    except ValueError as error:
        detail = str(error)
        if detail in {
            "different_model_aliases_required",
            "invalid_model_alias",
            "model_unavailable",
            "question_required",
            "question_too_large",
            "comparison_input_too_large",
            "evidence_scope_too_large",
        }:
            raise HTTPException(status_code=422, detail=detail) from error
        raise HTTPException(
            status_code=422, detail="invalid_model_comparison"
        ) from error

    analysis_id = str(uuid.uuid4())
    document_ids = sorted(
        {
            str(item["workspace_document_id"])
            for item in evidence
            if item.get("workspace_document_id")
        }
    )
    statuses = [str(item.get("status") or "") for item in result["responses"]]
    analysis_status = (
        "ok"
        if statuses == ["success", "success"]
        and all(
            item.get("identity_status") == "matched" for item in result["responses"]
        )
        else "partial"
    )
    analysis = {
        "analysis_id": analysis_id,
        "kind": "model_comparison",
        "status": analysis_status,
        "requested_model_aliases": [model_a, model_b],
        "workspace_document_ids": document_ids,
        "selected_evidence_ids": [str(item["evidence_id"]) for item in evidence],
        "evidence_snapshot": _evidence_snapshot(evidence),
        "result": result,
        "provider_calls": current_provider_calls() or [],
        "provider": None,
        "model": None,
    }
    contexts = [
        str(item.get("original") or item.get("excerpt") or "")[:4_000]
        for item in evidence
    ]
    logged = await log_interaction(
        trace_id=analysis_id,
        user_query=(
            "Explicit two-model comparison over selected workspace evidence "
            f"({len(evidence)} records)"
        ),
        bot_response=analysis_status,
        contexts=[],
        cached=False,
        session_id=workspace_id,
        client_id=client_id,
        user_id=user_id,
        request_status=f"model_comparison_{analysis_status}",
        observed_provider=None,
        observed_model=None,
        context_count=len(contexts),
        no_evidence=not bool(contexts),
        retrieval_trace={
            "mode": "selected_evidence_model_comparison",
            "selected_evidence_count": len(evidence),
            "model_aliases": [model_a, model_b],
            "input_sha256": result["same_input_proof"]["input_sha256"],
            "context_sha256": [
                hashlib.sha256(context.encode("utf-8")).hexdigest()
                for context in contexts
            ],
        },
        request_metadata={"method": "POST", "path": request.url.path},
    )
    analysis["admin_trace_status"] = "persisted" if logged else "unavailable"
    if not await save_workspace_analysis(
        workspace_id,
        analysis,
        client_id,
        user_id=user_id,
        required_document_ids=document_ids,
    ):
        await update_interaction_request_status(analysis_id, "workspace_changed")
        raise HTTPException(status_code=409, detail="workspace_changed")
    return JSONResponse(analysis, headers={"Cache-Control": "no-store"})
