from __future__ import annotations

import uuid
import hashlib

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.dependencies import optional_user, verify_csrf
from app.api.workspace_routes import (
    _evidence_snapshot,
    _owned_workspace,
    _workspace_document,
)
from app.config import get_settings
from app.database import log_interaction, update_interaction_request_status
from app.rate_limit import limiter
from app.research_database import (
    save_full_document_review_batch,
    save_workspace_analysis,
)
from app.services.full_document_review import (
    aggregate_full_document_review,
    plan_full_document_review,
)
from app.services.provider_runtime import capture_provider_usage, current_provider_calls
from app.services.research_analysis import generate_contract_review


router = APIRouter()
settings = get_settings()


def _legal_evidence(workspace: dict, raw_ids: str) -> list[dict]:
    requested = {item.strip() for item in raw_ids.split(",") if item.strip()}
    evidence = [
        item
        for item in workspace.get("evidence") or []
        if item.get("evidence_id") in requested
    ]
    if (
        len(requested) != len(evidence)
        or len(evidence) > 10
        or any(item.get("workspace_document_id") for item in evidence)
    ):
        raise HTTPException(status_code=422, detail="invalid_legal_evidence")
    return evidence


@router.post(
    "/workspaces/{workspace_id}/documents/{document_id}/analyses/full-review/plan"
)
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def full_document_review_plan(
    request: Request,
    workspace_id: str,
    document_id: str,
    legal_evidence_ids: str = Form("", max_length=2_000),
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    workspace, _, _ = await _owned_workspace(request, workspace_id, current_user)
    try:
        plan = plan_full_document_review(
            _workspace_document(workspace, document_id),
            _legal_evidence(workspace, legal_evidence_ids),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    response = JSONResponse(
        {
            **plan,
            "aggregate": aggregate_full_document_review(
                plan, workspace.get("analyses") or []
            ),
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/workspaces/{workspace_id}/analyses/full-review")
@limiter.limit(settings.CHAT_RATE_LIMIT)
@capture_provider_usage
async def run_full_document_review(
    request: Request,
    workspace_id: str,
    document_id: str = Form(..., min_length=1, max_length=100),
    batch_id: str = Form(..., min_length=1, max_length=40),
    input_sha256: str = Form(..., min_length=64, max_length=64),
    legal_evidence_ids: str = Form("", max_length=2_000),
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    document = _workspace_document(workspace, document_id)
    evidence = _legal_evidence(workspace, legal_evidence_ids)
    try:
        plan = plan_full_document_review(document, evidence)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if input_sha256 != plan["input_sha256"]:
        raise HTTPException(status_code=409, detail="review_input_changed")
    batch = next(
        (item for item in plan["batches"] if item["batch_id"] == batch_id), None
    )
    if batch is None:
        raise HTTPException(status_code=422, detail="invalid_batch_id")
    clauses_by_id = {
        str(item.get("clause_id")): item for item in document.get("clauses") or []
    }
    clauses = [clauses_by_id[item] for item in batch["clause_ids"]]
    analysis_id = str(uuid.uuid4())
    try:
        review, metadata = await generate_contract_review(clauses, evidence)
        status, result, error_type = "ok", review.model_dump(mode="json"), None
    except (ValidationError, ValueError):
        status, result, error_type, metadata = (
            "invalid_structured_response",
            None,
            "ContractReviewValidationError",
            {},
        )
    except RuntimeError:
        status, result, error_type, metadata = (
            "provider_error",
            None,
            "ContractReviewProviderError",
            {},
        )
    analysis = {
        "analysis_id": analysis_id,
        "kind": "full_document_review",
        "status": status,
        "document_id": document_id,
        "input_sha256": plan["input_sha256"],
        "batch_id": batch_id,
        "clause_ids": batch["clause_ids"],
        "legal_evidence_ids": plan["legal_evidence_ids"],
        "result": result,
        "error_type": error_type,
        "provider_calls": current_provider_calls() or [],
        **metadata,
    }
    analysis["selected_clauses"] = [
        {key: item.get(key) for key in ("clause_id", "title", "page", "order", "text")}
        for item in clauses
    ]
    analysis["evidence_snapshot"] = _evidence_snapshot(evidence)
    logged = await log_interaction(
        trace_id=analysis_id,
        user_query=f"Full-document review batch ({len(clauses)} clauses)",
        bot_response=status,
        contexts=[],
        cached=False,
        session_id=workspace_id,
        client_id=client_id,
        user_id=user_id,
        request_status=f"full_document_review_{status}",
        observed_provider=analysis.get("provider"),
        observed_model=analysis.get("model"),
        context_count=len(clauses) + len(evidence),
        no_evidence=not bool(clauses or evidence),
        retrieval_trace={
            "mode": "bounded_full_document_review",
            "batch_id": batch_id,
            "clause_count": len(clauses),
            "selected_legal_evidence_count": len(evidence),
            "context_sha256": [
                hashlib.sha256(str(item.get("text") or "").encode()).hexdigest()
                for item in clauses
            ],
        },
        request_metadata={"method": "POST", "path": request.url.path},
    )
    analysis["admin_trace_status"] = "persisted" if logged else "unavailable"
    saved = (
        await save_full_document_review_batch(
            workspace_id,
            analysis,
            client_id,
            user_id=user_id,
            document_id=document_id,
            input_sha256=plan["input_sha256"],
            completed_clause_ids=batch["clause_ids"],
        )
        if status == "ok"
        else await save_workspace_analysis(
            workspace_id,
            analysis,
            client_id,
            user_id=user_id,
            required_document_ids=[document_id],
        )
    )
    if not saved:
        await update_interaction_request_status(analysis_id, "workspace_changed")
        raise HTTPException(status_code=409, detail="workspace_changed")
    aggregate = aggregate_full_document_review(
        plan, [*(workspace.get("analyses") or []), analysis]
    )
    response = JSONResponse(
        {**analysis, "plan": plan, "aggregate": aggregate},
        status_code=502
        if status in {"provider_error", "invalid_structured_response"}
        else 200,
    )
    response.headers["Cache-Control"] = "no-store"
    return response
