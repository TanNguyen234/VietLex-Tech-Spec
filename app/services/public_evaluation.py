from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from threading import Lock
from typing import Any

from app.evaluation.legal_citations import parse_legal_citations


_CODE_LIMITATION = (
    "Code evaluation không chứng minh kết luận pháp lý đúng hoặc văn bản còn hiệu lực."
)

_TIMING_LABELS = {
    "t_guardrails_input": "NeMo input guardrail",
    "t_cache": "Semantic cache",
    "t_rewrite": "Query rewrite",
    "t_retrieval": "Retrieval",
    "t_hybrid": "Pinecone hybrid",
    "t_lexical": "SQLite FTS",
    "t_candidate": "Candidate merge",
    "t_resolve_chunk": "Resolve và chunk",
    "t_rerank": "Rerank",
    "t_llm": "Generation",
    "t_guardrails_output": "NeMo output guardrail",
    "t_total": "Tổng thời gian",
}


class DailyRagasQuota:
    def __init__(self, *, client_limit: int, global_limit: int) -> None:
        self._client_limit = client_limit
        self._global_limit = global_limit
        self._day: date | None = None
        self._global_count = 0
        self._client_counts: dict[str, int] = {}
        self._lock = Lock()

    def reserve(self, client_id: str, *, today: date | None = None) -> bool:
        current_day = today or date.today()
        with self._lock:
            if self._day != current_day:
                self._day = current_day
                self._global_count = 0
                self._client_counts.clear()
            client_count = self._client_counts.get(client_id, 0)
            if client_count >= self._client_limit:
                return False
            if self._global_count >= self._global_limit:
                return False
            self._client_counts[client_id] = client_count + 1
            self._global_count += 1
            return True


def build_code_evaluation(interaction: Mapping[str, Any]) -> dict[str, Any]:
    metrics = interaction.get("metrics")
    metrics = metrics if isinstance(metrics, Mapping) else {}
    latency = metrics.get("latency")
    latency = latency if isinstance(latency, Mapping) else {}
    response = str(interaction.get("bot_response") or "")
    contexts = interaction.get("contexts")
    context_count = len(contexts) if isinstance(contexts, list) else 0
    observed_context_count = int(metrics.get("context_count", context_count) or 0)
    parsed_citation_count = len(parse_legal_citations(response))
    request_status = metrics.get("request_status") or "unobserved"
    technical_error = metrics.get("technical_error") is not None
    timings = [
        {
            "key": key,
            "label": _TIMING_LABELS[key],
            "seconds": round(float(latency[key]), 4),
        }
        for key in _TIMING_LABELS
        if isinstance(latency.get(key), (int, float))
    ]
    return {
        "status": "available",
        "summary": {
            "request_status": request_status,
            "latency_seconds": latency.get("t_total"),
            "cached": bool(interaction.get("cached")),
            "context_count": observed_context_count,
            "citation_count": metrics.get("citation_count", 0),
            "parsed_citation_count": parsed_citation_count,
            "no_evidence": bool(metrics.get("no_evidence")),
            "technical_error": technical_error,
            "observed_provider": metrics.get("observed_provider") or "unobserved",
            "observed_model": metrics.get("observed_model") or "unobserved",
        },
        "checks": [
            {
                "key": "request_completed",
                "label": "Request hoàn tất",
                "status": "pass" if request_status in {"ok", "cache_hit"} and not technical_error else "fail",
                "value": request_status,
                "meaning": "Backend hoàn thành request mà không ghi nhận lỗi kỹ thuật.",
            },
            {
                "key": "context_present",
                "label": "Có context",
                "status": "pass" if observed_context_count > 0 else "fail",
                "value": observed_context_count,
                "meaning": "Số đoạn bằng chứng được đưa vào bước tạo câu trả lời.",
            },
            {
                "key": "citation_present",
                "label": "Có trích dẫn",
                "status": "pass" if parsed_citation_count > 0 else "fail",
                "value": parsed_citation_count,
                "meaning": "Số trích dẫn pháp lý được code nhận diện trong câu trả lời.",
            },
        ],
        "timings": timings,
        "limitations": [_CODE_LIMITATION],
    }


def ragas_metric_catalog(*, has_reference: bool) -> list[dict[str, Any]]:
    return [
        {
            "key": "faithfulness",
            "label": "Faithfulness",
            "meaning": "Mức độ các nhận định trong câu trả lời được context hỗ trợ.",
            "applicable": True,
            "limitation": "Điểm cao không chứng minh context hoặc kết luận pháp lý đúng.",
        },
        {
            "key": "answer_relevance",
            "label": "Answer Relevance",
            "meaning": "Mức độ câu trả lời trực tiếp giải quyết câu hỏi của người dùng.",
            "applicable": True,
            "limitation": "Điểm dùng LLM và embedding judge; không chứng minh đúng pháp lý.",
        },
        {
            "key": "answer_accuracy",
            "label": "Answer Accuracy",
            "meaning": "Mức độ câu trả lời phù hợp với đáp án tham chiếu.",
            "applicable": has_reference,
            "display_value": None if has_reference else "N/A",
            "reason_not_applicable": "Public chat không có reference answer đã kiểm chứng.",
            "limitation": "Cần đáp án tham chiếu đã được kiểm chứng.",
        },
        {
            "key": "context_precision",
            "label": "Context Precision",
            "meaning": "Mức độ context truy xuất tập trung vào bằng chứng liên quan.",
            "applicable": has_reference,
            "display_value": None if has_reference else "N/A",
            "reason_not_applicable": "Public chat không có reference contexts đã kiểm chứng.",
            "limitation": "Cần bằng chứng tham chiếu để chấm đáng tin cậy.",
        },
        {
            "key": "context_recall",
            "label": "Context Recall",
            "meaning": "Tỷ lệ bằng chứng cần thiết được tìm thấy trong context.",
            "applicable": has_reference,
            "display_value": None if has_reference else "N/A",
            "reason_not_applicable": "Public chat không có reference contexts đầy đủ.",
            "limitation": "Cần tập reference contexts đầy đủ.",
        },
    ]
