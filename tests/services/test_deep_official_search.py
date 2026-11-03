"""Provider-free contracts for request-scoped official reading; synthetic law only."""
import asyncio
import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest


def source(url, text, **extra):
    return {
        "url": url, "title": "Quy định tổng hợp", "text": text,
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "method": "visible_html_text", "legal_effect_status": "unverified",
        **extra,
    }


def test_excluded_future_source_does_not_change_retained_effect_diagnostics():
    from app.services.deep_official_search import pack_sources
    from app.services.official_search_plan import build_official_search_plan
    old = source('https://vanban.chinhphu.vn/?docid=1',
        'Điều 1. Giấy phép môi trường\nNhập khẩu phế liệu cần đáp ứng điều kiện.',
        document_number='11/2020/ND-TEST', issued_date='2020-01-01')
    future = source('https://vanban.chinhphu.vn/?docid=2',
        'Điều 1. Giấy phép môi trường\nVăn bản này có hiệu lực từ ngày 01 tháng 01 năm 2028.',
        document_number='12/2027/ND-TEST', issued_date='2027-01-01',
        reported_effective_from='2027-02-01')
    plan = build_official_search_plan('Tại ngày 29/10/2026, nhập khẩu phế liệu cần giấy phép môi trường không?')
    contexts, report = pack_sources([old, future], plan)
    assert len(contexts) == 1
    assert report['legal_effect_status'] == 'unverified'
    assert any(x['reason'] == 'issued_after_requested_date' for x in report['alternative_versions'])


@pytest.mark.parametrize('discard', ['metadata_only', 'hash_mismatch', 'unrelated_topic'])
def test_discarded_source_cannot_poison_selected_evidence_status(discard):
    from app.services.deep_official_search import pack_sources
    from app.services.official_search_plan import build_official_search_plan
    good = source('https://vanban.chinhphu.vn/?docid=1',
        'Điều 1. Giấy phép môi trường\nNhập khẩu phế liệu cần đáp ứng điều kiện.',
        document_number='11/2020/ND-TEST', issued_date='2020-01-01')
    heading = 'Giấy phép môi trường' if discard != 'unrelated_topic' else 'Sản xuất thuốc'
    bad = source('https://vanban.chinhphu.vn/?docid=2',
        f'Điều 2. {heading}\nVăn bản này có hiệu lực từ ngày 01 tháng 01 năm 2028.',
        document_number='12/2020/ND-TEST', issued_date='2020-02-01',
        reported_effective_from='2027-01-01')
    if discard == 'metadata_only':
        bad['content_status'] = 'metadata_only'
    elif discard == 'hash_mismatch':
        bad['sha256'] = '0' * 64
    contexts, report = pack_sources([good, bad], build_official_search_plan(
        'Tại ngày 29/10/2026, nhập khẩu phế liệu cần giấy phép môi trường không?'))
    assert len(contexts) == 1
    assert report['legal_effect_status'] == 'unverified'
    assert 'Hiệu lực pháp lý: unverified' in contexts[0]


@pytest.mark.parametrize('invalid_first', [False, True])
@pytest.mark.parametrize('title', ['Quy định tổng hợp', 'Văn bản hợp nhất Luật Mẫu'])
def test_untrusted_mirror_neither_poison_nor_suppress_valid_source(invalid_first, title):
    from app.services.deep_official_search import pack_sources
    from app.services.official_search_plan import build_official_search_plan
    good = source('https://vanban.chinhphu.vn/?docid=1',
        'Điều 1. Giấy phép môi trường\nNhập khẩu phế liệu cần điều kiện.',
        title=title, document_number='11/2020/ND-TEST', reported_effective_from='01/01/2021')
    bad = {**good, 'url': 'https://example.com/untrusted', 'reported_effective_from': '02/01/2021'}
    contexts, report = pack_sources([bad, good] if invalid_first else [good, bad],
        build_official_search_plan('Nhập khẩu phế liệu có cần giấy phép môi trường không?'))
    assert len(contexts) == 1
    assert 'example.com' not in contexts[0]
    assert report['legal_effect_status'] == 'unverified'


