from app.services.legal_timeline import build_legal_timeline
import pytest


def test_timeline_preserves_offsets_and_sorts_dates():
    text = "Ký ngày 03/02/2025. Giao ngày 01/01/2025."
    result = build_legal_timeline([{"evidence_id": "e1", "excerpt": text}])
    assert [r["date"] for r in result["events"]] == ["2025-01-01", "2025-02-03"]
    for row in result["events"]:
        assert text[row["start"] : row["end"]] == row["quote"]
        assert row["evidence_id"] == "e1"
    assert result["legal_effect_status"] == "unverified"


def test_timeline_does_not_invent_relative_deadline_or_invalid_date():
    result = build_legal_timeline(
        [
            {
                "evidence_id": "e1",
                "excerpt": "Trả trong 30 ngày từ khi nhận. Ký 31/02/2025.",
            }
        ]
    )
    assert result["events"] == []
    assert {r["reason"] for r in result["unresolved"]} == {
        "relative_date_requires_trigger",
        "invalid_calendar_date",
    }


def test_empty_source_has_explicit_coverage_and_duplicate_id_rejected():
    result = build_legal_timeline(
        [{"evidence_id": "e1", "excerpt": "Không có mốc ngày."}]
    )
    assert result["coverage"] == {
        "sources_total": 1,
        "sources_with_dates": 0,
        "events": 0,
        "unresolved": 0,
    }
    with pytest.raises(ValueError):
        build_legal_timeline([{"evidence_id": "e1"}, {"evidence_id": "e1"}])
