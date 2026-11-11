"""Bounded, source-read-only official evidence fallback for chat."""

from __future__ import annotations

import asyncio
from itertools import combinations
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.config import get_settings
from app.services.legal_topic_terms import (
    contains_topic_phrase,
    extract_official_topic_phrases,
    fold_topic_text,
    matches_legal_situation,
)


_MAX_QUERIES = 2
_MAX_URLS = 3
_MAX_SOURCES = 2
_MAX_EXCERPT_TOKENS = 220
_MAX_CONTEXT_TOKENS = 720
_SHA256 = re.compile(r"[0-9a-f]{64}", re.IGNORECASE)
_SAFE_METHOD = re.compile(r"[a-zA-Z0-9_-]{1,80}")
_PDF_METHODS = frozenset({"pdf_text", "vertex_ocr"})
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_LEGAL_TITLE_PREFIX = re.compile(
    r"^(?:bo luat|luat|phap lenh|nghi dinh|thong tu|quyet dinh|nghi quyet|hien phap)\b"
)
_TEMPORAL_CUES = (
    ("hien hanh", "hiện hành"),
    ("hien nay", "hiện nay"),
    ("hien tai", "hiện tại"),
    ("moi nhat", "mới nhất"),
    ("cap nhat", "cập nhật"),
    ("sua doi", "sửa đổi"),
    ("bo sung", "bổ sung"),
    ("dieu chinh", "điều chỉnh"),
    ("thay doi", "thay đổi"),
    ("con hieu luc", "còn hiệu lực"),
    ("con ap dung", "còn áp dụng"),
    ("dang ap dung", "đang áp dụng"),
    ("het hieu luc", "hết hiệu lực"),
    ("co hieu luc", "có hiệu lực"),
    ("van ap dung", "vẫn áp dụng"),
)
_LEGAL_YEAR_REFERENCE = re.compile(
    r"(?<![a-z0-9])(?:sua doi|bo sung|ban hanh|co hieu luc|hieu luc|ap dung)"
    r"(?:\s+nam)?\s+(?P<year>(?:19|20)\d{2})(?![a-z0-9])"
)
_APPLICABILITY_CUES = (
    "co can",
    "can phai",
    "co phai",
    "phai xin",
    "phai dang ky",
    "phai thuc hien",
    "co bat buoc",
    "bat buoc",
    "co duoc phep",
    "duoc phep",
    "co bi cam",
    "duoc mien",
)
_TOPIC_QUESTION_CUES = (
    "the nao",
    "ra sao",
    "la gi",
    "co dung khong",
    "duoc khong",
    "co duoc",
    "co can",
    "co phai",
    "co bat buoc",
)


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9]+", fold_topic_text(value)))


def _temporal_query_terms(query: str) -> tuple[str, ...]:
    folded = fold_topic_text(query)
    # A deadline measured from commencement does not ask whether the law is current.
    folded = re.sub(
        r"\bke tu ngay (?:bo luat|luat|nghi dinh|thong tu) nay co hieu luc\b",
        "", folded,
    )
    matches = [
        (match.start(), display)
        for normalized, display in _TEMPORAL_CUES
        if (match := re.search(rf"(?<![a-z0-9]){normalized}(?![a-z0-9])", folded))
    ]
    matches.extend(
        (match.start("year"), match.group("year"))
        for match in _LEGAL_YEAR_REFERENCE.finditer(folded)
    )
    if not matches:
        return ()
    return tuple(
        dict.fromkeys(value for _, value in sorted(matches, key=lambda item: item[0]))
    )


def _current_applicability_intent(query: str) -> bool:
    if _temporal_query_terms(query):
        return True
    if not extract_official_topic_phrases(query):
        return False
    folded = fold_topic_text(query)
    return any(
        re.search(rf"(?<![a-z0-9]){cue}(?![a-z0-9])", folded)
        for cue in _APPLICABILITY_CUES
    )


