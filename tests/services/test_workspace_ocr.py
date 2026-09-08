from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json

import pytest
from pypdf import PdfWriter


def pdf_bytes(pages=1):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=100, height=100)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


@pytest.fixture
def ocr(monkeypatch):
    from app.services import workspace_ocr as service
    response = SimpleNamespace(text=json.dumps({'pages':[{'page':1,'text':'Điều 1\nThanh toán ngày 15/09/2026.'}]}), finish_reason='STOP', prompt_token_count=20, output_token_count=30, thought_token_count=0, total_token_count=50,
                               metadata=SimpleNamespace(provider='google_vertex_ai', model='test-model', latency_ms=10))
    generate = AsyncMock(return_value=response)
    monkeypatch.setattr(service, 'get_vertex_provider', lambda: SimpleNamespace(generate=generate))
    return service, generate


@pytest.mark.asyncio
async def test_ocr_keeps_page_hash_and_provider_provenance(ocr):
    service, generate = ocr
    payload = pdf_bytes()
    result = await service.extract_ocr_document('scan.pdf', 'application/pdf', payload)
    assert result.clauses[0].page == 1
    assert '15/09/2026' in result.clauses[0].text
    assert result.extraction_method == 'vertex_ocr'
    assert result.ocr_model == 'test-model'
    assert result.sha256 == __import__('hashlib').sha256(payload).hexdigest()
    assert generate.await_args.kwargs['pdf_bytes'] == payload
    assert generate.await_args.kwargs['max_retries'] == 0


@pytest.mark.asyncio
async def test_ocr_rejects_large_page_count_before_provider(ocr):
    service, generate = ocr
    with pytest.raises(service.DocumentExtractionError, match='ocr_page_limit'):
        await service.extract_ocr_document('scan.pdf','application/pdf',pdf_bytes(6))
    generate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('pages', [[{'page':2,'text':'bad'}], [{'page':1,'text':'a'},{'page':1,'text':'duplicate'}], []])
async def test_ocr_requires_exact_page_coverage(ocr, pages):
    service, generate = ocr
    generate.return_value.text = json.dumps({'pages':pages})
    with pytest.raises(service.DocumentExtractionError, match='ocr_invalid_response'):
        await service.extract_ocr_document('scan.pdf','application/pdf',pdf_bytes())


@pytest.mark.asyncio
async def test_truncated_ocr_is_not_saved_as_complete_text(ocr):
    service, generate = ocr
    generate.return_value.finish_reason = 'MAX_TOKENS'
    with pytest.raises(service.DocumentExtractionError, match='ocr_incomplete'):
        await service.extract_ocr_document('scan.pdf','application/pdf',pdf_bytes())


@pytest.mark.asyncio
async def test_ocr_provider_failure_is_typed_and_not_retried(ocr):
    service, generate = ocr
    generate.side_effect = TimeoutError('private provider message')
    with pytest.raises(service.DocumentExtractionError, match='ocr_timeout'):
        await service.extract_ocr_document('scan.pdf','application/pdf',pdf_bytes())
    generate.assert_awaited_once()
