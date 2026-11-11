"""Bounded metadata lookup for curated primary-law titles in the selected corpus."""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Any

from app.ingestion.legal_text import EvidenceChunk, chunk_document
from app.services.source_quality import assess_source_quality
from app.services.legal_topic_terms import (
    contains_topic_phrase,
    extract_official_topic_phrases,
    fold_topic_text,
    local_rescue_terms,
    matches_legal_situation,
)


_MAX_TITLE_CANDIDATES = 10
_MAX_DOCUMENT_LOADS = 2
_MAX_EVIDENCE = 3
_MAX_CONTEXT_TOKENS = 720
_PRIMARY_RESCUE_TIMEOUT_SECONDS = 8.0
_DOCUMENT_ID = re.compile(r"\b\d+\s*/\s*(?:19|20)\d{2}\s*/\s*[a-z]{1,8}\d*\b")
_ARTICLE_REFERENCE = re.compile(r"\bdieu\s+(\d+)(?:\s*[-–]\s*(\d+))?")
_TOKEN = re.compile(r"[a-z0-9]+")


def _heading_phrase_overlap(query: str, text: str) -> int:
    """Favor a clause heading that names the action in the question."""
    folded_query = re.sub(
        r"\bhet(?=\s+thoi gian thu viec\b)",
        "ket thuc",
        fold_topic_text(query),
    )
    query_tokens = _TOKEN.findall(folded_query)
    heading_tokens = _TOKEN.findall(fold_topic_text(text))[:18]
    heading = " " + " ".join(heading_tokens) + " "
    for size in range(min(6, len(query_tokens)), 1, -1):
        if any(
            " " + " ".join(query_tokens[start : start + size]) + " " in heading
            for start in range(len(query_tokens) - size + 1)
        ):
            return size
    return 0


def _is_keyword_only_clause(text: str) -> bool:
    """Identify a bare list entry without a usable condition or rule."""
    payload = re.split(r"\b\d+\.\s*", text)[-1]
    return len(payload.split()) <= 3


def _trial_facets(query: str) -> tuple[str, ...]:
    """Allocate the bounded evidence slots to issues actually asked about."""
    if not contains_topic_phrase(query, "thử việc"):
        return ()
    folded = fold_topic_text(query)
    facets = []
    if re.search(r"\b(?:thoi gian|thoi han|bao lau|ngay|thang)\b", folded):
        facets.append("trial_duration")
    if re.search(r"\bluong\b", folded):
        facets.append("trial_wage")
    if re.search(r"\b(?:nghi|huy|cham dut|bao truoc)\b", folded):
        facets.append("trial_termination")
    return tuple(facets)


@dataclass(frozen=True)
class _LawTitle:
    title_base: str
    year: str
    topics: tuple[str, ...]
    document_number: str

    @property
    def exact_title(self) -> str:
        return f"{self.title_base} {self.year}"


@dataclass(frozen=True)
class PrimaryLawRescueResult:
    evidence: tuple[EvidenceChunk, ...]
    diagnostics: dict[str, Any]


_LABOR = _LawTitle(
    "Bộ luật Lao động",
    "2019",
    ("thử việc", "tiền lương", "mức lương", "lương", "chấm dứt hợp đồng", "hợp đồng lao động", "nghỉ phép năm"),
    "45/2019/QH14",
)
_CIVIL = _LawTitle("Bộ luật Dân sự", "2015", ("đặt cọc", "thuê nhà"), "91/2015/QH13")


def _planned_titles(query: str) -> tuple[_LawTitle, ...]:
    topics = set(extract_official_topic_phrases(query, limit=4))
    selected: list[_LawTitle] = []
    if topics.intersection(_LABOR.topics):
        selected.append(_LABOR)
    if "đặt cọc" in topics:
        selected.append(_CIVIL)
    return tuple(selected[:_MAX_DOCUMENT_LOADS])


