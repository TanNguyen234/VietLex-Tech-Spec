from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
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
async def legal_search(request: Request, q: str = ""):
    query = q.strip()[:200]
    results = await asyncio.to_thread(_get_browser().search, query, 20)
    return templates.TemplateResponse(
        request,
        "legal_search.html",
        {"query": query, "results": results},
    )


@router.get("/documents/{document_id}", response_class=HTMLResponse)
async def legal_document(request: Request, document_id: int):
    if document_id < 0:
        raise HTTPException(status_code=404, detail="Document not found")
    document = await asyncio.to_thread(_get_browser().get_document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return templates.TemplateResponse(
        request,
        "legal_document.html",
        {
            "document": document,
            "sections": document_sections(document.content),
            "source_url": _safe_source_url(document.metadata.source_url),
        },
    )


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    return templates.TemplateResponse(request, "privacy.html", {})


@router.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    return templates.TemplateResponse(request, "terms.html", {})
