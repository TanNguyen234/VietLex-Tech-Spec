from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import date
from app.legal_registry_database import registry_records_batch, RegistryUnavailable
from app.services.legal_registry import registry_view, STATUS_LABELS
from typing import Any, Literal
from urllib.parse import urlparse, urlencode

from fastapi import APIRouter, HTTPException, Request, Query, Form, Depends
from app.api.dependencies import optional_user, verify_csrf
from app.rate_limit import limiter
from app.services.legal_browser import SearchFilters, LegalBrowserBackendError
from app.services.document_structure import document_sections
from app.services.body_search import BodySearchUnavailable
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.paths import APP_ROOT

from app.config import get_settings


router = APIRouter()
templates = Jinja2Templates(directory=APP_ROOT / "templates")
browser: Any | None = None


def _get_browser() -> Any:
    global browser
    if browser is None:
        from app.services.legal_browser import LegalBrowser

        browser = LegalBrowser.from_settings(get_settings())
    return browser


def _safe_source_url(value: str) -> str | None:
    parsed = urlparse((value or "").strip())
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value.strip()
    return None


def _registry_day(value):
    day = value or date.today().isoformat()
    try:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError()
    except ValueError:
        raise HTTPException(422, "invalid_as_of_date") from None
    return day


async def _registry_context(numbers, day):
    numbers = list(dict.fromkeys(number for number in numbers if number.strip()))
    results, error = {}, None
    try:
        rows = await asyncio.wait_for(registry_records_batch(numbers), timeout=3)
        results = {number: registry_view(number, day, rows) for number in numbers}
    except (RegistryUnavailable, TimeoutError, ValueError) as exc:
        logging.getLogger(__name__).warning("legal_registry_lookup_failed: %s", type(exc).__name__, extra={"error_type": type(exc).__name__})
        error = "Không đọc được registry hoặc lịch sử vượt giới hạn. Chưa thể đối chiếu hiệu lực; nội dung văn bản vẫn đọc được."
    return {"registry_results": results, "registry_error": error, "as_of": day, "status_labels": STATUS_LABELS}


@router.get("/search", response_class=HTMLResponse)
async def legal_search(request: Request, q: str = "", legal_type: str = Query("", max_length=100),
                       authority: str = Query("", max_length=200), issued_from: str = "", issued_to: str = "", sort: str = "default",
                       scope: Literal["metadata", "body"] = "metadata", offset: int = Query(0, ge=0, le=1000),
                       as_of: str = Query("", max_length=10)):
    day = _registry_day(as_of)
    query = q.strip()[:200]
    try:
        filters = SearchFilters(legal_type.strip(), authority.strip(), issued_from, issued_to, sort)
    except ValueError:
        raise HTTPException(422, "Bộ lọc ngày hoặc thứ tự không hợp lệ.") from None
    current = _get_browser()
    coverage = await asyncio.to_thread(current.body_coverage) if hasattr(current, "body_coverage") else None
    next_page = previous_page = None
    try:
        if scope == "body":
            results = await asyncio.to_thread(current.search_body, query, filters=filters, limit=21, offset=offset)
            params = dict(request.query_params)
            if len(results) > 20 and offset < 1000:
                params["offset"] = str(min(offset + 20, 1000))
                next_page = "/search?" + urlencode(params)
            if offset:
                params["offset"] = str(max(0, offset - 20))
                previous_page = "/search?" + urlencode(params)
            results = results[:20]
        else:
            results = await asyncio.to_thread(current.search, query, 20, **({"filters": filters} if filters.active else {}))
    except BodySearchUnavailable:
        raise HTTPException(503, "Chưa có chỉ mục toàn văn sẵn sàng cho kho dữ liệu này. Hãy tìm theo số hiệu/tiêu đề hoặc tìm nguồn chính thức.") from None
    except LegalBrowserBackendError:
        raise HTTPException(503, "Không đọc được kết quả tra cứu. Vui lòng thử lại.") from None
    return templates.TemplateResponse(
        request,
        "legal_search.html",
        {"query": query, "results": results, "filters": filters, "scope": scope, "body_coverage": coverage,
         "next_page": next_page, "previous_page": previous_page, "as_of_query": as_of,
         **await _registry_context([result["document_number"] if scope == "body" else result.document_number for result in results], day)},
    )


@router.get("/documents/{document_id}", response_class=HTMLResponse)
async def legal_document(request: Request, document_id: int, as_of: str = Query("", max_length=10)):
    day = _registry_day(as_of)
    if document_id < 0:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        document = await asyncio.to_thread(_get_browser().get_document, document_id)
    except LegalBrowserBackendError:
        raise HTTPException(503, "Không đọc được văn bản nguồn.") from None
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    from app.api.workspace_routes import _workspace_page
    return _workspace_page(
        request,
        "legal_document.html",
        {
            "document": document,
            "sections": document_sections(document.content),
            "source_url": _safe_source_url(document.metadata.source_url),
            **await _registry_context([document.metadata.document_number], day),
        },
    )


@router.post("/documents/{document_id}/sections/{section_id}/pin")
@limiter.limit(get_settings().SESSION_RATE_LIMIT)
async def pin_document_section(
    request: Request, document_id: int, section_id: str,
    workspace_id: str = Form(..., max_length=100), note: str = Form("", max_length=500),
    _csrf: str = Depends(verify_csrf), current_user=Depends(optional_user),
):
    from app.api import workspace_routes as workspaces
    _, client_id, user_id = await workspaces._owned_workspace(request, workspace_id, current_user)
    try:
        document = await asyncio.to_thread(_get_browser().get_document, document_id)
    except LegalBrowserBackendError:
        raise HTTPException(503, "Không đọc được văn bản nguồn.") from None
    section = next((item for item in document_sections(document.content) if item["id"] == section_id), None) if document else None
    if section is None:
        raise HTTPException(404, "Section not found")
    if len(section["text"]) > 4000:
        raise HTTPException(422, "Điều khoản vượt giới hạn 4.000 ký tự; hãy chọn trích đoạn qua câu trả lời có dẫn nguồn.")
    metadata = document.metadata
    citation = f"{metadata.document_number} · {section['title']}"
    evidence = {
        "evidence_id": hashlib.sha256(f"{document_id}:{section_id}:{section['text']}".encode()).hexdigest()[:24],
        "document_id": document_id, "document_number": metadata.document_number,
        "title": metadata.title, "citation": citation, "source_url": _safe_source_url(metadata.source_url),
        "original": section["text"], "excerpt": section["text"], "note": note.strip(),
        "trace_id": f"document-{document_id}", "source_kind": "legal_evidence",
        "introduced_by_claim": "", "section_id": section_id,
    }
    if not await workspaces.pin_workspace_evidence(workspace_id, evidence, client_id, user_id=user_id):
        raise HTTPException(409, "duplicate_or_workspace_limit")
    return {"status": "pinned"}


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    return templates.TemplateResponse(request, "privacy.html", {})


@router.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    return templates.TemplateResponse(request, "terms.html", {})