def _is_explicitly_scoped(query: str, titles: tuple[_LawTitle, ...]) -> bool:
    """Reject a different named law; dates and article references remain usable."""
    folded = fold_topic_text(query)
    allowed_numbers = {_number_key(title.document_number) for title in titles}
    if any(_number_key(match.group()) not in allowed_numbers
           for match in _DOCUMENT_ID.finditer(folded)):
        return True
    for match in re.finditer(r"\b(?:bo )?luat\b", folded):
        if folded[:match.start()].endswith("phap "):
            continue
        remainder = folded[match.end():].strip()
        if re.match(
            r"(?:nay|hien hanh|hien nay|hien tai|viet nam|khac|co lien quan|quy dinh|ve|co|khong|nhu|thi|la|ap dung)\b|\d",
            remainder,
        ) or not remainder:
            continue
        named = folded[match.start():]
        target = next((title for title in titles
                       if re.match(re.escape(fold_topic_text(title.title_base)) + r"\b", named)), None)
        if target is None:
            return True
        tail = named[len(fold_topic_text(target.title_base)):].strip()
        year = re.match(
            r"(?:\(\s*)?(?:(?:duoc\s+)?ban hanh\s+(?:vao\s+)?)?(?:nam\s+)?((?:19|20)\d{2})\b",
            tail,
        )
        if year and year.group(1) != target.year:
            return True
    return False


def _number_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def _contains_topic_phrase(text: str, topic: str) -> bool:
    return contains_topic_phrase(text, topic)


