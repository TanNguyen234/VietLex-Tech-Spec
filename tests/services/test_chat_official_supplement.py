from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest


class EmptyCorpusBrowser:
    def search(self, *_args, **_kwargs):
        return []

    def get_document(self, *_args, **_kwargs):
        pytest.fail("no corpus match should be loaded")


def test_search_topics_drop_names_and_numbers_from_natural_question() -> None:
    from app.services.chat_official_supplement import derive_official_search_queries

    queries = derive_official_search_queries(
        "Tôi là Nguyễn Văn Bình, lương 12 triệu; công ty trả 70% trong hai tháng thử việc có đúng không?"
    )

    assert queries == ("lương thử việc",)
    assert all("12" not in query and "70" not in query for query in queries)
    assert all("Nguyễn" not in query and "Bình" not in query for query in queries)


def test_separate_contexts_cannot_combine_to_claim_topic_coverage() -> None:
    from app.services.chat_official_supplement import corpus_evidence_covers_topic

    assert not corpus_evidence_covers_topic(
        "Hỏi về lương thử việc",
        ["Quy định mức lương tối thiểu.", "Thử việc theo hợp đồng lao động."],
    )


def test_evidence_must_cover_each_distinct_legal_topic() -> None:
    from app.services.chat_official_supplement import corpus_evidence_covers_topic

    assert not corpus_evidence_covers_topic(
        "lương thử việc và bảo hiểm xã hội",
        ["Quy định về lương trong thời gian thử việc."],
    )


def test_temporal_update_question_preserves_safe_search_specificity() -> None:
    from app.services.chat_official_supplement import (
        corpus_evidence_covers_topic,
        derive_official_search_queries,
    )

    query = (
        "Tôi tên Nguyễn Văn Bình, lương 12 triệu; điều kiện nhập phế liệu "
        "theo sửa đổi năm 2025 hiện nay là gì?"
    )
    queries = derive_official_search_queries(query)

    assert queries == ("nhập phế liệu sửa đổi 2025 hiện nay",)
    assert "Nguyễn" not in str(queries)
    assert "12" not in str(queries)
    assert not corpus_evidence_covers_topic(
        query,
        ["Quy định về nhập phế liệu theo văn bản ban hành từ năm 2012."],
    )


def test_temporal_search_does_not_forward_unrelated_personal_year() -> None:
    from app.services.chat_official_supplement import derive_official_search_queries

    queries = derive_official_search_queries(
        "Tôi sinh năm 1990 và lương thử việc hiện nay tính thế nào?"
    )

    assert queries == ("lương thử việc hiện nay",)
    assert all("1990" not in query for query in queries)
    assert derive_official_search_queries(
        "Tôi sinh năm 1990 và lương thử việc theo sửa đổi năm 2025 hiện nay thế nào?"
    ) == ("lương thử việc sửa đổi 2025 hiện nay",)


def test_temporal_search_retains_a_separate_non_temporal_topic_question() -> None:
    from app.services.chat_official_supplement import derive_official_search_queries

    queries = derive_official_search_queries(
        "Thử việc quy định thế nào? Bảo hiểm xã hội hiện nay ra sao?"
    )

    assert queries == ("thử việc bảo hiểm xã hội hiện nay",)
    assert len(queries) <= 2


def test_generic_current_rule_question_keeps_subject_from_preceding_clause() -> None:
    from app.services.chat_official_supplement import derive_official_search_queries

    queries = derive_official_search_queries(
        "Tôi muốn nhập khẩu phế liệu làm nguyên liệu sản xuất. "
        "Theo quy định hiện nay, doanh nghiệp cần đáp ứng điều kiện gì "
        "và có phải xin giấy phép môi trường không?"
    )

    assert queries == (
        "nhập khẩu phế liệu giấy phép môi trường hiện nay",
    )


@pytest.mark.parametrize(
    "query",
    (
        "Quy định thử việc còn áp dụng không?",
        "Quy định thử việc đang áp dụng thế nào?",
        "Quy định thử việc vẫn áp dụng không?",
    ),
)
def test_application_tense_cues_are_time_sensitive(query: str) -> None:
    from app.services.chat_official_supplement import _current_applicability_intent

    assert _current_applicability_intent(query)


def test_natural_scrap_query_keeps_the_import_action() -> None:
    from app.services.chat_official_supplement import derive_official_search_queries

    assert derive_official_search_queries(
        "Quy định mới nhất khi nhập phế liệu là gì?"
    ) == ("nhập phế liệu mới nhất",)


@pytest.mark.asyncio
async def test_numberless_applicability_query_discovers_update_to_corpus_law() -> None:
    from app.services.chat_official_supplement import (
        corpus_evidence_covers_topic,
        derive_official_search_queries,
        supplement_official_evidence,
    )

    query = (
        "Tôi tên Nguyễn Văn Bình; xưởng của tôi nhập phế liệu từ nước ngoài. "
        "Tôi có cần xin giấy phép môi trường trước khi hoạt động không?"
    )
    corpus_contexts = [
        "[72/2020/QH14, Điều 53]\n"
        "Nguồn: https://example.gov.vn/law\n"
        "Tiêu đề: Luật Bảo vệ môi trường\n"
        "Quy định về nhập phế liệu từ nước ngoài."
    ]

    queries = derive_official_search_queries(query, corpus_contexts=corpus_contexts)

    assert queries == (
        "nhập phế liệu giấy phép môi trường",
        "sửa đổi Luật Bảo vệ môi trường",
    )
    assert "Nguyễn" not in str(queries)
    assert "xưởng" not in str(queries)
    assert not corpus_evidence_covers_topic(query, corpus_contexts)

    seen_searches: list[tuple[str, int]] = []

    class Provider:
        async def search(self, search_query: str, *, limit: int = 3):
            seen_searches.append((search_query, limit))
            return SimpleNamespace(results=(), errors=())

    result = await supplement_official_evidence(
        query,
        corpus_contexts=corpus_contexts,
        settings=SimpleNamespace(
            CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED=True,
            CHAT_OFFICIAL_WEB_SUPPLEMENT_TIMEOUT_SECONDS=8.0,
            OFFICIAL_WEB_RESEARCH_ENABLED=True,
        ),
        provider=Provider(),
        reader=lambda *_args, **_kwargs: None,
    )

    assert seen_searches == [(item, 3) for item in queries]
    assert result.diagnostics["search_queries"] == 2
    assert result.status == "no_search_results"


