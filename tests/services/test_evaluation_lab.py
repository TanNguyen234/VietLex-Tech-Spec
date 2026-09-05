import json
import pytest

from app.services.evaluation_lab import load_evaluation_lab


@pytest.mark.parametrize("failures", [None, "error", [42], {}])
def test_lab_rejects_malformed_gate_failures(tmp_path, failures):
    (tmp_path / "manifest.json").write_text('{"run_id":"r"}')
    (tmp_path / "answer_results.json").write_text("[]")
    (tmp_path / "quality_gate.json").write_text(
        json.dumps({"passed": False, "failures": failures})
    )
    assert load_evaluation_lab(tmp_path)["status"] == "invalid"


def test_lab_uses_current_manifest_provider_and_metric_fields(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "r",
                "code_metric_version": "v3",
                "configured_provider_models": {"answer": "test-model"},
            }
        )
    )
    (tmp_path / "answer_results.json").write_text("[]")
    result = load_evaluation_lab(tmp_path)
    assert result["provenance"]["code_metric_version"] == "v3"
    assert result["provenance"]["configured_provider_models"] == {
        "answer": "test-model"
    }


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


def test_lab_reads_retrieval_gate_and_missing_metrics(tmp_path):
    (tmp_path / "manifest.json").write_text(
        '{"run_id":"retrieval","selected_case_count":2}'
    )
    (tmp_path / "retrieval_results.json").write_text(
        json.dumps(
            [
                {
                    "case_id": "a",
                    "status": "ok",
                    "latency": {"t_total": 2},
                    "metrics": {
                        "document_recall": {"3": {"value": 1}},
                        "no_candidate": False,
                    },
                },
                {
                    "case_id": "b",
                    "status": "retrieval_error",
                    "latency": {"t_total": 4},
                    "metrics": {
                        "document_recall": {
                            "3": {"value": None, "reason": "technical_error"}
                        },
                        "no_candidate": True,
                    },
                },
            ]
        )
    )
    (tmp_path / "quality_gate.json").write_text(
        '{"passed":false,"failures":["retrieval_technical_error_rate"]}'
    )
    result = load_evaluation_lab(tmp_path, case_id="b")
    assert result["status"] == "available"
    assert result["run_kind"] == "retrieval"
    assert result["quality_gate"]["passed"] is False
    assert result["status_counts"] == {"ok": 1, "retrieval_error": 1}
    assert result["latency"]["t_total"]["mean"] == 3
    assert (
        result["deterministic_metrics"]["retrieval.document_recall_at_3"]["coverage"]
        == 1
    )
    assert result["deterministic_metrics"]["retrieval.no_candidate"]["mean"] == 0.5


def test_lab_keeps_all_missing_answer_metrics_and_reports_truncation(tmp_path):
    (tmp_path / "manifest.json").write_text('{"run_id":"answer"}')
    (tmp_path / "answer_results.json").write_text(
        json.dumps(
            [
                {
                    "case_id": str(i),
                    "metrics": {
                        "number_precision": None,
                        "skip_reason": "no_reference",
                    },
                }
                for i in range(105)
            ]
        )
    )
    result = load_evaluation_lab(tmp_path)
    assert result["record_count"] == 105
    assert result["displayed_count"] == 100
    assert result["truncated"] is True
    assert len(result["cases"]) == 100
    metric = result["deterministic_metrics"]["number_precision"]
    assert metric["mean"] is None and metric["coverage"] == 0
    assert metric["skip_reasons"] == {"no_reference": 100}


def test_lab_exposes_all_recorded_recall_cutoffs_and_stage_survival(tmp_path):
    (tmp_path / "manifest.json").write_text('{"run_id":"r"}')
    (tmp_path / "retrieval_results.json").write_text(
        json.dumps(
            [
                {
                    "metrics": {
                        "document_recall": {"10": {"value": 0.5}},
                        "stages": {
                            "final_evidence_metrics": {
                                "candidate_count": 3,
                                "recall": {"article": {"3": {"value": 0.25}}},
                            }
                        },
                    }
                }
            ]
        )
    )
    result = load_evaluation_lab(tmp_path)
    assert (
        result["deterministic_metrics"]["retrieval.document_recall_at_10"]["mean"]
        == 0.5
    )
    assert (
        result["stage_metrics"]["final_evidence_metrics.article_recall_at_3"]["mean"]
        == 0.25
    )