def _field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _issuance_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _search_and_load(
    query: str,
    planned_titles: tuple[_LawTitle, ...],
    settings: Any,
    browser: Any | None,
    deadline: float,
) -> tuple[list[EvidenceChunk], dict[str, Any]]:
    from app.services.legal_browser import LegalBrowser

    diagnostics: dict[str, Any] = {
        "status": "no_evidence",
        "method": "curated_primary_law_title_metadata_v1",
        "provenance": "pinned_corpus_store",
        "legal_effect_asserted": False,
        "current_effect_status": "unverified",
        "title_searches": [],
        "candidates": 0,
        "corpus_documents_loaded": 0,
        "corpus_document_load_attempts": 0,
        "selected_chunk_count": 0,
    }
    if time.monotonic() >= deadline:
        diagnostics["status"] = "timeout"
        return [], diagnostics
    try:
        selected_browser = browser or LegalBrowser.from_settings(settings)
    except Exception as error:
        diagnostics.update(status="unavailable", error_type=type(error).__name__)
        return [], diagnostics

    loaded = 0
    chunks_with_scores: list[
        tuple[int, int, int, int, int, frozenset[str], EvidenceChunk]
    ] = []
    query_topics = extract_official_topic_phrases(query, limit=4)
    query_terms = set(local_rescue_terms(query, limit=12))
    rental_deposit = "đặt cọc" in query_topics and "thuê nhà" in query_topics
    handover = bool(re.search(r"\b(?:ban giao|tra lai|hoan tra)\b", fold_topic_text(query)))
    trial_facets = _trial_facets(query)
    requested_articles = [
        (int(first), int(last or first))
        for first, last in _ARTICLE_REFERENCE.findall(fold_topic_text(query))
    ]
    requested_clauses = set(re.findall(r"\bkhoan\s+(\d+)\b", fold_topic_text(query)))
    now = datetime.now(timezone.utc).date()

    for target_index, target in enumerate(planned_titles):
        item: dict[str, Any] = {
            "title_query": target.exact_title,
            "expected_title": target.exact_title,
            "status": "not_found",
        }
        diagnostics["title_searches"].append(item)
        if time.monotonic() >= deadline:
            diagnostics["status"] = "timeout"
            break
        try:
            results = list(selected_browser.search(
                target.exact_title,
                limit=_MAX_TITLE_CANDIDATES,
            ) or ())[:_MAX_TITLE_CANDIDATES]
        except Exception as error:
            item.update(status="search_error", error_type=type(error).__name__)
            diagnostics["status"] = "search_error"
            continue
        if time.monotonic() >= deadline:
            diagnostics["status"] = "timeout"
            break

        diagnostics["candidates"] += len(results)
        eligible: list[tuple[date, Any, int]] = []
        for result in results:
            title = str(_field(result, "title", "") or "").strip()
            if fold_topic_text(title) != fold_topic_text(target.exact_title):
                item["status"] = "title_mismatch"
                continue
            if fold_topic_text(_field(result, "legal_type", "")) != "luat":
                item["status"] = "legal_type_mismatch"
                continue
            issued = _issuance_date(_field(result, "issuance_date"))
            if issued is None:
                item["status"] = "invalid_issuance_date"
                continue
            if issued > now:
                item["status"] = "future_issuance_date"
                continue
            try:
                document_id = int(_field(result, "document_id"))
            except (TypeError, ValueError):
                item["status"] = "invalid_document_id"
                continue
            if document_id <= 0:
                item["status"] = "invalid_document_id"
                continue
            eligible.append((issued, result, document_id))

        if not eligible:
            continue
        # Issue date orders duplicates; it does not establish legal effect.
        eligible.sort(key=lambda candidate: (candidate[0], -candidate[2]), reverse=True)
        issued, selected, document_id = eligible[0]
        if loaded >= _MAX_DOCUMENT_LOADS or time.monotonic() >= deadline:
            diagnostics["status"] = "timeout" if time.monotonic() >= deadline else "load_limit"
            break
        loaded += 1
        diagnostics["corpus_document_load_attempts"] = loaded
        try:
            document = selected_browser.get_document(document_id)
        except Exception as error:
            item.update(status="load_error", error_type=type(error).__name__)
            diagnostics["status"] = "load_error"
            continue
        if document is None:
            item["status"] = "document_missing"
            diagnostics["status"] = "integrity_error"
            continue
        metadata = _field(document, "metadata")
        content = _field(document, "content")
        try:
            stored_id = int(_field(metadata, "document_id"))
        except (TypeError, ValueError):
            stored_id = -1
        metadata_title = str(_field(metadata, "title", "") or "").strip()
        metadata_number = _field(metadata, "document_number")
        hit_number = _field(selected, "document_number")
        metadata_date = _issuance_date(_field(metadata, "issuance_date"))
        if (
            stored_id != document_id
            or not _number_key(hit_number)
            or _number_key(metadata_number) != _number_key(hit_number)
            or fold_topic_text(metadata_title) != fold_topic_text(target.exact_title)
            or fold_topic_text(_field(metadata, "legal_type", "")) != "luat"
            or metadata_date != issued
            or metadata_date is None
            or metadata_date > now
            or not isinstance(content, str)
            or not content.strip()
        ):
            item["status"] = "metadata_integrity_error"
            diagnostics["status"] = "integrity_error"
            continue
        actual_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        stored_digest = str(_field(document, "content_sha256", "") or "").casefold()
        if not re.fullmatch(r"[0-9a-f]{64}", stored_digest) or actual_digest != stored_digest:
            item["status"] = "content_hash_mismatch"
            diagnostics["status"] = "integrity_error"
            continue

        if not assess_source_quality(content)["usable_as_evidence"]:
            item["status"] = "source_quality_rejected"
            diagnostics["status"] = "source_quality_rejected"
            continue

        target_topics = tuple(topic for topic in target.topics if topic in query_topics)
        max_tokens = min(
            _MAX_CONTEXT_TOKENS,
            max(1, int(getattr(settings, "LLM_CONTEXT_MAX_TOKENS", _MAX_CONTEXT_TOKENS))),
        )
        chunk_max = max(1, int(getattr(settings, "QUERY_CHUNK_MAX_TOKENS", 220)))
        overlap = max(0, int(getattr(settings, "QUERY_CHUNK_OVERLAP_TOKENS", 24)))
        preserve_unit_max_tokens = min(480, max(1, max_tokens - 80))
        chunks = chunk_document(
            metadata,
            content,
            preserve_unit_max_tokens=preserve_unit_max_tokens,
            preserve_article_max_tokens=(
                preserve_unit_max_tokens
                if not requested_clauses
                else None
            ),
            require_preamble=not bool(requested_articles),
            max_tokens=chunk_max,
            overlap_tokens=overlap,
        )
        group_counts = Counter((chunk.article, chunk.clause) for chunk in chunks)
        for position, chunk in enumerate(chunks):
            if requested_articles:
                article = _ARTICLE_REFERENCE.search(fold_topic_text(chunk.article or ""))
                if article is None or not any(
                    first <= int(article.group(1)) <= last for first, last in requested_articles
                ):
                    continue
            if requested_clauses and str(chunk.clause) not in requested_clauses:
                continue
            # Oversized structural units split into multiple windows are not complete clauses.
            if group_counts[(chunk.article, chunk.clause)] > 1:
                continue
            if (
                target == _LABOR
                and "thử việc" in query_topics
                and not _contains_topic_phrase(chunk.text, "thử việc")
            ):
                continue
            body = set(_TOKEN.findall(fold_topic_text(chunk.text)))
            supported = [
                topic
                for topic in target_topics
                if _contains_topic_phrase(chunk.text, topic)
                and matches_legal_situation(query, chunk.text)
            ]
            if target == _LABOR and trial_facets:
                folded_chunk = fold_topic_text(chunk.text)
                facet_patterns = {
                    "trial_duration": r"\bthoi gian thu viec\b",
                    "trial_wage": r"\btien luong thu viec\b",
                    "trial_termination": r"\b(?:khong can bao truoc|huy bo hop dong)\b",
                }
                supported.extend(facet for facet in trial_facets
                                 if re.search(facet_patterns[facet], folded_chunk))
            if target == _CIVIL and rental_deposit:
                folded_chunk = fold_topic_text(chunk.text)
                if (
                    "hop dong thue nha" in folded_chunk
                    and _contains_topic_phrase(chunk.text, "thuê nhà")
                    and "thuê nhà" not in supported
                ):
                    supported.append("thuê nhà")
                if (
                    handover
                    and re.search(r"^dieu\s+\d+\.\s+tra lai tai san thue\b", folded_chunk)
                    and "ben thue" in folded_chunk
                ):
                    supported.append("bàn giao")
            if not supported:
                continue
            overlap_score = len(query_terms.intersection(body))
            heading_score = _heading_phrase_overlap(query, chunk.text)
            keyword_only = int(_is_keyword_only_clause(chunk.text))
            verified = replace(chunk, source_content_sha256=actual_digest)
            chunks_with_scores.append(
                (-len(supported), keyword_only, -heading_score, -overlap_score,
                 target_index * 1000 + position, frozenset(supported), verified)
            )
        item.update(status="body_verified", document_loaded=True)
        diagnostics["corpus_documents_loaded"] += 1

    max_evidence = min(
        _MAX_EVIDENCE,
        max(0, int(getattr(settings, "FINAL_EVIDENCE_LIMIT", _MAX_EVIDENCE))),
    )
    max_tokens = min(
        _MAX_CONTEXT_TOKENS,
        max(0, int(getattr(settings, "LLM_CONTEXT_MAX_TOKENS", _MAX_CONTEXT_TOKENS))),
    )
    selected_chunks: list[EvidenceChunk] = []
    used_tokens = 0
    seen: set[tuple[int, str, str]] = set()
    substantive_topics: dict[int, set[str]] = {}
    for _topic_score, keyword_only, _heading_score, _query_score, _position, topics, chunk in chunks_with_scores:
        if not keyword_only:
            substantive_topics.setdefault(chunk.document_id, set()).update(topics)
    ranked_chunks = sorted(chunks_with_scores)
    priority_facets = ("đặt cọc", "thuê nhà", "bàn giao") if rental_deposit else trial_facets
    prioritized = []
    for facet in priority_facets:
        candidates = [item for item in ranked_chunks if facet in item[5]]
        if facet == "bàn giao" and not re.search(
            r"\b(?:cham|tre)\s+(?:tra|ban giao)\b", fold_topic_text(query)
        ):
            candidates.sort(
                key=lambda item: (
                    "cham tra" in fold_topic_text(item[6].text),
                    "tinh trang" not in fold_topic_text(item[6].text),
                )
            )
        match = candidates[0] if candidates else None
        if match is not None and match not in prioritized:
            prioritized.append(match)
    for _topic_score, keyword_only, _heading_score, _query_score, _position, topics, chunk in [
        *prioritized, *ranked_chunks
    ]:
        if keyword_only and topics <= substantive_topics.get(chunk.document_id, set()):
            continue
        identity = (chunk.document_id, chunk.citation, chunk.text)
        if identity in seen:
            continue
        context_cost = len(chunk.formatted_context().split())
        reference_cost = len(f"[Tài liệu tham khảo #{len(selected_chunks) + 1}]".split())
        if len(selected_chunks) >= max_evidence or used_tokens + context_cost + reference_cost > max_tokens:
            continue
        selected_chunks.append(chunk)
        seen.add(identity)
        used_tokens += context_cost + reference_cost
    diagnostics.update(
        status="evidence_selected" if selected_chunks else diagnostics["status"],
        selected_chunk_count=len(selected_chunks),
        selected_context_tokens=used_tokens,
    )
    return selected_chunks, diagnostics