@pytest.mark.asyncio
async def test_default_chat_search_keeps_gazette_result_when_portal_is_slow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from app.services import congbao_search, official_web_search
    from app.services.chat_official_supplement import supplement_official_evidence
    from app.services.official_web_search import OfficialSearchRecord, OfficialSearchResponse

    gazette_url = "https://congbao.chinhphu.vn/van-ban/thu-viec.htm"
    gazette_record = OfficialSearchRecord(
        gazette_url,
        "Tiền lương trong thời gian thử việc",
        "congbao.chinhphu.vn",
        "Mức lương trong thời gian thử việc.",
        "",
        "",
    )

    class SlowPortal:
        async def search(self, _query: str, *, limit: int = 3):
            await asyncio.sleep(3.0)
            return OfficialSearchResponse((), "chinhphu", 3.0, 1)

    class DelayedGazette:
        async def search(self, _query: str, *, limit: int = 3):
            await asyncio.sleep(2.15)
            return OfficialSearchResponse((gazette_record,), "congbao", 2.15, 1)

    monkeypatch.setattr(
        official_web_search,
        "OfficialPortalClient",
        lambda *, settings: SlowPortal(),
    )
    monkeypatch.setattr(
        congbao_search,
        "CongBaoClient",
        lambda *, settings: DelayedGazette(),
    )

    async def reader(url: str, *, use_ocr: bool, page_limit: int):
        assert url == gazette_url
        assert use_ocr is False
        assert page_limit <= 5
        return {
            "text": "Điều 26. Tiền lương trong thời gian thử việc.",
            "sha256": "a" * 64,
            "retrieved_at": "2026-10-15T10:00:00+00:00",
            "method": "visible_html_text",
            "title": gazette_record.title,
        }

    result = await supplement_official_evidence(
        "Công ty trả tôi 70% lương trong thời gian thử việc đúng không?",
        settings=SimpleNamespace(
            CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED=True,
            CHAT_OFFICIAL_WEB_SUPPLEMENT_TIMEOUT_SECONDS=8.0,
            OFFICIAL_WEB_RESEARCH_ENABLED=True,
        ),
        reader=reader,
        browser=EmptyCorpusBrowser(),
    )

    assert result.status == "ok", result.diagnostics
    assert result.latency_seconds < 8.0
    assert len(result.contexts) == 1
    assert gazette_url in result.contexts[0]
    assert result.diagnostics["partial_search_errors"] == 1


def test_non_applicability_question_does_not_search_for_law_update() -> None:
    from app.services.chat_official_supplement import (
        corpus_evidence_covers_topic,
        derive_official_search_queries,
    )

    query = "Xưởng đang tìm hiểu quy trình nhập phế liệu từ nước ngoài gồm bước nào?"
    corpus_contexts = [
        "[72/2020/QH14, Điều 53]\n"
        "Nguồn: https://example.gov.vn/law\n"
        "Tiêu đề: Luật Bảo vệ môi trường\n"
        "Quy trình nhập phế liệu từ nước ngoài."
    ]

    assert derive_official_search_queries(query, corpus_contexts=corpus_contexts) == (
        "nhập phế liệu",
    )
    assert corpus_evidence_covers_topic(query, corpus_contexts)


def test_topical_headers_do_not_count_as_corpus_evidence_body() -> None:
    from app.services.chat_official_supplement import corpus_evidence_covers_topic

    context = (
        "[72/2020/QH14, Điều 53]\n"
        "Nguồn: https://example.gov.vn/law\n"
        "Tiêu đề: Quy định nhập phế liệu\n"
        "Điều kiện kinh doanh được quy định tại điều này."
    )

    assert not corpus_evidence_covers_topic("Quy định nhập phế liệu gồm những bước nào?", [context])


def test_unknown_topic_cannot_claim_current_law_coverage() -> None:
    from app.services.chat_official_supplement import corpus_evidence_covers_topic

    context = "[Văn bản]\nNguồn: https://example.invalid/1\nTiêu đề: Quy chế nội bộ\nNội dung cũ."
    assert not corpus_evidence_covers_topic("Quy định này còn áp dụng không?", [context])


def test_import_text_does_not_cover_environmental_permit_question() -> None:
    from app.services.chat_official_supplement import evidence_covers_recognized_topics

    source = "[Luật]\nNguồn: https://example.invalid/1\nTiêu đề: Đầu tư\nQuy định nhập khẩu phế liệu."
    query = "Nhập khẩu phế liệu hiện nay có cần giấy phép môi trường không?"
    assert not evidence_covers_recognized_topics(query, [source])


@pytest.mark.parametrize("suffix", ["2020", "năm 2020"])
def test_update_discovery_does_not_require_base_law_version_year(suffix: str) -> None:
    from app.services.chat_official_supplement import derive_official_search_queries

    context = (
        "[72/2020/QH14, Điều 39]\nNguồn: https://example.invalid/1\n"
        f"Tiêu đề: Luật Bảo vệ môi trường {suffix}\nQuy định về nhập phế liệu."
    )
    queries = derive_official_search_queries(
        "Nhập phế liệu hiện nay có cần giấy phép môi trường không?",
        corpus_contexts=[context],
    )
    assert queries[-1] == "hiện nay Luật Bảo vệ môi trường"


def test_unrelated_clauses_keep_separate_safe_search_queries() -> None:
    from app.services.chat_official_supplement import derive_official_search_queries

    assert derive_official_search_queries(
        "Lương 12 triệu; điều kiện nhập phế liệu sau sửa đổi năm 2025 hiện nay?"
    ) == ("nhập phế liệu sửa đổi 2025 hiện nay",)


def test_temporal_query_adds_only_the_retrieved_law_title() -> None:
    from app.services.chat_official_supplement import derive_official_search_queries

    query = "Tôi là Nguyễn Văn Bình. Điều kiện nhập phế liệu sau sửa đổi năm 2025?"
    contexts = [
        "[72/2020/QH14, Điều 53]\n"
        "Nguồn: https://example.gov.vn/law\n"
        "Tiêu đề: Luật Bảo vệ môi trường\n"
        "Tiêu đề: Nguyễn Văn Bình\n"
        "Quy định về nhập phế liệu."
    ]

    queries = derive_official_search_queries(query, corpus_contexts=contexts)

    assert queries == (
        "nhập phế liệu sửa đổi 2025",
        "sửa đổi 2025 Luật Bảo vệ môi trường",
    )
    assert all("Nguyễn" not in item and "Bình" not in item for item in queries)


