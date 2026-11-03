from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ingestion.legal_text import DocumentMetadata, EvidenceChunk
from app.services import legal_browser, rag_pipeline
from app.services.primary_law_rescue import rescue_primary_law_evidence


class _Retriever:
    def __init__(self, evidence):
        self.evidence = evidence

    async def retrieve_detailed(self, *_args, **_kwargs):
        return rag_pipeline.RetrievalOutcome(
            evidence=list(self.evidence),
            latency={},
            status="ok",
            diagnostics={},
        )


class _Browser:
    def __init__(
        self,
        documents_by_title,
        *,
        search_results=None,
        document_override=None,
        search_error=None,
        load_error=None,
    ):
        self.documents_by_title = documents_by_title
        self.search_results = search_results or {}
        self.document_override = document_override
        self.search_error = search_error
        self.load_error = load_error
        self.search_calls = []
        self.document_calls = []

    def search(self, query, *, limit, filters=None):
        self.search_calls.append((query, limit, filters))
        if self.search_error is not None:
            raise self.search_error
        if query in self.search_results:
            return self.search_results[query][:limit]
        base_query = query.removesuffix(" 2019").removesuffix(" 2015")
        document = self.documents_by_title.get(query) or self.documents_by_title.get(base_query)
        if document is None:
            return []
        metadata = document.metadata
        return [
            SimpleNamespace(
                document_id=metadata.document_id,
                document_number=metadata.document_number,
                title=metadata.title,
                source_url=metadata.source_url,
                legal_type=metadata.legal_type,
                issuing_authority=metadata.issuing_authority,
                issuance_date=metadata.issuance_date,
            )
        ][:limit]

    def get_document(self, document_id):
        self.document_calls.append(document_id)
        if self.load_error is not None:
            raise self.load_error
        if self.document_override is not None:
            return self.document_override
        return next(
            (
                document
                for document in self.documents_by_title.values()
                if document.metadata.document_id == document_id
            ),
            None,
        )


