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
    return {
        re.sub(r"\s+", "", match.group()).replace("Ð", "Đ")
        for match in _DOCUMENT_REFERENCE.finditer(text.upper().replace("Ð", "Đ"))
    }


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
    def __init__(
        self,
        *,
        portal,
        web=None,
        gazette=None,
        tavily=None,
        max_wait_seconds: float | None = None,
        provider_timeouts: dict[str, float] | None = None,
    ):
        if max_wait_seconds is not None and max_wait_seconds <= 0:
            raise ValueError("max_wait_seconds must be positive")
        self.providers = [("chinhphu", portal)]
        if gazette is not None:
            self.providers.append(("congbao", gazette))
        if tavily is not None:
            self.providers.append(("tavily", tavily))
        if web is not None:
            self.providers.append(("brave", web))
        provider_names = {name for name, _ in self.providers}
        provider_timeouts = provider_timeouts or {}
        if set(provider_timeouts) - provider_names:
            raise ValueError("provider_timeouts contains an unknown provider")
        if any(timeout <= 0 for timeout in provider_timeouts.values()):
            raise ValueError("provider timeouts must be positive")
        self.provider = "_and_".join(name for name, _ in self.providers)
        self.method = "federated-official-discovery-v1"
        self.max_wait_seconds = max_wait_seconds
        self.provider_timeouts = dict(provider_timeouts)

    async def search(self, query: str, *, limit: int = 3):
        started = time.perf_counter()
        limit = max(1, min(int(limit), 10))
        requested = _references(query)
        async def search_one(name, provider):
            request = provider.search(query, limit=limit)
            timeout = self.provider_timeouts.get(name, self.max_wait_seconds)
            if timeout is None:
                return await request
            return await asyncio.wait_for(request, timeout=timeout)

        outcomes = await asyncio.gather(
            *(search_one(name, provider) for name, provider in self.providers),
            return_exceptions=True,
        )
        errors, records, count, seen = [], [], 0, set()
        pivot_numbers: list[str] = []
        pivot_superseded: set[str] = set()
        for (_name, _), result in zip(self.providers, outcomes):
            if isinstance(result, BaseException):
                continue
            pivot_hints = getattr(result, "pivot_hints", None)
            if pivot_hints is not None:
                for num in getattr(pivot_hints, "document_numbers", ()) or ():
                    clean_num = re.sub(r"\s+", "", str(num)).upper().replace("Ð", "Đ")
                    if clean_num and clean_num not in pivot_numbers:
                        pivot_numbers.append(clean_num)
                for sup in getattr(pivot_hints, "superseded_numbers", ()) or ():
                    clean_sup = re.sub(r"\s+", "", str(sup)).upper().replace("Ð", "Đ")
                    if clean_sup:
                        pivot_superseded.add(clean_sup)

        unrequested_superseded = pivot_superseded - requested

        def _is_superseded_record(record) -> bool:
            if not unrequested_superseded:
                return False
            rec_nums = (
                _references(record.document_number)
                if getattr(record, "document_number", "")
                else _references(getattr(record, "title", ""))
            )
            return bool(rec_nums and rec_nums.issubset(unrequested_superseded))

        def _ingest_records(rows, *, allowed_refs: set[str]):
            for record in rows:
                url = urldefrag(record.url)[0]
                if not is_official_source(url, record.domain):
                    continue
                if _is_superseded_record(record):
                    continue
                # Metadata establishes discovery relevance only; originals still
                # need reading before an answer can cite legal evidence.
                if allowed_refs and not allowed_refs.intersection(_references(
                    "\n".join((record.document_number, record.title, record.snippet))
                )):
                    continue
                if url not in seen:
                    records.append(record)
                    seen.add(url)

        for (name, _), result in zip(self.providers, outcomes):
            count += getattr(result, "request_count", 0) or 0
            if isinstance(result, BaseException):
                errors.append(name + ":" + str(getattr(result, "kind", type(result).__name__)))
                continue
            errors.extend(name + ":" + error for error in result.errors)
            _ingest_records(result.results, allowed_refs=requested)

        covered_refs = (
            set().union(*(_references("\n".join((r.document_number, r.title))) for r in records))
            if records
            else set()
        )
        missing_pivots = [num for num in pivot_numbers[:2] if num not in covered_refs]
        hop2_providers = [
            (name, prov) for name, prov in self.providers if name in {"tavily", "congbao"}
        ]
        if missing_pivots and hop2_providers:
            async def search_hop2(name: str, provider, doc_num: str):
                rem = (
                    self.max_wait_seconds - (time.perf_counter() - started)
                    if self.max_wait_seconds is not None
                    else None
                )
                prov_budget = self.provider_timeouts.get(name, self.max_wait_seconds)
                if rem is not None and rem <= 0.02:
                    raise asyncio.TimeoutError()
                budget = (
                    min(prov_budget, rem)
                    if prov_budget is not None and rem is not None
                    else (prov_budget if prov_budget is not None else (rem if rem is not None else 4.0))
                )
                if name == "tavily":
                    coro = provider.search(doc_num, limit=limit, include_tier2=False)
                else:
                    coro = provider.search(doc_num, limit=limit)
                return await asyncio.wait_for(coro, timeout=budget)

            hop2_pairs = [
                (name, prov, doc_num)
                for doc_num in missing_pivots
                for name, prov in hop2_providers
            ]
            hop2_outcomes = await asyncio.gather(
                *(search_hop2(name, prov, doc_num) for name, prov, doc_num in hop2_pairs),
                return_exceptions=True,
            )
            hop2_allowed = requested | set(missing_pivots) if requested else set()
            for (name, _, _), hop_res in zip(hop2_pairs, hop2_outcomes):
                count += getattr(hop_res, "request_count", 0) or 0
                if isinstance(hop_res, BaseException):
                    errors.append(name + ":" + str(getattr(hop_res, "kind", type(hop_res).__name__)))
                    continue
                errors.extend(name + ":" + err for err in getattr(hop_res, "errors", ()))
                _ingest_records(hop_res.results, allowed_refs=hop2_allowed)

        if all(isinstance(result, BaseException) for result in outcomes) and not records:
            raise OfficialPortalError(";".join(errors), request_count=count, latency_ms=(time.perf_counter()-started)*1000)
        if requested:
            records.sort(key=lambda record: not bool(requested.intersection(_references(record.document_number))))
        return OfficialSearchResponse(tuple(records[:min(10, limit*len(self.providers))]), self.provider, (time.perf_counter()-started)*1000,
                                      count, tuple(errors), "federated-official-discovery-v1")
