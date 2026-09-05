from __future__ import annotations

from dataclasses import dataclass
import asyncio
from html.parser import HTMLParser
import re
import time
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.config import get_settings, install_system_trust_store


PORTAL_URL = "https://vanban.chinhphu.vn/he-thong-van-ban"
_MAX_RESPONSE_BYTES = 2_000_000
_TABLE_ID = "ctrl_191017_163_grvDocument"
_PREFIX = "ctrl_191017_163$"
_PORTAL_SEMAPHORE = asyncio.Semaphore(2)


class OfficialPortalError(RuntimeError):
    def __init__(
        self,
        kind: str,
        *,
        request_count: int | None = None,
        latency_ms: float | None = None,
    ) -> None:
        super().__init__(kind)
        self.kind = kind
        self.request_count = request_count
        self.latency_ms = latency_ms


@dataclass(frozen=True)
class OfficialSearchRecord:
    url: str
    title: str
    domain: str
    snippet: str
    document_number: str
    issued_date: str


@dataclass(frozen=True)
class OfficialSearchResponse:
    results: tuple[OfficialSearchRecord, ...]
    provider: str
    latency_ms: float
    request_count: int = 2


class _PortalParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden: dict[str, str] = {}
        self.rows: list[list[dict[str, Any]]] = []
        self.saw_results_table = False
        self._table_depth = 0
        self._row: list[dict[str, Any]] | None = None
        self._cell: dict[str, Any] | None = None
        self._anchor: dict[str, str] | None = None

    @staticmethod
    def _attrs(attrs) -> dict[str, str]:
        return {str(key): str(value or "") for key, value in attrs}

    def handle_starttag(self, tag: str, attrs) -> None:
        values = self._attrs(attrs)
        if tag == "input" and values.get("type", "").casefold() == "hidden":
            name = values.get("name")
            if name:
                self.hidden[name] = values.get("value", "")
        if tag == "table":
            if self._table_depth:
                self._table_depth += 1
            elif values.get("id") == _TABLE_ID:
                self._table_depth = 1
                self.saw_results_table = True
            return
        if not self._table_depth:
            return
        if tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = {"text": [], "links": []}
        elif tag == "a" and self._cell is not None:
            self._anchor = {"href": values.get("href", ""), "text": ""}

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"].append(data)
        if self._anchor is not None:
            self._anchor["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if not self._table_depth:
            return
        if tag == "a" and self._anchor is not None and self._cell is not None:
            self._anchor["text"] = " ".join(self._anchor["text"].split())
            self._cell["links"].append(self._anchor)
            self._anchor = None
        elif tag == "td" and self._cell is not None and self._row is not None:
            self._cell["text"] = " ".join("".join(self._cell["text"]).split())
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if len(self._row) >= 3:
                self.rows.append(self._row)
            self._row = None
        elif tag == "table":
            self._table_depth -= 1


def _parse(html: str) -> _PortalParser:
    parser = _PortalParser()
    parser.feed(html)
    return parser


async def _request_text(
    client: httpx.AsyncClient,
    method: str,
    *,
    data: dict[str, str] | None = None,
) -> str:
    async with client.stream(
        method, PORTAL_URL, data=data, follow_redirects=False
    ) as response:
        if response.is_redirect:
            raise OfficialPortalError("unexpected_redirect")
        response.raise_for_status()
        if response.url.scheme != "https" or response.url.host != "vanban.chinhphu.vn":
            raise OfficialPortalError("unexpected_origin")
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > _MAX_RESPONSE_BYTES:
                raise OfficialPortalError("response_too_large")
        return body.decode(response.encoding or "utf-8", errors="replace")


def _records(parser: _PortalParser, limit: int) -> tuple[OfficialSearchRecord, ...]:
    output = []
    for row in parser.rows:
        number, issued, summary = row[:3]
        detail = None
        for link in [*number["links"], *summary["links"]]:
            candidate = urljoin(PORTAL_URL, link["href"])
            parsed = urlparse(candidate)
            if (
                parsed.scheme == "https"
                and parsed.hostname == "vanban.chinhphu.vn"
                and "docid=" in parsed.query.casefold()
            ):
                detail = (candidate, link["text"])
                break
        if detail is None:
            continue
        title = next(
            (
                link["text"]
                for link in summary["links"]
                if "docid=" in urlparse(urljoin(PORTAL_URL, link["href"])).query.casefold()
                and link["text"]
            ),
            summary["text"],
        )
        output.append(
            OfficialSearchRecord(
                url=detail[0][:2_000],
                title=title[:500],
                domain="vanban.chinhphu.vn",
                snippet=title[:2_000],
                document_number=re.sub(
                    r"\s+\d{2}/\d{2}/\d{4}$", "", detail[1] or str(number["text"])
                )[:200],
                issued_date=str(issued["text"])[:50],
            )
        )
        if len(output) >= limit:
            break
    return tuple(output)


class OfficialPortalClient:
    def __init__(self, *, client: httpx.AsyncClient | None = None, settings=None):
        self._client = client
        self._settings = settings or get_settings()

    async def _run(self, client: httpx.AsyncClient, query: str, limit: int):
        started = time.perf_counter()
        request_count = 0
        try:
            request_count += 1
            form = _parse(await _request_text(client, "GET"))
            if "__VIEWSTATE" not in form.hidden or "__EVENTVALIDATION" not in form.hidden:
                raise OfficialPortalError("form_contract_unavailable")
            payload = {
                **form.hidden,
                f"{_PREFIX}drdDocCategory": "0",
                f"{_PREFIX}drdDocOrg": "0",
                f"{_PREFIX}drdDocYear": "0",
                f"{_PREFIX}txtSearchKeyword": " ".join(query.split())[:500],
                f"{_PREFIX}drdRecordPerPage": "50",
                f"{_PREFIX}btnSearch": "Tìm kiếm",
            }
            request_count += 1
            result_text = await _request_text(client, "POST", data=payload)
            parsed = _parse(result_text)
            if not parsed.saw_results_table:
                raise OfficialPortalError("form_contract_unavailable")
        except OfficialPortalError as error:
            raise OfficialPortalError(
                error.kind,
                request_count=request_count,
                latency_ms=round((time.perf_counter() - started) * 1_000, 3),
            ) from None
        except httpx.HTTPError as error:
            raise OfficialPortalError(
                type(error).__name__,
                request_count=request_count,
                latency_ms=round((time.perf_counter() - started) * 1_000, 3),
            ) from None
        return OfficialSearchResponse(
            results=_records(parsed, limit),
            provider="chinhphu_official_portal",
            latency_ms=round((time.perf_counter() - started) * 1_000, 3),
            request_count=request_count,
        )

    async def search(self, query: str, *, limit: int = 3) -> OfficialSearchResponse:
        query = " ".join(str(query or "").split())
        if not query:
            raise ValueError("query is required")
        limit = min(max(1, int(limit)), 10)
        if self._client is not None:
            async with _PORTAL_SEMAPHORE:
                return await self._run(self._client, query, limit)
        install_system_trust_store()
        timeout = httpx.Timeout(self._settings.OFFICIAL_WEB_SEARCH_TIMEOUT_SECONDS)
        async with _PORTAL_SEMAPHORE:
            async with httpx.AsyncClient(
                timeout=timeout,
                headers={"User-Agent": "VietLex/1.0 legal-research"},
            ) as client:
                return await self._run(client, query, limit)
