"""Bounded reads from approved public origins and explicit excerpt pinning."""

import asyncio
import hashlib
import uuid
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from app.api.dependencies import optional_user, verify_csrf
from app.api.workspace_routes import _owned_workspace
from app.config import get_settings
from app.rate_limit import limiter
from app.research_database import save_workspace_analysis, pin_workspace_evidence
from app.services.trusted_source_reader import (
    read_source,
    validate_source_url,
    reconcile_sources,
    SourceReadError,
)

router = APIRouter()


@router.post("/workspaces/{workspace_id}/analyses/sources")
@limiter.limit(get_settings().OFFICIAL_WEB_RESEARCH_RATE_LIMIT)
async def source_read(
    request: Request,
    workspace_id: str,
    urls: str = Form(..., max_length=6000),
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    _workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    selected = list(
        dict.fromkeys(line.strip() for line in urls.splitlines() if line.strip())
    )
    try:
        if not 1 <= len(selected) <= 3:
            raise ValueError("source_scope_invalid")
        for url in selected:
            validate_source_url(url)
    except ValueError as error:
        raise HTTPException(422, detail="source_scope_invalid") from error

    async def one(url):
        try:
            return await read_source(url), None
        except SourceReadError as error:
            return None, {"url": url, "kind": error.kind}

    outcomes = await asyncio.gather(*(one(url) for url in selected))
    sources = [source for source, error in outcomes if source]
    errors = [error for source, error in outcomes if error]
    analysis = {
        "analysis_id": str(uuid.uuid4()),
        "kind": "trusted_sources",
        "status": "ok" if not errors else "partial" if sources else "source_error",
        "result": {
            **reconcile_sources(sources),
            "errors": errors,
            "coverage": {
                "requested": len(selected),
                "retrieved": len(sources),
                "failed": len(errors),
            },
        },
        "provider": "approved_public_html",
        "model": None,
    }
    if not await save_workspace_analysis(
        workspace_id, analysis, client_id, user_id=user_id
    ):
        raise HTTPException(409, detail="workspace_changed")
    return JSONResponse(
        analysis,
        status_code=200 if sources else 502,
        headers={"Cache-Control": "no-store"},
    )


@router.post("/workspaces/{workspace_id}/sources/pin")
@limiter.limit(get_settings().SESSION_RATE_LIMIT)
async def pin_source(
    request: Request,
    workspace_id: str,
    analysis_id: str = Form(..., max_length=100),
    source_index: int = Form(..., ge=0, le=2),
    quote: str = Form(..., min_length=1, max_length=3000),
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    analysis = next(
        (
            a
            for a in workspace.get("analyses", [])
            if a.get("analysis_id") == analysis_id
            and a.get("kind") == "trusted_sources"
        ),
        None,
    )
    sources = (analysis or {}).get("result", {}).get("sources", [])
    if source_index >= len(sources):
        raise HTTPException(404, detail="source_not_found")
    source = sources[source_index]
    if not quote.strip() or quote not in source["text"]:
        raise HTTPException(422, detail="quote_not_in_source")
    evidence = {
        "evidence_id": hashlib.sha256(
            (source["url"] + "\n" + quote).encode()
        ).hexdigest()[:24],
        "trace_id": analysis_id,
        "session_id": None,
        "source_kind": "official_web",
        "source_url": source["url"],
        "title": source["title"],
        "citation": source["title"],
        "excerpt": quote,
        "original": quote,
        "source_sha256": source["sha256"],
        "retrieved_at": source["retrieved_at"],
        "introduced_by_claim": "",
        "legal_effect_status": "unverified",
    }
    if not await pin_workspace_evidence(
        workspace_id, evidence, client_id, user_id=user_id
    ):
        raise HTTPException(409, detail="evidence_already_pinned_or_workspace_changed")
    return JSONResponse(
        {"status": "ok", "evidence_id": evidence["evidence_id"]},
        headers={"Cache-Control": "no-store"},
    )
