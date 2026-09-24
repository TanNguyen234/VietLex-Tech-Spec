import uuid
import re
from typing import Literal
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from app.api.dependencies import optional_user, verify_csrf
from app.api.workspace_routes import _owned_workspace, _validate_id, _workspace_page
from app.services.report_deliverables import report_preview
from app.config import get_settings
from app.database import log_interaction, update_interaction_request_status
from app.rate_limit import limiter
from app.research_database import save_workspace_analysis
from app.services.provider_runtime import capture_provider_usage, current_provider_calls
from app.services.retained_source_analysis import (
    collect_retained_source,
    analyze_retained_source,
)

router = APIRouter()
settings = get_settings()


@router.post("/workspaces/{workspace_id}/analyses/retained-source")
@limiter.limit(settings.CHAT_RATE_LIMIT)
@capture_provider_usage
async def retained_source_answer(
    request: Request,
    workspace_id: str,
    analysis_id: str = Form(..., max_length=100),
    source_index: int = Form(..., ge=0, le=2),
    question: str = Form(..., min_length=1, max_length=2000),
    scope: Literal['full', 'relevant'] = Form('relevant'),
    _csrf=Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    _validate_id(analysis_id, "analysis")
    if not question.strip():
        raise HTTPException(422, "invalid_question")
    workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    try:
        source = collect_retained_source(workspace, analysis_id, source_index)
    except ValueError as error:
        messages = {
            "source_scope_too_large": "Bản đọc vượt 120.000 ký tự hoặc 24.000 từ. Hãy chọn các trích đoạn cần thiết và dùng Phân tích bằng chứng.",
            "source_not_found": "Lượt đọc không còn trong hồ sơ. Hãy mở lại nguồn.",
            "source_read_truncated": "Bản HTML đã bị cắt khi lưu. Hãy đọc bản PDF hoặc phân tích các trích đoạn đã ghim.",
            "source_text_unavailable": "Chưa có chữ đọc được. Hãy đọc thêm trang hoặc dùng OCR trước.",
        }
        response = _workspace_page(
            request,
            "retained_source_error.html",
            {
                "workspace": workspace,
                "message": messages.get(
                    str(error),
                    "Không xác định được một bản nguồn nhất quán. Hãy mở lại nguồn trước khi phân tích.",
                ),
            },
        )
        response.status_code = 422
        return response
    try:
        result = await analyze_retained_source(question, source, relevant_only=scope == 'relevant')
    except RuntimeError as error:
        result = {"status": "provider_error", "error_type": type(error).__name__}
    identifier = str(uuid.uuid4())
    record = {
        "analysis_id": identifier,
        "kind": "retained_source_answer",
        "question": question,
        "source_scope": {key: value for key, value in source.items() if key != "pages"},
        "source_reads": [
            {key: value for key, value in page.items() if key != "text"}
            for page in source["pages"]
        ],
        "provider_calls": current_provider_calls() or [],
        **result,
    }
    selection = result.get("context_selection") or {}
    selected_count = int(selection.get("selected") or 0)
    logged = await log_interaction(
        trace_id=identifier,
        user_query="Retained-source analysis over saved official pages",
        bot_response=str(record["status"]),
        contexts=[],
        cached=False,
        session_id=workspace_id,
        client_id=client_id,
        user_id=user_id,
        request_status=f"retained_source_{record['status']}",
        observed_provider=record.get("provider"),
        observed_model=record.get("model"),
        context_count=selected_count,
        no_evidence=not bool(selected_count),
        technical_error={
            "stage": "retained_source", "error_type": record["status"],
        } if record["status"] in {"provider_error", "degraded", "invalid_structured_response"} else None,
        retrieval_trace={
            "mode": "retained_source_analysis",
            "selection_method": selection.get("method") or scope,
            "selected_passage_count": selected_count,
            "available_passage_count": int(selection.get("available") or 0),
            "source_input_sha256": source["input_sha256"],
            "readable_page_count": len(source.get("readable_pages") or []),
        },
        request_metadata={"method": "POST", "path": request.url.path},
    )
    record["admin_trace_status"] = "persisted" if logged else "unavailable"
    if not await save_workspace_analysis(
        workspace_id, record, client_id, user_id=user_id
    ):
        await update_interaction_request_status(identifier, "workspace_changed")
        raise HTTPException(409, "workspace_changed")
    return RedirectResponse(
        f"/workspaces/{workspace_id}/source-analysis/{identifier}", status_code=303
    )


@router.get("/workspaces/{workspace_id}/source-analysis/{analysis_id}")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def retained_source_result(
    request: Request,
    workspace_id: str,
    analysis_id: str,
    current_user=Depends(optional_user),
):
    _validate_id(analysis_id, "analysis")
    workspace, _, _ = await _owned_workspace(request, workspace_id, current_user)
    analysis = next(
        (
            row
            for row in workspace.get("analyses", [])
            if row.get("analysis_id") == analysis_id
            and row.get("kind") == "retained_source_answer"
        ),
        None,
    )
    if analysis is None:
        raise HTTPException(404, "analysis_not_found")
    markdown = re.sub(
        r"(?<![A-Za-z0-9\[])(p\d+-s\d+|source-metadata)(?![A-Za-z0-9\]])",
        r"[\1]",
        analysis.get("text", ""),
    )
    preview = report_preview(
        {
            "status": analysis.get("status"),
            "markdown": markdown,
            "evidence_snapshot": [
                {
                    "evidence_id": c.get("passage_id", ""),
                    "citation": "Thông tin trang nguồn"
                    if c.get("citation_kind") == "metadata"
                    else "Trang " + str(c["page"]),
                }
                for c in analysis.get("citations", [])
            ],
        }
    )
    return _workspace_page(
        request,
        "retained_source_answer.html",
        {
            "workspace": workspace,
            "analysis": analysis,
            "preview": preview,
            "workspace_user": current_user,
        },
    )