def _stored_document(document_id, title, content, issued):
    metadata = DocumentMetadata(
        document_id=document_id,
        document_number=f"TEST-{document_id}",
        title=title,
        source_url=f"https://corpus.example.invalid/{document_id}",
        legal_type="Luật",
        legal_sectors="test-only",
        issuing_authority="test-only",
        issuance_date=issued,
    )
    return SimpleNamespace(
        metadata=metadata,
        content=content,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def _hit(document, *, document_id=None, title=None, legal_type=None, issued=None):
    metadata = document.metadata
    return SimpleNamespace(
        document_id=metadata.document_id if document_id is None else document_id,
        document_number=metadata.document_number,
        title=metadata.title if title is None else title,
        source_url=metadata.source_url,
        legal_type=metadata.legal_type if legal_type is None else legal_type,
        issuing_authority=metadata.issuing_authority,
        issuance_date=metadata.issuance_date if issued is None else issued,
    )
def _evidence(document_id, title, text):
    return EvidenceChunk(
        document_id=document_id,
        document_number=f"OLD-{document_id}",
        title=title,
        source_url=f"https://old-corpus.example.invalid/{document_id}",
        heading_path="Chương I > Điều 1",
        article="Điều 1",
        clause="1",
        citation=f"OLD-{document_id}, Điều 1, Khoản 1",
        text=text,
        token_count=len(text.split()),
    )


def _settings(*, legacy=False):
    return SimpleNamespace(
        USE_LEGACY_FREE_PIPELINE=legacy,
        FINAL_EVIDENCE_LIMIT=3,
        LLM_CONTEXT_MAX_TOKENS=720,
        QUERY_CHUNK_MAX_TOKENS=220,
        QUERY_CHUNK_OVERLAP_TOKENS=24,
        LLM_CONTEXT_PER_DOCUMENT_LIMIT=2,
        CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED=False,
    )


def _patch_pipeline(monkeypatch, evidence, settings, browser):
    monkeypatch.setattr(rag_pipeline, "get_settings", lambda: settings)
    monkeypatch.setattr(
        rag_pipeline,
        "retrieve_configured_legal_evidence",
        lambda *_args, **_kwargs: _Retriever(evidence).retrieve_detailed(),
    )

    async def no_expansion(_query, _candidates, selected, **_kwargs):
        return SimpleNamespace(
            selected_evidence=list(selected),
            diagnostics={"status": "not_needed"},
            status="not_needed",
        )

    monkeypatch.setattr(rag_pipeline, "expand_v3_evidence", no_expansion)
    monkeypatch.setattr(
        legal_browser.LegalBrowser,
        "from_settings",
        classmethod(lambda _cls, _settings: browser),
    )


async def _capture_answer(monkeypatch):
    captured = {}

    async def answer(_original, _rewritten, contexts):
        captured["contexts"] = list(contexts)
        return rag_pipeline.LLMGenerationResult("test response", "test", "test")

    monkeypatch.setattr(rag_pipeline, "generate_response_with_metadata", answer)
    return captured


@pytest.mark.asyncio
async def test_verified_primary_labor_title_replaces_historical_same_topic_and_keeps_other_topic(
    monkeypatch,
):
    query = (
        "Tôi nhận lương 12 triệu, thử việc công ty trả 70% có đúng không? "
        "Bảo hiểm xã hội ra sao?"
    )
    corpus_text = (
        "Điều 1. Fixture heading.\n"
        "1. test-only-current-trial-pay thử việc tiền lương.\n"
        "Điều 2. Fixture heading.\n"
        "1. test-only-current-trial-result kết thúc thử việc."
    )
    primary = _stored_document(
        731, "Bộ luật Lao động 2019", corpus_text, "2019-11-20"
    )
    browser = _Browser({"Bộ luật Lao động": primary})
    historical = [
        _evidence(11, "Older labour source", "test-only-historical-trial thử việc."),
        _evidence(12, "Another older labour source", "test-only-historical-pay thử việc lương."),
        _evidence(13, "Insurance source", "test-only-distinct-insurance bảo hiểm xã hội."),
    ]
    _patch_pipeline(monkeypatch, historical, _settings(), browser)
    captured = await _capture_answer(monkeypatch)

    _response, contexts, latency = await rag_pipeline.run_advanced_rag(query)

    assert any("test-only-current-trial-pay" in context for context in contexts)
    assert any("test-only-current-trial-result" in context for context in contexts)
    assert not any("test-only-historical-trial" in context for context in contexts)
    assert not any("test-only-historical-pay" in context for context in contexts)
    assert any("test-only-distinct-insurance" in context for context in contexts)
    assert captured["contexts"] == contexts
    assert [call[0] for call in browser.search_calls] == ["Bộ luật Lao động 2019"]
    assert browser.search_calls[0][2] is None
    rescue = latency["retrieval_diagnostics"]["primary_law_rescue"]
    assert rescue["provenance"] == "pinned_corpus_store"
    assert rescue["legal_effect_asserted"] is False
    assert rescue["current_effect_status"] == "unverified"


@pytest.mark.asyncio
async def test_rental_deposit_rescue_requires_verified_body_not_title_metadata(
    monkeypatch,
):
    query = "Cọc thuê nhà bị giữ lại xử lý thế nào?"
    civil = _stored_document(
        732,
        "Bộ luật Dân sự 2015",
        "Điều 1. Fixture heading.\n1. test-only-deposit đặt cọc bảo đảm hợp đồng.",
        "2015-11-24",
    )
    browser = _Browser({"Bộ luật Dân sự": civil})
    _patch_pipeline(monkeypatch, [], _settings(), browser)
    captured = await _capture_answer(monkeypatch)

    _response, contexts, latency = await rag_pipeline.run_advanced_rag(query)

    assert any("test-only-deposit" in context for context in contexts)
    assert any("Tiêu đề: Bộ luật Dân sự 2015" in context for context in contexts)
    assert captured["contexts"] == contexts
    assert len(browser.document_calls) <= 2
    rescue = latency["retrieval_diagnostics"]["primary_law_rescue"]
    assert rescue["corpus_documents_loaded"] == 1
    assert rescue["legal_effect_asserted"] is False
    assert rescue["current_effect_status"] == "unverified"


@pytest.mark.asyncio
async def test_primary_rescue_uses_indexed_title_lookup_before_metadata_validation():
    document = _stored_document(
        733,
        "Bộ luật Lao động 2019",
        "Điều 1. Fixture heading.\n1. test-only-primary-trial thử việc tiền lương.",
        "2019-11-20",
    )

    class IndexedOnlyBrowser(_Browser):
        def search(self, query, *, limit, filters=None):
            assert filters is None, "filtered local LIKE search exceeds its 3-second deadline"
            return super().search(query, limit=limit, filters=filters)

    browser = IndexedOnlyBrowser({"Bộ luật Lao động": document})
    result = await rescue_primary_law_evidence(
        "Lương thử việc tính thế nào?", settings=_settings(), browser=browser
    )

    assert result.diagnostics["status"] == "evidence_selected"
    assert [chunk.document_id for chunk in result.evidence] == [733]
    assert result.evidence[0].source_content_sha256 == document.content_sha256


@pytest.mark.asyncio
async def test_primary_rescue_queries_exact_title_when_broad_top_ten_omit_target():
    document = _stored_document(
        736,
        "Bộ luật Dân sự 2015",
        "Điều 1. Đặt cọc\n1. Bên đặt cọc giao tiền để bảo đảm hợp đồng và có quyền nhận lại theo thỏa thuận.",
        "2015-11-24",
    )
    unrelated = _stored_document(
        1, "Nghị quyết thi hành Bộ luật Dân sự", "Điều 1. Không liên quan.", "2005-01-01"
    )
    browser = _Browser(
        {"Bộ luật Dân sự": document},
        search_results={
            "Bộ luật Dân sự": [_hit(unrelated)] * 10,
            "Bộ luật Dân sự 2015": [_hit(document)],
        },
    )
    result = await rescue_primary_law_evidence(
        "Cọc thuê nhà được trả lại thế nào?", settings=_settings(), browser=browser
    )

    assert [chunk.document_id for chunk in result.evidence] == [736]
    assert [call[0] for call in browser.search_calls] == ["Bộ luật Dân sự 2015"]


@pytest.mark.asyncio
async def test_primary_rescue_keeps_bounded_remote_read_after_expansion_deadline(monkeypatch):
    from app.services import v3_article_expansion

    monkeypatch.setattr(v3_article_expansion, "_SOURCE_DOCUMENT_LOAD_TIMEOUT_SECONDS", 0.05)
    document = _stored_document(
        737,
        "Bộ luật Dân sự 2015",
        "Điều 1. Đặt cọc\n1. Bên đặt cọc giao tiền để bảo đảm thực hiện hợp đồng.",
        "2015-11-24",
    )

    class SlowBrowser(_Browser):
        def search(self, query, *, limit, filters=None):
            time.sleep(0.08)
            return super().search(query, limit=limit, filters=filters)

    result = await rescue_primary_law_evidence(
        "Cọc thuê nhà được trả lại thế nào?",
        settings=_settings(),
        browser=SlowBrowser({"Bộ luật Dân sự": document}),
    )

    assert result.diagnostics["status"] == "evidence_selected"


@pytest.mark.asyncio
async def test_primary_rescue_covers_pay_and_end_of_probation_without_article_numbers():
    document = _stored_document(
        734,
        "Bộ luật Lao động 2019",
        "Điều 1. Thời gian thử việc\n"
        "1. Hai bên thỏa thuận thời gian thử việc theo tính chất công việc.\n"
        "2. Thời gian thử việc không được lặp lại cho cùng một công việc.\n"
        "3. Thời gian thử việc phải được báo trước cho người lao động.\n"
        "Điều 2. Tiền lương thử việc\n"
        "1. Người lao động được nhận tiền lương trong thời gian thử việc theo thỏa thuận của hai bên.\n"
        "Điều 3. Kết thúc thời gian thử việc\n"
        "1. Khi kết thúc thời gian thử việc, người sử dụng lao động thông báo kết quả và tiếp tục hợp đồng nếu đạt yêu cầu.",
        "2019-11-20",
    )
    result = await rescue_primary_law_evidence(
        "Công ty không trả lương thử việc; tôi cần làm gì khi hết thời gian thử việc?",
        settings=_settings(),
        browser=_Browser({"Bộ luật Lao động": document}),
    )

    text = "\n".join(chunk.text for chunk in result.evidence)
    assert "Tiền lương thử việc" in text
    assert "Kết thúc thời gian thử việc" in text


@pytest.mark.asyncio
async def test_primary_rescue_rejects_keyword_only_list_when_substantive_deposit_exists():
    document = _stored_document(
        735,
        "Bộ luật Dân sự 2015",
        "Điều 1. Biện pháp bảo đảm thực hiện nghĩa vụ\n"
        "1. Đặt cọc.\n"
        "Điều 2. Đặt cọc\n"
        "1. Bên đặt cọc giao tài sản để bảo đảm giao kết hoặc thực hiện hợp đồng.\n"
        "2. Khi hợp đồng được thực hiện, tài sản đặt cọc được trả lại hoặc trừ vào nghĩa vụ trả tiền, trừ khi có thỏa thuận khác.",
        "2015-11-24",
    )
    result = await rescue_primary_law_evidence(
        "Chủ nhà giữ tiền đặt cọc sau khi tôi bàn giao nhà thuê?",
        settings=_settings(),
        browser=_Browser({"Bộ luật Dân sự": document}),
    )

    assert result.evidence
    assert all("Biện pháp bảo đảm thực hiện nghĩa vụ" not in chunk.text for chunk in result.evidence)


@pytest.mark.asyncio
async def test_rental_handover_keeps_deposit_contract_and_return_facets():
    document = _stored_document(
        736,
        "Bộ luật Dân sự 2015",
        "Điều 1. Đặt cọc\n"
        "1. Khi hợp đồng được thực hiện, tài sản đặt cọc được trả lại hoặc trừ vào nghĩa vụ trả tiền, trừ khi có thỏa thuận khác.\n"
        "Điều 2. Hợp đồng thuê tài sản\n"
        "1. Hợp đồng thuê nhà ở là thỏa thuận về việc giao nhà để sử dụng và trả tiền thuê.\n"
        "Điều 3. Trả lại tài sản thuê\n"
        "1. Bên thuê phải trả lại tài sản thuê theo tình trạng đã thỏa thuận, trừ hao mòn tự nhiên; hư hỏng có thể phát sinh nghĩa vụ bồi thường.\n"
        "2. Quyền và nghĩa vụ của bên thuê nhà khi chậm trả tài sản thuê là trả thêm tiền thuê trong thời gian chậm trả và bồi thường.",
        "2015-11-24",
    )
    result = await rescue_primary_law_evidence(
        "Tôi thuê nhà, chủ giữ tiền đặt cọc sau khi tôi đã bàn giao nhà. "
        "Quyền và nghĩa vụ mỗi bên thế nào?",
        settings=_settings(),
        browser=_Browser({"Bộ luật Dân sự": document}),
    )

    texts = [chunk.text for chunk in result.evidence]
    assert len(texts) == 3
    assert any("tài sản đặt cọc được trả lại" in text for text in texts)
    assert any("Hợp đồng thuê nhà ở" in text for text in texts)
    assert any("trừ hao mòn tự nhiên" in text for text in texts)
    assert not any("chậm trả tài sản thuê" in text for text in texts)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query,settings",
    [
        ("Thử việc theo Bộ luật Lao động 2012 thế nào?", _settings()),
        ("Thử việc thế nào?", _settings(legacy=True)),
    ],
)
async def test_conflicting_law_year_or_legacy_query_bypasses_primary_title_rescue(
    monkeypatch, query, settings
):
    browser = _Browser({})
    _patch_pipeline(monkeypatch, [], settings, browser)
    await _capture_answer(monkeypatch)

    await rag_pipeline.run_advanced_rag(query)

    assert browser.search_calls == []
    assert browser.document_calls == []


