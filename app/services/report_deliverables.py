"""Provider-free report deliverables; source snapshots remain separate from edits."""
from __future__ import annotations

import re
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from xml.sax.saxutils import escape, quoteattr
from collections import Counter
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
    sources = report_sources(analysis)
    counts = Counter(source['id'] for source in sources)
    anchors = {source['id']: f'source_{i}' for i, source in enumerate(sources)
               if source['id'] and counts[source['id']] == 1}
    relationships = []

    def clean(value):
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", "", value)

    def run(text, bold=False, link=False):
        properties = ('<w:b/>' if bold else '') + ('<w:color w:val="0563C1"/><w:u w:val="single"/>' if link else '')
        return f'<w:r><w:rPr>{properties}</w:rPr><w:t xml:space="preserve">{escape(clean(text))}</w:t></w:r>'

    def paragraph(line, citations=False):
        bold = line.startswith('#')
        text = line.lstrip('# ') if bold else line
        pieces, start = [], 0
        if citations:
            for match in re.finditer(r'\[([A-Za-z0-9, -]+)\](?!\()', text):
                ids = [item.strip() for item in match.group(1).split(',')]
                if any(identifier not in anchors for identifier in ids):
                    continue
                pieces.append(run(text[start:match.start()], bold))
                pieces.append(run('['))
                for index, identifier in enumerate(ids):
                    if index:
                        pieces.append(run(', '))
                    pieces.append(f'<w:hyperlink w:anchor="{anchors[identifier]}">{run(identifier, link=True)}</w:hyperlink>')
                pieces.append(run(']'))
                start = match.end()
        pieces.append(run(text[start:], bold))
        return '<w:p>' + ''.join(pieces) + '</w:p>'

    paragraphs = [paragraph(line, citations=True) for line in report_body(analysis).splitlines()]
    paragraphs.append(paragraph('## Sources (saved snapshots)'))
    for index, source in enumerate(sources):
        heading = run(f"{source['id']} · {source['citation']}", bold=True)
        if source['id'] in anchors:
            heading = f'<w:bookmarkStart w:id="{index}" w:name="{anchors[source["id"]]}"/>' + heading + f'<w:bookmarkEnd w:id="{index}"/>'
        paragraphs.append('<w:p>' + heading + '</w:p>')
        if source['url'] and clean(source['url']) == source['url']:
            rid = f'rId{len(relationships)+1}'
            relationships.append(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target={quoteattr(source["url"])} TargetMode="External"/>')
            paragraphs.append(f'<w:p><w:hyperlink r:id="{rid}">{run(source["url"], link=True)}</w:hyperlink></w:p>')
        paragraphs.extend(paragraph(line) for line in source['excerpt'].splitlines())
    paragraphs.append(paragraph('Trạng thái: ' + str(analysis.get('status', 'unknown'))))
    paragraphs.append(paragraph('Nội dung giới hạn trong nguồn đã chọn; chưa chứng nhận tính đúng luật hoặc hiệu lực hiện hành.'))
    document = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>' + "".join(paragraphs) + '<w:sectPr/></w:body></w:document>'
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(relationships) + "</Relationships>")
    return output.getvalue()
