"""Bounded, provider-free textual redline for server-extracted documents.

This module reports text and source-record differences only.  It intentionally
does not infer legal meaning, effect, validity, or conflict.
"""

from __future__ import annotations

from collections import defaultdict, deque
from difflib import SequenceMatcher
from typing import Any, Mapping


SCHEMA_VERSION = "document-redline-v1"
MAX_CLAUSES = 100
MAX_DOCUMENT_CHARACTERS = 250_000
# A char-level SequenceMatcher can be quadratic.  Larger differing windows are
# represented by their exact common-prefix/common-suffix bounded coarse span.
MAX_DETAILED_DIFF_WINDOW_CHARACTERS = 8_192
MAX_DETAILED_DIFF_OPCODES = 128


def compare_documents(document_a: dict, document_b: dict) -> dict:
    """Compare two extracted documents without semantic or legal conclusions.

    Documents must be mappings with a distinct non-empty ``document_id`` and a
    ``clauses`` list. Each clause requires a distinct non-empty ``clause_id``
    and string ``text``; ``title`` and ``page`` are retained when supplied.
    """

    left = _validate_document(document_a, "document_a")
    right = _validate_document(document_b, "document_b")
    if left["document_id"] == right["document_id"]:
        raise ValueError("document_a and document_b must have different document ids")

    pairs = _match_clauses(left["clauses"], right["clauses"])
    same: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    paired_left = set()
    paired_right = set()

    for left_index, right_index in pairs:
        before = left["clauses"][left_index]
        after = right["clauses"][right_index]
        paired_left.add(left_index)
        paired_right.add(right_index)
        if before["text"] == after["text"]:
            same.append(
                {
                    "before": _source(before),
                    "after": _source(after),
                    "before_quote": _span(before["text"], 0, len(before["text"])),
                    "after_quote": _span(after["text"], 0, len(after["text"])),
                }
            )
            continue
        comparison_mode, changes = _text_changes(before["text"], after["text"])
        changed.append(
            {
                "before": _source(before),
                "after": _source(after),
                "comparison_mode": comparison_mode,
                "changes": changes,
            }
        )

    removed = [
        {
            "before": _source(clause),
            "before_quote": _span(clause["text"], 0, len(clause["text"])),
        }
        for index, clause in enumerate(left["clauses"])
        if index not in paired_left
    ]
    added = [
        {
            "after": _source(clause),
            "after_quote": _span(clause["text"], 0, len(clause["text"])),
        }
        for index, clause in enumerate(right["clauses"])
        if index not in paired_right
    ]
    covered_clauses = 2 * (len(same) + len(changed)) + len(added) + len(removed)

    return {
        "schema_version": SCHEMA_VERSION,
        "document_a_id": left["document_id"],
        "document_b_id": right["document_id"],
        "legal_conclusion": "not_evaluated",
        "added": added,
        "removed": removed,
        "changed": changed,
        "same": same,
        "coverage": {
            "documents": _coverage(2, 2),
            "clauses": _coverage(
                covered_clauses, len(left["clauses"]) + len(right["clauses"])
            ),
        },
    }


def _validate_document(document: object, label: str) -> dict[str, Any]:
    if not isinstance(document, Mapping):
        raise ValueError(f"{label} must be a mapping")
    document_id = document.get("document_id")
    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError(f"{label}.document_id must be a non-empty string")
    raw_clauses = document.get("clauses")
    if not isinstance(raw_clauses, list):
        raise ValueError(f"{label}.clauses must be a list")
    if len(raw_clauses) > MAX_CLAUSES:
        raise ValueError(f"{label} must contain at most 100 clauses")

    clauses: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    total_characters = 0
    for index, raw_clause in enumerate(raw_clauses):
        if not isinstance(raw_clause, Mapping):
            raise ValueError(f"{label}.clauses[{index}] must be a mapping")
        clause_id = raw_clause.get("clause_id")
        text = raw_clause.get("text")
        title = raw_clause.get("title")
        page = raw_clause.get("page")
        order = raw_clause.get("order")
        if not isinstance(clause_id, str) or not clause_id.strip():
            raise ValueError(
                f"{label}.clauses[{index}].clause_id must be a non-empty string"
            )
        if clause_id in seen_ids:
            raise ValueError(f"{label} contains duplicate clause_id: {clause_id}")
        if not isinstance(text, str):
            raise ValueError(f"{label}.clauses[{index}].text must be a string")
        if title is not None and not isinstance(title, str):
            raise ValueError(
                f"{label}.clauses[{index}].title must be a string when supplied"
            )
        if page is not None and not isinstance(page, (int, str)):
            raise ValueError(
                f"{label}.clauses[{index}].page must be an int or string when supplied"
            )
        if order is not None and (not isinstance(order, int) or order < 1):
            raise ValueError(
                f"{label}.clauses[{index}].order must be a positive int when supplied"
            )
        seen_ids.add(clause_id)
        total_characters += len(text)
        if total_characters > MAX_DOCUMENT_CHARACTERS:
            raise ValueError(f"{label} must contain at most 250000 characters")
        clauses.append(
            {
                "clause_id": clause_id,
                "text": text,
                "title": title,
                "page": page,
                "order": order,
            }
        )
    return {"document_id": document_id, "clauses": clauses}


