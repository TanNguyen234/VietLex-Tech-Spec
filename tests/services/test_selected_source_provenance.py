from app.services.research_analysis import build_selected_evidence_prompt


def test_synthesis_receives_saved_source_identity_and_page_scope():
    evidence = [{
        'evidence_id': 'official-1', 'excerpt': 'Nội dung nguồn.',
        'source_url': 'https://vanban.chinhphu.vn/?docid=1',
        'source_sha256': 'a' * 64, 'document_sha256': 'b' * 64,
        'retrieved_at': '2026-10-19T00:00:00+00:00',
        'extraction_method': 'pdf_text', 'page_numbers': [2], 'page_window': [1, 5],
        'legal_effect_status': 'unverified',
    }]
    prompt = build_selected_evidence_prompt('Tổng hợp nguồn đã chọn', evidence)
    assert 'a' * 64 in prompt and 'b' * 64 in prompt
    assert 'page_numbers' in prompt and '[2]' in prompt
    assert 'page_window' in prompt and '[1, 5]' in prompt
    assert 'pdf_text' in prompt
