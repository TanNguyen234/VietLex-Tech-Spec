from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


_DOCUMENT_NUMBER = re.compile(r"\b\d{1,4}/\d{4}/[A-ZĐ0-9-]+\b", re.IGNORECASE)


@dataclass(frozen=True)
class EvidenceView:
    original: str
    citation: str | None
    document_number: str | None
    title: str | None
    source_url: str | None
    excerpt: str


def _safe_url(value: str) -> str | None:
    parsed = urlparse(value.strip())
    return value.strip() if parsed.scheme in {"http", "https"} and parsed.netloc else None


def present_context(text: str) -> EvidenceView:
    original = str(text)
    lines = original.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    citation: str | None = None
    title: str | None = None
    source_url: str | None = None
    excerpt_lines: list[str] = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if citation is None and line.startswith("[") and line.endswith("]"):
            citation = line[1:-1].strip() or None
            continue
        if line.casefold().startswith("dẫn chiếu:"):
            citation = line.split(":", 1)[1].strip() or citation
            continue
        if line.casefold().startswith("nguồn:"):
            source_url = _safe_url(line.split(":", 1)[1])
            continue
        if line.casefold().startswith("url:"):
            source_url = _safe_url(line.split(":", 1)[1])
            continue
        if line.casefold().startswith("tiêu đề:"):
            title = line.split(":", 1)[1].strip() or None
            continue
        excerpt_lines.append(raw_line.strip())

    document_match = _DOCUMENT_NUMBER.search(citation or original)
    return EvidenceView(
        original=original,
        citation=citation,
        document_number=(document_match.group().upper() if document_match else None),
        title=title,
        source_url=source_url,
        excerpt="\n".join(excerpt_lines).strip(),
    )
