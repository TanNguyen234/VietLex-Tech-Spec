from __future__ import annotations

import asyncio
import hashlib
import re
import secrets
import uuid
from dataclasses import asdict
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from app.paths import APP_ROOT
from pydantic import ValidationError

from app.api.dependencies import optional_user, verify_csrf, verify_csrf_header
from app.config import get_settings
from app.database import (
    get_owned_interaction,
    log_interaction,
    update_interaction_request_status,
)
from app.rate_limit import limiter
from app.research_database import (
    create_workspace,
    delete_workspace,
    get_workspace,
    get_workspace_original,
    list_workspaces,
    pin_workspace_evidence,
    remove_workspace_document,
    save_workspace_analysis,
    save_workspace_document,
    unpin_workspace_evidence,
    update_workspace,
)
from app.services.evidence_presenter import present_context
from app.services.research_analysis import (
    generate_comparison,
    generate_contract_review,
    generate_obligation_matrix,
    generate_selected_evidence_answer,
)
from app.services.deep_research import (
    DeepResearchDisabled,
    ResearchPlan,
    build_research_plan,
    run_deep_research,
)
from app.services.provider_runtime import capture_provider_usage, current_provider_calls
from app.services.workspace_documents import (
    DocumentExtractionError,
    MAX_UPLOAD_BYTES,
)
from app.services.document_worker import extract_isolated as extract_workspace_document

_DOCUMENT_PARSE_GATE = asyncio.Semaphore(2)


router = APIRouter()
templates = Jinja2Templates(directory=APP_ROOT / "templates")
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
        "source_kind",
        "workspace_document_id",
        "clause_id",
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
    from app.services.model_comparison import available_model_choices

    return _workspace_page(
        request,
        "research_workspace.html",
        {
            "workspace": workspace,
            "workspace_user": current_user,
            "comparison_models": available_model_choices() if current_user and current_user.get("email_verified") else [],
            "official_research_enabled": (
                settings.OFFICIAL_WEB_RESEARCH_ENABLED
            ),
        },
    )


