from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from dataclasses import asdict

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.api.dependencies import optional_user, verify_csrf, verify_csrf_header
from app.config import get_settings
from app.database import get_owned_interaction
from app.rate_limit import limiter
from app.research_database import (
    create_workspace,
    delete_workspace,
    get_workspace,
    list_workspaces,
    pin_workspace_evidence,
    save_workspace_analysis,
    unpin_workspace_evidence,
    update_workspace,
)
from app.services.evidence_presenter import present_context
from app.services.research_analysis import (
    generate_comparison,
    generate_obligation_matrix,
    generate_selected_evidence_answer,
)


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()
_SAFE_ID = re.compile(r"^[A-Za-z0-9-]{1,100}$")


def _identity(request: Request, current_user) -> tuple[str, str | None]:
    return (
        getattr(request.state, "client_id", "legacy"),
        str(current_user["_id"]) if current_user else None,
    )


def _validate_id(value: str, label: str = "object") -> str:
    if not _SAFE_ID.fullmatch(value):
        raise HTTPException(status_code=422, detail=f"invalid_{label}_id")
    return value


def _selected(workspace: dict, raw_ids: str) -> list[dict]:
    requested = {item.strip() for item in raw_ids.split(",") if item.strip()}
    if any(not _SAFE_ID.fullmatch(item) for item in requested):
        raise HTTPException(status_code=422, detail="invalid_evidence_id")
    selected = [
        item
        for item in (workspace.get("evidence") or [])[:100]
        if item.get("evidence_id") in requested
    ]
    if len(selected) != len(requested) or not selected:
        raise HTTPException(status_code=422, detail="insufficient_evidence")
    if len(selected) > 10:
        raise HTTPException(status_code=422, detail="evidence_scope_too_large")
    return selected