def test_older_official_source_keeps_legal_effect_unverified() -> None:
    from app.services.chat_official_supplement import (
        _source_context,
        derive_official_search_queries,
    )
    from app.services.evidence_presenter import present_context

    query = derive_official_search_queries(
        "Điều kiện nhập phế liệu sau sửa đổi năm 2025"
    )[0]
    source = {
        "text": "Điều kiện nhập phế liệu theo quy định hiện hành.",
        "issued_date": "2012-01-01",
        "document_number": "11/2012/TT-BTNMT",
        "sha256": "a" * 64,
        "retrieved_at": "2026-10-15T10:00:00+00:00",
        "method": "visible_html_text",
        "title": "Quy định về nhập phế liệu",
    }

    context = _source_context(
        "https://congbao.chinhphu.vn/van-ban/law-1.htm", source, query
    )

    assert context is not None
    assert present_context(context).legal_effect_status == "unverified"


def test_pdf_source_context_distinguishes_extracted_text_and_pdf_provenance() -> None:
    from app.services.chat_official_supplement import _source_context
    from app.services.evidence_presenter import present_context

    source = {
        "text": "Quy định về nhập khẩu phế liệu.",
        "sha256": "a" * 64,
        "document_sha256": "b" * 64,
        "attachment_url": "https://datafiles.chinhphu.vn/law.pdf",
        "page_start": 1,
        "page_end": 5,
        "page_count": 12,
        "truncated": True,
        "retrieved_at": "2026-10-15T10:00:00+00:00",
        "method": "pdf_text",
        "title": "Quy định về nhập khẩu phế liệu",
    }

    context = _source_context(
        "https://congbao.chinhphu.vn/van-ban/law.htm", source,
        "quy định nhập khẩu phế liệu",
    )

    assert context is not None
    assert "SHA-256 nội dung trích xuất: " + "a" * 64 in context
    assert "SHA-256 tệp PDF: " + "b" * 64 in context
    assert "Tệp PDF: https://datafiles.chinhphu.vn/law.pdf" in context
    assert "Phạm vi trang PDF: 1-5/12" in context
    assert "Đọc một phần PDF: có" in context
    view = present_context(context)
    assert view.source_sha256 == "a" * 64
    assert view.document_sha256 == "b" * 64
    assert view.source_url == "https://congbao.chinhphu.vn/van-ban/law.htm"
    assert view.attachment_url == "https://datafiles.chinhphu.vn/law.pdf"
    assert (view.page_start, view.page_end, view.page_count) == (1, 5, 12)
    assert view.truncated is True


def test_html_source_context_keeps_legacy_hash_label_and_has_no_pdf_scope() -> None:
    from app.services.chat_official_supplement import _source_context
    from app.services.evidence_presenter import present_context

    source = {
        "text": "Quy định về nhập khẩu phế liệu.",
        "sha256": "a" * 64,
        "retrieved_at": "2026-10-15T10:00:00+00:00",
        "method": "visible_html_text",
        "title": "Quy định về nhập khẩu phế liệu",
    }

    context = _source_context(
        "https://vanban.chinhphu.vn/default.aspx?docid=123", source,
        "quy định nhập khẩu phế liệu",
    )

    assert context is not None
    assert "SHA-256 nguồn: " + "a" * 64 in context
    assert "SHA-256 tệp PDF:" not in context
    view = present_context(context)
    assert view.source_sha256 == "a" * 64
    assert view.document_sha256 is None
    assert (view.page_start, view.page_end, view.page_count) == (None, None, None)
    assert view.truncated is None


def test_pdf_source_without_complete_page_provenance_is_not_used_as_evidence() -> None:
    from app.services.chat_official_supplement import _source_context

    source = {
        "text": "Quy định về nhập khẩu phế liệu.",
        "sha256": "a" * 64,
        "retrieved_at": "2026-10-15T10:00:00+00:00",
        "method": "pdf_text",
        "title": "Quy định về nhập khẩu phế liệu",
    }

    assert _source_context(
        "https://congbao.chinhphu.vn/van-ban/law.pdf", source,
        "quy định nhập khẩu phế liệu",
    ) is None


def test_pdf_source_rejects_unapproved_attachment_url() -> None:
    from app.services.chat_official_supplement import _source_context

    source = {
        "text": "Quy định về nhập khẩu phế liệu.",
        "sha256": "a" * 64,
        "document_sha256": "b" * 64,
        "attachment_url": "https://evil.example/law.pdf",
        "page_start": 1,
        "page_end": 1,
        "page_count": 1,
        "truncated": False,
        "retrieved_at": "2026-10-15T10:00:00+00:00",
        "method": "pdf_text",
        "title": "Quy định về nhập khẩu phế liệu",
    }

    assert _source_context(
        "https://congbao.chinhphu.vn/van-ban/law.htm", source,
        "quy định nhập khẩu phế liệu",
    ) is None


def test_official_source_context_rejects_unapproved_detail_url() -> None:
    from app.services.chat_official_supplement import _source_context

    source = {
        "text": "Quy định về nhập khẩu phế liệu.",
        "sha256": "a" * 64,
        "retrieved_at": "2026-10-15T10:00:00+00:00",
        "method": "visible_html_text",
        "title": "Quy định về nhập khẩu phế liệu",
    }

    assert _source_context(
        "https://evil.example/law.htm", source,
        "quy định nhập khẩu phế liệu",
    ) is None


