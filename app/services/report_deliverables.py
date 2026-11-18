"""Provider-free report deliverables; source snapshots remain separate from edits."""
from __future__ import annotations

from collections import Counter
from html import escape as html_escape
from io import BytesIO
import re
from urllib.parse import urlsplit
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZIP_DEFLATED, ZipFile


def report_assessed_claims(analysis: dict) -> list[dict]:
    # An edited version has not been assessed against its new text.
    if "markdown" in analysis:
        return []
    assessment = (
        (analysis.get("result") or {}).get("model_assessment")
        or analysis.get("model_assessment")
        or {}
    )
    return (assessment.get("result") or {}).get("claims") or []


def report_display_status(analysis: dict) -> str:
    status = str(analysis.get("status") or "unknown")
    if status == "ok" and any(
        item.get("verdict") in {"contradicted", "insufficient"}
        for item in report_assessed_claims(analysis)
    ):
        return "insufficient_evidence"
    return status


def report_review_notice(analysis: dict) -> str:
    status = str(analysis.get("status") or "")
    if status in {"ok", "insufficient_evidence"} and any(
        item.get("verdict") in {"contradicted", "insufficient"}
        for item in report_assessed_claims(analysis)
    ):
        return (
            "Bản nháp chưa xác minh. Có nhận định bị mô hình đánh giá mâu thuẫn "
            "hoặc chưa đủ bằng chứng. Xem đánh giá từng nhận định và đối chiếu bản gốc."
        )
    if status == "ok":
        return ""
    reason = {
        "invalid_evidence_reference": "Mô hình dùng mã bằng chứng không có trong nguồn đã chọn.",
        "invalid_evidence_quote": "Câu trích của mô hình không khớp nguyên văn với nguồn đã chọn.",
    }.get(str(analysis.get("error_code") or ""))
    if reason is None:
        reason = {
            "human_edited_unverified": "Nội dung đã được chỉnh sửa và chưa kiểm chứng lại.",
            "citation_mismatch": "Dẫn nguồn của một số khẳng định cần đối chiếu lại.",
            "provider_error": "Dịch vụ tạo hoặc kiểm chứng báo cáo chưa hoàn tất.",
            "insufficient_evidence": "Nguồn đã chọn chưa đủ để kết luận.",
        }.get(status, "Báo cáo chưa vượt qua bước kiểm chứng.")
    return "Bản nháp chưa xác minh. " + reason + " Cần đối chiếu bản gốc trước khi sử dụng."


def report_preview(analysis: dict) -> str:
    """Render the report's headings, lists and source references; no active Markdown links/HTML."""
    sources = {source["id"]: source for source in report_sources(analysis)}

    def inline(value: str) -> str:
        value = html_escape(value)
        value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)

        def references(match: re.Match[str]) -> str:
            ids = [item.strip() for item in match.group(1).split(",")]
            if not ids or any(identifier not in sources for identifier in ids):
                return match.group(0)
            return " · ".join(
                '<a href="#report-source-'
                + html_escape(identifier, quote=True)
                + '">'
                + html_escape(sources[identifier]["citation"] or identifier)
                + "</a>"
                for identifier in ids
            )

        return re.sub(r"\[([A-Za-z0-9, -]+)\](?!\()", references, value)

    notice = report_review_notice(analysis)
    blocks = ['<p class="legal-warning">' + html_escape(notice) + "</p>"] if notice else []
    in_list = False
    for line in report_body(analysis).splitlines():
        is_item = line.startswith("- ")
        if in_list and not is_item:
            blocks.append("</ul>")
            in_list = False
        if is_item:
            if not in_list:
                blocks.append("<ul>")
                in_list = True
            blocks.append("<li>" + inline(line[2:]) + "</li>")
        elif match := re.match(r"^(#{1,4})\s+(.+)$", line):
            tag = "h" + str(len(match.group(1)))
            blocks.append(f"<{tag}>" + inline(match.group(2)) + f"</{tag}>")
        elif line.strip():
            blocks.append("<p>" + inline(line) + "</p>")
    if in_list:
        blocks.append("</ul>")
    return "\n".join(blocks)