def _match_clauses(
    left: list[dict[str, Any]], right: list[dict[str, Any]]
) -> list[tuple[int, int]]:
    """Pair exact text first, then same normalized titles, in stable order."""

    right_by_text: dict[str, deque[int]] = defaultdict(deque)
    for right_index, clause in enumerate(right):
        right_by_text[clause["text"]].append(right_index)

    pairs: list[tuple[int, int]] = []
    paired_right: set[int] = set()
    unmatched_left: list[int] = []
    for left_index, clause in enumerate(left):
        candidates = right_by_text[clause["text"]]
        while candidates and candidates[0] in paired_right:
            candidates.popleft()
        if candidates:
            right_index = candidates.popleft()
            paired_right.add(right_index)
            pairs.append((left_index, right_index))
        else:
            unmatched_left.append(left_index)

    right_by_clause_id = {
        clause["clause_id"]: right_index
        for right_index, clause in enumerate(right)
        if right_index not in paired_right
    }
    remaining_left: list[int] = []
    for left_index in unmatched_left:
        right_index = right_by_clause_id.get(left[left_index]["clause_id"])
        if right_index is None:
            remaining_left.append(left_index)
            continue
        paired_right.add(right_index)
        pairs.append((left_index, right_index))

    right_by_title: dict[str, deque[int]] = defaultdict(deque)
    for right_index, clause in enumerate(right):
        if right_index not in paired_right:
            key = _title_key(clause["title"])
            if key:
                right_by_title[key].append(right_index)
    for left_index in remaining_left:
        key = _title_key(left[left_index]["title"])
        candidates = right_by_title[key] if key else deque()
        if candidates:
            right_index = candidates.popleft()
            paired_right.add(right_index)
            pairs.append((left_index, right_index))

    return sorted(pairs)


def _title_key(title: str | None) -> str:
    return " ".join((title or "").casefold().split())


def _text_changes(before: str, after: str) -> tuple[str, list[dict[str, Any]]]:
    prefix = _common_prefix_length(before, after)
    suffix = _common_suffix_length(before, after, prefix)
    before_end = len(before) - suffix
    after_end = len(after) - suffix
    before_window = before[prefix:before_end]
    after_window = after[prefix:after_end]

    if len(before_window) + len(after_window) > MAX_DETAILED_DIFF_WINDOW_CHARACTERS:
        return "bounded_coarse_span", [
            _change("replace", before, prefix, before_end, after, prefix, after_end)
        ]

    matcher = SequenceMatcher(None, before_window, after_window, autojunk=True)
    opcodes = [opcode for opcode in matcher.get_opcodes() if opcode[0] != "equal"]
    if len(opcodes) > MAX_DETAILED_DIFF_OPCODES:
        return "bounded_coarse_span", [
            _change("replace", before, prefix, before_end, after, prefix, after_end)
        ]
    return "detailed", [
        _change(
            kind,
            before,
            prefix + start_before,
            prefix + end_before,
            after,
            prefix + start_after,
            prefix + end_after,
        )
        for kind, start_before, end_before, start_after, end_after in opcodes
    ]


def _common_prefix_length(before: str, after: str) -> int:
    limit = min(len(before), len(after))
    index = 0
    while index < limit and before[index] == after[index]:
        index += 1
    return index


def _common_suffix_length(before: str, after: str, prefix: int) -> int:
    limit = min(len(before), len(after)) - prefix
    index = 0
    while index < limit and before[-(index + 1)] == after[-(index + 1)]:
        index += 1
    return index


def _change(
    kind: str,
    before: str,
    before_start: int,
    before_end: int,
    after: str,
    after_start: int,
    after_end: int,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "before": _span(before, before_start, before_end),
        "after": _span(after, after_start, after_end),
    }


def _span(text: str, start: int, end: int) -> dict[str, Any]:
    return {"start": start, "end": end, "quote": text[start:end]}


def _source(clause: Mapping[str, Any]) -> dict[str, Any]:
    source = {"clause_id": clause["clause_id"]}
    if clause["title"] is not None:
        source["title"] = clause["title"]
    if clause["page"] is not None:
        source["page"] = clause["page"]
    if clause["order"] is not None:
        source["order"] = clause["order"]
    return source


def _coverage(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "omitted": denominator - numerator,
        "omitted_reasons": [],
    }
