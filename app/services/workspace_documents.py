from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
import re
from typing import Literal
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, ConfigDict, Field


MAX_UPLOAD_BYTES = 10_000_000
MAX_EXTRACTED_CHARACTERS = 250_000
MAX_CLAUSES = 100
MAX_PDF_PAGES = 200
MAX_DOCX_ENTRIES = 500
MAX_DOCX_UNCOMPRESSED_BYTES = 20_000_000
_WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_HEADING = re.compile(
    r"^(?P<title>(?:(?:điều|dieu)\s+\d+[\w.-]*|(?:chương|mục|phần)\s+[\wIVXLCDM.-]+)(?:[^\n]{0,180})?)$",
    re.IGNORECASE,
)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


class DocumentExtractionError(ValueError):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class WorkspaceClause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause_id: str = Field(pattern=r"^[a-f0-9]{24}-\d{3}$")
    title: str = Field(min_length=1, max_length=240)
    text: str = Field(min_length=1, max_length=12_000)
    page: int | None = Field(default=None, ge=1, le=MAX_PDF_PAGES)
    order: int = Field(ge=1, le=MAX_CLAUSES)


class ExtractedWorkspaceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    filename: str = Field(min_length=1, max_length=180)
    file_type: Literal["pdf", "docx", "txt"]
    media_type: str = Field(max_length=160)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=1, le=MAX_UPLOAD_BYTES)
    extracted_characters: int = Field(ge=1, le=MAX_EXTRACTED_CHARACTERS)
    page_count: int | None = Field(default=None, ge=1, le=MAX_PDF_PAGES)
    clauses: list[WorkspaceClause] = Field(min_length=1, max_length=MAX_CLAUSES)
    extraction_method: Literal["text", "vertex_ocr"] = "text"
    ocr_provider: str | None = Field(default=None, max_length=100)
    ocr_model: str | None = Field(default=None, max_length=200)


class ContractFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause_id: str
    risk_level: Literal["high", "medium", "review", "info"]
    issue: str = Field(min_length=1, max_length=2_000)
    legal_evidence_ids: list[str] = Field(default_factory=list, max_length=10)
    recommendation: str = Field(min_length=1, max_length=2_000)
    support_state: Literal["evidence_linked", "needs_verification"]


class ContractReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[ContractFinding] = Field(max_length=30)


def normalize_contract_review(
    result: ContractReviewResult,
    selected_clause_ids: set[str],
    selected_evidence_ids: set[str],
) -> ContractReviewResult:
    for finding in result.findings:
        if finding.clause_id not in selected_clause_ids:
            raise ValueError("invalid_clause_reference")
        if set(finding.legal_evidence_ids) - selected_evidence_ids:
            raise ValueError("invalid_evidence_reference")
        if not finding.legal_evidence_ids:
            finding.support_state = "needs_verification"
    return result


def _safe_filename(filename: str) -> str:
    value = Path(_CONTROL.sub(" ", str(filename or "document"))).name
    return " ".join(value.split())[:180] or "document"


def _clean_text(text: str) -> str:
    return "\n".join(line.strip() for line in text.replace("\r", "").split("\n")).strip()


def _split_sections(
    text: str,
    *,
    document_id: str,
    start_order: int = 1,
    page: int | None = None,
) -> list[WorkspaceClause]:
    sections: list[tuple[str, list[str]]] = []
    title = f"Trang {page}" if page else "Mở đầu"
    lines: list[str] = []
    for raw_line in _clean_text(text).splitlines():
        if match := _HEADING.fullmatch(raw_line):
            if any(lines):
                sections.append((title, lines))
            title = match.group("title")[:240]
            lines = [raw_line]
        elif raw_line or lines:
            lines.append(raw_line)
    if any(lines):
        sections.append((title, lines))

    clauses: list[WorkspaceClause] = []
    for section_title, section_lines in sections:
        value = "\n".join(section_lines).strip()
        for offset in range(0, len(value), 12_000):
            chunk = value[offset : offset + 12_000].strip()
            if not chunk:
                continue
            order = start_order + len(clauses)
            if order > MAX_CLAUSES:
                raise DocumentExtractionError("document_structure_too_large")
            suffix = f" · phần {offset // 12_000 + 1}" if offset else ""
            clauses.append(
                WorkspaceClause(
                    clause_id=f"{document_id}-{order:03d}",
                    title=(section_title + suffix)[:240],
                    text=chunk,
                    page=page,
                    order=order,
                )
            )
    return clauses


