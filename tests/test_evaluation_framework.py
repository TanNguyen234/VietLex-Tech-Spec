from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import sqlite3
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
    calculate_stage_candidate_metrics,
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
    EvidenceStatus,
    GoldEvidence,
    GoldenCase,
    RequiredLevel,
    RetrievalCaseResult,
    RetrievalStageCapacities,
    RetrievalStageTrace,
    StageCandidate,
)
from audit_golden_dataset import check_anchor_match, resolve_document_identity


# 1. Test Citation Normalization & Evidence Matching
def test_legal_identifier_normalization():
    assert normalize_legal_identifier("  Điều 3  ") == "điều 3"
    assert normalize_legal_identifier("Khoản 8.") == "khoản 8"
    assert normalize_legal_identifier("72/2020/QH14") == "72/2020/qh14"


def test_gold_evidence_matching():
    gold = GoldEvidence(
        evidence_item_id="ev_01",
        case_id="case_001",
        document_id=431147,
        document_number="72/2020/QH14",
        article="Điều 3",
        clause="Khoản 8",
        required=True,
        required_level=RequiredLevel.CLAUSE,
        status=EvidenceStatus.VERIFIED,
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


# 2. Test Sidecar Loader Strict Fail Closed & No Mutation (Phase 1 & 11 Constraints)
def test_gold_sidecar_loader_fails_closed_on_missing_required_fields(tmp_path):
    f = tmp_path / "invalid_sidecar.json"

    # Missing evidence_item_id
    f.write_text(json.dumps({
        "schema_version": "2.0.0",
        "labels": [{"case_id": "c1", "status": "verified", "required": True}]
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="missing non-empty 'evidence_item_id'"):
        load_gold_sidecar(f)

    # Missing status
    f.write_text(json.dumps({
        "schema_version": "2.0.0",
        "labels": [{"evidence_item_id": "ev1", "case_id": "c1", "required": True}]
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="missing non-empty 'status'"):
        load_gold_sidecar(f)

    # Missing required boolean
    f.write_text(json.dumps({
        "schema_version": "2.0.0",
        "labels": [{"evidence_item_id": "ev1", "case_id": "c1", "status": "verified"}]
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="missing explicit 'required' boolean"):
        load_gold_sidecar(f)


def test_gold_sidecar_loader_does_not_mutate_raw_payload(tmp_path):
    f = tmp_path / "valid_sidecar.json"
    raw_payload = {
        "schema_version": "2.0.0",
        "dataset_name": "test_ds",
        "total_cases": 1,
        "total_evidence_items": 1,
        "labels": [{
            "evidence_item_id": "ev_01",
            "case_id": "c1",
            "required": True,
            "required_level": "article",
            "status": "verified"
        }]
    }
    raw_str_before = json.dumps(raw_payload)
    f.write_text(raw_str_before, encoding="utf-8")

    sidecar = load_gold_sidecar(f)
    assert len(sidecar.labels) == 1

    # Verify original file bytes and contents were untouched
    raw_str_after = f.read_text(encoding="utf-8")
    assert raw_str_before == raw_str_after


def test_gold_sidecar_loader_validates_exact_case_set_equality(tmp_path):
    f = tmp_path / "sidecar.json"
    f.write_text(json.dumps({
        "schema_version": "2.0.0",
        "total_evidence_items": 1,
        "labels": [{"evidence_item_id": "ev1", "case_id": "case_001", "required": True, "status": "verified"}]
    }), encoding="utf-8")

    # Mismatch dataset case IDs
    with pytest.raises(ValueError, match="Case ID set mismatch"):
        load_gold_sidecar(f, dataset_case_ids=["case_001", "case_002"])


# 3. Test Identity Resolution Hierarchy (Phase 2 & 11 Constraints)
def test_exact_document_id_identity_resolution():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE metadata (document_id INT, source_url TEXT, document_number TEXT)")
    conn.execute("INSERT INTO metadata VALUES (100, 'http://example.com/doc1', '10/2020/NĐ-CP')")

    mock_fts = MagicMock()

    # Exact doc_id
    cand, method, sources, is_complete = resolve_document_identity(conn, mock_fts, 100, None, None)
    assert cand == [100]
    assert method == "exact_doc_id"
    assert "dataset_reference_doc_id" in sources
    assert is_complete is True


def test_exact_source_url_identity_resolution():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE metadata (document_id INT, source_url TEXT, document_number TEXT)")
    conn.execute("INSERT INTO metadata VALUES (200, 'http://example.com/doc2', '20/2020/NĐ-CP')")

    mock_fts = MagicMock()

    # Exact source_url
    cand, method, sources, is_complete = resolve_document_identity(conn, mock_fts, None, "http://example.com/doc2", None)
    assert cand == [200]
    assert method == "exact_source_url"
    assert "dataset_reference_source_url" in sources
    assert is_complete is True


def test_candidate_only_uniqueness_cannot_create_verified_status():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE metadata (document_id INT, source_url TEXT, document_number TEXT)")
    # Metadata has NO matching doc number or ID
    mock_fts = MagicMock()
    mock_fts.search.return_value = [999]  # Truncated candidate set from FTS

    cand, method, sources, is_complete = resolve_document_identity(conn, mock_fts, None, None, "99/2020/UNKNOWN")
    assert cand == [999]
    assert method == "lexical_candidate_fallback"
    assert is_complete is False  # Candidate-only uniqueness is incomplete and cannot create verified status!


# 4. Test Level-Specific Verification Matching (Phase 2 & 11 Constraints)
def test_article_and_clause_required_evidence_verification_levels():
    gold_art = GoldEvidence(
        evidence_item_id="ev_art",
        case_id="c1",
        document_id=1,
        article="Điều 5",
        required=True,
        required_level=RequiredLevel.ARTICLE,
        status=EvidenceStatus.VERIFIED,
    )
    # Chunk with matching document but missing article
    chunk_no_art = CandidateChunk(
        document_id=1,
        document_number="1",
        title="T",
        source_url="U",
        citation="C",
        article=None,
        text="T",
        token_count=10,
    )

    doc_m, art_m, cl_m = match_gold_evidence(gold_art, chunk_no_art)
    assert doc_m is True
    assert art_m is False  # Article required evidence CANNOT verify without matched article!

    gold_clause = GoldEvidence(
        evidence_item_id="ev_cl",
        case_id="c1",
        document_id=1,
        article="Điều 5",
        clause="Khoản 2",
        required=True,
        required_level=RequiredLevel.CLAUSE,
        status=EvidenceStatus.VERIFIED,
    )
    chunk_no_cl = CandidateChunk(
        document_id=1,
        document_number="1",
        title="T",
        source_url="U",
        citation="C",
        article="Điều 5",
        clause=None,
        text="T",
        token_count=10,
    )
    doc_m, art_m, cl_m = match_gold_evidence(gold_clause, chunk_no_cl)
    assert doc_m is True
    assert art_m is True
    assert cl_m is False  # Clause required evidence CANNOT verify without matched clause!


# 5. Test Configured Stage Capacity Semantics & Denominators (Phase 3 & 11 Constraints)
def test_configured_capacity_24_with_two_candidates_yields_numeric_recall():
    gold = [GoldEvidence(evidence_item_id="ev1", case_id="c1", document_id=1, article="Điều 1", required=True, status=EvidenceStatus.VERIFIED)]
    candidates = [
        StageCandidate(document_id=1, article="Điều 1"),
        StageCandidate(document_id=2, article="Điều 2"),
    ]  # Only 2 candidates observed in top_k=24!

    res = calculate_stage_candidate_metrics(gold, candidates, is_doc_stage=True, stage_capacity=24)
    # Recall@3 MUST BE numeric float 1.0 (not None), because 3 <= 24!
    assert res["doc_recall_at_3"] == 1.0
    assert res["doc_recall_at_24"] == 1.0


def test_final_configured_limit_3_yields_null_recall_at_6():
    gold = [GoldEvidence(evidence_item_id="ev1", case_id="c1", document_id=1, article="Điều 1", required=True, required_level=RequiredLevel.ARTICLE, status=EvidenceStatus.VERIFIED)]
    candidates = [StageCandidate(document_id=1, article="Điều 1")]

    res = calculate_stage_candidate_metrics(gold, candidates, is_doc_stage=False, stage_capacity=3)
    assert res["article_recall_at_3"] == 1.0
    assert res["article_recall_at_6"] is None
    assert res["article_recall_at_6_reason"] == "k_exceeds_effective_stage_limit"


def test_final_configured_limit_6_yields_numeric_recall_at_6():
    gold = [GoldEvidence(evidence_item_id="ev1", case_id="c1", document_id=1, article="Điều 1", required=True, required_level=RequiredLevel.ARTICLE, status=EvidenceStatus.VERIFIED)]
    candidates = [StageCandidate(document_id=1, article="Điều 1")]

    res = calculate_stage_candidate_metrics(gold, candidates, is_doc_stage=False, stage_capacity=6)
    assert res["article_recall_at_6"] == 1.0


def test_article_and_clause_stage_recalls_and_mrr_can_differ():
    gold = [
        GoldEvidence(evidence_item_id="ev1", case_id="c1", document_id=1, article="Điều 1", clause="Khoản 2", required=True, required_level=RequiredLevel.CLAUSE, status=EvidenceStatus.VERIFIED)
    ]
    # Rank 1 chunk matches article but wrong clause
    # Rank 2 chunk matches article AND clause
    candidates = [
        StageCandidate(document_id=1, article="Điều 1", clause="Khoản 1"),
        StageCandidate(document_id=1, article="Điều 1", clause="Khoản 2"),
    ]

    res = calculate_stage_candidate_metrics(gold, candidates, is_doc_stage=False, stage_capacity=6)
    assert res["article_recall_at_1"] == 1.0
    assert res["clause_recall_at_1"] == 0.0
    assert res["article_mrr"] == 1.0
    assert res["clause_mrr"] == 0.5


# 6. Test Atomic Writes & Historical Preservation (Phase 4 & 11 Constraints)
def test_atomic_write_json_and_manifest(tmp_path):
    out_path = tmp_path / "sub" / "result.json"
    data = {"status": "success", "count": 42}
    atomic_write_json(out_path, data)

    assert out_path.exists()
    assert json.loads(out_path.read_text(encoding="utf-8")) == data


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
