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
from app.services.retrieval import INTENT_PATTERNS, select_rerank_candidates


_ARTICLE_QUERY_RE = re.compile(r"\bdieu\s+(\d+[a-z]?)\b", re.IGNORECASE)
_CLAUSE_QUERY_RE = re.compile(r"\bkhoan\s+(\d+)\b", re.IGNORECASE)
_ARTICLE_NUMBER_RE = re.compile(r"\b(?:dieu\s*)?(\d+[a-z]?)\b", re.IGNORECASE)
_DURATION_EVIDENCE_RE = re.compile(
    r"(?<!\d)\d{1,4}(?:[.,]\d+)?\s*"
    r"(?:ngay(?:\s+lam\s+viec)?|tuan|thang|nam|gio|phut)\b",
    re.IGNORECASE,
)


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


def _load_source_documents(settings: Any, document_ids: list[int]) -> dict[int, StoredDocument]:
    if getattr(settings, "SERVERLESS_ONLINE_ONLY", False):
        from app.services.legal_browser import SupabaseLegalStore

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
    return ContentStore(settings.CONTENT_STORE_PATH).get_many(document_ids)


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
    if not explicit and not _asks_for_duration(query):
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

    document_ids, group_order = _candidate_groups(
        expansion_candidates,
        max_documents=max(0, int(max_documents)),
    )
    if not document_ids or not group_order:
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
        documents = await asyncio.to_thread(loader, document_ids)
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

    chunks_by_group: dict[tuple[int, str], list[EvidenceChunk]] = {
        group: [] for group in group_order
    }
    for document_id in document_ids:
        document = documents[document_id]
        chunks = chunk_document(
            document.metadata,
            document.content,
            max_tokens=int(
                getattr(settings, "QUERY_CHUNK_MAX_TOKENS", 220)
            ),
            overlap_tokens=int(
                getattr(settings, "QUERY_CHUNK_OVERLAP_TOKENS", 24)
            ),
        )
        for chunk in chunks:
            group = (document_id, _article_number(chunk.article) or "")
            if group not in chunks_by_group:
                continue
            chunks_by_group[group].append(
                replace(
                    chunk,
                    source_content_sha256=verified_hashes[document_id],
                )
            )

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
            diagnostics={"status": "sibling_already_selected"},
            latency_seconds=time.perf_counter() - started,
        )

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
        },
        latency_seconds=time.perf_counter() - started,
    )
