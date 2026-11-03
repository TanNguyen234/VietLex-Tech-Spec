"""Bounded public-page reader; allowlisted origins only, no redirect/auth bypass."""

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import re
import socket
import ssl
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlsplit, urljoin
import httpx

from app.services.runtime_errors import SourceReadError

_G7_STREAM_HOST = "g7.cdnchinhphu.vn"
_G7_STREAM_PATH = "/api/download/stream"
APPROVED_HOSTS = frozenset({
    "vbpl.vn",
    "vanban.chinhphu.vn",
    "baochinhphu.vn",
    "datafiles.chinhphu.vn",
    "congbao.chinhphu.vn",
    "congbaocdn.chinhphu.vn",
    _G7_STREAM_HOST,
})
_G7_STREAM_TOKEN = re.compile(r"[A-Za-z0-9_-]+~{0,2}")
_G7_STREAM_FILENAME = re.compile(r"[\w .()+-]{1,251}\.pdf", re.IGNORECASE)
_MAX_BYTES = 1_000_000
_MAX_TEXT = 120_000
_SEMAPHORE = asyncio.Semaphore(2)


def _transport_cause(error: BaseException) -> str:
    """Classify bounded exception chains without exposing messages/endpoints."""
    pending, labels = [error], set()
    for _ in range(8):
        if not pending:
            break
        error = pending.pop()
        if isinstance(error, ssl.SSLCertVerificationError):
            labels.add({
                20: 'tls_certificate_untrusted_issuer',
                21: 'tls_certificate_untrusted_issuer',
                10: 'tls_certificate_expired',
                62: 'tls_certificate_hostname_mismatch',
            }.get(getattr(error, 'verify_code', None), 'tls_certificate_verification'))
            continue
        if isinstance(error, BaseExceptionGroup):
            if len(pending) + len(error.exceptions) > 8:
                return 'unknown'
            pending.extend(error.exceptions)
            continue
        for cls, label in (
            (ssl.SSLError, 'tls'), (socket.gaierror, 'dns'),
            (ConnectionRefusedError, 'connection_refused'),
            (ConnectionResetError, 'connection_reset'),
        ):
            if isinstance(error, cls):
                labels.add(label)
                break
        else:
            cause = error.__cause__ or error.__context__
            if cause is not None:
                pending.append(cause)
            else:
                labels.add('unknown')
    return labels.pop() if not pending and len(labels) == 1 else 'unknown'


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
    if parsed.hostname == _G7_STREAM_HOST:
        if parsed.path != _G7_STREAM_PATH:
            raise ValueError("source_origin_not_approved")
        try:
            parameters = parse_qsl(
                parsed.query,
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=2,
            )
        except ValueError:
            raise ValueError("source_origin_not_approved") from None
        values = dict(parameters)
        if (
            len(parameters) != 2
            or set(values) != {"Url", "file_name"}
            or not _G7_STREAM_TOKEN.fullmatch(values.get("Url", ""))
            or not _G7_STREAM_FILENAME.fullmatch(
                values.get("file_name", "")
            )
        ):
            raise ValueError("source_origin_not_approved")
    return url