_ROMAN_PAIRS = (
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
)


def _to_roman(num: int) -> str:
    if num <= 0:
        return str(num)
    n = min(num, 3999)
    parts: list[str] = []
    for value, symbol in _ROMAN_PAIRS:
        while n >= value:
            parts.append(symbol)
            n -= value
    return "".join(parts)


def _to_alpha(num: int) -> str:
    if num <= 0:
        return str(num)
    chars: list[str] = []
    n = num
    while n > 0:
        n, rem = divmod(n - 1, 26)
        chars.append(chr(ord("a") + rem))
    return "".join(reversed(chars))


def _format_num_value(num: int, fmt: str) -> str:
    if fmt == "none":
        return ""
    if fmt == "lowerLetter":
        return _to_alpha(num)
    if fmt == "upperLetter":
        return _to_alpha(num).upper()
    if fmt == "lowerRoman":
        return _to_roman(num).lower()
    if fmt == "upperRoman":
        return _to_roman(num)
    if fmt == "bullet":
        return "-"
    return str(num)


def _safe_parse_xml(data: bytes) -> ElementTree.Element:
    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise DocumentExtractionError("malformed_document")
    try:
        return ElementTree.fromstring(data)
    except (ElementTree.ParseError, RecursionError):
        raise DocumentExtractionError("malformed_document") from None


def _safe_parse_optional_xml(data: bytes) -> ElementTree.Element | None:
    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise DocumentExtractionError("malformed_document")
    try:
        return ElementTree.fromstring(data)
    except (ElementTree.ParseError, RecursionError):
        return None


