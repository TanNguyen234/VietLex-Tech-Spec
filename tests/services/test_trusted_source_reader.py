import hashlib
import pytest
from app.services.trusted_source_reader import (
    validate_source_url,
    extract_page,
    reconcile_sources,
)

G7_STREAM_URL = (
    "https://g7.cdnchinhphu.vn/api/download/stream?"
    "Url=abc_DEF-123~~&file_name=2025_301+%2B+302_64-2024-TT-NHNN.pdf"
)


@pytest.mark.parametrize(
    "url",
    [
        "http://vanban.chinhphu.vn/a",
        "https://vanban.chinhphu.vn.evil.test/a",
        "https://u:p@vanban.chinhphu.vn/a",
        "https://127.0.0.1/a",
        "https://vanban.chinhphu.vn:443/a",
    ],
)
def test_rejects_unapproved_origin_credentials_and_port(url):
    with pytest.raises(ValueError):
        validate_source_url(url)


def test_accepts_official_g7_stream_pdf_url():
    assert validate_source_url(G7_STREAM_URL) == G7_STREAM_URL


@pytest.mark.parametrize(
    "url",
    [
        "https://g7.cdnchinhphu.vn.evil.test/api/download/stream?Url=opaque&file_name=law.pdf",
        "https://g7.cdnchinhphu.vn:443/api/download/stream?Url=opaque&file_name=law.pdf",
        "https://g7.cdnchinhphu.vn/other?Url=opaque&file_name=law.pdf",
        "https://g7.cdnchinhphu.vn/api/download/stream?Url=https%3A%2F%2Fevil.test%2Fa.pdf&file_name=a.pdf",
        "https://g7.cdnchinhphu.vn/api/download/stream?Url=opaque&file_name=../law.pdf",
        "https://g7.cdnchinhphu.vn/api/download/stream?Url=opaque&file_name=law.pdf&extra=1",
        "https://g7.cdnchinhphu.vn/api/download/stream?Url=one&Url=two&file_name=law.pdf",
        "https://g7.cdnchinhphu.vn/api/download/stream?Url=opaque&file_name=law.txt",
    ],
)
def test_rejects_unbounded_g7_stream_urls(url):
    with pytest.raises(ValueError):
        validate_source_url(url)


def test_extract_page_excludes_scripts_and_requires_text():
    result = extract_page(
        "<html><title>Văn bản</title><nav>menu</nav><article><p>Điều 1. Nội dung văn bản.</p></article><script>secret()</script></html>",
        "https://vanban.chinhphu.vn/a",
    )
    assert "secret" not in result["text"] and "menu" not in result["text"]
    assert result["text"] == "Điều 1. Nội dung văn bản."
    assert result["legal_effect_status"] == "unverified"


def test_extract_page_retains_complete_mid_size_law_for_bounded_analysis():
    from app.services.retained_source_analysis import collect_retained_source, relevant_source_passages

    html = "<html><body><p>Điều 1. Phạm vi</p>" + "<p>Nội dung pháp luật mẫu.</p>" * 2500 + "<p>Điều 2. Hiệu lực</p></body></html>"
    result = extract_page(html, "https://vanban.chinhphu.vn/default.aspx?docid=123")
    assert 20_000 < result["extracted_characters"] < 120_000
    assert result["stored_characters"] == result["extracted_characters"]
    assert result["truncated"] is False
    workspace = {"analyses": [{"kind": "trusted_sources", "analysis_id": "a1", "result": {"sources": [result]}}]}
    source = collect_retained_source(workspace, "a1", 0)
    passages = relevant_source_passages("Điều 2 hiệu lực", source, limit=10)
    assert source["characters"] == result["extracted_characters"]
    assert len(passages) <= 10