def _workspace_document(workspace: dict, document_id: str) -> dict:
    _validate_id(document_id, "document")
    document = next(
        (
            item
            for item in (workspace.get("documents") or [])[:20]
            if item.get("document_id") == document_id
        ),
        None,
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.post("/workspaces/{workspace_id}/documents")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def workspace_document_upload(
    request: Request,
    workspace_id: str,
    document: UploadFile = File(...),
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    if len(workspace.get("documents") or []) >= 20:
        raise HTTPException(status_code=409, detail="document_limit_reached")
    try:
        payload = await document.read(MAX_UPLOAD_BYTES + 1)
    finally:
        await document.close()
    try:
        async with _DOCUMENT_PARSE_GATE:
            extracted = await asyncio.to_thread(
                extract_workspace_document,
                document.filename or "document",
                document.content_type or "",
                payload,
            )
    except DocumentExtractionError as error:
        raise HTTPException(status_code=422, detail=error.kind) from error
    if any(
        item.get("document_id") == extracted.document_id
        for item in (workspace.get("documents") or [])
    ):
        raise HTTPException(status_code=409, detail="duplicate_document")
    record = extracted.model_dump(mode="json")
    record["original_available"] = True
    if not await save_workspace_document(
        workspace_id, record, client_id, user_id=user_id, original_bytes=payload
    ):
        raise HTTPException(status_code=409, detail="workspace_changed")
    return JSONResponse(record)


@router.get("/workspaces/{workspace_id}/documents/{document_id}/original")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def workspace_original_download(
    request: Request, workspace_id: str, document_id: str,
    current_user=Depends(optional_user),
):
    _workspace, client_id, user_id = await _owned_workspace(request, workspace_id, current_user)
    original = await get_workspace_original(workspace_id, document_id, client_id, user_id=user_id)
    if original is None:
        raise HTTPException(404, "original_not_found", headers={"Cache-Control": "no-store"})
    filename = quote(original.get("filename") or "document", safe="")
    return Response(original["original_bytes"], media_type="application/octet-stream", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })


@router.delete("/workspaces/{workspace_id}/documents/{document_id}")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def workspace_document_delete(
    request: Request,
    workspace_id: str,
    document_id: str,
    _csrf: str = Depends(verify_csrf_header),
    current_user=Depends(optional_user),
):
    workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    _workspace_document(workspace, document_id)
    if not await remove_workspace_document(
        workspace_id, document_id, client_id, user_id=user_id
    ):
        raise HTTPException(status_code=409, detail="workspace_changed")
    return {"status": "deleted"}


@router.post(
    "/workspaces/{workspace_id}/documents/{document_id}/clauses/{clause_id}/pin"
)
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def workspace_document_clause_pin(
    request: Request,
    workspace_id: str,
    document_id: str,
    clause_id: str,
    _csrf: str = Depends(verify_csrf_header),
    current_user=Depends(optional_user),
):
    workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    source = _workspace_document(workspace, document_id)
    _validate_id(clause_id, "clause")
    clause = next(
        (
            item
            for item in (source.get("clauses") or [])[:100]
            if item.get("clause_id") == clause_id
        ),
        None,
    )
    if clause is None:
        raise HTTPException(status_code=422, detail="invalid_clause_id")
    page = f" · Trang {clause.get('page')}" if clause.get("page") else ""
    citation = f"{source.get('filename')} · {clause.get('title')}{page}"[:500]
    original = f"[{citation}]\n{str(clause.get('text') or '')}"[:12_500]
    evidence = {
        "evidence_id": f"udoc-{clause_id}",
        "trace_id": f"document-{document_id}",
        "session_id": workspace_id,
        "workspace_document_id": document_id,
        "clause_id": clause_id,
        "source_kind": "user_document",
        "introduced_by_claim": "Điều khoản do người dùng tải lên; chưa được đối chiếu luật.",
        "note": "",
        "original": original,
        "citation": citation,
        "excerpt": str(clause.get("text") or "")[:600],
        "document_id": None,
        "document_number": "",
        "title": str(clause.get("title") or "")[:240],
        "source_url": "",
    }
    if not await pin_workspace_evidence(
        workspace_id, evidence, client_id, user_id=user_id
    ):
        return JSONResponse(
            {"status": "not_pinned", "reason": "duplicate_or_workspace_limit"},
            status_code=409,
        )
    return {"status": "pinned", "evidence": evidence}


@router.post("/workspaces/{workspace_id}/documents/{document_id}/review")
@limiter.limit(settings.CHAT_RATE_LIMIT)
@capture_provider_usage
async def workspace_contract_review(
    request: Request,
    workspace_id: str,
    document_id: str,
    clause_ids: str = Form(..., min_length=1, max_length=4_000),
    legal_evidence_ids: str = Form("", max_length=2_000),
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    source = _workspace_document(workspace, document_id)
    requested_clauses = {item for item in clause_ids.split(",") if item}
    if (
        not requested_clauses
        or len(requested_clauses) > 10
        or any(not _SAFE_ID.fullmatch(item) for item in requested_clauses)
    ):
        raise HTTPException(status_code=422, detail="invalid_clause_id")
    clauses = [
        item
        for item in (source.get("clauses") or [])[:100]
        if item.get("clause_id") in requested_clauses
    ]
    if len(clauses) != len(requested_clauses):
        raise HTTPException(status_code=422, detail="invalid_clause_id")
    requested_evidence = {
        item for item in legal_evidence_ids.split(",") if item
    }
    if len(requested_evidence) > 10 or any(
        not _SAFE_ID.fullmatch(item) for item in requested_evidence
    ):
        raise HTTPException(status_code=422, detail="invalid_evidence_id")
    legal_evidence = [
        item
        for item in (workspace.get("evidence") or [])[:100]
        if item.get("evidence_id") in requested_evidence
        and item.get("source_kind") != "user_document"
    ]
    if len(legal_evidence) != len(requested_evidence):
        raise HTTPException(status_code=422, detail="invalid_evidence_id")
    analysis_id = str(uuid.uuid4())
    try:
        result, metadata = await generate_contract_review(clauses, legal_evidence)
        analysis = {
            "analysis_id": analysis_id,
            "kind": "contract_review",
            "status": "ok" if result.findings else "insufficient_evidence",
            "workspace_document_id": document_id,
            "filename": str(source.get("filename") or "")[:180],
            "selected_clauses": clauses,
            "evidence_snapshot": _evidence_snapshot(legal_evidence),
            "result": result.model_dump(mode="json"),
            "provider_calls": current_provider_calls() or [],
            **metadata,
        }
        status_code = 200
    except ValueError as error:
        if str(error) == "evidence_scope_too_large":
            raise HTTPException(status_code=422, detail=str(error)) from error
        analysis = {
            "analysis_id": analysis_id,
            "kind": "contract_review",
            "status": "invalid_structured_response",
            "workspace_document_id": document_id,
            "error_type": type(error).__name__,
        }
        status_code = 502
    except (ValidationError, RuntimeError) as error:
        analysis = {
            "analysis_id": analysis_id,
            "kind": "contract_review",
            "status": (
                "invalid_structured_response"
                if isinstance(error, ValidationError)
                else "provider_error"
            ),
            "workspace_document_id": document_id,
            "error_type": type(error).__name__,
        }
        status_code = 502
    contexts = [
        f"[User document: {source.get('filename')} · {item.get('title')}]\n"
        f"{str(item.get('text') or '')[:4_000]}"
        for item in clauses
    ] + [str(item.get("original") or "")[:4_000] for item in legal_evidence]
    logged = await log_interaction(
        trace_id=analysis_id,
        user_query=f"Rà soát {len(clauses)} điều khoản tài liệu cá nhân",
        bot_response=analysis['status'],
        contexts=[],
        cached=False,
        session_id=workspace_id,
        client_id=client_id,
        user_id=user_id,
        request_status=f"contract_review_{analysis['status']}",
        observed_provider=analysis.get("provider"),
        observed_model=analysis.get("model"),
        context_count=len(contexts[:20]),
        no_evidence=not bool(contexts),
        retrieval_trace={
            "mode": "user_document_review",
            "document_id": document_id,
            "selected_clause_count": len(clauses),
            "selected_legal_evidence_count": len(legal_evidence),
            "content_storage": "workspace_only",
            "context_sha256": [hashlib.sha256(c.encode('utf-8')).hexdigest() for c in contexts],
        },
        request_metadata={"method": "POST", "path": request.url.path},
    )
    analysis["admin_trace_status"] = "persisted" if logged else "unavailable"
    if not await save_workspace_analysis(
        workspace_id,
        analysis,
        client_id,
        user_id=user_id,
        required_document_id=document_id,
    ):
        await update_interaction_request_status(analysis_id, "workspace_changed")
        raise HTTPException(status_code=409, detail="workspace_changed")
    return JSONResponse(analysis, status_code=status_code)


@router.post("/workspaces/{workspace_id}/research/plan")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def deep_research_plan(
    request: Request,
    workspace_id: str,
    question: str = Form(..., min_length=1, max_length=2_000),
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    await _owned_workspace(request, workspace_id, current_user)
    try:
        return build_research_plan(question).model_dump(mode="json")
    except (ValidationError, ValueError) as error:
        raise HTTPException(status_code=422, detail="invalid_research_question") from error


@router.post("/workspaces/{workspace_id}/research/run")
@limiter.limit(settings.OFFICIAL_WEB_RESEARCH_RATE_LIMIT)
@capture_provider_usage
async def deep_research_run(
    request: Request,
    workspace_id: str,
    plan: str = Form(..., min_length=1, max_length=12_000),
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    _workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    try:
        approved_plan = ResearchPlan.model_validate_json(plan)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail="invalid_research_plan") from error
    try:
        result = await run_deep_research(approved_plan)
    except DeepResearchDisabled as error:
        raise HTTPException(status_code=503, detail="research_disabled") from error
    analysis = {
        "analysis_id": str(uuid.uuid4()),
        "kind": "deep_research",
        "status": result.status,
        "question": result.question,
        "plan": approved_plan.model_copy(
            update={"plan_id": result.plan_id}
        ).model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
        "provider": result.provider,
        "model": result.model,
        "provider_calls": current_provider_calls() or [],
    }
    contexts = [
        f"[Official web: {source.title}]\nURL: {source.url}\n"
        + source.snippet[:1_000]
        for step in result.steps
        for source in step.sources
    ][:20]
    logged = await log_interaction(
        trace_id=analysis["analysis_id"],
        user_query=result.question,
        bot_response="\n\n".join(
            source.title for step in result.steps for source in step.sources
        )[:10_000],
        contexts=contexts,
        cached=False,
        session_id=workspace_id,
        client_id=client_id,
        user_id=user_id,
        request_status=(
            "ok" if result.status == "complete" else "deep_research_" + result.status
        ),
        observed_provider=result.provider,
        observed_model=result.model,
        context_count=len(contexts),
        no_evidence=not bool(contexts),
        retrieval_trace={
            "mode": "official_web",
            "stages": [
                {
                    "stage": step.step_id,
                    "status": step.status,
                    "source_count": len(step.sources),
                    "result_count": len(step.sources),
                }
                for step in result.steps
            ],
        },
        request_metadata={"method": "POST", "path": request.url.path},
    )
    analysis["admin_trace_status"] = "persisted" if logged else "unavailable"
    if not await save_workspace_analysis(
        workspace_id, analysis, client_id, user_id=user_id
    ):
        await update_interaction_request_status(
            analysis["analysis_id"], "workspace_changed"
        )
        raise HTTPException(status_code=409, detail="workspace_changed")
    return JSONResponse(analysis)


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
