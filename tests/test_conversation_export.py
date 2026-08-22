from datetime import datetime


def test_markdown_export_contains_trace_sources_and_safe_heading() -> None:
    from app.services.conversation_export import render_conversation_markdown

    result = render_conversation_markdown(
        {"title": "Hợp đồng # lao động"},
        [
            {
                "timestamp": datetime(2026, 8, 22, 9, 30),
                "trace_id": "trace-123",
                "user_query": "Thử việc bao lâu?",
                "bot_response": "Tối đa 60 ngày.",
                "contexts": ["Dẫn chiếu: Điều 25\nNội dung nguồn"],
            }
        ],
    )

    assert result.startswith("# Hợp đồng \\# lao động\n")
    assert "**Trace:** `trace-123`" in result
    assert "## Người dùng" in result
    assert "## VietLex" in result
    assert "> Dẫn chiếu: Điều 25" in result
    assert result.endswith("\n")
