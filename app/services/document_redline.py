"""Bounded, provider-free textual redline for server-extracted documents.

This module reports text and source-record differences only.  It intentionally
does not infer legal meaning, effect, validity, or conflict.
"""

from __future__ import annotations

from collections import defaultdict, deque
from difflib import SequenceMatcher
import re
from typing import Any, Mapping


SCHEMA_VERSION = "document-redline-v1"
MAX_CLAUSES = 100
MAX_DOCUMENT_CHARACTERS = 250_000
# A char-level SequenceMatcher can be quadratic.  Larger differing windows are
# represented by their exact common-prefix/common-suffix bounded coarse span.
MAX_DETAILED_DIFF_WINDOW_CHARACTERS = 8_192
MAX_DETAILED_DIFF_OPCODES = 128
MAX_INLINE_DIFF_TOKENS = 600
_STRUCTURAL_ID_RE = re.compile(
    r"^\s*(?P<kind>điều|dieu|khoản|khoan|mục|muc|phụ\s+lục|phu\s+luc)\s+"
    r"(?P<num>[IVXLCDM\d]+[a-zđ]?(?:\.\d+)*)\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_INLINE_TOKEN_RE = re.compile(r"\S+|\s+")


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
        changed_entry: dict[str, Any] = {
            "before": _source(before),
            "after": _source(after),
            "comparison_mode": comparison_mode,
            "changes": changes,
        }
        if comparison_mode == "detailed":
            changed_entry["inline_tokens"] = _inline_word_tokens(
                before["text"], after["text"]
            )
        changed.append(changed_entry)

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
    still_unmatched_left: list[int] = []
    for left_index in remaining_left:
        key = _title_key(left[left_index]["title"])
        candidates = right_by_title[key] if key else deque()
        while candidates and candidates[0] in paired_right:
            candidates.popleft()
        if candidates:
            right_index = candidates.popleft()
            paired_right.add(right_index)
            pairs.append((left_index, right_index))
        else:
            still_unmatched_left.append(left_index)

    # Pass 4a: leading structural identifier (Điều <N>, Khoản <N>, Mục <N>, Phụ lục <N>)
    right_by_struct: dict[str, deque[int]] = defaultdict(deque)
    for right_index, clause in enumerate(right):
        if right_index not in paired_right:
            struct_key = _structural_key(clause)
            if struct_key:
                right_by_struct[struct_key].append(right_index)

    jaccard_left: list[int] = []
    for left_index in still_unmatched_left:
        struct_key = _structural_key(left[left_index])
        candidates = right_by_struct[struct_key] if struct_key else deque()
        while candidates and candidates[0] in paired_right:
            candidates.popleft()
        if candidates:
            right_index = candidates.popleft()
            paired_right.add(right_index)
            pairs.append((left_index, right_index))
        else:
            jaccard_left.append(left_index)

    # Pass 4b: normalized word-token Jaccard similarity >= 0.45
    unmatched_right = [
        idx for idx in range(len(right)) if idx not in paired_right
    ]
    if jaccard_left and unmatched_right:
        left_tokens = {idx: _clause_word_set(left[idx]) for idx in jaccard_left}
        right_tokens = {idx: _clause_word_set(right[idx]) for idx in unmatched_right}
        scored_candidates: list[tuple[float, int, int]] = []
        for l_idx in jaccard_left:
            l_words = left_tokens[l_idx]
            len_l = len(l_words)
            if not len_l:
                continue
            for r_idx in unmatched_right:
                r_words = right_tokens[r_idx]
                len_r = len(r_words)
                if not len_r:
                    continue
                if min(len_l, len_r) < 0.45 * max(len_l, len_r):
                    continue
                inter = len(l_words & r_words)
                union_len = len_l + len_r - inter
                if union_len <= 0:
                    continue
                score = inter / union_len
                if score >= 0.45:
                    scored_candidates.append((score, -l_idx, -r_idx))
        scored_candidates.sort(reverse=True)
        paired_left_p4: set[int] = set()
        for _score, neg_l, neg_r in scored_candidates:
            l_idx, r_idx = -neg_l, -neg_r
            if l_idx in paired_left_p4 or r_idx in paired_right:
                continue
            paired_left_p4.add(l_idx)
            paired_right.add(r_idx)
            pairs.append((l_idx, r_idx))

    return sorted(pairs)


def _structural_key(clause: Mapping[str, Any]) -> str:
    for raw in (clause.get("title"), (clause.get("text") or "").splitlines()[0] if clause.get("text") else None):
        if not raw:
            continue
        match = _STRUCTURAL_ID_RE.match(raw)
        if match:
            raw_kind = re.sub(r"\s+", " ", match.group("kind").casefold())
            norm_kind = {
                "điều": "dieu",
                "dieu": "dieu",
                "khoản": "khoan",
                "khoan": "khoan",
                "mục": "muc",
                "muc": "muc",
                "phụ lục": "phu_luc",
                "phu luc": "phu_luc",
            }.get(raw_kind, raw_kind)
            return f"{norm_kind}:{match.group('num').casefold()}"
    return ""


def _clause_word_set(clause: Mapping[str, Any]) -> set[str]:
    combined = f"{clause.get('title') or ''} {clause.get('text') or ''}".casefold()
    return set(_WORD_RE.findall(combined))


def _inline_word_tokens(before: str, after: str) -> list[dict[str, str]]:
    before_tokens = _INLINE_TOKEN_RE.findall(before)
    after_tokens = _INLINE_TOKEN_RE.findall(after)
    prefix_len = 0
    min_len = min(len(before_tokens), len(after_tokens))
    while prefix_len < min_len and before_tokens[prefix_len] == after_tokens[prefix_len]:
        prefix_len += 1
    suffix_len = 0
    rem_min = min_len - prefix_len
    while (
        suffix_len < rem_min
        and before_tokens[len(before_tokens) - 1 - suffix_len]
        == after_tokens[len(after_tokens) - 1 - suffix_len]
    ):
        suffix_len += 1

    b_end = len(before_tokens) - suffix_len
    a_end = len(after_tokens) - suffix_len
    b_mid = before_tokens[prefix_len:b_end]
    a_mid = after_tokens[prefix_len:a_end]

    segments: list[dict[str, str]] = []

    def _push(kind: str, text: str) -> None:
        if not text:
            return
        if segments and segments[-1]["kind"] == kind:
            segments[-1]["text"] += text
        else:
            segments.append({"kind": kind, "text": text})

    if prefix_len:
        _push("equal", "".join(before_tokens[:prefix_len]))

    if len(b_mid) + len(a_mid) > MAX_INLINE_DIFF_TOKENS * 2:
        _push("delete", "".join(b_mid))
        _push("insert", "".join(a_mid))
    else:
        matcher = SequenceMatcher(None, b_mid, a_mid, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                _push("equal", "".join(b_mid[i1:i2]))
            elif tag == "delete":
                _push("delete", "".join(b_mid[i1:i2]))
            elif tag == "insert":
                _push("insert", "".join(a_mid[j1:j2]))
            elif tag == "replace":
                _push("delete", "".join(b_mid[i1:i2]))
                _push("insert", "".join(a_mid[j1:j2]))

    if suffix_len:
        _push("equal", "".join(before_tokens[b_end:]))
    return segments


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
