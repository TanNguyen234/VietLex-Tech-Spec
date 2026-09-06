import pytest


def test_isolated_extraction_returns_text_and_typed_errors():
    from app.services.document_worker import extract_isolated
    from app.services.workspace_documents import DocumentExtractionError

    result = extract_isolated('sample.txt', 'text/plain', b'Contract content')
    assert result.clauses[0].text == 'Contract content'
    with pytest.raises(DocumentExtractionError, match='document_signature_mismatch'):
        extract_isolated('sample.pdf', 'application/pdf', b'bad')


def test_isolated_timeout_is_typed(monkeypatch):
    import subprocess
    from app.services import document_worker
    from app.services.workspace_documents import DocumentExtractionError

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('worker', 15)

    monkeypatch.setattr(document_worker.subprocess, 'run', timeout)
    with pytest.raises(DocumentExtractionError, match='document_processing_timeout'):
        document_worker.extract_isolated('sample.pdf', 'application/pdf', b'%PDF-')
