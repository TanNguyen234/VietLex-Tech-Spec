from __future__ import annotations

import asyncio
import hashlib
import re
import time
import unicodedata
from dataclasses import dataclass, replace
from typing import Any, Callable

import httpx

from app.config import system_ssl_context
from app.ingestion.content_store import ContentStore, StoredDocument
from app.ingestion.legal_text import EvidenceChunk, chunk_document
from app.services.legal_topic_terms import (
    extract_official_topic_phrases,
    fold_topic_text,
)
from app.services.retrieval import INTENT_PATTERNS, select_rerank_candidates


_ARTICLE_QUERY_RE = re.compile(r"\bdieu\s+(\d+[a-z]?)\b", re.IGNORECASE)
_CLAUSE_QUERY_RE = re.compile(r"\bkhoan\s+(\d+)\b", re.IGNORECASE)
_ARTICLE_NUMBER_RE = re.compile(r"\b(?:dieu\s*)?(\d+[a-z]?)\b", re.IGNORECASE)
_DURATION_EVIDENCE_RE = re.compile(
    r"(?<!\d)\d{1,4}(?:[.,]\d+)?\s*"
    r"(?:ngay(?:\s+lam\s+viec)?|tuan|thang|nam|gio|phut)\b",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"(?<!\d)\d+(?:[.,]\d+)?\s*%")
_SOURCE_DOCUMENT_LOAD_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class V3ArticleExpansion:
    status: str
    selected_evidence: list[EvidenceChunk]
    added_evidence: list[EvidenceChunk]
    diagnostics: dict[str, Any]
    latency_seconds: float


class SourceContentHashMismatch(ValueError):
    """Full-document content does not match its Qdrant/source hashes."""


class SourceContentHashMissing(ValueError):
    """A Qdrant candidate lacks the hash required for safe expansion."""


class SourceDocumentMissing(LookupError):
    """A candidate document is absent from its configured full-text source."""


class SourceDocumentLoadTimeout(TimeoutError):
    """The configured deadline elapsed while loading source documents."""


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    unmarked = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    return unmarked.replace("đ", "d")


def _article_number(value: str | None) -> str | None:
    if not value:
        return None
    match = _ARTICLE_NUMBER_RE.search(_fold(value))
    return match.group(1) if match else None


def _explicit_reference(query: str) -> tuple[str, str] | None:
    folded = _fold(query)
    article = _ARTICLE_QUERY_RE.search(folded)
    clause = _CLAUSE_QUERY_RE.search(folded)
    if not article or not clause:
        return None
    return article.group(1), clause.group(1)


def _asks_for_duration(query: str) -> bool:
    folded = _fold(query)
    query_hints = {
        _fold(hint)
        for hint in INTENT_PATTERNS["deadline"][0]
        if _fold(hint) not in {"ngay", "thang", "nam"}
    }
    return any(hint in folded for hint in query_hints)


def _has_numeric_duration(text: str) -> bool:
    return bool(_DURATION_EVIDENCE_RE.search(_fold(text)))


def _local_rescue_topic(query: str) -> tuple[str, ...] | None:
    phrases = extract_official_topic_phrases(query, limit=4)
    terms = tuple(
        dict.fromkeys(
            term
            for phrase in phrases
            for term in fold_topic_text(phrase).split()
        )
    )
    return terms or None


def _local_rescue_document_ids(
    topic_terms: tuple[str, ...],
    candidates: list[EvidenceChunk],
    *,
    max_documents: int,
    include_unmatched: bool = False,
) -> list[int]:
    scores: dict[int, int] = {}
    for candidate in candidates:
        folded = _fold(" ".join((candidate.title, candidate.text)))
        score = sum(term in folded for term in topic_terms)
        if score:
            document_id = int(candidate.document_id)
            scores[document_id] = max(scores.get(document_id, 0), score)
    order = {
        int(candidate.document_id): index
        for index, candidate in reversed(list(enumerate(candidates)))
    }
    ranked = [
        document_id
        for document_id, score in sorted(
            scores.items(), key=lambda item: (-item[1], order[item[0]])
        )[: max(0, max_documents)]
        if score > 0
    ]
    if include_unmatched and len(ranked) < max(0, max_documents):
        seen = set(ranked)
        for candidate in candidates:
            document_id = int(candidate.document_id)
            if document_id in seen:
                continue
            ranked.append(document_id)
            seen.add(document_id)
            if len(ranked) >= max(0, max_documents):
                break
    return ranked


