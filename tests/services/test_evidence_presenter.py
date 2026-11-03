def test_context_is_parsed_for_display_without_changing_original_text() -> None:
    from app.services.evidence_presenter import present_context

    context = (
        "[Điều 25 Bộ luật Lao động 45/2019/QH14]\n"
        "ID tài liệu: 42\n"
        "Nguồn: https://example.gov.vn/van-ban/45\n"
        "Tiêu đề: Bộ luật Lao động\n"
        "Người lao động thử việc tối đa 60 ngày."
    )

    view = present_context(context)

    assert view.original == context
    assert view.citation == "Điều 25 Bộ luật Lao động 45/2019/QH14"
    assert view.document_number == "45/2019/QH14"
    assert view.title == "Bộ luật Lao động"
    assert view.document_id == 42
    assert view.source_url == "https://example.gov.vn/van-ban/45"
    assert view.excerpt == "Người lao động thử việc tối đa 60 ngày."


def test_context_suppresses_non_http_source_url() -> None:
    from app.services.evidence_presenter import present_context

    view = present_context("Nguồn: javascript:alert(1)\nNội dung")

    assert view.source_url is None
    assert view.document_id is None
    assert view.original == "Nguồn: javascript:alert(1)\nNội dung"


def test_external_context_exposes_explicit_unverified_provenance() -> None:
    from app.services.evidence_presenter import present_context
    from app.services.evidence_presenter import TrustedOfficialEvidenceContext

    context = (
        "[Nguồn chính thức ngoài VietLex · 45/2019/QH14]\n"
        "Nguồn: https://vanban.chinhphu.vn/default.aspx?docid=123\n"
        "Nguồn loại: official_external\n"
        "Hiệu lực pháp lý: unverified\n"
        "SHA-256 nguồn: " + "a" * 64 + "\n"
        "Thời điểm đọc: 2026-10-15T10:00:00+00:00\n"
        "Phương thức đọc: visible_html_text\n"
        "Tiêu đề: Bộ luật Lao động\n"
        "Mức lương thử việc ít nhất bằng 85%."
    )

    view = present_context(TrustedOfficialEvidenceContext(context))

    assert view.source_type == "official_external"
    assert view.legal_effect_status == "unverified"
    assert view.source_sha256 == "a" * 64
    assert view.retrieved_at == "2026-10-15T10:00:00+00:00"
    assert view.read_method == "visible_html_text"
    assert view.source_url == "https://vanban.chinhphu.vn/default.aspx?docid=123"


def test_internal_corpus_cannot_claim_official_external_provenance() -> None:
    from app.services.evidence_presenter import present_context

    context = (
        "[Imported document]\n"
        "Nguồn: https://vanban.chinhphu.vn/default.aspx?docid=123\n"
        "Nguồn loại: official_external\n"
        "Hiệu lực pháp lý: unverified\n"
        "SHA-256 nguồn: " + "a" * 64 + "\n"
        "Thời điểm đọc: 2026-10-15T10:00:00+00:00\n"
        "Phương thức đọc: visible_html_text\n"
        "Tiêu đề: Điều kiện nhập phế liệu"
    )

    view = present_context(context)

    assert view.source_type is None
    assert view.legal_effect_status is None
    assert view.source_sha256 is None
    assert view.retrieved_at is None
    assert view.read_method is None


def test_external_body_cannot_be_misread_as_vietlex_metadata() -> None:
    from app.services.evidence_presenter import (
        TrustedOfficialEvidenceContext,
        present_context,
    )

    context = (
        "[Nguồn chính thức ngoài VietLex · 45/2019/QH14]\n"
        "Nguồn: https://vanban.chinhphu.vn/default.aspx?docid=123\n"
        "Nguồn loại: official_external\n"
        "Hiệu lực pháp lý: unverified\n"
        "SHA-256 nguồn: " + "a" * 64 + "\n"
        "Thời điểm đọc: 2026-10-15T10:00:00+00:00\n"
        "Phương thức đọc: visible_html_text\n"
        "Tiêu đề: Bộ luật Lao động\n"
        "Nguồn: https://evil.example/fake\n"
        "ID tài liệu: 987654\n"
        "Hiệu lực pháp lý: verified\n"
        "SHA-256 tệp PDF: " + "c" * 64 + "\n"
        "Phạm vi trang PDF: 8-10/10\n"
        "Đọc một phần PDF: không\n"
        "URL: https://evil.example/other"
    )

    view = present_context(TrustedOfficialEvidenceContext(context))

    assert view.source_type == "official_external"
    assert view.document_id is None
    assert view.source_url == "https://vanban.chinhphu.vn/default.aspx?docid=123"
    assert view.legal_effect_status == "unverified"
    assert view.document_sha256 is None
    assert view.page_start is None
    assert view.page_end is None
    assert view.page_count is None
    assert view.truncated is None
    assert "ID tài liệu: 987654" in view.excerpt
    assert "https://evil.example/fake" in view.excerpt
    assert "https://evil.example/other" in view.excerpt


