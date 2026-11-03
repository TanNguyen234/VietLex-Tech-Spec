import pytest

from app.services.chat_official_supplement import (
    corpus_evidence_covers_topic, derive_official_search_queries,
    evidence_covers_recognized_topics, topic_coverage_diagnostics,
    _relevant_excerpt,
)
from app.services.legal_topic_terms import contains_topic_phrase, extract_official_topic_phrases
from app.services.rag_pipeline import build_bounded_context


def test_unknown_topic_does_not_prove_sufficiency():
    assert not corpus_evidence_covers_topic('Một tình huống chưa được nhận diện', ['Bất kỳ văn bản'])


def test_rental_aliases_are_sanitized():
    queries = derive_official_search_queries('Tôi là Nguyễn Văn Bình, thuê trọ cọc 5 triệu, chủ trọ giữ tiền cọc?')
    assert queries == ('thuê nhà đặt cọc',)
    assert 'Bình' not in str(queries) and '5' not in str(queries)


@pytest.mark.parametrize('text', [
    'Đặt cọc cho người lao động đi làm việc ở nước ngoài.',
    'Quản lý cư trú, đăng ký tạm trú của người thuê trọ.',
    'Giao dịch nhà ở được xác lập trước ngày 01 tháng 7 năm 1991; đặt cọc thuê nhà.',
])
def test_rental_deposit_rejects_wrong_situations(text):
    assert not corpus_evidence_covers_topic('thuê trọ tiền cọc', [text])
    assert _relevant_excerpt(text, 'thuê nhà đặt cọc') is None


def test_rental_deposit_accepts_equivalent_words():
    assert corpus_evidence_covers_topic('thuê trọ tiền cọc', ['Đặt cọc bảo đảm hợp đồng thuê nhà ở.'])


def test_overlapping_deposit_alias_preserves_rental_situation_and_deduplicates():
    assert extract_official_topic_phrases("cọc thuê nhà") == ("đặt cọc", "thuê nhà")
    assert extract_official_topic_phrases("đặt cọc thuê nhà") == (
        "đặt cọc",
        "thuê nhà",
    )
    assert not corpus_evidence_covers_topic(
        "cọc thuê nhà",
        ["Đặt cọc cho người lao động đi làm việc ở nước ngoài."],
    )


def test_current_rental_coverage_rejects_historical_pre_1991_evidence():
    historical_context = (
        "[Luật nhà ở]\nNguồn: https://example.gov.vn/law\n"
        "Tiêu đề: Giao dịch nhà ở trước ngày 01 tháng 7 năm 1991\n"
        "Đặt cọc thuê nhà theo thỏa thuận của các bên."
    )

    assert not evidence_covers_recognized_topics(
        "Hiện nay thuê trọ tiền cọc xử lý thế nào?", [historical_context]
    )


def test_topic_coverage_diagnostic_lists_only_curated_missing_topics():
    diagnostic = topic_coverage_diagnostics(
        "Tôi tên Nguyễn Văn Bình, hỏi về thử việc và bảo hiểm xã hội.", []
    )

    assert diagnostic["status"] == "missing"
    assert diagnostic["recognized_topics"] == ["thử việc", "bảo hiểm xã hội"]
    assert diagnostic["missing_topics"] == ["thử việc", "bảo hiểm xã hội"]
    assert "Bình" not in str(diagnostic)


def test_multiword_topic_coverage_requires_phrase_or_curated_alias():
    from app.services.chat_official_supplement import (
        topic_supporting_contexts,
    )

    query = "Thử việc quy định thế nào?"
    disjoint_terms = "Người lao động phải tuân thủ quy định về ngày làm việc."

    assert not corpus_evidence_covers_topic(query, [disjoint_terms])
    assert not evidence_covers_recognized_topics(query, [disjoint_terms])
    assert topic_coverage_diagnostics(query, [disjoint_terms])["missing_topics"] == [
        "thử việc"
    ]
    assert topic_supporting_contexts(query, [disjoint_terms]) == ()


def test_topic_match_does_not_expand_unrelated_missing_phrases(monkeypatch):
    import app.services.legal_topic_terms as terms

    def unexpected_expansion(*args, **kwargs):
        raise AssertionError("whole-topic extraction must not run for a missing phrase")

    monkeypatch.setattr(terms, "extract_official_topic_phrases", unexpected_expansion)
    assert not contains_topic_phrase("Quy định về hợp đồng.", "đặt cọc")
    assert contains_topic_phrase("Nhập khẩu phế liệu được phép", "nhập phế liệu")


