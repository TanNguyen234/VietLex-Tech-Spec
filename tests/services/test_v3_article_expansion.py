from __future__ import annotations

import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.ingestion.content_store import StoredDocument
from app.ingestion.legal_text import DocumentMetadata, EvidenceChunk


def _metadata(document_id: int = 10) -> DocumentMetadata:
    return DocumentMetadata(
        document_id=document_id,
        document_number="10/2020/QH14",
        title="Test law",
        source_url="https://example.test/law",
        legal_type="Law",
        legal_sectors="test",
        issuing_authority="Assembly",
        issuance_date="2020-01-01",
    )


def _content() -> str:
    return (
        "Điều 164. Trách nhiệm của thành viên\n"
        "1. Thành viên thực hiện nghĩa vụ với công ty.\n"
        "2. Thành viên báo cáo đầy đủ thông tin.\n"
        "3. Thành viên phải thông báo bằng văn bản trong 07 ngày làm việc.\n"
        "4. Thành viên tuân thủ quy định và bảo vệ lợi ích công ty.\n"
        "5. Thành viên chịu trách nhiệm theo quy định.\n"
    )


def _stored_document(document_id: int = 10, *, content: str | None = None, digest: str | None = None) -> StoredDocument:
    body = content if content is not None else _content()
    actual_digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return StoredDocument(
        metadata=_metadata(document_id),
        content=body,
        content_sha256=digest or actual_digest,
        content_store_key=str(document_id),
        quality_flags=(),
    )


def _candidate(
    document_id: int = 10,
    *,
    article: str = "Điều 164",
    clause: str = "5",
    source_hash: str | None = None,
) -> EvidenceChunk:
    source_hash = source_hash or hashlib.sha256(_content().encode("utf-8")).hexdigest()
    return EvidenceChunk(
        document_id=document_id,
        document_number="10/2020/QH14",
        title="Test law",
        source_url="https://example.test/law",
        heading_path=article,
        article=article,
        clause=clause,
        citation=f"10/2020/QH14, {article}, Khoản {clause}",
        text="Thành viên chịu trách nhiệm theo quy định.",
        token_count=10,
        source_content_sha256=source_hash,
    )


@pytest.mark.asyncio
async def test_duration_query_recovers_hash_verified_sibling_clause() -> None:
    from app.services.v3_article_expansion import expand_v3_evidence

    source = _stored_document()
    reads: list[list[int]] = []

    def load_many(document_ids: list[int]):
        reads.append(document_ids)
        return {10: source}

    candidate = _candidate()
    selected = [candidate, _candidate(document_id=11), _candidate(document_id=12)]
    result = await expand_v3_evidence(
        "Thành viên phải thực hiện nghĩa vụ gì và trong thời gian bao lâu?",
        [candidate],
        selected,
        settings=SimpleNamespace(QUERY_CHUNK_MAX_TOKENS=220, QUERY_CHUNK_OVERLAP_TOKENS=24),
        max_documents=3,
        document_loader=load_many,
    )

    assert reads == [[10]]
    assert result.status == "expanded"
    assert any(item.article == "Điều 164" and item.clause == "3" for item in result.selected_evidence)
    assert len(result.selected_evidence) == 3
    assert result.diagnostics["documents_expanded"] == 1


@pytest.mark.asyncio
async def test_duration_query_does_not_stop_at_unrelated_selected_deadline() -> None:
    from app.services.v3_article_expansion import expand_v3_evidence

    content = (
        "Điều 10. Báo cáo hồ sơ\n"
        "1. Người nộp hồ sơ hoàn thành việc báo cáo trong 30 ngày.\n"
        "Điều 164. Nghĩa vụ thành viên Hội đồng quản trị\n"
        "1. Thành viên Hội đồng quản trị thực hiện nghĩa vụ với công ty.\n"
        "3. Thành viên Hội đồng quản trị phải kê khai lợi ích liên quan của doanh nghiệp mà mình sở hữu trong 07 ngày làm việc.\n"
        "5. Thành viên chịu trách nhiệm theo quy định.\n"
    )
    source = _stored_document(content=content)
    source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    unrelated_deadline = replace(
        _candidate(article="Điều 10", clause="1", source_hash=source_hash),
        text="Người nộp hồ sơ hoàn thành việc báo cáo trong 30 ngày.",
    )
    target_article = _candidate(
        article="Điều 164",
        clause="5",
        source_hash=source_hash,
    )
    result = await expand_v3_evidence(
        "Thành viên Hội đồng quản trị sở hữu doanh nghiệp phải kê khai lợi ích liên quan và trong thời gian bao lâu?",
        [unrelated_deadline, target_article],
        [unrelated_deadline],
        settings=SimpleNamespace(QUERY_CHUNK_MAX_TOKENS=220, QUERY_CHUNK_OVERLAP_TOKENS=24),
        max_documents=3,
        document_loader=lambda ids: {10: source} if ids == [10] else {},
    )

    assert result.status == "expanded"
    assert result.added_evidence[0].article == "Điều 164"
    assert result.added_evidence[0].clause == "3"


@pytest.mark.asyncio
async def test_non_temporal_query_does_not_read_full_documents() -> None:
    from app.services.v3_article_expansion import expand_v3_evidence

    def unexpected_read(_document_ids: list[int]):
        raise AssertionError("full document store should not be read")

    candidate = _candidate()
    selected = [candidate]
    result = await expand_v3_evidence(
        "What are the general responsibilities of a member?",
        [candidate],
        selected,
        settings=SimpleNamespace(QUERY_CHUNK_MAX_TOKENS=220, QUERY_CHUNK_OVERLAP_TOKENS=24),
        max_documents=3,
        document_loader=unexpected_read,
    )

    assert result.status == "not_needed"
    assert result.selected_evidence == selected


