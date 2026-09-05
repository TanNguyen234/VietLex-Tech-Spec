import json

from app.services.evaluation_lab import load_evaluation_lab


def test_evaluation_lab_reads_provenance_and_bounded_case(tmp_path) -> None:
    run = tmp_path / "answer-run"
    run.mkdir()
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "answer-run",
                "utc_timestamp": "2026-09-03T00:00:00Z",
                "git_sha": "abc123",
                "git_dirty": True,
                "dataset_revision": "dataset-rev",
                "dataset_sha256": "dataset-sha",
                "configuration_fingerprint": "config-sha",
                "judge_mode": "ragas",
                "selected_case_count": 1,
                "provenance_status": "ok",
            }
        ),
        encoding="utf-8",
    )
    (run / "answer_results.json").write_text(
        json.dumps(
            [
                {
                    "case_id": "case_001",
                    "question": "Câu hỏi",
                    "status": "ok",
                    "final_response": "Câu trả lời",
                    "metrics": {"token_f1": 0.25, "citation_precision": 1.0},
                    "ragas_metrics": {"faithfulness": 0.8},
                    "retrieval_result": {
                        "metrics": {
                            "document_recall": {"3": {"value": 1.0}},
                            "exact_reference_hit": {"value": 1.0},
                        },
                        "retrieved_evidence": [
                            {
                                "citation": "Điều 1",
                                "text": "Trích đoạn",
                                "document_id": 7,
                            }
                        ],
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    result = load_evaluation_lab(run, case_id="case_001")

    assert result["status"] == "available"
    assert result["provenance"]["git_dirty"] is True
    assert result["case"]["evidence"][0]["citation"] == "Điều 1"
    assert result["case"]["ragas_metrics"]["faithfulness"] == 0.8
    assert (
        result["deterministic_metrics"]["retrieval.document_recall_at_3"]["mean"] == 1.0
    )
    assert result["deterministic_metrics"]["token_f1"]["numerator"] == 0.25
    assert result["deterministic_metrics"]["token_f1"]["denominator"] == 1
    assert "whole-corpus" in result["boundary"]


def test_evaluation_lab_fails_closed_for_missing_or_invalid_artifact(tmp_path) -> None:
    assert load_evaluation_lab(tmp_path / "missing")["status"] == "unavailable"
    run = tmp_path / "bad"
    run.mkdir()
    (run / "manifest.json").write_text("not json", encoding="utf-8")
    assert load_evaluation_lab(run)["status"] == "invalid"


def test_evaluation_lab_handles_invalid_nested_artifacts(tmp_path) -> None:
    (tmp_path / "manifest.json").write_text('{"run_id":"test"}', encoding="utf-8")
    (tmp_path / "answer_results.json").write_text(
        '[{"retrieval_result":42}]', encoding="utf-8"
    )
    assert load_evaluation_lab(tmp_path)["status"] == "invalid"


def test_evaluation_lab_preserves_unscored_coverage_and_skip_reason(tmp_path) -> None:
    (tmp_path / "manifest.json").write_text('{"run_id":"test"}', encoding="utf-8")
    (tmp_path / "answer_results.json").write_text(
        json.dumps(
            [
                {"case_id": "a", "metrics": {"token_f1": 0.5}},
                {
                    "case_id": "b",
                    "metrics": {"token_f1": None, "skip_reason": "no_reference"},
                },
            ]
        ),
        encoding="utf-8",
    )
    metric = load_evaluation_lab(tmp_path)["deterministic_metrics"]["token_f1"]
    assert metric["mean"] == 0.5
    assert metric["coverage"] == 1 and metric["total"] == 2
    assert metric["skipped"] == 1
    assert metric["skip_reasons"] == {"no_reference": 1}
