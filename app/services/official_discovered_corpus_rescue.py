"""Recover relevant local-corpus evidence for official discovery records."""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
from itertools import islice
from typing import Any, Iterable, Mapping

from app.config import get_settings
from app.ingestion.legal_text import EvidenceChunk, chunk_document


_MAX_DISCOVERY_RECORDS = 10
_MAX_CORPUS_MATCHES = 50
_MAX_DOCUMENTS_TO_LOAD = 2
_MAX_EVIDENCE_CHUNKS = 3
_MAX_EVIDENCE_TOKENS = 720
_CHUNK_MAX_TOKENS = 220
_CHUNK_OVERLAP_TOKENS = 24
_MAX_TOPIC_TERMS = 64
_MAX_PHRASE_SOURCE_TOKENS = 256
_TOPIC_PHRASE_LENGTHS = range(2, 5)
_CORROBORATION_FIELDS = ("title", "issuing_authority", "issuance_date")
_TOPIC_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_NON_TOPICAL_TERMS = frozenset(
    {
        "bị", "bởi", "các", "có", "của", "được", "là", "một", "những",
        "theo", "thì", "trong", "và", "về", "với", "tại", "cho", "để",
        "đến", "này", "đó", "nào", "gì", "như", "thế", "bao", "nhiêu",
        "không", "phải", "sẽ", "đã", "cần", "nên", "hay", "hoặc", "vì",
        "do", "làm", "hãy", "vui", "lòng", "nói", "biết", "hỏi", "trả",
        "lời", "tóm", "tắt", "giải", "thích", "nội", "dung", "căn", "cứ",
        "pháp", "lý", "người",
        "điều", "khoản", "điểm", "mục", "chương", "luật", "văn", "bản",
        "giấy", "phép", "xuất", "khẩu", "nhập", "cấp", "thủ", "tục", "kiện",
        "quy", "định", "mức", "số", "tiền", "đồng", "ngày", "tháng", "năm",
        "mỗi", "hưởng", "triệu", "tỷ", "nghìn", "ngàn", "trăm", "phần",
        "lần", "giờ", "phút", "tuần", "quý", "kg", "km", "vnd", "usd",
        "the", "what", "which", "how", "much", "many",
        "does", "article", "section", "clause", "law", "amount", "number",
        "under", "say", "is", "it", "of", "a", "an", "for", "on",
    }
)


@dataclass(frozen=True)
class OfficialCorpusRescueResult:
    evidence: tuple[EvidenceChunk, ...]
    diagnostics: dict[str, Any]


def _field(record: Any, name: str, *aliases: str) -> Any:
    for key in (name, *aliases):
        value = record.get(key) if isinstance(record, Mapping) else getattr(record, key, None)
        if value is not None and str(value).strip():
            return value
    return None


def _number_key(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).upper()


def _text_key(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def _date_key(value: Any) -> str:
    raw = _text_key(value)
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, pattern).date().isoformat()
        except ValueError:
            continue
    return raw


def _corroboration(candidate: Any, records: list[Any]) -> tuple[set[str], set[str]]:
    matched: set[str] = set()
    conflicts: set[str] = set()
    for field in _CORROBORATION_FIELDS:
        aliases = {
            "issuing_authority": ("authority",),
            "issuance_date": ("issued_date", "date"),
        }.get(field, ())
        corpus_value = _field(candidate, field, *aliases)
        canonical = _date_key if field == "issuance_date" else _text_key
        corpus_key = canonical(corpus_value)
        official_keys = {
            canonical(_field(record, field, *aliases))
            for record in records
            if _field(record, field, *aliases) is not None
        }
        if not corpus_key or not official_keys:
            continue
        if corpus_key in official_keys:
            matched.add(field)
        if official_keys - {corpus_key}:
            conflicts.add(field)
    return matched, conflicts


def _resolve_collision(matches: list[Any], records: list[Any]) -> Any | None:
    results = []
    for candidate in matches:
        matched, conflicts = _corroboration(candidate, records)
        results.append((candidate, matched, conflicts))
    clean = [item for item in results if item[1] and not item[2]]
    if len(clean) != 1:
        return None
    selected = clean[0][0]
    # A candidate with missing corroboration data is still a possible collision.
    if any(not matched and not conflicts for candidate, matched, conflicts in results if candidate is not selected):
        return None
    return selected


