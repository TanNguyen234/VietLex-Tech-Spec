from __future__ import annotations

from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from app.services.report_deliverables import report_body, report_docx, report_markdown


def _sample_report_analysis() -> dict:
    return {
        "analysis_id": "rep-vn-1",
        "kind": "research_report",
        "status": "ok",
        "result": {
            "report": {
                "issue": "Thời hạn thử việc đối với vị trí quản lý doanh nghiệp",
                "analysis": [
                    {
                        "text": "Thời gian thử việc không quá 180 ngày đối với người quản lý doanh nghiệp.",
                        "evidence_ids": ["ev-1"],
                    }
                ],
                "exceptions": [
                    {
                        "text": "Không áp dụng thử việc đối với hợp đồng lao động dưới 01 tháng.",
                        "evidence_ids": ["ev-1"],
                    }
                ],
                "checklist": [
                    {
                        "text": "Kiểm tra điều lệ công ty và quyết định bổ nhiệm.",
                        "evidence_ids": ["ev-1"],
                    }
                ],
                "unknown": [
                    "Chưa có thông tin chức danh cụ thể theo Luật Doanh nghiệp."
                ],
            }
        },
        "evidence_snapshot": [
            {
                "evidence_id": "ev-1",
                "citation": "45/2019/QH14 · Điều 25",
                "excerpt": "Không quá 180 ngày đối với công việc của người quản lý doanh nghiệp.",
                "source_url": "https://vbpl.vn/bllđ-2019",
            }
        ],
    }


def test_report_markdown_and_body_use_vietnamese_memorandum_headings() -> None:
    analysis = _sample_report_analysis()
    body = report_body(analysis)
    md = report_markdown(analysis)

    for expected in (
        "# Bản Ghi Nhớ Nghiên Cứu Pháp Lý",
        "## 1. Vấn đề pháp lý",
        "## 2. Phân tích căn cứ",
        "## 3. Ngoại lệ và điều kiện áp dụng",
        "## 4. Danh mục rà soát thực thi",
        "## 5. Điểm chưa đủ căn cứ / Rủi ro cần xác minh",
    ):
        assert expected in body
        assert expected in md

    assert "## Nguồn căn cứ (bản chụp đã lưu)" in md
    assert "Legal Research Memorandum" not in md
    assert "Sources (saved snapshots)" not in md


def test_report_docx_uses_decree_30_margins_times_new_roman_and_hyperlink_only_rels() -> None:
    analysis = _sample_report_analysis()
    payload = report_docx(analysis)

    with ZipFile(BytesIO(payload)) as archive:
        doc_xml = archive.read("word/document.xml")
        rels_xml = archive.read("word/_rels/document.xml.rels")

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    w = "{" + ns["w"] + "}"
    root = ET.fromstring(doc_xml)
    rels = ET.fromstring(rels_xml)

    full_text = "".join(root.itertext())
    assert "Bản Ghi Nhớ Nghiên Cứu Pháp Lý" in full_text
    assert "1. Vấn đề pháp lý" in full_text
    assert "Nguồn căn cứ (bản chụp đã lưu)" in full_text
    # Raw "- " markdown prefix is formatted into proper bullet paragraph indentation, not literal "- "
    assert "- Thời gian thử việc" not in full_text

    # Fonts & sizes: Times New Roman + 13pt (26 half-points) + #163B3A headings
    fonts = [el.get(w + "ascii") for el in root.findall(".//w:rFonts", ns)]
    assert "Times New Roman" in fonts
    sizes = {el.get(w + "val") for el in root.findall(".//w:sz", ns)}
    assert "26" in sizes
    colors = {el.get(w + "val") for el in root.findall(".//w:color", ns)}
    assert "163B3A" in colors

    # Bullet indentation present
    indents = root.findall(".//w:ind", ns)
    assert indents

    # Decree-30 A4 page size & margins
    pg_sz = root.find(".//w:sectPr/w:pgSz", ns)
    pg_mar = root.find(".//w:sectPr/w:pgMar", ns)
    assert pg_sz is not None
    assert pg_sz.get(w + "w") == "11906"
    assert pg_sz.get(w + "h") == "16838"
    assert pg_mar is not None
    assert pg_mar.get(w + "top") == "1440"
    assert pg_mar.get(w + "right") == "1134"
    assert pg_mar.get(w + "bottom") == "1440"
    assert pg_mar.get(w + "left") == "1701"

    # Security/contract invariant: document.xml.rels contains ONLY external hyperlinks!
    assert [r.get("Target") for r in rels] == ["https://vbpl.vn/bllđ-2019"]
    assert all(r.get("TargetMode") == "External" for r in rels)