def _is_explicit_topic_question(clause: str) -> bool:
    folded = fold_topic_text(clause)
    return "?" in clause or any(
        re.search(rf"(?<![a-z0-9]){cue}(?![a-z0-9])", folded)
        for cue in _TOPIC_QUESTION_CUES
    )


def _corpus_law_title(contexts: list[str]) -> str | None:
    for context in contexts[:4]:
        lines = str(context).replace("\r", "\n").splitlines()
        if (
            len(lines) < 3
            or not lines[0].strip().startswith("[")
            or not lines[1].strip().casefold().startswith("nguồn:")
            or not lines[2].strip().casefold().startswith("tiêu đề:")
        ):
            continue
        title = " ".join(lines[2].split(":", 1)[1].split())[:100]
        if _LEGAL_TITLE_PREFIX.match(fold_topic_text(title)):
            return re.sub(r"\s+(?:năm\s+)?(?:19|20)\d{2}$", "", title, flags=re.IGNORECASE)
    return None


def _corpus_law_year(contexts: list[str]) -> int | None:
    for context in contexts[:4]:
        lines = str(context).replace("\r", "\n").splitlines()
        if (
            len(lines) < 3
            or not lines[0].strip().startswith("[")
            or not lines[1].strip().casefold().startswith("nguồn:")
            or not lines[2].strip().casefold().startswith("tiêu đề:")
            or not _LEGAL_TITLE_PREFIX.match(
                fold_topic_text(lines[2].split(":", 1)[1].strip())
            )
        ):
            continue
        match = _YEAR.search(lines[0])
        return int(match.group()) if match else None
    return None


def _evidence_body(context: str) -> str:
    lines = str(context).replace("\r", "\n").splitlines()
    if (
        len(lines) >= 3
        and lines[0].strip().startswith("[")
        and lines[1].strip().casefold().startswith("nguồn:")
        and lines[2].strip().casefold().startswith("tiêu đề:")
    ):
        return "\n".join(lines[3:])
    return context


def _topic_evidence_body(context: str) -> str:
    """Exclude typed official-source metadata while retaining corpus body parsing."""
    from app.services.evidence_presenter import (
        TrustedOfficialEvidenceContext,
        present_context,
    )

    if isinstance(context, TrustedOfficialEvidenceContext):
        return present_context(context).excerpt
    return _evidence_body(context)


@dataclass(frozen=True)
class OfficialSupplementResult:
    status: str
    contexts: list[str]
    diagnostics: dict[str, Any]
    latency_seconds: float


def derive_official_search_queries(
    query: str,
    *,
    corpus_contexts: list[str] | None = None,
) -> tuple[str, ...]:
    """Build short search queries only from recognized legal topic phrases."""
    temporal_terms = _temporal_query_terms(query)
    clauses = [
        clause.strip()
        for clause in re.split(r"(?<=[;,.!?\n])", query)[:8]
        if clause.strip()
    ]
    temporal_clauses = [
        clause
        for clause in clauses
        if _temporal_query_terms(clause)
    ]
    if temporal_clauses:
        # A generic current-rule question can refer back to the subject in
        # the immediately preceding sentence. Forward only curated topics.
        carried_subjects = {
            index - 1
            for index, clause in enumerate(clauses)
            if index > 0
            and _temporal_query_terms(clause)
            and re.match(
                r"^(?:theo (?:quy dinh|phap luat) )?hien nay\b",
                fold_topic_text(clause),
            )
        }
        relevant_clauses = [
            clause
            for index, clause in enumerate(clauses)
            if _temporal_query_terms(clause)
            or (
                (index in carried_subjects or _is_explicit_topic_question(clause))
                and extract_official_topic_phrases(clause, limit=4)
            )
        ]
        phrases = tuple(
            dict.fromkeys(
                phrase
                for clause in relevant_clauses
                for phrase in extract_official_topic_phrases(clause, limit=4)
            )
        )
        topic_queries = (
            (" ".join((*phrases, *temporal_terms))[:120],)
            if carried_subjects and phrases
            else tuple(
                " ".join((*phrases[index : index + 2], *temporal_terms))[:120]
                for index in range(0, len(phrases), 2)
            )[:_MAX_QUERIES]
        )
    else:
        phrases = extract_official_topic_phrases(query, limit=4)
        topic_queries = tuple(
            " ".join(phrases[index : index + 2])[:120]
            for index in range(0, len(phrases), 2)
        )[:_MAX_QUERIES]
    law_title = (
        _corpus_law_title(corpus_contexts or [])
        if _current_applicability_intent(query)
        else None
    )
    if law_title:
        title_terms = temporal_terms or ("sửa đổi",)
        title_query = " ".join((*title_terms, law_title))[:120]
        return ((topic_queries[0], title_query) if topic_queries else (title_query,))
    if not topic_queries:
        from app.services.official_search_plan import build_official_search_plan
        return build_official_search_plan(query).queries[:_MAX_QUERIES]
    return topic_queries


