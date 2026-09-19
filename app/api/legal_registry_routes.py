from datetime import date
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from app.api.dependencies import optional_user, require_admin, verify_csrf
from app.api.routes import _admin_response
from app.api.legal_routes import templates
from app.api.workspace_routes import _owned_workspace, _validate_id
from app.config import get_settings
from app.rate_limit import limiter
from app.legal_registry_database import (
    registry_records,
    publish_review,
    withdraw_review,
    RegistryUnavailable,
)
from app.services.legal_registry import publication_record, registry_view

router = APIRouter()
settings = get_settings()
STATUS_LABELS = {
    "unknown": "Chưa xác định",
    "effective": "Có sự kiện bắt đầu hiệu lực",
    "amended": "Có sự kiện sửa đổi",
    "partially_effective": "Có sự kiện chấm dứt hiệu lực một phần",
    "repealed": "Có sự kiện bãi bỏ",
    "replaced": "Có sự kiện thay thế",
}


@router.get("/legal-status")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def legal_status(
    request: Request, document_number: str = Query("", max_length=100), as_of: str = ""
):
    day = as_of or date.today().isoformat()
    try:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError()
    except ValueError:
        raise HTTPException(422, "invalid_as_of_date") from None
    result = None
    error = None
    code = 200
    if document_number.strip():
        try:
            result = registry_view(
                document_number, day, await registry_records(document_number)
            )
        except (RegistryUnavailable, ValueError):
            error = "Không kết nối hoặc không thể đọc đầy đủ registry. Chưa thể kết luận tình trạng văn bản; hãy thử lại sau."
            code = 503
    return templates.TemplateResponse(
        request,
        "legal_status.html",
        {
            "document_number": document_number,
            "as_of": day,
            "result": result,
            "error": error,
            "status_labels": STATUS_LABELS,
        },
        status_code=code,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/admin/legal-registry")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def registry_admin(
    request: Request,
    workspace_id: str = Query("", max_length=100),
    skip: int = Query(0, ge=0, le=10000),
    current_user=Depends(optional_user),
    admin=Depends(require_admin),
):
    pending = []
    if workspace_id:
        workspace, _, _ = await _owned_workspace(request, workspace_id, current_user)
        pending = [
            row
            for row in workspace.get("analyses", [])
            if row.get("kind") == "legal_effect_review"
        ]
    try:
        rows = await registry_records(skip=skip)
    except RegistryUnavailable:
        raise HTTPException(503, "legal_registry_unavailable") from None
    return _admin_response(
        request,
        "admin_legal_registry.html",
        "registry",
        "Registry hiệu lực",
        {
            "rows": rows[:25],
            "has_next": len(rows) > 25,
            "skip": skip,
            "pending": pending,
            "workspace_id": workspace_id,
        },
    )


@router.post("/workspaces/{workspace_id}/analyses/{analysis_id}/publish-legal-effect")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def publish_legal_effect(
    request: Request,
    workspace_id: str,
    analysis_id: str,
    confirmed: str = Form(...),
    _csrf=Depends(verify_csrf),
    current_user=Depends(optional_user),
    admin=Depends(require_admin),
):
    if confirmed != "yes":
        raise HTTPException(422, "publication_confirmation_required")
    _validate_id(analysis_id, "analysis")
    workspace, _, _ = await _owned_workspace(request, workspace_id, current_user)
    analysis = next(
        (
            row
            for row in workspace.get("analyses", [])
            if row.get("analysis_id") == analysis_id
        ),
        None,
    )
    if analysis is None:
        raise HTTPException(404, "review_not_found")
    try:
        record = publication_record(analysis, str(admin.get("_id") or ""))
        await publish_review(record)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except RegistryUnavailable:
        raise HTTPException(503, "legal_registry_write_unavailable") from None
    return RedirectResponse("/admin/legal-registry", status_code=303)


@router.post("/admin/legal-registry/{review_id}/withdraw")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def withdraw_legal_effect(
    request: Request,
    review_id: str,
    reason: str = Form(..., min_length=5, max_length=1000),
    _csrf=Depends(verify_csrf),
    admin=Depends(require_admin),
):
    _validate_id(review_id, "analysis")
    try:
        changed = await withdraw_review(review_id, str(admin.get("_id") or ""), reason)
    except ValueError:
        raise HTTPException(422, "withdrawal_reason_required") from None
    except RegistryUnavailable:
        raise HTTPException(503, "legal_registry_write_unavailable") from None
    if not changed:
        raise HTTPException(409, "review_not_published_reload")
    return RedirectResponse("/admin/legal-registry", status_code=303)
