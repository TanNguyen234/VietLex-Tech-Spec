from app.services.source_quality import assess_source_quality


def test_confirmed_paywall_boilerplate_is_not_usable_as_evidence():
    body = ('Article 1. Rule.\nBạn phải đăng nhập hoặc đăng ký Thành Viên TVPL Pro '
            'để sử dụng được đầy đủ các tiện ích gia tăng liên quan đến nội dung TCVN.')
    result = assess_source_quality(body)
    assert not result['usable_as_evidence']
    assert result['issues'] == ['commercial_boilerplate']


def test_clean_excerpt_of_known_contaminated_document_is_still_quarantined():
    result = assess_source_quality('Article 1. A clean-looking excerpt.',
        source_sha256='c65bce6a4c27b72396b5c53270f0994e80be69000ae76e7102e746ccfd492b61')
    assert not result['usable_as_evidence']
    assert result['issues'] == ['known_contaminated_source']


def test_brand_or_phone_alone_does_not_reject_legal_text():
    assert assess_source_quality('Điều 1. Tên doanh nghiệp TVPL Pro, điện thoại 0906.')['usable_as_evidence']


def test_translation_is_labeled_without_claiming_it_is_invalid():
    body = 'THE NATIONAL ASSEMBLY\nLAW\nArticle 1. Rules.'
    result = assess_source_quality(body)
    assert result['language_hint'] == 'english'
    assert result['usable_as_evidence']
    assert 'translation_unverified' in result['warnings']


def test_quality_assessment_preserves_exact_input_and_is_deterministic():
    text = 'Điều 26. 85% mức lương. Trừ trường hợp ngày 01/01/2026.'
    assert assess_source_quality(text) == assess_source_quality(text)
    assert assess_source_quality(text)['issues'] == []


def test_scoped_document_rejects_known_contamination_before_chunk_selection():
    from app.services.document_scope import document_evidence
    from app.ingestion.legal_text import DocumentMetadata
    from types import SimpleNamespace
    body = ('Điều 1. Quy định về tiền lương.\nĐiều 2.\n'
            'Bạn phải đăng nhập hoặc đăng ký Thành Viên TVPL Pro để sử dụng tiện ích.')
    document = SimpleNamespace(metadata=DocumentMetadata(1, 'TEST', 'Test fixture', '', '', '', '', None),
                               content=body)
    result = document_evidence('Điều 1', document)
    assert result.evidence == []
    assert result.diagnostics['source_quality']['issues'] == ['commercial_boilerplate']


def test_reader_discloses_contamination_without_rewriting_body(monkeypatch):
    from app.api import legal_routes
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from unittest.mock import AsyncMock
    from app.ingestion.legal_text import DocumentMetadata
    metadata = DocumentMetadata(7, '38/2019/QH14', 'Luật Quản lý thuế 2019',
                                'https://example.invalid/7', 'Luật', '', '', '2019-06-13')
    body = ('THE NATIONAL ASSEMBLY\nArticle 1.\nBạn phải đăng nhập hoặc đăng ký Thành Viên TVPL Pro '
            'để sử dụng được đầy đủ các tiện ích gia tăng liên quan đến nội dung TCVN.')
    monkeypatch.setattr(legal_routes, 'browser', SimpleNamespace(
        get_document=lambda value: SimpleNamespace(metadata=metadata, content=body)))
    monkeypatch.setattr(legal_routes, 'registry_records_batch', AsyncMock(return_value=[]))
    app = FastAPI()
    app.include_router(legal_routes.router)
    client = TestClient(app)
    response = client.get('/documents/7')
    assert response.status_code == 200
    assert 'data-source-quality="flagged"' in response.text
    assert 'Nội dung có dấu hiệu lẫn thông báo thương mại' in response.text
    assert 'TVPL Pro' in response.text
