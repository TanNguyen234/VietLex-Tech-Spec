import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
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
    combined_content = "\n".join(chunk["content"] for chunk in chunks)
    assert len(chunks) >= 1
    assert any(chunk["node_type"] == "article" for chunk in chunks)
    assert all(chunk["audit_id"] for chunk in chunks)
    assert all(chunk["source_block_ids"] for chunk in chunks)
    assert "Luật Đấu thầu 2023" in combined_content
    assert "22/2023/QH15" in combined_content
    assert "Chương I" in combined_content
    assert "Mục 1" in combined_content
    assert "Điều 1. Phạm vi điều chỉnh" in combined_content
