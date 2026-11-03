"""Bounded, provider-free official-source discovery and reading for workspaces."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, AsyncIterator
from urllib.parse import urlsplit, urldefrag

from app.config import get_settings
from app.services.deep_research import build_research_plan, is_official_source
from app.services.legal_topic_terms import (
    LEGAL_TOPIC_PHRASES,
    extract_official_topic_phrases,
    fold_topic_text,
    local_rescue_terms,
)


_NETWORK_CONCURRENCY = 2
_QUERY_CONCURRENCY = 2
_MAX_QUERIES = 5
_MAX_SELECTED_SOURCES = 3
_EXTRACTION_VERSION = "official-source-smart-pages-v1"
_SNAPSHOT_TTL_SECONDS = 15 * 60
_SPACE = re.compile(r"\s+")
_CURRENT_LAW = re.compile(
    r"\b(?:hien hanh|moi nhat|hien nay|con hieu luc|tai ngay|tinh den|as of)\b",
    re.IGNORECASE,
)
_SUPPLEMENTAL_TOPICS = (
    "khấu trừ tiền lương",
    "thiếu hụt tài sản",
    "thiết kế",
    "chi phí",
    "hàng không",
    "máy bay",
    "thời hạn",
    "tài sản",
    "người lao động",
    "lao động",
    "người sử dụng lao động",
    "đình công",
    "sa thải",
    "kỷ luật lao động",
    "tiền công",
    "bảo hiểm",
    "giấy phép",
    "môi trường",
    "đất đai",
    "đấu thầu",
    "xây dựng",
    "đầu tư",
    "sở hữu",
    "trách nhiệm",
    "hợp đồng",
    "vận tải",
    "thuế",
    "hải quan",
    "xuất nhập khẩu",
    "doanh nghiệp",
    "ngân hàng",
    "tín dụng",
    "điều kiện",
    "thủ tục",
    "xử phạt",
    "khiếu nại",
    "khởi kiện",
    "bồi thường",
    "thừa kế",
    "ly hôn",
    "cổ phần",
    "chứng khoán",
    "dữ liệu",
    "an toàn thực phẩm",
    "y tế",
)
_NETWORK_SEMAPHORE = asyncio.Semaphore(_NETWORK_CONCURRENCY)


class FreeWebResearchDisabled(RuntimeError):
    pass


def _clean_question(question: str) -> str:
    value = _SPACE.sub(" ", str(question or "")).strip()
    # Recover token boundaries in ordinary pasted queries, e.g. Lao động2019
    # and lương85; do not forward a negated QA privacy note as a legal topic.
    value = re.sub(r'(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])', ' ', value)
    value = re.sub(
        r'(?:^|[;.!?])\s*không\s+(?:có\s+|sử dụng\s+|chứa\s+)?'
        r'(?:dữ liệu cá nhân|thông tin cá nhân|pii)(?=\s*(?:[.;!?]|$))',
        '', value, flags=re.I,
    )
    return value.rstrip("?!. ")[:2_000]


def _official_topics(question: str) -> list[str]:
    clean = _clean_question(question)
    if not clean:
        return []
    folded = fold_topic_text(clean)
    local_terms = set(local_rescue_terms(clean, limit=32))
    recognized = list(extract_official_topic_phrases(clean, limit=8))
    topics: list[tuple[int, int, str]] = []
    for phrase in (*_SUPPLEMENTAL_TOPICS, *LEGAL_TOPIC_PHRASES):
        normalized = fold_topic_text(phrase)
        match = re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", folded)
        if not match:
            continue
        # The private rescue tokenizer is only used to discard terms that are
        # not part of the local recognized topic vocabulary.
        if not set(normalized.split()).intersection(local_terms):
            continue
        topics.append((match.start(), match.end(), phrase))
    for phrase in recognized:
        normalized = fold_topic_text(phrase)
        match = re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", folded)
        if match:
            topics.append((match.start(), match.end(), phrase))

    selected: list[tuple[int, int, str]] = []
    for candidate in sorted(topics, key=lambda item: (item[0], -(item[1] - item[0]))):
        if any(candidate[0] < item[1] and item[0] < candidate[1] for item in selected):
            continue
        if candidate[2] not in [item[2] for item in selected]:
            selected.append(candidate)

    return [item[2] for item in selected[:5]]


def _official_title_families(question: str) -> list[str]:
    """Return narrow official title anchors for well-known legal issue families."""
    topics = {fold_topic_text(phrase) for phrase in _official_topics(question)}
    families: list[str] = []
    if topics.intersection({"thu viec", "khau tru tien luong", "hop dong lao dong", "cham dut hop dong"}):
        families.append("Bộ luật Lao động")
    if topics.intersection({"nhap phe lieu", "giay phep moi truong"}):
        families.append("Luật Bảo vệ môi trường")
    if topics.intersection({'dat coc', 'thue nha'}):
        families.append('Bộ luật Dân sự')
    selected = []
    clean = _clean_question(question)
    for family in families:
        year = re.search(re.escape(family) + r'\s*(?:năm\s*)?\(?((?:19|20)\d{2})\b', clean, re.I)
        selected.append(f'{family} {year.group(1)}' if year else family)
    return selected


def _fallback_seed_topics(question: str, plan) -> list[str]:
    """Use a sanitized deterministic seed when the curated topic lexicon misses."""
    folded = fold_topic_text(question)
    # The fallback deliberately declines personal narratives; recognized legal
    # topics above remain available because they are extracted independently.
    if re.search(r"\b(?:toi|ten toi|cua toi|anh|chi|ong|ba|nhan vien)\b", folded):
        return []
    safe_question = re.sub(
        r"\b(?:as\s+of|tinh\s+den|tai\s+ngay)\s+\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}\b",
        " ",
        question,
        flags=re.IGNORECASE,
    )
    safe_question = re.sub(
        r"(?<!\w)\d[\d.,]*(?:\s*(?:đồng|vnđ|triệu|tỷ|%))?(?!\w)",
        " ",
        safe_question,
        flags=re.IGNORECASE,
    )
    rescue = set(local_rescue_terms(safe_question, limit=32))
    raw_words = list(re.finditer(r"[^\W\d_]+", safe_question, flags=re.UNICODE))
    normalized = [fold_topic_text(match.group(0)) for match in raw_words]
    selected: list[str] = []
    seed_words = set(local_rescue_terms(plan.steps[0].query, limit=8))
    for index, (match, term) in enumerate(zip(raw_words, normalized)):
        if term not in seed_words or term not in rescue or term in selected:
            continue
        # Properly capitalized noninitial tokens are likely names or locations.
        original = match.group(0)
        if original[:1].isupper() and original[1:].islower():
            continue
        if len(term) < 3:
            continue
        selected.append(original)
        if len(selected) >= 4:
            break
    return selected if len(selected) >= 2 else []


def build_free_web_queries(question: str) -> list[str]:
    """Build short official-search terms without forwarding personal narratives."""
    clean = _clean_question(question)
    if not clean:
        return []
    plan = build_research_plan(clean)
    subject_phrases = _official_topics(clean)
    if not subject_phrases:
        subject_phrases = _fallback_seed_topics(clean, plan)
    if not subject_phrases:
        from app.services.official_search_plan import build_official_search_plan
        fallback = build_official_search_plan(clean)
        return list(dict.fromkeys(" ".join(query.split()[:8]) for query in fallback.queries))[:5]
    # Preserve only explicit statutory identifiers, not incidental amounts,
    # personal dates, or names from the narrative question.
    explicit_number = re.search(
        r"(?<![\w/-])\d{1,4}\s*/\s*\d{4}\s*/\s*[A-ZĐ][A-ZĐ0-9-]{1,29}(?![\w/-])",
        clean,
        flags=re.I,
    )
    if explicit_number:
        subject_phrases.insert(0, re.sub(r"\s+", "", explicit_number.group(0).upper()))
    if not subject_phrases:
        return []

    low_signal = {
        fold_topic_text(phrase)
        for phrase in ("doanh nghiệp", "người lao động", "người sử dụng lao động", "điều kiện")
    }
    focused_phrases = [
        phrase for phrase in subject_phrases
        if fold_topic_text(phrase) not in low_signal
    ] or subject_phrases

    def words(values: list[str], limit: int) -> list[str]:
        result: list[str] = []
        for phrase in values:
            phrase_words = phrase.split()
            if len(result) + len(phrase_words) > limit:
                break
            result.extend(phrase_words)
        return result

    core = words(focused_phrases, 8)
    anchor = words(focused_phrases, 6)
    if not anchor:
        return []
    families = _official_title_families(clean)

    query_values: list[str] = []
    seen: set[str] = set()
    def add_query(value: str):
        query = _SPACE.sub(" ", value).strip()[:160]
        word_count = len(re.findall(r"[^\W_]+", query, flags=re.UNICODE))
        key = query.casefold()
        if query and word_count <= 8 and key not in seen:
            query_values.append(query)
            seen.add(key)

    # The core query covers every focused issue when it fits; follow-up
    # searches add narrow official title anchors before varying legal intent.
    add_query(" ".join(core))
    for family in families:
        family_words = family.split()
        family_budget = 8 - len(family_words)
        family_subject = words(focused_phrases, family_budget)
        if not family_subject and re.search(r'\s(?:19|20)\d{2}$', family):
            # Preserve an indivisible issue such as "khấu trừ tiền lương".
            # The bounded query cannot carry both its full phrase and the year.
            family = family.rsplit(' ', 1)[0]
            family_words = family.split()
            family_budget = 8 - len(family_words)
            family_subject = words(focused_phrases, family_budget)
        if sum(len(phrase.split()) for phrase in focused_phrases) > family_budget:
            family_subject = words(focused_phrases[:1], family_budget)
        add_query(" ".join([*family_subject, *family_words]))
    for intent in ("điều kiện", "ngoại lệ", "sửa đổi hiệu lực", "văn bản chính thức"):
        add_query(" ".join([*anchor, intent]))
        if len(query_values) >= _MAX_QUERIES:
            break
    return query_values


def _candidate_rank(record: dict[str, str], question: str) -> tuple[int, str]:
    title = fold_topic_text(record.get("title", ""))
    snippet = fold_topic_text(record.get("discovery_snippet", ""))
    score = sum(2 for family in _official_title_families(question) if fold_topic_text(family) in title)
    for phrase in _official_topics(question):
        normalized = fold_topic_text(phrase)
        if len(normalized.split()) > 1:
            score += 6 if normalized in title else 0
            score += 3 if normalized in snippet else 0
        else:
            # A broad one-word match such as "lương" is weak metadata evidence.
            score += 1 if normalized in title else 0
    if record.get("document_number"):
        number = str(record["document_number"]).casefold().replace(" ", "")
        if number in _clean_question(question).casefold().replace(" ", ""):
            score += 10
    return (-score, record.get("url", ""))


class _BoundedProvider:
    """Apply one shared network gate and a hard per-provider wall timeout."""

    def __init__(self, provider, timeout: float):
        self.provider = provider
        self.timeout = min(10.0, max(0.05, float(timeout)))

    async def search(self, query: str, *, limit: int = 3):
        async with _NETWORK_SEMAPHORE:
            async with asyncio.timeout(self.timeout):
                return await self.provider.search(query, limit=limit)


def _configured_provider(settings):
    from app.services.congbao_search import CongBaoClient
    from app.services.federated_official_search import FederatedOfficialClient
    from app.services.official_web_search import OfficialPortalClient

    timeout = min(
        10.0,
        float(getattr(settings, "FREE_WEB_RESEARCH_PROVIDER_TIMEOUT_SECONDS", 10.0)),
    )
    return FederatedOfficialClient(
        portal=_BoundedProvider(OfficialPortalClient(settings=settings), timeout),
        gazette=_BoundedProvider(CongBaoClient(settings=settings), timeout),
        max_wait_seconds=timeout,
        provider_timeouts={"chinhphu": timeout, "congbao": timeout},
    )


def _source_record(record: Any) -> dict[str, str]:
    return {
        "url": str(getattr(record, "url", "") or "")[:2_000],
        "title": str(getattr(record, "title", "") or "")[:500],
        "domain": str(getattr(record, "domain", "") or "")[:255],
        "discovery_snippet": str(getattr(record, "snippet", "") or "")[:1_000],
        "document_number": str(getattr(record, "document_number", "") or "")[:200],
        "issued_date": str(getattr(record, "issued_date", "") or "")[:50],
    }


def _candidate_url(record: Any) -> str | None:
    from app.services.trusted_source_reader import validate_source_url

    source = _source_record(record)
    raw_url = source["url"]
    try:
        url = validate_source_url(raw_url)
    except (TypeError, ValueError):
        return None
    if not is_official_source(url, source["domain"]):
        return None
    # Remove a fragment only after origin validation; fragments are not sent to
    # the server and must not make duplicate URLs appear distinct.
    return urldefrag(url)[0]


def _has_readable_text(source: dict[str, Any]) -> bool:
    if str(source.get("content_status") or "").casefold() in {
        "metadata_only", "unreadable", "empty"
    }:
        return False
    if str(source.get("text") or "").strip():
        return True
    pages = source.get("pages")
    if not isinstance(pages, list):
        return False
    return any(
        str(page.get("text") or "").strip()
        for page in pages
        if isinstance(page, dict)
    )


def _valid_snapshot_content(source: dict[str, Any]) -> bool:
    text = source.get("text")
    text_hash = str(source.get("sha256") or source.get("text_sha256") or "")
    if not isinstance(text, str) or not text.strip():
        return False
    if not re.fullmatch(r"[a-f0-9]{64}", text_hash):
        return False
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != text_hash:
        return False
    if source.get("sha256") and source.get("text_sha256") and source["sha256"] != source["text_sha256"]:
        return False

    pages = source.get("pages")
    if pages is not None:
        if not isinstance(pages, list) or not pages or len(pages) > 5:
            return False
        numbers = [page.get("page") for page in pages if isinstance(page, dict)]
        if len(numbers) != len(pages) or any(
            not isinstance(number, int) or isinstance(number, bool) or number < 1
            for number in numbers
        ):
            return False
        if numbers != list(range(numbers[0], numbers[0] + len(numbers))):
            return False
        page_start = source.get("page_start", numbers[0])
        page_end = source.get("page_end", numbers[-1])
        page_text = "\n\n".join(str(page.get("text") or "") for page in pages)
        if (
            page_start != numbers[0]
            or page_end != numbers[-1]
            or " ".join(page_text.split()) != " ".join(text.split())
        ):
            return False
    return True


def _snapshot(
    source: dict[str, Any],
    requested_url: str,
    *,
    workspace_id: str,
    owner_scope: str,
    question: str,
) -> dict[str, Any] | None:
    from app.services.trusted_source_reader import validate_source_url

    returned_url = str(source.get("url") or "")
    try:
        validate_source_url(returned_url)
    except (TypeError, ValueError):
        return None
    if urldefrag(returned_url)[0] != requested_url or not _has_readable_text(source):
        return None
    parsed = urlsplit(returned_url)
    document_hash = str(source.get("document_sha256") or source.get("sha256") or "")[:128]
    if not re.fullmatch(r"[a-f0-9]{64}", document_hash):
        return None
    page_start = source.get("page_start", 1)
    page_end = source.get("page_end", page_start)
    if any(not isinstance(page, int) or isinstance(page, bool) or page < 1 for page in (page_start, page_end)) or page_end < page_start:
        return None
    extraction_version = str(source.get("extraction_version") or _EXTRACTION_VERSION)[:100]
    if not _valid_snapshot_content(source):
        return None
    owner_hash = hashlib.sha256(owner_scope.encode("utf-8")).hexdigest()
    identity = json.dumps(
        [workspace_id, owner_hash, returned_url, document_hash, page_start, page_end, extraction_version],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    saved = dict(source)
    saved.update(
        {
            "url": returned_url,
            "domain": parsed.hostname or "",
            "document_sha256": document_hash,
            "snapshot_key": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
            "snapshot_scope_sha256": owner_hash,
            "snapshot_timestamp": datetime.now(timezone.utc).isoformat(),
            "extraction_version": extraction_version,
            "content_status": "readable",
            "legal_effect_status": "unverified",
            "source_type": "official_government",
            "topic_sha256": hashlib.sha256(
                "\n".join(build_free_web_queries(question)).encode("utf-8")
            ).hexdigest(),
            "snapshot_reused": False,
        }
    )
    # The reader bounds text/pages already. Apply a second defensive cap before
    # the snapshot enters the Mongo workspace document.
    if isinstance(saved.get("text"), str):
        saved["text"] = saved["text"][:120_000]
    if isinstance(saved.get("pages"), list):
        saved["pages"] = saved["pages"][:5]
    return saved


def _cached_snapshot(
    candidates: list[dict[str, Any]],
    url: str,
    *,
    question: str,
    workspace_id: str,
    owner_scope: str,
    now: datetime,
) -> dict[str, Any] | None:
    owner_hash = hashlib.sha256(owner_scope.encode("utf-8")).hexdigest()
    current_law = bool(_CURRENT_LAW.search(fold_topic_text(question)))
    topic_hash = hashlib.sha256(
        "\n".join(build_free_web_queries(question)).encode("utf-8")
    ).hexdigest()
    for candidate in candidates:
        if not isinstance(candidate, dict) or candidate.get("source_type") != "official_government":
            continue
        try:
            from app.services.trusted_source_reader import validate_source_url

            cached_url = validate_source_url(str(candidate.get("url") or ""))
        except (TypeError, ValueError):
            continue
        if (
            urldefrag(cached_url)[0] != url
            or not is_official_source(cached_url, urlsplit(cached_url).hostname or "")
            or not _has_readable_text(candidate)
            or not _valid_snapshot_content(candidate)
        ):
            continue
        if candidate.get("snapshot_scope_sha256") != owner_hash:
            continue
        stamp = candidate.get("snapshot_timestamp") or candidate.get("retrieved_at")
        try:
            parsed_stamp = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            if parsed_stamp.tzinfo is None:
                parsed_stamp = parsed_stamp.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        age = (now - parsed_stamp).total_seconds()
        if age < -30 or age > _SNAPSHOT_TTL_SECONDS:
            continue
        text_hash = str(candidate.get("sha256") or candidate.get("text_sha256") or "")
        page_start, page_end = candidate.get("page_start", 1), candidate.get("page_end", candidate.get("page_start", 1))
        document_hash = str(candidate.get("document_sha256") or text_hash)
        version = str(candidate.get("extraction_version") or "")
        identity = json.dumps(
            [workspace_id, owner_hash, cached_url, document_hash, page_start, page_end, version],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if not version or hashlib.sha256(identity.encode("utf-8")).hexdigest() != candidate.get("snapshot_key"):
            continue
        is_pdf = candidate.get("method") == "pdf_text" or candidate.get("page_count") is not None
        if current_law or (is_pdf and candidate.get("topic_sha256") != topic_hash):
            continue
        return {**candidate, "snapshot_reused": True}
    return None


async def stream_free_web_research(
    question: str,
    *,
    provider=None,
    reader=None,
    settings=None,
    workspace_id: str = "",
    owner_scope: str = "",
    cached_sources: list[dict[str, Any]] | None = None,
    refresh: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """Yield actual bounded discovery/read events; the route checkpoints each."""
    settings = settings or get_settings()
    if not getattr(settings, "OFFICIAL_WEB_RESEARCH_ENABLED", True) or not getattr(
        settings, "FREE_WEB_RESEARCH_ENABLED", True
    ):
        raise FreeWebResearchDisabled("free_official_research_disabled")
    clean_question = _clean_question(question)
    queries = build_free_web_queries(clean_question)
    if not queries:
        yield {"type": "terminal", "status": "failed", "error_kind": "question_required"}
        return

    if provider is None:
        provider = _configured_provider(settings)
    if reader is None:
        from app.services.trusted_source_reader import read_source

        reader = read_source

    total_budget = min(
        180.0,
        max(0.1, float(getattr(settings, "FREE_WEB_RESEARCH_TOTAL_BUDGET_SECONDS", 180.0))),
    )
    discovery_budget = min(
        60.0,
        max(0.05, float(getattr(settings, "FREE_WEB_RESEARCH_DISCOVERY_BUDGET_SECONDS", 60.0))),
        total_budget,
    )
    read_budget = min(
        105.0,
        max(0.05, float(getattr(settings, "FREE_WEB_RESEARCH_READ_BUDGET_SECONDS", 105.0))),
        total_budget,
    )
    provider_timeout = min(
        10.0,
        max(0.05, float(getattr(settings, "FREE_WEB_RESEARCH_PROVIDER_TIMEOUT_SECONDS", 10.0))),
    )
    network_limit = max(
        1,
        min(2, int(getattr(settings, "FREE_WEB_RESEARCH_NETWORK_CONCURRENCY", 2))),
    )
    query_gate = asyncio.Semaphore(min(_QUERY_CONCURRENCY, network_limit))
    started_at = asyncio.get_running_loop().time()
    overall_deadline = started_at + total_budget
    yield {"type": "started", "status": "running", "query_count": len(queries)}

    candidates: dict[str, dict[str, str]] = {}
    discovery_deadline = min(overall_deadline, started_at + discovery_budget)
    started_queries: set[str] = set()

    async def run_query(query: str) -> dict[str, Any] | None:
        try:
            async with query_gate:
                if asyncio.get_running_loop().time() >= discovery_deadline:
                    return None
                started_queries.add(query)
                remaining = min(provider_timeout, discovery_deadline - asyncio.get_running_loop().time())
                if remaining <= 0:
                    return None
                async with asyncio.timeout(remaining):
                    result = await provider.search(query, limit=10)
            rows = getattr(result, "results", ())
            errors = tuple(getattr(result, "errors", ()) or ())
            accepted = 0
            for row in rows:
                url = _candidate_url(row)
                if not url:
                    continue
                source_row = _source_record(row) | {"url": url}
                if url not in candidates or _candidate_rank(source_row, clean_question) < _candidate_rank(candidates[url], clean_question):
                    candidates[url] = source_row
                accepted += 1
            return {
                "type": "query",
                "query": query,
                "status": "partial_results" if errors and accepted else (
                    "provider_error" if errors and not accepted else (
                        "results_found" if accepted else "no_results"
                    )
                ),
                "source_count": accepted,
                "error_kind": ";".join(str(item) for item in errors)[:160] or None,
                "provider": str(getattr(result, "provider", "official_federation"))[:100],
                "method": str(getattr(result, "method", "federated-official-discovery-v1"))[:100],
            }
        except asyncio.CancelledError:
            raise
        except (TimeoutError, asyncio.TimeoutError):
            return {"type": "query", "query": query, "status": "provider_error", "source_count": 0, "error_kind": "provider_timeout"}
        except Exception as error:
            error_kind = str(getattr(error, "kind", type(error).__name__))[:100]
            return {"type": "query", "query": query, "status": "provider_error", "source_count": 0, "error_kind": error_kind}

    query_tasks = [asyncio.create_task(run_query(query)) for query in queries]
    query_by_task = dict(zip(query_tasks, queries))
    pending = set(query_tasks)
    query_events: list[dict[str, Any]] = []
    try:
        while pending:
            remaining = discovery_deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            done, pending = await asyncio.wait(
                pending,
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                break
            for task in done:
                event = task.result()
                if event is not None:
                    query_events.append(event)
                    yield event
        timed_out_tasks = set(pending)
        for task in timed_out_tasks:
            task.cancel()
        if timed_out_tasks:
            await asyncio.gather(*timed_out_tasks, return_exceptions=True)
            # A request that acquired the query gate was actually sent. Preserve
            # its deadline outcome after cancellation; queued queries have no
            # event because no provider call began.
            for task in timed_out_tasks:
                query = query_by_task[task]
                if query in started_queries:
                    event = {
                        "type": "query",
                        "query": query,
                        "status": "provider_error",
                        "source_count": 0,
                        "error_kind": "discovery_deadline",
                    }
                    query_events.append(event)
                    yield event
    finally:
        for task in query_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*query_tasks, return_exceptions=True)

    query_complete = len(started_queries) == len(queries) and all(task.done() for task in query_tasks)
    discovery_timed_out = asyncio.get_running_loop().time() >= discovery_deadline
    query_error_count = sum(
        event.get("status") in {"provider_error", "partial_results"}
        for event in query_events
    )
    no_results_count = sum(event.get("status") == "no_results" for event in query_events)
    source_results: list[dict[str, Any]] = []
    source_errors: list[dict[str, str]] = []
    read_deadline = min(overall_deadline, asyncio.get_running_loop().time() + read_budget)
    ranked_candidates = sorted(
        candidates.items(), key=lambda item: _candidate_rank(item[1], clean_question)
    )
    relevance_threshold = 4 if _official_title_families(clean_question) else 1
    candidate_rows = [
        item for item in ranked_candidates
        if -_candidate_rank(item[1], clean_question)[0] >= relevance_threshold
    ][:min(_MAX_SELECTED_SOURCES, int(getattr(settings, "FREE_WEB_RESEARCH_MAX_READ_ATTEMPTS", 3)))]

    read_count = 0
    reused_count = 0
    owner_scope = owner_scope or "anonymous"
    cached_sources = cached_sources or []
    force_fresh = bool(refresh or _CURRENT_LAW.search(fold_topic_text(clean_question)))

    async def read_candidate(url: str, metadata: dict[str, str]) -> tuple[str, dict[str, Any] | None, str | None, list[int] | None]:
        nonlocal read_count
        remaining = min(45.0, read_deadline - asyncio.get_running_loop().time())
        if remaining <= 0:
            return url, None, "read_deadline", None
        try:
            async with asyncio.timeout(remaining):
                async with _NETWORK_SEMAPHORE:
                    read_count += 1
                    source = await reader(
                        url,
                        question=clean_question,
                        smart_pages=True,
                        use_ocr=False,
                        page_limit=min(
                            5,
                            int(getattr(settings, "FREE_WEB_RESEARCH_PAGE_LIMIT", 5)),
                        ),
                    )
            if not isinstance(source, dict):
                return url, None, "invalid_source_response", None
            merged = {**metadata, **source}
            snapshot = _snapshot(
                merged,
                url,
                workspace_id=workspace_id,
                owner_scope=owner_scope,
                question=clean_question,
            )
            inspected = source.get("inspected_pages")
            inspected_pages = [int(page) for page in inspected if isinstance(page, int) and page > 0] if isinstance(inspected, list) else None
            return url, snapshot, None if snapshot else "source_unreadable_or_url_mismatch", inspected_pages
        except asyncio.CancelledError:
            raise
        except (TimeoutError, asyncio.TimeoutError):
            return url, None, "source_timeout", None
        except Exception as error:
            return url, None, str(getattr(error, "kind", type(error).__name__))[:100], None

    # Select and rank at most three allowlisted URLs before any content fetch.
    for index in range(0, len(candidate_rows), network_limit):
        if asyncio.get_running_loop().time() >= read_deadline:
            break
        batch = candidate_rows[index : index + network_limit]
        tasks = []
        for url, metadata in batch:
            cached = None if force_fresh else _cached_snapshot(
                cached_sources,
                url,
                question=clean_question,
                workspace_id=workspace_id,
                owner_scope=owner_scope,
                now=datetime.now(timezone.utc),
            )
            if cached is not None:
                reused_count += 1
                source_results.append(cached)
                yield {"type": "source", "url": url, "status": "readable", "source": cached}
            else:
                tasks.append(asyncio.create_task(read_candidate(url, metadata)))
        try:
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        for outcome in batch_results:
            if isinstance(outcome, BaseException):
                continue
            url, snapshot, error_kind, inspected_pages = outcome
            if snapshot is None:
                error = {"url": url, "error_kind": error_kind or "source_unreadable"}
                if inspected_pages is not None:
                    error["inspected_pages"] = inspected_pages
                    error["inspected_page_count"] = len(inspected_pages)
                source_errors.append(error)
                yield {"type": "source", "status": "unreadable", **error}
                continue
            source_results.append(snapshot)
            yield {"type": "source", "url": url, "status": "readable", "source": snapshot}

    status = "failed" if not source_results else (
        "partial" if source_errors or query_error_count or discovery_timed_out or not query_complete else "complete"
    )
    yield {
        "type": "terminal",
        "status": status,
        "query_count": len(queries),
        "candidate_count": len(candidates),
        "source_count": len(source_results),
        "fetched_count": read_count,
        "reused_count": reused_count,
        "query_error_count": query_error_count,
        "no_results_count": no_results_count,
        "source_errors": source_errors[:_MAX_SELECTED_SOURCES],
        "error_kind": "discovery_deadline" if discovery_timed_out else None,
    }