@pytest.mark.asyncio
async def test_scoped_outcome_bypasses_primary_title_rescue(monkeypatch):
    browser = _Browser({})
    settings = _settings()
    _patch_pipeline(monkeypatch, [], settings, browser)
    await _capture_answer(monkeypatch)
    scoped = rag_pipeline.RetrievalOutcome(
        evidence=[], latency={}, status="ok", diagnostics={}
    )

    await rag_pipeline.run_advanced_rag(
        "Thử việc thế nào?", scoped_outcome=scoped
    )

    assert browser.search_calls == []
    assert browser.document_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize('query', [
    'Tại ngày 29/10/2026, lương thử việc tối thiểu thế nào?',
    'Thử việc theo quy định năm 2019 thế nào?',
    'Điều 26 Bộ luật Lao động 2019 quy định tiền lương thử việc thế nào?',
    'Điều 26 Bộ luật Lao động 45/2019/QH14 quy định tiền lương thử việc thế nào?',
    'Theo Bộ luật Lao động ban hành năm 2019, tiền lương thử việc thế nào?',
    'Theo Bộ luật Lao động được ban hành năm 2019, tiền lương thử việc thế nào?',
    'Theo Bộ luật Lao động tại ngày 29/10/2026, tiền lương thử việc thế nào?',
    'Theo Bộ luật Lao động, tính đến năm 2026 tiền lương thử việc thế nào?',
])
async def test_temporal_or_compatible_legal_reference_allows_bounded_rescue(query):
    document = _stored_document(741, 'Bộ luật Lao động 2019',
        'Điều 25. Thời gian thử việc\n1. test-only-duration Thời gian thử việc được thỏa thuận.\n'
        'Điều 26. Tiền lương thử việc\n1. test-only-wage Tiền lương thử việc do hai bên thỏa thuận.', '2019-11-20')
    browser = _Browser({'Bộ luật Lao động': document})
    result = await rescue_primary_law_evidence(query, settings=_settings(), browser=browser)
    assert result.evidence
    assert result.diagnostics['status'] == 'evidence_selected'
    assert result.diagnostics['legal_effect_asserted'] is False
    assert len(browser.search_calls) == 1
    assert len(browser.document_calls) == 1
    assert len(result.evidence) <= 3
    if 'Điều 26' in query:
        assert all(chunk.article == 'Điều 26' for chunk in result.evidence)