def test_recognized_topic_does_not_admit_generic_word_overlap_from_other_domain():
    from app.services.deep_official_search import pack_sources
    from app.services.official_search_plan import build_official_search_plan
    query = 'Tại ngày 29/10/2026, nhập khẩu phế liệu có cần giấy phép môi trường không?'
    plan = build_official_search_plan(query)
    unrelated = source('https://vanban.chinhphu.vn/?docid=2',
        'Điều 1. Nguyên liệu sản xuất thuốc\nCơ sở nhập khẩu nguyên liệu sản xuất thuốc gửi hồ sơ kỹ thuật đến cơ quan có thẩm quyền.',
        document_number='44/2026/TT-BYT', issued_date='2026-10-20')
    relevant = source('https://vanban.chinhphu.vn/?docid=1',
        'Điều 2. Giấy phép môi trường\nCơ sở nhập khẩu phế liệu phải đáp ứng điều kiện. KẾT THÚC.',
        document_number='08/2022/NĐ-CP', issued_date='2022-01-10')
    contexts, report = pack_sources([unrelated, relevant], plan)
    assert len(contexts) == 1
    assert 'KẾT THÚC.' in contexts[0]
    assert 'thuốc' not in contexts[0]
    assert any(x['reason'] == 'unrelated_topic' for x in report['excluded_blocks'])


@pytest.mark.parametrize('title', ['Quy định tổng hợp', 'Văn bản hợp nhất Luật Mẫu'])
def test_known_issue_date_after_cutoff_is_excluded_for_every_instrument(title):
    from app.services.deep_official_search import pack_sources
    from app.services.official_search_plan import build_official_search_plan
    future = source('https://vanban.chinhphu.vn/?docid=2',
        'Điều 1. Giấy phép môi trường\nNhập khẩu phế liệu phải đáp ứng điều kiện.',
        title=title, document_number='44/2026/TT-TEST', issued_date='2026-10-30')
    contexts, report = pack_sources([future], build_official_search_plan(
        'Tại ngày 29/10/2026, nhập khẩu phế liệu có cần giấy phép môi trường không?'))
    assert contexts == []
    assert any(x['reason'] == 'issued_after_requested_date' for x in report['alternative_versions'])


def test_unrecognized_narrative_gets_private_facet_queries():
    from app.services.official_search_plan import build_official_search_plan
    plan = build_official_search_plan(
        "Tôi tên Nguyễn Văn Bình, email binh@example.com, ở số 25 đường Hoa Mai; "
        "hàng xóm dựng rào chắn lối đi chung thì giải quyết thế nào?"
    )
    assert 1 <= len(plan.queries) <= 5
    assert any("lối đi" in q for q in plan.queries)
    assert not any(x in " ".join(plan.queries) for x in ("Nguyễn", "Bình", "25", "Hoa Mai", "@"))
    assert build_official_search_plan("Tôi là ai?").status == "unknown"


def test_subject_survives_following_generic_current_question():
    from app.services.official_search_plan import build_official_search_plan
    plan = build_official_search_plan("Tôi muốn nhập khẩu phế liệu. Hiện nay có cần giấy phép môi trường không?")
    assert any("phế liệu" in q for q in plan.queries)
    assert any("giấy phép môi trường" in q for q in plan.queries)
    assert plan.current_required


def test_whole_articles_and_budget_reasons():
    from app.services.deep_official_search import pack_sources
    from app.services.official_search_plan import DEEP_READING, build_official_search_plan
    text = "Điều 1. Lối đi chung\n" + "lối đi chung " * 300 + "KẾT THÚC.\nĐiều 2. Hiệu lực\nVăn bản tổng hợp."
    item = source("https://vanban.chinhphu.vn/?docid=1", text)
    contexts, diagnostics = pack_sources([item], build_official_search_plan("lối đi chung"), DEEP_READING)
    assert any("KẾT THÚC." in c for c in contexts)
    small, report = pack_sources([item], build_official_search_plan("lối đi chung"), replace(DEEP_READING, context_tokens=720))
    assert not any("Điều 1." in c for c in small)
    assert any(r["reason"] == "context_budget" for r in report["excluded_blocks"])
    assert diagnostics["budget_unit"] == "approx_whitespace_tokens"