def _is_pdf_attachment_url(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.path.lower().endswith(".pdf") or (
        parsed.netloc == _G7_STREAM_HOST and parsed.path == _G7_STREAM_PATH
    )


def is_official_document_url(url: str) -> bool:
    """Exclude portal categories/news/navigation before scheduling a legal read."""
    try:
        parsed = urlsplit(validate_source_url(url))
    except (ValueError, TypeError):
        return False
    if _is_pdf_attachment_url(url):
        return True
    query = dict(parse_qsl(parsed.query))
    if parsed.hostname == "vanban.chinhphu.vn":
        return any(key.lower() == "docid" and value.isdecimal() for key, value in query.items())
    if parsed.hostname == "congbao.chinhphu.vn":
        return bool(re.fullmatch(r"/van-ban/[^/]+-\d+(?:/\d+)?\.htm", parsed.path))
    if parsed.hostname == "vbpl.vn":
        return "vbpq-" in parsed.path.lower() and any(key.lower() == "itemid" and value.isdecimal() for key, value in query.items())
    return False


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.in_title = False
        self.title = []
        self.parts = []
        self.attachments = []
        self.links = []
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in {'a', 'iframe'}:
            link = values.get('data-href') or values.get('href') or values.get('src') or ''
            if tag == 'a':
                self.anchor = [link, ""]
            if _is_pdf_attachment_url(link):
                self.attachments.append(link)
        if tag in {"script", "style", "nav", "header", "footer", "noscript"}:
            self.hidden += 1
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor is not None:
            self.links.append(self.anchor)
            self.anchor = None
        if tag in {"script", "style", "nav", "header", "footer", "noscript"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.anchor is not None:
            self.anchor[1] += data
        if self.in_title:
            self.title.append(data)
        elif not self.hidden and data.strip():
            self.parts.append(data.strip())


def _contains_inline_articles(parts: list[str]) -> bool:
    numbers = {
        int(match.group(1))
        for part in parts
        if (match := re.match(r"^\s*(?:Điều|Dieu)\s+(\d{1,4})\b\s*[.:]?", part, re.IGNORECASE))
    }
    return len(numbers) >= 2


def extract_page(html: str, url: str) -> dict:
    validate_source_url(url)
    if len(html.encode("utf-8")) > _MAX_BYTES:
        raise SourceReadError("source_body_too_large")
    parser = _TextParser()
    parser.feed(html)
    full_text = "\n".join(parser.parts)
    if not full_text.strip():
        raise SourceReadError("source_text_unavailable")
    retained_text = full_text[:_MAX_TEXT]
    return {
        "url": url,
        "title": "".join(parser.title)[:300],
        "text": retained_text,
        "sha256": hashlib.sha256(retained_text.encode()).hexdigest(),
        "document_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "extracted_characters": len(full_text),
        "stored_characters": min(len(full_text), _MAX_TEXT),
        "truncated": len(full_text) > _MAX_TEXT,
        "method": "visible_html_text",
        "legal_effect_status": "unverified",
        "document_number": None,
    }


async def read_source(url: str, *, question: str = "", smart_pages: bool = False,
                      page_start: int = 1, use_ocr: bool = False,
                      page_limit: int = 5, client=None, deep_read: bool = False) -> dict:
    validate_source_url(url)
    if deep_read and (use_ocr or not smart_pages or not 1 <= page_limit <= 20):
        raise SourceReadError("source_deep_read_mode_invalid")

    async def fetch(session, target=url, *, title='', attachment=False, redirects=0):
        validate_source_url(target)
        async with session.stream("GET", target, follow_redirects=False) as response:
            if response.is_redirect:
                if redirects >= 3:
                    raise SourceReadError("source_redirect_limit")
                location = response.headers.get("location")
                if not location:
                    raise SourceReadError("source_redirect_invalid")
                try:
                    destination = validate_source_url(urljoin(target, location))
                except ValueError:
                    if deep_read:
                        raise
                    raise SourceReadError("source_http_" + str(response.status_code)) from None
                return await fetch(session, destination, title=title, attachment=attachment, redirects=redirects + 1)
            if response.status_code != 200:
                raise SourceReadError("source_http_" + str(response.status_code))
            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            is_pdf = content_type == 'application/pdf' or (
                content_type == 'application/octet-stream' and _is_pdf_attachment_url(target))
            if not is_pdf and content_type not in {
                "text/html",
                "application/xhtml+xml",
            }:
                raise SourceReadError("source_content_type_unsupported")
            data = bytearray()
            byte_limit = _MAX_BYTES
            if is_pdf:
                from app.services.official_document_reader import PDF_MAX_BYTES
                byte_limit = PDF_MAX_BYTES
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > byte_limit:
                    raise SourceReadError("source_body_too_large")
            if is_pdf:
                from app.services.official_document_reader import extract_official_pdf
                return await extract_official_pdf(bytes(data), url=url, attachment_url=target,
                                                  title=title, page_start=page_start, use_ocr=use_ocr,
                                                  page_limit=page_limit, question=question,
                                                  smart_pages=smart_pages,
                                                  **({"deep_read": True} if deep_read else {}))
            try:
                html = bytes(data).decode("utf-8", errors="strict")
            except UnicodeDecodeError as error:
                raise SourceReadError("source_encoding_unsupported") from error
            result = extract_page(html, url)
            parser = _TextParser()
            parser.feed(html)
            if not attachment and urlsplit(target).hostname in {'vanban.chinhphu.vn', 'congbao.chinhphu.vn', 'vbpl.vn'}:
                metadata = {}
                issued = re.search(r"Ban hành:\s*(\d{2}/\d{2}/\d{4})", " ".join(parser.parts), re.I)
                if issued:
                    metadata["issued_date"] = issued.group(1)
                for index, part in enumerate(parser.parts[:-1]):
                    key = {'Số ký hiệu': 'document_number', 'Ngày ban hành': 'issued_date',
                           'Ngày có hiệu lực': 'reported_effective_from', 'Cơ quan ban hành': 'issuing_authority'}.get(part)
                    value = parser.parts[index + 1]
                    if key and len(value) <= 100 and (
                        key == 'document_number' and '/' in value or
                        key == 'issuing_authority' or
                        key != 'document_number' and re.fullmatch(r'\d{2}[-/]\d{2}[-/]\d{4}', value)
                    ):
                        metadata[key] = value
                approved = []
                for link in parser.attachments:
                    try:
                        approved.append(validate_source_url(urljoin(target, link)))
                    except ValueError:
                        continue
                if approved:
                    result = await fetch(session, approved[0], title=result['title'], attachment=True)
                    result['attachments'] = list(dict.fromkeys(approved))
                elif ('docid=' in urlsplit(target).query.lower() or urlsplit(target).hostname in {'congbao.chinhphu.vn', 'vbpl.vn'}) and not _contains_inline_articles(result['text'].splitlines()):
                    # A catalogue/detail page without readable legislation is not legal evidence.
                    result.update(text='', content_status='metadata_only', requires_ocr=False,
                                  sha256=hashlib.sha256(b'').hexdigest(), stored_characters=0)
                result.update(metadata)
            if deep_read:
                from app.services.legal_topic_terms import local_rescue_terms
                generic = set("huong dan sua doi bo sung van ban hieu luc so luat nghi dinh thong tu quyet hop nhat dieu kien thu tuc".split())
                topic_terms = set(local_rescue_terms(question, limit=80)) - generic
                related = []
                for link, label in parser.links:
                    if not re.search(r"sửa đổi|thay thế|bãi bỏ|hướng dẫn|hợp nhất", label, re.I):
                        continue
                    try:
                        candidate = validate_source_url(urljoin(target, link))
                    except ValueError:
                        continue
                    if is_official_document_url(candidate) and len(topic_terms.intersection(local_rescue_terms(label, limit=80))) >= 2:
                        related.append(candidate)
                result["related_urls"] = list(dict.fromkeys(related))[:8]
                result["url"] = url
            return result

    async with _SEMAPHORE:
        try:
            async with asyncio.timeout(100 if use_ocr else 30):
                if client is not None:
                    return await fetch(client)
                from app.services.source_tls import source_ssl_context
                async with httpx.AsyncClient(
                    timeout=10,
                    trust_env=False,
                    verify=source_ssl_context(),
                    headers={"User-Agent": "VietLex-Reviewer/1.0"},
                ) as session:
                    return await fetch(session)
        except (httpx.HTTPError, TimeoutError) as error:
            transport_kind = next((name for cls, name in (
                (httpx.ConnectTimeout, 'connect_timeout'), (httpx.ReadTimeout, 'read_timeout'),
                (httpx.WriteTimeout, 'write_timeout'), (httpx.PoolTimeout, 'pool_timeout'),
                (httpx.ConnectError, 'connect_error'), (httpx.RemoteProtocolError, 'remote_protocol_error'),
                (TimeoutError, 'deadline'),
            ) if isinstance(error, cls)), 'http_error')
            raise SourceReadError("source_transport_error", transport_kind=transport_kind,
                                  transport_cause=_transport_cause(error)) from None


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


def official_evidence_id(source: dict, quote: str) -> str:
    """Deduplicate within a source version, never across replaced documents."""
    import json

    identity = [source["url"], source.get("document_sha256") or source["sha256"], quote]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()[:24]
