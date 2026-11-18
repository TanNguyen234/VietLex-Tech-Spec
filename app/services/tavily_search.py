"""Two-tier Tavily Search & Extract client for Vietnamese legal discovery and HTTP-403 rescue."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import re
import time
from typing import Any, Literal
from urllib.parse import urldefrag, urlparse

import httpx

from app.config import get_settings, system_ssl_context
from app.services.instrument_registry import drop_superseded_contexts
from app.services.legal_topic_terms import local_rescue_terms
from app.services.official_search_plan import DOCUMENT_REFERENCE
from app.services.official_web_search import OfficialSearchRecord
from app.services.provider_runtime import ProviderEvent, record_provider_event
from app.services.web_source_tiers import (
    TAVILY_HYBRID_DOMAINS,
    TIER1_OFFICIAL_DOMAINS,
    classify_web_source_tier,
)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"
_MAX_RESPONSE_BYTES = 4_000_000
_ISSUED_DATE_RE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-](?:19|20)\d{2})\b")
_ARTICLE_HEADING_RE = re.compile(
    r"(?:^|\n)\s*(?:#{1,6}\s*|\*\*)?(?:Điều|Dieu)\s+\d{1,4}[a-zđ]?\b[.:]?",
    re.IGNORECASE,
)
_ARTICLE_REF_RE = re.compile(r"\b(?:Điều|Dieu)\s+(\d{1,4})(?![\da-zđ])\b", re.IGNORECASE)
_SUPERSEDED_STATUS_RE = re.compile(
    r"(?:tình\s+trạng\s*:\s*)?(?:đã\s+)?hết\s+hiệu\s+lực|ngưng\s+hiệu\s+lực|không\s+còn\s+hiệu\s+lực",
    re.IGNORECASE,
)
_REPLACED_BY_PAIR_RE = re.compile(
    r"(?P<old>\d{1,4}/(?:\d{4}/[A-ZĐÐ][A-ZĐÐ0-9-]{1,29}|VBHN-[A-ZĐÐ0-9-]{1,29}))"
    r"[^.\n]{0,120}?(?:bị\s+)?thay\s+thế\s+bởi[^.\n]{0,90}?"
    r"(?P<new>\d{1,4}/(?:\d{4}/[A-ZĐÐ][A-ZĐÐ0-9-]{1,29}|VBHN-[A-ZĐÐ0-9-]{1,29}))",
    re.IGNORECASE,
)
_REPLACES_ACTIVE_RE = re.compile(
    r"(?P<new>\d{1,4}/(?:\d{4}/[A-ZĐÐ][A-ZĐÐ0-9-]{1,29}|VBHN-[A-ZĐÐ0-9-]{1,29}))"
    r"[^.\n]{0,60}?\bthay\s+thế(?!\s+bởi)[^.\n]{0,90}?"
    r"(?P<old>\d{1,4}/(?:\d{4}/[A-ZĐÐ][A-ZĐÐ0-9-]{1,29}|VBHN-[A-ZĐÐ0-9-]{1,29}))",
    re.IGNORECASE,
)
_REPLACED_BY_TARGET_RE = re.compile(
    r"(?:bị\s+)?thay\s+thế\s+bởi[^.\n]{0,90}?"
    r"(?P<new>\d{1,4}/(?:\d{4}/[A-ZĐÐ][A-ZĐÐ0-9-]{1,29}|VBHN-[A-ZĐÐ0-9-]{1,29}))",
    re.IGNORECASE,
)


class TavilySearchError(RuntimeError):
    def __init__(
        self,
        kind: str,
        *,
        status_code: int | None = None,
        latency_ms: float = 0.0,
        request_count: int = 1,
    ) -> None:
        super().__init__(kind)
        self.kind = kind
        self.status_code = status_code
        self.latency_ms = latency_ms
        self.request_count = request_count


@dataclass(frozen=True)
class DiscoveryPivotHint:
    document_numbers: tuple[str, ...] = ()
    target_articles: tuple[int, ...] = ()
    superseded_numbers: tuple[str, ...] = ()
    superseded_by: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedWebDocument:
    url: str
    raw_content: str
    title: str = ""
    sha256: str = ""


@dataclass(frozen=True)
class TavilyDiscoveryBundle:
    tier1_records: tuple[OfficialSearchRecord, ...] = ()
    tier1_raw_markdown: dict[str, str] = field(default_factory=dict)
    pivot_hints: DiscoveryPivotHint = field(default_factory=DiscoveryPivotHint)
    provider: str = "tavily"
    latency_ms: float = 0.0
    request_count: int = 1
    errors: tuple[str, ...] = ()
    method: str = "tavily-two-tier-v1"

    @property
    def results(self) -> tuple[OfficialSearchRecord, ...]:
        """Expose only Tier-1 official records to standard OfficialSearchResponse callers."""
        return self.tier1_records


def _normalize_doc_number(raw: str) -> str:
    cleaned = re.sub(r"\s+", "", str(raw or "").strip()).upper().replace("Ð", "Đ")
    for ascii_code, vn_code in (
        ("/ND-CP", "/NĐ-CP"),
        ("/QD-", "/QĐ-"),
        ("-HDTP", "-HĐTP"),
        ("-BLDTBXH", "-BLĐTBXH"),
        ("-UBTVQH", "-UBTVQH"),
    ):
        cleaned = cleaned.replace(ascii_code, vn_code)
    return cleaned


def _extract_doc_numbers(text: str) -> list[str]:
    found: list[str] = []
    for match in DOCUMENT_REFERENCE.finditer(str(text or "")):
        norm = _normalize_doc_number(match.group(0))
        if norm and norm not in found:
            found.append(norm)
    return found


def normalize_markdown_legal_text(raw: str) -> str:
    """Normalize Markdown headings so downstream Vietnamese article parsers match cleanly."""
    lines: list[str] = []
    for raw_line in str(raw or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"^\s*#{1,6}\s+", "", raw_line)
        line = re.sub(
            r"^\s*\*\*((?:Điều|Dieu|Chương|Mục|Phần)\s+[^*\n]+)\*\*\s*(.*)$",
            r"\1 \2",
            line,
            flags=re.IGNORECASE,
        )
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


def _extract_pivot_hints(
    query: str,
    tier2_rows: list[tuple[str, str, str]],
) -> DiscoveryPivotHint:
    superseded: list[str] = []
    superseded_by: dict[str, str] = {}
    candidates: list[str] = []
    articles: list[int] = []
    query_terms = set(local_rescue_terms(query, limit=24))

    for title, content, raw_content in tier2_rows:
        header_nums = _extract_doc_numbers(title)
        lead_text = "\n".join(part for part in (title, content, raw_content[:4_000]) if part)
        full_sample = "\n".join(part for part in (title, content, raw_content[:12_000]) if part)

        row_superseded_pairs = False
        for regex in (_REPLACED_BY_PAIR_RE, _REPLACES_ACTIVE_RE):
            for pair_match in regex.finditer(lead_text):
                old_num = _normalize_doc_number(pair_match.group("old"))
                new_num = _normalize_doc_number(pair_match.group("new"))
                if old_num and new_num != old_num:
                    row_superseded_pairs = True
                    if old_num not in superseded:
                        superseded.append(old_num)
                    if new_num:
                        superseded_by[old_num] = new_num
                        if new_num not in candidates:
                            candidates.append(new_num)

        if header_nums and _SUPERSEDED_STATUS_RE.search(lead_text):
            primary_old = header_nums[0]
            if primary_old not in superseded_by.values() and (
                _SUPERSEDED_STATUS_RE.search(title) or not row_superseded_pairs
            ):
                if primary_old not in superseded:
                    superseded.append(primary_old)
                rep_match = _REPLACED_BY_TARGET_RE.search(lead_text)
                if rep_match:
                    rep_num = _normalize_doc_number(rep_match.group("new"))
                    if rep_num and rep_num != primary_old:
                        superseded_by[primary_old] = rep_num
                        if rep_num not in candidates:
                            candidates.append(rep_num)

        for num in _extract_doc_numbers(full_sample):
            if num not in candidates:
                candidates.append(num)

        # Extract target Điều numbers from title/snippet first, then topical raw lines.
        for art_match in _ARTICLE_REF_RE.finditer(f"{title}\n{content}"):
            art_no = int(art_match.group(1))
            if 1 <= art_no <= 2000 and art_no not in articles:
                articles.append(art_no)
        if len(articles) < 6 and raw_content:
            for line in raw_content[:12_000].splitlines():
                if query_terms and not (query_terms & set(local_rescue_terms(line, limit=32))):
                    continue
                for art_match in _ARTICLE_REF_RE.finditer(line):
                    art_no = int(art_match.group(1))
                    if 1 <= art_no <= 2000 and art_no not in articles:
                        articles.append(art_no)
                if len(articles) >= 6:
                    break

    active_numbers: list[str] = []
    superseded_set = set(superseded)
    for num in candidates:
        if num in superseded_set:
            continue
        kept, dropped = drop_superseded_contexts(query, [f"[{num}]"])
        if dropped or not kept:
            if num not in superseded_set:
                superseded.append(num)
                superseded_set.add(num)
            continue
        active_numbers.append(num)

    return DiscoveryPivotHint(
        document_numbers=tuple(active_numbers[:6]),
        target_articles=tuple(articles[:6]),
        superseded_numbers=tuple(superseded[:10]),
        superseded_by=superseded_by,
    )


def _resolve_tavily_key(settings: Any) -> str | None:
    key = (
        getattr(settings, "tavily_api_key", None)
        or getattr(settings, "TAVILY_API_KEY", None)
        or getattr(settings, "TAVILY_API", None)
    )
    cleaned = str(key or "").strip()
    return cleaned or None


def is_tavily_search_enabled(settings: Any) -> bool:
    return bool(
        getattr(settings, "TAVILY_SEARCH_ENABLED", False)
        and _resolve_tavily_key(settings)
        and not getattr(settings, "USE_LEGACY_FREE_PIPELINE", False)
    )


def is_tavily_extract_enabled(settings: Any) -> bool:
    return bool(
        getattr(settings, "TAVILY_EXTRACT_ENABLED", False)
        and _resolve_tavily_key(settings)
        and not getattr(settings, "USE_LEGACY_FREE_PIPELINE", False)
    )


class TavilyOfficialClient:
    """Async HTTPX client for Tavily Search and Extract with strict Tier-1/Tier-2 provenance."""

    provider = "tavily"
    method = "tavily-two-tier-v1"

    def __init__(
        self,
        *,
        settings: Any = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings if settings is not None else get_settings()
        if getattr(self.settings, "USE_LEGACY_FREE_PIPELINE", False):
            raise ValueError("tavily_blocked_in_legacy_free_pipeline")
        api_key = _resolve_tavily_key(self.settings)
        if not api_key:
            raise ValueError("tavily_not_configured")
        self._api_key = api_key
        self.client = client

    def _timeout(self) -> float:
        return float(getattr(self.settings, "TAVILY_TIMEOUT_SECONDS", 8.0) or 8.0)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def _post_json(
        self,
        http_client: httpx.AsyncClient,
        url: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], int]:
        async with http_client.stream(
            "POST",
            url,
            json=payload,
            headers=self._headers(),
            follow_redirects=False,
        ) as response:
            status_code = response.status_code
            if response.is_redirect:
                raise TavilySearchError("tavily_unexpected_redirect", status_code=status_code)
            if status_code >= 400:
                raise TavilySearchError(f"tavily_http_{status_code}", status_code=status_code)
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > _MAX_RESPONSE_BYTES:
                    raise TavilySearchError("tavily_response_too_large", status_code=status_code)
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise TavilySearchError("tavily_invalid_json", status_code=status_code) from exc
        if not isinstance(decoded, dict):
            raise TavilySearchError("tavily_invalid_payload", status_code=status_code)
        return decoded, status_code

    async def search(
        self,
        query: str,
        *,
        limit: int = 5,
        include_tier2: bool = True,
        tier: Literal["tier1", "hybrid"] | None = None,
    ) -> TavilyDiscoveryBundle:
        clean_query = " ".join(str(query or "").split())[:400]
        if not clean_query:
            raise ValueError("query_required")
        use_tier2 = (tier == "hybrid") if tier is not None else bool(include_tier2)
        search_depth = str(getattr(self.settings, "TAVILY_SEARCH_DEPTH", "basic") or "basic")
        domains = list(TAVILY_HYBRID_DOMAINS if use_tier2 else TIER1_OFFICIAL_DOMAINS)
        payload = {
            "query": clean_query,
            "search_depth": search_depth,
            "max_results": max(int(limit), 8),
            "include_domains": domains,
            "include_raw_content": "markdown",
        }
        started = time.perf_counter()
        try:
            if self.client is not None:
                data, _ = await self._post_json(self.client, TAVILY_SEARCH_URL, payload)
            else:
                async with httpx.AsyncClient(
                    verify=system_ssl_context(),
                    timeout=self._timeout(),
                    trust_env=False,
                ) as session:
                    data, _ = await self._post_json(session, TAVILY_SEARCH_URL, payload)
        except TavilySearchError as err:
            latency_ms = round((time.perf_counter() - started) * 1000, 3)
            record_provider_event(
                ProviderEvent(
                    provider="tavily",
                    model=f"search-{search_depth}",
                    use_case="search",
                    success=False,
                    error_kind=err.kind,
                    latency_ms=latency_ms,
                    fallback_used=False,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    call_kind="http",
                    request_count=1,
                )
            )
            raise TavilySearchError(
                err.kind,
                status_code=err.status_code,
                latency_ms=latency_ms,
            ) from None
        except httpx.HTTPError as err:
            latency_ms = round((time.perf_counter() - started) * 1000, 3)
            kind = f"tavily_{type(err).__name__.lower()}"
            record_provider_event(
                ProviderEvent(
                    provider="tavily",
                    model=f"search-{search_depth}",
                    use_case="search",
                    success=False,
                    error_kind=kind,
                    latency_ms=latency_ms,
                    fallback_used=False,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    call_kind="http",
                    request_count=1,
                )
            )
            raise TavilySearchError(kind, latency_ms=latency_ms) from None

        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        record_provider_event(
            ProviderEvent(
                provider="tavily",
                model=f"search-{search_depth}",
                use_case="search",
                success=True,
                error_kind=None,
                latency_ms=latency_ms,
                fallback_used=False,
                timestamp=datetime.now(timezone.utc).isoformat(),
                call_kind="http",
                request_count=1,
            )
        )

        rows = data.get("results")
        if not isinstance(rows, list):
            rows = []

        tier1_records: list[OfficialSearchRecord] = []
        tier1_raw_markdown: dict[str, str] = {}
        tier2_rows: list[tuple[str, str, str]] = []
        seen_urls: set[str] = set()
        bounded_limit = max(1, min(int(limit), 12))

        for row in rows[:20]:
            if not isinstance(row, dict):
                continue
            raw_url = urldefrag(str(row.get("url") or "").strip())[0]
            if not raw_url or raw_url in seen_urls:
                continue
            source_tier = classify_web_source_tier(raw_url)
            title = " ".join(str(row.get("title") or "").split())[:500]
            snippet = " ".join(str(row.get("content") or "").split())[:2_000]
            raw_md = str(row.get("raw_content") or "")[:120_000]

            if source_tier == "official_primary":
                seen_urls.add(raw_url)
                nums = _extract_doc_numbers(f"{title}\n{snippet}\n{raw_md[:1500]}")
                doc_num = nums[0] if nums else ""
                date_match = _ISSUED_DATE_RE.search(f"{title}\n{snippet}")
                issued_date = date_match.group(1) if date_match else ""
                if len(tier1_records) < bounded_limit:
                    tier1_records.append(
                        OfficialSearchRecord(
                            url=raw_url,
                            title=title or (urlparse(raw_url).hostname or ""),
                            domain=(urlparse(raw_url).hostname or "").casefold(),
                            snippet=snippet,
                            document_number=doc_num,
                            issued_date=issued_date,
                        )
                    )
                if (
                    raw_md
                    and "\ufffd" not in raw_md
                    and len(raw_md.strip()) >= 120
                    and _ARTICLE_HEADING_RE.search(raw_md)
                ):
                    normalized_md = normalize_markdown_legal_text(raw_md)
                    if normalized_md:
                        tier1_raw_markdown[raw_url] = normalized_md
            elif source_tier == "legal_discovery_pivot" and use_tier2:
                seen_urls.add(raw_url)
                tier2_rows.append((title, snippet, raw_md))

        pivot_hints = (
            _extract_pivot_hints(clean_query, tier2_rows)
            if tier2_rows
            else DiscoveryPivotHint()
        )
        return TavilyDiscoveryBundle(
            tier1_records=tuple(tier1_records),
            tier1_raw_markdown=tier1_raw_markdown,
            pivot_hints=pivot_hints,
            provider="tavily",
            latency_ms=latency_ms,
            request_count=1,
            errors=(),
            method="tavily-two-tier-v1",
        )

    async def extract(
        self,
        urls: Sequence[str],
        *,
        query: str | None = None,
    ) -> dict[str, ExtractedWebDocument]:
        approved_urls: list[str] = []
        for candidate in urls:
            clean_url = urldefrag(str(candidate or "").strip())[0]
            if (
                clean_url
                and clean_url not in approved_urls
                and classify_web_source_tier(clean_url) == "official_primary"
            ):
                approved_urls.append(clean_url)
            if len(approved_urls) >= 5:
                break
        if not approved_urls:
            return {}

        payload: dict[str, Any] = {
            "urls": approved_urls,
            "extract_depth": "basic",
            "format": "markdown",
        }
        if query and str(query).strip():
            payload["query"] = " ".join(str(query).split())[:300]

        started = time.perf_counter()
        try:
            if self.client is not None:
                data, _ = await self._post_json(self.client, TAVILY_EXTRACT_URL, payload)
            else:
                async with httpx.AsyncClient(
                    verify=system_ssl_context(),
                    timeout=self._timeout(),
                    trust_env=False,
                ) as session:
                    data, _ = await self._post_json(session, TAVILY_EXTRACT_URL, payload)
        except TavilySearchError as err:
            latency_ms = round((time.perf_counter() - started) * 1000, 3)
            record_provider_event(
                ProviderEvent(
                    provider="tavily",
                    model="extract-basic",
                    use_case="extract",
                    success=False,
                    error_kind=err.kind,
                    latency_ms=latency_ms,
                    fallback_used=False,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    call_kind="http",
                    request_count=1,
                )
            )
            raise TavilySearchError(
                err.kind,
                status_code=err.status_code,
                latency_ms=latency_ms,
            ) from None
        except httpx.HTTPError as err:
            latency_ms = round((time.perf_counter() - started) * 1000, 3)
            kind = f"tavily_{type(err).__name__.lower()}"
            record_provider_event(
                ProviderEvent(
                    provider="tavily",
                    model="extract-basic",
                    use_case="extract",
                    success=False,
                    error_kind=kind,
                    latency_ms=latency_ms,
                    fallback_used=False,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    call_kind="http",
                    request_count=1,
                )
            )
            raise TavilySearchError(kind, latency_ms=latency_ms) from None

        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        record_provider_event(
            ProviderEvent(
                provider="tavily",
                model="extract-basic",
                use_case="extract",
                success=True,
                error_kind=None,
                latency_ms=latency_ms,
                fallback_used=False,
                timestamp=datetime.now(timezone.utc).isoformat(),
                call_kind="http",
                request_count=1,
            )
        )

        extracted: dict[str, ExtractedWebDocument] = {}
        rows = data.get("results")
        if not isinstance(rows, list):
            return extracted
        for row in rows:
            if not isinstance(row, dict):
                continue
            item_url = urldefrag(str(row.get("url") or "").strip())[0]
            if classify_web_source_tier(item_url) != "official_primary":
                continue
            raw_md = normalize_markdown_legal_text(str(row.get("raw_content") or "")[:120_000])
            if not raw_md or "\ufffd" in raw_md:
                continue
            title = ""
            first_line = raw_md.splitlines()[0].strip() if raw_md else ""
            if first_line and not re.match(r"^(?:Điều|Dieu)\s+\d+", first_line, re.I):
                title = first_line[:300]
            digest = hashlib.sha256(raw_md.encode("utf-8")).hexdigest()
            extracted[item_url] = ExtractedWebDocument(
                url=item_url,
                raw_content=raw_md,
                title=title,
                sha256=digest,
            )
        return extracted


TavilyClient = TavilyOfficialClient