def _is_topic_term(term: str) -> bool:
    return (
        len(term) >= 2
        and not any(character.isdigit() for character in term)
        and term not in _NON_TOPICAL_TERMS
    )


def _topic_phrases(text: str) -> Counter[str]:
    normalized = unicodedata.normalize("NFC", str(text or "")).casefold()
    terms = [
        match.group()
        for match in islice(_TOPIC_TOKEN.finditer(normalized), _MAX_PHRASE_SOURCE_TOKENS)
    ]
    phrases: Counter[str] = Counter()
    for length in _TOPIC_PHRASE_LENGTHS:
        for start in range(len(terms) - length + 1):
            phrase_terms = terms[start : start + length]
            if sum(_is_topic_term(term) for term in phrase_terms) >= 2:
                phrases[" ".join(phrase_terms)] += 1
    return phrases


def _topic_score(
    query_terms: Counter[str], query_phrases: Counter[str], chunk: EvidenceChunk
) -> float:
    if query_phrases:
        counts = _topic_phrases(chunk.text)
        return sum(
            1.0 + math.log(counts[phrase])
            for phrase in query_phrases
            if counts[phrase]
        )
    if len(query_terms) != 1:
        return 0.0
    term = next(iter(query_terms))
    count = Counter(_topic_terms(chunk.text, limit=_CHUNK_MAX_TOKENS))[term]
    return 1.0 + math.log(count) if count else 0.0


def _topic_terms(text: str, *, limit: int = _MAX_TOPIC_TERMS) -> Iterable[str]:
    """Yield bounded content terms, excluding legal scaffolding and quantities."""
    normalized = unicodedata.normalize("NFC", str(text or "")).casefold()
    emitted = 0
    for term in _TOPIC_TOKEN.findall(normalized):
        if not _is_topic_term(term):
            continue
        yield term
        emitted += 1
        if emitted >= limit:
            return


