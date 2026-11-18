from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


@pytest.mark.asyncio
async def test_v3_retains_valid_corpus_contexts_when_supplement_times_out_even_without_deep_profile(
    monkeypatch,
):
    from app.ingestion.legal_text import EvidenceChunk
    from app.services import rag_pipeline
    from app.services.chat_official_supplement import OfficialSupplementResult

    chunk = EvidenceChunk(
        document_id=333670,
        document_number="45/2019/QH14",
        title="Bộ luật Lao động 2019",
        source_url="https://vanban.chinhphu.vn/?docid=333670",
        article="Điều 26",
        clause=None,
        heading_path="Chương III > Điều 26",
        citation="45/2019/QH14, Điều 26",
        text="Tiền lương của người lao động trong thời gian thử việc ít nhất phải bằng 85% mức lương của công việc đó.",
        token_count=24,
        source_content_sha256="a" * 64,
    )
    settings = rag_pipeline.get_settings().model_copy(
        update={
            "USE_LEGACY_FREE_PIPELINE": False,
            "CHAT_OFFICIAL_DEEP_READING_ENABLED": False,
            "CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED": True,
        }
    )

    async def fake_retrieve(*_args, **_kwargs):
        return rag_pipeline.RetrievalOutcome(evidence=[chunk], latency={}, status="ok")

    async def fake_expansion(*_args, **_kwargs):
        return SimpleNamespace(selected_evidence=[chunk], diagnostics={}, status="unchanged")

    async def fake_rescue(*_args, **_kwargs):
        return SimpleNamespace(evidence=[], diagnostics={"status": "no_evidence"})

    async def timed_out_supplement(*_args, **_kwargs):
        return OfficialSupplementResult("timeout", [], {"newer_source_required": False}, 0.05)

    llm_calls: list[str] = []

    async def fake_llm(user_prompt, _system_prompt, **_kwargs):
        llm_calls.append(user_prompt)
        return rag_pipeline.LLMGenerationResult(
            "Mức lương thử việc ít nhất bằng 85% mức lương của công việc đó [45/2019/QH14, Điều 26].",
            "google_vertex_ai",
            "gemini-3.5-flash",
            observed=True,
        )

    monkeypatch.setattr(rag_pipeline, "get_settings", lambda: settings)
    monkeypatch.setattr(rag_pipeline, "retrieve_configured_legal_evidence", fake_retrieve)
    monkeypatch.setattr(rag_pipeline, "expand_v3_evidence", fake_expansion)
    monkeypatch.setattr(rag_pipeline, "rescue_primary_law_evidence", fake_rescue)
    monkeypatch.setattr(rag_pipeline, "supplement_official_evidence", timed_out_supplement)
    monkeypatch.setattr(rag_pipeline, "generate_llm_response_with_metadata", fake_llm)

    answer, contexts, metadata = await rag_pipeline.run_advanced_rag(
        "Hiện nay mức lương thử việc tối thiểu là bao nhiêu phần trăm?"
    )

    assert len(llm_calls) == 1
    assert len(contexts) == 1
    assert "85%" in answer
    assert metadata["observed_provider"] == "google_vertex_ai"
    assert metadata["retrieval_diagnostics"]["official_supplement"]["corpus_contexts_suppressed"] == 0


