from pathlib import Path
from types import SimpleNamespace

import pytest


def test_portfolio_evidence_loader_reads_scores_and_boundary(tmp_path: Path) -> None:
    from app.services.portfolio_evidence import load_portfolio_evidence

    report = tmp_path / "report.md"
    report.write_text(
        "# Report\n| Ragas Faithfulness | 0.9158 |\n"
        "| Ragas Answer Accuracy | 0.8950 |\n"
        "| Ragas Context Precision | 0.8757 |\n"
        "| Ragas Context Recall | 0.9333 |\n",
        encoding="utf-8",
    )

    result = load_portfolio_evidence(report)

    assert result["status"] == "available"
    assert result["scores"] == {
        "faithfulness": 0.9158,
        "answer_accuracy": 0.895,
        "context_precision": 0.8757,
        "context_recall": 0.9333,
    }
    assert "không chứng minh" in result["boundary"]


def test_admin_template_uses_local_assets_and_evidence_summary() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "app/templates/admin.html").read_text(encoding="utf-8")

    assert "cdn.tailwindcss.com" not in html
    assert "unpkg.com" not in html
    assert 'href="/static/css/vietlex.css"' in html
    assert "portfolio_evidence" in html
    assert "Lỗi kỹ thuật" in html
    assert "Ragas coverage" in html


class _AggregateCursor:
    def __init__(self, row):
        self.row = row

    async def to_list(self, *, length):
        return [self.row][:length]


class _AggregateCollection:
    def __init__(self, row):
        self.row = row
        self.pipeline = None

    def aggregate(self, pipeline):
        self.pipeline = pipeline
        return _AggregateCursor(self.row)


@pytest.mark.asyncio
async def test_admin_stats_include_technical_errors_and_ragas_coverage(monkeypatch) -> None:
    import app.database as database

    facets = {
        "total": [{"count": 10}],
        "cached": [{"count": 2}],
        "avg_faithfulness": [],
        "avg_relevance": [],
        "total_feedback": [],
        "positive_feedback": [],
        "technical_errors": [{"count": 1}],
        "ragas_executed": [{"count": 4}],
    }
    collection = _AggregateCollection(facets)
    monkeypatch.setattr(
        database,
        "get_db",
        lambda: SimpleNamespace(evaluation_logs=collection),
    )

    stats = await database.get_admin_stats()

    assert stats["technical_error_count"] == 1
    assert stats["ragas_coverage_rate"] == 40.0
    facet = collection.pipeline[0]["$facet"]
    assert "technical_errors" in facet
    assert "ragas_executed" in facet
