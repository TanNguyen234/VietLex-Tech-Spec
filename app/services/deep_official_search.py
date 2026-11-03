"""Ephemeral official-source search. No corpus, storage, OCR or model clients."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import re
import time

from app.services.legal_topic_terms import contains_topic_phrase, fold_topic_text, local_rescue_terms
from app.services.official_search_plan import DEEP_READING, DOCUMENT_REFERENCE, build_official_search_plan
from app.services.trusted_source_reader import SourceReadError, is_official_document_url, validate_source_url

_NETWORK = asyncio.Semaphore(2)
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


def pack_sources(sources, plan, profile=DEEP_READING, *, deadline=None):
    """Select intact articles by facet coverage, retaining exact text and provenance."""
    from app.services.chat_official_supplement import _source_context
    from app.services.evidence_presenter import EphemeralOfficialEvidenceContext
    excluded, validated_sources = [], []
    deadline_exceeded = False
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
        text = item.get("text", "")
        identity = (item.get("document_number"), item.get("issuing_authority", ""),
                    item["sha256"])
        verified_versions.setdefault(identity, []).append(item)
        if identity in seen:
            excluded.append({"source": source_index, "reason": "duplicate_source"})
            continue
        seen.add(identity)
        tail = _TAIL.search(text)
        article_text = text[:tail.start()] if tail else text
        headings = list(_ARTICLE.finditer(article_text))
        for index, match in enumerate(headings):
            if deadline is not None and time.perf_counter() >= deadline:
                deadline_exceeded = True
                break
            label = match.group().strip()
            if index == len(headings) - 1 and (item.get("truncated") or item.get("requires_ocr")):
                excluded.append({"source": source_index, "article": label, "reason": "incomplete_article"})
                continue
            end = headings[index + 1].start() if index + 1 < len(headings) else len(article_text)
            excerpt = article_text[match.start():end].strip()
            if "\ufffd" in excerpt:
                excluded.append({"source": source_index, "article": label, "reason": "unreliable_text_encoding"})
                continue
            if "trach nhiem thi hanh" in fold_topic_text(label) and "thi hanh" not in fold_topic_text(plan.original_question):
                continue
            covered = {topic for topic in plan.topics if contains_topic_phrase(excerpt, topic)}
            overlap = len(terms.intersection(local_rescue_terms(excerpt, limit=256)))
            actual_number = item.get("document_number") or (
                DOCUMENT_REFERENCE.search(str(item.get("title", ""))).group()
                if DOCUMENT_REFERENCE.search(str(item.get("title", ""))) else "")
            explicit_document = bool(plan.reference and actual_number.upper().replace("Ð", "Đ") == plan.reference.replace("Ð", "Đ"))
            numeric_heading = re.match(r'(?:Điều|Dieu)\s+(\d+)[.:]', label, re.I)
            requested_article = bool(numeric_heading) and (not plan.reference or explicit_document) and any(
                first <= int(numeric_heading.group(1)) <= last for first, last in requested_articles
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


async def search_and_read(question, *, settings=None, providers=None, reader=None, profile=DEEP_READING):
    from app.services.chat_official_supplement import OfficialSupplementResult
    from app.services.trusted_source_reader import read_source
    plan = build_official_search_plan(question)
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
        from app.services.vbpl_search import VbplClient
        providers = [OfficialPortalClient(settings=settings), CongBaoClient(settings=settings), VbplClient()]
    reader = reader or read_source
    records = {}
    started_queries, completed_queries = set(), set()
    async def discover(provider, query):
        name = type(provider).__name__
        try:
            async with _NETWORK:
                started_queries.add(query)
                diagnostics["search_queries"] = len(started_queries)
                diagnostics["provider_attempts"] += 1
                response = await provider.search(query, limit=8)
            completed_queries.add(query)
            diagnostics["queries_completed"] = len(completed_queries)
            for error in getattr(response, "errors", ()):
                diagnostics["errors"].append({"phase": "discovery", "provider": name, "kind": str(error)[:100]})
            for record in getattr(response, "results", ()):
                try:
                    url = validate_source_url(record.url)
                    if not is_official_document_url(url):
                        continue
                except (ValueError, AttributeError):
                    continue
                records[url] = record
        except asyncio.CancelledError:
            raise
        except Exception as error:
            diagnostics["errors"].append({"phase": "discovery", "provider": name,
                                          "kind": str(getattr(error, "kind", type(error).__name__))[:100]})
    phase_started = loop.time()
    tasks = [asyncio.create_task(discover(provider, query)) for query in plan.queries[:profile.query_limit] for provider in providers]
    try:
        _, pending = await asyncio.wait(tasks, timeout=max(0, min(profile.discovery_seconds, overall_deadline-loop.time())))
        if pending:
            diagnostics["errors"].append({"phase": "discovery", "kind": "deadline"})
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    diagnostics["phase_seconds"]["discovery"] = round(loop.time()-phase_started, 3)
    diagnostics["urls_discovered"] = len(records)
    diagnostics["discovered_urls"] = sorted(records)[:120]
    terms = set(local_rescue_terms(" ".join(plan.topics), limit=40))
    def rank(record):
        metadata = record.title + " " + getattr(record, "snippet", "")
        return (sum(contains_topic_phrase(metadata, t) for t in plan.topics),
                len(terms.intersection(local_rescue_terms(metadata, limit=128))))
    queue = [(u, r) for u, r in sorted(records.items(), key=lambda pair: (-rank(pair[1])[0], -_year(pair[1]), -rank(pair[1])[1], pair[0]))
             if not _organization_only(r.title, question)]
    sources, attempted, pending = [], set(), set()
    phase_started = loop.time()
    pack_reserve = min(5, profile.total_seconds / 12)
    cleanup_reserve = min(3, profile.read_seconds / 10)
    read_deadline = min(overall_deadline - pack_reserve - cleanup_reserve,
                        loop.time() + profile.read_seconds - cleanup_reserve)
    async def read_one(url, record):
        try:
            async with _NETWORK:
                item = await reader(url, question=plan.original_question, smart_pages=True, deep_read=True,
                                    use_ocr=False, page_limit=20)
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
    try:
        while loop.time() < read_deadline:
            while queue and len(pending) < 2 and len(attempted) < profile.source_limit:
                url, record = queue.pop(0)
                if url not in attempted:
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
    contexts, packed = pack_sources(sorted(sources, key=lambda s: s["url"]), plan, profile,
                                   deadline=time.perf_counter() + min(pack_reserve, max(0, overall_deadline-loop.time())))
    diagnostics.update(packed)
    diagnostics["phase_seconds"]["pack"] = round(loop.time()-phase_started, 3)
    diagnostics["urls_attempted"] = len(attempted)
    partial = bool(diagnostics["errors"] or diagnostics["topic_coverage"]["missing"] or packed["packing_deadline_exceeded"]
                   or any(s.get("truncated") or s.get("requires_ocr") for s in sources)
                   or (plan.current_required and packed["legal_effect_status"] != "supported"))
    state = "partial" if contexts and partial else "ok" if contexts else "no_readable_source" if records else "search_error" if diagnostics["errors"] else "no_search_results"
    return OfficialSupplementResult(state, contexts, diagnostics, time.perf_counter()-started)
