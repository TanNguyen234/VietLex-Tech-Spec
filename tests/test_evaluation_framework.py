from __future__ import annotations

import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.evaluation.schemas import (
    CandidateChunk,
    GoldEvidence,
    GoldenCase,
    RetrievalStageTrace,
    EvaluationRunManifest,
)
from app.evaluation.retrieval_metrics import (
    calculate_case_retrieval_metrics,
    aggregate_retrieval_metrics,
    calculate_stage_survival_rates,
    normalize_legal_identifier,
    match_gold_evidence,
)
from app.evaluation.answer_metrics import (
    token_level_metrics,
    char_f1_metric,
    rouge_l_metric,
    chrf_metric,
    classify_response_refusal,
    calculate_case_answer_metrics,
    aggregate_answer_metrics,
)
from app.evaluation.run_manifest import (
    get_git_commit_sha,
    calculate_dataset_sha256,
    calculate_configuration_fingerprint,
    generate_unique_run_id,
    atomic_write_json,
    create_run_manifest,
)
from app.evaluation.reporting import generate_markdown_report, write_run_report


# 1. Test Citation Normalization & Evidence Matching
def test_legal_identifier_normalization():
    assert normalize_legal_identifier("  Điều 3  ") == "điều 3"
    assert normalize_legal_identifier("Khoản 8.") == "khoản 8"
    assert normalize_legal_identifier("72/2020/QH14") == "72/2020/qh14"