def evidence_covers_recognized_topics(query: str, contexts: list[str]) -> bool:
    """Require each recognized topic in an evidence body, excluding metadata."""
    from app.services.evidence_presenter import present_context

    topics = extract_official_topic_phrases(query, limit=4)
    if not topics:
        return False
    bodies = [
        present_context(context).excerpt
        for context in contexts
        if matches_legal_situation(query, context)
    ]
    return all(
        any(contains_topic_phrase(body, topic) for body in bodies)
        for topic in topics
    )


def topic_coverage_diagnostics(query: str, contexts: list[str]) -> dict[str, Any]:
    """Describe recognized topic coverage without retaining user narrative."""
    topics = extract_official_topic_phrases(query, limit=4)
    if not topics:
        return {
            "status": "unknown",
            "recognized_topics": [],
            "missing_topics": None,
        }

    eligible_bodies = [
        _topic_evidence_body(context)
        for context in contexts
        if matches_legal_situation(query, context)
    ]
    missing = [
        topic
        for topic in topics
        if not any(contains_topic_phrase(body, topic) for body in eligible_bodies)
    ]
    current_source_required = _current_applicability_intent(query)
    return {
        "status": "covered"
        if not missing and not current_source_required
        else "missing",
        "recognized_topics": list(topics),
        "missing_topics": missing,
        "current_source_required": current_source_required,
        "situation_rejected_contexts": len(contexts) - len(eligible_bodies),
    }


def topic_supporting_contexts(query: str, contexts: list[str]) -> tuple[str, ...]:
    """Keep a compact ranked set covering as many recognized topics as possible."""
    topics = extract_official_topic_phrases(query, limit=4)
    if not topics:
        return ()

    evidence: list[tuple[int, str, set[str]]] = []
    candidates_by_topic: dict[str, list[tuple[int, str, set[str]]]] = {
        topic: [] for topic in topics
    }
    for index, context in enumerate(contexts):
        if not matches_legal_situation(query, context):
            continue
        body = _topic_evidence_body(context)
        supported = {
            topic for topic in topics if contains_topic_phrase(body, topic)
        }
        if supported:
            item = (index, context, supported)
            evidence.append(item)
            for topic in supported:
                candidates_by_topic[topic].append(item)

    # Bound combinations to the four shortest ranked candidates per topic.
    candidate_indices = {
        item[0]
        for matches in candidates_by_topic.values()
        for item in sorted(matches, key=lambda item: (len(item[1].split()), item[0]))[:4]
    }
    candidates = [item for item in evidence if item[0] in candidate_indices]
    best: tuple[tuple[int, int, tuple[int, ...]], tuple[str, ...]] | None = None
    for count in range(1, min(len(topics), len(candidates)) + 1):
        for selection in combinations(candidates, count):
            covered = set().union(*(item[2] for item in selection))
            ranked_indices = tuple(item[0] for item in selection)
            reference_tokens = sum(
                len(f"[Tài liệu tham khảo #{index}]".split())
                for index in range(1, count + 1)
            )
            total_tokens = sum(len(item[1].split()) for item in selection) + reference_tokens
            key = (-len(covered), total_tokens, ranked_indices)
            selected_contexts = tuple(item[1] for item in selection)
            if best is None or key < best[0]:
                best = (key, selected_contexts)
    return best[1] if best is not None else ()


