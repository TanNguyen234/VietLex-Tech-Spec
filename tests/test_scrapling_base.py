import os
import pytest
from app.ingestion.schemas import LegalDocumentSchema
from app.ingestion.scrapling_base import get_output_dir_for_source, BaseLegalCrawler

def test_legal_document_schema_validation():
    data = {
        "source_id": "12345",
        "source": "vbpl.vn",
        "url": "https://vbpl.vn/tw/Pages/vbpq-todan.aspx?ItemID=12345",
        "title": "Luật Công chứng 2024",
        "document_type": "Luật",
        "official_number": "25/2024/QH15",
        "issued_date": "2024-11-20",
        "effective_date": "2025-07-01",
        "full_text": "Nội dung luật...",
        "attributes": {"Cơ quan ban hành": "Quốc hội"},
        "relations": {"Văn bản căn cứ": ["https://vbpl.vn/tw/Pages/vbpq-todan.aspx?ItemID=11111"]}
    }
    doc = LegalDocumentSchema(**data)
    assert doc.source == "vbpl.vn"
    assert doc.official_number == "25/2024/QH15"

def test_output_directory_routing():
    vbpl_dir = get_output_dir_for_source("vbpl.vn")
    vietlaw_dir = get_output_dir_for_source("vietlaw.quochoi.vn")
    moj_dir = get_output_dir_for_source("moj.gov.vn")

    assert vbpl_dir.endswith(os.path.join("data", "scrapling_raw", "vbpl"))
    assert vietlaw_dir.endswith(os.path.join("data", "scrapling_raw", "vietlaw"))
    assert moj_dir.endswith(os.path.join("data", "scrapling_raw", "moj"))
    assert os.path.exists(vbpl_dir)
    assert os.path.exists(vietlaw_dir)
    assert os.path.exists(moj_dir)
