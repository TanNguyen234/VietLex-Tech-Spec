from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import optional_user, verify_csrf
from app.api.workspace_routes import _evidence_snapshot, _owned_workspace, _selected
from app.config import get_settings
from app.database import log_interaction, update_interaction_request_status
from app.rate_limit import limiter
from app.research_database import save_workspace_analysis
from app.services.provider_runtime import capture_provider_usage, current_provider_calls
from app.services.research_report import generate_research_report


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


@router.post("/workspaces/{workspace_id}/analyses/report")
@limiter.limit(settings.CHAT_RATE_LIMIT)
@capture_provider_usage
async def research_report(
    request: Request,
    workspace_id: str,
    question: str = Form(..., min_length=1, max_length=2_000),
    evidence_ids: str = Form(..., min_length=1, max_length=2_000),
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    evidence = _selected(workspace, evidence_ids)
    try:
        result = await generate_research_report(question, evidence)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="invalid_report_request") from error

    analysis_id = str(uuid.uuid4())
    document_ids = _workspace_document_ids(evidence)
    contexts = [
        str(item.get("original") or item.get("excerpt") or "")[:4_000]
        for item in evidence
    ]
    analysis = {
        "analysis_id": analysis_id,
        "kind": "research_report",
        "question": question,
        "selected_evidence_ids": [str(item["evidence_id"]) for item in evidence],
        "evidence_ids": [str(item["evidence_id"]) for item in evidence],
        "workspace_document_ids": document_ids,
        "evidence_snapshot": _evidence_snapshot(evidence),
        "provider_calls": current_provider_calls() or [],
        "result": {
            key: result[key]
            for key in ("report", "coverage", "unknown", "model_assessment")
        },
        **result,
    }
    logged = await log_interaction(
        trace_id=analysis_id,
        user_query=f"Structured research report over selected workspace evidence ({len(evidence)} records)",
        bot_response=str(analysis["status"]),
        contexts=[],
        cached=False,
        session_id=workspace_id,
        client_id=client_id,
        user_id=user_id,
        request_status=f"research_report_{analysis['status']}",
        observed_provider=analysis.get("provider"),
        observed_model=analysis.get("model"),
        context_count=len(contexts),
        no_evidence=not bool(contexts),
        retrieval_trace={
            "mode": "selected_evidence_research_report",
            "selected_evidence_count": len(evidence),
            "report_claim_count": int(
                (analysis.get("coverage") or {}).get("report_claims", 0)
            ),
            "verified_claim_count": int(
                (analysis.get("coverage") or {}).get("verified_claims", 0)
            ),
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
    return JSONResponse(
        {**analysis, "evidence_scope": len(evidence)},
        status_code=502
        if analysis["status"] in {"invalid_structured_response", "provider_error"}
        else 200,
    )