def _choose_local_rescue_clause(
    query: str,
    topic_terms: tuple[str, ...],
    chunks_by_group: dict[tuple[int, str], list[EvidenceChunk]],
    group_order: list[tuple[int, str]],
    selected: list[EvidenceChunk],
    *,
    require_numeric_duration: bool = False,
    max_aggregate_tokens: int = 220,
) -> tuple[EvidenceChunk | None, dict[str, Any]]:
    candidates_by_score: list[tuple[int, EvidenceChunk]] = []
    percentage_question = bool(_PERCENT_RE.search(query))
    for group in group_order:
        for chunk in chunks_by_group.get(group, []):
            folded = _fold(chunk.text)
            coverage = sum(term in folded for term in topic_terms)
            if 2 * coverage > len(topic_terms) and (
                not require_numeric_duration or _has_numeric_duration(chunk.text)
            ):
                score = 2 * coverage + 3 * bool(
                    percentage_question and _PERCENT_RE.search(chunk.text)
                )
                candidates_by_score.append((score, chunk))
    if not candidates_by_score:
        diagnostics = (
            {
                "duration_group_complete": False,
                "duration_group_chunks_found": 0,
                "duration_group_chunks_omitted": 0,
            }
            if require_numeric_duration
            else {}
        )
        return None, diagnostics

    max_score = max(score for score, _chunk in candidates_by_score)
    candidates = [
        chunk
        for score, chunk in candidates_by_score
        if score == max_score
    ]

    ranked = select_rerank_candidates(
        query,
        candidates,
        limit=len(candidates),
        per_document_limit=max(1, len(candidates)),
    )
    incomplete_selection: tuple[EvidenceChunk, dict[str, Any]] | None = None
    for candidate in ranked:
        already_selected = any(
            int(item.document_id) == int(candidate.document_id)
            and item.citation == candidate.citation
            and item.text == candidate.text
            for item in selected
        )
        if require_numeric_duration:
            candidate_group = (
                int(candidate.document_id),
                _article_number(candidate.article) or "",
            )
            related_chunks = list(
                dict.fromkeys(
                    chunk
                    for _score, chunk in candidates_by_score
                    if (
                        int(chunk.document_id),
                        _article_number(chunk.article) or "",
                    )
                    == candidate_group
                )
            )
            if len(related_chunks) > 1:
                combined_text = "\n".join(chunk.text for chunk in related_chunks)
                combined_token_count = len(combined_text.split())
                complete = combined_token_count <= max_aggregate_tokens
                selection_diagnostics = {
                    "duration_group_complete": complete,
                    "duration_group_chunks_found": len(related_chunks),
                    "duration_group_chunks_omitted": (
                        0 if complete else len(related_chunks) - 1
                    ),
                }
                if complete:
                    article = candidate.article or ""
                    return (
                        replace(
                            candidate,
                            clause=None,
                            citation=f"{candidate.document_number}, {article}",
                            text=combined_text,
                            token_count=combined_token_count,
                        ),
                        selection_diagnostics,
                    )
                if not already_selected:
                    return candidate, selection_diagnostics
                if incomplete_selection is None:
                    incomplete_selection = (candidate, selection_diagnostics)
                continue
            if already_selected:
                continue
            return candidate, {
                "duration_group_complete": True,
                "duration_group_chunks_found": len(related_chunks),
                "duration_group_chunks_omitted": 0,
            }
        if already_selected:
            continue
        return candidate, {}
    if incomplete_selection is not None:
        return incomplete_selection
    return None, {}


def _load_source_documents(settings: Any, document_ids: list[int]) -> dict[int, StoredDocument]:
    from app.services.legal_browser import (
        SupabaseLegalStore,
        local_legal_paths,
        should_use_supabase_legal_store,
    )

    local_content_path, local_fts_path, _ = local_legal_paths(settings)
    if should_use_supabase_legal_store(
        settings,
        local_content_path=local_content_path,
        local_fts_path=local_fts_path,
    ):
        with httpx.Client(
            verify=system_ssl_context(),
            timeout=httpx.Timeout(10.0),
        ) as client:
            store = SupabaseLegalStore(
                url=settings.SUPABASE_URL,
                publishable_key=settings.SUPABASE_PUBLISHABLE_KEY,
                client=client,
            )
            return store.get_many(document_ids)
    return ContentStore(local_content_path).get_many(document_ids)