@pytest.mark.asyncio
@pytest.mark.parametrize('query', [
    'Theo Bộ luật Lao động 2012, tiền lương thử việc thế nào?',
    'Theo Bộ luật Lao động năm 2012, tiền lương thử việc thế nào?',
    'Theo Bộ luật Lao động (2012), tiền lương thử việc thế nào?',
    'Theo Bộ luật Lao động ban hành năm 2012, tiền lương thử việc thế nào?',
    'Theo Bộ luật Lao động được ban hành năm 2012, tiền lương thử việc thế nào?',
    'Theo Bộ luật Lao động được ban hành vào năm 2012, tiền lương thử việc thế nào?',
    'Theo Bộ luật Lao động ban hành vào năm 2012, tiền lương thử việc thế nào?',
    'Theo Bộ luật Hình sự 2015, giữ tiền đặt cọc có vi phạm không?',
    'Luật Nhà ở 2023 có quy định tiền đặt cọc thuê nhà không?',
    'Luật 10/2012/QH13 quy định tiền lương thử việc thế nào?',
])
async def test_explicit_different_law_scope_never_substitutes_curated_law(query):
    browser = _Browser({})
    result = await rescue_primary_law_evidence(query, settings=_settings(), browser=browser)
    assert not result.evidence
    assert result.diagnostics['status'] == 'bypassed_explicit_scope'
    assert browser.search_calls == []


