"""Opt-in official-domain web discovery alongside the direct government portal.

Protocol: https://api-dashboard.search.brave.com/api-reference/web/search/get
Search snippets are discovery metadata, not independently fetched legal evidence.
"""
from __future__ import annotations
import asyncio
import json
import re
import time
from html import unescape
from urllib.parse import urlparse, urldefrag
import httpx
from app.config import system_ssl_context
from app.services.deep_research import OFFICIAL_SOURCE_DOMAINS, is_official_source
from app.services.official_web_search import OfficialSearchRecord, OfficialSearchResponse, OfficialPortalError


_DOCUMENT_REFERENCE = re.compile(r"(?<![\w/-])\d{1,4}\s*/\s*\d{4}\s*/\s*[A-ZĐ][A-ZĐ0-9-]{1,29}(?![\w/-])")


def _references(text: str) -> set[str]:
    return {re.sub(r"\s+", "", match.group()) for match in _DOCUMENT_REFERENCE.finditer(text.upper())}


class BraveOfficialClient:
    def __init__(self, *, settings, client=None):
        if not settings.BRAVE_SEARCH_API_KEY:
            raise ValueError("brave_search_not_configured")
        self.settings, self.client = settings, client

    async def search(self, query: str, *, limit: int = 3):
        if not query.strip():
            raise ValueError("query_required")
        if self.client is not None:
            return await self._search(self.client, query, limit)
        async with httpx.AsyncClient(verify=system_ssl_context(), timeout=self.settings.OFFICIAL_WEB_SEARCH_TIMEOUT_SECONDS) as client:
            return await self._search(client, query, limit)

    async def _search(self, client, query, limit):
        started = time.perf_counter()
        limit = max(1, min(int(limit), 10))
        domains = " OR ".join("site:" + domain for domain in sorted(OFFICIAL_SOURCE_DOMAINS))
        try:
            async with client.stream("GET", "https://api.search.brave.com/res/v1/web/search",
                                     params={"q": query[:500] + " (" + domains + ")", "count": 20, "safesearch": "strict"},
                                     headers={"X-Subscription-Token": self.settings.BRAVE_SEARCH_API_KEY}, follow_redirects=False) as response:
                if response.is_redirect:
                    raise OfficialPortalError("unexpected_redirect")
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 2_000_000:
                        raise OfficialPortalError("response_too_large")
            payload = json.loads(body)
            rows = payload.get("web", {}).get("results", [])
            if not isinstance(rows, list):
                raise ValueError("invalid_search_response")
            records, seen = [], set()
            for row in rows[:20]:
                url = str(row.get("url") or "")
                if len(url) > 2_000 or not is_official_source(url):
                    continue
                url = urldefrag(url)[0]
                if url in seen:
                    continue
                seen.add(url)
                records.append(OfficialSearchRecord(url, str(row.get("title") or "")[:500], urlparse(url).hostname,
                    unescape(re.sub(r"<[^>]+>", "", str(row.get("description") or "")))[:2_000], "", ""))
                if len(records) >= limit:
                    break
        except (httpx.HTTPError, ValueError, TypeError, AttributeError, OfficialPortalError) as error:
            raise OfficialPortalError(getattr(error, "kind", type(error).__name__), request_count=1,
                                      latency_ms=(time.perf_counter()-started)*1000) from None
        return OfficialSearchResponse(tuple(records), "brave_official_domains", (time.perf_counter()-started)*1000, 1,
                                      method="brave-web-search-v1")


class FederatedOfficialClient:
    def __init__(self, *, portal, web=None, gazette=None):
        self.providers = [("chinhphu", portal)]
        if gazette is not None:
            self.providers.append(("congbao", gazette))
        if web is not None:
            self.providers.append(("brave", web))
        self.provider = "_and_".join(name for name, _ in self.providers)
        self.method = "federated-official-discovery-v1"

    async def search(self, query: str, *, limit: int = 3):
        started = time.perf_counter()
        limit = max(1, min(int(limit), 10))
        requested = _references(query)
        outcomes = await asyncio.gather(*(provider.search(query, limit=limit) for _, provider in self.providers), return_exceptions=True)
        errors, records, count, seen = [], [], 0, set()
        for (name, _), result in zip(self.providers, outcomes):
            count += getattr(result, "request_count", 0) or 0
            if isinstance(result, BaseException):
                errors.append(name + ":" + str(getattr(result, "kind", type(result).__name__)))
                continue
            errors.extend(name + ":" + error for error in result.errors)
            for record in result.results:
                url = urldefrag(record.url)[0]
                if not is_official_source(url, record.domain):
                    continue
                # Metadata establishes discovery relevance only; originals still
                # need reading before an answer can cite legal evidence.
                if requested and not requested.intersection(_references(
                    "\n".join((record.document_number, record.title, record.snippet))
                )):
                    continue
                if url not in seen:
                    records.append(record)
                    seen.add(url)
        if all(isinstance(result, BaseException) for result in outcomes):
            raise OfficialPortalError(";".join(errors), request_count=count, latency_ms=(time.perf_counter()-started)*1000)
        if requested:
            records.sort(key=lambda record: not bool(requested.intersection(_references(record.document_number))))
        return OfficialSearchResponse(tuple(records[:min(10, limit*len(self.providers))]), self.provider, (time.perf_counter()-started)*1000,
                                      count, tuple(errors), "federated-official-discovery-v1")
