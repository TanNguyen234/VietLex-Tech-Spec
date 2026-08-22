from __future__ import annotations

import re
from pathlib import Path
from typing import Any


_METRICS = {
    "faithfulness": ("Ragas Faithfulness", "faithfulness"),
    "answer_accuracy": ("Ragas Answer Accuracy", "answer_accuracy"),
    "context_precision": ("Ragas Context Precision", "context_precision"),
    "context_recall": ("Ragas Context Recall", "context_recall"),
}


def load_portfolio_evidence(report_path: Path) -> dict[str, Any]:
    if not report_path.is_file():
        return {"status": "unavailable", "scores": {}, "boundary": "Báo cáo chưa có."}
    text = report_path.read_text(encoding="utf-8")
    scores: dict[str, float] = {}
    for key, labels in _METRICS.items():
        label_pattern = "|".join(re.escape(label) for label in labels)
        match = re.search(
            rf"\|\s*`?(?:{label_pattern})`?\s*\|\s*(?:`|\*\*)?([01](?:\.\d+)?)",
            text,
            re.IGNORECASE,
        )
        if match:
            scores[key] = float(match.group(1))
    return {
        "status": "available" if scores else "unavailable",
        "scores": scores,
        "boundary": (
            "Các điểm số chứng minh một lát cắt benchmark có giới hạn; "
            "không chứng minh độ chính xác pháp lý toàn corpus hoặc production readiness."
        ),
        "report_path": str(report_path),
    }
