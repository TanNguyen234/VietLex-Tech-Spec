from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import optional_user, require_admin
from app.services.document_redline import compare_documents
from app.services.workspace_documents import extract_workspace_document

ROOT = Path(__file__).resolve().parents[2]


def _build_numbered_docx() -> bytes:
    numbering_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:abstractNum w:abstractNumId="10">
    <w:lvl w:ilvl="0">
      <w:start w:val="1"/>
      <w:numFmt w:val="decimal"/>
      <w:lvlText w:val="Điều %1."/>
    </w:lvl>
    <w:lvl w:ilvl="1">
      <w:start w:val="1"/>
      <w:numFmt w:val="decimal"/>
      <w:lvlText w:val="%1.%2."/>
    </w:lvl>
    <w:lvl w:ilvl="2">
      <w:start w:val="1"/>
      <w:numFmt w:val="lowerLetter"/>
      <w:lvlText w:val="%3)"/>
    </w:lvl>
  </w:abstractNum>
  <w:num w:numId="5">
    <w:abstractNumId w:val="10"/>
  </w:num>
</w:numbering>"""

    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="5"/></w:numPr></w:pPr>
      <w:r><w:t>Đối tượng hợp đồng</w:t></w:r>
    </w:p>
    <w:p>
      <w:pPr><w:numPr><w:ilvl w:val="1"/><w:numId w:val="5"/></w:numPr></w:pPr>
      <w:r><w:t>Phạm vi cung cấp dịch vụ tư vấn</w:t></w:r>
    </w:p>
    <w:p>
      <w:pPr><w:numPr><w:ilvl w:val="2"/><w:numId w:val="5"/></w:numPr></w:pPr>
      <w:r><w:t>Soạn thảo hồ sơ pháp lý</w:t></w:r>
    </w:p>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Đợt thanh toán</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Tỷ lệ</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Đợt 1</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>50%</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
    <w:p>
      <w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="5"/></w:numPr></w:pPr>
      <w:r><w:t>Phạt vi phạm và bồi thường</w:t></w:r>
    </w:p>
    <w:p>
      <w:pPr><w:numPr><w:ilvl w:val="1"/><w:numId w:val="5"/></w:numPr></w:pPr>
      <w:r><w:t>Mức phạt tối đa 8%</w:t></w:r>
    </w:p>
  </w:body>
</w:document>"""

    buf = BytesIO()
    with ZipFile(buf, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/numbering.xml", numbering_xml)
        archive.writestr("word/document.xml", document_xml)
    return buf.getvalue()


def test_docx_extracts_numbering_prefixes_with_level_reset_and_markdown_tables() -> None:
    extracted = extract_workspace_document(
        "hop-dong.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        _build_numbered_docx(),
    )

    titles = [c.title for c in extracted.clauses]
    assert titles == [
        "Điều 1. Đối tượng hợp đồng",
        "Điều 2. Phạt vi phạm và bồi thường",
    ]
    clause_1_text = extracted.clauses[0].text
    assert "1.1. Phạm vi cung cấp dịch vụ tư vấn" in clause_1_text
    assert "a) Soạn thảo hồ sơ pháp lý" in clause_1_text
    assert "| Đợt thanh toán | Tỷ lệ |" in clause_1_text
    assert "| Đợt 1 | 50% |" in clause_1_text
    # Level 1 counter reset when parent level 0 incremented to Điều 2!
    assert "2.1. Mức phạt tối đa 8%" in extracted.clauses[1].text


def test_redline_pairs_edited_clauses_by_structural_id_and_jaccard_with_inline_word_tokens() -> None:
    doc_a = {
        "document_id": "contract-v1",
        "clauses": [
            {
                "clause_id": "aaa111-001",
                "title": "Điều 1. Giá và thanh toán",
                "text": "Bên A thanh toán cho Bên B trong thời hạn 15 ngày làm việc kể từ ngày nhận hóa đơn.",
                "order": 1,
            },
            {
                "clause_id": "aaa111-002",
                "title": "Cam kết bảo mật thông tin",
                "text": "Các bên cam kết giữ bí mật toàn bộ tài liệu thương mại trong thời hạn 03 năm.",
                "order": 2,
            },
        ],
    }
    doc_b = {
        "document_id": "contract-v2",
        "clauses": [
            {
                "clause_id": "bbb222-001",
                "title": "Điều 1. Giá dịch vụ và tiến độ thanh toán",
                "text": "Bên A thanh toán cho Bên B trong thời hạn 30 ngày làm việc kể từ ngày nhận hóa đơn hợp lệ.",
                "order": 1,
            },
            {
                "clause_id": "bbb222-002",
                "title": "Nghĩa vụ bảo mật thông tin",
                "text": "Các bên cam kết giữ bí mật toàn bộ tài liệu thương mại trong thời hạn 05 năm.",
                "order": 2,
            },
        ],
    }

    diff = compare_documents(doc_a, doc_b)
    assert diff["schema_version"] == "document-redline-v1"
    assert diff["added"] == []
    assert diff["removed"] == []
    assert len(diff["changed"]) == 2

    first = diff["changed"][0]
    assert first["comparison_mode"] == "detailed"
    tokens = first["inline_tokens"]
    assert any(t["kind"] == "delete" and "15" in t["text"] for t in tokens)
    assert any(t["kind"] == "insert" and "30" in t["text"] for t in tokens)
    assert "".join(t["text"] for t in tokens if t["kind"] != "insert") == doc_a["clauses"][0]["text"]
    assert "".join(t["text"] for t in tokens if t["kind"] != "delete") == doc_b["clauses"][0]["text"]


def test_workspace_evidence_persists_across_tabs_and_admin_registry_lists_pending_without_workspace_param(
    monkeypatch,
) -> None:
    evidence_tpl = (ROOT / "app/templates/workspace_evidence.html").read_text(encoding="utf-8")
    assert 'data-workspace-panel="sources analysis review reports"' in evidence_tpl

    ws_js = (ROOT / "app/static/js/research-workspace.js").read_text(encoding="utf-8")
    assert "Chạy tự động toàn bộ các lô" in ws_js
    assert "Tải bảng phát hiện (.csv)" in ws_js
    assert "redline-inline" in ws_js

    import app.database as db_mod
    from app.api import legal_registry_routes

    list_ws = AsyncMock(
        return_value=[
            {
                "_id": "ws-pending-99",
                "workspace_id": "ws-pending-99",
                "title": "Hồ sơ rà soát NĐ 168",
                "analyses": [
                    {
                        "analysis_id": "rev-99",
                        "kind": "legal_effect_review",
                        "reviewed_at": "2026-11-18T00:00:00+00:00",
                        "result": {
                            "assertions": [
                                {
                                    "document_number": "168/2024/NĐ-CP",
                                    "target_document_number": "100/2019/NĐ-CP",
                                    "effective_date": "2025-01-01",
                                    "scope": "partial",
                                    "exact_quote": "Sửa đổi, bổ sung một số điều",
                                    "source_url": "https://vanban.chinhphu.vn/?docid=168",
                                }
                            ]
                        },
                    }
                ],
            }
        ]
    )
    fake_reg_cursor = SimpleNamespace(to_list=AsyncMock(return_value=[]))
    fake_db = SimpleNamespace(
        legal_effect_registry=SimpleNamespace(find=lambda *_a, **_kw: fake_reg_cursor),
    )
    monkeypatch.setattr(db_mod, "db", fake_db)
    monkeypatch.setattr("app.research_database.list_workspaces", list_ws)
    monkeypatch.setattr(legal_registry_routes, "registry_records", AsyncMock(return_value=[]))

    app = FastAPI()
    app.include_router(legal_registry_routes.router)
    app.dependency_overrides[require_admin] = lambda: {"_id": "admin-1"}
    app.dependency_overrides[optional_user] = lambda: {"_id": "admin-1"}
    resp = TestClient(app).get("/admin/legal-registry")

    assert resp.status_code == 200
    assert "Hồ sơ rà soát NĐ 168" in resp.text
    assert "/workspaces/ws-pending-99/analyses/rev-99/publish-legal-effect" in resp.text


def test_long_clause_single_word_edit_preserves_word_level_inline_tokens_and_docx_hardening() -> None:
    from io import BytesIO
    from zipfile import ZIP_DEFLATED, ZipFile
    import pytest
    from app.services.document_redline import compare_documents
    from app.services.workspace_documents import DocumentExtractionError, extract_workspace_document

    # 400-word contract clause (~800 tokens > 600 cap before prefix/suffix trimming)
    preamble = " ".join(f"khoản_mục_{i}" for i in range(200))
    tail = " ".join(f"nghĩa_vụ_{i}" for i in range(200))
    doc_a = {
        "document_id": "a" * 24,
        "clauses": [{"clause_id": f"{'a'*24}-001", "title": "Điều 5", "text": f"{preamble} trong thời hạn 15 ngày {tail}"}],
    }
    doc_b = {
        "document_id": "b" * 24,
        "clauses": [{"clause_id": f"{'b'*24}-001", "title": "Điều 5", "text": f"{preamble} trong thời hạn 30 ngày {tail}"}],
    }
    diff = compare_documents(doc_a, doc_b)
    tokens = diff["changed"][0]["inline_tokens"]
    # Must NOT collapse into 2 full-clause delete+insert blocks!
    assert len(tokens) >= 4
    assert any(t["kind"] == "delete" and t["text"] == "15" for t in tokens)
    assert any(t["kind"] == "insert" and t["text"] == "30" for t in tokens)

    # DOCX DTD / entity expansion must fail closed as malformed_document
    buf = BytesIO()
    with ZipFile(buf, "w", ZIP_DEFLATED) as zf:
        zf.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe "boom">]><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>&xxe;</w:t></w:r></w:p></w:body></w:document>',
        )
    with pytest.raises(DocumentExtractionError) as exc_info:
        extract_workspace_document("evil.docx", "", buf.getvalue())
    assert exc_info.value.kind == "malformed_document"

    # DOCX numFmt="none" must not prepend "1."
    buf_none = BytesIO()
    with ZipFile(buf_none, "w", ZIP_DEFLATED) as zf:
        zf.writestr(
            "word/numbering.xml",
            '<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="none"/><w:lvlText w:val="%1."/></w:lvl></w:abstractNum>'
            '<w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num></w:numbering>',
        )
        zf.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
            '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>Điều khoản không số</w:t></w:r></w:p>'
            '</w:body></w:document>',
        )
    extracted = extract_workspace_document("none.docx", "", buf_none.getvalue())
    assert extracted.clauses[0].text == "Điều khoản không số"
