def test_context_is_parsed_for_display_without_changing_original_text() -> None:
    from app.services.evidence_presenter import present_context

    context = (
        "[Điều 25 Bộ luật Lao động 45/2019/QH14]\n"
        "Nguồn: https://example.gov.vn/van-ban/45\n"
        "Tiêu đề: Bộ luật Lao động\n"
        "Người lao động thử việc tối đa 60 ngày."
    )

    view = present_context(context)

    assert view.original == context
    assert view.citation == "Điều 25 Bộ luật Lao động 45/2019/QH14"
    assert view.document_number == "45/2019/QH14"
    assert view.title == "Bộ luật Lao động"
    assert view.source_url == "https://example.gov.vn/van-ban/45"
    assert view.excerpt == "Người lao động thử việc tối đa 60 ngày."


def test_context_suppresses_non_http_source_url() -> None:
    from app.services.evidence_presenter import present_context

    view = present_context("Nguồn: javascript:alert(1)\nNội dung")

    assert view.source_url is None
    assert view.original == "Nguồn: javascript:alert(1)\nNội dung"
