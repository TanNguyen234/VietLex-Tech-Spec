"""Ephemeral official-source search. No corpus, storage, OCR or model clients."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import re
import time

from app.services.instrument_registry import drop_superseded_contexts
from app.services.legal_topic_terms import contains_topic_phrase, fold_topic_text, local_rescue_terms
from app.services.official_search_plan import DEEP_READING, DOCUMENT_REFERENCE, build_official_search_plan
from app.services.trusted_source_reader import SourceReadError, is_official_document_url, validate_source_url
from app.services.web_source_tiers import classify_web_source_tier

_NETWORK = asyncio.Semaphore(2)


def _is_superseded(question, title, document_number):
    """Old versions are skipped before reading or packing; they never consume read time or evidence slots."""
    header = f"[{document_number or ''}]\nTiêu đề: {title or ''}"
    _, dropped = drop_superseded_contexts(question, [header])
    return bool(dropped)
_ARTICLE = re.compile(r"^\s*(?:Điều|Dieu)\s+\d+[a-zđ]?[.:][^\n]*", re.M | re.I)
_REQUESTED_ARTICLE = re.compile(r'\bdieu\s+(\d+)(?![\da-zđ])(?:\s*[-–]\s*(\d+)(?![\da-zđ]))?')
_TAIL = re.compile(r"^\s*(?:Nơi nhận\s*:|TM\.\s|KT\.\s|PHỤ LỤC\b)", re.M)


def _organization_only(title, question):
    if DOCUMENT_REFERENCE.search(question):
        return False
    return bool(re.search(r"chuc nang.{0,40}nhiem vu|co cau to chuc", fold_topic_text(title))
                and not re.search(r"chuc nang|co cau to chuc|to chuc bo may", fold_topic_text(question)))


def _year(item):
    for key in ("issued_date", "document_number", "title"):
        value = item.get(key, "") if isinstance(item, dict) else getattr(item, key, "")
        match = re.search(r"\b(?:19|20)\d{2}\b", str(value or ""))
        if match:
            return int(match.group())
    return 0  # Ranking hint only; never used as legal-effect proof.


def _date(value):
    for pattern in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value), pattern).date()
        except ValueError:
            continue
    return None


def _select_consolidations(sources, plan):
    """Keep one dated candidate per consolidated law; never certify current effect."""
    as_of = _date(plan.as_of) if plan.as_of else datetime.now(timezone.utc).date()
    chosen, alternatives, plain = {}, [], []
    for item in sources:
        issued = _date(item.get("issued_date"))
        if issued and as_of and issued > as_of:
            alternatives.append({"url": item["url"], "reason": "issued_after_requested_date"})
            continue
        family = re.search(r"hợp nhất ((?:Bộ luật|Luật|Nghị định|Thông tư|Pháp lệnh)\b.+)", str(item.get("title", "")), re.I)
        if not family:
            plain.append(item)
            continue
        key = fold_topic_text(family.group(1)).rstrip(" .")
        previous = chosen.get(key)
        previous_date = _date(previous.get("issued_date")) if previous else None
        if previous is None or (issued is not None and (previous_date is None or issued > previous_date)):
            if previous:
                alternatives.append({"url": previous["url"], "reason": "alternative_consolidation_unverified"})
            chosen[key] = item
        else:
            alternatives.append({"url": item["url"], "reason": "alternative_consolidation_unverified"})
    return [*plain, *chosen.values()], alternatives


def _effect_status(sources):
    """Metadata disagreements are observable; absence of disagreement is no proof."""
    groups = {}
    def normalized(value):
        for pattern in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(value), pattern).date().isoformat()
            except ValueError:
                continue
        return str(value)
    for item in sources:
        key = (item.get("document_number"), item.get("issuing_authority", ""))
        if key[0]:
            groups.setdefault(key, set()).update(
                [normalized(item["reported_effective_from"])] if item.get("reported_effective_from") else []
            )
        declared = re.search(
            r"(?:Luật|Nghị định|Thông tư|Quyết định|Văn bản) này có hiệu lực(?: thi hành)?(?: kể)? từ ngày (\d{1,2}) tháng (\d{1,2}) năm (\d{4})",
            " ".join(str(item.get("text", "")).split()), re.I)
        if declared and item.get("reported_effective_from"):
            actual = "/".join(declared.groups())
            if normalized(actual) != normalized(item["reported_effective_from"]):
                return "conflicting"
    return "conflicting" if any(len(values) > 1 for values in groups.values()) else "unverified"


_SENTENCE_END_TAIL = re.compile(r'[.;!?]["”’)\]]*\s*$')


def _contiguous_article_runs(item: dict) -> list[tuple[str, bool]]:
    """Split extracted text into contiguous page runs so non-contiguous deep PDF reads never merge across gaps."""
    pages = item.get("pages")
    page_count = item.get("page_count")
    if isinstance(pages, list) and len(pages) > 1:
        runs: list[list[dict]] = []
        for page in pages:
            if not isinstance(page, dict) or not isinstance(page.get("page"), int):
                runs = []
                break
            if runs and page["page"] == runs[-1][-1]["page"] + 1:
                runs[-1].append(page)
            else:
                runs.append([page])
        if runs:
            output: list[tuple[str, bool]] = []
            for run in runs:
                raw_text = "\n\n".join(str(p.get("text") or "") for p in run).strip()
                if not raw_text:
                    continue
                tail = _TAIL.search(raw_text)
                clean_text = raw_text[: tail.start()] if tail else raw_text
                end_page = run[-1]["page"]
                cut_at_end = (
                    bool(item.get("truncated"))
                    and tail is None
                    and (not isinstance(page_count, int) or end_page < page_count)
                )
                output.append((clean_text, cut_at_end))
            return output

    text = str(item.get("text") or "")
    tail = _TAIL.search(text)
    article_text = text[: tail.start()] if tail else text
    end_page = item.get("page_end")
    cut_at_end = (
        bool(item.get("truncated"))
        and tail is None
        and (
            not isinstance(page_count, int)
            or not isinstance(end_page, int)
            or end_page < page_count
        )
    )
    return [(article_text, cut_at_end)]


def pack_sources(
    sources,
    plan,
    profile=DEEP_READING,
    *,
    deadline=None,
    pivoted_numbers: set[str] | None = None,
    pivoted_articles: set[int] | None = None,
):
    """Select intact articles by facet coverage, retaining exact text and provenance."""
    from app.services.chat_official_supplement import _source_context
    from app.services.evidence_presenter import EphemeralOfficialEvidenceContext
    excluded, validated_sources = [], []
    deadline_exceeded = False
    pivoted_numbers = {n.upper().replace("Ð", "Đ") for n in (pivoted_numbers or set())}
    pivoted_articles = set(pivoted_articles or set())
    # Validate before version selection/deduplication: an invalid mirror must
    # neither replace a valid source nor contribute conflict metadata.
    for source_index, item in enumerate(sources):
        if deadline is not None and time.perf_counter() >= deadline:
            deadline_exceeded = True
            break
        text = item.get("text", "")
        reason = None
        if _organization_only(item.get("title", ""), plan.original_question):
            reason = "organization_instrument"
        elif _is_superseded(plan.original_question, item.get("title", ""), item.get("document_number", "")):
            reason = "superseded_version"
        elif not isinstance(text, str) or not text.strip() or item.get("content_status") == "metadata_only":
            reason = "metadata_only"
        elif hashlib.sha256(text.encode()).hexdigest() != item.get("sha256"):
            reason = "content_hash_mismatch"
        elif _source_context(item.get("url"), item, plan.original_question, excerpt_override=text) is None:
            reason = "invalid_provenance"
        if reason:
            excluded.append({"source": source_index, "url": item.get("url"),
                             "phase": "source_validation", "reason": reason})
        else:
            validated_sources.append(item)
    sources, alternative_versions = _select_consolidations(validated_sources, plan)
    candidates, seen = [], set()
    verified_versions = {}
    terms = set(local_rescue_terms(" ".join(plan.topics), limit=40))
    requested_articles = [(int(m.group(1)), int(m.group(2) or m.group(1)))
                          for m in _REQUESTED_ARTICLE.finditer(fold_topic_text(plan.original_question))]
    for source_index, item in enumerate(sources[:profile.source_limit]):
        if deadline is not None and time.perf_counter() >= deadline:
            deadline_exceeded = True
            break
        identity = (item.get("document_number"), item.get("issuing_authority", ""),
                    item["sha256"])
        verified_versions.setdefault(identity, []).append(item)
        if identity in seen:
            excluded.append({"source": source_index, "reason": "duplicate_source"})
            continue
        seen.add(identity)
        actual_number = item.get("document_number") or (
            DOCUMENT_REFERENCE.search(str(item.get("title", ""))).group()
            if DOCUMENT_REFERENCE.search(str(item.get("title", ""))) else "")
        norm_actual_number = actual_number.upper().replace("Ð", "Đ")
        explicit_document = bool(
            (plan.reference and norm_actual_number == plan.reference.replace("Ð", "Đ"))
            or (norm_actual_number and norm_actual_number in pivoted_numbers)
        )
        for article_text, cut_at_end in _contiguous_article_runs(item):
            headings = list(_ARTICLE.finditer(article_text))
            for index, match in enumerate(headings):
                if deadline is not None and time.perf_counter() >= deadline:
                    deadline_exceeded = True
                    break
                label = match.group().strip()
                end = headings[index + 1].start() if index + 1 < len(headings) else len(article_text)
                excerpt = article_text[match.start():end].strip()
                if index == len(headings) - 1 and (
                    item.get("requires_ocr")
                    or (cut_at_end and not _SENTENCE_END_TAIL.search(excerpt))
                ):
                    excluded.append({"source": source_index, "article": label, "reason": "incomplete_article"})
                    continue
                if "\ufffd" in excerpt:
                    excluded.append({"source": source_index, "article": label, "reason": "unreliable_text_encoding"})
                    continue
                if "trach nhiem thi hanh" in fold_topic_text(label) and "thi hanh" not in fold_topic_text(plan.original_question):
                    continue
                covered = {topic for topic in plan.topics if contains_topic_phrase(excerpt, topic)}
                overlap = len(terms.intersection(local_rescue_terms(excerpt, limit=256)))
                numeric_heading = re.match(r'(?:Điều|Dieu)\s+(\d+)[.:]', label, re.I)
                heading_num = int(numeric_heading.group(1)) if numeric_heading else None
                requested_article = bool(heading_num is not None) and (
                    ((not plan.reference or explicit_document) and any(
                        first <= heading_num <= last for first, last in requested_articles
                    ))
                    or (explicit_document and heading_num in pivoted_articles)
                )
                if plan.status == "recognized" and not covered and not explicit_document and not requested_article:
                    excluded.append({"source": source_index, "article": label, "reason": "unrelated_topic"})
                    continue
                if not covered and overlap < 2 and not explicit_document and not requested_article:
                    continue
                context = _source_context(item["url"], item, plan.original_question, excerpt_override=excerpt)
                if context is None:
                    excluded.append({"source": source_index, "article": label, "reason": "invalid_provenance"})
                    continue
                context = EphemeralOfficialEvidenceContext(context)
                heading_score = sum(contains_topic_phrase(label, t) for t in plan.topics) * 4
                candidates.append((context, covered, overlap + heading_score, source_index, label, _year(item), requested_article))
    contexts, covered, used_sources = [], set(), set()
    remaining = profile.context_tokens
    while candidates and len(contexts) < profile.evidence_limit:
        if deadline is not None and time.perf_counter() >= deadline:
            deadline_exceeded = True
            break
        candidates.sort(key=lambda c: (c[6], len(c[1] - covered), c[2], c[5], c[3] not in used_sources, -len(c[0].split())), reverse=True)
        context, facets, _, source_index, article, _, _ = candidates.pop(0)
        required = len(context.split()) + len(f"[Tài liệu tham khảo #{len(contexts) + 1}]".split())
        if required > remaining:
            excluded.append({"source": source_index, "article": article, "reason": "context_budget"})
            continue
        contexts.append(context)
        covered.update(facets)
        used_sources.add(source_index)
        remaining -= required
    excluded.extend({"source": c[3], "article": c[4], "reason": "evidence_limit"} for c in candidates)
    # Only sources that survive quality, topic and budget gates describe the
    # returned evidence. Discarded candidates cannot poison its metadata status.
    retained_identities = {
        (sources[index].get("document_number"), sources[index].get("issuing_authority", ""),
         sources[index]["sha256"]) for index in used_sources
    }
    # Valid mirrors of a retained document still expose metadata disagreements.
    status = _effect_status([
        item for identity, versions in verified_versions.items()
        if identity in retained_identities for item in versions
    ])
    if status == "conflicting":
        contexts = [EphemeralOfficialEvidenceContext(context.replace(
            "Hiệu lực pháp lý: unverified", "Hiệu lực pháp lý: conflicting", 1))
            for context in contexts]
    return contexts, {
        "profile": asdict(profile), "budget_unit": "approx_whitespace_tokens",
        "context_tokens": profile.context_tokens - remaining, "evidence_blocks": len(contexts),
        "legal_effect_status": status, "effect_as_of": plan.as_of or datetime.now(timezone.utc).date().isoformat(),
        "effect_reason": "conflicting_metadata" if status == "conflicting" else "amendment_chain_not_verified",
        "topic_coverage": {"covered": sorted(covered), "missing": [t for t in plan.topics if t not in covered],
                           "status": "known" if plan.status == "recognized" else "unknown"},
        "excluded_blocks": excluded, "packing_deadline_exceeded": deadline_exceeded,
        "alternative_versions": alternative_versions,
        "version_selection_status": "candidate_only_effect_unverified",
    }


async def search_and_read(question, *, settings=None, providers=None, reader=None, browser=None, profile=DEEP_READING,
                          explicit_queries=None, explicit_topics=None, reader_hint=""):
    from dataclasses import replace as _replace
    from types import SimpleNamespace

    from app.config import get_settings
    from app.services.chat_official_supplement import OfficialSupplementResult
    from app.services.tavily_search import TavilyOfficialClient, is_tavily_search_enabled
    from app.services.trusted_source_reader import read_source
    active_settings = settings if settings is not None else get_settings()
    plan = build_official_search_plan(question)
    if explicit_queries:
        # Registry-driven queries name the current instrument directly; they replace the derived plan.
        plan = _replace(
            plan,
            queries=tuple(" ".join(str(query).split())[:220] for query in explicit_queries[:profile.query_limit] if str(query).strip()),
            topics=tuple(explicit_topics) or plan.topics,
            status="registry",
            current_required=True,
        )
    started = time.perf_counter()
    loop = asyncio.get_running_loop()
    overall_deadline = loop.time() + min(60, profile.total_seconds)
    diagnostics = {"search_queries": 0, "queries_completed": 0, "provider_attempts": 0, "urls_discovered": 0,
                   "sources_read": 0, "sources_downloaded": 0, "read_failures": 0, "query_status": plan.status,
                   "errors": [], "queries": list(plan.queries), "phase_seconds": {},
                   "budget_unit": "approx_whitespace_tokens", "profile": asdict(profile)}
    if not plan.queries:
        return OfficialSupplementResult("unknown", [], diagnostics, time.perf_counter() - started)
    if providers is None:
        from app.services.official_web_search import OfficialPortalClient
        from app.services.congbao_search import CongBaoClient
        if is_tavily_search_enabled(active_settings):
            providers = [
                TavilyOfficialClient(settings=active_settings),
                CongBaoClient(settings=active_settings),
                OfficialPortalClient(settings=active_settings),
            ]
        else:
            from app.services.vbpl_search import VbplClient
            providers = [OfficialPortalClient(settings=active_settings), CongBaoClient(settings=active_settings), VbplClient()]
    default_reader = reader is None
    reader = reader or read_source
    records = {}
    raw_markdown_by_url: dict[str, str] = {}
    pivot_numbers: list[str] = []
    pivot_articles: list[int] = []
    pivot_superseded: set[str] = set()
    started_queries, completed_queries = set(), set()

    def _ingest_response(response):
        raw_md = getattr(response, "tier1_raw_markdown", None)
        if isinstance(raw_md, dict):
            for md_url, md_body in raw_md.items():
                try:
                    valid_md_url = validate_source_url(md_url)
                    if classify_web_source_tier(valid_md_url) != "official_primary":
                        continue
                except (ValueError, TypeError):
                    continue
                if isinstance(md_body, str) and md_body.strip():
                    raw_markdown_by_url.setdefault(valid_md_url, md_body)
        hints = getattr(response, "pivot_hints", None)
        if hints is not None:
            for num in getattr(hints, "document_numbers", ()):
                if num and num not in pivot_numbers:
                    pivot_numbers.append(num)
            for art in getattr(hints, "target_articles", ()):
                if isinstance(art, int) and art not in pivot_articles:
                    pivot_articles.append(art)
            for sup in getattr(hints, "superseded_numbers", ()):
                if sup:
                    pivot_superseded.add(sup.upper().replace("Ð", "Đ"))
        for record in getattr(response, "results", ()):
            try:
                url = validate_source_url(record.url)
                if classify_web_source_tier(url) != "official_primary":
                    continue
                if not is_official_document_url(url) and url not in raw_markdown_by_url:
                    continue
            except (ValueError, AttributeError):
                continue
            records[url] = record

    async def discover(provider, query, *, tier1_only: bool = False):
        name = type(provider).__name__
        if isinstance(provider, TavilyOfficialClient):
            prov_timeout = min(
                6.0,
                float(getattr(active_settings, "TAVILY_TIMEOUT_SECONDS", 6.0) or 6.0),
            )
        elif name == "OfficialPortalClient":
            prov_timeout = 1.75
        elif name == "CongBaoClient":
            prov_timeout = 3.5
        else:
            prov_timeout = min(profile.discovery_seconds, max(0.05, overall_deadline - loop.time()))
        try:
            async with _NETWORK:
                started_queries.add(query)
                diagnostics["search_queries"] = len(started_queries)
                diagnostics["provider_attempts"] += 1
                if tier1_only and isinstance(provider, TavilyOfficialClient):
                    coro = provider.search(query, limit=5, include_tier2=False)
                else:
                    coro = provider.search(query, limit=8)
                response = await asyncio.wait_for(coro, timeout=prov_timeout)
            completed_queries.add(query)
            diagnostics["queries_completed"] = len(completed_queries)
            for error in getattr(response, "errors", ()):
                diagnostics["errors"].append({"phase": "discovery", "provider": name, "kind": str(error)[:100]})
            _ingest_response(response)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            diagnostics["errors"].append({"phase": "discovery", "provider": name,
                                          "kind": str(getattr(error, "kind", type(error).__name__))[:100]})
    phase_started = loop.time()
    has_tavily = any(isinstance(p, TavilyOfficialClient) for p in providers)
    tasks = [
        asyncio.create_task(discover(provider, query))
        for q_idx, query in enumerate(plan.queries[:profile.query_limit])
        for provider in providers
        if not isinstance(provider, TavilyOfficialClient) or q_idx < 2
    ]
    hop1_budget = max(
        0,
        min(
            5.0 if has_tavily else profile.discovery_seconds,
            profile.discovery_seconds,
            overall_deadline - loop.time(),
        ),
    )
    try:
        _, pending = await asyncio.wait(tasks, timeout=hop1_budget)
        if pending:
            diagnostics["errors"].append({"phase": "discovery", "kind": "deadline"})
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # Two-Hop Pivot when Tier-2 discovered exact legal document numbers.
    rescued_contexts: list[str] = []
    rescued_numbers: set[str] = set()
    if pivot_numbers:
        diagnostics["pivot_hints"] = {
            "document_numbers": list(pivot_numbers[:6]),
            "target_articles": list(pivot_articles[:6]),
            "superseded_numbers": sorted(pivot_superseded)[:10],
        }
        # Hop 2A: Fast local/Supabase corpus rescue (<100ms when indexed).
        if browser is not None or settings is None or hasattr(active_settings, "CONTENT_STORE_PATH"):
            def _run_corpus_rescue():
                active_browser = browser
                if active_browser is None:
                    from app.services.legal_browser import LegalBrowser
                    active_browser = LegalBrowser.from_settings(active_settings)
                from app.services.official_discovered_corpus_rescue import rescue_official_discoveries
                return rescue_official_discoveries(
                    question,
                    [SimpleNamespace(document_number=num) for num in pivot_numbers[:4]],
                    active_browser,
                    settings=active_settings,
                )

            try:
                rescue_budget = min(2.5, max(0.05, overall_deadline - loop.time()))
                rescue_res = await asyncio.wait_for(
                    asyncio.to_thread(_run_corpus_rescue),
                    timeout=rescue_budget,
                )
                diagnostics["official_corpus_rescue"] = dict(rescue_res.diagnostics)
                if rescue_res.evidence:
                    rescued_contexts = [chunk.formatted_context() for chunk in rescue_res.evidence]
                    rescued_numbers = {
                        re.sub(r"\s+", "", str(chunk.document_number or "")).upper().replace("Ð", "Đ")
                        for chunk in rescue_res.evidence
                        if chunk.document_number
                    }
            except Exception as exc:
                diagnostics["official_corpus_rescue"] = {
                    "status": "rescue_error",
                    "error_type": type(exc).__name__,
                }

        # Hop 2B: Targeted Tier-1 exact-number search for unrescued pivot numbers not yet in records.
        covered_tier1 = {
            re.sub(r"\s+", "", str(getattr(r, "document_number", "") or "")).upper().replace("Ð", "Đ")
            for r in records.values()
        }
        for r in records.values():
            for m in DOCUMENT_REFERENCE.finditer(str(getattr(r, "title", "") or "")):
                covered_tier1.add(m.group(0).upper().replace("Ð", "Đ"))
        missing_pivots = [
            num for num in pivot_numbers[:3]
            if num.upper().replace("Ð", "Đ") not in rescued_numbers
            and num.upper().replace("Ð", "Đ") not in covered_tier1
        ]
        hop2_remaining = min(profile.discovery_seconds, overall_deadline - loop.time() - 1.0)
        if missing_pivots and hop2_remaining > 0.1:
            tier1_providers = [
                p for p in providers
                if isinstance(p, TavilyOfficialClient) or type(p).__name__ == "CongBaoClient"
            ] or providers[:2]
            hop2_tasks = [
                asyncio.create_task(discover(p, doc_num, tier1_only=True))
                for doc_num in missing_pivots[:2]
                for p in tier1_providers
            ]
            try:
                await asyncio.wait(hop2_tasks, timeout=max(0.1, hop2_remaining))
            finally:
                for task in hop2_tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*hop2_tasks, return_exceptions=True)

    diagnostics["phase_seconds"]["discovery"] = round(loop.time()-phase_started, 3)
    diagnostics["urls_discovered"] = len(records)
    diagnostics["discovered_urls"] = sorted(records)[:120]
    terms = set(local_rescue_terms(" ".join(plan.topics), limit=40))
    def rank(record):
        metadata = record.title + " " + getattr(record, "snippet", "")
        rec_num = re.sub(r"\s+", "", str(getattr(record, "document_number", "") or "")).upper().replace("Ð", "Đ")
        pivot_boost = 4 if rec_num and rec_num in {n.upper().replace("Ð", "Đ") for n in pivot_numbers} else 0
        return (sum(contains_topic_phrase(metadata, t) for t in plan.topics) + pivot_boost,
                len(terms.intersection(local_rescue_terms(metadata, limit=128))))

    def _record_superseded(rec):
        doc_num = re.sub(r"\s+", "", str(getattr(rec, "document_number", "") or "")).upper().replace("Ð", "Đ")
        if doc_num and doc_num in pivot_superseded and doc_num not in question.upper().replace("Ð", "Đ"):
            return True
        return _is_superseded(question, rec.title, getattr(rec, "document_number", ""))

    superseded_urls = {u for u, r in records.items() if _record_superseded(r)}
    diagnostics["superseded_skipped"] = sorted(superseded_urls)[:40]
    queue = [(u, r) for u, r in sorted(records.items(), key=lambda pair: (-rank(pair[1])[0], -_year(pair[1]), -rank(pair[1])[1], pair[0]))
             if not _organization_only(r.title, question) and u not in superseded_urls]
    sources, attempted, pending = [], set(), set()
    phase_started = loop.time()
    pack_reserve = min(5, profile.total_seconds / 12)
    cleanup_reserve = min(3, profile.read_seconds / 10)
    read_deadline = min(overall_deadline - pack_reserve - cleanup_reserve,
                        loop.time() + profile.read_seconds - cleanup_reserve)
    article_hint_str = (
        f"[gợi ý điều khoản: {', '.join(str(a) for a in pivot_articles[:6])}]"
        if pivot_articles
        else ""
    )
    reader_question = " ".join(
        part for part in (plan.original_question, str(reader_hint or "").strip(), article_hint_str) if part
    )
    async def read_one(url, record):
        try:
            if default_reader and url in raw_markdown_by_url:
                md_text = raw_markdown_by_url[url][:120_000]
                md_sha = hashlib.sha256(md_text.encode("utf-8")).hexdigest()
                item = {
                    "url": url,
                    "title": (getattr(record, "title", "") if record else "") or url,
                    "text": md_text,
                    "sha256": md_sha,
                    "text_sha256": md_sha,
                    "document_sha256": md_sha,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "method": "tavily_raw_markdown_tier1",
                    "content_status": "full_text",
                    "legal_effect_status": "unverified",
                    "document_number": (getattr(record, "document_number", "") if record else "") or None,
                    "issued_date": (getattr(record, "issued_date", "") if record else "") or None,
                    "truncated": False,
                    "related_urls": [],
                }
            else:
                async with _NETWORK:
                    extra_kw = {"settings": active_settings} if default_reader and settings is not None else {}
                    item = await reader(url, question=reader_question, smart_pages=True, deep_read=True,
                                        use_ocr=False, page_limit=20, **extra_kw)
            if not isinstance(item, dict) or item.get("url") != url:
                raise SourceReadError("source_url_mismatch")
            item = dict(item)
            diagnostics["sources_downloaded"] += 1
            if not item.get("document_number"):
                number = DOCUMENT_REFERENCE.search(str(item.get("title") or ""))
                if number:
                    item["document_number"] = number.group().upper().replace("Ð", "Đ")
            # Discovery metadata identifies candidates; it never supplies body or effect proof.
            if record:
                discovered = getattr(record, "document_number", "")
                if discovered and item.get("document_number") and discovered.replace("Ð", "Đ").casefold().replace(" ", "") != str(item["document_number"]).replace("Ð", "Đ").casefold().replace(" ", ""):
                    raise SourceReadError("document_identity_conflict")
            sources.append(item)
            readable = bool(str(item.get("text") or "").strip()) and item.get("content_status") != "metadata_only"
            if readable:
                diagnostics["sources_read"] += 1
            else:
                diagnostics["read_failures"] += 1
                diagnostics["errors"].append({"phase": "extraction", "url": url, "kind": "source_metadata_only"})
            diagnostics.setdefault("source_reads", []).append({
                "url": url, "sha256": item.get("sha256"), "document_sha256": item.get("document_sha256"),
                "inspected_pages": item.get("inspected_pages", []),
                "retained_pages": [p["page"] for p in item.get("pages", [])],
                "partial_read": bool(item.get("truncated") or item.get("requires_ocr")),
            })
            for related in item.get("related_urls", ())[:8]:
                try:
                    related = validate_source_url(related)
                    if not is_official_document_url(related):
                        continue
                except (ValueError, TypeError):
                    continue
                if related not in attempted and all(related != entry[0] for entry in queue):
                    queue.insert(0, (related, None))
        except asyncio.CancelledError:
            diagnostics["read_failures"] += 1
            diagnostics["errors"].append({"phase": "read", "url": url, "kind": "deadline"})
            raise
        except Exception as error:
            diagnostics["read_failures"] += 1
            kind = str(getattr(error, "kind", type(error).__name__))[:100]
            phase = "download" if kind.startswith(("source_http", "source_transport", "source_redirect", "source_body")) else "extraction"
            diagnostics["errors"].append({"phase": phase, "url": url, "kind": kind})
    def _record_doc_numbers(rec) -> set[str]:
        if rec is None:
            return set()
        found: set[str] = set()
        raw_num = re.sub(r"\s+", "", str(getattr(rec, "document_number", "") or "")).upper().replace("Ð", "Đ")
        if raw_num:
            found.add(raw_num)
        for m in DOCUMENT_REFERENCE.finditer(str(getattr(rec, "title", "") or "")):
            found.add(re.sub(r"\s+", "", m.group(0)).upper().replace("Ð", "Đ"))
        return found

    try:
        while loop.time() < read_deadline:
            while queue and len(pending) < 2 and len(attempted) < profile.source_limit:
                url, record = queue.pop(0)
                if url in attempted:
                    continue
                if (
                    rescued_contexts
                    and url not in raw_markdown_by_url
                    and bool(_record_doc_numbers(record) & rescued_numbers)
                ):
                    continue
                attempted.add(url)
                pending.add(asyncio.create_task(read_one(url, record)))
            if not pending:
                break
            _, pending = await asyncio.wait(pending, timeout=max(0, read_deadline-loop.time()), return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    diagnostics["phase_seconds"]["read"] = round(loop.time()-phase_started, 3)
    phase_started = loop.time()
    contexts, packed = pack_sources(
        sorted(sources, key=lambda s: s["url"]),
        plan,
        profile,
        deadline=time.perf_counter() + min(pack_reserve, max(0, overall_deadline-loop.time())),
        pivoted_numbers=set(pivot_numbers),
        pivoted_articles=set(pivot_articles),
    )
    if rescued_contexts:
        merged_contexts: list = []
        used_tokens = 0
        for item_ctx in [*rescued_contexts, *contexts]:
            if item_ctx in merged_contexts or len(merged_contexts) >= profile.evidence_limit:
                continue
            item_tokens = len(item_ctx.split()) + 4
            if used_tokens + item_tokens > profile.context_tokens:
                continue
            merged_contexts.append(item_ctx)
            used_tokens += item_tokens
        contexts = merged_contexts
        packed["evidence_blocks"] = len(contexts)
    diagnostics.update(packed)
    diagnostics["phase_seconds"]["pack"] = round(loop.time()-phase_started, 3)
    diagnostics["urls_attempted"] = len(attempted)
    partial = bool(diagnostics["errors"] or diagnostics["topic_coverage"]["missing"] or packed["packing_deadline_exceeded"]
                   or any(s.get("truncated") or s.get("requires_ocr") for s in sources)
                   or (plan.current_required and packed["legal_effect_status"] != "supported"))
    state = (
        "corpus_rescued" if rescued_contexts and not sources else
        "partial" if contexts and partial else
        "ok" if contexts else
        "no_readable_source" if records else
        "search_error" if diagnostics["errors"] else
        "no_search_results"
    )
    return OfficialSupplementResult(state, contexts, diagnostics, time.perf_counter()-started)