class _DocxNumberingTracker:
    def __init__(
        self,
        numbering_xml: bytes | None,
        styles_xml: bytes | None = None,
    ) -> None:
        self._abstract_levels: dict[str, dict[int, tuple[int, str, str]]] = {}
        self._num_to_abstract: dict[str, str] = {}
        self._start_overrides: dict[tuple[str, int], int] = {}
        self._style_numpr: dict[str, tuple[str, int]] = {}
        self._counters: dict[tuple[str, int], int] = {}
        w_val = f"{_WORD_NAMESPACE}val"

        if numbering_xml:
            num_root = _safe_parse_optional_xml(numbering_xml)
            if num_root is not None:
                w_abs_id = f"{_WORD_NAMESPACE}abstractNumId"
                w_ilvl = f"{_WORD_NAMESPACE}ilvl"
                w_num_id = f"{_WORD_NAMESPACE}numId"
                for abs_el in num_root.findall(f"{_WORD_NAMESPACE}abstractNum"):
                    abs_id = abs_el.get(w_abs_id)
                    if not abs_id:
                        continue
                    levels: dict[int, tuple[int, str, str]] = {}
                    for lvl_el in abs_el.findall(f"{_WORD_NAMESPACE}lvl"):
                        try:
                            ilvl = int(lvl_el.get(w_ilvl) or "0")
                        except ValueError:
                            continue
                        start_el = lvl_el.find(f"{_WORD_NAMESPACE}start")
                        fmt_el = lvl_el.find(f"{_WORD_NAMESPACE}numFmt")
                        txt_el = lvl_el.find(f"{_WORD_NAMESPACE}lvlText")
                        try:
                            start_val = int((start_el.get(w_val) if start_el is not None else "1") or "1")
                        except ValueError:
                            start_val = 1
                        num_fmt = (fmt_el.get(w_val) if fmt_el is not None else "decimal") or "decimal"
                        lvl_text = (txt_el.get(w_val) if txt_el is not None else f"%{ilvl + 1}.") or f"%{ilvl + 1}."
                        levels[ilvl] = (start_val, num_fmt, lvl_text)
                    self._abstract_levels[abs_id] = levels

                for num_el in num_root.findall(f"{_WORD_NAMESPACE}num"):
                    num_id = num_el.get(w_num_id)
                    abs_ref = num_el.find(f"{_WORD_NAMESPACE}abstractNumId")
                    if not num_id or abs_ref is None:
                        continue
                    abs_id = abs_ref.get(w_val)
                    if abs_id:
                        self._num_to_abstract[num_id] = abs_id
                    for ovr_el in num_el.findall(f"{_WORD_NAMESPACE}lvlOverride"):
                        st_ovr = ovr_el.find(f"{_WORD_NAMESPACE}startOverride")
                        if st_ovr is None:
                            continue
                        try:
                            ovr_lvl = int(ovr_el.get(w_ilvl) or "0")
                            ovr_val = int(st_ovr.get(w_val) or "1")
                            self._start_overrides[(num_id, ovr_lvl)] = ovr_val
                        except ValueError:
                            continue

        if styles_xml:
            styles_root = _safe_parse_optional_xml(styles_xml)
            if styles_root is not None:
                w_style_id = f"{_WORD_NAMESPACE}styleId"
                for st_el in styles_root.findall(f"{_WORD_NAMESPACE}style"):
                    st_id = st_el.get(w_style_id)
                    num_pr = st_el.find(f"{_WORD_NAMESPACE}pPr/{_WORD_NAMESPACE}numPr")
                    if not st_id or num_pr is None:
                        continue
                    num_id_el = num_pr.find(f"{_WORD_NAMESPACE}numId")
                    ilvl_el = num_pr.find(f"{_WORD_NAMESPACE}ilvl")
                    n_id = num_id_el.get(w_val) if num_id_el is not None else None
                    if n_id and n_id != "0":
                        try:
                            lvl = int((ilvl_el.get(w_val) if ilvl_el is not None else "0") or "0")
                        except ValueError:
                            lvl = 0
                        self._style_numpr[st_id] = (n_id, lvl)

    def next_prefix(self, paragraph: ElementTree.Element) -> str:
        w_val = f"{_WORD_NAMESPACE}val"
        p_pr = paragraph.find(f"{_WORD_NAMESPACE}pPr")
        if p_pr is None:
            return ""
        num_id: str | None = None
        ilvl = 0
        num_pr = p_pr.find(f"{_WORD_NAMESPACE}numPr")
        if num_pr is not None:
            num_id_el = num_pr.find(f"{_WORD_NAMESPACE}numId")
            ilvl_el = num_pr.find(f"{_WORD_NAMESPACE}ilvl")
            num_id = num_id_el.get(w_val) if num_id_el is not None else None
            if ilvl_el is not None:
                try:
                    ilvl = int(ilvl_el.get(w_val) or "0")
                except ValueError:
                    ilvl = 0
        else:
            p_style = p_pr.find(f"{_WORD_NAMESPACE}pStyle")
            st_id = p_style.get(w_val) if p_style is not None else None
            if st_id and st_id in self._style_numpr:
                num_id, ilvl = self._style_numpr[st_id]

        if not num_id or num_id == "0":
            return ""
        abs_id = self._num_to_abstract.get(num_id)
        if not abs_id or abs_id not in self._abstract_levels:
            return ""
        levels = self._abstract_levels[abs_id]
        start_val, num_fmt, lvl_text = levels.get(ilvl, (1, "decimal", f"%{ilvl + 1}."))
        if (num_id, ilvl) in self._start_overrides and (num_id, ilvl) not in self._counters:
            start_val = self._start_overrides[(num_id, ilvl)]

        current = self._counters.get((num_id, ilvl), start_val - 1) + 1
        self._counters[(num_id, ilvl)] = current
        for key in [k for k in self._counters if k[0] == num_id and k[1] > ilvl]:
            del self._counters[key]

        if num_fmt == "none":
            return ""
        if num_fmt == "bullet":
            return "-"

        def _replace_placeholder(match: re.Match[str]) -> str:
            ref_lvl = int(match.group(1)) - 1
            ref_start, ref_fmt, _ = levels.get(ref_lvl, (1, "decimal", ""))
            ref_val = self._counters.get((num_id, ref_lvl), ref_start)
            return _format_num_value(ref_val, ref_fmt)

        return re.sub(r"%([1-9])", _replace_placeholder, lvl_text).strip()


