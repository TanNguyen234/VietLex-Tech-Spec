import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import pytest
from app.ingestion.parser import parse_legal_document_with_context

def test_parse_legal_document_with_context():
    doc_text = """
    Chương I
    QUY ĐỊNH CHUNG
    Mục 1
    PHẠM VI ĐIỀU CHỈNH
    Điều 1. Phạm vi điều chỉnh
    Luật này quy định về hoạt động đấu thầu.
    """
    metadata = {
        "title": "Luật Đấu thầu 2023",
        "official_number": "22/2023/QH15"
    }
    chunks = parse_legal_document_with_context(doc_text, metadata)
    assert len(chunks) == 1
    assert "Luật Đấu thầu 2023" in chunks[0]["content"]
    assert "22/2023/QH15" in chunks[0]["content"]
    assert "Chương I" in chunks[0]["content"]
    assert "Mục 1" in chunks[0]["content"]
    assert "Điều 1. Phạm vi điều chỉnh" in chunks[0]["content"]