@pytest.mark.parametrize('reference', ['Điều 25', 'các điều 24–25'])
def test_requested_articles_survive_topic_distractors_under_block_limit(reference):
    from app.services.deep_official_search import pack_sources
    from app.services.official_search_plan import DEEP_READING, build_official_search_plan
    text = ('Điều 24. Điều kiện\nThử việc có điều kiện riêng.\n'
            'Điều 25. Phân nhóm\nNhóm A; nhóm B; các công việc khác. KẾT THÚC.\n'
            'Điều 50. Thử việc và tiền lương\nThử việc tiền lương trong quan hệ lao động.\n'
            'Điều 51. Thử việc tiền lương\nThử việc và tiền lương lao động.')
    item = source('https://vanban.chinhphu.vn/?docid=1', text,
                  document_number='45/2019/QH14')
    plan = build_official_search_plan(f'Theo {reference} 45/2019/QH14, thử việc thế nào?')
    profile = replace(DEEP_READING, evidence_limit=2 if '24' in reference else 1)
    contexts, report = pack_sources([item], plan, profile)
    assert any('Điều 25. Phân nhóm' in c and 'KẾT THÚC.' in c for c in contexts)
    if '24' in reference:
        assert any('Điều 24. Điều kiện' in c for c in contexts)
    assert len(contexts) <= profile.evidence_limit
    assert report['context_tokens'] <= profile.context_tokens


def test_requested_article_priority_respects_explicit_document_identity():
    from app.services.deep_official_search import pack_sources
    from app.services.official_search_plan import DEEP_READING, build_official_search_plan
    right = source('https://vanban.chinhphu.vn/?docid=1',
                   'Điều 25. Phân nhóm\nNội dung đúng phạm vi.', document_number='45/2019/QH14')
    wrong = source('https://vanban.chinhphu.vn/?docid=2',
                   'Điều 25. Thử việc\nThử việc tiền lương lao động.', document_number='99/2020/QH14')
    contexts, _ = pack_sources([wrong, right],
        build_official_search_plan('Điều 25 45/2019/QH14 quy định thử việc thế nào?'),
        replace(DEEP_READING, evidence_limit=1))
    assert len(contexts) == 1
    assert 'Nội dung đúng phạm vi.' in contexts[0]


def test_numeric_article_request_does_not_prioritize_letter_suffix():
    from app.services.deep_official_search import pack_sources
    from app.services.official_search_plan import DEEP_READING, build_official_search_plan
    item = source('https://vanban.chinhphu.vn/?docid=1',
                  'Điều 25. Phân nhóm\nĐúng Điều được hỏi.\n'
                  'Điều 25a. Thử việc tiền lương\nThử việc tiền lương lao động.',
                  document_number='45/2019/QH14')
    contexts, _ = pack_sources([item],
        build_official_search_plan('Điều 25 45/2019/QH14 quy định thử việc thế nào?'),
        replace(DEEP_READING, evidence_limit=1))
    assert len(contexts) == 1
    assert 'Đúng Điều được hỏi.' in contexts[0]