async def rescue_primary_law_evidence(
    query: str,
    *,
    settings: Any,
    browser: Any | None = None,
) -> PrimaryLawRescueResult:
    """Search only curated law titles and verify source text from the selected store."""
    planned = _planned_titles(query)
    diagnostics: dict[str, Any] = {
        "status": "not_applicable",
        "method": "curated_primary_law_title_metadata_v1",
        "provenance": "pinned_corpus_store",
        "legal_effect_asserted": False,
        "current_effect_status": "unverified",
        "title_searches": [],
        "candidates": 0,
        "corpus_documents_loaded": 0,
        "corpus_document_load_attempts": 0,
        "selected_chunk_count": 0,
    }
    if getattr(settings, "USE_LEGACY_FREE_PIPELINE", None) is not False:
        diagnostics["status"] = "bypassed_legacy_lane"
        return PrimaryLawRescueResult((), diagnostics)
    if not planned:
        return PrimaryLawRescueResult((), diagnostics)
    planned = tuple(title for title in planned if not _is_explicitly_scoped(query, (title,)))
    if not planned:
        diagnostics["status"] = "bypassed_explicit_scope"
        return PrimaryLawRescueResult((), diagnostics)

    deadline = time.monotonic() + _PRIMARY_RESCUE_TIMEOUT_SECONDS
    task = asyncio.create_task(
        asyncio.to_thread(_search_and_load, query, planned, settings, browser, deadline)
    )
    try:
        done, _pending = await asyncio.wait(
            {task}, timeout=_PRIMARY_RESCUE_TIMEOUT_SECONDS
        )
    except asyncio.CancelledError:
        task.cancel()
        raise
    if task not in done:
        task.cancel()
        diagnostics["status"] = "timeout"
        return PrimaryLawRescueResult((), diagnostics)
    try:
        evidence, diagnostics = task.result()
    except Exception as error:
        diagnostics["status"] = "unavailable"
        diagnostics["error_type"] = type(error).__name__
        return PrimaryLawRescueResult((), diagnostics)
    return PrimaryLawRescueResult(tuple(evidence), diagnostics)


