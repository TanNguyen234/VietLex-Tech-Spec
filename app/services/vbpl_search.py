"""Fail-closed VBPL discovery using a public, discovered GET form only.

The 2026-10-24 public preflight returned 403. No guessed WebForms/API schema,
challenge bypass, credentials or third-party proxy is used.
"""
import asyncio
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit

import httpx

from app.config import system_ssl_context
from app.services.official_web_search import OfficialPortalError, OfficialSearchRecord, OfficialSearchResponse
from app.services.trusted_source_reader import validate_source_url

SEARCH_PAGE = "https://vbpl.vn/TW/Pages/vbpq-timkiem.aspx"


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.form = None
        self.forms = []
        self.anchor = None
        self.records = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.form = {"method": attrs.get("method", "get").lower(), "action": attrs.get("action", ""), "fields": {}}
        if tag == "input" and self.form is not None:
            name = attrs.get("name", "")
            kind = attrs.get("type", "text").lower()
            if kind in {"text", "search"} and name:
                self.form["query_field"] = name
            elif kind == "hidden" and name:
                self.form["fields"][name] = attrs.get("value", "")
        if tag == "a":
            self.anchor = [attrs.get("href", ""), ""]

    def handle_data(self, data):
        if self.anchor is not None:
            self.anchor[1] += data

    def handle_endtag(self, tag):
        if tag == "form" and self.form is not None:
            self.forms.append(self.form)
            self.form = None
        if tag == "a" and self.anchor is not None:
            self.records.append(self.anchor)
            self.anchor = None


class VbplClient:
    def __init__(self, *, client=None):
        self.client = client
        self._lock = asyncio.Lock()
        self._prepared = False
        self._error = None
        self._form = None

    async def _get(self, client, url, **kwargs):
        validate_source_url(url)
        async with client.stream("GET", url, follow_redirects=False, **kwargs) as response:
            if response.status_code != 200:
                raise OfficialPortalError(f"vbpl_http_{response.status_code}")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 2_000_000:
                    raise OfficialPortalError("vbpl_response_too_large")
        text = body.decode("utf-8", errors="strict")
        if any(marker in text.lower() for marker in ("g-recaptcha", "hcaptcha", "cf-chl-")):
            raise OfficialPortalError("vbpl_challenge")
        page = _Page()
        page.feed(text)
        return page

    async def _search(self, client, query, limit):
        async with self._lock:
            if not self._prepared:
                try:
                    page = await self._get(client, SEARCH_PAGE)
                    for form in page.forms:
                        action = urljoin(SEARCH_PAGE, form["action"])
                        if form["method"] == "get" and form.get("query_field") and urlsplit(action).netloc == "vbpl.vn":
                            validate_source_url(action)
                            self._form = {**form, "action": action}
                            break
                    if self._form is None:
                        raise OfficialPortalError("vbpl_search_contract_unavailable")
                except (OfficialPortalError, httpx.HTTPError, UnicodeError, ValueError) as error:
                    self._error = getattr(error, "kind", type(error).__name__)
                self._prepared = True
        if self._error:
            raise OfficialPortalError(self._error)
        form = self._form
        page = await self._get(client, form["action"], params={**form["fields"], form["query_field"]: query[:220]})
        records, seen = [], set()
        for href, title in page.records:
            url = urljoin(form["action"], href)
            if "vbpq-toanvan.aspx" not in urlsplit(url).path.lower():
                continue
            try:
                validate_source_url(url)
            except ValueError:
                continue
            if url in seen or urlsplit(url).netloc != "vbpl.vn":
                continue
            seen.add(url)
            number = re.search(r"\d{1,4}/\d{4}/[\wĐ-]+", title)
            records.append(OfficialSearchRecord(url, " ".join(title.split())[:500], "vbpl.vn", "", number.group() if number else "", ""))
            if len(records) >= limit:
                break
        return OfficialSearchResponse(tuple(records), "vbpl_public_form", 0, method="vbpl-discovered-get-form-v1")

    async def search(self, query, *, limit=3):
        if self.client is not None:
            return await self._search(self.client, query, min(8, max(1, limit)))
        async with httpx.AsyncClient(verify=system_ssl_context(), timeout=10, trust_env=False) as client:
            return await self._search(client, query, min(8, max(1, limit)))