@pytest.mark.asyncio
async def test_current_authority_question_with_evidence_calls_llm_and_surfaces_published_registry(
    monkeypatch,
):
    from app.ingestion.legal_text import EvidenceChunk
    from app.services import rag_pipeline
    from app.services.chat_official_supplement import OfficialSupplementResult
    from app.services.evidence_presenter import TrustedOfficialEvidenceContext

    # Part A: generate_response_with_metadata calls LLM on current-authority question when official/corpus evidence exists
    official_ctx = TrustedOfficialEvidenceContext(
        "[Nguồn chính thức ngoài VietLex · 31/2024/QH15]\n"
        "Nguồn: https://congbao.chinhphu.vn/van-ban/luat-dat-dai-31-2024.htm\n"
        "Nguồn loại: official_external\n"
        "Hiệu lực pháp lý: unverified\n"
        f"SHA-256 nguồn: {'b' * 64}\n"
        "Thời điểm đọc: 2026-11-18T00:00:00+00:00\n"
        "Phương thức đọc: tavily_extract_tier1\n"
        "Tiêu đề: Luật Đất đai 2024\n"
        "Điều 136. Thẩm quyền cấp Giấy chứng nhận quyền sử dụng đất lần đầu đối với cá nhân thuộc Ủy ban nhân dân cấp huyện."
    )

    async def fake_llm(_user_prompt, _system_prompt, **_kwargs):
        return rag_pipeline.LLMGenerationResult(
            "Theo Điều 136 Luật Đất đai 2024 [31/2024/QH15, Điều 136], UBND cấp huyện cấp Giấy chứng nhận lần đầu cho cá nhân.",
            "groq",
            "qwen/qwen3.8-27b",
            observed=True,
        )

    monkeypatch.setattr(rag_pipeline, "generate_llm_response_with_metadata", fake_llm)

    gen_result = await rag_pipeline.generate_response_with_metadata(
        "Hiện nay cơ quan nào có thẩm quyền cấp sổ đỏ lần đầu cho cá nhân?",
        "thẩm quyền cấp sổ đỏ lần đầu",
        [official_ctx],
    )
    assert gen_result.observed_provider == "groq"
    assert "Điều 136" in gen_result.text

    # Part B: run_advanced_rag checks published legal_effect_registry when available, retaining authority contexts
    chunk = EvidenceChunk(
        document_id=312024,
        document_number="31/2024/QH15",
        title="Luật Đất đai 2024",
        source_url="https://vanban.chinhphu.vn/?docid=312024",
        article="Điều 136",
        clause="1",
        heading_path="Điều 136",
        citation="31/2024/QH15, Điều 136, Khoản 1",
        text="Ủy ban nhân dân cấp huyện cấp Giấy chứng nhận quyền sử dụng đất lần đầu cho cá nhân.",
        token_count=20,
        source_content_sha256="c" * 64,
    )
    settings = rag_pipeline.get_settings().model_copy(
        update={
            "APP_ENV": "production",
            "MONGO_URL": "mongodb://mock-registry",
            "USE_LEGACY_FREE_PIPELINE": False,
            "CHAT_OFFICIAL_DEEP_READING_ENABLED": True,
        }
    )

    async def fake_registry_batch(numbers):
        assert any("31/2024/qh15" in n.lower() for n in numbers)
        return [
            {
                "state": "published",
                "reviewed_at": "2026-11-01T00:00:00+00:00",
                "assertions": [
                    {
                        "event_kind": "effective",
                        "effective_date": "2024-08-01",
                        "document_number": "31/2024/QH15",
                        "target_document_number": "31/2024/QH15",
                        "exact_quote": "Luật 31/2024/QH15 có hiệu lực từ ngày 01/08/2024.",
                        "source_url": "https://congbao.chinhphu.vn/van-ban/luat-31-2024.htm",
                        "source_sha256": "d" * 64,
                        "scope": "whole_document",
                    }
                ],
            }
        ]

    monkeypatch.setattr(rag_pipeline, "get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.legal_registry_database.registry_records_batch", fake_registry_batch
    )
    monkeypatch.setattr(
        rag_pipeline,
        "retrieve_configured_legal_evidence",
        lambda *_a, **_kw: _async_val(
            rag_pipeline.RetrievalOutcome(evidence=[chunk], latency={}, status="ok")
        ),
    )
    monkeypatch.setattr(
        rag_pipeline,
        "expand_v3_evidence",
        lambda *_a, **_kw: _async_val(
            SimpleNamespace(selected_evidence=[chunk], diagnostics={}, status="unchanged")
        ),
    )
    monkeypatch.setattr(
        rag_pipeline,
        "rescue_primary_law_evidence",
        lambda *_a, **_kw: _async_val(SimpleNamespace(evidence=[], diagnostics={})),
    )
    monkeypatch.setattr(
        rag_pipeline,
        "supplement_official_evidence",
        lambda *_a, **_kw: _async_val(OfficialSupplementResult("timeout", [], {}, 0.01)),
    )

    answer, contexts, metadata = await rag_pipeline.run_advanced_rag(
        "Hiện nay cơ quan nào có thẩm quyền cấp Giấy chứng nhận quyền sử dụng đất lần đầu?"
    )
    assert contexts
    assert metadata["observed_provider"] == "groq"
    reg_diag = metadata["retrieval_diagnostics"]["legal_effect_registry"]
    assert reg_diag["documents"]["31/2024/QH15"]["status"] == "effective"


async def _async_val(value):
    return value


