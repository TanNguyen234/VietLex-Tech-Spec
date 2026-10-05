import pytest
from app.services.trusted_source_reader import (
    validate_source_url,
    extract_page,
    reconcile_sources,
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


def test_extract_page_excludes_scripts_and_requires_text():
    result = extract_page(
        "<html><title>Văn bản</title><nav>menu</nav><article><p>Điều 1. Nội dung văn bản.</p></article><script>secret()</script></html>",
        "https://vanban.chinhphu.vn/a",
    )
    assert "secret" not in result["text"] and "menu" not in result["text"]
    assert result["text"] == "Điều 1. Nội dung văn bản."
    assert result["legal_effect_status"] == "unverified"


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
        "<html><body><p>" + "Danh mục văn bản. " * 1300 + "</p>"
        "<p>Điều 1. Phạm vi</p><p>Nội dung một.</p>"
        "<p>Điều 2. Hiệu lực</p><p>Nội dung hai.</p></body></html>"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, headers={"content-type": "text/html"}, content=html.encode())
    )) as client:
        result = await read_source("https://vanban.chinhphu.vn/default.aspx?docid=789", client=client)

    assert result["content_status"] == "metadata_only"
