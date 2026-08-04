from __future__ import annotations

import dataclasses
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


# 2. Test Retrieval Metrics & Verified Only Filtering
def test_retrieval_metrics_calculation_verified_only():
    gold = [
        GoldEvidence(document_id=1, article="Điều 1", required=True, status="verified"),
        GoldEvidence(document_id=2, article="Điều 5", required=True, status="verified"),
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
    assert res["mrr_article"] == 1.0  # First hit at rank 1
    assert res["all_hop_coverage"] is True
    assert res["partial_hop_coverage"] is True


def test_unverified_gold_label_skips_metric_denominator():
    gold_unverified = [GoldEvidence(status="ambiguous")]
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


# 7. Test Evaluation Profiles & Immutable Replacement
def test_evaluation_profile_immutable_replacement():
    base = get_evaluation_profile("legacy")
    assert base.resolved_document_limit == 12
    assert base.local_chunks_per_document == 2
    assert base.rerank_input_limit == 12
    assert base.intent_scoring_enabled is False

    effective = dataclasses.replace(base, rewrite_mode="on", reranker_mode="qdrant-only")
    assert effective.name == "legacy"
    assert effective.rewrite_mode == "on"
    assert effective.reranker_mode == "qdrant-only"
    # Ensure PROFILES constant was NOT mutated
    assert PROFILES["legacy"].rewrite_mode == "off"


def test_all_eight_profile_fields():
    prof = EvaluationProfile(
        name="custom_test",
        retrieval_document_limit=30,
        resolved_document_limit=20,
        local_chunks_per_document=5,
        rerank_input_limit=35,
        rerank_return_limit=4,
        final_evidence_limit=4,
        final_context_token_limit=800,
        intent_scoring_enabled=True,
    )
    pdict = prof.to_dict()
    assert pdict["retrieval_document_limit"] == 30
    assert pdict["resolved_document_limit"] == 20
    assert pdict["local_chunks_per_document"] == 5
    assert pdict["rerank_input_limit"] == 35
    assert pdict["rerank_return_limit"] == 4
    assert pdict["final_evidence_limit"] == 4
    assert pdict["final_context_token_limit"] == 800
    assert pdict["intent_scoring_enabled"] is True


@pytest.mark.asyncio
async def test_reranker_mode_routing():
    from app.services.remote_reranker import RemoteReranker, RerankOutcome, RerankResult

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

    reranker = RemoteReranker(
        settings=mock_settings, qdrant=mock_qdrant, pinecone=mock_pinecone
    )

    # pinecone-only mode
    outcome_pinecone = await reranker.rerank("query", ["doc1"], mode="pinecone-only")
    assert outcome_pinecone.provider == "pinecone"
    mock_qdrant.upsert.assert_not_called()

    # qdrant-only mode
    mock_pinecone.inference.rerank.reset_mock()
    with patch.object(
        reranker, "_qdrant_once", return_value=[RerankResult(index=0, score=0.95)]
    ):
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


def test_git_provenance_canonical_diff():
    (
        git_sha,
        git_dirty,
        git_tracked_dirty,
        git_staged_dirty,
        git_untracked_dirty,
        git_diff_sha256,
        repo_root,
    ) = get_git_provenance()

    assert isinstance(git_sha, str)
    assert isinstance(git_dirty, bool)
    if git_dirty:
        assert git_diff_sha256 is not None
        assert len(git_diff_sha256) == 64


@pytest.mark.asyncio
async def test_run_answer_eval_single_retrieval_contract():
    from run_answer_eval import run_stage_a_online

    case = GoldenCase(
        case_id="case_test_01",
        question="Điều kiện là gì?",
        question_type="factoid",
        answerable=True,
        reference_answer="Trả lời...",
        gold_evidence=[],
    )

    mock_settings = MagicMock()
    effective_profile = get_evaluation_profile("separated_intent")

    mock_retrieval_res = RetrievalCaseResult(
        case_id="case_test_01",
        question="Điều kiện là gì?",
        question_type="factoid",
        answerable=True,
        query_used="Điều kiện là gì?",
        original_query="Điều kiện là gì?",
        status="ok",
        retrieved_evidence=[
            CandidateChunk(
                document_id=1,
                document_number="1",
                title="T",
                source_url="U",
                citation="C",
                article="A",
                clause="K",
                text="Text context...",
                token_count=20,
            )
        ],
        latency={"t_retrieval": 0.5, "t_total": 0.5},
        metrics={},
    )

    with patch(
        "run_answer_eval.evaluate_single_retrieval_case",
        new_callable=AsyncMock,
        return_value=mock_retrieval_res,
    ) as mock_eval_retrieval, patch(
        "app.services.rag_pipeline.generate_response",
        new_callable=AsyncMock,
        return_value="Nội dung câu trả lời",
    ) as mock_gen_ans:

        stage_a_res = await run_stage_a_online(
            case, mock_settings, "off", effective_profile
        )

        # EXACTLY 1 retrieval call per case
        assert mock_eval_retrieval.call_count == 1
        assert mock_gen_ans.call_count == 1
        assert stage_a_res["retrieval_result"] == mock_retrieval_res
