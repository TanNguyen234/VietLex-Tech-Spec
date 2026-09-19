"""Stable text-preserving anchors shared by the reader and passage index."""

import re


def document_sections(content: str) -> list[dict[str, str]]:
    """Add navigable anchors without rewriting or dropping source characters."""
    headings = list(
        re.finditer(
            r"(?m)^(?:Điều\s+\d+[a-zđ]?\b|Chương\s+[IVXLCDM\d]+\b)[^\r\n]*", content
        )
    )
    sections = []
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
