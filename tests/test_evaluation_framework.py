from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.evaluation.answer_metrics import (
    aggregate_answer_metrics,
    calculate_case_answer_metrics,
    char_f1_metric,
    chrf_metric,
    classify_response_refusal,
    rouge_l_metric,
    token_level_metrics,
)
from app.evaluation.case_selection import build_cases, select_evaluation_cases
from app.evaluation.gold_sidecar import GoldSidecar, load_gold_sidecar
from app.evaluation.profiles import PROFILES, EvaluationProfile, get_evaluation_profile
from app.evaluation.reporting import generate_markdown_report, write_run_report
from app.evaluation.retrieval_metrics import (
    aggregate_retrieval_metrics,
    calculate_case_retrieval_metrics,
    calculate_stage_survival_rates,
    match_gold_evidence,
    normalize_legal_identifier,
)
from app.evaluation.run_manifest import (
    atomic_write_json,
    calculate_configuration_fingerprint,
    calculate_dataset_sha256,
    create_run_manifest,
    generate_unique_run_id,
    get_git_commit_sha,
    get_git_provenance,
    prepare_run_directory,
)
from app.evaluation.schemas import (
    CandidateChunk,
    EvaluationRunManifest,
    GoldEvidence,
    GoldenCase,
    RetrievalCaseResult,
    RetrievalStageTrace,
    StageCandidate,
)
from audit_golden_dataset import check_anchor_match, find_document_candidates


# 1. Test Citation Normalization & Evidence Matching
def test_legal_identifier_normalization():
    assert normalize_legal_identifier("  Điều 3  ") == "điều 3"
    assert normalize_legal_identifier("Khoản 8.") == "khoản 8"
    assert normalize_legal_identifier("72/2020/QH14") == "72/2020/qh14"


def test_gold_evidence_matching():
    gold = GoldEvidence(
        evidence_item_id="ev_01",
        document_id=431147,
        document_number="72/2020/QH14",
        article="Điều 3",
        clause="Khoản 8",
    )
    chunk_exact = CandidateChunk(
        document_id=431147,
        document_number="72/2020/QH14",
        title="Luật BVMT",
        source_url="http://example.com",
        citation="Điều 3 Khoản 8 Luật 72/2020/QH14",
        article="Điều 3",
        clause="Khoản 8",
        text="Nội dung...",
        token_count=50,
    )
    doc_m, art_m, cl_m = match_gold_evidence(gold, chunk_exact)
    assert doc_m is True
    assert art_m is True
    assert cl_m is True

    chunk_diff_clause = CandidateChunk(
        document_id=431147,
        document_number="72/2020/QH14",
        title="Luật BVMT",
        source_url="http://example.com",
        citation="Điều 3 Khoản 1 Luật 72/2020/QH14",
        article="Điều 3",
        clause="Khoản 1",
        text="Nội dung...",
        token_count=50,
    )
    doc_m, art_m, cl_m = match_gold_evidence(gold, chunk_diff_clause)
    assert doc_m is True
    assert art_m is True
    assert cl_m is False


# 2. Test Retrieval Metrics & Verified Only Filtering
def test_retrieval_metrics_calculation_verified_only():
    gold = [
        GoldEvidence(evidence_item_id="ev_01", document_id=1, article="Điều 1", required=True, status="verified"),
        GoldEvidence(evidence_item_id="ev_02", document_id=2, article="Điều 5", required=True, status="verified"),
    ]
    chunks = [
        CandidateChunk(
            document_id=1,
            document_number="1",
            title="T",
            source_url="U",
            citation="C1",
            article="Điều 1",
            text="T1",
            token_count=10,
        ),
        CandidateChunk(
            document_id=3,
            document_number="3",
            title="T",
            source_url="U",
            citation="C3",
            article="Điều 9",
            text="T3",
            token_count=10,
        ),
        CandidateChunk(
            document_id=2,
            document_number="2",
            title="T",
            source_url="U",
            citation="C2",
            article="Điều 5",
            text="T2",
            token_count=10,
        ),
    ]

    res = calculate_case_retrieval_metrics(gold, chunks)
    assert res["has_gold_labels"] is True
    assert res["doc_recall"][1] == 0.5
    assert res["doc_recall"][3] == 1.0
    assert res["article_recall"][1] == 0.5
    assert res["article_recall"][3] == 1.0
    assert res["mrr_article"] == 1.0
    assert res["all_hop_coverage"] is True
    assert res["partial_hop_coverage"] is True


