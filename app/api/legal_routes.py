from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.services.legal_browser import LegalBrowser


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
browser = LegalBrowser.from_settings(get_settings())


def _safe_source_url(value: str) -> str | None:
    parsed = urlparse((value or "").strip())
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value.strip()
    return None


@router.get("/search", response_class=HTMLResponse)
async def legal_search(request: Request, q: str = ""):
    query = q.strip()[:200]
    results = await asyncio.to_thread(browser.search, query, 20)
    return templates.TemplateResponse(
        request,
        "legal_search.html",
        {"query": query, "results": results},
    )


@router.get("/documents/{document_id}", response_class=HTMLResponse)
async def legal_document(request: Request, document_id: int):
    if document_id < 0:
        raise HTTPException(status_code=404, detail="Document not found")
    document = await asyncio.to_thread(browser.get_document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return templates.TemplateResponse(
        request,
        "legal_document.html",
        {
            "document": document,
            "source_url": _safe_source_url(document.metadata.source_url),
        },
    )


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    return templates.TemplateResponse(request, "privacy.html", {})


@router.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    return templates.TemplateResponse(request, "terms.html", {})