@pytest.mark.asyncio
async def test_temporal_query_ranks_relevant_recent_result_before_older_hits() -> None:
    from app.services.chat_official_supplement import supplement_official_evidence
    from app.services.official_web_search import OfficialSearchRecord, OfficialSearchResponse

    target_url = "https://congbao.chinhphu.vn/van-ban/amendment-2025.htm"
    old_urls = [
        "https://vanban.chinhphu.vn/default.aspx?docid=1",
        "https://vanban.chinhphu.vn/default.aspx?docid=2",
    ]
    records = (
        OfficialSearchRecord(
            old_urls[0], "Phế liệu", "vanban.chinhphu.vn", "Nhập phế liệu", "", "2012-01-01"
        ),
        OfficialSearchRecord(
            old_urls[1], "Phế liệu", "vanban.chinhphu.vn", "Nhập phế liệu", "", "2014-01-01"
        ),
        OfficialSearchRecord(
            target_url,
            "Sửa đổi quy định nhập phế liệu năm 2025",
            "congbao.chinhphu.vn",
            "Luật Bảo vệ môi trường",
            "12/2025/QH14",
            "2025-08-01",
        ),
    )
    corpus_contexts = [
        "[72/2020/QH14, Điều 53]\n"
        "Nguồn: https://example.gov.vn/law\n"
        "Tiêu đề: Luật Bảo vệ môi trường\n"
        "Quy định về nhập phế liệu."
    ]
    seen_queries: list[str] = []
    read_urls: list[str] = []

    class Provider:
        async def search(self, query: str, *, limit: int = 3):
            seen_queries.append(query)
            return OfficialSearchResponse(records, "public", 1.0, 3)

    async def reader(url: str, *, use_ocr: bool, page_limit: int):
        read_urls.append(url)
        return {
            "text": "Điều kiện nhập phế liệu theo Luật Bảo vệ môi trường.",
            "issued_date": "2025-08-01" if url == target_url else "2012-01-01",
            "document_number": "12/2025/QH14" if url == target_url else "11/2012/TT-BTNMT",
            "sha256": "a" * 64,
            "retrieved_at": "2026-10-15T10:00:00+00:00",
            "method": "visible_html_text",
            "title": "Luật Bảo vệ môi trường",
        }

    result = await supplement_official_evidence(
        "Điều kiện nhập phế liệu sau sửa đổi năm 2025?",
        corpus_contexts=corpus_contexts,
        settings=SimpleNamespace(
            CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED=True,
            CHAT_OFFICIAL_WEB_SUPPLEMENT_TIMEOUT_SECONDS=8.0,
            OFFICIAL_WEB_RESEARCH_ENABLED=True,
        ),
        provider=Provider(),
        reader=reader,
        browser=EmptyCorpusBrowser(),
    )

    assert seen_queries == [
        "nhập phế liệu sửa đổi 2025",
        "sửa đổi 2025 Luật Bảo vệ môi trường",
    ]
    assert read_urls[0] == target_url
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_source_can_cover_one_topic_without_all_topics_in_same_excerpt() -> None:
    from app.services.chat_official_supplement import supplement_official_evidence
    from app.services.official_web_search import OfficialSearchRecord, OfficialSearchResponse

    class Provider:
        async def search(self, query: str, *, limit: int = 3):
            return OfficialSearchResponse(
                (OfficialSearchRecord(
                    "https://vanban.chinhphu.vn/default.aspx?docid=123",
                    "Quy định nhập phế liệu",
                    "vanban.chinhphu.vn",
                    "",
                    "123/2025/QH15",
                    "2025-01-01",
                ),),
                "public", 1.0, 1,
            )

    async def reader(url: str, *, use_ocr: bool, page_limit: int):
        return {
            "text": "Điều kiện nhập phế liệu được quy định tại văn bản này.",
            "sha256": "a" * 64,
            "retrieved_at": "2026-10-15T10:00:00+00:00",
            "method": "visible_html_text",
            "title": "Quy định nhập phế liệu",
            "document_number": "123/2025/QH15",
        }

    result = await supplement_official_evidence(
        "Mức lương thử việc và điều kiện nhập phế liệu hiện nay?",
        settings=SimpleNamespace(
            CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED=True,
            CHAT_OFFICIAL_WEB_SUPPLEMENT_TIMEOUT_SECONDS=8.0,
            OFFICIAL_WEB_RESEARCH_ENABLED=True,
        ),
        provider=Provider(),
        reader=reader,
        browser=EmptyCorpusBrowser(),
    )

    assert result.status == "ok"
    assert len(result.contexts) == 1


@pytest.mark.asyncio
async def test_reads_only_approved_official_sources_and_ignores_discovery_snippets() -> None:
    from app.services.chat_official_supplement import supplement_official_evidence
    from app.services.official_web_search import (
        OfficialSearchRecord,
        OfficialSearchResponse,
    )

    seen_queries: list[str] = []
    read_urls: list[str] = []

    class Provider:
        async def search(self, query: str, *, limit: int = 3):
            seen_queries.append(query)
            return OfficialSearchResponse(
                results=(
                    OfficialSearchRecord(
                        "https://vanban.chinhphu.vn.evil.test/a",
                        "Spoofed",
                        "vanban.chinhphu.vn.evil.test",
                        "UNTRUSTED DISCOVERY TEXT",
                        "",
                        "",
                    ),
                    OfficialSearchRecord(
                        "https://vanban.chinhphu.vn/default.aspx?docid=123",
                        "Metadata title",
                        "vanban.chinhphu.vn",
                        "UNTRUSTED DISCOVERY TEXT",
                        "45/2019/QH14",
                        "2019-11-20",
                    ),
                ),
                provider="chinhphu_and_congbao",
                latency_ms=1.0,
                request_count=3,
            )

    async def reader(url: str, *, use_ocr: bool, page_limit: int):
        read_urls.append(url)
        assert use_ocr is False
        assert page_limit <= 5
        return {
            "url": url,
            "title": "Bộ luật Lao động",
            "text": (
                "Điều 26. Tiền lương trong thời gian thử việc\n"
                "Mức lương thử việc ít nhất bằng 85% mức lương của công việc đó."
            ),
            "sha256": "a" * 64,
            "retrieved_at": "2026-10-15T10:00:00+00:00",
            "method": "visible_html_text",
            "legal_effect_status": "unverified",
            "document_number": "45/2019/QH14",
            "content_status": "readable",
        }

    result = await supplement_official_evidence(
        "Tôi tên Nguyễn Văn Bình, lương 12 triệu; công ty trả 70% khi thử việc?",
        settings=SimpleNamespace(
            CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED=True,
            CHAT_OFFICIAL_WEB_SUPPLEMENT_TIMEOUT_SECONDS=8.0,
            OFFICIAL_WEB_RESEARCH_ENABLED=True,
        ),
        provider=Provider(),
        reader=reader,
        browser=EmptyCorpusBrowser(),
    )

    assert seen_queries == ["lương thử việc"]
    assert read_urls == ["https://vanban.chinhphu.vn/default.aspx?docid=123"]
    assert result.status == "ok"
    assert len(result.contexts) == 1
    context = result.contexts[0]
    from app.services.evidence_presenter import (
        TrustedOfficialEvidenceContext,
        present_context,
    )

    assert isinstance(context, TrustedOfficialEvidenceContext)
    assert present_context(context).source_type == "official_external"
    assert "85%" in context
    assert "UNTRUSTED DISCOVERY TEXT" not in context
    assert "Nguồn loại: official_external" in context
    assert "Hiệu lực pháp lý: unverified" in context
    assert "SHA-256 nguồn: " + "a" * 64 in context
    assert "Thời điểm đọc: 2026-10-15T10:00:00+00:00" in context
    assert result.diagnostics["sources_read"] == 1


