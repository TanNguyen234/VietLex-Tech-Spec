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
    r"^(?P<title>(?:điều|chương|mục|phần)\s+[\wIVXLCDM.-]+(?:[^\n]{0,180})?)$",
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
            try:
                xml = archive.read("word/document.xml")
            except KeyError:
                raise DocumentExtractionError("malformed_document") from None
    except DocumentExtractionError:
        raise
    except (BadZipFile, RuntimeError, OSError, ValueError):
        raise DocumentExtractionError("malformed_document") from None
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        raise DocumentExtractionError("malformed_document") from None
    paragraphs = []
    for paragraph in root.iter(f"{_WORD_NAMESPACE}p"):
        value = "".join(
            node.text or "" for node in paragraph.iter(f"{_WORD_NAMESPACE}t")
        ).strip()
        if value:
            paragraphs.append(value)
    return paragraphs


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