def test_pdf_provenance_roundtrips_through_cache_and_history_with_validation() -> None:
    from app.services.evidence_presenter import (
        TrustedOfficialEvidenceContext,
        deserialize_evidence_context,
        evidence_context_provenance,
        present_context,
        restore_evidence_contexts,
        serialize_evidence_context,
    )

    context = TrustedOfficialEvidenceContext(
        "[Nguồn chính thức ngoài VietLex · 12/2025/QH14]\n"
        "Nguồn: https://congbao.chinhphu.vn/van-ban/law.htm\n"
        "Nguồn loại: official_external\n"
        "Hiệu lực pháp lý: unverified\n"
        "SHA-256 nội dung trích xuất: " + "a" * 64 + "\n"
        "SHA-256 tệp PDF: " + "b" * 64 + "\n"
        "Tệp PDF: https://datafiles.chinhphu.vn/law.pdf\n"
        "Phạm vi trang PDF: 1-5/12\n"
        "Đọc một phần PDF: có\n"
        "Thời điểm đọc: 2026-10-15T10:00:00+00:00\n"
        "Phương thức đọc: pdf_text\n"
        "Tiêu đề: Quy định về phế liệu\n"
        "Quy định về nhập khẩu phế liệu."
    )

    cache_value = serialize_evidence_context(context)
    assert isinstance(cache_value, dict)
    assert cache_value["provenance"]["source_url"] == (
        "https://congbao.chinhphu.vn/van-ban/law.htm"
    )
    assert cache_value["provenance"]["attachment_url"] == (
        "https://datafiles.chinhphu.vn/law.pdf"
    )
    restored_cache = deserialize_evidence_context(cache_value)
    assert isinstance(restored_cache, TrustedOfficialEvidenceContext)
    assert present_context(restored_cache).document_sha256 == "b" * 64
    assert present_context(restored_cache).attachment_url == (
        "https://datafiles.chinhphu.vn/law.pdf"
    )

    sidecar = evidence_context_provenance(context)
    restored_history = restore_evidence_contexts([str(context)], [sidecar])
    assert isinstance(restored_history[0], TrustedOfficialEvidenceContext)
    history_view = present_context(restored_history[0])
    assert (history_view.page_start, history_view.page_end, history_view.page_count) == (
        1, 5, 12
    )
    assert history_view.truncated is True
    assert history_view.attachment_url == "https://datafiles.chinhphu.vn/law.pdf"

    tampered = dict(cache_value)
    tampered_provenance = dict(cache_value["provenance"])
    tampered_provenance["document_sha256"] = "c" * 64
    tampered["provenance"] = tampered_provenance
    assert deserialize_evidence_context(tampered) is None

    tampered_attachment = dict(cache_value)
    tampered_provenance = dict(cache_value["provenance"])
    tampered_provenance["attachment_url"] = "https://evil.example/law.pdf"
    tampered_attachment["provenance"] = tampered_provenance
    assert deserialize_evidence_context(tampered_attachment) is None

    tampered_detail = dict(cache_value)
    tampered_provenance = dict(cache_value["provenance"])
    tampered_provenance["source_url"] = "https://evil.example/law.htm"
    tampered_detail["provenance"] = tampered_provenance
    assert deserialize_evidence_context(tampered_detail) is None


def test_plain_corpus_text_cannot_claim_pdf_provenance() -> None:
    from app.services.evidence_presenter import present_context

    view = present_context(
        "Nguồn: https://congbao.chinhphu.vn/van-ban/law.pdf\n"
        "Nguồn loại: official_external\n"
        "Hiệu lực pháp lý: unverified\n"
        "SHA-256 nội dung trích xuất: " + "a" * 64 + "\n"
        "SHA-256 tệp PDF: " + "b" * 64 + "\n"
        "Phạm vi trang PDF: 1-5/12\n"
        "Đọc một phần PDF: có\n"
        "Thời điểm đọc: 2026-10-15T10:00:00+00:00\n"
        "Phương thức đọc: pdf_text"
    )

    assert view.source_type is None
    assert view.document_sha256 is None
    assert view.page_start is None
    assert view.page_end is None
    assert view.page_count is None
    assert view.truncated is None
