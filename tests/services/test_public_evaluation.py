def test_code_evaluation_reports_observations_without_claiming_correctness() -> None:
    from app.services.public_evaluation import build_code_evaluation

    result = build_code_evaluation(
        {
            "cached": False,
            "bot_response": "Theo Điều 25 Bộ luật Lao động, thời hạn là 60 ngày.",
            "contexts": ["[Điều 25 Bộ luật Lao động]\nNội dung"],
            "metrics": {
                "request_status": "ok",
                "latency": {
                    "t_total": 1.25,
                    "t_cache": 0.1,
                    "t_retrieval": 0.7,
                    "ignored_metadata": "not numeric",
                },
                "context_count": 1,
                "citation_count": 1,
                "no_evidence": False,
                "technical_error": None,
                "observed_provider": "vertex",
                "observed_model": "gemini-3.5-flash",
            },
        }
    )

    assert result["status"] == "available"
    assert result["summary"]["request_status"] == "ok"
    assert result["summary"]["latency_seconds"] == 1.25
    assert result["summary"]["context_count"] == 1
    assert result["summary"]["parsed_citation_count"] == 1
    assert result["checks"] == [
        {
            "key": "request_completed",
            "label": "Request hoàn tất",
            "status": "pass",
            "value": "ok",
            "meaning": "Backend hoàn thành request mà không ghi nhận lỗi kỹ thuật.",
        },
        {
            "key": "context_present",
            "label": "Có context",
            "status": "pass",
            "value": 1,
            "meaning": "Số đoạn bằng chứng được đưa vào bước tạo câu trả lời.",
        },
        {
            "key": "citation_present",
            "label": "Có trích dẫn",
            "status": "pass",
            "value": 1,
            "meaning": "Số trích dẫn pháp lý được code nhận diện trong câu trả lời.",
        },
    ]
    assert result["timings"] == [
        {"key": "t_cache", "label": "Semantic cache", "seconds": 0.1},
        {"key": "t_retrieval", "label": "Retrieval", "seconds": 0.7},
        {"key": "t_total", "label": "Tổng thời gian", "seconds": 1.25},
    ]
    assert result["limitations"] == [
        "Code evaluation không chứng minh kết luận pháp lý đúng hoặc văn bản còn hiệu lực."
    ]
    assert "accuracy" not in result["summary"]


def test_ragas_metric_catalog_marks_reference_metrics_not_applicable() -> None:
    from app.services.public_evaluation import ragas_metric_catalog

    metrics = {item["key"]: item for item in ragas_metric_catalog(has_reference=False)}

    assert metrics["faithfulness"]["applicable"] is True
    assert metrics["answer_relevance"]["applicable"] is True
    assert metrics["answer_accuracy"]["applicable"] is False
    assert metrics["context_precision"]["applicable"] is False
    assert metrics["context_recall"]["applicable"] is False
    assert "không chứng minh" in metrics["faithfulness"]["limitation"]


def test_ragas_metric_catalog_explains_missing_reference_scores() -> None:
    from app.services.public_evaluation import ragas_metric_catalog

    metrics = {item["key"]: item for item in ragas_metric_catalog(has_reference=False)}

    for key in ("answer_accuracy", "context_precision", "context_recall"):
        assert metrics[key]["display_value"] == "N/A"
        assert "reference" in metrics[key]["reason_not_applicable"].casefold()


def test_daily_ragas_quota_enforces_client_and_global_budgets() -> None:
    from datetime import date

    from app.services.public_evaluation import DailyRagasQuota

    quota = DailyRagasQuota(client_limit=2, global_limit=3)

    assert quota.reserve("client-a", today=date(2026, 8, 22)) is True
    assert quota.reserve("client-a", today=date(2026, 8, 22)) is True
    assert quota.reserve("client-a", today=date(2026, 8, 22)) is False
    assert quota.reserve("client-b", today=date(2026, 8, 22)) is True
    assert quota.reserve("client-c", today=date(2026, 8, 22)) is False
    assert quota.reserve("client-a", today=date(2026, 8, 23)) is True