def test_extract_page_hash_matches_truncated_retained_text():
    full_text = "x" * 120_001
    result = extract_page(
        f"<article>{full_text}</article>",
        "https://vanban.chinhphu.vn/default.aspx?docid=large-html",
    )

    assert result["truncated"] is True
    assert len(result["text"]) == 120_000
    assert result["sha256"] == hashlib.sha256(result["text"].encode()).hexdigest()
    html = f"<article>{full_text}</article>"
    assert result["document_sha256"] == hashlib.sha256(html.encode()).hexdigest()


def test_reconciliation_keeps_different_sources_and_flags_text_difference():
    rows = [
        {
            "url": "https://vanban.chinhphu.vn/a",
            "sha256": "1",
            "document_number": "1/2025",
        },
        {"url": "https://baochinhphu.vn/b", "sha256": "1", "document_number": "1/2025"},
        {"url": "https://baochinhphu.vn/c", "sha256": "2", "document_number": "1/2025"},
    ]
    result = reconcile_sources(rows)
    assert len(result["sources"]) == 3
    assert result["duplicates"][0]["urls"] == [rows[0]["url"], rows[1]["url"]]
    assert result["potential_text_conflicts"][0]["legal_conflict"] == "not_assessed"


@pytest.mark.asyncio
async def test_reader_rejects_redirect_and_oversized_body_without_following():
    import httpx
    from app.services.trusted_source_reader import read_source, SourceReadError

    seen = []

    def redirect(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(redirect)) as client:
        with pytest.raises(SourceReadError, match="source_http_302"):
            await read_source("https://vanban.chinhphu.vn/a", client=client)
    assert len(seen) == 1
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, headers={"content-type": "text/html"}, content=b"x" * 1_000_001
            )
        )
    ) as client:
        with pytest.raises(SourceReadError, match="source_body_too_large"):
            await read_source("https://vanban.chinhphu.vn/a", client=client)


@pytest.mark.asyncio
async def test_reader_extracts_g7_stream_pdf_attachment(monkeypatch):
    import httpx
    from unittest.mock import AsyncMock
    from app.services.trusted_source_reader import read_source

    extractor = AsyncMock(return_value={"text": "PDF text", "method": "pdf_text"})
    monkeypatch.setattr("app.services.official_document_reader.extract_official_pdf", extractor)
    detail = "https://congbao.chinhphu.vn/van-ban/law-1.htm"
    requests = []

    def respond(request):
        requests.append(str(request.url))
        if str(request.url) == detail:
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text=f'<title>Law</title><a href="{G7_STREAM_URL}">PDF</a>',
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/octet-stream"},
            content=b"%PDF-test",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await read_source(
            detail,
            question="Trách nhiệm người sử dụng lao động",
            smart_pages=True,
            client=client,
        )

    assert requests == [detail, G7_STREAM_URL]
    assert result["attachments"] == [G7_STREAM_URL]
    assert result["text"] == "PDF text"
    assert extractor.await_args.kwargs["attachment_url"] == G7_STREAM_URL
    assert extractor.await_args.kwargs["question"] == "Trách nhiệm người sử dụng lao động"
    assert extractor.await_args.kwargs["smart_pages"] is True


@pytest.mark.asyncio
async def test_reader_does_not_fetch_arbitrary_url_from_g7_stream_parameter():
    import httpx
    from app.services.trusted_source_reader import read_source

    detail = "https://congbao.chinhphu.vn/van-ban/law-2.htm"
    unsafe = (
        "https://g7.cdnchinhphu.vn/api/download/stream?"
        "Url=https%3A%2F%2F127.0.0.1%2Fprivate.pdf&file_name=private.pdf"
    )
    requests = []

    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=f'<title>Law</title><a href="{unsafe}">PDF</a>',
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await read_source(detail, client=client)

    assert requests == [detail]
    assert result["content_status"] == "metadata_only"
    assert result["text"] == ""