def prefer_primary_topic_contexts(
    query: str,
    corpus_contexts: list[str],
    primary_contexts: list[str],
    *,
    max_evidence: int = _MAX_EVIDENCE,
) -> list[str]:
    """Replace same-topic corpus passages with verified primary-law passages."""
    if not primary_contexts:
        return list(corpus_contexts)
    from app.services.chat_official_supplement import (
        _topic_evidence_body,
        topic_supporting_contexts,
    )

    topics = extract_official_topic_phrases(query, limit=4)

    def supported(context: str) -> set[str]:
        body = _topic_evidence_body(context)
        return {
            topic
            for topic in topics
            if _contains_topic_phrase(body, topic)
            and matches_legal_situation(query, context)
        }

    primary_topics = set().union(*(supported(context) for context in primary_contexts))
    retained = [
        context
        for context in corpus_contexts
        if not (supported(context) and supported(context) <= primary_topics)
    ]
    distinct_topic_contexts = list(topic_supporting_contexts(query, retained))
    distinct_topics = set().union(
        *(supported(context) - primary_topics for context in distinct_topic_contexts)
    )
    selected_primary = list(primary_contexts[: max(0, max_evidence)])
    if distinct_topics and max_evidence > 1:
        distinct_slots = min(len(distinct_topic_contexts), max_evidence - 1)
        selected_primary = selected_primary[: max_evidence - distinct_slots]
        distinct_topic_contexts = distinct_topic_contexts[:distinct_slots]
    # Keep verified primary clauses first, but reserve capacity for recognized
    # topics that the primary source does not cover.
    return [*selected_primary, *distinct_topic_contexts]
