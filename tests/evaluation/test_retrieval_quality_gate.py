from __future__ import annotations

import json
from pathlib import Path

import pytest


def _metric(value: float) -> dict[str, float]:
    return {"micro": value, "numerator": value, "denominator": 1}


def test_retrieval_gate_accepts_required_metrics() -> None:
    from app.evaluation.retrieval_gate import evaluate_retrieval_gate

    summary = {
        "document_recall": {3: _metric(1.0)},
        "article_recall": {3: _metric(0.96)},
        "clause_recall": {3: _metric(0.90)},
        "multi_hop_all_required": _metric(0.95),
        "no_candidate_rate": _metric(0.0),
        "retrieval_technical_error_rate": _metric(0.0),
        "reranker_technical_error_rate": _metric(0.0),
    }

    result = evaluate_retrieval_gate(summary, k=3)

    assert result["passed"] is True
    assert result["failures"] == []


def test_retrieval_gate_rejects_weak_recall_before_ragas() -> None:
    from app.evaluation.retrieval_gate import evaluate_retrieval_gate

    summary = {
        "document_recall": {3: _metric(0.0)},
        "article_recall": {3: _metric(0.0)},
        "clause_recall": {3: _metric(0.0)},
        "multi_hop_all_required": _metric(0.0),
        "no_candidate_rate": _metric(0.0),
        "retrieval_technical_error_rate": _metric(0.0),
        "reranker_technical_error_rate": _metric(0.0),
    }

    result = evaluate_retrieval_gate(summary, k=3)

    assert result["passed"] is False
    assert "document_recall@3" in result["failures"]


def test_retrieval_run_binding_rejects_different_ranking(tmp_path: Path) -> None:
    from app.evaluation.retrieval_gate import validate_retrieval_run

    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "dataset_sha256": "dataset",
                "selected_case_ids_sha256": "cases",
                "configuration": {
                    "requested_backend": "vertex-qdrant-v3",
                    "ranking_mode": "raw-rrf",
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "retrieval_results.json").write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="ranking"):
        validate_retrieval_run(
            tmp_path,
            expected_backend="vertex-qdrant-v3",
            expected_ranking="qdrant-colbert",
            expected_dataset_sha256="dataset",
            expected_selected_case_ids_sha256="cases",
            k=3,
        )