@pytest.mark.asyncio
async def test_named_civil_law_never_rescues_labor_law_for_overlapping_wage_term():
    browser = _Browser({})
    await rescue_primary_law_evidence(
        'Theo Bộ luật Dân sự 2015, tiền lương được dùng đặt cọc thuê nhà có phải hoàn lại không?',
        settings=_settings(), browser=browser)
    assert [call[0] for call in browser.search_calls] == ['Bộ luật Dân sự 2015']


@pytest.mark.asyncio
async def test_explicit_civil_clause_rescue_keeps_requested_clause_only():
    document = _stored_document(742, 'Bộ luật Dân sự 2015',
        'Điều 328. Đặt cọc\n1. test-only-definition Đặt cọc để bảo đảm giao kết hợp đồng.\n'
        '2. test-only-return Tài sản đặt cọc được trả lại khi hợp đồng được giao kết, trừ thỏa thuận khác.\n'
        'Điều 329. Ký cược\n1. test-only-other Đặt cọc có thỏa thuận riêng.', '2015-11-24')
    browser = _Browser({'Bộ luật Dân sự': document})
    result = await rescue_primary_law_evidence(
        'Giả định chỉ áp dụng khoản 2 Điều 328 Bộ luật Dân sự 2015: trả tiền đặt cọc thế nào?',
        settings=_settings(), browser=browser)
    assert len(result.evidence) == 1
    assert result.evidence[0].article == 'Điều 328'
    assert result.evidence[0].clause == '2'
    assert 'test-only-return' in result.evidence[0].text
    assert result.evidence[0].citation.endswith('Điều 328, Khoản 2')