def test_unverified_gold_label_skips_metric_denominator():
    gold_unverified = [GoldEvidence(evidence_item_id="ev_01", status="ambiguous")]
    chunks = []
    res = calculate_case_retrieval_metrics(gold_unverified, chunks)
    assert res["has_gold_labels"] is False
    assert res["skip_reason"] == "no_verified_gold_label"

    agg = aggregate_retrieval_metrics([{"metrics": res}])
    assert agg["total_cases"] == 1
    assert agg["scored_cases_count"] == 0
    assert agg["skipped_cases_count"] == 1
    assert agg["coverage"] == 0.0


# 3. Test Deterministic Refusal Classifier
def test_refusal_classification():
    cat, is_ref = classify_response_refusal("Hệ thống chưa thể xử lý yêu cầu", ["context"])
    assert cat == "technical_error"
    assert is_ref is False

    cat, is_ref = classify_response_refusal("Xin lỗi, tôi không có thông tin về vấn đề này.", ["context"])
    assert cat == "pure_refusal"
    assert is_ref is True

    cat, is_ref = classify_response_refusal(
        "Theo Điều 3 Luật 72/2020/QH14, giấy phép môi trường là... Nội dung chỉ nhằm cung cấp thông tin, không phải tư vấn pháp lý.",
        ["context"],
    )
    assert cat == "disclaimer"
    assert is_ref is False

    cat, is_ref = classify_response_refusal(
        "Căn cứ Điều 10 Luật Bảo vệ môi trường, đối tượng đăng ký bao gồm dự án nhóm C. Tuy nhiên về mức phạt chi tiết thì tài liệu không đề cập.",
        ["context"],
    )
    assert cat == "mixed_claim_refusal"
    assert is_ref is False

    cat, is_ref = classify_response_refusal(
        "Theo Điều 3 Luật Bảo vệ môi trường 2020, giấy phép môi trường là...", ["context"]
    )
    assert cat == "normal_answer"
    assert is_ref is False


# 4. Test Text & Answer Metrics
def test_text_similarity_metrics():
    pred = "Giấy phép môi trường là văn bản do cơ quan có thẩm quyền cấp"
    ref = "Giấy phép môi trường là văn bản do cơ quan quản lý nhà nước có thẩm quyền cấp"
    p, r, f1 = token_level_metrics(pred, ref)
    assert 0.8 < p <= 1.0
    assert 0.7 < r <= 1.0
    assert 0.8 < f1 <= 1.0

    assert rouge_l_metric(pred, ref) > 0.7
    assert chrf_metric(pred, ref) > 0.7


# 5. Test Run Manifest & Atomic Writes
def test_atomic_write_json_and_manifest(tmp_path):
    out_path = tmp_path / "sub" / "result.json"
    data = {"status": "success", "count": 42}
    atomic_write_json(out_path, data)

    assert out_path.exists()
    assert json.loads(out_path.read_text(encoding="utf-8")) == data
    assert not out_path.with_suffix(".json.tmp").exists()


def test_unique_run_id_generation():
    run_id1 = generate_unique_run_id(prefix="test", config_fingerprint="abcdef123456")
    assert run_id1.startswith("test_")
    assert "abcdef12" in run_id1


# 6. Test CLI Option Stripping in Retrieval Runner
def test_run_retrieval_eval_strips_unsupported_options():
    from run_retrieval_eval import build_parser

    parser = build_parser()
    options = [action.dest for action in parser._actions]
    assert "mode" not in options
    assert "guardrails" not in options
    assert "judge" not in options