@pytest.mark.asyncio
async def test_current_query_reads_topical_official_rule_outside_base_law_title() -> None:
    from app.services.chat_official_supplement import (
        evidence_covers_recognized_topics,
        supplement_official_evidence,
    )
    from app.services.official_web_search import OfficialSearchRecord, OfficialSearchResponse

    query = (
        "Tôi muốn nhập khẩu phế liệu làm nguyên liệu sản xuất. "
        "Theo quy định hiện nay, doanh nghiệp cần đáp ứng điều kiện gì "
        "và có phải xin giấy phép môi trường không?"
    )
    corpus_contexts = [
        "[72/2020/QH14, Điều 1]\nNguồn: https://example.gov.vn/base\n"
        "Tiêu đề: Luật Bảo vệ môi trường 2020\nQuy định về phế liệu."
    ]
    url = "https://congbao.chinhphu.vn/van-ban/scrap-list-2023.htm"
    record = OfficialSearchRecord(
        url, "Danh mục phế liệu được phép nhập khẩu làm nguyên liệu sản xuất",
        "congbao.chinhphu.vn", "Danh mục nhập khẩu phế liệu",
        "13/2023/QĐ-TTg", "2023-05-22",
    )

    class Provider:
        async def search(self, search_query: str, *, limit: int = 3):
            return OfficialSearchResponse(
                (record,) if "phế liệu" in search_query else (),
                "public", 1.0, 1,
            )

    read_urls = []

    async def reader(source_url: str, *, use_ocr: bool, page_limit: int):
        read_urls.append(source_url)
        assert not use_ocr and page_limit == 5
        return {
            "title": record.title,
            "text": "Điều 1. Danh mục phế liệu được phép nhập khẩu làm nguyên liệu sản xuất.",
            "sha256": "a" * 64,
            "retrieved_at": "2026-10-24T00:00:00+00:00",
            "method": "visible_html_text",
            "content_status": "readable",
        }

    result = await supplement_official_evidence(
        query,
        corpus_contexts=corpus_contexts,
        settings=SimpleNamespace(
            CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED=True,
            CHAT_OFFICIAL_WEB_SUPPLEMENT_TIMEOUT_SECONDS=8.0,
            OFFICIAL_WEB_RESEARCH_ENABLED=True,
        ),
        provider=Provider(),
        reader=reader,
        browser=EmptyCorpusBrowser(),
    )

    assert read_urls == [url]
    assert result.status == "ok"
    assert len(result.contexts) == 1
    assert result.diagnostics["newer_source_required"] is True
    assert not evidence_covers_recognized_topics(query, result.contexts)


@pytest.mark.asyncio
async def test_unreadable_official_page_does_not_become_evidence() -> None:
    from app.services.chat_official_supplement import supplement_official_evidence
    from app.services.official_web_search import OfficialSearchRecord, OfficialSearchResponse

    class Provider:
        async def search(self, query: str, *, limit: int = 3):
            return OfficialSearchResponse(
                (OfficialSearchRecord(
                    "https://congbao.chinhphu.vn/van-ban/example-123.htm",
                    "Công báo",
                    "congbao.chinhphu.vn",
                    "SNIPPET MUST NOT BE EVIDENCE",
                    "123/2025/NĐ-CP",
                    "2025-01-01",
                ),),
                "chinhphu_and_congbao", 1.0, 1,
            )

    async def reader(*_args, **_kwargs):
        return {
            "text": "",
            "content_status": "metadata_only",
            "legal_effect_status": "unverified",
        }

    result = await supplement_official_evidence(
        "Điều kiện nhập khẩu phế liệu là gì?",
        settings=SimpleNamespace(
            CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED=True,
            CHAT_OFFICIAL_WEB_SUPPLEMENT_TIMEOUT_SECONDS=8.0,
            OFFICIAL_WEB_RESEARCH_ENABLED=True,
        ),
        provider=Provider(),
        reader=reader,
        browser=EmptyCorpusBrowser(),
    )

    assert result.status == "no_readable_source"
    assert result.contexts == []
    assert "SNIPPET MUST NOT BE EVIDENCE" not in str(result)


@pytest.mark.asyncio
async def test_hash_mismatch_uses_verified_official_reader_fallback() -> None:
    from types import SimpleNamespace

    from app.ingestion.legal_text import DocumentMetadata
    from app.services.chat_official_supplement import supplement_official_evidence
    from app.services.official_web_search import OfficialSearchRecord, OfficialSearchResponse

    record = OfficialSearchRecord(
        "https://congbao.chinhphu.vn/van-ban/amendment-2025.htm",
        "Sửa đổi quy định nhập phế liệu",
        "congbao.chinhphu.vn",
        "Quy định mới về nhập phế liệu",
        "34/2025/NĐ-CP",
        "2025-08-01",
    )
    content = (
        "Điều 1. Nhập phế liệu\n"
        "1. Cơ sở nhập khẩu phế liệu phải thực hiện quy định môi trường.\n"
    )
    metadata = DocumentMetadata(
        document_id=34,
        document_number=record.document_number,
        title=record.title,
        source_url=record.url,
        legal_type="Nghị định",
        legal_sectors="môi trường",
        issuing_authority="Chính phủ",
        issuance_date=record.issued_date,
    )

    class Provider:
        async def search(self, _query: str, *, limit: int = 3):
            return OfficialSearchResponse((record,), "public", 1.0, 1)

    class FakeBrowser:
        def search(self, _query: str, *, limit: int):
            return [
                SimpleNamespace(
                    document_id=metadata.document_id,
                    document_number=metadata.document_number,
                )
            ]

        def get_document(self, _document_id: int):
            return SimpleNamespace(
                metadata=metadata,
                content=content,
                content_sha256="0" * 64,
            )

    async def reader(_url: str, *, use_ocr: bool, page_limit: int):
        assert not use_ocr and page_limit <= 5
        return {
            "text": "Điều kiện nhập phế liệu theo quy định môi trường.",
            "sha256": "a" * 64,
            "retrieved_at": "2026-10-15T10:00:00+00:00",
            "method": "visible_html_text",
            "title": record.title,
        }

    result = await supplement_official_evidence(
        "Điều kiện nhập phế liệu hiện nay?",
        settings=SimpleNamespace(
            CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED=True,
            CHAT_OFFICIAL_WEB_SUPPLEMENT_TIMEOUT_SECONDS=8.0,
            OFFICIAL_WEB_RESEARCH_ENABLED=True,
        ),
        provider=Provider(),
        reader=reader,
        browser=FakeBrowser(),
    )

    assert result.status == "ok"
    assert result.diagnostics["official_corpus_rescue"]["status"] == "no_evidence"
    assert result.diagnostics["official_corpus_rescue"]["candidates"][0]["status"] == (
        "corpus_hash_mismatch"
    )
    assert "Nguồn loại: official_external" in result.contexts[0]