def report_body(analysis: dict) -> str:
    if "markdown" in analysis:
        return str(analysis["markdown"])
    report = (analysis.get("result") or {}).get("report") or {}
    lines = [
        "# Bản Ghi Nhớ Nghiên Cứu Pháp Lý",
        "",
        "## 1. Vấn đề pháp lý",
        str(report.get("issue") or "Chưa có nội dung"),
    ]
    section_titles = [
        ("analysis", "2. Phân tích căn cứ"),
        ("exceptions", "3. Ngoại lệ và điều kiện áp dụng"),
        ("checklist", "4. Danh mục rà soát thực thi"),
    ]
    for key, title in section_titles:
        lines.extend(["", "## " + title])
        for claim in report.get(key) or []:
            ids = ", ".join(str(value) for value in claim.get("evidence_ids") or [])
            lines.append(f"- {claim.get('text', '')} [{ids}]")
    lines.extend(["", "## 5. Điểm chưa đủ căn cứ / Rủi ro cần xác minh"])
    lines.extend("- " + str(value) for value in report.get("unknown") or [])
    assessments = report_assessed_claims(analysis)
    if assessments:
        lines.extend(["", "## Đánh giá từng nhận định (mô hình, chưa chứng nhận pháp lý)"])
        for claim in assessments:
            lines.append(
                f"- {claim.get('claim_id', '')}: {claim.get('verdict', 'unknown')} · {claim.get('text', '')}"
            )
            for quote in claim.get("quotes") or []:
                lines.append(f"  - [{quote.get('evidence_id', '')}] {quote.get('quote', '')}")
    return "\n".join(lines)


def report_sources(analysis: dict) -> list[dict]:
    sources = []
    for item in analysis.get("evidence_snapshot") or []:
        url = str(item.get("source_url") or "")
        try:
            parsed = urlsplit(url)
            valid = (
                parsed.scheme in {"https", "http"}
                and parsed.hostname
                and not parsed.username
                and not parsed.password
            )
        except ValueError:
            valid = False
        sources.append(
            {
                "id": str(item.get("evidence_id") or ""),
                "citation": str(item.get("citation") or item.get("title") or ""),
                "url": url if valid else "",
                "excerpt": str(item.get("excerpt") or item.get("original") or ""),
            }
        )
    return sources


def report_markdown(analysis: dict) -> str:
    notice = report_review_notice(analysis)
    lines = (["> " + notice, ""] if notice else []) + [
        report_body(analysis),
        "",
        "## Nguồn căn cứ (bản chụp đã lưu)",
    ]
    for source in report_sources(analysis):
        lines.extend(
            [
                "",
                f"### {source['id']} · {source['citation']}",
                source["url"],
                source["excerpt"],
            ]
        )
    lines.extend(
        [
            "",
            "---",
            "Trạng thái: " + report_display_status(analysis),
            "Nội dung giới hạn trong nguồn đã chọn; chưa chứng nhận tính đúng luật hoặc hiệu lực hiện hành.",
        ]
    )
    return "\n".join(lines) + "\n"