@pytest.mark.asyncio
async def test_article_range_rescue_keeps_complete_bounded_article_exception():
    content = (
        "Điều 6. Test-only out-of-range heading\n"
        "1. test-only-out-of-range Đặt cọc thuê nhà được bàn giao theo hồ sơ.\n"
        "Điều 7. Test-only requested article\n"
        "1. test-only-deposit Bên đặt cọc giao tài sản để bảo đảm hợp đồng thuê nhà.\n"
        "2. test-only-handover Khi bàn giao nhà thuê, hai bên xác nhận tình trạng tài sản.\n"
        "3. test-only-low-overlap-exception Trường hợp có thỏa thuận riêng bằng văn bản, cách xử lý theo điều kiện đó.\n"
        "4. test-only-final-provision Các bên thực hiện quyền và nghĩa vụ đã xác nhận.\n"
        "Điều 8. Test-only second requested article\n"
        "1. test-only-in-range-end Giao dịch thuê nhà được xác nhận theo văn bản."
    )
    document = _stored_document(
        744, 'Bộ luật Dân sự 2015', content, '2015-11-24'
    )
    browser = _Browser({'Bộ luật Dân sự': document})

    result = await rescue_primary_law_evidence(
        'Theo Bộ luật Dân sự 2015, Điều 7-8: tiền đặt cọc thuê nhà sau khi bàn giao xử lý thế nào?',
        settings=_settings(),
        browser=browser,
    )

    assert result.diagnostics['status'] == 'evidence_selected'
    assert result.evidence
    assert all(chunk.article in {'Điều 7', 'Điều 8'} for chunk in result.evidence)
    assert any(
        chunk.clause is None
        and 'test-only-low-overlap-exception' in chunk.text
        for chunk in result.evidence
    )


@pytest.mark.asyncio
async def test_missing_requested_article_never_rescues_unrelated_article():
    document = _stored_document(743, 'Bộ luật Lao động 2019',
        'Điều 26. Tiền lương thử việc\n1. test-only-wage Tiền lương thử việc do hai bên thỏa thuận.', '2019-11-20')
    browser = _Browser({'Bộ luật Lao động': document})
    result = await rescue_primary_law_evidence(
        'Có Điều 9999 Bộ luật Lao động quy định tiền lương thử việc không?',
        settings=_settings(), browser=browser)
    assert browser.search_calls
    assert not result.evidence


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_case",
    ["wrong_title", "future_date", "missing_date", "wrong_id", "bad_hash"],
)
async def test_unverified_primary_law_candidates_are_rejected_and_diagnosed(
    monkeypatch, failure_case
):
    query = "Thử việc thế nào?"
    content = "Điều 1. Test-only heading.\n1. test-only-primary-trial thử việc."
    digest = "0" * 64 if failure_case == "bad_hash" else None
    issued = "2999-01-01" if failure_case == "future_date" else "2019-11-20"
    if failure_case == "missing_date":
        issued = ""
    document = _stored_document(
        77, "Bộ luật Lao động 2019", content, issued
    )
    document.content_sha256 = digest or document.content_sha256
    overrides = {}
    if failure_case == "wrong_title":
        overrides = {"title": "Dự thảo Bộ luật Lao động 2019"}
    if failure_case == "wrong_id":
        overrides = {"document_id": 999}
    browser = _Browser(
        {"Bộ luật Lao động": document},
        search_results={"Bộ luật Lao động 2019": [_hit(document, **overrides)]},
    )
    _patch_pipeline(monkeypatch, [], _settings(), browser)
    await _capture_answer(monkeypatch)

    _response, contexts, latency = await rag_pipeline.run_advanced_rag(query)

    assert not any("test-only-primary-trial" in context for context in contexts)
    diagnostics = latency["retrieval_diagnostics"]["primary_law_rescue"]
    assert diagnostics["status"] != "evidence_selected"
    assert diagnostics["candidates"]
    assert diagnostics["legal_effect_asserted"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["search", "load"])