async def _load_source_documents_bounded(
    loader: Callable[[list[int]], dict[int, StoredDocument]],
    document_ids: list[int],
) -> dict[int, StoredDocument]:
    task = asyncio.create_task(asyncio.to_thread(loader, document_ids))
    try:
        done, _pending = await asyncio.wait(
            {task}, timeout=_SOURCE_DOCUMENT_LOAD_TIMEOUT_SECONDS
        )
    except asyncio.CancelledError:
        task.cancel()
        raise
    if task not in done:
        task.cancel()
        raise SourceDocumentLoadTimeout
    return task.result()


def _candidate_groups(
    candidates: list[EvidenceChunk],
    *,
    max_documents: int,
) -> tuple[list[int], list[tuple[int, str]]]:
    document_ids: list[int] = []
    groups: list[tuple[int, str]] = []
    seen_documents: set[int] = set()
    seen_groups: set[tuple[int, str]] = set()
    for candidate in candidates:
        article = _article_number(candidate.article)
        if article is None:
            continue
        document_id = int(candidate.document_id)
        if document_id not in seen_documents:
            if len(document_ids) >= max_documents:
                continue
            seen_documents.add(document_id)
            document_ids.append(document_id)
        if document_id not in seen_documents:
            continue
        group = (document_id, article)
        if group not in seen_groups:
            seen_groups.add(group)
            groups.append(group)
    return document_ids, groups


def _verify_document_hashes(
    document_ids: list[int],
    candidates: list[EvidenceChunk],
    documents: dict[int, StoredDocument],
) -> dict[int, str]:
    verified: dict[int, str] = {}
    for document_id in document_ids:
        document = documents.get(document_id)
        if document is None:
            raise SourceDocumentMissing("candidate document is absent from source")
        candidate_hashes = [
            candidate.source_content_sha256
            for candidate in candidates
            if int(candidate.document_id) == document_id
        ]
        if not candidate_hashes or any(
            not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest, re.IGNORECASE) is None
            for digest in candidate_hashes
        ):
            raise SourceContentHashMissing("candidate source hash is missing or inconsistent")
        expected = {digest.casefold() for digest in candidate_hashes}
        if len(expected) != 1:
            raise SourceContentHashMissing("candidate source hash is missing or inconsistent")
        actual = hashlib.sha256(document.content.encode("utf-8")).hexdigest()
        if actual != str(document.content_sha256).casefold() or actual not in expected:
            raise SourceContentHashMismatch("source content hashes disagree")
        verified[document_id] = actual
    return verified


def _choose_additional_evidence(
    query: str,
    selected: list[EvidenceChunk],
    expanded_by_group: dict[tuple[int, str], list[EvidenceChunk]],
    group_order: list[tuple[int, str]],
) -> EvidenceChunk | None:
    explicit = _explicit_reference(query)
    if explicit:
        article_number, clause_number = explicit
        for document_id, article_number_in_group in group_order:
            if article_number_in_group != article_number:
                continue
            for candidate in expanded_by_group.get(
                (document_id, article_number_in_group), []
            ):
                if candidate.clause == clause_number:
                    return candidate
        return None

    if not _asks_for_duration(query):
        return None

    selected_duration_groups = {
        (int(candidate.document_id), article_number)
        for candidate in selected
        if _has_numeric_duration(candidate.text)
        and (article_number := _article_number(candidate.article)) is not None
    }

    for group in group_order:
        if group in selected_duration_groups:
            continue
        group_chunks = expanded_by_group.get(group, [])
        if not group_chunks:
            continue
        ranked = select_rerank_candidates(
            query,
            group_chunks,
            limit=len(group_chunks),
            per_document_limit=max(1, len(group_chunks)),
        )
        duration_evidence = next(
            (chunk for chunk in ranked if _has_numeric_duration(chunk.text)),
            None,
        )
        if duration_evidence is not None:
            return duration_evidence
    return None


