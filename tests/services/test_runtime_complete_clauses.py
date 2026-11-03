from app.ingestion.legal_text import DocumentMetadata, chunk_document


def test_runtime_can_preserve_clause_without_changing_ingest_defaults():
    metadata = DocumentMetadata(document_id=1, document_number='1/2026/QH', title='Luật', source_url='https://example.gov.vn', legal_type='Luật', legal_sectors='', issuing_authority='', issuance_date=None)
    text = 'Điều 1. Đặt cọc\n1. ' + 'điều kiện ' * 130 + 'ngoại lệ cuối khoản.'
    original = chunk_document(metadata, text, max_tokens=220)
    runtime = chunk_document(metadata, text, max_tokens=220, preserve_unit_max_tokens=480)
    assert len(original) > 1
    assert len(runtime) == 1
    assert runtime[0].text.endswith('ngoại lệ cuối khoản.')
    assert runtime[0].token_count == len(runtime[0].text.split())


def test_oversized_clause_remains_bounded():
    metadata = DocumentMetadata(document_id=1, document_number='1/2026/QH', title='Luật', source_url='https://example.gov.vn', legal_type='Luật', legal_sectors='', issuing_authority='', issuance_date=None)
    chunks = chunk_document(metadata, 'Điều 1. Nội dung\n1. ' + 'quy định ' * 500, max_tokens=220, preserve_unit_max_tokens=480)
    assert all(chunk.token_count <= 220 for chunk in chunks)

