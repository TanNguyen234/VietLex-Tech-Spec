import re

from typing import Optional
from app.ingestion.schemas import LegalDocumentSchema, ExtractedMetadata, ExtractedMetadataField

# Document types list in Vietnamese legal system
DOCUMENT_TYPES = [
    "Bộ luật", "Luật", "Pháp lệnh", "Lệnh", "Nghị định", "Nghị quyết",
    "Quyết định", "Thông tư", "Thông tư liên tịch", "Chỉ thị", "Quy định", "Quy chế"
]

class MetadataResolver:
    """
    Deterministic Metadata Resolver & Extractor for Vietnamese Legal Documents.
    Resolves metadata fields with high fidelity and confidence scoring without LLM hallucination.
    """

    def resolve(self, doc: LegalDocumentSchema, body_text: Optional[str] = None) -> ExtractedMetadata:
        title = doc.title or ""
        full_text = body_text if body_text is not None else (doc.full_text or "")
        html_text = doc.html_text or ""
        url = doc.url or ""

        # Header window (first 2000 chars of full_text)
        header_text = full_text[:2500]
        # Footer window (last 1500 chars of full_text)
        footer_text = full_text[-1500:] if len(full_text) > 1500 else full_text

        doc_type = self._extract_document_type(doc.document_type, title, header_text, url)
        official_num = self._extract_official_number(doc.official_number, title, header_text, html_text)
        issued_date = self._extract_issued_date(doc.issued_date, header_text, html_text)
        effective_date = self._extract_effective_date(doc.effective_date, full_text, html_text)
        enforced_date = self._extract_enforced_date(doc.enforced_date, full_text, html_text)
        expiry_date = self._extract_expiry_date(doc.expiry_date, full_text, html_text)
        issuing_body = self._extract_issuing_body(doc.issuing_body, header_text, html_text)
        signer = self._extract_signer(doc.signer, footer_text, html_text)
        status = self._extract_status(doc.status, full_text, html_text)

        return ExtractedMetadata(
            document_type=doc_type,
            official_number=official_num,
            issued_date=issued_date,
            effective_date=effective_date,
            enforced_date=enforced_date,
            expiry_date=expiry_date,
            issuing_body=issuing_body,
            signer=signer,
            status=status
        )

    def _extract_document_type(self, crawled_val: Optional[str], title: str, header: str, url: str) -> ExtractedMetadataField:
        if crawled_val and crawled_val.strip() and crawled_val.strip() != "UNKNOWN":
            return ExtractedMetadataField(
                value=crawled_val.strip(),
                source="crawled_metadata",
                method="direct",
                confidence=1.0
            )

        # Match in title
        for dt in DOCUMENT_TYPES:
            if re.search(r'(?i)\b' + re.escape(dt) + r'\b', title):
                return ExtractedMetadataField(
                    value=dt,
                    source="title",
                    method="regex",
                    confidence=0.95
                )

        # Match in header text
        header_upper = header[:500].upper()
        for dt in DOCUMENT_TYPES:
            if dt.upper() in header_upper:
                return ExtractedMetadataField(
                    value=dt,
                    source="header_text",
                    method="regex",
                    confidence=0.90
                )

        return ExtractedMetadataField(value="UNKNOWN", source="none", method="none", confidence=0.0, reason="not_found")

    def _extract_official_number(self, crawled_val: Optional[str], title: str, header: str, html: str) -> ExtractedMetadataField:
        text_value = self._find_official_number_in_text(title, header)
        if crawled_val and crawled_val.strip() and crawled_val.strip() != "UNKNOWN":
            clean_crawled = crawled_val.strip()
            if text_value and text_value != clean_crawled:
                return ExtractedMetadataField(
                    value=clean_crawled,
                    source="crawled_metadata",
                    method="direct_with_conflict",
                    confidence=0.6,
                    reason="crawled_metadata_conflicts_with_body",
                    evidence={"body_value": text_value},
                    conflicts=[f"official_number crawler={clean_crawled} body={text_value}"],
                )
            return ExtractedMetadataField(
                value=clean_crawled,
                source="crawled_metadata",
                method="direct",
                confidence=0.85,
                reason="crawled_metadata_present"
            )

        if text_value:
            return ExtractedMetadataField(
                value=text_value,
                source="full_text_header",
                method="regex",
                confidence=0.99
            )

        return ExtractedMetadataField(value="UNKNOWN", source="none", method="none", confidence=0.0, reason="not_found")

    def _find_official_number_in_text(self, title: str, header: str) -> Optional[str]:
        # Pattern: Số: 52/2006/NĐ-CP or 22/2023/QH15 or 01/2021/TT-BTP
        pattern = r'(?i)(?:Số|So|Số:|So:)\s*([0-9]+(?:/[0-9]+)?(?:/[A-Za-z0-9_À-ỹ\-]+)?)'
        
        match = re.search(pattern, header)
        if match:
            return match.group(1).strip()

        # Search in title
        match_title = re.search(r'\b([0-9]+/[0-9]{4}/[A-Za-z0-9_À-ỹ\-]+)\b', title)
        if match_title:
            return match_title.group(1).strip()

        return None

    def _extract_issued_date(self, crawled_val: Optional[str], header: str, html: str) -> ExtractedMetadataField:
        if crawled_val and crawled_val.strip() and crawled_val.strip() != "UNKNOWN":
            return ExtractedMetadataField(
                value=crawled_val.strip(),
                source="crawled_metadata",
                method="direct",
                confidence=1.0
            )

        # Pattern: Hà Nội, ngày 23 tháng 6 năm 2023
        pattern = r'(?i)ngày\s+([0-9]{1,2})\s+tháng\s+([0-9]{1,2})\s+năm\s+([0-9]{4})'
        match = re.search(pattern, header)
        if match:
            d, m, y = match.group(1).zfill(2), match.group(2).zfill(2), match.group(3)
            return ExtractedMetadataField(
                value=f"{y}-{m}-{d}",
                source="full_text_header",
                method="regex",
                confidence=0.95
            )

        return ExtractedMetadataField(value="UNKNOWN", source="none", method="none", confidence=0.0, reason="not_found")

    def _extract_effective_date(self, crawled_val: Optional[str], full_text: str, html: str) -> ExtractedMetadataField:
        if crawled_val and crawled_val.strip() and crawled_val.strip() != "UNKNOWN":
            return ExtractedMetadataField(
                value=crawled_val.strip(),
                source="crawled_metadata",
                method="direct",
                confidence=1.0
            )

        # Pattern: có hiệu lực thi hành từ ngày 01 tháng 01 năm 2024
        pattern = r'(?i)(?:có hiệu lực|hiệu lực thi hành|thi hành từ)\s+(?:từ\s+)?ngày\s+([0-9]{1,2})\s+tháng\s+([0-9]{1,2})\s+năm\s+([0-9]{4})'
        match = re.search(pattern, full_text)
        if match:
            d, m, y = match.group(1).zfill(2), match.group(2).zfill(2), match.group(3)
            return ExtractedMetadataField(
                value=f"{y}-{m}-{d}",
                source="full_text_clause",
                method="regex",
                confidence=0.90
            )

        return ExtractedMetadataField(value="UNKNOWN", source="none", method="none", confidence=0.0, reason="not_found")

    def _extract_enforced_date(self, crawled_val: Optional[str], full_text: str, html: str) -> ExtractedMetadataField:
        if crawled_val and crawled_val.strip() and crawled_val.strip() != "UNKNOWN":
            return ExtractedMetadataField(
                value=crawled_val.strip(),
                source="crawled_metadata",
                method="direct",
                confidence=1.0
            )
        return ExtractedMetadataField(value="UNKNOWN", source="none", method="none", confidence=0.0, reason="not_found")

    def _extract_expiry_date(self, crawled_val: Optional[str], full_text: str, html: str) -> ExtractedMetadataField:
        if crawled_val and crawled_val.strip() and crawled_val.strip() != "UNKNOWN":
            return ExtractedMetadataField(
                value=crawled_val.strip(),
                source="crawled_metadata",
                method="direct",
                confidence=1.0
            )
        return ExtractedMetadataField(value="UNKNOWN", source="none", method="none", confidence=0.0, reason="not_found")

    def _extract_issuing_body(self, crawled_val: Optional[str], header: str, html: str) -> ExtractedMetadataField:
        if crawled_val and crawled_val.strip() and crawled_val.strip() != "UNKNOWN":
            return ExtractedMetadataField(
                value=crawled_val.strip(),
                source="crawled_metadata",
                method="direct",
                confidence=1.0
            )

        patterns = [
            r'(?m)^\s*(CHÍNH PHỦ)\s*$',
            r'(?m)^\s*(QUỐC HỘI)\s*$',
            r'(?m)^\s*(ỦY BÀN THƯỜNG VỤ QUỐC HỘI)\s*$',
            r'(?m)^\s*(BỘ [A-Za-z0-9_À-ỹ\s]+)\s*$',
            r'(?m)^\s*(THỦ TƯỚNG CHÍNH PHỦ)\s*$',
            r'(?m)^\s*(HỘI ĐỒNG NHÂN DÂN[A-Za-z0-9_À-ỹ\s]*)\s*$',
            r'(?m)^\s*(ỦY BÀN NHÂN DÂN[A-Za-z0-9_À-ỹ\s]*)\s*$'
        ]

        for p in patterns:
            match = re.search(p, header)
            if match:
                return ExtractedMetadataField(
                    value=match.group(1).strip().title(),
                    source="full_text_header",
                    method="regex",
                    confidence=0.90
                )

        return ExtractedMetadataField(value="UNKNOWN", source="none", method="none", confidence=0.0, reason="not_found")

    def _extract_signer(self, crawled_val: Optional[str], footer: str, html: str) -> ExtractedMetadataField:
        if crawled_val and crawled_val.strip() and crawled_val.strip() != "UNKNOWN":
            return ExtractedMetadataField(
                value=crawled_val.strip(),
                source="crawled_metadata",
                method="direct",
                confidence=1.0
            )

        # Pattern near signature block
        pattern = r'(?i)(?:TM\.\s*CHÍNH PHỦ|THỦ TƯỚNG|BỘ TRƯỜNG|CHỦ TỊCH|KÝ THAY|KT\.)[^\n]*\n+([A-Za-z0-9_À-ỹ\s]{3,35})\b'
        match = re.search(pattern, footer)
        if match:
            signer_name = match.group(1).strip().title()
            # Clean up title artifacts
            if len(signer_name.split()) >= 2:
                return ExtractedMetadataField(
                    value=signer_name,
                    source="full_text_footer",
                    method="regex",
                    confidence=0.85
                )

        return ExtractedMetadataField(value="UNKNOWN", source="none", method="none", confidence=0.0, reason="not_found")

    def _extract_status(self, crawled_val: Optional[str], full_text: str, html: str) -> ExtractedMetadataField:
        if crawled_val and crawled_val.strip() and crawled_val.strip() != "UNKNOWN":
            return ExtractedMetadataField(
                value=crawled_val.strip(),
                source="crawled_metadata",
                method="direct",
                confidence=1.0
            )

        if "hết hiệu lực" in full_text.lower():
            return ExtractedMetadataField(
                value="Hết hiệu lực",
                source="full_text_keyword",
                method="regex",
                confidence=0.80
            )
        elif "bị thay thế" in full_text.lower():
            return ExtractedMetadataField(
                value="Bị thay thế",
                source="full_text_keyword",
                method="regex",
                confidence=0.80
            )

        return ExtractedMetadataField(
            value="UNKNOWN",
            source="none",
            method="none",
            confidence=0.0,
            reason="not_found_in_source"
        )
