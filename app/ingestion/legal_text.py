from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5


CHAPTER_RE = re.compile(
    r"^\s*(Chương\s+(?:[IVXLCDM]+|\d+))\b",
    re.IGNORECASE,
)
SECTION_RE = re.compile(
    r"^\s*((?:Mục|Tiểu mục)\s+\d+)\b",
    re.IGNORECASE,
)
ARTICLE_RE = re.compile(
    r"^\s*(Điều\s+\d+[A-Za-z]?)\b",
    re.IGNORECASE,
)
CLAUSE_RE = re.compile(r"^\s*(\d+)\.\s+", re.MULTILINE)
HEADING_RE = re.compile(
    r"^\s*(?:Chương\s+(?:[IVXLCDM]+|\d+)|"
    r"(?:Mục|Tiểu mục)\s+\d+|"
    r"Điều\s+\d+[A-Za-z]?)\b.*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class DocumentMetadata:
    document_id: int
    document_number: str
    title: str
    source_url: str
    legal_type: str
    legal_sectors: str
    issuing_authority: str
    issuance_date: str | None


@dataclass(frozen=True)
class EvidenceChunk:
    document_id: int
    document_number: str
    title: str
    source_url: str
    heading_path: str
    article: str | None
    clause: str | None
    citation: str
    text: str
    token_count: int

    def formatted_context(self) -> str:
        return (
            f"[{self.citation}]\n"
            f"Nguồn: {self.source_url}\n"
            f"Tiêu đề: {self.title}\n"
            f"{self.text}"
        )


def normalize_legal_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text or "")
    normalized = normalized.replace("\ufeff", "").replace("\u00a0", " ")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r" *\n *", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def deterministic_point_id(
    repository: str,
    revision: str,
    document_id: int,
) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"{repository}@{revision}#{document_id}",
    )


def _tokens(text: str) -> list[str]:
    return re.findall(r"\S+", text)


def _truncate_tokens(text: str, limit: int) -> str:
    return " ".join(_tokens(text)[: max(0, limit)])


def _extract_outline_normalized(text: str) -> list[str]:
    seen: set[str] = set()
    outline: list[str] = []
    for match in HEADING_RE.finditer(text):
        heading = " ".join(match.group(0).split())
        identity = heading.casefold()
        if identity not in seen:
            seen.add(identity)
            outline.append(heading)
    return outline


def extract_outline(text: str) -> list[str]:
    return _extract_outline_normalized(normalize_legal_text(text))


def _metadata_text(metadata: DocumentMetadata) -> str:
    fields = (
        f"Số văn bản: {metadata.document_number}",
        f"Tiêu đề: {metadata.title}",
        f"Loại văn bản: {metadata.legal_type}",
        f"Lĩnh vực: {metadata.legal_sectors}",
        f"Cơ quan ban hành: {metadata.issuing_authority}",
        f"Ngày ban hành: {metadata.issuance_date or 'không xác định'}",
    )
    return "\n".join(fields)


