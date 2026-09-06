from io import BytesIO
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

import pytest


def _docx(*paragraphs: str) -> bytes:
    body = "".join(
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", xml)
    return output.getvalue()


def test_txt_and_docx_extract_bounded_clause_records() -> None:
    from app.services.workspace_documents import extract_workspace_document

    txt = extract_workspace_document(
        "hop-dong.txt",
        "text/plain",
        "ĐIỀU 1. Phạm vi\nBên A cung cấp dịch vụ.\nĐIỀU 2. Thanh toán\n30 ngày.".encode(),
    )
    docx = extract_workspace_document(
        "hop-dong.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        _docx("ĐIỀU 1. Phạm vi", "Bên A cung cấp dịch vụ.", "ĐIỀU 2. Thanh toán", "30 ngày."),
    )

    assert [item.title for item in txt.clauses] == ["ĐIỀU 1. Phạm vi", "ĐIỀU 2. Thanh toán"]
    assert [item.text for item in docx.clauses] == [item.text for item in txt.clauses]
    assert txt.sha256 != docx.sha256
    assert txt.extracted_characters > 0


@pytest.mark.parametrize(
    ("name", "content_type", "payload", "kind"),
    [
        ("bad.exe", "application/octet-stream", b"MZ", "unsupported_document_type"),
        ("fake.pdf", "application/pdf", b"not a pdf", "document_signature_mismatch"),
        ("empty.txt", "text/plain", b" \n ", "empty_document"),
    ],
)
def test_document_extraction_rejects_unsafe_or_empty_inputs(
    name, content_type, payload, kind
) -> None:
    from app.services.workspace_documents import DocumentExtractionError, extract_workspace_document

    with pytest.raises(DocumentExtractionError, match=kind):
        extract_workspace_document(name, content_type, payload)


def test_pdf_pages_keep_page_provenance(monkeypatch) -> None:
    from app.services import workspace_documents

    pages = [SimpleNamespace(extract_text=lambda: "Điều 1. Nội dung trang một."), SimpleNamespace(extract_text=lambda: "Điều 2. Nội dung trang hai.")]
    reader = SimpleNamespace(is_encrypted=False, pages=pages)
    monkeypatch.setattr(workspace_documents, "_pdf_reader", lambda _: reader)

    result = workspace_documents.extract_workspace_document(
        "contract.pdf", "application/pdf", b"%PDF-1.7 fixture"
    )

    assert [clause.page for clause in result.clauses] == [1, 2]
    assert result.clauses[1].title.startswith("Điều 2")


def test_encrypted_pdf_and_oversized_docx_archive_are_rejected(monkeypatch) -> None:
    from pypdf import PdfWriter
    from app.services import workspace_documents

    pdf = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret")
    writer.write(pdf)
    with pytest.raises(
        workspace_documents.DocumentExtractionError, match="encrypted_document"
    ):
        workspace_documents.extract_workspace_document(
            "secret.pdf", "application/pdf", pdf.getvalue()
        )

    monkeypatch.setattr(workspace_documents, "MAX_DOCX_UNCOMPRESSED_BYTES", 10)
    with pytest.raises(
        workspace_documents.DocumentExtractionError,
        match="document_archive_too_large",
    ):
        workspace_documents.extract_workspace_document(
            "large.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            _docx("Điều 1. Nội dung dài"),
        )


def test_declared_media_type_must_match_extension() -> None:
    from app.services.workspace_documents import (
        DocumentExtractionError,
        extract_workspace_document,
    )

    with pytest.raises(DocumentExtractionError, match="document_type_mismatch"):
        extract_workspace_document("contract.txt", "application/pdf", b"text")


@pytest.mark.asyncio
async def test_contract_review_rejects_unknown_references_and_marks_missing_law() -> None:
    from app.services.workspace_documents import (
        ContractReviewResult,
        normalize_contract_review,
    )

    raw = ContractReviewResult.model_validate(
        {
            "findings": [
                {
                    "clause_id": "clause-1",
                    "risk_level": "high",
                    "issue": "Thiếu thời hạn báo trước",
                    "legal_evidence_ids": [],
                    "recommendation": "Bổ sung thời hạn.",
                    "support_state": "evidence_linked",
                }
            ]
        }
    )
    normalized = normalize_contract_review(raw, {"clause-1"}, set())
    assert normalized.findings[0].support_state == "needs_verification"
    with pytest.raises(ValueError, match="invalid_clause_reference"):
        normalize_contract_review(raw, {"different"}, set())
    invalid_law = raw.model_copy(deep=True)
    invalid_law.findings[0].legal_evidence_ids = ["forged"]
    with pytest.raises(ValueError, match="invalid_evidence_reference"):
        normalize_contract_review(invalid_law, {"clause-1"}, {"selected"})