@pytest.mark.asyncio
async def test_deadline_keeps_completed_sources_and_bounds_concurrency():
    from app.services.deep_official_search import search_and_read
    from app.services.official_search_plan import DEEP_READING
    active = peak = 0
    urls = [f"https://vanban.chinhphu.vn/?docid={n}" for n in (1, 2)]
    class Provider:
        async def search(self, query, *, limit):
            return SimpleNamespace(results=[SimpleNamespace(url=u, title="lối đi chung", document_number="", issued_date="", snippet="") for u in urls], errors=())
    async def reader(url, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            assert kwargs["deep_read"] and kwargs["smart_pages"] and not kwargs["use_ocr"]
            assert "lối đi" in kwargs["question"]
            if url == urls[1]:
                await asyncio.sleep(1)
            return source(url, "Điều 1. Lối đi chung\nBảo đảm lối đi chung.\nĐiều 2. Khác\nKết thúc.")
        finally:
            active -= 1
    result = await search_and_read("lối đi chung", providers=[Provider()], reader=reader,
        profile=replace(DEEP_READING, discovery_seconds=.1, read_seconds=.2, total_seconds=1))
    assert result.contexts
    assert result.status == "partial"
    assert result.diagnostics["sources_read"] == 1
    assert result.diagnostics["discovered_urls"] == urls
    assert peak <= 2 and active == 0
    assert result.diagnostics["read_failures"] >= 1


def test_metadata_alone_cannot_prove_effect_and_conflicts_survive():
    from app.services.deep_official_search import pack_sources
    from app.services.official_search_plan import DEEP_READING, build_official_search_plan
    a = source("https://vanban.chinhphu.vn/?docid=1", "Điều 1. Lối đi chung\nQuy định lối đi chung.\nĐiều 2. Khác\nHết.",
               document_number="01/2099/QH99", reported_effective_from="01/01/2099")
    b = {**a, "url": "https://congbao.chinhphu.vn/van-ban/test-2.htm", "reported_effective_from": "02/01/2099"}
    _, report = pack_sources([a, b], build_official_search_plan("lối đi chung hiện nay"), DEEP_READING)
    assert report["legal_effect_status"] == "conflicting"
    _, report = pack_sources([a], build_official_search_plan("lối đi chung hiện nay"), DEEP_READING)
    assert report["legal_effect_status"] == "unverified"


@pytest.mark.asyncio
async def test_profile_survives_final_prompt_without_global_budget_change(monkeypatch):
    from app.services import rag_pipeline as pipeline
    from app.services.official_search_plan import DEEP_READING, ProfiledContexts
    seen = []
    async def generate(prompt, system, **kwargs):
        seen.append(prompt)
        return pipeline.LLMGenerationResult(text="ok", observed_provider="test", observed_model="test")
    monkeypatch.setattr(pipeline, "generate_llm_response_with_metadata", generate)
    text = "Điều 1. " + "chứng cứ " * 500 + "DẤU CUỐI"
    await pipeline.generate_response_with_metadata("hỏi", "hỏi", ProfiledContexts([text], DEEP_READING))
    assert "DẤU CUỐI" in seen[-1]
    await pipeline.generate_response_with_metadata("hỏi", "hỏi", [text])
    assert len(seen) == 1  # Ordinary callers still use their small budget.


def test_deep_pdf_reads_beyond_old_probe_and_retains_page_map(monkeypatch):
    from pypdf import PdfWriter
    from app.services import official_document_reader as reader
    writer = PdfWriter()
    for _ in range(35):
        writer.add_blank_page(width=100, height=100)
    out = BytesIO()
    writer.write(out)
    monkeypatch.setattr(reader, "_page_text", lambda _, n: "lối đi chung" if n == 13 else "nội dung khác")
    result, _ = reader._smart_window(out.getvalue(), "lối đi chung", False, 20, deep_read=True)
    assert 13 in [p["page"] for p in result["pages"]]
    assert len(result["pages"]) <= 20
    assert len(result["inspected_pages"]) <= 40
    with pytest.raises(Exception, match="source_page_window_invalid"):
        reader._smart_window(out.getvalue(), "lối đi chung", False, 20)


@pytest.mark.asyncio
async def test_vbpl_forbidden_is_typed_and_never_bypassed():
    from app.services.vbpl_search import VbplClient
    from app.services.official_web_search import OfficialPortalError
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(403, text="Forbidden")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = VbplClient(client=client)
        for _ in range(2):
            with pytest.raises(OfficialPortalError, match="vbpl_http_403"):
                await provider.search("lối đi chung", limit=3)
    assert len(calls) == 1


def test_incomplete_last_article_is_not_answer_evidence():
    from app.services.deep_official_search import pack_sources
    from app.services.official_search_plan import DEEP_READING, build_official_search_plan
    item = source("https://vanban.chinhphu.vn/?docid=1", "Điều 1. Lối đi chung\nĐoạn chưa kết thúc", truncated=True)
    contexts, report = pack_sources([item], build_official_search_plan("lối đi chung"), DEEP_READING)
    assert not contexts
    assert any(r["reason"] == "incomplete_article" for r in report["excluded_blocks"])


@pytest.mark.asyncio
async def test_deep_web_body_is_never_persisted_to_chat_log(monkeypatch):
    from app import database
    from app.services.evidence_presenter import EphemeralOfficialEvidenceContext
    monkeypatch.setattr(database.settings, "APP_ENV", "development")
    document = await database.log_interaction("deep-memory-only", "question", "answer", [
        "existing corpus context", EphemeralOfficialEvidenceContext("PRIVATE TRANSIENT WEB BODY")
    ], False)
    assert document["contexts"] == ["existing corpus context"]
    assert "PRIVATE TRANSIENT WEB BODY" not in str(document)
    assert document["metrics"]["context_count"] == 2


@pytest.mark.asyncio
async def test_real_pipeline_passes_large_web_evidence_to_final_prompt(monkeypatch):
    from app.services import rag_pipeline as pipeline
    from app.services.chat_official_supplement import supplement_official_evidence
    cfg = SimpleNamespace(CHAT_OFFICIAL_DEEP_READING_ENABLED=True, USE_LEGACY_FREE_PIPELINE=False,
        CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED=True, OFFICIAL_WEB_RESEARCH_ENABLED=True,
        FINAL_EVIDENCE_LIMIT=3, LLM_CONTEXT_MAX_TOKENS=720, LLM_MAX_OUTPUT_TOKENS=1536)
    monkeypatch.setattr(pipeline, "get_settings", lambda: cfg)
    async def retrieve(*args):
        return pipeline.RetrievalOutcome(evidence=[], latency={}, status="ok", diagnostics={})
    async def rescue(*args, **kwargs):
        return SimpleNamespace(evidence=[], diagnostics={})
    class Provider:
        async def search(self, query, **kwargs):
            return SimpleNamespace(results=[SimpleNamespace(url="https://vanban.chinhphu.vn/?docid=1",
                title="lối đi chung", snippet="", document_number="")], errors=())
    async def reader(url, **kwargs):
        return source(url, "Điều 1. Lối đi chung\n" + "lối đi chung " * 300 + "DẤU CUỐI.\nĐiều 2. Khác\nKết.")
    async def supplement(query, **kwargs):
        return await supplement_official_evidence(query, provider=Provider(), reader=reader, **kwargs)
    seen = []
    async def generate(prompt, system, **kwargs):
        seen.append(prompt)
        return pipeline.LLMGenerationResult(text="answer", observed_provider="test", observed_model="test")
    monkeypatch.setattr(pipeline, "retrieve_configured_legal_evidence", retrieve)
    monkeypatch.setattr(pipeline, "rescue_primary_law_evidence", rescue)
    monkeypatch.setattr(pipeline, "supplement_official_evidence", supplement)
    monkeypatch.setattr(pipeline, "generate_llm_response_with_metadata", generate)
    answer, contexts, latency = await pipeline.run_advanced_rag("lối đi chung")
    assert latency["retrieval_diagnostics"]["official_supplement"]["status"] in {"ok", "partial"}, latency["retrieval_diagnostics"]["official_supplement"]
    assert answer == "answer", latency["retrieval_diagnostics"]
    assert "DẤU CUỐI" in seen[0] and len(contexts[0].split()) > 720
    assert latency["retrieval_diagnostics"]["context_profile"]["max_tokens"] == 8000


def test_shared_planner_keeps_explicit_reference_and_legal_date():
    from app.services.official_search_plan import build_official_search_plan
    plan = build_official_search_plan("Lối đi chung theo 01/2099/QH99 tại ngày 01/01/2099?")
    assert any("01/2099/QH99" in q for q in plan.queries)
    assert plan.as_of == "01/01/2099" and plan.current_required


@pytest.mark.asyncio
async def test_deep_reader_rejects_redirect_to_unapproved_origin_and_marks_metadata():
    from app.services.trusted_source_reader import read_source
    requests = []
    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://example.invalid/secret"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError, match="source_origin_not_approved"):
            await read_source("https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=1", client=client,
                              smart_pages=True, deep_read=True, page_limit=20)
    assert len(requests) == 1


def test_effect_conflict_between_article_and_metadata():
    from app.services.deep_official_search import pack_sources
    from app.services.official_search_plan import DEEP_READING, build_official_search_plan
    item = source("https://vanban.chinhphu.vn/?docid=1",
        "Điều 1. Lối đi chung\nQuy định lối đi chung.\nĐiều 2. Hiệu lực\n"
        "Văn bản này có hiệu lực từ ngày 02 tháng 01 năm 2099.",
        document_number="01/2099/QH99", reported_effective_from="01/01/2099")
    _, report = pack_sources([item], build_official_search_plan("lối đi chung hiện nay"), DEEP_READING)
    assert report["legal_effect_status"] == "conflicting"


def test_trace_uses_request_budget_and_has_no_web_body():
    from app.services.research_presenter import sanitize_retrieval_trace
    from app.services.official_search_plan import DEEP_READING, ProfiledContexts
    contexts = ProfiledContexts(["NEVER PERSIST THIS WEB BODY"], DEEP_READING)
    trace = sanitize_retrieval_trace({"retrieval_diagnostics": {
        "context_profile": {"max_tokens": 8000}, "official_supplement": {
            "sources_read": 3, "queries_completed": 2, "phase_seconds": {"read": .5},
            "sources_downloaded": 4, "discovered_urls": ["https://vanban.chinhphu.vn/?docid=1"],
            "topic_coverage": {"covered": ["lối đi"], "missing": ["thuê nhà"], "status": "known", "text": "SECRET"},
            "excluded_blocks": [{"source": 0, "article": "Điều 1", "reason": "context_budget", "text": "SECRET"}],
            "legal_effect_status": "unverified", "raw_text": "SECRET"}}},
        contexts, SimpleNamespace(LLM_CONTEXT_MAX_TOKENS=720), query="question", cached=False)
    assert trace["context_budget_tokens"] == 8000
    assert trace["official_search"]["sources_read"] == 3
    assert trace["official_search"]["sources_downloaded"] == 4
    assert trace["official_search"]["discovered_urls"] == ["https://vanban.chinhphu.vn/?docid=1"]
    assert trace["official_search"]["topic_coverage"]["missing"] == ["thuê nhà"]
    assert trace["official_search"]["excluded_blocks"][0]["reason"] == "context_budget"
    assert "SECRET" not in str(trace) and "NEVER PERSIST" not in str(trace)


def test_article_parser_never_splits_on_wrapped_cross_reference_or_annex():
    from app.services.deep_official_search import pack_sources
    from app.services.official_search_plan import DEEP_READING, build_official_search_plan
    item = source("https://vanban.chinhphu.vn/?docid=1",
        "Điều 1. Lối đi chung\nQuy định dẫn chiếu\nĐiều 44 Luật tổng hợp và nội dung tiếp nối.\n"
        "Điều 2. Lối đi khác\nNội dung lối đi chung.\nPHỤ LỤC\n" + "không phải điều khoản " * 1000)
    contexts, _ = pack_sources([item], build_official_search_plan("lối đi chung"), DEEP_READING)
    assert any("Điều 44 Luật tổng hợp" in c for c in contexts)
    assert not any("PHỤ LỤC" in c for c in contexts)
    assert len(contexts) == 2


def test_organization_instrument_is_not_situation_evidence():
    from app.services.deep_official_search import pack_sources
    from app.services.official_search_plan import DEEP_READING, build_official_search_plan
    item = source("https://vanban.chinhphu.vn/?docid=1",
        "Điều 1. Nhiệm vụ\nQuản lý nhập khẩu phế liệu và giấy phép môi trường.",
        title="Quy định chức năng, nhiệm vụ, quyền hạn và cơ cấu tổ chức của Bộ tổng hợp")
    contexts, report = pack_sources([item], build_official_search_plan("nhập khẩu phế liệu giấy phép môi trường"), DEEP_READING)
    assert not contexts
    assert any(x["reason"] == "organization_instrument" for x in report["excluded_blocks"])


def test_query_plan_uses_specific_situation_and_primary_law_hypotheses():
    from app.services.official_search_plan import build_official_search_plan
    plan = build_official_search_plan("Tôi nhập khẩu phế liệu. Hiện nay có cần giấy phép môi trường?")
    assert "nhập khẩu" not in plan.queries
    assert any(q == "nhập khẩu phế liệu" for q in plan.queries)
    assert any("Luật Bảo vệ môi trường" in q for q in plan.queries)
    local = build_official_search_plan("Sếp đuổi tôi không báo trước tại tỉnh Đồng Nai thì xử lý thế nào?")
    assert "tỉnh Đồng Nai" in local.jurisdictions
    assert any("chấm dứt hợp đồng lao động" in q for q in local.queries)


@pytest.mark.asyncio
async def test_deep_pdf_worker_protocol_accepts_twenty_pages_without_ocr():
    from pypdf import PdfWriter
    from app.services.official_document_reader import extract_official_pdf
    writer = PdfWriter()
    for _ in range(24):
        writer.add_blank_page(width=100, height=100)
    out = BytesIO()
    writer.write(out)
    item = await extract_official_pdf(out.getvalue(), url="https://vbpl.vn/FileData/test.pdf",
        attachment_url="https://vbpl.vn/FileData/test.pdf", smart_pages=True, deep_read=True, page_limit=20)
    assert len(item["pages"]) == 20 and len(item["inspected_pages"]) <= 40
    assert item["requires_ocr"] and item["ocr_provider"] is None


@pytest.mark.asyncio
async def test_related_links_exclude_navigation_and_unrelated_documents():
    from app.services.trusted_source_reader import read_source
    html = '''<title>Quy định lối đi</title><p>Điều 1. Lối đi chung</p><p>Nội dung.</p>
    <p>Điều 2. Quy định khác</p><p>Kết thúc.</p>
    <a href="/van-ban-dang-cong-bao/van-ban-hop-nhat-l7.htm">Văn bản hợp nhất</a>
    <a href="/van-ban/huong-dan-999.htm">Hướng dẫn đặc xá</a>
    <a href="/van-ban/sua-doi-123.htm">Sửa đổi quy định lối đi chung</a>'''
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html,
            headers={"content-type": "text/html"}))) as client:
        item = await read_source("https://congbao.chinhphu.vn/van-ban/quy-dinh-1.htm", client=client,
                                 question="lối đi chung hướng dẫn", smart_pages=True, deep_read=True, page_limit=20)
    assert item["related_urls"] == ["https://congbao.chinhphu.vn/van-ban/sua-doi-123.htm"]