@pytest.mark.asyncio
async def test_corpus_rescue_stops_after_first_verified_relevant_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import official_discovered_corpus_rescue
    from app.services.chat_official_supplement import supplement_official_evidence
    from app.services.official_web_search import OfficialSearchRecord, OfficialSearchResponse

    records = (
        OfficialSearchRecord(
            "https://congbao.chinhphu.vn/van-ban/amendment-2025.htm",
            "Sửa đổi Luật Bảo vệ môi trường về nhập phế liệu",
            "congbao.chinhphu.vn", "", "146/2025/QH15", "2025-07-01",
        ),
        OfficialSearchRecord(
            "https://congbao.chinhphu.vn/van-ban/original-2020.htm",
            "Luật Bảo vệ môi trường về nhập phế liệu",
            "congbao.chinhphu.vn", "", "72/2020/QH14", "2020-11-17",
        ),
    )
    seen_numbers: list[str] = []

    class Provider:
        async def search(self, _query: str, *, limit: int = 3):
            return OfficialSearchResponse(records, "public", 1.0, 1)

    class Chunk:
        def formatted_context(self):
            return "[Luật 146/2025/QH15, Điều 1]\nPhế liệu nhập khẩu."

    def rescue(_query, selected_records, _browser, *, settings):
        selected = list(selected_records)
        seen_numbers.extend(record.document_number for record in selected)
        assert len(selected) == 1
        return SimpleNamespace(
            evidence=(Chunk(),),
            diagnostics={"status": "evidence_selected", "selected_chunk_count": 1},
        )

    monkeypatch.setattr(
        official_discovered_corpus_rescue, "rescue_official_discoveries", rescue
    )

    async def unexpected_reader(*_args, **_kwargs):
        raise AssertionError("verified corpus evidence should avoid official PDF reads")

    result = await supplement_official_evidence(
        "Nhập phế liệu có cần giấy phép môi trường sau khi sửa đổi không?",
        settings=SimpleNamespace(
            CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED=True,
            CHAT_OFFICIAL_WEB_SUPPLEMENT_TIMEOUT_SECONDS=8.0,
            OFFICIAL_WEB_RESEARCH_ENABLED=True,
        ),
        provider=Provider(),
        reader=unexpected_reader,
        browser=EmptyCorpusBrowser(),
    )

    assert result.status == "corpus_rescued", result.diagnostics
    assert seen_numbers == ["146/2025/QH15"]


