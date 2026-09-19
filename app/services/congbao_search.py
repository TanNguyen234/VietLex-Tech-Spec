"""Bounded discovery using the public search endpoint linked by congbao.chinhphu.vn."""
from __future__ import annotations

import asyncio
import json
import re
import time
import unicodedata

import httpx

from app.config import get_settings, system_ssl_context
from app.services.official_web_search import (
    OfficialPortalError, OfficialSearchRecord, OfficialSearchResponse,
)

SEARCH_URL = "https://api-searchcongbao.chinhphu.vn/search/van-ban"
_SEMAPHORE = asyncio.Semaphore(2)


class CongBaoClient:
    def __init__(self, *, client=None, settings=None):
        self.client = client
        self.settings = settings or get_settings()

    async def search(self, query: str, *, limit: int = 3):
        query = " ".join(str(query or "").split())[:500]
        if not query:
            raise ValueError("query_required")
        limit = max(1, min(int(limit), 10))
        async with _SEMAPHORE:
            if self.client is not None:
                return await self._search(self.client, query, limit)
            async with httpx.AsyncClient(
                verify=system_ssl_context(),
                timeout=self.settings.OFFICIAL_WEB_SEARCH_TIMEOUT_SECONDS,
            ) as client:
                return await self._search(client, query, limit)

    async def _search(self, client, query, limit):
        started = time.perf_counter()
        try:
            async with client.stream(
                "POST", SEARCH_URL, follow_redirects=False,
                json={"filters": {}, "page": 1, "page_size": limit, "query": query},
            ) as response:
                if response.is_redirect:
                    raise OfficialPortalError("unexpected_redirect")
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 2_000_000:
                        raise OfficialPortalError("response_too_large")
            payload = json.loads(body)
            if not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(payload.get("data"), list):
                raise OfficialPortalError("invalid_search_response")
            records, seen = [], set()
            for row in payload["data"][:10]:
                if not isinstance(row, dict):
                    raise OfficialPortalError("invalid_search_response")
                identifier = row.get("id_van_ban")
                if type(identifier) is not int or identifier <= 0:
                    raise OfficialPortalError("invalid_search_response")
                if identifier in seen:
                    continue
                seen.add(identifier)
                number = str(row.get("so_ky_hieu") or "")[:200]
                label = str(row.get("loai_van_ban") or "Văn bản")[:100] + " số " + number
                ascii_label = unicodedata.normalize("NFD", label.replace("đ", "d").replace("Đ", "D")).encode("ascii", "ignore").decode().lower()
                slug = re.sub(r"[^a-z0-9]+", "-", ascii_label).strip("-")
                records.append(OfficialSearchRecord(
                    url=f"https://congbao.chinhphu.vn/van-ban/{slug}-{identifier}.htm",
                    title=str(row.get("trich_yeu") or label)[:500],
                    domain="congbao.chinhphu.vn",
                    snippet=str(row.get("noi_dung_lien_quan_tim_thay") or "")[:2000],
                    document_number=number,
                    issued_date=str(row.get("ngay_ban_hanh") or "")[:10],
                ))
                if len(records) >= limit:
                    break
        except (httpx.HTTPError, ValueError, TypeError, OfficialPortalError) as error:
            raise OfficialPortalError(
                getattr(error, "kind", type(error).__name__), request_count=1,
                latency_ms=(time.perf_counter() - started) * 1000,
            ) from None
        return OfficialSearchResponse(
            tuple(records), "congbao_official_search",
            (time.perf_counter() - started) * 1000, 1, method="congbao-public-search-v1",
        )