# 7. Test Canonical Gold Sidecar Loader (Phase 1 & Phase 8)
def test_gold_sidecar_v2_wrapper_loading(tmp_path):
    sidecar_file = tmp_path / "sidecar.json"
    payload = {
        "schema_version": "2.0.0",
        "dataset_name": "namsyntax_legal_qa_420",
        "total_cases": 420,
        "total_evidence_items": 2,
        "labels": [
            {
                "evidence_item_id": "case_001_ev_01",
                "case_id": "case_001",
                "document_id": 100,
                "document_number": "72/2020/QH14",
                "article": "Điều 3",
                "required": True,
                "status": "verified",
            },
            {
                "evidence_item_id": "case_002_ev_01",
                "case_id": "case_002",
                "document_id": 200,
                "document_number": "10/2021/TT-BTNMT",
                "article": "Điều 5",
                "required": True,
                "status": "verified",
            },
        ],
    }
    sidecar_file.write_text(json.dumps(payload), encoding="utf-8")

    sidecar = load_gold_sidecar(sidecar_file)
    assert sidecar.metadata.schema_version == "2.0.0"
    assert sidecar.metadata.total_evidence_items == 2
    assert len(sidecar.labels) == 2
    assert "case_001" in sidecar.labels_by_case_id
    assert "case_002" in sidecar.labels_by_case_id