@pytest.mark.asyncio
@pytest.mark.parametrize("generic_amendment_title", [False, True])
async def test_current_law_rescue_prioritizes_newer_official_amendment(generic_amendment_title: bool) -> None:
    from app.services.chat_official_supplement import (
        _search_record_rank,
        derive_official_search_queries,
        supplement_official_evidence,
    )
    from app.services.official_web_search import OfficialSearchRecord, OfficialSearchResponse

    query = "Quy định nhập phế liệu hiện nay theo Luật Bảo vệ môi trường?"
    corpus_contexts = [
        "[72/2020/QH14, Điều 53]\n"
        "Nguồn: https://example.gov.vn/law\n"
        "Tiêu đề: Luật Bảo vệ môi trường\n"
        "Quy định về nhập phế liệu."
    ]
    queries = derive_official_search_queries(query, corpus_contexts=corpus_contexts)
    old_record = OfficialSearchRecord(
        "https://congbao.chinhphu.vn/van-ban/base-2020.htm",
        "Luật Bảo vệ môi trường quy định nhập phế liệu hiện nay",
        "congbao.chinhphu.vn",
        "Quy định nhập phế liệu",
        "72/2020/QH14",
        "2020-11-17",
    )
    amendment_record = OfficialSearchRecord(
        "https://congbao.chinhphu.vn/van-ban/amendment-2025.htm",
        "Luật sửa đổi một số điều của 15 Luật trong lĩnh vực nông nghiệp và môi trường"
        if generic_amendment_title else "Nghị định 146/2025/NĐ-CP sửa đổi quy định nhập phế liệu",
        "congbao.chinhphu.vn",
        "" if generic_amendment_title else "Sửa đổi Luật Bảo vệ môi trường",
        "146/2025/NĐ-CP",
        "2025-07-01",
    )
    unrelated_record = OfficialSearchRecord(
        "https://congbao.chinhphu.vn/van-ban/unrelated-2026.htm",
        "Nghị định 9/2026/NĐ-CP về thú y",
        "congbao.chinhphu.vn",
        "Quy định phòng dịch động vật",
        "9/2026/NĐ-CP",
        "2026-01-01",
    )
    assert _search_record_rank(old_record, queries[1]) > _search_record_rank(
        amendment_record, queries[0]
    )
    records_by_query = {
        queries[0]: (unrelated_record,) if generic_amendment_title else (amendment_record, unrelated_record),
        queries[1]: (old_record, amendment_record, unrelated_record)
        if generic_amendment_title else (old_record, unrelated_record),
    }

    class Provider:
        def __init__(self):
            self.calls: list[str] = []

        async def search(self, search_query: str, *, limit: int = 3):
            self.calls.append(search_query)
            assert limit == 3
            return OfficialSearchResponse(records_by_query[search_query], "public", 1.0, 1)

    def corpus_document(record, document_id: int, title: str, body: str):
        metadata = SimpleNamespace(
            document_id=document_id,
            document_number=record.document_number,
            title=title,
            source_url=record.url,
            legal_type="Luật",
            legal_sectors="môi trường",
            issuing_authority="Quốc hội",
            issuance_date=record.issued_date,
        )
        return SimpleNamespace(
            metadata=metadata,
            content=body,
            content_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        )

    old_document = corpus_document(
        old_record,
        720,
        "Luật Bảo vệ môi trường",
        "Điều 53. Quy định nhập phế liệu phải đáp ứng yêu cầu môi trường.",
    )
    amendment_document = corpus_document(
        amendment_record,
        146,
        "Nghị định 146/2025/NĐ-CP sửa đổi quy định nhập phế liệu",
        "Điều 1. Sửa đổi quy định nhập phế liệu và yêu cầu giấy phép môi trường.",
    )
    documents = {
        old_record.document_number: old_document,
        amendment_record.document_number: amendment_document,
    }

    class Browser:
        def __init__(self, missing_numbers=()):
            self.searches: list[str] = []
            self.loads: list[int] = []
            self.missing_numbers = set(missing_numbers)

        def search(self, number: str, *, limit: int):
            self.searches.append(number)
            assert limit == 50
            if number in self.missing_numbers:
                return []
            document = documents[number]
            return [
                SimpleNamespace(
                    document_id=document.metadata.document_id,
                    document_number=number,
                    title=document.metadata.title,
                    issuing_authority=document.metadata.issuing_authority,
                    issuance_date=document.metadata.issuance_date,
                )
            ]

        def get_document(self, document_id: int):
            self.loads.append(document_id)
            return next(
                document for document in documents.values()
                if document.metadata.document_id == document_id
            )

    provider = Provider()
    browser = Browser()

    async def unexpected_reader(*_args, **_kwargs):
        raise AssertionError("hash-verified corpus evidence should avoid external reads")

    result = await supplement_official_evidence(
        query,
        corpus_contexts=corpus_contexts,
        settings=SimpleNamespace(
            CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED=True,
            CHAT_OFFICIAL_WEB_SUPPLEMENT_TIMEOUT_SECONDS=8.0,
            OFFICIAL_WEB_RESEARCH_ENABLED=True,
        ),
        provider=provider,
        reader=unexpected_reader,
        browser=browser,
    )

    assert provider.calls == list(queries)
    assert result.status == "corpus_rescued", result.diagnostics
    assert "146/2025/NĐ-CP" in result.contexts[0]
    assert result.diagnostics["newer_source_status"] == "corpus_identity_verified_effect_unverified"
    assert browser.searches == ["146/2025/NĐ-CP"]
    assert len(browser.searches) <= 2
    assert len(browser.loads) <= 2
    assert result.latency_seconds <= 8.0
    assert result.diagnostics["official_corpus_rescue"]["legal_effect_asserted"] is False
    assert old_document.content_sha256 == hashlib.sha256(old_document.content.encode()).hexdigest()
    assert amendment_document.content_sha256 == hashlib.sha256(
        amendment_document.content.encode()
    ).hexdigest()

    missing_amendment_browser = Browser([amendment_record.document_number])
    read_urls: list[str] = []

    async def unreadable_newer_source(url: str, *, use_ocr: bool, page_limit: int):
        read_urls.append(url)
        return {"text": "", "content_status": "metadata_only"}

    incomplete = await supplement_official_evidence(
        query,
        corpus_contexts=corpus_contexts,
        settings=SimpleNamespace(
            CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED=True,
            CHAT_OFFICIAL_WEB_SUPPLEMENT_TIMEOUT_SECONDS=8.0,
            OFFICIAL_WEB_RESEARCH_ENABLED=True,
        ),
        provider=Provider(),
        reader=unreadable_newer_source,
        browser=missing_amendment_browser,
    )

    assert incomplete.status == "no_readable_source"
    assert incomplete.contexts == []
    assert missing_amendment_browser.searches == [amendment_record.document_number]
    assert missing_amendment_browser.loads == []
    assert read_urls == [amendment_record.url]


@pytest.mark.asyncio
async def test_corpus_rescue_timeout_keeps_official_reader_fallback() -> None:
    import time
    from types import SimpleNamespace

    from app.services.chat_official_supplement import supplement_official_evidence
    from app.services.official_web_search import OfficialSearchRecord, OfficialSearchResponse

    record = OfficialSearchRecord(
        "https://congbao.chinhphu.vn/van-ban/amendment-timeout.htm",
        "Quy định nhập phế liệu",
        "congbao.chinhphu.vn",
        "Quy định môi trường khi nhập phế liệu",
        "33/2025/NĐ-CP",
        "2025-08-01",
    )

    class Provider:
        async def search(self, _query: str, *, limit: int = 3):
            return OfficialSearchResponse((record,), "public", 1.0, 1)

    class SlowBrowser:
        def search(self, _query: str, *, limit: int):
            time.sleep(0.6)
            return []

    async def reader(_url: str, *, use_ocr: bool, page_limit: int):
        return {
            "text": "Điều kiện nhập phế liệu theo quy định môi trường.",
            "sha256": "a" * 64,
            "retrieved_at": "2026-10-15T10:00:00+00:00",
            "method": "visible_html_text",
            "title": record.title,
        }

    result = await supplement_official_evidence(
        "Điều kiện nhập phế liệu hiện nay?",
        settings=SimpleNamespace(
            CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED=True,
            CHAT_OFFICIAL_WEB_SUPPLEMENT_TIMEOUT_SECONDS=0.5,
            OFFICIAL_WEB_RESEARCH_ENABLED=True,
        ),
        provider=Provider(),
        reader=reader,
        browser=SlowBrowser(),
    )

    assert result.status == "ok"
    assert result.diagnostics["official_corpus_rescue"]["status"] == "timeout"
    assert "Nguồn loại: official_external" in result.contexts[0]