def corpus_evidence_covers_topic(query: str, contexts: list[str]) -> bool:
    """Require all words of one sanitized topic query in corpus evidence."""
    if _current_applicability_intent(query):
        return False
    topics = derive_official_search_queries(query, corpus_contexts=contexts)
    if not topics:
        return False
    evidence = [
        _topic_evidence_body(context)
        for context in contexts
        if matches_legal_situation(query, context)
    ]
    if not evidence:
        return False
    topic_groups = tuple(
        extract_official_topic_phrases(topic, limit=4) for topic in topics
    )
    if all(bool(group) for group in topic_groups):
        return all(
            any(
                all(contains_topic_phrase(body, phrase) for phrase in group)
                for body in evidence
            )
            for group in topic_groups
        )
    from app.services.legal_topic_terms import local_rescue_terms
    from app.services.official_search_plan import DOCUMENT_REFERENCE

    ref_match = DOCUMENT_REFERENCE.search(query)
    if ref_match:
        ref_key = re.sub(r"\s+", "", ref_match.group()).upper()
        if any(ref_key in re.sub(r"\s+", "", str(ctx)).upper() for ctx in contexts):
            return True
    subject_terms = local_rescue_terms(topics[0], limit=8)
    if not subject_terms:
        return False
    required = max(1, min(2, len(subject_terms)))
    return any(
        len(set(subject_terms) & set(_tokens(body))) >= required
        for body in evidence
    )


def _relevant_excerpt(text: str, query: str) -> str | None:
    if not matches_legal_situation(query, text):
        return None
    phrases = extract_official_topic_phrases(query, limit=4)
    phrase_terms = tuple(tuple(dict.fromkeys(_tokens(phrase))) for phrase in phrases)
    if not phrase_terms:
        temporal = set(_tokens(" ".join(_temporal_query_terms(query))))
        terms = tuple(term for term in _tokens(query) if term not in temporal)
        phrase_terms = (terms,) if terms else ()
    if not phrase_terms:
        return None

    def supports_topic(text: str) -> bool:
        if phrases:
            return any(contains_topic_phrase(text, phrase) for phrase in phrases)
        folded = set(_tokens(text))
        return any(all(term in folded for term in terms) for terms in phrase_terms)

    words = text.split()
    from app.ingestion.legal_text import ARTICLE_RE, DocumentMetadata, chunk_document

    if any(ARTICLE_RE.match(line) for line in text.splitlines()):
        metadata = DocumentMetadata(0, "", "", "", "", "", "", None)
        # Read complete structural units; this never changes index chunking.
        units = chunk_document(metadata, text, max_tokens=max(1, len(words)), overlap_tokens=0)
        for unit in units:
            if unit.token_count > 480 or not matches_legal_situation(query, unit.text):
                continue
            if supports_topic(unit.text):
                return unit.text
        return None
    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", text.strip())
        if paragraph.strip()
    ]
    for paragraph in paragraphs:
        paragraph_words = paragraph.split()
        if len(paragraph_words) > _MAX_EXCERPT_TOKENS:
            continue
        excerpt = " ".join(paragraph_words)
        if not matches_legal_situation(query, excerpt):
            continue
        if supports_topic(excerpt):
            return excerpt
    return None