@pytest.mark.asyncio
async def test_reader_does_not_follow_g7_stream_redirect():
    import httpx
    from app.services.trusted_source_reader import read_source, SourceReadError

    requests = []

    def redirect(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(redirect)) as client:
        with pytest.raises(SourceReadError, match="source_http_302"):
            await read_source(G7_STREAM_URL, client=client)

    assert requests == [G7_STREAM_URL]


@pytest.mark.asyncio
async def test_reader_follows_bounded_official_pdf_redirect_without_deep_mode(monkeypatch):
    import httpx
    from unittest.mock import AsyncMock
    from app.services.trusted_source_reader import read_source
    extractor = AsyncMock(return_value={'text': 'Điều 328. Fixture text', 'method': 'pdf_text'})
    monkeypatch.setattr('app.services.official_document_reader.extract_official_pdf', extractor)
    destination = 'https://datafiles.chinhphu.vn/law.pdf'
    seen = []
    def respond(request):
        seen.append(str(request.url))
        return (httpx.Response(302, headers={'location': destination}) if len(seen) == 1
                else httpx.Response(200, headers={'content-type': 'application/pdf'}, content=b'%PDF-fixture'))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await read_source(G7_STREAM_URL, client=client)
    assert seen == [G7_STREAM_URL, destination]
    assert result['text'] == 'Điều 328. Fixture text'
    assert extractor.await_args.kwargs['attachment_url'] == destination


@pytest.mark.asyncio
async def test_reader_transport_failure_has_sanitized_boundary_diagnostic():
    import httpx
    from app.services.trusted_source_reader import read_source, SourceReadError
    def fail(request):
        raise httpx.ConnectTimeout('private raw credential=do-not-expose', request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(SourceReadError) as failure:
            await read_source(G7_STREAM_URL, client=client)
    assert failure.value.kind == 'source_transport_error'
    assert getattr(failure.value, 'transport_kind', None) == 'connect_timeout'
    assert 'do-not-expose' not in str(failure.value)


@pytest.mark.asyncio
async def test_docid_page_with_inline_articles_is_readable_without_pdf():
    import httpx
    from app.services.trusted_source_reader import read_source

    html = (
        "<html><title>Luật mẫu</title><body>"
        "<p><b>Điều 1. Phạm vi</b></p><p>Áp dụng cho tổ chức.</p>"
        "<p><b>Điều 2. Hiệu lực</b></p><p>Có hiệu lực từ ngày ban hành.</p>"
        "</body></html>"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, headers={"content-type": "text/html"}, content=html.encode())
    )) as client:
        result = await read_source("https://vanban.chinhphu.vn/default.aspx?docid=123", client=client)

    assert result["method"] == "visible_html_text"
    assert "Điều 2. Hiệu lực" in result["text"]
    assert result.get("content_status") != "metadata_only"


@pytest.mark.asyncio
async def test_docid_metadata_page_without_articles_remains_unreadable():
    import httpx
    from app.services.trusted_source_reader import read_source

    html = "<html><title>Chi tiết văn bản</title><body>Số ký hiệu 12/2026/QH15. Tải văn bản để xem nội dung.</body></html>"
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, headers={"content-type": "text/html"}, content=html.encode())
    )) as client:
        result = await read_source("https://vanban.chinhphu.vn/default.aspx?docid=456", client=client)

    assert result["content_status"] == "metadata_only"
    assert result["text"] == ""


@pytest.mark.asyncio
async def test_docid_page_does_not_mark_articles_beyond_retained_text_as_readable():
    import httpx
    from app.services.trusted_source_reader import read_source

    html = (
        "<html><body><p>" + "Danh mục văn bản. " * 8000 + "</p>"
        "<p>Điều 1. Phạm vi</p><p>Nội dung một.</p>"
        "<p>Điều 2. Hiệu lực</p><p>Nội dung hai.</p></body></html>"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, headers={"content-type": "text/html"}, content=html.encode())
    )) as client:
        result = await read_source("https://vanban.chinhphu.vn/default.aspx?docid=789", client=client)

    assert result["content_status"] == "metadata_only"