def test_citation_clause_guard_corrects_money_percent_age_points_hours_and_prison_years():
    from app.services.citation_clause_guard import correct_clause_citations

    traffic_ctx = (
        "[168/2024/NĐ-CP, Điều 6]\n"
        "Điều 6. Xử phạt người điều khiển xe ô tô\n"
        "5. Phạt tiền từ 4.000.000 đồng đến 6.000.000 đồng đối với hành vi đỗ xe sai quy định.\n"
        "9. Phạt tiền từ 18.000.000 đồng đến 20.000.000 đồng đối với hành vi vượt đèn đỏ.\n"
        "16. Trừ điểm giấy phép lái xe:\n"
        "b) Thực hiện hành vi vượt đèn đỏ bị trừ 4 điểm giấy phép lái xe.\n"
    )
    ans1, chg1 = correct_clause_citations(
        "Ô tô vượt đèn đỏ bị phạt từ 18.000.000 đồng đến 20.000.000 đồng theo Khoản 5 Điều 6 [168/2024/NĐ-CP, Điều 6].",
        [traffic_ctx],
    )
    assert "Khoản 9 Điều 6" in ans1
    assert chg1 and chg1[0]["to_clause"] == "9"

    ans1b, chg1b = correct_clause_citations(
        "Ô tô vượt đèn đỏ bị phạt từ 18 triệu đồng đến 20 triệu đồng và bị trừ 4 điểm bằng lái theo Khoản 5 Điều 6.",
        [traffic_ctx],
    )
    assert "Khoản 9 Điều 6" not in ans1b or chg1b == []  # 18 triệu in K9 vs 4 điểm in K16 -> split claims below:

    ans_trieu, chg_trieu = correct_clause_citations(
        "Ô tô vượt đèn đỏ bị phạt từ 18 triệu đồng đến 20 triệu đồng theo Khoản 5 Điều 6.",
        [traffic_ctx],
    )
    assert "Khoản 9 Điều 6" in ans_trieu
    assert chg_trieu[0]["to_clause"] == "9"

    ans_points, chg_points = correct_clause_citations(
        "Người lái xe vượt đèn đỏ bị trừ 4 điểm giấy phép lái xe theo Khoản 5 Điều 6.",
        [traffic_ctx],
    )
    assert "Khoản 16 Điều 6" in ans_points
    assert chg_points[0]["to_clause"] == "16"

    # Percent / phần trăm, tuổi, giờ, năm tù, tỷ đồng
    mixed_ctx = (
        "[45/2019/QH14, Điều 26]\n"
        "Điều 26. Quy định tổng hợp\n"
        "1. Làm thêm không quá 48 giờ trong một tuần.\n"
        "2. Tiền lương thử việc ít nhất bằng 85% mức lương của công việc đó.\n"
        "3. Nam từ đủ 20 tuổi trở lên, thiệt hại từ 1 tỷ đồng trở lên bị phạt 7 năm tù.\n"
    )
    ans_pct, _ = correct_clause_citations(
        "Lương thử việc ít nhất bằng 85 phần trăm mức lương chính thức theo Khoản 1 Điều 26.",
        [mixed_ctx],
    )
    assert "Khoản 2 Điều 26" in ans_pct

    ans_age, _ = correct_clause_citations(
        "Nam kết hôn từ đủ 20 tuổi trở lên theo Khoản 1 Điều 26.",
        [mixed_ctx],
    )
    assert "Khoản 3 Điều 26" in ans_age

    ans_hours, _ = correct_clause_citations(
        "Thời giờ làm việc không quá 48 giờ theo Khoản 2 Điều 26.",
        [mixed_ctx],
    )
    assert "Khoản 1 Điều 26" in ans_hours

    ans_prison, _ = correct_clause_citations(
        "Thiệt hại từ 1 tỷ trở lên bị phạt 7 năm tù theo Khoản 1 Điều 26.",
        [mixed_ctx],
    )
    assert "Khoản 3 Điều 26" in ans_prison

    # Fractional Decimal million/billion aliases (e.g., 5,31 triệu đồng <-> 5.310.000 đồng)
    decimal_ctx = (
        "[293/2025/NĐ-CP, Điều 3]\n"
        "Điều 3. Mức lương tối thiểu và chế tài\n"
        "1. Vùng II là 4.730.000 đồng.\n"
        "2. Vùng I là 5.310.000 đồng.\n"
        "3. Phạt hành chính 2.500.000 đồng và bồi thường thiệt hại 1.500.000.000 đồng.\n"
    )
    ans_dec1, chg_dec1 = correct_clause_citations(
        "Mức lương tối thiểu vùng I là 5,31 triệu đồng theo Khoản 1 Điều 3.",
        [decimal_ctx],
    )
    assert "Khoản 2 Điều 3" in ans_dec1
    assert chg_dec1 and chg_dec1[0]["to_clause"] == "2"

    ans_dec2, chg_dec2 = correct_clause_citations(
        "Bị phạt 2,5 triệu đồng và bồi thường 1,5 tỷ đồng theo Khoản 1 Điều 3.",
        [decimal_ctx],
    )
    assert "Khoản 3 Điều 3" in ans_dec2
    assert chg_dec2 and chg_dec2[0]["to_clause"] == "3"


def test_is_local_stateless_mode_allows_connected_db_in_development(monkeypatch):
    import app.database as db_mod
    from app.services.rag_pipeline import is_local_stateless_mode

    dev_settings = SimpleNamespace(APP_ENV="development", MONGO_URL="mongodb://localhost:27017")
    monkeypatch.setattr(db_mod, "db", None)
    assert is_local_stateless_mode(dev_settings) is True

    monkeypatch.setattr(db_mod, "db", SimpleNamespace(name="vietlex_dev"))
    assert is_local_stateless_mode(dev_settings) is False

    no_mongo_settings = SimpleNamespace(APP_ENV="development", MONGO_URL=None)
    assert is_local_stateless_mode(no_mongo_settings) is True


def test_output_guardrail_prompt_approves_source_scoped_official_external_answers_and_matches_yaml():
    from app.services.guardrail_prompts import INPUT_PROMPT, OUTPUT_PROMPT

    prompts = yaml.safe_load(Path("guardrails_config/prompts.yml").read_text(encoding="utf-8"))[
        "prompts"
    ]
    by_task = {row["task"]: row["content"] for row in prompts}
    assert INPUT_PROMPT == by_task["self_check_input"]
    assert OUTPUT_PROMPT == by_task["self_check_facts"]
    assert "official_external" in OUTPUT_PROMPT