def test_topic_coverage_uses_complete_phrases_and_curated_aliases():
    split_trial_phrase = (
        "Người lao động phải tuân thủ quy định về ngày làm việc."
    )
    assert not corpus_evidence_covers_topic("Thử việc thế nào?", [split_trial_phrase])

    assert extract_official_topic_phrases("thuê phòng trọ") == ("thuê nhà",)
    assert corpus_evidence_covers_topic(
        "thuê phòng trọ", ["Quy định về việc thuê phòng trọ."]
    )

    wage_coverage = topic_coverage_diagnostics(
        "lương thử việc",
        ["Mức lương trong thời gian thử việc do hai bên thỏa thuận."],
    )
    assert wage_coverage["missing_topics"] == []


def test_official_topic_coverage_ignores_title_and_provenance_metadata():
    from app.services.evidence_presenter import TrustedOfficialEvidenceContext

    source = TrustedOfficialEvidenceContext(
        "[Nguồn chính thức ngoài VietLex · 45/2025/NĐ-CP]\n"
        "Nguồn: https://congbao.chinhphu.vn/law\n"
        "Nguồn loại: official_external\n"
        "Hiệu lực pháp lý: unverified\n"
        "SHA-256 nguồn: " + "a" * 64 + "\n"
        "Tiêu đề: Quy định về thử việc và bảo hiểm xã hội\n"
        "Quy định về thử việc."
    )
    query = "Thử việc và bảo hiểm xã hội hiện nay được quy định thế nào?"

    diagnostic = topic_coverage_diagnostics(query, [source])

    assert diagnostic["status"] == "missing"
    assert diagnostic["missing_topics"] == ["bảo hiểm xã hội"]
    assert not corpus_evidence_covers_topic(query, [source])


@pytest.mark.asyncio
async def test_unknown_topic_is_explicit_and_never_sent_to_search():
    from types import SimpleNamespace

    from app.services.chat_official_supplement import supplement_official_evidence

    class Provider:
        async def search(self, *_args, **_kwargs):
            pytest.fail("unknown narrative must not be sent to external search")

    result = await supplement_official_evidence(
        "Tôi tên Nguyễn Văn Bình và gặp vấn đề riêng chưa có trong từ điển.",
        settings=SimpleNamespace(
            CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED=True,
            CHAT_OFFICIAL_WEB_SUPPLEMENT_TIMEOUT_SECONDS=8.0,
            OFFICIAL_WEB_RESEARCH_ENABLED=True,
        ),
        provider=Provider(),
    )

    assert result.status == "no_topics"
    assert result.diagnostics["topic_coverage"] == {
        "status": "unknown",
        "recognized_topics": [],
        "missing_topics": None,
    }
    assert result.diagnostics["search_attempted"] is False


def test_prompt_keeps_whole_evidence_and_skips_oversized_blocks():
    oversized = 'Khoản 1. ' + 'quy định ' * 30 + 'ngoại lệ cuối khoản.'
    complete = 'Khoản 2. Trả lại cọc khi đáp ứng điều kiện.'
    result = build_bounded_context([oversized, complete], max_tokens=25)
    assert oversized not in result and 'Khoản 1.' not in result
    assert complete in result
    assert len(result.split()) <= 25


def test_official_excerpt_preserves_clause_tail_when_it_fits():
    text = 'Điều 328. Đặt cọc\n1. Đặt cọc bảo đảm hợp đồng thuê nhà. ' + 'điều kiện ' * 125 + 'Trừ trường hợp có thỏa thuận khác.'
    excerpt = _relevant_excerpt(text, 'thuê nhà đặt cọc')
    assert excerpt is not None
    assert excerpt.endswith('Trừ trường hợp có thỏa thuận khác.')


def test_unstructured_excerpt_never_cuts_a_long_paragraph_before_its_exception():
    text = (
        'Đặt cọc bảo đảm hợp đồng thuê nhà. '
        + 'Nội dung áp dụng. ' * 125
        + 'Trừ trường hợp có thỏa thuận khác.'
    )

    excerpt = _relevant_excerpt(text, 'thuê nhà đặt cọc')

    assert excerpt is None or excerpt.endswith('Trừ trường hợp có thỏa thuận khác.')
