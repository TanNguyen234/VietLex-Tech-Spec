import pytest
from app.ingestion.parser import parse_legal_document

def test_parse_legal_document_articles():
    sample_text = """Chương I\nNHỮNG QUY ĐỊNH CHUNG\n\nĐiều 1. Phạm vi điều chỉnh\nBộ luật này quy định tiêu chuẩn lao động...\n\nĐiều 2. Đối tượng áp dụng\n1. Người lao động, người học nghề..."""
    chunks = parse_legal_document(sample_text)
    assert len(chunks) == 2
    assert chunks[0]["article"] == "1"
    assert "Phạm vi điều chỉnh" in chunks[0]["content"] or "Điều 1" in chunks[0]["content"]
    assert chunks[1]["article"] == "2"

def test_parse_legal_document_chapters():
    sample_text = """Chương I\nQUY ĐỊNH CHUNG\n\nĐiều 1. Phạm vi\nNội dung 1\n\nChương II\nĐIỀU KHOẢN KHÁC\n\nĐiều 2. Áp dụng\nNội dung 2"""
    chunks = parse_legal_document(sample_text)
    assert len(chunks) == 2
    assert chunks[0]["chapter"] == "I"
    assert chunks[1]["chapter"] == "II"