@pytest.mark.asyncio
async def test_async_network_tripwire_precedes_any_connector(monkeypatch):
    loop = asyncio.get_running_loop()
    async def forbidden(*args, **kwargs):
        pytest.fail("external connector reached the OS")
    monkeypatch.setattr(loop, "_connect_sock", forbidden)
    with pytest.raises(RuntimeError, match="blocked"):
        await loop.create_connection(asyncio.Protocol, "203.0.113.1", 443)


@pytest.mark.asyncio
async def test_mixed_known_and_new_situation_still_searches_web(monkeypatch):
    from app.services import rag_pipeline as pipeline
    from app.ingestion.legal_text import EvidenceChunk
    item = EvidenceChunk(1, "01/2099/QH99", "Luật tổng hợp", "https://example.invalid/1",
        "Điều 1", "Điều 1", None, "01/2099/QH99, Điều 1", "Quy định đặt cọc trong hợp đồng.", 8)
    cfg = SimpleNamespace(CHAT_OFFICIAL_DEEP_READING_ENABLED=True, USE_LEGACY_FREE_PIPELINE=False,
        FINAL_EVIDENCE_LIMIT=3, LLM_CONTEXT_MAX_TOKENS=720)
    monkeypatch.setattr(pipeline, "get_settings", lambda: cfg)
    async def retrieve(*args):
        return pipeline.RetrievalOutcome(evidence=[item], latency={}, status="ok", diagnostics={})
    async def expand(*args, **kwargs):
        return SimpleNamespace(selected_evidence=[item], status="ok", diagnostics={})
    async def rescue(*args, **kwargs):
        return SimpleNamespace(evidence=[], diagnostics={})
    searches = []
    async def search(query, **kwargs):
        searches.append(query)
        return SimpleNamespace(contexts=[], diagnostics={}, status="no_readable_source")
    async def answer(*args, **kwargs):
        return pipeline.LLMGenerationResult(text="conditional", observed_provider="test", observed_model="test")
    monkeypatch.setattr(pipeline, "retrieve_configured_legal_evidence", retrieve)
    monkeypatch.setattr(pipeline, "expand_v3_evidence", expand)
    monkeypatch.setattr(pipeline, "rescue_primary_law_evidence", rescue)
    monkeypatch.setattr(pipeline, "supplement_official_evidence", search)
    monkeypatch.setattr(pipeline, "generate_response_with_metadata", answer)
    await pipeline.run_advanced_rag("đặt cọc và lối đi chung")
    assert searches == ["đặt cọc và lối đi chung"]