def _source_context(source_url: str, source: dict[str, Any], query: str, *, excerpt_override: str | None = None) -> str | None:
    try:
        from app.services.trusted_source_reader import validate_source_url

        source_url = validate_source_url(source_url)
    except (ImportError, TypeError, ValueError):
        return None
    text = source.get("text")
    if (
        not isinstance(text, str)
        or not text.strip()
        or source.get("content_status") == "metadata_only"
    ):
        return None
    if not matches_legal_situation(query, str(source.get("title") or "") + "\n" + text):
        return None
    excerpt = excerpt_override if excerpt_override is not None else _relevant_excerpt(text, query)
    digest = source.get("sha256")
    retrieved_at = source.get("retrieved_at")
    method = source.get("method")
    if (
        not excerpt
        or not isinstance(digest, str)
        or not _SHA256.fullmatch(digest)
        or not isinstance(retrieved_at, str)
        or len(retrieved_at) > 64
        or not isinstance(method, str)
        or not _SAFE_METHOD.fullmatch(method)
    ):
        return None
    try:
        datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    except ValueError:
        return None

    document_sha256 = source.get("document_sha256")
    is_pdf = method in _PDF_METHODS or (method != "visible_html_text" and document_sha256 is not None)
    attachment_url = source.get("attachment_url")
    if is_pdf:
        if not isinstance(attachment_url, str):
            return None
        try:
            from app.services.trusted_source_reader import validate_source_url

            attachment_url = validate_source_url(attachment_url)
        except (ImportError, TypeError, ValueError):
            return None
    page_start = source.get("page_start")
    page_end = source.get("page_end")
    page_count = source.get("page_count")
    truncated = source.get("truncated")
    if is_pdf and (
        not isinstance(document_sha256, str)
        or not _SHA256.fullmatch(document_sha256)
        or any(
            not isinstance(page, int) or isinstance(page, bool)
            for page in (page_start, page_end, page_count)
        )
        or not 1 <= page_start <= page_end <= page_count <= 200
        or not isinstance(truncated, bool)
        or truncated != (page_start > 1 or page_end < page_count)
    ):
        return None

    title = " ".join(str(source.get("title") or "Văn bản chính thức").split())[:300]
    number = " ".join(str(source.get("document_number") or "").split())[:100]
    label = number or title
    from app.services.evidence_presenter import TrustedOfficialEvidenceContext

    digest_label = "SHA-256 nội dung trích xuất" if is_pdf else "SHA-256 nguồn"
    pdf_provenance = (
        f"SHA-256 tệp PDF: {document_sha256.lower()}\n"
        f"Phạm vi trang PDF: {page_start}-{page_end}/{page_count}\n"
        f"Đọc một phần PDF: {'có' if truncated else 'không'}\n"
        if is_pdf
        else ""
    )
    attachment_provenance = (
        f"Tệp PDF: {attachment_url}\n" if is_pdf else ""
    )
    article_provenance = (
        f"Dẫn chiếu: {label}, {' '.join(excerpt.splitlines()[0].split())[:200]}\n"
        f"Cơ quan ban hành: {' '.join(str(source.get('issuing_authority') or 'không xác định').split())[:200]}\n"
        if excerpt_override is not None else ""
    )
    return TrustedOfficialEvidenceContext(
        f"[Nguồn chính thức ngoài VietLex · {label}]\n"
        f"Nguồn: {source_url}\n"
        "Nguồn loại: official_external\n"
        "Hiệu lực pháp lý: unverified\n"
        f"{digest_label}: {digest.lower()}\n"
        f"{pdf_provenance}"
        f"{attachment_provenance}"
        f"Thời điểm đọc: {retrieved_at}\n"
        f"Phương thức đọc: {method}\n"
        f"{article_provenance}"
        f"Tiêu đề: {title}\n"
        f"{excerpt}"
    )


def _record_year(record: Any) -> int:
    for value in (
        getattr(record, "issued_date", None),
        getattr(record, "document_number", None),
        getattr(record, "title", None),
    ):
        if isinstance(value, str) and (match := _YEAR.search(value)):
            return int(match.group())
    return 0


def _record_document_number(record: Any) -> str:
    value = (
        record.get("document_number")
        if isinstance(record, Mapping)
        else getattr(record, "document_number", None)
    )
    return value.strip() if isinstance(value, str) else ""