def build_dense_text(
    metadata: DocumentMetadata,
    content: str,
    *,
    max_tokens: int = 420,
    max_characters: int = 2_400,
    content_is_normalized: bool = False,
) -> str:
    normalized = (
        content
        if content_is_normalized
        else normalize_legal_text(content)
    )
    header = _metadata_text(metadata)
    outline = "\n".join(_extract_outline_normalized(normalized))
    outline_tokens = _tokens(outline)
    outline_budget = min(
        len(outline_tokens),
        max(0, max_tokens // 3),
    )
    pieces = [header]
    if outline_budget:
        pieces.append(
            "Mục lục cấu trúc:\n"
            + " ".join(outline_tokens[:outline_budget])
        )
    body_label = "Nội dung đại diện:"
    body_budget = max(
        0,
        max_tokens
        - len(_tokens("\n".join(pieces)))
        - len(_tokens(body_label)),
    )
    pieces.append(
        body_label + "\n" + _truncate_tokens(normalized, body_budget)
    )
    bounded = _truncate_tokens("\n".join(pieces), max_tokens)
    return bounded[:max_characters].rstrip()


def build_sparse_text(
    metadata: DocumentMetadata,
    content: str,
    *,
    max_terms: int = 2_048,
    content_is_normalized: bool = False,
) -> str:
    normalized = (
        content
        if content_is_normalized
        else normalize_legal_text(content)
    )
    outline = "\n".join(_extract_outline_normalized(normalized))
    combined = "\n".join(
        (
            _metadata_text(metadata),
            outline,
            normalized,
        )
    )
    return _truncate_tokens(combined, max_terms)


def _window_tokens(
    text: str,
    *,
    max_tokens: int,
    overlap_tokens: int,
) -> list[tuple[str, int]]:
    tokens = _tokens(text)
    if not tokens:
        return []
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive.")
    if overlap_tokens < 0 or overlap_tokens >= max_tokens:
        raise ValueError(
            "overlap_tokens must be non-negative and below max_tokens."
        )
    step = max_tokens - overlap_tokens
    windows: list[tuple[str, int]] = []
    for start in range(0, len(tokens), step):
        window = tokens[start : start + max_tokens]
        if not window:
            break
        windows.append((" ".join(window), len(window)))
        if start + max_tokens >= len(tokens):
            break
    return windows


def _citation(
    metadata: DocumentMetadata,
    article: str | None,
    clause: str | None,
) -> str:
    components = [
        metadata.document_number or f"ID {metadata.document_id}"
    ]
    if article:
        components.append(article)
    if clause:
        components.append(f"Khoản {clause}")
    return ", ".join(components)


def _make_chunks(
    metadata: DocumentMetadata,
    text: str,
    heading_path: str,
    article: str | None,
    clause: str | None,
    *,
    max_tokens: int,
    overlap_tokens: int,
) -> list[EvidenceChunk]:
    chunks: list[EvidenceChunk] = []
    for window, token_count in _window_tokens(
        text,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
    ):
        chunks.append(
            EvidenceChunk(
                document_id=metadata.document_id,
                document_number=metadata.document_number,
                title=metadata.title,
                source_url=metadata.source_url,
                heading_path=heading_path,
                article=article,
                clause=clause,
                citation=_citation(metadata, article, clause),
                text=window,
                token_count=token_count,
            )
        )
    return chunks


def _article_units(article_text: str) -> list[tuple[str | None, str]]:
    """Return self-contained article or clause units in source order."""
    heading, separator, body = article_text.partition("\n")
    if not separator:
        return [(None, article_text)]

    matches = list(CLAUSE_RE.finditer(body))
    if not matches:
        return [(None, article_text)]

    preamble = body[: matches[0].start()].strip()
    units: list[tuple[str | None, str]] = []
    for index, match in enumerate(matches):
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(body)
        )
        clause_text = body[match.start() : end].strip()
        pieces = [heading]
        if index == 0 and preamble:
            pieces.append(preamble)
        pieces.append(clause_text)
        units.append((match.group(1), "\n".join(pieces)))
    return units


def chunk_document(
    metadata: DocumentMetadata,
    content: str,
    *,
    max_tokens: int = 280,
    overlap_tokens: int = 24,
) -> list[EvidenceChunk]:
    normalized = normalize_legal_text(content)
    if not normalized:
        return []

    current_chapter: str | None = None
    current_section: str | None = None
    current_article: str | None = None
    article_lines: list[str] = []
    article_blocks: list[
        tuple[str, str, str]
    ] = []

    def flush_article() -> None:
        nonlocal article_lines
        if current_article and article_lines:
            ancestry = " > ".join(
                item
                for item in (
                    current_chapter,
                    current_section,
                    current_article,
                )
                if item
            )
            article_blocks.append(
                (
                    ancestry,
                    current_article,
                    "\n".join(article_lines),
                )
            )
        article_lines = []

    for line in normalized.splitlines():
        chapter_match = CHAPTER_RE.match(line)
        section_match = SECTION_RE.match(line)
        article_match = ARTICLE_RE.match(line)
        if chapter_match:
            flush_article()
            current_article = None
            current_chapter = chapter_match.group(1)
            current_section = None
            continue
        if section_match:
            flush_article()
            current_article = None
            current_section = section_match.group(1)
            continue
        if article_match:
            flush_article()
            current_article = article_match.group(1)
            article_lines = [line]
            continue
        if current_article:
            article_lines.append(line)
    flush_article()

    if article_blocks:
        chunks: list[EvidenceChunk] = []
        for heading_path, article, article_text in article_blocks:
            for clause, unit_text in _article_units(article_text):
                chunks.extend(
                    _make_chunks(
                        metadata,
                        unit_text,
                        heading_path,
                        article,
                        clause,
                        max_tokens=max_tokens,
                        overlap_tokens=overlap_tokens,
                    )
                )
        return chunks

    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", normalized)
        if paragraph.strip()
    ]
    fallback_text = "\n\n".join(paragraphs)
    return _make_chunks(
        metadata,
        fallback_text,
        "",
        None,
        None,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
    )
