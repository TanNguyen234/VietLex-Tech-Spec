"""Provider-free report deliverables; source snapshots remain separate from edits."""
from __future__ import annotations

import re
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from xml.sax.saxutils import escape
from urllib.parse import urlsplit
from html import escape as html_escape


def report_preview(analysis: dict) -> str:
    """Render the report's headings, lists and source references; no active Markdown links/HTML."""
    sources = {source['id']: source for source in report_sources(analysis)}

    def inline(value):
        value = html_escape(value)
        value = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', value)

        def references(match):
            ids = [item.strip() for item in match.group(1).split(',')]
            if not ids or any(identifier not in sources for identifier in ids):
                return match.group(0)
            return ' · '.join(
                '<a href="#report-source-' + html_escape(identifier, quote=True) + '">' +
                html_escape(sources[identifier]['citation'] or identifier) + '</a>' for identifier in ids)
        return re.sub(r'\[([A-Za-z0-9, -]+)\](?!\()', references, value)

    blocks = []
    in_list = False
    for line in report_body(analysis).splitlines():
        is_item = line.startswith('- ')
        if in_list and not is_item:
            blocks.append('</ul>')
            in_list = False
        if is_item:
            if not in_list:
                blocks.append('<ul>')
                in_list = True
            blocks.append('<li>' + inline(line[2:]) + '</li>')
        elif match := re.match(r'^(#{1,4})\s+(.+)$', line):
            tag = 'h' + str(len(match.group(1)))
            blocks.append(f'<{tag}>' + inline(match.group(2)) + f'</{tag}>')
        elif line.strip():
            blocks.append('<p>' + inline(line) + '</p>')
    if in_list:
        blocks.append('</ul>')
    return '\n'.join(blocks)


def report_body(analysis: dict) -> str:
    if "markdown" in analysis:
        return str(analysis["markdown"])
    report = (analysis.get("result") or {}).get("report") or {}
    lines = ["# Legal Research Memorandum", "", "## Issue", str(report.get("issue") or "Chưa có nội dung")]
    for key, title in [("analysis", "Analysis"), ("exceptions", "Exceptions"), ("checklist", "Checklist")]:
        lines.extend(["", "## " + title])
        for claim in report.get(key) or []:
            ids = ", ".join(str(value) for value in claim.get("evidence_ids") or [])
            lines.append(f"- {claim.get('text', '')} [{ids}]")
    lines.extend(["", "## Risks / Unknown"])
    lines.extend("- " + str(value) for value in report.get("unknown") or [])
    return "\n".join(lines)


def report_sources(analysis: dict) -> list[dict]:
    sources = []
    for item in analysis.get("evidence_snapshot") or []:
        url = str(item.get("source_url") or "")
        try:
            parsed = urlsplit(url)
            valid = parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username and not parsed.password
        except ValueError:
            valid = False
        sources.append({"id": str(item.get("evidence_id") or ""),
                        "citation": str(item.get("citation") or item.get("title") or ""),
                        "url": url if valid else "",
                        "excerpt": str(item.get("excerpt") or item.get("original") or "")})
    return sources


def report_markdown(analysis: dict) -> str:
    lines = [report_body(analysis), "", "## Sources (saved snapshots)"]
    for source in report_sources(analysis):
        lines.extend(["", f"### {source['id']} · {source['citation']}", source["url"], source["excerpt"]])
    lines.extend(["", "---", "Trạng thái: " + str(analysis.get("status", "unknown")),
                  "Nội dung giới hạn trong nguồn đã chọn; chưa chứng nhận tính đúng luật hoặc hiệu lực hiện hành."])
    return "\n".join(lines) + "\n"


def report_docx(analysis: dict) -> bytes:
    # Standard Office Open XML, no runtime conversion service or provider.
    paragraphs = []
    for line in report_markdown(analysis).splitlines():
        line = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", line)
        bold = "<w:rPr><w:b/></w:rPr>" if line.startswith("#") else ""
        text = line.lstrip("# ") if bold else line
        paragraphs.append(f'<w:p><w:r>{bold}<w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>')
    document = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + "".join(paragraphs) + '<w:sectPr/></w:body></w:document>'
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr("word/document.xml", document)
    return output.getvalue()
