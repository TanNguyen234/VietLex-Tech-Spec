"""Deterministic check of the clause number cited next to a numeric claim.

The answer model sometimes names the wrong Khoản of an Điều. When the claim
next to the citation holds numbers (for example "60 ngày") that occur in exactly
one clause of the cited Điều in the retrieved evidence, the clause number is
replaced with that clause. Ambiguous or unsupported cases are left unchanged.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any

_HEADER = re.compile(
    r"\[(?:Nguồn chính thức ngoài VietLex\s*·\s*)?(?P<doc>[^\],]+),\s*Điều\s+(?P<art>\d{1,3})(?:,\s*Khoản\s+(?P<cl>\d{1,2}))?\]",
    re.IGNORECASE,
)
_OFFICIAL_CITE = re.compile(
    r"^Dẫn chiếu:\s*(?P<doc>[^,\n]+),\s*Điều\s+(?P<art>\d{1,3})(?:,\s*Khoản\s+(?P<cl>\d{1,2}))?",
    re.IGNORECASE | re.MULTILINE,
)
_CLAUSE_MARK = re.compile(r"(?<![\w.,])(\d{1,2})\.\s+(?=\S)")
_NOT_CLAUSE_PREFIX = re.compile(
    r"(?:điều|khoản|điểm|chương|mục|nghị định|thông tư|bộ luật|luật)\s*$", re.IGNORECASE)
_CITATION = re.compile(r"Khoản\s+(\d{1,2})(\s+(?:của\s+)?Điều\s+(\d{1,3}))", re.IGNORECASE)
_NUMBER_UNIT = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:\.\d{3})+|\d{1,5}(?:[.,]\d{1,2})?)\s*"
    r"(%|(?:ngày(?:\s+làm\s+việc)?|tháng|năm(?:\s+tù)?|tỷ(?:\s*đồng)?|triệu(?:\s*đồng)?|đồng|phần\s+trăm|tuổi|điểm|giờ)(?!\w))",
    re.IGNORECASE,
)
_POINT_CITE_PREFIX = re.compile(r"(?:khoản|điều|mục|chương)\s*$", re.IGNORECASE)
_POINT_LABEL_SUFFIX = re.compile(r"^\s+[a-zđ](?:\)|\b\s*(?:khoản|điều|,|;))", re.IGNORECASE)
_BRACKETS = re.compile(r"\[[^\]]*\]")
_URL = re.compile(r"https?://\S+")
_NEXT_REFERENCE = re.compile(r"\b(?:Khoản|Điều)\s+\d", re.IGNORECASE)


def _norm_num(value: str) -> str:
    raw = str(value or "").strip()
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw):
        raw = raw.replace(".", "")
    else:
        raw = raw.replace(",", ".")
        if "." in raw:
            raw = raw.rstrip("0").rstrip(".")
    stripped = raw.lstrip("0")
    if not stripped or stripped.startswith("."):
        stripped = "0" + stripped
    return stripped or "0"


def _unit(value: str) -> str:
    text = re.sub(r"\s+", " ", value.lower().strip())
    if text.startswith("ngày"):
        return "ngày làm việc" if "làm việc" in text else "ngày"
    if text.startswith("năm"):
        return "năm tù" if "tù" in text else "năm"
    if text in {"%", "phần trăm"}:
        return "%"
    if text.startswith("triệu"):
        return "triệu"
    if text.startswith("tỷ"):
        return "tỷ"
    return text


def _fmt_decimal(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _numbers(text: str, *, include_aliases: bool = False) -> set[tuple[str, str]]:
    extracted: set[tuple[str, str]] = set()
    for match in _NUMBER_UNIT.finditer(text):
        unit = _unit(match.group(2))
        if unit == "điểm":
            if _POINT_CITE_PREFIX.search(text[max(0, match.start() - 16) : match.start()]):
                continue
            if _POINT_LABEL_SUFFIX.match(text[match.end() : match.end() + 20]):
                continue
        num = _norm_num(match.group(1))
        extracted.add((num, unit))
        if include_aliases:
            try:
                dec = Decimal(num)
            except InvalidOperation:
                dec = None
            if dec is not None:
                if unit == "đồng":
                    if dec >= Decimal(100_000) and dec % Decimal(10_000) == 0:
                        extracted.add((_fmt_decimal(dec / Decimal(1_000_000)), "triệu"))
                    if dec >= Decimal(100_000_000) and dec % Decimal(10_000_000) == 0:
                        extracted.add((_fmt_decimal(dec / Decimal(1_000_000_000)), "tỷ"))
                elif unit == "triệu":
                    dong_val = dec * Decimal(1_000_000)
                    if dong_val == dong_val.to_integral_value():
                        extracted.add((_fmt_decimal(dong_val), "đồng"))
                elif unit == "tỷ":
                    dong_val = dec * Decimal(1_000_000_000)
                    if dong_val == dong_val.to_integral_value():
                        extracted.add((_fmt_decimal(dong_val), "đồng"))
    return extracted


def _clause_starts(body: str) -> list[tuple[str, int]]:
    """Positions of numbered clauses ("1. ...") that open a sentence, inline or at line start."""
    starts: list[tuple[str, int]] = []
    for match in _CLAUSE_MARK.finditer(body):
        if _NOT_CLAUSE_PREFIX.search(body[max(0, match.start() - 24):match.start()]):
            continue
        before = body[:match.start()].rstrip(" \t")
        if before and before[-1] not in ":;.\n":
            continue
        starts.append((_norm_num(match.group(1)), match.start()))
    return starts


def _clause_index(contexts: list[str]) -> dict[tuple[str, str], dict[str, str]]:
    index: dict[tuple[str, str], dict[str, str]] = {}
    for context in contexts:
        text = context or ""
        header = _HEADER.search(text) or _OFFICIAL_CITE.search(text)
        if header is None:
            continue
        key = (header.group("doc").strip(), _norm_num(header.group("art")))
        body = text[header.end():]
        clauses = index.setdefault(key, {})
        if header.group("cl"):
            cl_num = _norm_num(header.group("cl"))
            # The evidence header already names the Khoản; the whole chunk belongs to it.
            clauses[cl_num] = clauses.get(cl_num, "") + " " + body
            continue
        starts = _clause_starts(body)
        for position, (number, start) in enumerate(starts):
            end = starts[position + 1][1] if position + 1 < len(starts) else len(body)
            clauses[number] = clauses.get(number, "") + " " + body[start:end]
    return index


_SENTENCE_END = re.compile(r"[.;](?=\s|$)")


def _first_sentence(text: str) -> str:
    match = _SENTENCE_END.search(text)
    return text[:match.end()] if match else text


def _claim_after(answer: str, position: int) -> str:
    """Rest of the citing sentence, plus the first sentence of the next paragraph."""
    tail = answer[position:position + 500]
    tail = _BRACKETS.sub(" ", tail)
    tail = _URL.sub(" ", tail)
    following = _CITATION.search(tail)
    if following:
        tail = tail[:following.start()]
    paragraphs = [part for part in re.split(r"\n\s*\n", tail)]
    own = _first_sentence(paragraphs[0]) if paragraphs else ""
    nxt_raw = next((_first_sentence(part.strip()) for part in paragraphs[1:] if part.strip()), "")
    nxt = "" if _NEXT_REFERENCE.search(nxt_raw) else nxt_raw
    return own + " " + nxt


def _claim_before(answer: str, position: int) -> str:
    """Text of the citing sentence before the citation, after any earlier clause citation."""
    head = answer[max(0, position - 300):position]
    sentence = re.split(r"[.;](?=\s|$)|\n", head)[-1]
    citations = list(_CITATION.finditer(sentence))
    return sentence[citations[-1].end():] if citations else sentence


def correct_clause_citations(answer: str, contexts: list[str]) -> tuple[str, list[dict[str, Any]]]:
    """Return the answer with unambiguous clause numbers corrected, plus the changes made."""
    if not answer or not contexts:
        return answer, []
    index = _clause_index(contexts)
    if not index:
        return answer, []
    changes: list[dict[str, Any]] = []
    pieces: list[str] = []
    last = 0
    for citation in _CITATION.finditer(answer):
        cited_clause = _norm_num(citation.group(1))
        article = _norm_num(citation.group(3))
        matching_docs = [
            (doc, clauses)
            for (doc, art), clauses in index.items()
            if art == article
        ]
        if not matching_docs:
            continue
        if len(matching_docs) > 1:
            nearby = answer[max(0, citation.start() - 120):min(len(answer), citation.end() + 180)].casefold()
            scoped_docs = [
                (doc, clauses)
                for doc, clauses in matching_docs
                if doc.casefold() in nearby
            ]
            if len(scoped_docs) != 1:
                continue
            matching_docs = scoped_docs
        candidates = matching_docs[0][1]
        if not candidates:
            continue
        claim = _claim_before(answer, citation.start()) + " " + _claim_after(answer, citation.end())
        claim_numbers = _numbers(claim)
        clause_number_sets = {
            number: _numbers(text, include_aliases=True)
            for number, text in candidates.items()
        }
        in_article = set().union(*clause_number_sets.values()) if clause_number_sets else set()
        required = claim_numbers & in_article
        if not required or required <= clause_number_sets.get(cited_clause, set()):
            continue
        matching = [number for number, c_nums in clause_number_sets.items() if required <= c_nums]
        if len(matching) != 1 or matching[0] == cited_clause:
            continue
        pieces.append(answer[last:citation.start()])
        pieces.append("Khoản " + matching[0] + citation.group(2))
        last = citation.end()
        changes.append({
            "article": article,
            "from_clause": cited_clause,
            "to_clause": matching[0],
            "numbers": sorted(f"{value} {unit}" for value, unit in required),
        })
    if not changes:
        return answer, []
    pieces.append(answer[last:])
    return "".join(pieces), changes


_DOCUMENT_ID_TOKEN = re.compile(r"\b\d{1,5}/[A-Za-z0-9À-ỹ\-]+(?:/[A-Za-z0-9À-ỹ\-]+)*")
_BRACKET_CITATION = re.compile(r"\[([^\[\]\n]{1,200})\]")


def drop_ungrounded_document_citations(answer: str, contexts: list[str]) -> tuple[str, list[str]]:
    """Remove bracketed citations whose document number never appears in the retrieved contexts.

    A citation such as ``[122/VBHN-VPQH, Điều 5]`` is not grounded when that document number was not
    retrieved; the claim stays, the unsupported reference is dropped. Title-style citations are kept.
    """
    if not answer or not contexts:
        return answer, []
    grounded = {token.casefold() for context in contexts for token in _DOCUMENT_ID_TOKEN.findall(context)}
    removed: list[str] = []

    def _check(match: re.Match[str]) -> str:
        first = match.group(1).split(",")[0].strip()
        if not _DOCUMENT_ID_TOKEN.fullmatch(first):
            return match.group(0)
        if first.casefold() in grounded:
            return match.group(0)
        removed.append(match.group(1).strip())
        return ""

    return _BRACKET_CITATION.sub(_check, answer), removed
