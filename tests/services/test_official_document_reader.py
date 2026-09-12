from io import BytesIO
import pytest
import httpx
from pypdf import PdfWriter

from app.services.trusted_source_reader import read_source, SourceReadError


def blank_pdf(pages=6):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=300, height=400)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.mark.asyncio
async def test_official_attachment_reads_pages_not_navigation_and_marks_scan():
    urls = []

    def handler(request):
        urls.append(str(request.url))
        if request.url.host == "vanban.chinhphu.vn":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text='<title>Quy định</title><nav>Menu</nav><table><tr><td>Số ký hiệu</td><td>1/2026/NĐ-CP</td></tr><tr><td>Ngày có hiệu lực</td><td>09-09-2026</td></tr></table><a href="https://datafiles.chinhphu.vn/law.pdf">Bản ký</a>',
            )
        return httpx.Response(
            200, headers={"content-type": "application/pdf"}, content=blank_pdf()
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await read_source(
            "https://vanban.chinhphu.vn/?docid=123", client=client
        )
    assert len(urls) == 2
    assert result["text"] == ""
    assert result["requires_ocr"] is True
    assert result["page_count"] == 6 and result["next_page_start"] == 6
    assert result["attachment_url"] == "https://datafiles.chinhphu.vn/law.pdf"
    assert result["legal_effect_status"] == "unverified"
    assert result["document_number"] == "1/2026/NĐ-CP"
    assert result["reported_effective_from"] == "09-09-2026"


@pytest.mark.asyncio
async def test_reader_never_fetches_unapproved_attachment():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text='<title>Law</title><a href="https://evil.test/law.pdf">Bản ký</a>',
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await read_source("https://vanban.chinhphu.vn/?docid=1", client=client)
    assert len(seen) == 1
    assert result.get("content_status") == "metadata_only"


@pytest.mark.asyncio
async def test_pdf_page_window_rejects_out_of_range():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "application/pdf"}, content=blank_pdf(2)
            )
        )
    ) as client:
        with pytest.raises(SourceReadError, match="source_page_out_of_range"):
            await read_source(
                "https://datafiles.chinhphu.vn/law.pdf", page_start=3, client=client
            )


@pytest.mark.asyncio
async def test_caller_can_reduce_window_without_losing_page_position():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "application/pdf"}, content=blank_pdf()
            )
        )
    ) as client:
        result = await read_source(
            "https://datafiles.chinhphu.vn/law.pdf",
            page_start=3,
            page_limit=1,
            client=client,
        )
    assert (
        result["page_start"] == 3
        and result["page_end"] == 3
        and result["next_page_start"] == 4
    )


def test_ocr_window_does_not_clone_annotation_document_graph():
    from pypdf.generic import (
        ArrayObject,
        DictionaryObject,
        NameObject,
        TextStringObject,
    )
    from app.services.official_document_reader import _window

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=400)
    page[NameObject("/Annots")] = ArrayObject(
        [
            writer._add_object(
                DictionaryObject(
                    {NameObject("/Contents"): TextStringObject("annotation-only")}
                )
            )
        ]
    )
    out = BytesIO()
    writer.write(out)
    result = _window(out.getvalue(), 1, True, 1)
    from pypdf import PdfReader

    assert not PdfReader(BytesIO(result[2])).pages[0].get("/Annots")


@pytest.mark.asyncio
async def test_recoverable_pdf_metadata_is_flagged_instead_of_rejecting_page_content():
    from app.services.official_document_reader import extract_official_pdf

    payload = blank_pdf(1).replace(b"/Size", b"/Info 1 0 R\n/Size", 1)
    result = await extract_official_pdf(
        payload,
        url="https://datafiles.chinhphu.vn/a.pdf",
        attachment_url="https://datafiles.chinhphu.vn/a.pdf",
    )
    assert result["parser_recovered"] is True
    assert result["page_count"] == 1
