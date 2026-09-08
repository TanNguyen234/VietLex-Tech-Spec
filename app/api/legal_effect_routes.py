from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import optional_user, require_admin, verify_csrf
from app.api.workspace_routes import _evidence_snapshot, _owned_workspace, _selected
from app.config import get_settings
from app.database import log_interaction, update_interaction_request_status
from app.rate_limit import limiter
from app.research_database import save_workspace_analysis
from app.services.legal_effect import review_legal_effect


router = APIRouter()
settings = get_settings()


def _workspace_document_ids(evidence: list[dict]) -> list[str]:
    return sorted(
        {
            str(item["workspace_document_id"])
            for item in evidence
            if item.get("workspace_document_id")
        }
    )


@router.post("/workspaces/{workspace_id}/analyses/legal-effect")
@limiter.limit(settings.CHAT_RATE_LIMIT)
async def legal_effect_review(
    request: Request,
    workspace_id: str,
    evidence_ids: str = Form(..., min_length=1, max_length=2_000),
    as_of: str = Form(..., min_length=10, max_length=10),
    events: str = Form(..., max_length=20_000),
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
    reviewer: dict = Depends(require_admin),
):
    workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    evidence = _selected(workspace, evidence_ids)
    try:
        raw_events = json.loads(events)
        if not isinstance(raw_events, list):
            raise ValueError("invalid_legal_effect_event")
        result = review_legal_effect(evidence, as_of, raw_events)
    except (json.JSONDecodeError, ValueError) as error:
        detail = str(error)
        if detail in {
            "invalid_as_of_date",
            "invalid_legal_effect_event",
            "legal_effect_scope_too_large",
        }:
            raise HTTPException(status_code=422, detail=detail) from error
        raise HTTPException(
            status_code=422, detail="invalid_legal_effect_event"
        ) from error

    checked_at = datetime.now(timezone.utc).isoformat()
    analysis_id = str(uuid.uuid4())
    document_ids = _workspace_document_ids(evidence)
    analysis = {
        "analysis_id": analysis_id,
        "kind": "legal_effect_review",
        "reviewer_id": str(reviewer.get("_id") or "")[:100],
        "reviewed_at": checked_at,
        "query_date": checked_at[:10],
        "last_checked": checked_at,
        "selected_evidence_ids": [str(item["evidence_id"]) for item in evidence],
        "evidence_ids": [str(item["evidence_id"]) for item in evidence],
        "workspace_document_ids": document_ids,
        "evidence_snapshot": _evidence_snapshot(evidence),
        "selected_source_sha256": [
            source["source_sha256"] for source in result["result"]["selected_sources"]
        ],
        "provider_calls": [],
        **result,
    }
    source_texts = [
        str(item.get("excerpt") or item.get("original") or "")[:4_000]
        for item in evidence
    ]
    logged = await log_interaction(
        trace_id=analysis_id,
        user_query=f"Human-reviewed legal-effect records ({len(evidence)} sources)",
        bot_response=str(analysis["status"]),
        contexts=[],
        cached=False,
        session_id=workspace_id,
        client_id=client_id,
        user_id=user_id,
        request_status=f"legal_effect_review_{analysis['status']}",
        observed_provider=None,
        observed_model=None,
        context_count=len(source_texts),
        no_evidence=not bool(source_texts),
        retrieval_trace={
            "mode": "human_admin_reviewed_legal_effect",
            "selected_evidence_count": len(evidence),
            "event_count": len(analysis["result"]["assertions"]),
            "as_of": analysis["result"]["as_of"],
            "context_sha256": [
                hashlib.sha256(text.encode("utf-8")).hexdigest()
                for text in source_texts
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
    return JSONResponse(
        {**analysis, "evidence_scope": len(evidence)},
        headers={"Cache-Control": "no-store"},
    )


@router.get("/workspaces/{workspace_id}/analyses/legal-effect")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def legal_effect_history(
    request: Request,
    workspace_id: str,
    current_user=Depends(optional_user),
):
    workspace, _client_id, _user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    analyses = [
        analysis
        for analysis in (workspace.get("analyses") or [])[:50]
        if analysis.get("kind") == "legal_effect_review"
    ]
    return JSONResponse({"analyses": analyses}, headers={"Cache-Control": "no-store"})
