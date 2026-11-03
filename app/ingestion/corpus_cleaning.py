"""Pure, conservative removal of confirmed TVPL Pro ad paragraphs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


VIETNAMESE_AD = (
    "Bạn phải đăng nhập hoặc đăng ký Thành Viên TVPL Pro để sử dụng được "
    "đầy đủ các tiện ích gia tăng liên quan đến nội dung TCVN."
)
ENGLISH_AD = (
    "Please sign up or sign in to your TVPL Pro Membership to see English "
    "documents."
)
CONTACT = "Mọi chi tiết xin liên hệ: ĐT: (028) 3930 3279 DĐ: 0906 22 99 66"

VIETNAMESE_AD_RULE = "tvpl_pro_vietnamese_tcvn_ad"
ENGLISH_AD_RULE = "tvpl_pro_english_documents_ad"
ADJACENT_CONTACT_RULE = "tvpl_contact_adjacent_to_vietnamese_ad"


@dataclass(frozen=True)
class DeletionSpan:
    """Half-open UTF-8 byte offsets into the original text."""

    start_byte: int
    end_byte: int
    rule_id: str
    removed_text: str


@dataclass(frozen=True)
class CorpusCleaningResult:
    cleaned_text: str
    deletion_spans: tuple[DeletionSpan, ...]
    raw_sha256: str
    cleaned_sha256: str


@dataclass(frozen=True)
class _Paragraph:
    text: str | None
    start_byte: int
    end_byte: int


def _paragraphs(text: str) -> list[_Paragraph]:
    paragraphs: list[_Paragraph] = []
    current: list[tuple[str, int, int]] = []
    byte_offset = 0
    char_offset = 0

    while char_offset < len(text):
        line_end = char_offset
        while line_end < len(text) and text[line_end] not in "\r\n":
            line_end += 1
        ending_end = line_end + (
            2 if text.startswith("\r\n", line_end) else int(line_end < len(text))
        )
        content = text[char_offset:line_end]

        content_bytes = len(content.encode("utf-8"))
        if content.strip():
            current.append((content, byte_offset, byte_offset + content_bytes))
        elif current:
            paragraphs.append(
                _Paragraph(
                    current[0][0] if len(current) == 1 else None,
                    current[0][1],
                    current[-1][2],
                )
            )
            current.clear()

        byte_offset += len(text[char_offset:ending_end].encode("utf-8"))
        char_offset = ending_end

    if current:
        paragraphs.append(
            _Paragraph(
                current[0][0] if len(current) == 1 else None,
                current[0][1],
                current[-1][2],
            )
        )
    return paragraphs


def _deletion_spans(text: str) -> tuple[DeletionSpan, ...]:
    paragraphs = _paragraphs(text)
    spans: list[DeletionSpan] = []

    for index, paragraph in enumerate(paragraphs):
        if paragraph.text == VIETNAMESE_AD:
            spans.append(
                DeletionSpan(
                    paragraph.start_byte,
                    paragraph.end_byte,
                    VIETNAMESE_AD_RULE,
                    VIETNAMESE_AD,
                )
            )
        elif paragraph.text == ENGLISH_AD:
            spans.append(
                DeletionSpan(
                    paragraph.start_byte,
                    paragraph.end_byte,
                    ENGLISH_AD_RULE,
                    ENGLISH_AD,
                )
            )
        elif paragraph.text == CONTACT and (
            (index > 0 and paragraphs[index - 1].text == VIETNAMESE_AD)
            or (
                index + 1 < len(paragraphs)
                and paragraphs[index + 1].text == VIETNAMESE_AD
            )
        ):
            spans.append(
                DeletionSpan(
                    paragraph.start_byte,
                    paragraph.end_byte,
                    ADJACENT_CONTACT_RULE,
                    CONTACT,
                )
            )

    return tuple(sorted(spans, key=lambda span: span.start_byte))


def clean_corpus_text(raw_text: str) -> CorpusCleaningResult:
    """Remove only exact confirmed ad paragraphs; preserve every other byte."""
    raw_bytes = raw_text.encode("utf-8")
    spans = _deletion_spans(raw_text)
    kept: list[bytes] = []
    cursor = 0
    for span in spans:
        kept.append(raw_bytes[cursor : span.start_byte])
        cursor = span.end_byte
    kept.append(raw_bytes[cursor:])
    cleaned_bytes = b"".join(kept)

    return CorpusCleaningResult(
        cleaned_text=cleaned_bytes.decode("utf-8"),
        deletion_spans=spans,
        raw_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        cleaned_sha256=hashlib.sha256(cleaned_bytes).hexdigest(),
    )


def verify_reconstruction(raw_text: str, result: CorpusCleaningResult) -> bool:
    """Check policy spans, hashes, and exact reconstruction from the source."""
    try:
        raw_bytes = raw_text.encode("utf-8")
        if result.raw_sha256 != hashlib.sha256(raw_bytes).hexdigest():
            return False
        if result.deletion_spans != _deletion_spans(raw_text):
            return False

        kept: list[bytes] = []
        cursor = 0
        for span in result.deletion_spans:
            if (
                span.start_byte < cursor
                or span.end_byte < span.start_byte
                or span.end_byte > len(raw_bytes)
            ):
                return False
            kept.append(raw_bytes[cursor : span.start_byte])
            cursor = span.end_byte
        kept.append(raw_bytes[cursor:])
        cleaned_bytes = b"".join(kept)
        return (
            cleaned_bytes.decode("utf-8") == result.cleaned_text
            and hashlib.sha256(cleaned_bytes).hexdigest()
            == result.cleaned_sha256
        )
    except (AttributeError, TypeError, UnicodeDecodeError, UnicodeEncodeError):
        return False