def test_malformed_sidecar_fails_closed(tmp_path):
    # Invalid schema version
    f1 = tmp_path / "f1.json"
    f1.write_text(json.dumps({"schema_version": "1.0.0", "labels": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported gold sidecar schema_version"):
        load_gold_sidecar(f1)

    # Declared total evidence count mismatch
    f2 = tmp_path / "f2.json"
    f2.write_text(json.dumps({"schema_version": "2.0.0", "total_evidence_items": 10, "labels": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="Sidecar evidence count mismatch"):
        load_gold_sidecar(f2)

    # Duplicate evidence_item_id
    f3 = tmp_path / "f3.json"
    f3.write_text(json.dumps({
        "schema_version": "2.0.0",
        "total_evidence_items": 2,
        "labels": [
            {"evidence_item_id": "dup", "case_id": "c1", "status": "verified"},
            {"evidence_item_id": "dup", "case_id": "c2", "status": "verified"},
        ]
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate evidence_item_id"):
        load_gold_sidecar(f3)


# 8. Test Centralized Case Construction & Policy Selection (Phase 2 & Phase 8)
def test_all_required_verified_policy_prevents_empty_case_selection():
    c_empty = GoldenCase(
        case_id="case_empty",
        question="Empty?",
        question_type="factoid",
        answerable=True,
        reference_answer="Ans",
        gold_evidence=[],  # ZERO labels!
    )
    c_unanswerable = GoldenCase(
        case_id="case_unanswerable",
        question="Unanswerable?",
        question_type="unanswerable",
        answerable=False,
        reference_answer="Tài liệu không đề cập",
        gold_evidence=[GoldEvidence(evidence_item_id="ev_u", status="unanswerable", required=False)],
    )
    c_verified = GoldenCase(
        case_id="case_valid",
        question="Valid?",
        question_type="factoid",
        answerable=True,
        reference_answer="Ans",
        gold_evidence=[GoldEvidence(evidence_item_id="ev_v", document_id=1, article="Điều 1", required=True, status="verified")],
    )

    cases = [c_empty, c_unanswerable, c_verified]

    sel = select_evaluation_cases(cases, gold_policy="all-required-verified", include_unanswerable=False)
    # Empty label case and unanswerable case MUST NOT be selected!
    assert sel.selected_case_count == 1
    assert sel.selected_case_ids == ["case_valid"]
    assert sel.selected_case_ids_sha256 is not None


# 9. Test Anchor Verification Hierarchy (Phase 5 & Phase 8)
def test_anchor_verification_hierarchy():
    snippet = "Giấy phép môi trường là văn bản do cơ quan quản lý nhà nước có thẩm quyền cấp cho tổ chức."
    content_exact = "Quy định về bảo vệ môi trường: Giấy phép môi trường là văn bản do cơ quan quản lý nhà nước có thẩm quyền cấp cho tổ chức. Hết."

    matched, m_type, diag = check_anchor_match(snippet, content_exact)
    assert matched is True
    assert m_type == "full_anchor_exact"

    # Multi-window match on slightly altered formatting
    content_reformatted = "Mở đầu... Giấy phép môi trường là văn bản do cơ quan quản lý nhà nước có thẩm quyền cấp... Phần giữa khác... cấp cho tổ chức."
    matched_mw, m_type_mw, diag_mw = check_anchor_match(snippet, content_reformatted)
    assert matched_mw is True
    assert m_type_mw == "multi_window_agreement"
    assert "window_beg_hash" in diag_mw


# 10. Test Answer Runner Contract & 3-Argument generate_response (Phase 6 & Phase 8)
@pytest.mark.asyncio
async def test_run_answer_eval_uses_real_three_arg_signature():
    import inspect
    from app.services.rag_pipeline import generate_response

    sig = inspect.signature(generate_response)
    params = list(sig.parameters.keys())
    assert len(params) == 3
    assert params[0] == "original_query"
    assert params[1] == "rewritten_query"
    assert params[2] == "context"


@pytest.mark.asyncio
async def test_answer_input_guardrail_enforce_rejection_zero_retrieval():
    from run_answer_eval import run_stage_a_online

    case = GoldenCase(
        case_id="c_unsafe",
        question="Unsafe text...",
        question_type="factoid",
        answerable=True,
        reference_answer="Ans",
        gold_evidence=[],
    )

    mock_settings = MagicMock()
    effective_profile = get_evaluation_profile("separated_intent")

    with patch("app.services.guardrails.check_input_guardrails", new_callable=AsyncMock, return_value=(False, "Blocked by guardrail")) as mock_gr, \
         patch("run_answer_eval.evaluate_single_retrieval_case", new_callable=AsyncMock) as mock_retrieval:

        res = await run_stage_a_online(case, mock_settings, "enforce", effective_profile)

        assert res["input_safe"] is False
        assert res["final_response"] == "Blocked by guardrail"
        # MUST MAKE ZERO RETRIEVAL CALLS ON INPUT REJECTION!
        mock_retrieval.assert_not_called()


# 11. Test Stage Specific Metrics & None Representation (Phase 7 & Phase 8)
def test_final_evidence_recall_at_6_is_none_when_k_exceeds_limit():
    gold = [GoldEvidence(evidence_item_id="ev1", document_id=1, article="Điều 1", required=True, status="verified")]
    chunks = [
        CandidateChunk(document_id=1, document_number="1", title="T", source_url="U", citation="C", article="Điều 1", text="T", token_count=10),
        CandidateChunk(document_id=2, document_number="2", title="T", source_url="U", citation="C", article="Điều 2", text="T", token_count=10),
        CandidateChunk(document_id=3, document_number="3", title="T", source_url="U", citation="C", article="Điều 3", text="T", token_count=10),
    ]
    stage_trace = RetrievalStageTrace(
        final_evidence_chunks=[
            StageCandidate(document_id=1, article="Điều 1"),
            StageCandidate(document_id=2, article="Điều 2"),
            StageCandidate(document_id=3, article="Điều 3"),
        ]
    )

    res = calculate_case_retrieval_metrics(gold, chunks, stage_trace=stage_trace)

    final_metrics = res["stage_metrics"]["final_evidence_metrics"]
    # article_recall_at_6 MUST BE None / JSON null with reason field!
    assert final_metrics["article_recall_at_6"] is None
    assert final_metrics["article_recall_at_6_reason"] == "k_exceeds_effective_stage_limit"
    assert final_metrics["article_recall_at_3"] == 1.0


def test_historical_runs_checksum_preservation():
    runs_dir = Path("docs/evaluation/runs")
    if not runs_dir.exists():
        pytest.skip("No historical runs directory present")

    before_manifest = Path("before_historical_runs_manifest.json")
    after_manifest = Path("after_historical_runs_manifest.json")
    if before_manifest.exists() and after_manifest.exists():
        b_data = json.loads(before_manifest.read_text(encoding="utf-8"))
        a_data = json.loads(after_manifest.read_text(encoding="utf-8"))
        assert b_data == a_data
