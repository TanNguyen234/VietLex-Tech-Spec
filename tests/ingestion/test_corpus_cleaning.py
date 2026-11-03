from __future__ import annotations

import hashlib
import importlib
from dataclasses import replace


def _cleaner_module():
    return importlib.import_module("app.ingestion.corpus_cleaning")


VIETNAMESE_AD = (
    "Bạn phải đăng nhập hoặc đăng ký Thành Viên TVPL Pro để sử dụng được "
    "đầy đủ các tiện ích gia tăng liên quan đến nội dung TCVN."
)
ENGLISH_AD = (
    "Please sign up or sign in to your TVPL Pro Membership to see English "
    "documents."
)
CONTACT = "Mọi chi tiết xin liên hệ: ĐT: (028) 3930 3279 DĐ: 0906 22 99 66"


def test_removes_only_exact_standalone_ad_paragraphs_and_reports_byte_spans() -> None:
    cleaner = _cleaner_module()
    raw = (
        "Căn cứ pháp lý…\n\n"
        + VIETNAMESE_AD
        + "\n\n"
        + ENGLISH_AD
        + "\n\n"
        + "Ngày ban hành: 01/02/2024; không áp dụng cho TCVN khác."
    )

    result = cleaner.clean_corpus_text(raw)

    assert result.cleaned_text == (
        "Căn cứ pháp lý…\n\n\n\n\n\n"
        "Ngày ban hành: 01/02/2024; không áp dụng cho TCVN khác."
    )
    assert [span.rule_id for span in result.deletion_spans] == [
        "tvpl_pro_vietnamese_tcvn_ad",
        "tvpl_pro_english_documents_ad",
    ]
    raw_bytes = raw.encode("utf-8")
    assert [
        raw_bytes[span.start_byte : span.end_byte].decode("utf-8")
        for span in result.deletion_spans
    ] == [VIETNAMESE_AD, ENGLISH_AD]
    rebuilt = bytearray(result.cleaned_text.encode("utf-8"))
    for span in result.deletion_spans:
        rebuilt[span.start_byte : span.start_byte] = span.removed_text.encode("utf-8")
    assert bytes(rebuilt) == raw_bytes
    assert result.raw_sha256 == hashlib.sha256(raw_bytes).hexdigest()
    assert result.cleaned_sha256 == hashlib.sha256(
        result.cleaned_text.encode("utf-8")
    ).hexdigest()
    assert cleaner.verify_reconstruction(raw, result)
    assert not cleaner.verify_reconstruction(
        raw,
        replace(result, cleaned_text=result.cleaned_text + "tampered"),
    )


def test_exact_contact_is_removed_only_when_adjacent_to_vietnamese_ad() -> None:
    cleaner = _cleaner_module()
    raw = "Trước\n\n" + CONTACT + "\n\n" + VIETNAMESE_AD + "\n\nSau"

    result = cleaner.clean_corpus_text(raw)

    assert result.cleaned_text == "Trước\n\n\n\n\n\nSau"
    assert [span.rule_id for span in result.deletion_spans] == [
        "tvpl_contact_adjacent_to_vietnamese_ad",
        "tvpl_pro_vietnamese_tcvn_ad",
    ]
    assert [span.removed_text for span in result.deletion_spans] == [
        CONTACT,
        VIETNAMESE_AD,
    ]
    assert cleaner.verify_reconstruction(raw, result)


def test_preserves_contact_alone_and_contact_adjacent_to_english_ad() -> None:
    cleaner = _cleaner_module()
    alone = "Mọi chi tiết xin liên hệ: ĐT: (028) 3930 3279 DĐ: 0906 22 99 66"
    beside_english = CONTACT + "\n\n" + ENGLISH_AD

    alone_result = cleaner.clean_corpus_text(alone)
    english_result = cleaner.clean_corpus_text(beside_english)

    assert alone_result.cleaned_text == alone
    assert alone_result.deletion_spans == ()
    assert english_result.cleaned_text == CONTACT + "\n\n"
    assert [span.rule_id for span in english_result.deletion_spans] == [
        "tvpl_pro_english_documents_ad"
    ]


def test_preserves_variants_and_legal_mentions() -> None:
    cleaner = _cleaner_module()
    raw = (
        "Bạn phải đăng nhập hoặc đăng ký thành viên TVPL Pro để sử dụng đầy "
        "đủ tiện ích liên quan nội dung TCVN.\n\n"
        "Mọi chi tiết xin liên hệ cơ quan ban hành theo Điều 5.\n\n"
        "Theo khoản 2, TCVN được áp dụng từ ngày 01/01/2025…"
    )

    result = cleaner.clean_corpus_text(raw)

    assert result.cleaned_text == raw
    assert result.deletion_spans == ()
    assert cleaner.verify_reconstruction(raw, result)


def test_repeated_matches_crlf_reconstruct_and_are_idempotent() -> None:
    cleaner = _cleaner_module()
    raw = (
        "Mở đầu\r\n\r\n"
        + VIETNAMESE_AD
        + "\r\n\t \r\n"
        + CONTACT
        + "\r\n\r\n"
        + VIETNAMESE_AD
        + "\r\n\r\nKết thúc"
    )

    result = cleaner.clean_corpus_text(raw)
    second = cleaner.clean_corpus_text(result.cleaned_text)

    assert len(result.deletion_spans) == 3
    assert result.cleaned_text == (
        "Mở đầu\r\n\r\n\r\n\t \r\n\r\n\r\n\r\n\r\nKết thúc"
    )
    assert second.cleaned_text == result.cleaned_text
    assert second.deletion_spans == ()
    assert second.raw_sha256 == result.cleaned_sha256
    assert second.cleaned_sha256 == result.cleaned_sha256
    assert cleaner.verify_reconstruction(raw, result)
    assert not cleaner.verify_reconstruction(raw + "x", result)