def _paragraph_text(paragraph: ElementTree.Element, tracker: _DocxNumberingTracker) -> str:
    pieces: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{_WORD_NAMESPACE}t" and node.text:
            pieces.append(node.text)
        elif node.tag in {f"{_WORD_NAMESPACE}tab", f"{_WORD_NAMESPACE}br"}:
            pieces.append(" ")
    value = " ".join("".join(pieces).split())
    if not value:
        return ""
    prefix = tracker.next_prefix(paragraph)
    if prefix and not value.casefold().startswith(prefix.casefold()):
        return f"{prefix} {value}"
    return value


def _read_docx_xml_entry(archive: ZipFile, name: str, remaining_budget: int) -> bytes:
    if remaining_budget <= 0:
        raise DocumentExtractionError("document_archive_too_large")
    with archive.open(name) as entry_stream:
        data = entry_stream.read(remaining_budget + 1)
    if len(data) > remaining_budget:
        raise DocumentExtractionError("document_archive_too_large")
    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise DocumentExtractionError("malformed_document")
    return data


def _extract_docx_blocks(
    element: ElementTree.Element,
    tracker: _DocxNumberingTracker,
    *,
    depth: int = 0,
) -> list[str]:
    if depth > 32:
        raise DocumentExtractionError("malformed_document")
    lines: list[str] = []
    for child in element:
        if child.tag == f"{_WORD_NAMESPACE}p":
            text = _paragraph_text(child, tracker)
            if text:
                lines.append(text)
        elif child.tag == f"{_WORD_NAMESPACE}tbl":
            for tr in child.findall(f"{_WORD_NAMESPACE}tr"):
                cells: list[str] = []
                for tc in tr.findall(f"{_WORD_NAMESPACE}tc"):
                    cell_parts: list[str] = []
                    for tc_child in tc:
                        if tc_child.tag == f"{_WORD_NAMESPACE}p":
                            p_txt = _paragraph_text(tc_child, tracker)
                            if p_txt:
                                cell_parts.append(p_txt)
                        elif tc_child.tag == f"{_WORD_NAMESPACE}tbl":
                            cell_parts.extend(_extract_docx_blocks(tc_child, tracker, depth=depth + 1))
                    cells.append(" ".join(cell_parts).replace("|", "\\|").strip())
                if any(cells):
                    lines.append("| " + " | ".join(cells) + " |")
        else:
            lines.extend(_extract_docx_blocks(child, tracker, depth=depth + 1))
    return lines


def _docx_paragraphs(payload: bytes) -> list[str]:
    try:
        with ZipFile(BytesIO(payload)) as archive:
            infos = archive.infolist()
            if (
                len(infos) > MAX_DOCX_ENTRIES
                or sum(info.file_size for info in infos)
                > MAX_DOCX_UNCOMPRESSED_BYTES
                or any(info.flag_bits & 0x1 for info in infos)
            ):
                raise DocumentExtractionError("document_archive_too_large")
            names = set(archive.namelist())
            budget = MAX_DOCX_UNCOMPRESSED_BYTES
            try:
                xml = _read_docx_xml_entry(archive, "word/document.xml", budget)
            except KeyError:
                raise DocumentExtractionError("malformed_document") from None
            budget -= len(xml)
            numbering_xml = (
                _read_docx_xml_entry(archive, "word/numbering.xml", budget)
                if "word/numbering.xml" in names
                else None
            )
            if numbering_xml is not None:
                budget -= len(numbering_xml)
            styles_xml = (
                _read_docx_xml_entry(archive, "word/styles.xml", budget)
                if "word/styles.xml" in names
                else None
            )
    except DocumentExtractionError:
        raise
    except (BadZipFile, RuntimeError, OSError, ValueError):
        raise DocumentExtractionError("malformed_document") from None
    root = _safe_parse_xml(xml)
    try:
        tracker = _DocxNumberingTracker(numbering_xml, styles_xml)
        body = root.find(f"{_WORD_NAMESPACE}body")
        if body is not None:
            return _extract_docx_blocks(body, tracker)
        return _extract_docx_blocks(root, tracker)
    except RecursionError:
        raise DocumentExtractionError("malformed_document") from None