def _search_record_rank(record: Any, query: str) -> tuple[int, int, int]:
    query_terms = set(_tokens(query))
    record_terms = set(
        _tokens(
            " ".join(
                str(getattr(record, field, "") or "")
                for field in ("title", "snippet", "document_number")
            )
        )
    )
    year = _record_year(record)
    requested_year = next(
        (int(term) for term in _temporal_query_terms(query) if term.isdecimal()),
        None,
    )
    year_match = int(requested_year is not None and year >= requested_year)
    return len(query_terms & record_terms), year_match, year


async def _default_provider(settings):
    from app.services.congbao_search import CongBaoClient
    from app.services.federated_official_search import FederatedOfficialClient
    from app.services.official_web_search import OfficialPortalClient

    # Only the two public government discovery endpoints are used. Brave is
    # deliberately excluded so this path needs no key and incurs no search fee.
    return FederatedOfficialClient(
        portal=OfficialPortalClient(settings=settings),
        gazette=CongBaoClient(settings=settings),
        provider_timeouts={"chinhphu": 1.75, "congbao": 3.5},
    )


async def supplement_official_evidence(
    query: str,
    *,
    settings=None,
    provider=None,
    reader=None,
    browser=None,
    corpus_contexts: list[str] | None = None,
) -> OfficialSupplementResult:
    started = time.perf_counter()
    settings = settings or get_settings()
    base_diagnostics: dict[str, Any] = {
        "search_queries": 0,
        "urls_discovered": 0,
        "sources_read": 0,
        "read_failures": 0,
        "newer_source_required": False,
    }
    if not getattr(settings, "CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED", False):
        return OfficialSupplementResult("disabled", [], {**base_diagnostics, "status": "disabled"}, 0.0)
    if not getattr(settings, "OFFICIAL_WEB_RESEARCH_ENABLED", False):
        return OfficialSupplementResult("disabled", [], {**base_diagnostics, "status": "official_research_disabled"}, 0.0)
    if (getattr(settings, "CHAT_OFFICIAL_DEEP_READING_ENABLED", False)
            and not getattr(settings, "USE_LEGACY_FREE_PIPELINE", False)):
        from app.services.deep_official_search import search_and_read
        return await search_and_read(query, settings=settings,
                                     providers=[provider] if provider is not None else None, reader=reader)
    corpus_contexts = corpus_contexts or []
    topic_coverage = topic_coverage_diagnostics(query, corpus_contexts)
    queries = derive_official_search_queries(
        query,
        corpus_contexts=corpus_contexts,
    )
    if not queries:
        return OfficialSupplementResult(
            "no_topics",
            [],
            {
                **base_diagnostics,
                "status": "no_topics",
                "topic_coverage": topic_coverage,
                "search_attempted": False,
            },
            0.0,
        )

    timeout = min(
        8.0,
        max(0.1, float(getattr(settings, "CHAT_OFFICIAL_WEB_SUPPLEMENT_TIMEOUT_SECONDS", 8.0))),
    )
    try:
        if provider is None:
            provider = await _default_provider(settings)
        if reader is None:
            from app.services.trusted_source_reader import read_source

            reader = read_source
    except Exception as error:
        diagnostics = {
            **base_diagnostics,
            "status": "unavailable",
            "error_type": type(error).__name__,
        }
        return OfficialSupplementResult("unavailable", [], diagnostics, time.perf_counter() - started)

    newer_source_required = False

    async def discover_and_read() -> tuple[list[str], dict[str, Any]]:
        nonlocal newer_source_required
        search_results = await asyncio.gather(
            *(provider.search(topic, limit=3) for topic in queries),
            return_exceptions=True,
        )
        candidate_records: dict[str, tuple[Any, str]] = {}
        search_errors = 0
        response_errors = 0
        for query_index, result in enumerate(search_results):
            if isinstance(result, BaseException):
                search_errors += 1
                continue
            response_errors += len(getattr(result, "errors", ()))
            for record in getattr(result, "results", ()):
                url = getattr(record, "url", None)
                if not isinstance(url, str):
                    continue
                try:
                    from app.services.trusted_source_reader import validate_source_url

                    approved_url = validate_source_url(url)
                except (ImportError, ValueError):
                    continue
                previous = candidate_records.get(approved_url)
                if previous is None or _search_record_rank(
                    record, queries[query_index]
                ) > _search_record_rank(previous[0], previous[1]):
                    candidate_records[approved_url] = (record, queries[query_index])

        current_query = _current_applicability_intent(query)
        law_title = _corpus_law_title(corpus_contexts) if current_query else None
        corpus_year = _corpus_law_year(corpus_contexts) if law_title else None
        title_query = bool(law_title)
        temporal_tokens = set(_tokens(" ".join(_temporal_query_terms(query))))
        topic_queries = (
            queries[:-1]
            if title_query and len(queries) > 1
            else queries
            if not title_query
            else ()
        )
        topic_query_terms = tuple(
            set(_tokens(topic_query)) - temporal_tokens
            for topic_query in topic_queries
        )
        law_subject = _LEGAL_TITLE_PREFIX.sub("", fold_topic_text(law_title or ""), count=1)
        law_title_terms = set(_tokens(law_subject)) - {"ve", "cua", "nam"}
        requested_topics = extract_official_topic_phrases(query, limit=4)

        def topical_and_title_match(record: Any, record_query: str) -> tuple[bool, bool]:
            record_terms = set(
                _tokens(
                    " ".join(
                        str(getattr(record, field, "") or "")
                        for field in ("title", "snippet", "document_number")
                    )
                )
            )
            topical_match = any(
                len(topic_terms) > 0
                and len(topic_terms & record_terms) >= min(2, len(topic_terms))
                for topic_terms in topic_query_terms
            )
            title_required = len(law_title_terms) // 2 + 1
            title_match = not law_title or bool(law_title_terms) and len(
                law_title_terms & record_terms
            ) >= title_required
            title_discovery = title_query and record_query == queries[-1] and title_match
            # An implementing rule can cover the requested subject without
            # repeating the base law's title. Require a whole recognized topic
            # in its title, rather than a loose token hit in a search snippet.
            subject_title_match = any(
                contains_topic_phrase(str(getattr(record, "title", "") or ""), topic)
                for topic in requested_topics
            )
            return topical_match or title_discovery, title_match or subject_title_match

        def record_rank(item):
            record, record_query = item[1]
            rank = _search_record_rank(record, record_query)
            if not current_query:
                return rank
            topical_match, title_match = topical_and_title_match(record, record_query)
            newer_than_corpus = int(
                corpus_year is not None and _record_year(record) > corpus_year
            )
            return (
                int(topical_match and title_match),
                newer_than_corpus,
                rank[1],
                rank[2],
                rank[0],
            )

        ranked_records = sorted(
            candidate_records.items(),
            key=record_rank,
            reverse=True,
        )
        if current_query:
            ranked_records = [
                item
                for item in ranked_records
                if all(topical_and_title_match(*item[1]))
            ]
            newer_records = (
                [
                    item
                    for item in ranked_records
                    if corpus_year is not None
                    and _record_year(item[1][0]) > corpus_year
                ]
                if law_title
                else []
            )
            if newer_records:
                newer_source_required = True
                ranked_records = newer_records
        ranked_records = ranked_records[:_MAX_URLS]
        candidate_urls = [
            (url, queries[0] if title_query else search_query)
            for url, (_record, search_query) in ranked_records
        ]

        rescue_diagnostics = None
        discovery_records = [
            record
            for _url, (record, _query) in ranked_records
            if _record_document_number(record)
        ]
        if discovery_records:
            try:
                def rescue_from_corpus():
                    active_browser = browser
                    if active_browser is None:
                        from app.services.legal_browser import LegalBrowser

                        active_browser = LegalBrowser.from_settings(settings)
                    from app.services.official_discovered_corpus_rescue import (
                        rescue_official_discoveries,
                    )

                    attempts = []
                    result = None
                    rescue_candidates = discovery_records[:_MAX_SOURCES]
                    for record in rescue_candidates:
                        result = rescue_official_discoveries(
                            query,
                            [record],
                            active_browser,
                            settings=settings,
                        )
                        attempts.append(result.diagnostics)
                        if result.evidence:
                            break
                    return result, attempts

                remaining = timeout - (time.perf_counter() - started)
                rescue_timeout = min(4.0, max(0.1, remaining * 0.6))
                try:
                    rescue_result, rescue_attempts = await asyncio.wait_for(
                        asyncio.to_thread(rescue_from_corpus),
                        timeout=rescue_timeout,
                    )
                except asyncio.TimeoutError:
                    rescue_diagnostics = {
                        "status": "timeout",
                        "error_type": "TimeoutError",
                    }
                else:
                    rescue_diagnostics = dict(rescue_result.diagnostics)
                    if len(rescue_attempts) > 1:
                        rescue_diagnostics["attempts"] = rescue_attempts
                    rescued_contexts = [
                        chunk.formatted_context() for chunk in rescue_result.evidence
                    ]
                    if rescued_contexts:
                        return rescued_contexts, {
                            "status": "corpus_rescued",
                            "search_queries": len(queries),
                            "search_errors": search_errors,
                            "partial_search_errors": response_errors,
                            "urls_discovered": len(candidate_urls),
                            "sources_read": 0,
                            "read_failures": 0,
                            "official_corpus_rescue": rescue_diagnostics,
                            "newer_source_required": newer_source_required,
                            "newer_source_status": "corpus_identity_verified_effect_unverified"
                            if newer_source_required
                            else None,
                            "provider": getattr(
                                provider, "provider", type(provider).__name__
                            ),
                        }
            except Exception as error:
                rescue_diagnostics = {
                    "status": "rescue_error",
                    "error_type": type(error).__name__,
                }

        async def read_one(url: str, topic: str):
            return await reader(url, use_ocr=False, page_limit=5), url, topic

        reads = await asyncio.gather(
            *(
                read_one(url, topic)
                for url, topic in candidate_urls[
                    :_MAX_SOURCES
                ]
            ),
            return_exceptions=True,
        )
        contexts: list[str] = []
        read_failures = 0
        for result in reads:
            if isinstance(result, BaseException):
                read_failures += 1
                continue
            source, url, topic = result
            context = _source_context(url, source, topic)
            if context is None:
                read_failures += 1
                continue
            token_count = len(context.split())
            if sum(len(item.split()) for item in contexts) + token_count > _MAX_CONTEXT_TOKENS:
                continue
            contexts.append(context)

        status = "ok" if contexts else (
            "no_readable_source"
            if candidate_urls
            else "search_error"
            if search_errors == len(search_results)
            else "no_search_results"
        )
        return contexts, {
            "status": status,
            "search_queries": len(queries),
            "search_errors": search_errors,
            "partial_search_errors": response_errors,
            "urls_discovered": len(candidate_urls),
            "sources_read": len(contexts),
            "read_failures": read_failures,
            "newer_source_required": newer_source_required,
            "newer_source_status": (
                ("readable" if contexts else "unavailable")
                if newer_source_required
                else None
            ),
            **(
                {"official_corpus_rescue": rescue_diagnostics}
                if rescue_diagnostics is not None
                else {}
            ),
            "provider": getattr(provider, "provider", type(provider).__name__),
        }

    try:
        contexts, diagnostics = await asyncio.wait_for(
            discover_and_read(), timeout=timeout
        )
        status = diagnostics["status"]
    except asyncio.TimeoutError:
        contexts = []
        diagnostics = {
            **base_diagnostics,
            "status": "timeout",
            "error_type": "TimeoutError",
            "newer_source_required": newer_source_required,
            "newer_source_status": (
                "unavailable" if newer_source_required else None
            ),
        }
        status = "timeout"
    except Exception as error:
        contexts = []
        diagnostics = {
            **base_diagnostics,
            "status": "search_error",
            "error_type": type(error).__name__,
        }
        status = "search_error"
    return OfficialSupplementResult(
        status,
        contexts,
        diagnostics,
        time.perf_counter() - started,
    )
