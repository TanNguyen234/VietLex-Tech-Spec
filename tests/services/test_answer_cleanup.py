"""Echoed evidence headers are removed from the answer body; ordinary answers are untouched."""

from app.services.answer_cleanup import strip_context_echo


def test_echoed_unnumbered_header_and_blockquote_are_removed() -> None:
    answer = (
        "Thời gian báo trước là 45 ngày [Bộ luật Lao động 2019, Điều 35, Khoản 1, Điểm a].\n\n"
        "**Đoạn mở đầu không đánh số — [45/2019/QH14, Điều 40]:**\n"
        "> Điều 40. Nghĩa vụ của người lao động khi đơn phương chấm dứt hợp đồng lao động trái pháp luật\n"
    )

    cleaned = strip_context_echo(answer)

    assert cleaned == "Thời gian báo trước là 45 ngày [Bộ luật Lao động 2019, Điều 35, Khoản 1, Điểm a]."
    assert "Đoạn mở đầu" not in cleaned
    assert "Điều 40" not in cleaned


def test_text_after_the_echo_block_is_kept_when_it_is_not_a_quote() -> None:
    answer = (
        "Kết luận chính.\n"
        "Đoạn mở đầu không đánh số — [91/2015/QH13, Điều 119]:\n"
        "> Điều 119. Hình thức giao dịch dân sự\n"
        "Lưu ý: thông tin chỉ mang tính tham khảo."
    )

    cleaned = strip_context_echo(answer)

    assert cleaned == "Kết luận chính.\nLưu ý: thông tin chỉ mang tính tham khảo."


def test_answer_without_the_echo_label_is_returned_unchanged() -> None:
    answer = "Hợp đồng lao động phải được giao kết bằng văn bản [Bộ luật Lao động 2019, Điều 14, Khoản 1]."

    assert strip_context_echo(answer) == answer


def test_empty_answer_is_handled() -> None:
    assert strip_context_echo("") == ""
    assert strip_context_echo(None) == ""