async def test_primary_law_read_failures_are_observable_without_raw_exception_text(
    monkeypatch, failure_stage
):
    private_error = "test-only exception detail must not escape"
    content = "Điều 1. Test-only heading.\n1. test-only-primary-trial thử việc."
    document = _stored_document(
        78, "Bộ luật Lao động 2019", content, "2019-11-20"
    )
    browser = _Browser(
        {"Bộ luật Lao động": document},
        search_error=RuntimeError(private_error) if failure_stage == "search" else None,
        load_error=RuntimeError(private_error) if failure_stage == "load" else None,
    )
    _patch_pipeline(monkeypatch, [], _settings(), browser)
    await _capture_answer(monkeypatch)

    _response, _contexts, latency = await rag_pipeline.run_advanced_rag(
        "Thử việc thế nào?"
    )

    diagnostics = latency["retrieval_diagnostics"]["primary_law_rescue"]
    assert diagnostics["status"] in {"unavailable", "search_error", "load_error"}
    assert private_error not in str(diagnostics)


@pytest.mark.asyncio
async def test_primary_law_lookup_timeout_is_observable_and_stops_before_body_load(
    monkeypatch,
):
    import app.services.primary_law_rescue as rescue_module

    content = "Điều 1. Test-only heading.\n1. test-only-primary-trial thử việc."
    document = _stored_document(
        81, "Bộ luật Lao động 2019", content, "2019-11-20"
    )

    class _SlowBrowser(_Browser):
        def search(self, query, *, limit, filters=None):
            time.sleep(0.05)
            return super().search(query, limit=limit, filters=filters)

    browser = _SlowBrowser({"Bộ luật Lao động": document})
    monkeypatch.setattr(
        rescue_module, "_PRIMARY_RESCUE_TIMEOUT_SECONDS", 0.001
    )
    _patch_pipeline(monkeypatch, [], _settings(), browser)
    await _capture_answer(monkeypatch)

    _response, _contexts, latency = await rag_pipeline.run_advanced_rag(
        "Thử việc thế nào?"
    )
    await asyncio.sleep(0.06)

    diagnostics = latency["retrieval_diagnostics"]["primary_law_rescue"]
    assert diagnostics["status"] == "timeout"
    assert browser.document_calls == []


@pytest.mark.asyncio
async def test_primary_rescue_uses_complete_units_with_shared_three_context_budget(
    monkeypatch,
):
    query = "Thử việc có được trả lương? Bảo hiểm xã hội ra sao?"
    pay_words = ["test-only-pay-unit", "thử", "việc", "tiền", "lương"] + [
        "payfiller" for _ in range(150)
    ]
    result_words = ["test-only-result-unit", "kết", "thúc", "thử", "việc"] + [
        "resultfiller" for _ in range(150)
    ]
    result_words.append("test-only-exception-tail")
    content = (
        "Điều 1. Fixture heading.\n1. "
        + " ".join(pay_words)
        + "\nĐiều 2. Fixture heading.\n1. "
        + " ".join(result_words)
    )
    primary = _stored_document(
        733, "Bộ luật Lao động 2019", content, "2019-11-20"
    )
    browser = _Browser({"Bộ luật Lao động": primary})
    insurance = _evidence(80, "Insurance source", "test-only-insurance bảo hiểm xã hội.")
    _patch_pipeline(monkeypatch, [insurance], _settings(), browser)
    await _capture_answer(monkeypatch)

    _response, contexts, _latency = await rag_pipeline.run_advanced_rag(query)

    assert len(contexts) <= 3
    used_tokens = sum(
        len(context.split()) + len(f"[Tài liệu tham khảo #{index}]".split())
        for index, context in enumerate(contexts, start=1)
    )
    assert used_tokens <= 720
    assert any("test-only-pay-unit" in context for context in contexts)
    assert any("test-only-result-unit" in context for context in contexts)
    assert any("test-only-exception-tail" in context for context in contexts)
    assert any("test-only-insurance" in context for context in contexts)


@pytest.mark.asyncio
async def test_primary_selection_reserves_one_of_three_slots_for_a_distinct_topic(
    monkeypatch,
):
    query = "Thử việc có được trả lương? Bảo hiểm xã hội ra sao?"
    content = "\n".join(
        f"Điều {index}. Fixture heading.\n1. test-only-labor-{index} thử việc tiền lương."
        for index in range(1, 4)
    )
    primary = _stored_document(
        734, "Bộ luật Lao động 2019", content, "2019-11-20"
    )
    browser = _Browser({"Bộ luật Lao động": primary})
    insurance = _evidence(
        735, "Insurance fixture", "test-only-insurance bảo hiểm xã hội."
    )
    _patch_pipeline(monkeypatch, [insurance], _settings(), browser)
    await _capture_answer(monkeypatch)

    _response, contexts, latency = await rag_pipeline.run_advanced_rag(query)

    assert len(contexts) == 3
    assert sum("test-only-labor-" in context for context in contexts) == 2
    assert any("test-only-insurance" in context for context in contexts)
    assert latency["retrieval_diagnostics"]["topic_coverage"]["status"] == "covered"