def test_gold_evidence_matching():
    gold = GoldEvidence(
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


# 2. Test Retrieval Metrics & Missing Gold Label Handling
def test_retrieval_metrics_calculation():
    gold = [
        GoldEvidence(document_id=1, article="Điều 1", required=True, status="verified"),
        GoldEvidence(document_id=2, article="Điều 5", required=True, status="verified"),
    ]
    chunks = [
        CandidateChunk(document_id=1, document_number="1", title="T", source_url="U", citation="C1", article="Điều 1", text="T1", token_count=10),
        CandidateChunk(document_id=3, document_number="3", title="T", source_url="U", citation="C3", article="Điều 9", text="T3", token_count=10),
        CandidateChunk(document_id=2, document_number="2", title="T", source_url="U", citation="C2", article="Điều 5", text="T2", token_count=10),
    ]

    res = calculate_case_retrieval_metrics(gold, chunks)
    assert res["has_gold_labels"] is True
    assert res["doc_recall"][1] == 0.5
    assert res["doc_recall"][3] == 1.0
    assert res["article_recall"][1] == 0.5
    assert res["article_recall"][3] == 1.0
    assert res["mrr_article"] == 1.0  # First hit at rank 1
    assert res["all_hop_coverage"] is True
    assert res["partial_hop_coverage"] is True


def test_missing_gold_label_skips_metric_denominator():
    gold_missing = [GoldEvidence(status="missing_gold_label")]
    chunks = []
    res = calculate_case_retrieval_metrics(gold_missing, chunks)
    assert res["has_gold_labels"] is False
    assert res["skip_reason"] == "missing_gold_label"

    agg = aggregate_retrieval_metrics([{"metrics": res}])
    assert agg["total_cases"] == 1
    assert agg["scored_cases_count"] == 0
    assert agg["skipped_cases_count"] == 1
    assert agg["coverage"] == 0.0


# 3. Test Deterministic Refusal Classifier
def test_refusal_classification():
    # Technical Error
    cat, is_ref = classify_response_refusal("Hệ thống chưa thể xử lý yêu cầu", ["context"])
    assert cat == "technical_error"
    assert is_ref is False

    # Pure Refusal
    cat, is_ref = classify_response_refusal("Xin lỗi, tôi không có thông tin về vấn đề này.", ["context"])
    assert cat == "pure_refusal"
    assert is_ref is True

    # Disclaimer
    cat, is_ref = classify_response_refusal("Theo Điều 3 Luật 72/2020/QH14, giấy phép môi trường là... Nội dung chỉ nhằm cung cấp thông tin, không phải tư vấn pháp lý.", ["context"])
    assert cat == "disclaimer"
    assert is_ref is False

    # Mixed Claim + Refusal
    cat, is_ref = classify_response_refusal("Căn cứ Điều 10 Luật Bảo vệ môi trường, đối tượng đăng ký bao gồm dự án nhóm C. Tuy nhiên về mức phạt chi tiết thì tài liệu không đề cập.", ["context"])
    assert cat == "mixed_claim_refusal"
    assert is_ref is False

    # Normal Answer
    cat, is_ref = classify_response_refusal("Theo Điều 3 Luật Bảo vệ môi trường 2020, giấy phép môi trường là...", ["context"])
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
    # Ensure temporary file was cleaned up
    assert not out_path.with_suffix(".json.tmp").exists()


def test_unique_run_id_generation():
    run_id1 = generate_unique_run_id(prefix="test", config_fingerprint="abcdef123456")
    assert run_id1.startswith("test_")
    assert "abcdef12" in run_id1


# 6. Test Default Mode Judge Independence
def test_run_retrieval_eval_defaults_to_no_judge():
    from run_retrieval_eval import build_parser
    args = build_parser().parse_args([])
    assert args.judge == "none"
    assert args.mode == "retrieval-only"
    assert args.rewrite == "off"
    assert args.guardrails == "off"


# 7. Test Evaluation Profiles & Reranker Routing
def test_evaluation_profiles():
    from app.evaluation.profiles import get_evaluation_profile
    legacy = get_evaluation_profile("legacy")
    assert legacy.resolved_document_limit == 12
    assert legacy.local_chunks_per_document == 2
    assert legacy.rerank_input_limit == 12
    assert legacy.intent_scoring_enabled is False

    sep_intent = get_evaluation_profile("separated_intent")
    assert sep_intent.resolved_document_limit == 16
    assert sep_intent.local_chunks_per_document == 4
    assert sep_intent.rerank_input_limit == 24
    assert sep_intent.intent_scoring_enabled is True


@pytest.mark.asyncio
async def test_reranker_mode_routing():
    from app.services.remote_reranker import RemoteReranker, RerankResult, RerankOutcome
    mock_settings = MagicMock()
    mock_settings.PINECONE_RERANK_MODEL = "bge-reranker-v2-m3"
    mock_settings.PINECONE_RERANK_TIMEOUT_SECONDS = 12.0
    mock_settings.QDRANT_RERANK_MODEL = "answerdotai/answerai-colbert-small-v1"
    mock_settings.QDRANT_RERANK_TIMEOUT_SECONDS = 12.0
    mock_settings.QDRANT_RERANK_MAX_RETRIES = 2
    mock_settings.RERANK_RETURN_LIMIT = 3

    mock_qdrant = MagicMock()
    mock_pinecone = MagicMock()
    mock_pinecone.inference.rerank.return_value = {"data": [{"index": 0, "score": 0.9}]}

    reranker = RemoteReranker(settings=mock_settings, qdrant=mock_qdrant, pinecone=mock_pinecone)

    # pinecone-only mode
    outcome_pinecone = await reranker.rerank("query", ["doc1"], mode="pinecone-only")
    assert outcome_pinecone.provider == "pinecone"
    mock_qdrant.upsert.assert_not_called()

    # qdrant-only mode
    mock_pinecone.inference.rerank.reset_mock()
    with patch.object(reranker, "_qdrant_once", return_value=[RerankResult(index=0, score=0.95)]):
        outcome_qdrant = await reranker.rerank("query", ["doc1"], mode="qdrant-only")
        assert outcome_qdrant.provider == "qdrant"
        mock_pinecone.inference.rerank.assert_not_called()


def test_run_dir_overwrite_protection(tmp_path):
    from app.evaluation.run_manifest import prepare_run_directory
    run_id = "test_run_123"
    dir1 = prepare_run_directory(tmp_path, run_id)
    assert dir1.exists()

    with pytest.raises(FileExistsError):
        prepare_run_directory(tmp_path, run_id)