@pytest.mark.asyncio
async def test_current_law_rescue_checks_two_topical_newer_records_and_skips_unrelated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import official_discovered_corpus_rescue
    from app.services.chat_official_supplement import supplement_official_evidence
    from app.services.official_web_search import OfficialSearchRecord, OfficialSearchResponse

    records = (
        OfficialSearchRecord(
            "https://congbao.chinhphu.vn/van-ban/amendment-2026.htm",
            "Nghị định sửa đổi Luật Bảo vệ môi trường về nhập phế liệu",
            "congbao.chinhphu.vn",
            "Quy định nhập phế liệu",
            "146/2026/NĐ-CP",
            "2026-07-01",
        ),
        OfficialSearchRecord(
            "https://congbao.chinhphu.vn/van-ban/amendment-2025.htm",
            "Nghị định sửa đổi Luật Bảo vệ môi trường về nhập phế liệu",
            "congbao.chinhphu.vn",
            "Quy định nhập phế liệu",
            "50/2025/NĐ-CP",
            "2025-07-01",
        ),
        OfficialSearchRecord(
            "https://congbao.chinhphu.vn/van-ban/unrelated-2027.htm",
            "Nghị định về bệnh dịch thú y",
            "congbao.chinhphu.vn",
            "Phòng dịch động vật",
            "9/2027/NĐ-CP",
            "2027-01-01",
        ),
    )
    seen_numbers: list[str] = []

    class Provider:
        async def search(self, _query: str, *, limit: int = 3):
            assert limit == 3
            return OfficialSearchResponse(records, "public", 1.0, len(records))

    class Chunk:
        def formatted_context(self):
            return "[Luật 50/2025/NĐ-CP, Điều 1]\nQuy định nhập phế liệu."

    def rescue(_query, selected_records, _browser, *, settings):
        record = list(selected_records)[0]
        seen_numbers.append(record.document_number)
        if record.document_number == "50/2025/NĐ-CP":
            return SimpleNamespace(
                evidence=(Chunk(),),
                diagnostics={"status": "evidence_selected", "selected_chunk_count": 1},
            )
        return SimpleNamespace(evidence=(), diagnostics={"status": "no_evidence"})

    monkeypatch.setattr(
        official_discovered_corpus_rescue, "rescue_official_discoveries", rescue
    )

    async def unexpected_reader(*_args, **_kwargs):
        pytest.fail("a verified topical amendment should end the bounded rescue")

    result = await supplement_official_evidence(
        "Nhập phế liệu hiện nay theo Luật Bảo vệ môi trường?",
        corpus_contexts=[
            "[72/2020/QH14, Điều 53]\n"
            "Nguồn: https://vanban.chinhphu.vn/default.aspx?docid=72\n"
            "Tiêu đề: Luật Bảo vệ môi trường\n"
            "Quy định về nhập phế liệu."
        ],
        settings=SimpleNamespace(
            CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED=True,
            CHAT_OFFICIAL_WEB_SUPPLEMENT_TIMEOUT_SECONDS=8.0,
            OFFICIAL_WEB_RESEARCH_ENABLED=True,
        ),
        provider=Provider(),
        reader=unexpected_reader,
        browser=EmptyCorpusBrowser(),
    )

    assert result.status == "corpus_rescued"
    assert seen_numbers == ["146/2026/NĐ-CP", "50/2025/NĐ-CP"]
    assert len(seen_numbers) <= 2
    assert "9/2027/NĐ-CP" not in seen_numbers


@pytest.mark.asyncio
async def test_unavailable_newer_law_does_not_fall_back_to_older_corpus_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import official_discovered_corpus_rescue
    from app.services.chat_official_supplement import supplement_official_evidence
    from app.services.official_web_search import OfficialSearchRecord, OfficialSearchResponse

    newer = OfficialSearchRecord(
        "https://congbao.chinhphu.vn/van-ban/amendment-2025.htm",
        "Nghị định sửa đổi Luật Bảo vệ môi trường về nhập phế liệu",
        "congbao.chinhphu.vn",
        "Quy định nhập phế liệu",
        "50/2025/NĐ-CP",
        "2025-07-01",
    )
    older = OfficialSearchRecord(
        "https://congbao.chinhphu.vn/van-ban/base-2020.htm",
        "Luật Bảo vệ môi trường về nhập phế liệu",
        "congbao.chinhphu.vn",
        "Quy định nhập phế liệu",
        "72/2020/QH14",
        "2020-11-17",
    )
    attempts: list[str] = []

    class Provider:
        async def search(self, _query: str, *, limit: int = 3):
            return OfficialSearchResponse((older, newer), "public", 1.0, 2)

    class OldChunk:
        def formatted_context(self):
            return "[72/2020/QH14, Điều 53]\nQuy định nhập phế liệu cũ."

    def rescue(_query, selected_records, _browser, *, settings):
        record = list(selected_records)[0]
        attempts.append(record.document_number)
        if record.document_number == older.document_number:
            return SimpleNamespace(
                evidence=(OldChunk(),),
                diagnostics={"status": "evidence_selected", "selected_chunk_count": 1},
            )
        return SimpleNamespace(evidence=(), diagnostics={"status": "no_evidence"})

    monkeypatch.setattr(
        official_discovered_corpus_rescue, "rescue_official_discoveries", rescue
    )

    async def metadata_only_reader(url: str, *, use_ocr: bool, page_limit: int):
        assert url == newer.url
        return {"text": "", "content_status": "metadata_only"}

    result = await supplement_official_evidence(
        "Nhập phế liệu hiện nay theo Luật Bảo vệ môi trường?",
        corpus_contexts=[
            "[72/2020/QH14, Điều 53]\n"
            "Nguồn: https://vanban.chinhphu.vn/default.aspx?docid=72\n"
            "Tiêu đề: Luật Bảo vệ môi trường\n"
            "Quy định về nhập phế liệu."
        ],
        settings=SimpleNamespace(
            CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED=True,
            CHAT_OFFICIAL_WEB_SUPPLEMENT_TIMEOUT_SECONDS=8.0,
            OFFICIAL_WEB_RESEARCH_ENABLED=True,
        ),
        provider=Provider(),
        reader=metadata_only_reader,
        browser=EmptyCorpusBrowser(),
    )

    assert result.status == "no_readable_source"
    assert result.contexts == []
    assert attempts == [newer.document_number]


@pytest.mark.asyncio
async def test_scoped_requests_and_disabled_setting_do_not_search() -> None:
    from app.services.chat_official_supplement import supplement_official_evidence

    class Provider:
        async def search(self, *_args, **_kwargs):
            raise AssertionError("disabled supplement must not search")

    disabled = await supplement_official_evidence(
        "lương thử việc",
        settings=SimpleNamespace(
            CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED=False,
            OFFICIAL_WEB_RESEARCH_ENABLED=True,
        ),
        provider=Provider(),
    )
    assert disabled.status == "disabled"
    assert disabled.contexts == []
