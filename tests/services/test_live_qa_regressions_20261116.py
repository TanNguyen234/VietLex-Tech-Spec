"""Regression tests for multi-domain legal rescue, normalization, UI/CSV safety, and claim cleanup."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.legal_browser import local_legal_paths
from app.services.legal_topic_terms import normalize_colloquial_query
from app.services.primary_law_rescue import _LABOR, _LAND, _MARRIAGE, _TRAFFIC_DECREE, _planned_titles
from app.services.rag_pipeline import _is_stale_historical_context
from app.services.research_presenter import build_claim_support


def test_normalize_colloquial_vietnamese_abbreviations():
    text = normalize_colloquial_query("cty bat ky hd thu viec 3 thang ko dc nghi rut bhxh 150tr")
    assert "công ty" in text
    assert "hợp đồng" in text
    assert "không" in text
    assert "được" in text
    assert "bảo hiểm xã hội" in text
    assert "150 triệu" in text


def test_planned_titles_routes_diverse_modern_legal_domains():
    assert _LABOR in _planned_titles("sếp tôi quịt tiền trợ cấp thực tập")
    assert _LAND in _planned_titles("mua đất giấy tay năm 2010 giờ làm sổ đỏ được không")
    assert _MARRIAGE in _planned_titles("chồng ngoại tình giờ muốn ly hôn giành nuôi con 2 tuổi")
    assert _TRAFFIC_DECREE in _planned_titles("vượt đèn đỏ ô tô năm 2025 2026 bị phạt bn tiền")
    assert _LABOR not in _planned_titles("Thủ tục đăng ký kinh doanh cho hộ kinh doanh là gì?")


def test_claim_support_strips_raw_markdown_asterisks_and_links():
    contexts = ["[45/2019/QH14, Điều 25]\nID tài liệu: 123\nKhông quá 60 ngày."]
    result = build_claim_support(
        "- **Thời gian tối đa:** [Điều 25](https://example.org/law) quy định **không quá 60 ngày**.",
        contexts,
    )
    assert result
    assert "**" not in result[0]["text"]
    assert "https://" not in result[0]["text"]
    assert result[0]["support_state"] == "directly_supported"


def test_stale_historical_context_filter_respects_explicit_years():
    old_doc = "[197/SL, Điều 5]\nLuật Cải cách ruộng đất 1953."
    modern_doc = "[31/2024/QH15, Điều 138]\nLuật Đất đai 2024."
    assert _is_stale_historical_context(old_doc, "mua đất giấy tay năm 2010 làm sổ đỏ")
    assert not _is_stale_historical_context(old_doc, "Luật năm 1953 quy định gì?")
    assert not _is_stale_historical_context(modern_doc, "mua đất giấy tay năm 2010 làm sổ đỏ")


def test_rescue_browser_uses_full_corpus_when_ready(monkeypatch, tmp_path):
    from app.services import legal_browser
    from app.services.primary_law_rescue import _rescue_browser

    base = tmp_path / "content_store.sqlite3"
    raw_fts = tmp_path / "legal_fts.sqlite3"
    v3 = tmp_path / "v3_content.sqlite3"
    v3_fts = tmp_path / "v3_fts.sqlite3"
    for p in (base, raw_fts, v3, v3_fts):
        p.touch()

    monkeypatch.setattr(legal_browser, "local_legal_index_ready", lambda s, cp, fp: cp == base and fp == raw_fts)
    monkeypatch.setattr(legal_browser, "ContentStore", lambda p: SimpleNamespace(path=p))
    monkeypatch.setattr(legal_browser, "LegalFtsIndex", lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(legal_browser, "LegalBrowser", lambda **kw: SimpleNamespace(**kw))
    settings = SimpleNamespace(
        APP_ENV="test",
        SERVERLESS_ONLINE_ONLY=False,
        CONTENT_STORE_PATH=base,
        LEGAL_FTS_PATH=raw_fts,
        DATASET_REVISION="rev1",
    )
    resolved = _rescue_browser(settings, None)
    assert resolved.store.path == base
    assert resolved.index.path == raw_fts
    assert local_legal_paths(SimpleNamespace(
        APP_ENV="test",
        USE_LEGACY_FREE_PIPELINE=False,
        CONTENT_STORE_PATH=base,
        CLEAN_CONTENT_STORE_PATH=tmp_path / "missing.sqlite3",
        LEGAL_FTS_PATH=raw_fts,
        V3_CONTENT_STORE_PATH=v3,
        V3_LEGAL_FTS_PATH=v3_fts,
    )) == (v3, v3_fts, False)


def test_admin_overview_renders_bars_without_inline_style(monkeypatch):
    import app.api.routes as routes
    from tests.test_admin_operations import _client

    monkeypatch.setattr(
        routes,
        "get_admin_stats",
        AsyncMock(
            return_value={
                "total_queries": 3,
                "daily": [{"_id": "2026-11-16", "requests": 3, "tokens": 100, "measured_calls": 1}],
                "token_usage": {"calls": 1, "total_token_count": 100, "total_token_count_coverage": 1},
                "latency": {"avg": 1.2, "count": 3},
            }
        ),
    )
    monkeypatch.setattr(routes, "get_admin_logs", AsyncMock(return_value=[]))
    monkeypatch.setattr(routes, "get_admin_inventory", AsyncMock(return_value={"status": "unavailable"}))
    resp = _client().get("/admin")
    assert resp.status_code == 200
    assert 'data-bar-height="100.0"' in resp.text
    assert 'class="admin-bar" style=' not in resp.text


def test_prepared_chunks_cache_reuses_identical_digest_and_invalidates_on_change(monkeypatch):
    from app.services import primary_law_rescue as rescue

    calls = 0

    def fake_chunk_document(metadata, content, **kwargs):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(rescue, "chunk_document", fake_chunk_document)
    rescue._PREPARED_DOCUMENT_CACHE.clear()
    meta = {"document_id": 999999, "document_number": "TEST"}
    rescue._prepared_chunks_for_document(
        document_id=999999,
        actual_digest="a" * 64,
        metadata=meta,
        content="Điều 1. Nội dung",
        preserve_unit_max_tokens=400,
        preserve_article_max_tokens=None,
        require_preamble=True,
        chunk_max=220,
        overlap=24,
    )
    rescue._prepared_chunks_for_document(
        document_id=999999,
        actual_digest="a" * 64,
        metadata=meta,
        content="Điều 1. Nội dung",
        preserve_unit_max_tokens=400,
        preserve_article_max_tokens=None,
        require_preamble=True,
        chunk_max=220,
        overlap=24,
    )
    assert calls == 1
    rescue._prepared_chunks_for_document(
        document_id=999999,
        actual_digest="b" * 64,
        metadata=meta,
        content="Điều 1. Nội dung mới",
        preserve_unit_max_tokens=400,
        preserve_article_max_tokens=None,
        require_preamble=True,
        chunk_max=220,
        overlap=24,
    )
    assert calls == 2


def test_rescue_rules_cover_red_light_points_shareholder_limit_and_zalo_evidence():
    from app.services.primary_law_rescue import _CIVIL_PROC, _ENTERPRISE, _E_TRANSACTION

    assert _TRAFFIC_DECREE in _planned_titles("vượt đèn đỏ ô tô có bị trừ điểm bằng lái không")
    assert any("tru diem giay phep lai xe" in p for _, phrases in _TRAFFIC_DECREE.domain_rules for p in phrases)
    assert _ENTERPRISE in _planned_titles("công ty nợ lương quá 3 tháng thì cổ đông hay giám đốc chịu trách nhiệm", max_docs=3)
    assert any("co dong chi chiu trach nhiem ve cac khoan no" in phrases for _, phrases in _ENTERPRISE.domain_rules)
    assert _LABOR not in _planned_titles("điều kiện thuế", max_docs=3)
    assert _CIVIL_PROC not in _planned_titles("điều kiện thuế", max_docs=3)
    followup = (
        "Tình huống trước do người dùng cung cấp (chỉ làm ngữ cảnh):\n"
        "cho bạn vay 50 triệu không giấy tờ\n"
        "Câu hỏi mới (ưu tiên dữ kiện mới):\n"
        "nhưng mà tui chỉ có tin nhắn zalo nó xác nhận mượn tiền thôi có làm chứng cứ đc ko"
    )
    assert _planned_titles(followup, max_docs=3)[0] == _CIVIL_PROC
    assert _E_TRANSACTION in _planned_titles("ký hợp đồng bằng chữ ký scan chụp ảnh gửi zalo giữa 2 công ty", max_docs=3)


def test_output_guardrail_prompts_allow_practical_prep_and_stay_synced():
    from pathlib import Path
    import yaml
    from app.services.guardrail_prompts import OUTPUT_PROMPT

    prompts = yaml.safe_load(Path("guardrails_config/prompts.yml").read_text(encoding="utf-8"))
    assert OUTPUT_PROMPT == prompts["prompts"][1]["content"]
    assert "Các khuyến nghị chuẩn bị thực tế" in OUTPUT_PROMPT


@pytest.mark.asyncio
async def test_deep_reading_retains_verified_corpus_on_non_temporal_co_can_co_phai_queries(monkeypatch):
    from app.ingestion.legal_text import EvidenceChunk
    from app.services import rag_pipeline
    from app.services.chat_official_supplement import OfficialSupplementResult
    from app.services.rag_pipeline import RetrievalOutcome

    chunk = EvidenceChunk(
        document_id=333670,
        document_number="45/2019/QH14",
        title="Bộ luật Lao động 2019",
        source_url="https://example.invalid/45-2019",
        article="Điều 188",
        clause="1",
        heading_path=(),
        citation="45/2019/QH14, Điều 188, Khoản 1",
        text="Tranh chấp lao động cá nhân phải được giải quyết thông qua thủ tục hòa giải.",
        token_count=20,
        source_content_sha256="a" * 64,
    )
    settings = rag_pipeline.get_settings().model_copy(
        update={"USE_LEGACY_FREE_PIPELINE": False, "CHAT_OFFICIAL_DEEP_READING_ENABLED": True}
    )

    async def fake_retrieve(*_args, **_kwargs):
        return RetrievalOutcome(evidence=[chunk], latency={}, status="ok")

    async def fake_expansion(*_args, **_kwargs):
        return SimpleNamespace(selected_evidence=[chunk], diagnostics={}, status="unchanged")

    async def fake_rescue(*_args, **_kwargs):
        return SimpleNamespace(evidence=[chunk], diagnostics={"status": "evidence_selected"})

    async def empty_supplement(*_args, **_kwargs):
        return OfficialSupplementResult("unknown", [], {}, 0.01)

    async def fake_llm(*_args, **_kwargs):
        return rag_pipeline.LLMGenerationResult("Cần hòa giải trước khi ra Tòa án [45/2019/QH14, Điều 188].", "test", "test")

    monkeypatch.setattr(rag_pipeline, "get_settings", lambda: settings)
    monkeypatch.setattr(rag_pipeline, "retrieve_configured_legal_evidence", fake_retrieve)
    monkeypatch.setattr(rag_pipeline, "expand_v3_evidence", fake_expansion)
    monkeypatch.setattr(rag_pipeline, "rescue_primary_law_evidence", fake_rescue)
    monkeypatch.setattr(rag_pipeline, "supplement_official_evidence", empty_supplement)
    monkeypatch.setattr(rag_pipeline, "generate_llm_response_with_metadata", fake_llm)

    ans, ctx, info = await rag_pipeline.run_advanced_rag(
        "cty ko chịu trả lương sau khi e báo trước nghỉ đúng luật thì có cần hòa giải trước khi ra tòa ko"
    )
    assert len(ctx) == 1
    assert "45/2019/QH14" in ans
    assert info["retrieval_diagnostics"]["official_supplement"]["corpus_contexts_suppressed"] == 0