@pytest.mark.asyncio
async def test_trial_rescue_rejects_disjoint_token_coincidences(monkeypatch):
    query = (
        "Tôi đang thử việc nhưng công ty nói không cần trả lương cho thời gian này. "
        "Tôi có được trả lương không, và phải làm gì khi hết thời gian thử việc?"
    )
    content = (
        "Điều 1. Tiền lương thử việc.\n"
        "1. test-only-trial-pay Tiền lương của người lao động trong thời gian thử việc do hai bên thỏa thuận.\n"
        "Điều 2. Kết thúc thời gian thử việc.\n"
        "1. test-only-trial-end Khi kết thúc thời gian thử việc, người sử dụng lao động phải thông báo kết quả thử việc.\n"
        "Điều 3. Trả lương thông qua người cai thầu.\n"
        "1. test-only-generic-wage Người lao động phải tuân thủ quy định và trả lương theo ngày làm việc.\n"
        "Điều 4. Hiệu lực thi hành.\n"
        "1. test-only-validity Kỳ họp thứ 8 quy định ngày làm việc và hiệu lực thi hành."
    )
    primary = _stored_document(
        736, "Bộ luật Lao động 2019", content, "2019-11-20"
    )
    browser = _Browser({"Bộ luật Lao động": primary})
    _patch_pipeline(monkeypatch, [], _settings(), browser)
    await _capture_answer(monkeypatch)

    _response, contexts, latency = await rag_pipeline.run_advanced_rag(query)

    joined = "\n".join(contexts)
    assert "test-only-trial-pay" in joined
    assert "test-only-trial-end" in joined
    assert "test-only-generic-wage" not in joined
    assert "test-only-validity" not in joined
    assert latency["retrieval_diagnostics"]["primary_law_rescue"]["selected_chunk_count"] == 2


@pytest.mark.asyncio
async def test_rental_query_rejects_guardianship_deposit_mention(monkeypatch):
    query = (
        "Tôi thuê nhà, chủ nhà giữ tiền đặt cọc sau khi tôi đã bàn giao nhà. "
        "Tôi cần biết quyền và nghĩa vụ của mỗi bên như thế nào?"
    )
    content = (
        "Điều 1. Đặt cọc.\n"
        "1. test-only-rental-deposit Đặt cọc là việc một bên giao cho bên kia một khoản tiền để bảo đảm giao kết hoặc thực hiện hợp đồng.\n"
        "2. test-only-rental-return Khi hợp đồng được giao kết, tài sản đặt cọc được trả lại hoặc trừ vào nghĩa vụ thanh toán.\n"
        "Điều 2. Quản lý tài sản của người được giám hộ.\n"
        "1. test-only-guardianship Việc cho thuê, cho mượn, đặt cọc tài sản của người được giám hộ phải được chấp thuận."
    )
    civil = _stored_document(
        737, "Bộ luật Dân sự 2015", content, "2015-11-24"
    )
    browser = _Browser({"Bộ luật Dân sự": civil})
    _patch_pipeline(monkeypatch, [], _settings(), browser)
    await _capture_answer(monkeypatch)

    _response, contexts, latency = await rag_pipeline.run_advanced_rag(query)

    joined = "\n".join(contexts)
    assert "test-only-rental-deposit" in joined
    assert "test-only-rental-return" in joined
    assert "test-only-guardianship" not in joined
    assert latency["retrieval_diagnostics"]["primary_law_rescue"]["selected_chunk_count"] == 2


def test_primary_rescue_test_fixtures_make_no_legal_validity_claims():
    fixture = _stored_document(
        1, "Bộ luật Lao động 2019", "test-only fixture", "2019-11-20"
    )

    assert fixture.metadata.document_number == "TEST-1"
    assert fixture.content_sha256 == hashlib.sha256(
        fixture.content.encode("utf-8")
    ).hexdigest()
