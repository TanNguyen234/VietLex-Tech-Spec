"""Bounded public-page reader; allowlisted origins only, no redirect/auth bypass."""

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
from urllib.parse import urlsplit
import httpx

APPROVED_HOSTS = frozenset({"vanban.chinhphu.vn", "baochinhphu.vn"})
_MAX_BYTES = 1_000_000
_MAX_TEXT = 20_000
_SEMAPHORE = asyncio.Semaphore(2)


def validate_source_url(url: str) -> str:
    parsed = urlsplit(url)
    if (
        len(url) > 2000
        or any(ord(c) < 33 for c in url)
        or parsed.scheme != "https"
        or parsed.netloc not in APPROVED_HOSTS
        or parsed.fragment
    ):
        raise ValueError("source_origin_not_approved")
    return url


class SourceReadError(RuntimeError):
    def __init__(self, kind):
        super().__init__(kind)
        self.kind = kind


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.in_title = False
        self.title = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "nav", "header", "footer", "noscript"}:
            self.hidden += 1
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag in {"script", "style", "nav", "header", "footer", "noscript"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
        elif not self.hidden and data.strip():
            self.parts.append(data.strip())


def extract_page(html: str, url: str) -> dict:
    validate_source_url(url)
    if len(html.encode("utf-8")) > _MAX_BYTES:
        raise SourceReadError("source_body_too_large")
    parser = _TextParser()
    parser.feed(html)
    full_text = "\n".join(parser.parts)
    if not full_text.strip():
        raise SourceReadError("source_text_unavailable")
    return {
        "url": url,
        "title": "".join(parser.title)[:300],
        "text": full_text[:_MAX_TEXT],
        "sha256": hashlib.sha256(full_text.encode()).hexdigest(),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "extracted_characters": len(full_text),
        "stored_characters": min(len(full_text), _MAX_TEXT),
        "truncated": len(full_text) > _MAX_TEXT,
        "method": "visible_html_text",
        "legal_effect_status": "unverified",
        "document_number": None,
    }


async def read_source(url: str, *, client=None) -> dict:
    validate_source_url(url)

    async def fetch(session):
        async with session.stream("GET", url, follow_redirects=False) as response:
            if response.status_code != 200:
                raise SourceReadError("source_http_" + str(response.status_code))
            if response.headers.get("content-type", "").split(";")[0].strip() not in {
                "text/html",
                "application/xhtml+xml",
            }:
                raise SourceReadError("source_content_type_unsupported")
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > _MAX_BYTES:
                    raise SourceReadError("source_body_too_large")
            try:
                html = bytes(data).decode("utf-8", errors="strict")
            except UnicodeDecodeError as error:
                raise SourceReadError("source_encoding_unsupported") from error
            return extract_page(html, url)

    async with _SEMAPHORE:
        try:
            async with asyncio.timeout(20):
                if client is not None:
                    return await fetch(client)
                async with httpx.AsyncClient(
                    timeout=10,
                    trust_env=False,
                    headers={"User-Agent": "VietLex-Reviewer/1.0"},
                ) as session:
                    return await fetch(session)
        except (httpx.HTTPError, TimeoutError) as error:
            raise SourceReadError("source_transport_error") from error


def reconcile_sources(sources: list[dict]) -> dict:
    if len(sources) > 10:
        raise ValueError("source_scope_too_large")
    by_hash, by_number = defaultdict(list), defaultdict(list)
    for source in sources:
        by_hash[source["sha256"]].append(source)
        if source.get("document_number"):
            by_number[source["document_number"]].append(source)
    return {
        "sources": sources,
        "duplicates": [
            {"sha256": sha, "urls": [s["url"] for s in group]}
            for sha, group in by_hash.items()
            if len(group) > 1
        ],
        "potential_text_conflicts": [
            {
                "document_number": number,
                "urls": [s["url"] for s in group],
                "legal_conflict": "not_assessed",
            }
            for number, group in by_number.items()
            if len({s["sha256"] for s in group}) > 1
        ],
    }