def _workspace_page(request: Request, name: str, context: dict):
    token = request.cookies.get("csrf_token") or secrets.token_hex(32)
    response = templates.TemplateResponse(
        request, name, {**context, "csrf_token": token}
    )
    response.set_cookie(
        "csrf_token", token, secure=request.url.scheme == "https", samesite="lax"
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _evidence_snapshot(evidence: list[dict]) -> list[dict]:
    fields = {
        "evidence_id",
        "trace_id",
        "session_id",
        "original",
        "citation",
        "excerpt",
        "document_id",
        "document_number",
        "title",
        "source_url",
    }
    return [
        {key: value for key, value in item.items() if key in fields}
        for item in evidence
    ]


async def _owned_workspace(request: Request, workspace_id: str, current_user):
    _validate_id(workspace_id, "workspace")
    client_id, user_id = _identity(request, current_user)
    workspace = await get_workspace(workspace_id, client_id, user_id=user_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace, client_id, user_id


@router.get("/workspaces", response_class=HTMLResponse)
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def workspace_list(request: Request, current_user=Depends(optional_user)):
    client_id, user_id = _identity(request, current_user)
    workspaces = await list_workspaces(client_id, user_id=user_id)
    return _workspace_page(
        request, "research_workspaces.html", {"workspaces": workspaces}
    )


@router.get("/api/workspaces")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def workspace_options(request: Request, current_user=Depends(optional_user)):
    client_id, user_id = _identity(request, current_user)
    workspaces = await list_workspaces(client_id, user_id=user_id)
    return {
        "workspaces": [
            {
                "workspace_id": item.get("workspace_id"),
                "title": str(item.get("title") or "")[:120],
            }
            for item in workspaces[:100]
        ]
    }


@router.post("/workspaces")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def workspace_create(
    request: Request,
    title: str = Form(..., min_length=1, max_length=120),
    description: str = Form("", max_length=2_000),
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    if not title.strip():
        raise HTTPException(status_code=422, detail="invalid_title")
    workspace_id = str(uuid.uuid4())
    client_id, user_id = _identity(request, current_user)
    await create_workspace(workspace_id, title, description, client_id, user_id=user_id)
    return RedirectResponse(f"/workspaces/{workspace_id}", status_code=303)


@router.get("/workspaces/{workspace_id}", response_class=HTMLResponse)
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def workspace_detail(
    request: Request, workspace_id: str, current_user=Depends(optional_user)
):
    workspace, _client_id, _user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    return _workspace_page(request, "research_workspace.html", {"workspace": workspace})


@router.post("/workspaces/{workspace_id}")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def workspace_update(
    request: Request,
    workspace_id: str,
    title: str = Form(..., min_length=1, max_length=120),
    description: str = Form("", max_length=2_000),
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    if not title.strip():
        raise HTTPException(status_code=422, detail="invalid_title")
    _workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    await update_workspace(
        workspace_id,
        client_id,
        user_id=user_id,
        title=title,
        description=description,
    )
    return RedirectResponse(f"/workspaces/{workspace_id}", status_code=303)


@router.delete("/workspaces/{workspace_id}")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def workspace_delete(
    request: Request,
    workspace_id: str,
    _csrf: str = Depends(verify_csrf_header),
    current_user=Depends(optional_user),
):
    _workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    await delete_workspace(workspace_id, client_id, user_id=user_id)
    return JSONResponse({"status": "deleted"})


@router.post("/workspaces/{workspace_id}/evidence")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def workspace_pin_evidence(
    request: Request,
    workspace_id: str,
    trace_id: str = Form(..., max_length=100),
    evidence_index: int = Form(..., ge=0, le=99),
    note: str = Form("", max_length=500),
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    _workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    _validate_id(trace_id, "trace")
    interaction = await get_owned_interaction(trace_id, client_id, user_id=user_id)
    contexts = list((interaction or {}).get("contexts") or [])
    if (
        interaction is None
        or (user_id is None and interaction.get("user_id"))
        or evidence_index >= len(contexts)
    ):
        raise HTTPException(status_code=422, detail="invalid_evidence")
    view = present_context(contexts[evidence_index])
    digest = hashlib.sha256(
        f"{trace_id}:{evidence_index}:{view.original}".encode("utf-8")
    ).hexdigest()[:24]
    evidence = {
        "evidence_id": digest,
        "trace_id": trace_id,
        "session_id": interaction.get("session_id"),
        "evidence_index": evidence_index,
        "introduced_by_claim": str(interaction.get("bot_response") or "")[:500],
        "note": note.strip()[:500],
        **asdict(view),
    }
    pinned = await pin_workspace_evidence(
        workspace_id, evidence, client_id, user_id=user_id
    )
    if not pinned:
        return JSONResponse(
            {"status": "not_pinned", "reason": "duplicate_or_workspace_limit"},
            status_code=409,
        )
    return JSONResponse({"status": "pinned", "evidence": evidence})


@router.delete("/workspaces/{workspace_id}/evidence/{evidence_id}")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def workspace_unpin_evidence(
    request: Request,
    workspace_id: str,
    evidence_id: str,
    _csrf: str = Depends(verify_csrf_header),
    current_user=Depends(optional_user),
):
    _workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    _validate_id(evidence_id, "evidence")
    removed = await unpin_workspace_evidence(
        workspace_id, evidence_id, client_id, user_id=user_id
    )
    if not removed:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return {"status": "unpinned"}


@router.post("/workspaces/{workspace_id}/analyses/selected")
@limiter.limit(settings.CHAT_RATE_LIMIT)
async def selected_evidence_analysis(
    request: Request,
    workspace_id: str,
    question: str = Form(..., min_length=1, max_length=2_000),
    evidence_ids: str = Form(..., max_length=2_000),
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    evidence = _selected(workspace, evidence_ids)
    if not evidence:
        raise HTTPException(status_code=422, detail="insufficient_evidence")
    try:
        result = await generate_selected_evidence_answer(question, evidence)
    except ValueError as error:
        raise HTTPException(
            status_code=422, detail="evidence_scope_too_large"
        ) from error
    except RuntimeError as error:
        result = {"status": "provider_error", "error_type": type(error).__name__}
    analysis = {
        "analysis_id": str(uuid.uuid4()),
        "kind": "selected_evidence",
        "question": question,
        "evidence_snapshot": _evidence_snapshot(evidence),
        "selected_evidence_ids": [item["evidence_id"] for item in evidence],
        "evidence_ids": [item["evidence_id"] for item in evidence],
        **result,
    }
    if not await save_workspace_analysis(
        workspace_id, analysis, client_id, user_id=user_id
    ):
        raise HTTPException(status_code=409, detail="workspace_changed")
    return JSONResponse(
        {**analysis, "evidence_scope": len(evidence)},
        status_code=502
        if result.get("status")
        in {"degraded", "invalid_structured_response", "provider_error"}
        else 200,
    )


async def _structured_response(
    *, workspace_id, client_id, user_id, kind, evidence, operation
):
    if not evidence:
        raise HTTPException(status_code=422, detail="insufficient_evidence")
    analysis_id = str(uuid.uuid4())
    try:
        result, metadata = await operation
        analysis = {
            "analysis_id": analysis_id,
            "kind": kind,
            "status": "ok"
            if (getattr(result, "findings", None) or getattr(result, "rows", None))
            else "insufficient_evidence",
            "evidence_ids": [item["evidence_id"] for item in evidence],
            "result": result.model_dump(mode="json"),
            "evidence_snapshot": _evidence_snapshot(evidence),
            **metadata,
        }
        status_code = 200
    except (ValidationError, RuntimeError) as error:
        analysis = {
            "analysis_id": analysis_id,
            "kind": kind,
            "status": "invalid_structured_response"
            if isinstance(error, ValidationError)
            else "provider_error",
            "evidence_ids": [item["evidence_id"] for item in evidence],
            "error_type": type(error).__name__,
        }
        status_code = 502
    except ValueError as error:
        raise HTTPException(
            status_code=422, detail="evidence_scope_too_large"
        ) from error
    if not await save_workspace_analysis(
        workspace_id, analysis, client_id, user_id=user_id
    ):
        raise HTTPException(status_code=409, detail="workspace_changed")
    return JSONResponse(analysis, status_code=status_code)


@router.post("/workspaces/{workspace_id}/analyses/compare")
@limiter.limit(settings.CHAT_RATE_LIMIT)
async def compare_evidence(
    request: Request,
    workspace_id: str,
    evidence_a: str = Form(..., max_length=2_000),
    evidence_b: str = Form(..., max_length=2_000),
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    group_a = _selected(workspace, evidence_a)
    group_b = _selected(workspace, evidence_b)
    if not group_a or not group_b:
        raise HTTPException(status_code=422, detail="insufficient_evidence")
    return await _structured_response(
        workspace_id=workspace_id,
        client_id=client_id,
        user_id=user_id,
        kind="comparison",
        evidence=group_a + group_b,
        operation=generate_comparison(group_a, group_b),
    )


@router.post("/workspaces/{workspace_id}/analyses/obligations")
@limiter.limit(settings.CHAT_RATE_LIMIT)
async def obligation_matrix(
    request: Request,
    workspace_id: str,
    evidence_ids: str = Form(..., max_length=2_000),
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    evidence = _selected(workspace, evidence_ids)
    if not evidence:
        raise HTTPException(status_code=422, detail="insufficient_evidence")
    return await _structured_response(
        workspace_id=workspace_id,
        client_id=client_id,
        user_id=user_id,
        kind="obligation_matrix",
        evidence=evidence,
        operation=generate_obligation_matrix(evidence),
    )