def rescue_official_discoveries(
    query: str,
    records: Iterable[Any],
    browser: Any,
    *,
    settings: Any | None = None,
) -> OfficialCorpusRescueResult:
    """Use discovery metadata to find, verify, and rank existing corpus text.

    `browser` must be the already-selected LegalBrowser; this function never
    creates a store or reads an official URL.
    """
    settings = settings or get_settings()
    records = list(islice(records or (), _MAX_DISCOVERY_RECORDS))
    grouped: dict[str, list[Any]] = {}
    display_numbers: dict[str, str] = {}
    candidates: list[dict[str, Any]] = []
    for record in records:
        number = _field(record, "document_number")
        key = _number_key(number)
        if not key or len(key) > 128:
            candidates.append({"document_number": "", "status": "invalid_document_number"})
            continue
        grouped.setdefault(key, []).append(record)
        display_numbers.setdefault(key, str(number).strip())

    resolved: list[tuple[str, Any, dict[str, Any]]] = []
    for key, grouped_records in grouped.items():
        search_number = key
        matches = [
            item
            for item in islice(
                browser.search(search_number, limit=_MAX_CORPUS_MATCHES),
                _MAX_CORPUS_MATCHES,
            )
            if _number_key(_field(item, "document_number")) == key
        ]
        unique_matches = []
        seen_ids: set[int] = set()
        for item in matches:
            try:
                document_id = int(_field(item, "document_id"))
            except (TypeError, ValueError):
                continue
            if document_id not in seen_ids:
                unique_matches.append(item)
                seen_ids.add(document_id)

        diagnostic = {
            "document_number": display_numbers[key],
            "corpus_match_count": len(unique_matches),
        }
        candidates.append(diagnostic)
        if len(matches) >= _MAX_CORPUS_MATCHES:
            diagnostic["status"] = "corpus_collision_limit_reached"
            continue
        if not unique_matches:
            diagnostic["status"] = "corpus_number_not_found"
            continue
        if len(unique_matches) == 1:
            selected = unique_matches[0]
            diagnostic["status"] = "corpus_number_matched"
            diagnostic["match_resolution"] = "exact_number"
        else:
            selected = _resolve_collision(unique_matches, grouped_records)
            if selected is None:
                diagnostic["status"] = "collision_ambiguous"
                continue
            diagnostic["status"] = "collision_corroborated"
            diagnostic["match_resolution"] = "collision_corroborated"
        diagnostic["document_id"] = int(_field(selected, "document_id"))
        resolved.append((key, selected, diagnostic))

    loaded_by_id: dict[int, Any | None] = {}
    chunks_by_id: dict[int, list[tuple[float, int, EvidenceChunk]]] = {}
    query_terms = Counter(_topic_terms(query))
    query_phrases = _topic_phrases(query)
    chunk_max = _CHUNK_MAX_TOKENS
    chunk_overlap = _CHUNK_OVERLAP_TOKENS
    chunk_limit = min(
        _MAX_EVIDENCE_CHUNKS,
        max(0, int(getattr(settings, "FINAL_EVIDENCE_LIMIT", _MAX_EVIDENCE_CHUNKS))),
    )
    token_limit = min(
        _MAX_EVIDENCE_TOKENS,
        max(0, int(getattr(settings, "LLM_CONTEXT_MAX_TOKENS", _MAX_EVIDENCE_TOKENS))),
    )

    for key, match, diagnostic in resolved:
        document_id = int(_field(match, "document_id"))
        if document_id not in loaded_by_id:
            if len(loaded_by_id) >= _MAX_DOCUMENTS_TO_LOAD:
                diagnostic["status"] = "corpus_document_load_limit"
                continue
            loaded_by_id[document_id] = browser.get_document(document_id)
        document = loaded_by_id[document_id]
        if document is None:
            diagnostic["status"] = "corpus_document_missing"
            continue
        metadata = _field(document, "metadata")
        content = _field(document, "content")
        if metadata is None or not isinstance(content, str) or not content:
            diagnostic["status"] = "corpus_document_incomplete"
            continue
        if _number_key(_field(metadata, "document_number")) != key:
            diagnostic["status"] = "corpus_document_number_changed"
            continue
        try:
            stored_document_id = int(_field(metadata, "document_id"))
        except (TypeError, ValueError):
            diagnostic["status"] = "corpus_document_id_changed"
            continue
        if stored_document_id != document_id:
            diagnostic["status"] = "corpus_document_id_changed"
            continue
        actual_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        stored_digest = str(_field(document, "content_sha256") or "").casefold()
        if actual_digest != stored_digest:
            diagnostic["status"] = "corpus_hash_mismatch"
            continue

        chunks = chunk_document(
            metadata,
            content,
            max_tokens=chunk_max,
            overlap_tokens=chunk_overlap,
        )
        scored = []
        for position, chunk in enumerate(chunks):
            score = _topic_score(query_terms, query_phrases, chunk)
            if score > 0:
                verified_chunk = replace(chunk, source_content_sha256=actual_digest)
                scored.append((score, position, verified_chunk))
        if not scored:
            diagnostic["status"] = "no_positive_topical_chunks"
            continue
        chunks_by_id[document_id] = scored
        diagnostic["status"] = "positive_topical_chunks"

    ranked = sorted(
        (item for chunks in chunks_by_id.values() for item in chunks),
        key=lambda item: (-item[0], item[1], item[2].document_id),
    )
    selected_chunks: list[EvidenceChunk] = []
    used_tokens = 0
    selected_ids: set[int] = set()
    for _score, _position, chunk in ranked:
        if len(selected_chunks) >= chunk_limit:
            break
        whitespace_tokens = len(chunk.text.split())
        if used_tokens + whitespace_tokens > token_limit:
            continue
        selected_chunks.append(chunk)
        selected_ids.add(chunk.document_id)
        used_tokens += whitespace_tokens

    for diagnostic in candidates:
        if diagnostic.get("document_id") in selected_ids:
            diagnostic["status"] = "evidence_selected"
    diagnostics = {
        "method": "official_discovery_corpus_rescue_v1",
        "status": "evidence_selected" if selected_chunks else "no_evidence",
        "discovery_records_considered": len(records),
        "corpus_documents_loaded": sum(document is not None for document in loaded_by_id.values()),
        "corpus_document_load_attempts": len(loaded_by_id),
        "selected_chunk_count": len(selected_chunks),
        "selected_whitespace_tokens": used_tokens,
        "chunk_max_tokens": chunk_max,
        "chunk_overlap_tokens": chunk_overlap,
        "provenance": "pinned_corpus_store",
        "official_discovery_used_as": "metadata_only",
        "official_external_source_read": False,
        "legal_effect_asserted": False,
        "candidates": candidates,
    }
    return OfficialCorpusRescueResult(tuple(selected_chunks), diagnostics)