@pytest.mark.asyncio
async def test_explicit_clause_reference_recovers_exact_sibling() -> None:
    from app.services.v3_article_expansion import expand_v3_evidence

    candidate = _candidate()
    result = await expand_v3_evidence(
        "Theo Khoản 3 Điều 164, thành viên phải làm gì?",
        [candidate],
        [candidate],
        settings=SimpleNamespace(QUERY_CHUNK_MAX_TOKENS=220, QUERY_CHUNK_OVERLAP_TOKENS=24),
        max_documents=3,
        document_loader=lambda ids: {10: _stored_document()} if ids == [10] else {},
    )

    assert result.status == "expanded"
    assert result.selected_evidence[0].article == "Điều 164"
    assert result.selected_evidence[0].clause == "3"


@pytest.mark.asyncio
async def test_explicit_article_without_candidate_match_skips_source_read() -> None:
    from app.services.v3_article_expansion import expand_v3_evidence

    candidate = _candidate(article="Điều 165", clause="1")

    def unexpected_read(_document_ids: list[int]):
        raise AssertionError("unanchored article must not trigger source reads")

    result = await expand_v3_evidence(
        "Theo Khoản 3 Điều 164, thành viên phải làm gì?",
        [candidate],
        [candidate],
        settings=SimpleNamespace(QUERY_CHUNK_MAX_TOKENS=220, QUERY_CHUNK_OVERLAP_TOKENS=24),
        max_documents=3,
        document_loader=unexpected_read,
    )

    assert result.status == "not_found"
    assert result.selected_evidence == [candidate]
    assert result.diagnostics["status"] == "no_matching_candidate_article"


@pytest.mark.asyncio
async def test_source_hash_mismatch_keeps_original_and_reports_type_only() -> None:
    from app.services.v3_article_expansion import expand_v3_evidence

    candidate = _candidate()
    selected = [candidate]
    mismatched = _stored_document(digest="0" * 64)
    result = await expand_v3_evidence(
        "Trong thời gian bao lâu?",
        [candidate],
        selected,
        settings=SimpleNamespace(QUERY_CHUNK_MAX_TOKENS=220, QUERY_CHUNK_OVERLAP_TOKENS=24),
        max_documents=3,
        document_loader=lambda _ids: {10: mismatched},
    )

    assert result.status == "integrity_error"
    assert result.selected_evidence == selected
    assert result.diagnostics["error_type"] == "SourceContentHashMismatch"
    assert "07 ngày làm việc" not in str(result.diagnostics)


@pytest.mark.asyncio
async def test_missing_hash_on_any_candidate_rejects_document_expansion() -> None:
    from app.services.v3_article_expansion import expand_v3_evidence

    valid_candidate = _candidate(clause="5")
    unhashed_candidate = replace(
        valid_candidate,
        clause="4",
        source_content_sha256=None,
    )
    selected = [valid_candidate]
    result = await expand_v3_evidence(
        "Trong thời gian bao lâu?",
        [valid_candidate, unhashed_candidate],
        selected,
        settings=SimpleNamespace(QUERY_CHUNK_MAX_TOKENS=220, QUERY_CHUNK_OVERLAP_TOKENS=24),
        max_documents=3,
        document_loader=lambda _ids: {10: _stored_document()},
    )

    assert result.status == "integrity_error"
    assert result.selected_evidence == selected
    assert result.diagnostics["error_type"] == "SourceContentHashMissing"


@pytest.mark.asyncio
async def test_zero_evidence_limit_skips_full_document_read() -> None:
    from app.services.v3_article_expansion import expand_v3_evidence

    candidate = _candidate()

    def unexpected_read(_document_ids: list[int]):
        raise AssertionError("zero evidence limit should skip source reads")

    result = await expand_v3_evidence(
        "Theo Khoản 3 Điều 164, cần làm gì?",
        [candidate],
        [candidate],
        settings=SimpleNamespace(QUERY_CHUNK_MAX_TOKENS=220, QUERY_CHUNK_OVERLAP_TOKENS=24),
        max_documents=3,
        max_evidence=0,
        document_loader=unexpected_read,
    )

    assert result.status == "not_needed"
    assert result.selected_evidence == [candidate]
    assert result.diagnostics["status"] == "zero_evidence_limit"


@pytest.mark.asyncio
async def test_source_exception_keeps_original_and_bounds_document_reads() -> None:
    from app.services.v3_article_expansion import expand_v3_evidence

    ids: list[int] = []
    candidates = [
        _candidate(10),
        _candidate(11),
        _candidate(12),
        _candidate(13),
    ]
    selected = candidates[:3]

    def fail_after_recording(document_ids: list[int]):
        ids.extend(document_ids)
        raise TimeoutError("source read failed")

    result = await expand_v3_evidence(
        "Trong thời gian bao lâu?",
        candidates,
        selected,
        settings=SimpleNamespace(QUERY_CHUNK_MAX_TOKENS=220, QUERY_CHUNK_OVERLAP_TOKENS=24),
        max_documents=2,
        document_loader=fail_after_recording,
    )

    assert ids == [10, 11]
    assert result.status == "unavailable"
    assert result.selected_evidence == selected
    assert result.diagnostics["error_type"] == "TimeoutError"
    assert "source read failed" not in str(result.diagnostics)