def report_docx(analysis: dict) -> bytes:
    # Standard Office Open XML (Decree-30 A4 layout & Times New Roman 13pt),
    # keeping word/_rels/document.xml.rels strictly limited to external hyperlinks.
    sources = report_sources(analysis)
    counts = Counter(source["id"] for source in sources)
    anchors = {
        source["id"]: f"source_{i}"
        for i, source in enumerate(sources)
        if source["id"] and counts[source["id"]] == 1
    }
    relationships: list[str] = []

    def clean(value: str) -> str:
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", "", value)

    font_xml = (
        '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>'
    )

    def run(
        text: str,
        *,
        bold: bool = False,
        italic: bool = False,
        link: bool = False,
        size_half_pt: int = 26,
        color: str | None = None,
    ) -> str:
        r_props = [font_xml, f'<w:sz w:val="{size_half_pt}"/><w:szCs w:val="{size_half_pt}"/>']
        if bold:
            r_props.append("<w:b/>")
        if italic:
            r_props.append("<w:i/>")
        if link:
            r_props.append('<w:color w:val="0563C1"/><w:u w:val="single"/>')
        elif color:
            r_props.append(f'<w:color w:val="{color}"/>')
        return (
            f"<w:r><w:rPr>{''.join(r_props)}</w:rPr>"
            f'<w:t xml:space="preserve">{escape(clean(text))}</w:t></w:r>'
        )

    def _styled_segment_runs(
        segment: str,
        *,
        bold: bool = False,
        italic: bool = False,
        size_half_pt: int = 26,
        color: str | None = None,
    ) -> list[str]:
        if not segment:
            return []
        out: list[str] = []
        pos = 0
        for bold_match in re.finditer(r"\*\*([^*]+)\*\*", segment):
            if bold_match.start() > pos:
                out.append(
                    run(
                        segment[pos : bold_match.start()],
                        bold=bold,
                        italic=italic,
                        size_half_pt=size_half_pt,
                        color=color,
                    )
                )
            out.append(
                run(
                    bold_match.group(1),
                    bold=True,
                    italic=italic,
                    size_half_pt=size_half_pt,
                    color=color,
                )
            )
            pos = bold_match.end()
        if pos < len(segment):
            out.append(
                run(
                    segment[pos:],
                    bold=bold,
                    italic=italic,
                    size_half_pt=size_half_pt,
                    color=color,
                )
            )
        return out

    def _inline_runs(
        text: str,
        *,
        citations: bool,
        bold: bool = False,
        italic: bool = False,
        size_half_pt: int = 26,
        color: str | None = None,
    ) -> str:
        pieces: list[str] = []
        start = 0
        if citations:
            for match in re.finditer(r"\[([A-Za-z0-9, -]+)\](?!\()", text):
                ids = [item.strip() for item in match.group(1).split(",")]
                if any(identifier not in anchors for identifier in ids):
                    continue
                if match.start() > start:
                    pieces.extend(
                        _styled_segment_runs(
                            text[start : match.start()],
                            bold=bold,
                            italic=italic,
                            size_half_pt=size_half_pt,
                            color=color,
                        )
                    )
                pieces.append(run("[", size_half_pt=size_half_pt))
                for index, identifier in enumerate(ids):
                    if index:
                        pieces.append(run(", ", size_half_pt=size_half_pt))
                    pieces.append(
                        f'<w:hyperlink w:anchor="{anchors[identifier]}">'
                        f"{run(identifier, link=True, size_half_pt=size_half_pt)}"
                        "</w:hyperlink>"
                    )
                pieces.append(run("]", size_half_pt=size_half_pt))
                start = match.end()
        if start < len(text):
            pieces.extend(
                _styled_segment_runs(
                    text[start:],
                    bold=bold,
                    italic=italic,
                    size_half_pt=size_half_pt,
                    color=color,
                )
            )
        elif not pieces:
            pieces.append(
                run(
                    "",
                    bold=bold,
                    italic=italic,
                    size_half_pt=size_half_pt,
                    color=color,
                )
            )
        return "".join(pieces)

    def paragraph(line: str, *, citations: bool = False, is_notice: bool = False) -> str:
        if not line.strip():
            return ""
        if is_notice:
            p_pr = (
                '<w:pPr><w:spacing w:before="120" w:after="160" w:line="312" w:lineRule="auto"/>'
                '<w:pBdr><w:left w:val="single" w:sz="12" w:space="8" w:color="946B3D"/></w:pBdr>'
                '<w:ind w:left="240"/></w:pPr>'
            )
            return f"<w:p>{p_pr}{_inline_runs(line, citations=False, bold=True, color='946B3D')}</w:p>"
        if heading_match := re.match(r"^(#{1,3})\s+(.+)$", line):
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            if level == 1:
                p_pr = (
                    '<w:pPr><w:jc w:val="center"/><w:spacing w:before="240" w:after="180"/>'
                    '<w:pBdr><w:bottom w:val="single" w:sz="8" w:space="6" w:color="946B3D"/></w:pBdr></w:pPr>'
                )
                sz = 32
            elif level == 2:
                p_pr = (
                    '<w:pPr><w:spacing w:before="220" w:after="100"/>'
                    '<w:pBdr><w:bottom w:val="single" w:sz="4" w:space="4" w:color="DCDED4"/></w:pBdr></w:pPr>'
                )
                sz = 28
            else:
                p_pr = '<w:pPr><w:spacing w:before="160" w:after="80"/></w:pPr>'
                sz = 26
            return (
                f"<w:p>{p_pr}"
                f"{_inline_runs(heading_text, citations=citations, bold=True, size_half_pt=sz, color='163B3A')}"
                "</w:p>"
            )
        if line.startswith("  - "):
            body_text = line[4:].strip()
            p_pr = (
                '<w:pPr><w:ind w:left="1080" w:hanging="360"/>'
                '<w:spacing w:after="80" w:line="312" w:lineRule="auto"/></w:pPr>'
            )
            return (
                f"<w:p>{p_pr}{run('◦ ', bold=True)}"
                f"{_inline_runs(body_text, citations=citations)}</w:p>"
            )
        if line.startswith("- "):
            body_text = line[2:].strip()
            p_pr = (
                '<w:pPr><w:ind w:left="720" w:hanging="360"/>'
                '<w:spacing w:after="80" w:line="312" w:lineRule="auto"/></w:pPr>'
            )
            return (
                f"<w:p>{p_pr}{run('• ', bold=True)}"
                f"{_inline_runs(body_text, citations=citations)}</w:p>"
            )
        p_pr = '<w:pPr><w:jc w:val="both"/><w:spacing w:after="120" w:line="312" w:lineRule="auto"/></w:pPr>'
        return f"<w:p>{p_pr}{_inline_runs(line, citations=citations)}</w:p>"

    notice = report_review_notice(analysis)
    paragraphs = [
        item
        for item in (
            ([paragraph(notice, is_notice=True)] if notice else [])
            + [paragraph(line, citations=True) for line in report_body(analysis).splitlines()]
        )
        if item
    ]
    paragraphs.append(paragraph("## Nguồn căn cứ (bản chụp đã lưu)"))
    for index, source in enumerate(sources):
        heading = run(
            f"{source['id']} · {source['citation']}",
            bold=True,
            size_half_pt=26,
            color="163B3A",
        )
        if source["id"] in anchors:
            heading = (
                f'<w:bookmarkStart w:id="{index}" w:name="{anchors[source["id"]]}"/>'
                + heading
                + f'<w:bookmarkEnd w:id="{index}"/>'
            )
        paragraphs.append(
            '<w:p><w:pPr><w:spacing w:before="140" w:after="60"/></w:pPr>' + heading + "</w:p>"
        )
        if source["url"] and clean(source["url"]) == source["url"]:
            rid = f"rId{len(relationships) + 1}"
            relationships.append(
                f'<Relationship Id="{rid}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
                f'Target={quoteattr(source["url"])} TargetMode="External"/>'
            )
            paragraphs.append(
                f'<w:p><w:pPr><w:spacing w:after="60"/></w:pPr>'
                f'<w:hyperlink r:id="{rid}">{run(source["url"], link=True, size_half_pt=24)}</w:hyperlink></w:p>'
            )
        paragraphs.extend(
            item for line in source["excerpt"].splitlines() if (item := paragraph(line))
        )
    paragraphs.append(paragraph("Trạng thái: " + report_display_status(analysis)))
    paragraphs.append(
        paragraph(
            "Nội dung giới hạn trong nguồn đã chọn; chưa chứng nhận tính đúng luật hoặc hiệu lực hiện hành."
        )
    )
    sect_pr = (
        "<w:sectPr>"
        '<w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1440" w:right="1134" w:bottom="1440" w:left="1701" w:header="708" w:footer="708" w:gutter="0"/>'
        "</w:sectPr>"
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<w:body>"
        + "".join(paragraphs)
        + sect_pr
        + "</w:body></w:document>"
    )
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        archive.writestr("word/document.xml", document)
        archive.writestr(
            "word/_rels/document.xml.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(relationships)
            + "</Relationships>",
        )
    return output.getvalue()