def test_consolidated_document_identifier_and_source_cap():
    from app.services.official_search_plan import build_official_search_plan
    from app.services.evidence_presenter import present_context
    from app.services.rag_pipeline import fit_contexts_under_budget
    assert any("15/VBHN-VPQH" in q for q in build_official_search_plan("Tra cứu 15/VBHN-VPQH").queries)
    contexts = [f"[15/VBHN-VPQH]\nNguồn: https://vanban.chinhphu.vn/?docid={i}\nTiêu đề: nguồn\nNội dung." for i in range(9)]
    assert present_context(contexts[0]).document_number == "15/VBHN-VPQH"
    distinct = [c.replace("15/VBHN-VPQH", f"{i}/2099/QH99") for i, c in enumerate(contexts, 1)]
    assert len(fit_contexts_under_budget(distinct, max_evidence=16, max_tokens=8000, max_sources=8)) == 8


@pytest.mark.parametrize("asked_date", ["01/01/2024", "01-01-2024", "01.01.2024"])
def test_alternative_consolidations_do_not_mix_versions_in_context(asked_date):
    from app.services.deep_official_search import pack_sources
    from app.services.official_search_plan import DEEP_READING, build_official_search_plan
    old = source("https://congbao.chinhphu.vn/van-ban/test-1.htm",
        "Điều 1. Lối đi chung\nLối đi chung OLD VERSION.", document_number="1/VBHN-TEST",
        title="Văn bản hợp nhất số 1/VBHN-TEST hợp nhất Luật tổng hợp", issued_date="01/01/2020")
    new = source("https://congbao.chinhphu.vn/van-ban/test-2.htm",
        "Điều 1. Lối đi chung\nLối đi chung NEW VERSION.", document_number="2/VBHN-TEST",
        title="Văn bản hợp nhất số 2/VBHN-TEST hợp nhất Luật tổng hợp", issued_date="01/01/2025")
    contexts, report = pack_sources([old, new], build_official_search_plan("lối đi chung hiện nay"), DEEP_READING)
    assert any("NEW VERSION" in c for c in contexts)
    assert not any("OLD VERSION" in c for c in contexts)
    assert report["legal_effect_status"] == "unverified"
    historic, _ = pack_sources([old, new], build_official_search_plan(f"lối đi chung tại ngày {asked_date}"), DEEP_READING)
    assert any("OLD VERSION" in c for c in historic)
    assert not any("NEW VERSION" in c for c in historic)
