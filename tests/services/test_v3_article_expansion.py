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


def _trial_period_content() -> str:
    return (
        "Điều 25. Thời gian thử việc\n"
        "1. Thời gian thử việc do hai bên thỏa thuận nhưng không quá 180 ngày "
        "đối với công việc quản lý doanh nghiệp.\n"
        "2. Không quá 60 ngày đối với công việc cần trình độ cao đẳng trở lên.\n"
        "3. Không quá 30 ngày đối với công việc cần trình độ trung cấp.\n"
        "4. Không quá 06 ngày làm việc đối với công việc khác.\n"
        "Điều 90. Tiền lương\n"
        "1. Tiền lương là số tiền người sử dụng lao động trả cho người lao động.\n"
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


def test_source_loader_uses_supabase_when_local_corpus_is_missing(
    monkeypatch, tmp_path
) -> None:
    from app.services import legal_browser, v3_article_expansion

    missing_content = tmp_path / "missing" / "content.sqlite3"
    missing_fts = tmp_path / "missing" / "fts.sqlite3"
    settings = SimpleNamespace(
        APP_ENV="development",
        SERVERLESS_ONLINE_ONLY=False,
        USE_LEGACY_FREE_PIPELINE=False,
        CONTENT_STORE_PATH=tmp_path / "full" / "content.sqlite3",
        LEGAL_FTS_PATH=tmp_path / "full" / "fts.sqlite3",
        V3_CONTENT_STORE_PATH=missing_content,
        V3_LEGAL_FTS_PATH=missing_fts,
        SUPABASE_URL="https://project.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="public-test-key",
    )
    document = _stored_document()

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class Store:
        def __init__(self, **kwargs):
            assert kwargs["url"] == settings.SUPABASE_URL

        def get_many(self, document_ids):
            assert document_ids == [10]
            return {10: document}

    monkeypatch.setattr(v3_article_expansion.httpx, "Client", lambda **_kwargs: Client())
    monkeypatch.setattr(legal_browser, "SupabaseLegalStore", Store)

    loaded = v3_article_expansion._load_source_documents(settings, [10])

    assert loaded == {10: document}
    assert not missing_content.exists()
    assert not missing_fts.exists()


def test_source_loader_uses_ready_v3_local_store(
    monkeypatch, tmp_path
) -> None:
    from pathlib import Path

    from app.services import legal_browser, v3_article_expansion

    default_content = tmp_path / "full" / "content.sqlite3"
    default_fts = tmp_path / "full" / "fts.sqlite3"
    v3_content = tmp_path / "v3" / "content.sqlite3"
    v3_fts = tmp_path / "v3" / "fts.sqlite3"
    for path in (v3_content, v3_fts):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    settings = SimpleNamespace(
        APP_ENV="development",
        SERVERLESS_ONLINE_ONLY=False,
        USE_LEGACY_FREE_PIPELINE=False,
        CONTENT_STORE_PATH=default_content,
        LEGAL_FTS_PATH=default_fts,
        V3_CONTENT_STORE_PATH=v3_content,
        V3_LEGAL_FTS_PATH=v3_fts,
        DATASET_REVISION="pinned-revision",
        SUPABASE_URL="https://project.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="public-test-key",
    )
    document = _stored_document()
    opened_paths: list[Path] = []

    class BrowserContentStore:
        def __init__(self, path):
            self.path = Path(path)

    class ReadyV3Index:
        def __init__(self, *, store, path, dataset_revision):
            self.store = store
            self.path = Path(path)
            self.dataset_revision = dataset_revision

        def is_ready(self):
            return self.path == v3_fts

    class SourceContentStore:
        def __init__(self, path):
            opened_paths.append(Path(path))

        def get_many(self, document_ids):
            assert document_ids == [10]
            return {10: document}

    monkeypatch.setattr(legal_browser, "ContentStore", BrowserContentStore)
    monkeypatch.setattr(legal_browser, "LegalFtsIndex", ReadyV3Index)
    monkeypatch.setattr(v3_article_expansion, "ContentStore", SourceContentStore)

    loaded = v3_article_expansion._load_source_documents(settings, [10])

    assert loaded == {10: document}
    assert opened_paths == [v3_content]


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
async def test_duration_question_prefers_numeric_sibling_to_local_topic_clause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import v3_article_expansion

    monkeypatch.setattr(
        v3_article_expansion,
        "select_rerank_candidates",
        lambda _query, candidates, **_kwargs: list(candidates),
    )
    content = (
        "Điều 25. Thời gian thử việc\n"
        "1. Thời gian thử việc do hai bên thỏa thuận theo tính chất công việc.\n"
        "2. Thời gian thử việc tối đa là 30 ngày.\n"
    )
    source = _stored_document(content=content)
    source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    candidate = replace(
        _candidate(article="Điều 25", clause="1", source_hash=source_hash),
        text="Thời gian thử việc do hai bên thỏa thuận.",
    )

    result = await v3_article_expansion.expand_v3_evidence(
        "Thời gian thử việc tối đa bao lâu?",
        [candidate],
        [candidate],
        settings=SimpleNamespace(
            QUERY_CHUNK_MAX_TOKENS=220,
            QUERY_CHUNK_OVERLAP_TOKENS=24,
        ),
        max_documents=3,
        document_loader=lambda ids: {10: source} if ids == [10] else {},
    )

    assert result.status == "expanded", result.diagnostics
    assert result.added_evidence[0].clause == "2"
    assert "30 ngày" in result.added_evidence[0].text


@pytest.mark.asyncio
async def test_duration_query_rescues_numeric_topic_from_another_article_in_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import v3_article_expansion

    monkeypatch.setattr(
        v3_article_expansion,
        "select_rerank_candidates",
        lambda _query, candidates, **_kwargs: sorted(
            candidates,
            key=lambda chunk: chunk.article == "Điều 26",
            reverse=True,
        ),
    )
    content = (
        "Điều 25. Thời gian thử việc\n"
        "1. Thời gian thử việc tối đa là 30 ngày.\n"
        "Điều 26. Thỏa thuận thử việc\n"
        "1. Thời gian thử việc do hai bên thỏa thuận theo tính chất công việc.\n"
        "Điều 90. Tiền lương\n"
        "1. Tiền lương là số tiền người sử dụng lao động trả cho người lao động.\n"
    )
    source = _stored_document(content=content)
    source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    wrong_article = replace(
        _candidate(article="Điều 90", clause="1", source_hash=source_hash),
        text="Tiền lương là số tiền người sử dụng lao động trả cho người lao động.",
    )

    result = await v3_article_expansion.expand_v3_evidence(
        "Thời gian thử việc tối đa bao lâu?",
        [wrong_article],
        [wrong_article],
        settings=SimpleNamespace(
            QUERY_CHUNK_MAX_TOKENS=220,
            QUERY_CHUNK_OVERLAP_TOKENS=24,
        ),
        max_documents=3,
        document_loader=lambda ids: {10: source} if ids == [10] else {},
    )

    assert result.status == "expanded", result.diagnostics
    assert result.added_evidence[0].article == "Điều 25"
    assert "30 ngày" in result.added_evidence[0].text


@pytest.mark.asyncio
async def test_duration_rescue_combines_all_matching_categories_within_context_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import v3_article_expansion

    monkeypatch.setattr(
        v3_article_expansion,
        "select_rerank_candidates",
        lambda _query, candidates, **_kwargs: list(candidates),
    )
    content = _trial_period_content()
    source = _stored_document(content=content)
    source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    wrong_article = replace(
        _candidate(article="Điều 90", clause="1", source_hash=source_hash),
        text="Tiền lương là số tiền người sử dụng lao động trả cho người lao động.",
    )
    selected = [wrong_article, _candidate(document_id=11), _candidate(document_id=12)]

    result = await v3_article_expansion.expand_v3_evidence(
        "Thời gian thử việc tối đa bao lâu?",
        [wrong_article],
        selected,
        settings=SimpleNamespace(
            QUERY_CHUNK_MAX_TOKENS=220,
            QUERY_CHUNK_OVERLAP_TOKENS=24,
        ),
        max_documents=3,
        max_evidence=3,
        document_loader=lambda ids: {10: source} if ids == [10] else {},
    )

    assert result.status == "expanded", result.diagnostics
    assert len(result.selected_evidence) <= 3
    assert sum(item.token_count for item in result.selected_evidence) <= 720
    added = result.added_evidence[0]
    assert added.article == "Điều 25"
    assert added.clause is None
    assert all(
        duration in added.text
        for duration in ("180 ngày", "60 ngày", "30 ngày", "06 ngày làm việc")
    )
    assert result.diagnostics["duration_group_complete"] is True
    assert result.diagnostics["duration_group_chunks_omitted"] == 0


@pytest.mark.asyncio
async def test_duration_rescue_expands_a_partially_selected_duration_article(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import v3_article_expansion

    monkeypatch.setattr(
        v3_article_expansion,
        "select_rerank_candidates",
        lambda _query, candidates, **_kwargs: list(candidates),
    )
    content = _trial_period_content()
    source = _stored_document(content=content)
    source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    selected_duration = replace(
        _candidate(
            article="Điều 25",
            clause="1",
            source_hash=source_hash,
        ),
        text="Thời gian thử việc do hai bên thỏa thuận nhưng không quá 180 ngày.",
    )

    result = await v3_article_expansion.expand_v3_evidence(
        "Thời gian thử việc tối đa bao lâu?",
        [selected_duration],
        [selected_duration],
        settings=SimpleNamespace(
            QUERY_CHUNK_MAX_TOKENS=220,
            QUERY_CHUNK_OVERLAP_TOKENS=24,
        ),
        max_documents=3,
        max_evidence=3,
        document_loader=lambda ids: {10: source} if ids == [10] else {},
    )

    assert result.status == "expanded", result.diagnostics
    assert len(result.selected_evidence) == 1
    assert all(
        duration in result.selected_evidence[0].text
        for duration in ("180 ngày", "60 ngày", "30 ngày", "06 ngày làm việc")
    )


@pytest.mark.asyncio
async def test_duration_rescue_reports_incomplete_when_group_exceeds_chunk_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import v3_article_expansion

    monkeypatch.setattr(
        v3_article_expansion,
        "select_rerank_candidates",
        lambda _query, candidates, **_kwargs: list(candidates),
    )
    repeated_context = "người lao động thực hiện nhiệm vụ " * 40
    content = (
        "Điều 25. Thời gian thử việc\n"
        "1. Thời gian thử việc tối đa là 180 ngày đối với công việc quản lý. "
        f"{repeated_context}\n"
        "2. Thời gian thử việc tối đa là 60 ngày đối với công việc chuyên môn. "
        f"{repeated_context}\n"
        "Điều 90. Tiền lương\n"
        "1. Tiền lương là số tiền người sử dụng lao động trả cho người lao động.\n"
    )
    source = _stored_document(content=content)
    source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    wrong_article = replace(
        _candidate(article="Điều 90", clause="1", source_hash=source_hash),
        text="Tiền lương là số tiền người sử dụng lao động trả cho người lao động.",
    )

    result = await v3_article_expansion.expand_v3_evidence(
        "Thời gian thử việc tối đa bao lâu?",
        [wrong_article],
        [wrong_article],
        settings=SimpleNamespace(
            QUERY_CHUNK_MAX_TOKENS=220,
            QUERY_CHUNK_OVERLAP_TOKENS=24,
        ),
        max_documents=3,
        max_evidence=3,
        document_loader=lambda ids: {10: source} if ids == [10] else {},
    )

    assert result.status == "expanded", result.diagnostics
    assert result.diagnostics["duration_group_complete"] is False
    assert result.diagnostics["duration_group_chunks_found"] == 2
    assert result.diagnostics["duration_group_chunks_omitted"] == 1


@pytest.mark.asyncio
async def test_trial_pay_query_recovers_relevant_clause_from_same_document() -> None:
    from app.services.v3_article_expansion import expand_v3_evidence

    content = (
        "Điều 25. Thời gian thử việc\n"
        "1. Thời gian thử việc do các bên thỏa thuận theo quy định.\n"
        "Điều 26. Tiền lương trong thời gian thử việc\n"
        "1. Tiền lương của người lao động trong thời gian thử việc do hai bên thỏa thuận.\n"
        "2. Mức lương thử việc ít nhất bằng 85% mức lương của công việc đó.\n"
        "Điều 90. Tiền lương\n"
        "1. Tiền lương là số tiền người sử dụng lao động trả cho người lao động.\n"
    )
    source = _stored_document(content=content)
    source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    candidate = _candidate(article="Điều 90", clause="1", source_hash=source_hash)
    candidate = replace(candidate, text="Tiền lương là số tiền người sử dụng lao động trả cho người lao động.")

    result = await expand_v3_evidence(
        "Tôi nhận lương công việc 12 triệu; công ty trả 70% trong hai tháng thử việc có đúng không?",
        [candidate],
        [candidate],
        settings=SimpleNamespace(QUERY_CHUNK_MAX_TOKENS=220, QUERY_CHUNK_OVERLAP_TOKENS=24),
        max_documents=3,
        document_loader=lambda ids: {10: source} if ids == [10] else {},
    )

    assert result.status == "expanded", result.diagnostics
    assert result.added_evidence[0].article == "Điều 26"
    assert "85%" in result.added_evidence[0].text


@pytest.mark.asyncio
async def test_trial_pay_rescue_ignores_nondecisive_missing_modifier() -> None:
    from app.services.v3_article_expansion import expand_v3_evidence

    content = (
        "Điều 3. Giải thích từ ngữ\n"
        "1. Mức lương thử việc là khoản tiền người sử dụng lao động trả cho công việc.\n"
        "Điều 26. Tiền lương trong thời gian thử việc\n"
        "1. Tiền lương trong thời gian thử việc do hai bên thỏa thuận, nhưng ít nhất bằng 85% tiền lương của công việc đó.\n"
    )
    source = _stored_document(content=content)
    source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    candidate = replace(
        _candidate(article="Điều 90", clause="1", source_hash=source_hash),
        text="Tiền lương là số tiền người sử dụng lao động trả cho người lao động.",
    )

    result = await expand_v3_evidence(
        "Mức lương trong hai tháng thử việc, công ty chỉ trả 70% tiền lương công việc, đúng không?",
        [candidate],
        [candidate],
        settings=SimpleNamespace(
            QUERY_CHUNK_MAX_TOKENS=220,
            QUERY_CHUNK_OVERLAP_TOKENS=24,
        ),
        max_documents=3,
        document_loader=lambda ids: {10: source} if ids == [10] else {},
    )

    assert result.status == "expanded", result.diagnostics
    assert result.added_evidence[0].article == "Điều 26"
    assert "85%" in result.added_evidence[0].text


@pytest.mark.asyncio
async def test_trial_pay_rescue_prefers_full_topic_over_unrelated_wage_clause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import v3_article_expansion

    monkeypatch.setattr(
        v3_article_expansion,
        "select_rerank_candidates",
        lambda _query, candidates, **_kwargs: sorted(
            candidates, key=lambda chunk: chunk.article == "Điều 41", reverse=True
        ),
    )

    content = (
        "Điều 26. Tiền lương thử việc\n"
        "Tiền lương của người lao động trong thời gian thử việc do hai bên thỏa thuận "
        "nhưng ít nhất phải bằng 85% mức lương của công việc đó.\n"
        "Điều 41. Nghĩa vụ khi đơn phương chấm dứt hợp đồng trái pháp luật\n"
        "1. Phải nhận người lao động trở lại làm việc và trả tiền lương, "
        "thêm ít nhất 02 tháng tiền lương theo hợp đồng lao động.\n"
        "Điều 90. Tiền lương\n"
        "1. Tiền lương là số tiền người sử dụng lao động trả cho người lao động.\n"
    )
    source = _stored_document(content=content)
    source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    candidate = replace(
        _candidate(article="Điều 90", clause="1", source_hash=source_hash),
        text="Tiền lương là số tiền người sử dụng lao động trả cho người lao động.",
    )
    result = await v3_article_expansion.expand_v3_evidence(
        "Công ty trả tôi 70% lương của công việc khi thử việc hai tháng, "
        "lương chính thức 12 triệu đồng mỗi tháng. Như vậy có đúng không?",
        [candidate],
        [candidate],
        settings=SimpleNamespace(QUERY_CHUNK_MAX_TOKENS=220, QUERY_CHUNK_OVERLAP_TOKENS=24),
        max_documents=3,
        document_loader=lambda ids: {10: source} if ids == [10] else {},
    )
    assert result.status == "expanded", result.diagnostics
    assert result.added_evidence[0].article == "Điều 26"
    assert "85%" in result.added_evidence[0].text


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
async def test_explicit_clause_wins_over_local_topic_rescue() -> None:
    from app.services.v3_article_expansion import expand_v3_evidence

    content = (
        "Điều 164. Thử việc\n"
        "1. Thời gian thử việc do các bên thỏa thuận.\n"
        "2. Người lao động nhận lương trong thời gian thử việc.\n"
        "3. Thời hạn thanh toán tiền lương thử việc là 07 ngày.\n"
    )
    source = _stored_document(content=content)
    source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    candidate = replace(
        _candidate(source_hash=source_hash),
        clause="2",
        text="Người lao động nhận lương trong thời gian thử việc.",
    )

    result = await expand_v3_evidence(
        "Theo Khoản 3 Điều 164, thời hạn trả lương thử việc là bao lâu?",
        [candidate],
        [candidate],
        settings=SimpleNamespace(
            QUERY_CHUNK_MAX_TOKENS=220,
            QUERY_CHUNK_OVERLAP_TOKENS=24,
        ),
        max_documents=3,
        document_loader=lambda ids: {10: source} if ids == [10] else {},
    )

    assert result.status == "expanded", result.diagnostics
    assert result.added_evidence[0].clause == "3"
    assert "07 ngày" in result.added_evidence[0].text


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


@pytest.mark.asyncio
async def test_source_load_timeout_keeps_original_and_reports_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from threading import Event

    from app.services import v3_article_expansion

    monkeypatch.setattr(
        v3_article_expansion,
        "_SOURCE_DOCUMENT_LOAD_TIMEOUT_SECONDS",
        0.01,
        raising=False,
    )
    candidate = _candidate()
    selected = [candidate]

    def stalled_loader(_document_ids: list[int]):
        Event().wait(0.1)
        return {10: _stored_document()}

    result = await v3_article_expansion.expand_v3_evidence(
        "Theo Khoản 3 Điều 164, thành viên phải làm gì?",
        [candidate],
        selected,
        settings=SimpleNamespace(
            QUERY_CHUNK_MAX_TOKENS=220,
            QUERY_CHUNK_OVERLAP_TOKENS=24,
        ),
        max_documents=3,
        document_loader=stalled_loader,
    )

    assert result.status == "unavailable"
    assert result.selected_evidence == selected
    assert result.diagnostics["error_type"] == "SourceDocumentLoadTimeout"
    assert result.diagnostics["documents_requested"] == 1
