"""Tiện ích hiển thị cho kết quả tra cứu: cảnh báo tuổi văn bản, lọc lĩnh vực, trích dẫn chuẩn.

Không suy ra hiệu lực pháp lý. VietLex chưa có trạng thái hiệu lực đã xác minh cho mọi văn bản,
nên mọi hàm ở đây chỉ nói "chưa xác minh" hoặc cảnh báo theo ngày ban hành.
"""

from __future__ import annotations

import re
from datetime import date

OLD_DOCUMENT_YEARS = 10
_YEAR = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def _year_of(issuance_date: str | None) -> int | None:
    if not issuance_date:
        return None
    match = _YEAR.search(str(issuance_date))
    return int(match.group(1)) if match else None


def currency_note(issuance_date: str | None, *, today: date | None = None) -> str:
    """Ghi chú hiển thị cạnh mỗi kết quả: luôn nói rõ chưa xác minh hiệu lực."""
    if not str(issuance_date or "").strip():
        return "Chưa có ngày ban hành · chưa xác minh hiệu lực"
    year = _year_of(issuance_date)
    if year is None:
        return "Ngày ban hành không đọc được · chưa xác minh hiệu lực"
    reference_year = (today or date.today()).year
    note = f"Ban hành {year} · chưa xác minh hiệu lực hiện hành"
    if reference_year - year > OLD_DOCUMENT_YEARS:
        note += f" · Cũ hơn {OLD_DOCUMENT_YEARS} năm: đối chiếu hiệu lực và văn bản sửa đổi trước khi trích dẫn"
    return note


def sector_matches(legal_sectors: str | None, wanted: str | None) -> bool:
    """Lọc lĩnh vực theo chuỗi con, không phân biệt hoa thường. Rỗng nghĩa là không lọc."""
    needle = (wanted or "").strip().casefold()
    if not needle:
        return True
    return needle in (legal_sectors or "").casefold()


def format_citation(
    *,
    title: str,
    document_number: str,
    issuing_authority: str | None,
    issuance_date: str | None,
    source_url: str | None,
) -> str:
    """Trích dẫn một dòng theo thứ tự: tên văn bản, số hiệu, cơ quan, ngày ban hành, nguồn."""
    parts = [title.strip(), f"số hiệu {document_number.strip()}"]
    if issuing_authority:
        parts.append(issuing_authority.strip())
    if issuance_date:
        parts.append(f"ban hành {str(issuance_date).strip()[:10]}")
    citation = ", ".join(part for part in parts if part)
    if source_url:
        citation += f". Nguồn: {source_url.strip()}"
    return citation
