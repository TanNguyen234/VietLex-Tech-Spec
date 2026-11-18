"""Stable text-preserving anchors shared by the reader and passage index."""
from __future__ import annotations

import re
from typing import Any

SECTION_WINDOW_MAX = 4000
SECTION_WINDOW_STEP = 3500

_BASE_HEADING_RE = re.compile(
    r"(?m)^(?:Điều\s+\d+[a-zđ]?\b|Chương\s+[IVXLCDM\d]+\b)[^\r\n]*"
)
_SUB_HEADING_RE = re.compile(
    r"(?m)^(?:Phần\s+(?:thứ\s+[^\r\n.:;]{1,30}|[IVXLCDM\d]+)\b"
    r"|Mục\s+[IVXLCDM\d]+\b"
    r"|Tiểu\s+mục\s+[IVXLCDM\d]+\b"
    r"|Phụ\s+lục(?:\s+[IVXLCDM\dA-Z]+)?\b)[^\r\n]*",
    re.IGNORECASE,
)


def document_sections(content: str) -> list[dict[str, str]]:
    """Add navigable anchors without rewriting or dropping source characters."""
    headings = list(_BASE_HEADING_RE.finditer(content))
    sections: list[dict[str, str]] = []
    start = 0
    for index, heading in enumerate(headings):
        if index == 0 and heading.start():
            sections.append(
                {
                    "id": "preamble",
                    "title": "Mở đầu",
                    "text": content[: heading.start()],
                }
            )
        start = heading.start()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(content)
        sections.append(
            {
                "id": f"section-{index + 1}",
                "title": heading.group()[:180],
                "text": content[start:end],
            }
        )
    return sections or [{"id": "full-text", "title": "Toàn văn", "text": content}]


def classify_section_heading(section_id: str, title: str) -> tuple[str, int]:
    if section_id == "preamble":
        return "preamble", 1
    if section_id == "full-text":
        return "body", 1
    lowered = (title or "").strip().casefold()
    if lowered.startswith("phần "):
        return "part", 1
    if lowered.startswith("chương "):
        return "chapter", 2
    if lowered.startswith("mục "):
        return "subpart", 3
    if lowered.startswith("tiểu mục "):
        return "subsection", 4
    if lowered.startswith("phụ lục"):
        return "annex", 1
    return "article", 5


def section_pin_windows(text: str) -> list[dict[str, Any]]:
    if len(text) <= SECTION_WINDOW_MAX:
        return []
    windows: list[dict[str, Any]] = []
    start = 0
    index = 1
    while start < len(text):
        end = min(len(text), start + SECTION_WINDOW_MAX)
        windows.append(
            {
                "index": index,
                "start": start,
                "end": end,
                "label": f"Đoạn {index} (ký tự {start + 1}–{end})",
            }
        )
        if end >= len(text):
            break
        start += SECTION_WINDOW_STEP
        index += 1
    return windows


def reader_sections(content: str) -> list[dict[str, Any]]:
    """Enrich sections with Phần/Mục/Tiểu mục/Phụ lục sub-anchors without shifting section-{i} IDs."""
    enriched: list[dict[str, Any]] = []
    for item in document_sections(content):
        base_id = item["id"]
        base_title = item["title"]
        base_text = item["text"]
        sub_matches = [
            m for m in _SUB_HEADING_RE.finditer(base_text) if m.start() > 0 or base_id in {"preamble", "full-text"}
        ]
        if not sub_matches:
            kind, level = classify_section_heading(base_id, base_title)
            enriched.append(
                {
                    **item,
                    "kind": kind,
                    "level": level,
                    "windows": section_pin_windows(base_text),
                }
            )
            continue

        pieces: list[tuple[str, str, str]] = []
        if sub_matches[0].start() > 0:
            pieces.append((base_id, base_title, base_text[: sub_matches[0].start()]))
        for idx, match in enumerate(sub_matches):
            seg_start = match.start()
            seg_end = sub_matches[idx + 1].start() if idx + 1 < len(sub_matches) else len(base_text)
            sub_id = base_id if (seg_start == 0 and not pieces) else f"{base_id}-sub-{idx + 1}"
            pieces.append((sub_id, match.group().strip()[:180], base_text[seg_start:seg_end]))

        for sub_id, sub_title, sub_text in pieces:
            kind, level = classify_section_heading(sub_id, sub_title)
            enriched.append(
                {
                    "id": sub_id,
                    "title": sub_title,
                    "text": sub_text,
                    "kind": kind,
                    "level": level,
                    "windows": section_pin_windows(sub_text),
                }
            )
    return enriched