async def expand_v3_evidence(
    query: str,
    candidate_evidence: list[EvidenceChunk],
    selected_evidence: list[EvidenceChunk],
    *,
    settings: Any,
    max_documents: int,
    max_evidence: int | None = None,
    document_loader: Callable[[list[int]], dict[int, StoredDocument]] | None = None,
) -> V3ArticleExpansion:
    """Use hash-verified sibling clauses from articles already found by V3."""
    started = time.perf_counter()
    limit = max(0, int(max_evidence if max_evidence is not None else len(selected_evidence)))
    if limit == 0:
        return V3ArticleExpansion(
            status="not_needed",
            selected_evidence=list(selected_evidence),
            added_evidence=[],
            diagnostics={"status": "zero_evidence_limit"},
            latency_seconds=time.perf_counter() - started,
        )
    explicit = _explicit_reference(query)
    local_topic = _local_rescue_topic(query)
    duration_intent = _asks_for_duration(query)
    local_rescue = (
        local_topic is not None
        and explicit is None
    )
    if not explicit and not duration_intent and not local_rescue:
        return V3ArticleExpansion(
            status="not_needed",
            selected_evidence=list(selected_evidence),
            added_evidence=[],
            diagnostics={"status": "not_needed"},
            latency_seconds=time.perf_counter() - started,
        )

    expansion_candidates = candidate_evidence
    if explicit:
        expansion_candidates = [
            candidate
            for candidate in candidate_evidence
            if _article_number(candidate.article) == explicit[0]
        ]
        if not expansion_candidates:
            return V3ArticleExpansion(
                status="not_found",
                selected_evidence=list(selected_evidence),
                added_evidence=[],
                diagnostics={"status": "no_matching_candidate_article"},
                latency_seconds=time.perf_counter() - started,
            )

    if local_rescue and local_topic is not None:
        document_ids = _local_rescue_document_ids(
            local_topic,
            expansion_candidates,
            max_documents=max(0, int(max_documents)),
            include_unmatched=duration_intent,
        )
        _candidate_document_ids, candidate_group_order = _candidate_groups(
            expansion_candidates,
            max_documents=max(0, int(max_documents)),
        )
        loaded_document_ids = set(document_ids)
        group_order = [
            group
            for group in candidate_group_order
            if group[0] in loaded_document_ids
        ]
    else:
        document_ids, group_order = _candidate_groups(
            expansion_candidates,
            max_documents=max(0, int(max_documents)),
        )
    if not document_ids or (not group_order and not local_rescue):
        return V3ArticleExpansion(
            status="not_found",
            selected_evidence=list(selected_evidence),
            added_evidence=[],
            diagnostics={"status": "no_article_candidates"},
            latency_seconds=time.perf_counter() - started,
        )

    loader = document_loader or (
        lambda ids: _load_source_documents(settings, ids)
    )
    try:
        documents = await _load_source_documents_bounded(loader, document_ids)
        verified_hashes = _verify_document_hashes(
            document_ids,
            candidate_evidence,
            documents,
        )
    except Exception as error:
        error_type = type(error).__name__
        status = (
            "integrity_error"
            if isinstance(
                error,
                (
                    SourceContentHashMismatch,
                    SourceContentHashMissing,
                    SourceDocumentMissing,
                ),
            )
            else "unavailable"
        )
        return V3ArticleExpansion(
            status=status,
            selected_evidence=list(selected_evidence),
            added_evidence=[],
            diagnostics={
                "status": status,
                "error_type": error_type,
                "documents_requested": len(document_ids),
            },
            latency_seconds=time.perf_counter() - started,
        )

    from app.services.source_quality import assess_source_quality
    rejected_documents = {
        document_id for document_id in document_ids
        if not assess_source_quality(documents[document_id].content,
                                     source_sha256=documents[document_id].content_sha256)["usable_as_evidence"]
    }
    if rejected_documents:
        selected_evidence = [chunk for chunk in selected_evidence
                             if int(chunk.document_id) not in rejected_documents]
        document_ids = [value for value in document_ids if value not in rejected_documents]
        group_order = [group for group in group_order if group[0] not in rejected_documents]
        if not document_ids:
            return V3ArticleExpansion(
                status="not_found", selected_evidence=list(selected_evidence), added_evidence=[],
                diagnostics={"status": "source_quality_rejected", "rejected_document_count": len(rejected_documents)},
                latency_seconds=time.perf_counter() - started,
            )
    chunks_by_group: dict[tuple[int, str], list[EvidenceChunk]] = {
        group: [] for group in group_order
    }
    for document_id in document_ids:
        document = documents[document_id]
        chunks = chunk_document(
            document.metadata,
            document.content,
            preserve_unit_max_tokens=min(
                480, max(1, int(getattr(settings, "LLM_CONTEXT_MAX_TOKENS", 720)) - 80)
            ),
            max_tokens=int(
                getattr(settings, "QUERY_CHUNK_MAX_TOKENS", 220)
            ),
            overlap_tokens=int(
                getattr(settings, "QUERY_CHUNK_OVERLAP_TOKENS", 24)
            ),
        )
        for chunk in chunks:
            group = (document_id, _article_number(chunk.article) or "")
            if local_rescue and group not in chunks_by_group:
                group_order.append(group)
                chunks_by_group[group] = []
            if group not in chunks_by_group:
                continue
            chunks_by_group[group].append(
                replace(
                    chunk,
                    source_content_sha256=verified_hashes[document_id],
                )
            )

    duration_selection_diagnostics: dict[str, Any] = {}
    if local_rescue and local_topic is not None:
        additional, duration_selection_diagnostics = _choose_local_rescue_clause(
            query,
            local_topic,
            chunks_by_group,
            group_order,
            selected_evidence,
            require_numeric_duration=duration_intent,
            max_aggregate_tokens=int(
                getattr(settings, "QUERY_CHUNK_MAX_TOKENS", 220)
            ),
        )
    else:
        additional = _choose_additional_evidence(
            query,
            selected_evidence,
            chunks_by_group,
            group_order,
        )
    if additional is None:
        return V3ArticleExpansion(
            status="not_found",
            selected_evidence=list(selected_evidence),
            added_evidence=[],
            diagnostics={
                "status": "no_matching_sibling_clause",
                "documents_expanded": len(documents),
                "articles_expanded": len(group_order),
                **duration_selection_diagnostics,
            },
            latency_seconds=time.perf_counter() - started,
        )

    if any(
        int(candidate.document_id) == int(additional.document_id)
        and candidate.citation == additional.citation
        and candidate.text == additional.text
        for candidate in selected_evidence
    ):
        return V3ArticleExpansion(
            status="not_found",
            selected_evidence=list(selected_evidence),
            added_evidence=[],
            diagnostics={
                "status": "sibling_already_selected",
                **duration_selection_diagnostics,
            },
            latency_seconds=time.perf_counter() - started,
        )

    additional_article = _article_number(additional.article)
    replace_same_duration_group = (
        duration_intent
        and local_rescue
        and additional_article is not None
        and any(
            int(item.document_id) == int(additional.document_id)
            and _article_number(item.article) == additional_article
            for item in selected_evidence
        )
    )
    if replace_same_duration_group:
        first_same_group = next(
            index
            for index, item in enumerate(selected_evidence)
            if int(item.document_id) == int(additional.document_id)
            and _article_number(item.article) == additional_article
        )
        expanded_selected = [
            item
            for item in selected_evidence
            if not (
                int(item.document_id) == int(additional.document_id)
                and _article_number(item.article) == additional_article
            )
        ]
        expanded_selected.insert(
            min(first_same_group, len(expanded_selected)), additional
        )
        expanded_selected = expanded_selected[:limit]
    else:
        expanded_selected = list(selected_evidence)
        if limit <= 0:
            expanded_selected = []
        elif len(expanded_selected) < limit:
            expanded_selected.append(additional)
        else:
            expanded_selected = expanded_selected[: limit - 1] + [additional]

    return V3ArticleExpansion(
        status="expanded",
        selected_evidence=expanded_selected,
        added_evidence=[additional],
        diagnostics={
            "status": "expanded",
            "documents_expanded": len(documents),
            "articles_expanded": len(group_order),
            "chunks_considered": sum(len(chunks) for chunks in chunks_by_group.values()),
            "evidence_added": 1,
            **duration_selection_diagnostics,
        },
        latency_seconds=time.perf_counter() - started,
    )
