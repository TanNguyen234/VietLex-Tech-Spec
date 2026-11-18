"""Curated modern normative corpus selector and whole-article structural chunking."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

import zstandard

from app.ingestion.legal_text import (
    ARTICLE_RE,
    DocumentMetadata,
    EvidenceChunk,
    chunk_document,
)
from app.ingestion.structural_index import StructuralRecord
from app.ingestion.vertex_qdrant_migration import select_evenly_spaced_chunks
from app.services.instrument_registry import SUPERSEDED_INSTRUMENTS
from app.services.legal_topic_terms import fold_topic_text


CURATED_MAX_TOKENS = 320
CURATED_OVERLAP_TOKENS = 32
CURATED_PRESERVE_ARTICLE_MAX_TOKENS = 320
CURATED_MAX_CONTENT_CHARS = 1_900_000
CURATED_V3_POINT_BUDGET = 225_000
CURATED_ANNEX_TAIL_CAP = 16

PINNED_CONSTITUTION_VBHN_ID = 665872  # 52/VBHN-VPQH (Hiến pháp hợp nhất 2025)
PINNED_CONSTITUTION_AMEND_ID = 655275  # 203/2025/QH15 (Sửa đổi Hiến pháp 2025)

PINNED_KEY_DECREE_NUMBERS = frozenset(
    {
        "126/2014/NĐ-CP",  # Hướng dẫn Luật Hôn nhân và gia đình 2014
        "123/2015/NĐ-CP",  # Hướng dẫn Luật Hộ tịch 2014
    }
)

EXCLUDED_QUALITY_FLAGS = frozenset(
    {
        "empty_content",
        "encoding_damage",
        "missing_document_number",
        "missing_title",
        "missing_source_url",
    }
)

CENTRAL_RESOLUTION_AUTHORITIES = frozenset(
    {
        "Quốc hội",
        "Uỷ ban Thường vụ Quốc hội",
        "Ủy ban Thường vụ Quốc hội",
        "Chính phủ",
        "Hội đồng Thẩm phán Toà án nhân dân tối cao",
        "Hội đồng Thẩm phán Tòa án nhân dân tối cao",
        "Chính phủ, Uỷ ban Thường vụ Quốc hội, Uỷ ban Trung ương Mặt trận Tổ quốc Việt Nam",
        "Chính phủ, Ủy ban Thường vụ Quốc hội, Ủy ban Trung ương Mặt trận Tổ quốc Việt Nam",
    }
)

_SUPERSEDED_CODE_NUMBERS = frozenset(
    {
        "33/2005/QH11",  # Bộ luật Dân sự 2005 -> BLDS 2015
        "24/2004/QH11",  # Bộ luật TTDS 2004 -> BLTTDS 2015
        "15/1999/QH10",  # Bộ luật Hình sự 1999 -> BLHS 2015
        "19/2003/QH11",  # Bộ luật TTHS 2003 -> BLTTHS 2015
        "10/2012/QH13",  # Bộ luật Lao động 2012 -> BLLĐ 2019
        "60/2005/QH11",  # Luật Doanh nghiệp 2005 -> Luật DN 2020
        "68/2014/QH13",  # Luật Doanh nghiệp 2014 -> Luật DN 2020
        "59/2005/QH11",  # Luật Đầu tư 2005 -> Luật Đầu tư 2020
        "67/2014/QH13",  # Luật Đầu tư 2014 -> Luật Đầu tư 2020
        "13/1999/QH10",  # Luật Doanh nghiệp nhà nước 1999 -> hết hiệu lực
        "18/2000/QH10",  # Luật Hôn nhân và gia đình 2000 -> 52/2014/QH13
        "13/2003/QH11",  # Luật Đất đai 2003 -> 45/2013/QH13 -> 31/2024/QH15
        "45/2013/QH13",  # Luật Đất đai 2013 -> 31/2024/QH15
        "23/2008/QH12",  # Luật Giao thông đường bộ 2008 -> Luật TTATGTĐB & Đường bộ 2024
        "65/2014/QH13",  # Luật Nhà ở 2014 -> 27/2023/QH15
        "66/2014/QH13",  # Luật Kinh doanh bất động sản 2014 -> 29/2023/QH15
        "55/2014/QH13",  # Luật Bảo vệ môi trường 2014 -> 72/2020/QH14
        "51/2005/QH11",  # Luật Giao dịch điện tử 2005 -> 20/2023/QH15
        "59/2010/QH12",  # Luật Bảo vệ quyền lợi NTD 2010 -> 19/2023/QH15
        "11/2012/QH13",  # Luật Giá 2012 -> 16/2023/QH15
        "59/2014/QH13",  # Luật Căn cước công dân 2014 -> 26/2023/QH15
        "43/2013/QH13",  # Luật Đấu thầu 2013 -> 22/2023/QH15
        "58/2014/QH13",  # Luật Bảo hiểm xã hội 2014 -> 41/2024/QH15
        "71/2006/QH11",  # Luật Bảo hiểm xã hội 2006 -> 58/2014/QH13 -> 41/2024/QH15
    }
)

_MULTILINE_ARTICLE_RE = re.compile(
    r"(?m)^(?:\s*(?:#{1,6}\s+|\*\*|__)?\s*)(?:Điều\s+\d+[A-Za-zđĐ]?)\b",
    re.IGNORECASE,
)
_ENGLISH_HEADER_RE = re.compile(
    r"\b(?:THE NATIONAL ASSEMBLY|SOCIALIST REPUBLIC OF VIET\s*NAM|THE GOVERNMENT|"
    r"MINISTRY OF|LAW\s+ON|DECREE\s+NO|PRIME MINISTER)\b",
    re.IGNORECASE,
)
_ENGLISH_ARTICLE_RE = re.compile(r"(?m)^\s*Article\s+\d+\.")
_NUMBER_YEAR_RE = re.compile(r"\d{1,4}/((?:19|20)\d{2})/")

TierName = Literal["A", "B", "D", "E"]
ValidityHint = Literal["active_candidate", "superseded"]


@dataclass(frozen=True)
class CuratedDocumentEntry:
    document_id: int
    tier: TierName
    document_number: str
    title: str
    legal_type: str
    issuing_authority: str
    issuance_date: str
    content_sha256: str
    utf8_bytes: int
    chunk_count: int
    distinct_article_count: int
    max_chunks_cap: int | None
    issuance_year: int
    normative_rank: int
    validity_hint: ValidityHint


@dataclass(frozen=True)
class CuratedCorpusPlan:
    entries: tuple[CuratedDocumentEntry, ...]
    document_ids: tuple[int, ...]
    total_documents: int
    total_points: int
    total_utf8_bytes: int
    tier_counts: dict[str, int]
    tier_points: dict[str, int]
    skipped_counts: dict[str, int]
    selection_sha256: str


def normalize_document_number(value: str) -> str:
    return re.sub(r"\s+", "", (value or "")).upper()


def is_valid_iso_date(value: str | None) -> bool:
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def extract_issuance_year(issuance_date: str | None) -> int | None:
    if not is_valid_iso_date(issuance_date):
        return None
    assert issuance_date is not None
    return int(issuance_date[:4])


def is_english_untranslated_body(content: str) -> bool:
    if _MULTILINE_ARTICLE_RE.search(content):
        return False
    head = content[:1500]
    if _ENGLISH_HEADER_RE.search(head) or _ENGLISH_ARTICLE_RE.search(content):
        return True
    return False


def is_constitutional_vbhn(
    *,
    document_id: int,
    document_number: str,
    title: str,
    legal_type: str,
) -> bool:
    if legal_type != "Văn bản hợp nhất":
        return False
    if document_id == PINNED_CONSTITUTION_VBHN_ID:
        return True
    return (
        normalize_document_number(document_number) == "52/VBHN-VPQH"
        and "hiến pháp" in (title or "").casefold()
    )


def compute_normative_rank(
    *,
    legal_type: str,
    title: str = "",
    issuing_authority: str = "",
    document_id: int | None = None,
    document_number: str = "",
) -> int:
    ltype = (legal_type or "").strip()
    tfold = (title or "").strip().casefold()
    if (
        ltype == "Hiến pháp"
        or document_id in {PINNED_CONSTITUTION_VBHN_ID, PINNED_CONSTITUTION_AMEND_ID}
        or is_constitutional_vbhn(
            document_id=document_id or 0,
            document_number=document_number,
            title=title,
            legal_type=ltype,
        )
    ):
        return 6
    if ltype in {"Bộ luật", "Luật"}:
        return 5 if tfold.startswith("bộ luật") else 4
    if ltype == "Pháp lệnh":
        return 3
    if ltype == "Nghị quyết":
        auth_fold = (issuing_authority or "").casefold()
        if "quốc hội" in auth_fold or "thẩm phán" in auth_fold:
            return 3
        return 2
    if ltype == "Nghị định":
        return 2
    if ltype in {"Thông tư", "Thông tư liên tịch"}:
        return 1
    return 1


def compute_validity_hint(
    *,
    document_number: str,
    title: str,
    issuance_date: str | None = None,
    legal_type: str = "",
) -> ValidityHint:
    norm_num = normalize_document_number(document_number)
    if norm_num in _SUPERSEDED_CODE_NUMBERS:
        return "superseded"
    tfold = (title or "").casefold()
    if "hết hiệu lực" in tfold:
        return "superseded"
    folded_header = fold_topic_text(f"{document_number} {title}")
    year_val = extract_issuance_year(issuance_date)
    if year_val is None:
        match = _NUMBER_YEAR_RE.search(folded_header)
        year_val = int(match.group(1)) if match else None
    if (legal_type or "").strip() == "Hiến pháp" and year_val is not None and year_val < 2013:
        return "superseded"
    for item in SUPERSEDED_INSTRUMENTS:
        if any(marker in folded_header for marker in item.markers):
            if item.before_year:
                if year_val is not None and year_val < int(item.before_year):
                    return "superseded"
            else:
                return "superseded"
    return "active_candidate"


def build_curated_extra_payload(metadata: DocumentMetadata) -> dict[str, object]:
    return {
        "issuance_year": extract_issuance_year(metadata.issuance_date),
        "normative_rank": compute_normative_rank(
            legal_type=metadata.legal_type,
            title=metadata.title,
            issuing_authority=metadata.issuing_authority,
            document_id=metadata.document_id,
            document_number=metadata.document_number,
        ),
        "validity_hint": compute_validity_hint(
            document_number=metadata.document_number,
            title=metadata.title,
            issuance_date=metadata.issuance_date,
            legal_type=metadata.legal_type,
        ),
    }


def classify_curated_tier(metadata: DocumentMetadata) -> TierName | None:
    doc_id = metadata.document_id
    ltype = (metadata.legal_type or "").strip()
    idate = (metadata.issuance_date or "").strip()
    auth = (metadata.issuing_authority or "").strip()
    norm_num = normalize_document_number(metadata.document_number)

    if is_constitutional_vbhn(
        document_id=doc_id,
        document_number=metadata.document_number,
        title=metadata.title,
        legal_type=ltype,
    ):
        return "A"
    if doc_id == PINNED_CONSTITUTION_AMEND_ID or (
        norm_num == "203/2025/QH15" and ltype == "Nghị quyết"
    ):
        return "A"
    if ltype == "Văn bản hợp nhất":
        return None
    if ltype == "Hiến pháp":
        return "A"
    if ltype in {"Luật", "Bộ luật", "Pháp lệnh"} and "1995-01-01" <= idate <= "2026-12-31":
        return "A"
    if ltype == "Nghị định" and (
        "2015-01-01" <= idate <= "2026-12-31" or norm_num in PINNED_KEY_DECREE_NUMBERS
    ):
        return "B"
    if (
        ltype == "Nghị quyết"
        and "2015-01-01" <= idate <= "2026-12-31"
        and auth in CENTRAL_RESOLUTION_AUTHORITIES
    ):
        return "D"
    if (
        ltype in {"Thông tư", "Thông tư liên tịch"}
        and "2020-01-01" <= idate <= "2026-12-31"
    ):
        return "E"
    return None


def pack_article_clause_chunks(
    chunks: list[EvidenceChunk],
    *,
    max_tokens: int = CURATED_MAX_TOKENS,
) -> list[EvidenceChunk]:
    """Pack consecutive single-window clause chunks of the same article up to max_tokens."""
    if not chunks:
        return []
    packed: list[EvidenceChunk] = []
    idx = 0
    total = len(chunks)
    while idx < total:
        first = chunks[idx]
        if first.article is None or first.clause is None:
            packed.append(first)
            idx += 1
            continue
        if (
            idx + 1 < total
            and chunks[idx + 1].article == first.article
            and chunks[idx + 1].clause == first.clause
        ):
            while (
                idx < total
                and chunks[idx].article == first.article
                and chunks[idx].clause == first.clause
            ):
                packed.append(chunks[idx])
                idx += 1
            continue

        merged_texts = [first.text]
        current_words = first.token_count
        next_idx = idx + 1
        while next_idx < total:
            candidate = chunks[next_idx]
            if candidate.article != first.article or candidate.clause is None:
                break
            if (
                next_idx + 1 < total
                and chunks[next_idx + 1].article == candidate.article
                and chunks[next_idx + 1].clause == candidate.clause
            ):
                break
            search_offset = (
                len(candidate.article)
                if candidate.article and candidate.text.startswith(candidate.article)
                else 0
            )
            tail_view = candidate.text[search_offset:]
            clause_match = re.search(
                rf"(?m)^\s*{re.escape(candidate.clause)}\.\s+",
                tail_view,
            ) or re.search(rf"\b{re.escape(candidate.clause)}\.\s+", tail_view)
            clause_body = (
                tail_view[clause_match.start() :].strip()
                if clause_match
                else candidate.text
            )
            added_words = len(clause_body.split())
            if current_words + added_words > max_tokens:
                break
            merged_texts.append(clause_body)
            current_words += added_words
            next_idx += 1

        if len(merged_texts) == 1:
            packed.append(first)
        else:
            joined = "\n".join(merged_texts)
            base_citation = first.citation.rsplit(", Khoản ", 1)[0]
            packed.append(
                EvidenceChunk(
                    document_id=first.document_id,
                    document_number=first.document_number,
                    title=first.title,
                    source_url=first.source_url,
                    heading_path=first.heading_path,
                    article=first.article,
                    clause=None,
                    citation=base_citation,
                    text=joined,
                    token_count=len(joined.split()),
                    source_content_sha256=first.source_content_sha256,
                )
            )
        idx = next_idx
    return packed


def chunk_curated_document(
    metadata: DocumentMetadata,
    content: str,
    *,
    tier: TierName,
) -> tuple[list[EvidenceChunk], int, int | None]:
    """Return `(selected_chunks, distinct_article_count, applied_cap)`."""
    raw_chunks = chunk_document(
        metadata,
        content,
        max_tokens=CURATED_MAX_TOKENS,
        overlap_tokens=CURATED_OVERLAP_TOKENS,
        preserve_article_max_tokens=CURATED_PRESERVE_ARTICLE_MAX_TOKENS,
    )
    packed = pack_article_clause_chunks(raw_chunks, max_tokens=CURATED_MAX_TOKENS)

    cap: int | None = None
    if tier == "A":
        selected = packed
    elif tier in {"B", "D"}:
        tfold = (metadata.title or "").casefold()
        is_tariff_schedule = tier == "B" and (
            "biểu thuế nhập khẩu" in tfold or "biểu thuế xuất khẩu" in tfold
        )
        if is_tariff_schedule:
            cap = 24
            selected = (
                select_evenly_spaced_chunks(packed, limit=cap)
                if len(packed) > cap
                else packed
            )
        else:
            article_chunks = [c for c in packed if c.article is not None]
            annex_chunks = [c for c in packed if c.article is None]
            if len(annex_chunks) > CURATED_ANNEX_TAIL_CAP:
                capped_annex = select_evenly_spaced_chunks(
                    annex_chunks,
                    limit=CURATED_ANNEX_TAIL_CAP,
                )
                selected = [*article_chunks, *capped_annex]
            else:
                selected = packed
    else:
        cap = 20
        selected = (
            select_evenly_spaced_chunks(packed, limit=cap)
            if len(packed) > cap
            else packed
        )

    distinct_articles = len(
        {
            match.group(1).casefold()
            for chunk in selected
            if chunk.article and (match := ARTICLE_RE.match(chunk.article))
        }
        or {chunk.article.casefold() for chunk in selected if chunk.article}
    )
    return selected, distinct_articles, cap


def _iter_candidate_documents_sqlite(
    db_path: Path,
) -> list[tuple[DocumentMetadata, str, str, tuple[str, ...]]]:
    decompressor = zstandard.ZstdDecompressor()
    authorities_placeholders = ",".join("?" for _ in CENTRAL_RESOLUTION_AUTHORITIES)
    pinned_decree_nums = tuple(PINNED_KEY_DECREE_NUMBERS)
    pinned_decree_placeholders = ",".join("?" for _ in pinned_decree_nums)
    sql = f"""
    SELECT m.document_id, m.document_number, m.title, m.source_url, m.legal_type,
           m.legal_sectors, m.issuing_authority, m.issuance_date, m.quality_flags,
           c.content_zstd, c.content_sha256, c.quality_flags
    FROM metadata m
    INNER JOIN contents c USING(document_id)
    WHERE (
        m.document_id IN (?, ?)
        OR m.legal_type = 'Hiến pháp'
        OR (m.legal_type IN ('Luật', 'Bộ luật', 'Pháp lệnh') AND m.issuance_date >= '1995-01-01' AND m.issuance_date <= '2026-12-31')
        OR (m.legal_type = 'Nghị định' AND ((m.issuance_date >= '2015-01-01' AND m.issuance_date <= '2026-12-31') OR UPPER(REPLACE(m.document_number, ' ', '')) IN ({pinned_decree_placeholders})))
        OR (m.legal_type = 'Nghị quyết' AND m.issuance_date >= '2015-01-01' AND m.issuance_date <= '2026-12-31' AND m.issuing_authority IN ({authorities_placeholders}))
        OR (m.legal_type IN ('Thông tư', 'Thông tư liên tịch') AND m.issuance_date >= '2020-01-01' AND m.issuance_date <= '2026-12-31')
    )
    ORDER BY m.issuance_date DESC, m.document_id DESC
    """
    params: tuple[object, ...] = (
        PINNED_CONSTITUTION_VBHN_ID,
        PINNED_CONSTITUTION_AMEND_ID,
        *pinned_decree_nums,
        *sorted(CENTRAL_RESOLUTION_AUTHORITIES),
    )
    out: list[tuple[DocumentMetadata, str, str, tuple[str, ...]]] = []
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        rows = conn.execute(sql, params).fetchall()
    for row in rows:
        doc_id = int(row[0])
        flags = tuple(sorted(set(json.loads(row[8])) | set(json.loads(row[11]))))
        content = decompressor.decompress(row[9]).decode("utf-8")
        meta = DocumentMetadata(
            document_id=doc_id,
            document_number=str(row[1] or ""),
            title=str(row[2] or ""),
            source_url=str(row[3] or ""),
            legal_type=str(row[4] or ""),
            legal_sectors=str(row[5] or ""),
            issuing_authority=str(row[6] or ""),
            issuance_date=row[7],
        )
        out.append((meta, content, str(row[10] or ""), flags))
    return out


def _iter_candidate_documents_generic(
    store: Any,
) -> list[tuple[DocumentMetadata, str, str, tuple[str, ...]]]:
    all_ids: list[int] = []
    after_id = -1
    while True:
        batch = store.iter_document_ids(after_id=after_id, limit=512)
        if not batch:
            break
        all_ids.extend(batch)
        after_id = max(batch)

    docs: list[tuple[DocumentMetadata, str, str, tuple[str, ...]]] = []
    for offset in range(0, len(all_ids), 128):
        loaded = store.get_many(all_ids[offset : offset + 128])
        for doc_id in all_ids[offset : offset + 128]:
            doc = loaded.get(doc_id)
            if doc is None:
                continue
            docs.append(
                (
                    doc.metadata,
                    doc.content,
                    doc.content_sha256,
                    tuple(doc.quality_flags),
                )
            )
    docs.sort(
        key=lambda item: (
            item[0].issuance_date or "",
            item[0].document_id,
        ),
        reverse=True,
    )
    return docs


def select_and_chunk_curated_corpus(
    store: Any,
    *,
    max_total_points: int = CURATED_V3_POINT_BUDGET,
) -> tuple[CuratedCorpusPlan, dict[int, tuple[DocumentMetadata, str, list[EvidenceChunk]]]]:
    """Select curated documents and return both the plan and prepared chunks in one pass."""
    if max_total_points <= 0:
        raise ValueError("max_total_points must be positive")

    store_path = getattr(store, "path", None)
    if isinstance(store_path, Path) and store_path.is_file():
        candidates = _iter_candidate_documents_sqlite(store_path)
    else:
        candidates = _iter_candidate_documents_generic(store)

    skipped: dict[str, int] = {
        "invalid_metadata": 0,
        "invalid_date": 0,
        "excluded_quality_flag": 0,
        "non_curated_tier": 0,
        "invalid_content_or_hash": 0,
        "english_untranslated": 0,
        "empty_chunks": 0,
        "tier_e_budget_capped": 0,
    }

    primary_entries: list[CuratedDocumentEntry] = []
    tier_e_candidates: list[tuple[CuratedDocumentEntry, DocumentMetadata, str, list[EvidenceChunk]]] = []
    prepared: dict[int, tuple[DocumentMetadata, str, list[EvidenceChunk]]] = {}
    seen_ids: set[int] = set()

    for raw_meta, content, stored_sha, quality_flags in candidates:
        doc_id = int(raw_meta.document_id)
        if doc_id <= 0 or doc_id in seen_ids:
            skipped["invalid_metadata"] += 1
            continue
        doc_num = (raw_meta.document_number or "").strip()
        title = (raw_meta.title or "").strip()
        source_url = (raw_meta.source_url or "").strip()
        legal_type = (raw_meta.legal_type or "").strip()
        authority = (raw_meta.issuing_authority or "").strip()
        idate = (raw_meta.issuance_date or "").strip()

        if not (doc_num and title and source_url and legal_type and authority and idate):
            skipped["invalid_metadata"] += 1
            continue
        if not is_valid_iso_date(idate) or not ("1945-01-01" <= idate <= "2026-12-31"):
            skipped["invalid_date"] += 1
            continue
        if EXCLUDED_QUALITY_FLAGS.intersection(quality_flags):
            skipped["excluded_quality_flag"] += 1
            continue

        clean_meta = DocumentMetadata(
            document_id=doc_id,
            document_number=doc_num,
            title=title,
            source_url=source_url,
            legal_type=legal_type,
            legal_sectors=(raw_meta.legal_sectors or "").strip(),
            issuing_authority=authority,
            issuance_date=idate,
        )
        tier = classify_curated_tier(clean_meta)
        if tier is None:
            skipped["non_curated_tier"] += 1
            continue

        if not isinstance(content, str) or not (0 < len(content) <= CURATED_MAX_CONTENT_CHARS):
            skipped["invalid_content_or_hash"] += 1
            continue
        content_bytes = content.encode("utf-8")
        computed_sha = hashlib.sha256(content_bytes).hexdigest()
        if computed_sha != stored_sha:
            skipped["invalid_content_or_hash"] += 1
            continue
        if is_english_untranslated_body(content):
            skipped["english_untranslated"] += 1
            continue

        chunks, distinct_articles, cap = chunk_curated_document(
            clean_meta,
            content,
            tier=tier,
        )
        if not chunks:
            skipped["empty_chunks"] += 1
            continue

        seen_ids.add(doc_id)
        entry = CuratedDocumentEntry(
            document_id=doc_id,
            tier=tier,
            document_number=doc_num,
            title=title,
            legal_type=legal_type,
            issuing_authority=authority,
            issuance_date=idate,
            content_sha256=computed_sha,
            utf8_bytes=len(content_bytes),
            chunk_count=len(chunks),
            distinct_article_count=distinct_articles,
            max_chunks_cap=cap,
            issuance_year=int(idate[:4]),
            normative_rank=compute_normative_rank(
                legal_type=legal_type,
                title=title,
                issuing_authority=authority,
                document_id=doc_id,
                document_number=doc_num,
            ),
            validity_hint=compute_validity_hint(
                document_number=doc_num,
                title=title,
                issuance_date=idate,
                legal_type=legal_type,
            ),
        )
        if tier == "E":
            tier_e_candidates.append((entry, clean_meta, computed_sha, chunks))
        else:
            primary_entries.append(entry)
            prepared[doc_id] = (clean_meta, computed_sha, chunks)

    running_points = sum(item.chunk_count for item in primary_entries)
    accepted_tier_e: list[CuratedDocumentEntry] = []
    # Tier E is already sorted newest-first (issuance_date DESC, document_id DESC)
    tier_e_candidates.sort(
        key=lambda item: (item[0].issuance_date, item[0].document_id),
        reverse=True,
    )
    for entry, clean_meta, computed_sha, chunks in tier_e_candidates:
        if running_points + entry.chunk_count > max_total_points:
            skipped["tier_e_budget_capped"] += 1
            continue
        accepted_tier_e.append(entry)
        prepared[entry.document_id] = (clean_meta, computed_sha, chunks)
        running_points += entry.chunk_count

    all_entries = sorted(
        [*primary_entries, *accepted_tier_e],
        key=lambda item: (item.issuance_date, item.document_id),
        reverse=True,
    )
    sorted_ids = tuple(sorted(item.document_id for item in all_entries))
    tier_counts: dict[str, int] = {"A": 0, "B": 0, "D": 0, "E": 0}
    tier_points: dict[str, int] = {"A": 0, "B": 0, "D": 0, "E": 0}
    for item in all_entries:
        tier_counts[item.tier] += 1
        tier_points[item.tier] += item.chunk_count

    selection_sha256 = hashlib.sha256(
        json.dumps(sorted_ids, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    plan = CuratedCorpusPlan(
        entries=tuple(all_entries),
        document_ids=sorted_ids,
        total_documents=len(all_entries),
        total_points=sum(item.chunk_count for item in all_entries),
        total_utf8_bytes=sum(item.utf8_bytes for item in all_entries),
        tier_counts=tier_counts,
        tier_points=tier_points,
        skipped_counts=skipped,
        selection_sha256=selection_sha256,
    )
    return plan, prepared


def select_curated_normative_ids(
    store: Any,
    *,
    max_total_points: int = CURATED_V3_POINT_BUDGET,
) -> CuratedCorpusPlan:
    plan, _ = select_and_chunk_curated_corpus(
        store,
        max_total_points=max_total_points,
    )
    return plan


def build_structural_records_from_prepared(
    plan: CuratedCorpusPlan,
    prepared: dict[int, tuple[DocumentMetadata, str, list[EvidenceChunk]]],
    *,
    repository: str,
    revision: str,
) -> list[tuple[StructuralRecord, dict[str, object]]]:
    records_with_extra: list[tuple[StructuralRecord, dict[str, object]]] = []
    by_id = {entry.document_id: entry for entry in plan.entries}
    for doc_id in plan.document_ids:
        entry = by_id[doc_id]
        meta, content_sha256, chunks = prepared[doc_id]
        extra = {
            "issuance_year": entry.issuance_year,
            "normative_rank": entry.normative_rank,
            "validity_hint": entry.validity_hint,
        }
        for chunk_index, chunk in enumerate(chunks):
            body = chunk.text.strip()
            chunk_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
            identity = (
                "vietlex-vertex-qdrant-v1:"
                f"{repository}@{revision}#{doc_id}:"
                f"{chunk_index}:{chunk_sha256}"
            )
            records_with_extra.append(
                (
                    StructuralRecord(
                        record_id=str(uuid5(NAMESPACE_URL, identity)),
                        body=body,
                        document_id=doc_id,
                        document_number=meta.document_number,
                        title=meta.title,
                        source_url=meta.source_url,
                        legal_type=meta.legal_type,
                        issuing_authority=meta.issuing_authority or None,
                        issuance_date=meta.issuance_date,
                        article=chunk.article,
                        clause=chunk.clause,
                        heading_path=chunk.heading_path,
                        citation=chunk.citation,
                        token_count=chunk.token_count,
                        dataset_revision=revision,
                        content_sha256=content_sha256,
                        chunk_sha256=chunk_sha256,
                    ),
                    extra,
                )
            )
    return records_with_extra


def build_curated_structural_records(
    store: Any,
    plan: CuratedCorpusPlan,
    *,
    repository: str,
    revision: str,
) -> list[tuple[StructuralRecord, dict[str, object]]]:
    by_id = {entry.document_id: entry for entry in plan.entries}
    prepared: dict[int, tuple[DocumentMetadata, str, list[EvidenceChunk]]] = {}
    ordered_ids = list(plan.document_ids)
    for offset in range(0, len(ordered_ids), 64):
        batch_ids = ordered_ids[offset : offset + 64]
        loaded = store.get_many(batch_ids)
        for doc_id in batch_ids:
            doc = loaded.get(doc_id)
            if doc is None:
                raise ValueError(f"missing curated document {doc_id} in store")
            entry = by_id[doc_id]
            clean_meta = DocumentMetadata(
                document_id=doc_id,
                document_number=doc.metadata.document_number.strip(),
                title=doc.metadata.title.strip(),
                source_url=doc.metadata.source_url.strip(),
                legal_type=doc.metadata.legal_type.strip(),
                legal_sectors=(doc.metadata.legal_sectors or "").strip(),
                issuing_authority=doc.metadata.issuing_authority.strip(),
                issuance_date=(doc.metadata.issuance_date or "").strip(),
            )
            chunks, _, _ = chunk_curated_document(
                clean_meta,
                doc.content,
                tier=entry.tier,
            )
            prepared[doc_id] = (clean_meta, doc.content_sha256, chunks)
    return build_structural_records_from_prepared(
        plan,
        prepared,
        repository=repository,
        revision=revision,
    )