def _pdf_reader(payload: bytes):
    from pypdf import PdfReader

    return PdfReader(BytesIO(payload), strict=True)


def _extract_pdf(payload: bytes, document_id: str) -> tuple[list[WorkspaceClause], int]:
    try:
        reader = _pdf_reader(payload)
        if reader.is_encrypted:
            raise DocumentExtractionError("encrypted_document")
        if not reader.pages or len(reader.pages) > MAX_PDF_PAGES:
            raise DocumentExtractionError("document_structure_too_large")
        clauses: list[WorkspaceClause] = []
        extracted_characters = 0
        for page_number, page in enumerate(reader.pages, 1):
            page_text = page.extract_text() or ""
            extracted_characters += len(page_text)
            if extracted_characters > MAX_EXTRACTED_CHARACTERS:
                raise DocumentExtractionError("document_text_too_large")
            clauses.extend(
                _split_sections(
                    page_text,
                    document_id=document_id,
                    start_order=len(clauses) + 1,
                    page=page_number,
                )
            )
        return clauses, len(reader.pages)
    except DocumentExtractionError:
        raise
    except Exception:
        raise DocumentExtractionError("malformed_document") from None


def extract_workspace_document(
    filename: str,
    content_type: str,
    payload: bytes,
) -> ExtractedWorkspaceDocument:
    if not payload:
        raise DocumentExtractionError("empty_document")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise DocumentExtractionError("document_too_large")
    safe_name = _safe_filename(filename)
    extension = Path(safe_name).suffix.casefold()
    file_type = {".pdf": "pdf", ".docx": "docx", ".txt": "txt"}.get(extension)
    if file_type is None:
        raise DocumentExtractionError("unsupported_document_type")
    if file_type == "pdf" and not payload.startswith(b"%PDF-"):
        raise DocumentExtractionError("document_signature_mismatch")
    if file_type == "docx" and not payload.startswith(b"PK"):
        raise DocumentExtractionError("document_signature_mismatch")
    allowed_media_types = {
        "pdf": {"application/pdf", "application/octet-stream", ""},
        "docx": {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/octet-stream",
            "",
        },
        "txt": {"text/plain", "application/octet-stream", ""},
    }
    normalized_media_type = content_type.partition(";")[0].strip().casefold()
    if normalized_media_type not in allowed_media_types[file_type]:
        raise DocumentExtractionError("document_type_mismatch")

    digest = hashlib.sha256(payload).hexdigest()
    document_id = digest[:24]
    page_count = None
    if file_type == "pdf":
        clauses, page_count = _extract_pdf(payload, document_id)
    else:
        try:
            text = (
                "\n".join(_docx_paragraphs(payload))
                if file_type == "docx"
                else payload.decode("utf-8-sig")
            )
        except UnicodeDecodeError:
            raise DocumentExtractionError("unsupported_text_encoding") from None
        if len(text) > MAX_EXTRACTED_CHARACTERS:
            raise DocumentExtractionError("document_text_too_large")
        clauses = _split_sections(text, document_id=document_id)
    extracted_characters = sum(len(item.text) for item in clauses)
    if not clauses or extracted_characters == 0:
        raise DocumentExtractionError("empty_document")
    if extracted_characters > MAX_EXTRACTED_CHARACTERS:
        raise DocumentExtractionError("document_text_too_large")
    return ExtractedWorkspaceDocument(
        document_id=document_id,
        filename=safe_name,
        file_type=file_type,
        media_type=str(content_type or "application/octet-stream")[:160],
        sha256=digest,
        size_bytes=len(payload),
        extracted_characters=extracted_characters,
        page_count=page_count,
        clauses=clauses,
    )
