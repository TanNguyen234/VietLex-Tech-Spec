from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, Query, Form, Depends
from app.api.dependencies import optional_user, verify_csrf
from app.rate_limit import limiter
from app.services.legal_browser import SearchFilters, LegalBrowserBackendError
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.paths import APP_ROOT

from app.config import get_settings


router = APIRouter()
templates = Jinja2Templates(directory=APP_ROOT / "templates")
browser: Any | None = None


def document_sections(content: str) -> list[dict[str, str]]:
    """Add navigable anchors without rewriting or dropping source characters."""
    headings = list(
        re.finditer(
            r"(?m)^(?:Điều\s+\d+[a-zđ]?\b|Chương\s+[IVXLCDM\d]+\b)[^\r\n]*", content
        )
    )
    sections = []
    start = 0
    for index, heading in enumerate(headings):
        if index == 0 and heading.start():
            sections.append(
                {
                    "id": "preamble",
                    "title": "Mở đầu",
                    "text": content[: heading.start()],
                }
            )
        start = heading.start()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(content)
        sections.append(
            {
                "id": f"section-{index + 1}",
                "title": heading.group()[:180],
                "text": content[start:end],
            }
        )
    return sections or [{"id": "full-text", "title": "Toàn văn", "text": content}]


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


@router.get("/search", response_class=HTMLResponse)
async def legal_search(request: Request, q: str = "", legal_type: str = Query("", max_length=100),
                       authority: str = Query("", max_length=200), issued_from: str = "", issued_to: str = "", sort: str = "default"):
    query = q.strip()[:200]
    try:
        filters = SearchFilters(legal_type.strip(), authority.strip(), issued_from, issued_to, sort)
    except ValueError:
        raise HTTPException(422, "Bộ lọc ngày hoặc thứ tự không hợp lệ.") from None
    try:
        results = await asyncio.to_thread(_get_browser().search, query, 20, **({"filters": filters} if filters.active else {}))
    except LegalBrowserBackendError:
        raise HTTPException(503, "Không đọc được kết quả tra cứu. Vui lòng thử lại.") from None
    return templates.TemplateResponse(
        request,
        "legal_search.html",
        {"query": query, "results": results, "filters": filters},
    )


@router.get("/documents/{document_id}", response_class=HTMLResponse)
async def legal_document(request: Request, document_id: int):
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
