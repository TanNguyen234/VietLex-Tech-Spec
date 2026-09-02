import json
from pathlib import Path


def test_export_golden_subset_preserves_case_ids_and_denominators(
    tmp_path: Path,
) -> None:
    from app.evaluation.golden_bundle import export_golden_subset

    dataset = tmp_path / "dataset.json"
    sidecar = tmp_path / "labels.json"
    dataset.write_text(
        json.dumps(
            [
                {"question": "q1", "ground_truth_answer": "a1"},
                {"question": "q2", "ground_truth_answer": "a2"},
                {"question": "q3", "ground_truth_answer": "a3"},
            ]
        ),
        encoding="utf-8",
    )
    sidecar.write_text(
        json.dumps(
            {
                "dataset_name": "test",
                "schema_version": "2.0.0",
                "total_cases": 3,
                "total_evidence_items": 3,
                "labels": [
                    {
                        "case_id": "case_001",
                        "evidence_item_id": "e1",
                        "status": "verified",
                        "required": True,
                    },
                    {
                        "case_id": "case_002",
                        "evidence_item_id": "e2",
                        "status": "verified",
                        "required": True,
                    },
                    {
                        "case_id": "case_003",
                        "evidence_item_id": "e3",
                        "status": "no_match",
                        "required": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    output_dir = tmp_path / "golden50"
    output_dir.mkdir()
    (output_dir / "README.md").write_text("bundle docs", encoding="utf-8")
    report = export_golden_subset(
        dataset_path=dataset,
        sidecar_path=sidecar,
        selected_case_ids=["case_001", "case_003"],
        output_dir=output_dir,
    )

    cases = json.loads((tmp_path / "golden50/cases.json").read_text())
    labels = json.loads((tmp_path / "golden50/labels.json").read_text())
    assert [case["case_id"] for case in cases] == ["case_001", "case_002"]
    assert [case["source_case_id"] for case in cases] == [
        "case_001",
        "case_003",
    ]
    assert [item["case_id"] for item in labels["labels"]] == [
        "case_001",
        "case_002",
    ]
    assert [item["source_case_id"] for item in labels["labels"]] == [
        "case_001",
        "case_003",
    ]
    assert report["selected_case_count"] == 2
    assert report["all_required_verified_case_count"] == 1
    assert report["cases_without_verified_retrieval_gold"] == 1
