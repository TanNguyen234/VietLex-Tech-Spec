"""Bounded official PDF page windows with explicit scan and OCR provenance."""

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO

from app.services.workspace_documents import DocumentExtractionError
from app.services.trusted_source_reader import SourceReadError

PDF_MAX_BYTES = 20_000_000
PAGE_WINDOW = 5
TEXT_LIMIT = 20_000


def _window(payload: bytes, page_start: int, use_ocr: bool, page_limit: int):
    from pypdf import PdfWriter, PdfReader
    from pypdf.errors import PdfReadError

    try:
        recovered = False
        try:
            reader = PdfReader(BytesIO(payload), strict=True)
        except PdfReadError:
            reader = PdfReader(BytesIO(payload), strict=False)
            recovered = True
        if reader.is_encrypted:
            raise SourceReadError("source_encrypted_pdf")
        count = len(reader.pages)
        if not 1 <= count <= 200:
            raise SourceReadError("source_pdf_page_limit")
        if not 1 <= page_start <= count:
            raise SourceReadError("source_page_out_of_range")
        if not 1 <= page_limit <= PAGE_WINDOW:
            raise SourceReadError("source_page_window_invalid")
        end = min(count, page_start + page_limit - 1)
        pages = []
        writer = PdfWriter()
        for index in range(page_start - 1, end):
            text = reader.pages[index].extract_text() or ""
            if len(text) > TEXT_LIMIT:
                raise SourceReadError("source_page_text_limit")
            pages.append({"page": index + 1, "text": text})
            if use_ocr:
                # Signature/widget references can pull the entire PDF into a page slice.
                # Only page contents are transcribed; originals and their digest stay intact.
                writer.add_page(reader.pages[index], excluded_keys=("/B", "/Annots"))
        batch = None
        if use_ocr:
            output = BytesIO()
            writer.write(output)
            batch = output.getvalue()
        return count, pages, batch, recovered
    except SourceReadError:
        raise
    except Exception:
        raise SourceReadError("source_malformed_pdf") from None


async def extract_official_pdf(
    payload: bytes,
    *,
    url: str,
    attachment_url: str,
    title: str = "",
    page_start: int = 1,
    use_ocr: bool = False,
    page_limit: int = PAGE_WINDOW,
):
    if len(payload) > PDF_MAX_BYTES or not payload.startswith(b"%PDF-"):
        raise SourceReadError("source_pdf_body_invalid")
    count, pages, batch, recovered = await asyncio.to_thread(
        _window, payload, page_start, use_ocr, page_limit
    )
    method = "pdf_text"
    provider = model = None
    if use_ocr:
        from app.services.workspace_ocr import extract_ocr_document

        try:
            document = await extract_ocr_document(
                "official-pages.pdf", "application/pdf", batch
            )
        except DocumentExtractionError as error:
            raise SourceReadError(str(error)) from None
        pages = [
            {
                "page": original["page"],
                "text": "\n\n".join(
                    c.text for c in document.clauses if c.page == index
                ),
            }
            for index, original in enumerate(pages, 1)
        ]
        method = "vertex_ocr"
        provider, model = document.ocr_provider, document.ocr_model
    full_text = "\n\n".join(page["text"] for page in pages).strip()
    if len(full_text) > TEXT_LIMIT:
        raise SourceReadError("source_page_window_text_limit")
    missing = [page["page"] for page in pages if not page["text"].strip()]
    end = pages[-1]["page"]
    return {
        "url": url,
        "attachment_url": attachment_url,
        "title": title or attachment_url.rsplit("/", 1)[-1],
        "text": full_text,
        "sha256": sha256(full_text.encode()).hexdigest(),
        "document_sha256": sha256(payload).hexdigest(),
        "parser_recovered": recovered,
        "ocr_input_sha256": sha256(batch).hexdigest() if batch else None,
        "ocr_input_transform": "selected_page_content_without_annotations"
        if batch
        else None,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "extracted_characters": len(full_text),
        "stored_characters": len(full_text),
        "truncated": page_start > 1 or end < count,
        "method": method,
        "legal_effect_status": "unverified",
        "document_number": None,
        "content_status": "readable" if full_text else "metadata_only",
        "pages": pages,
        "page_count": count,
        "page_start": page_start,
        "page_end": end,
        "next_page_start": end + 1 if end < count else None,
        "requires_ocr": bool(missing) and not use_ocr,
        "unreadable_pages": missing,
        "ocr_provider": provider,
        "ocr_model": model,
    }
