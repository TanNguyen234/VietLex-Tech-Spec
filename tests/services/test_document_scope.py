from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.ingestion.legal_text import DocumentMetadata


@pytest.mark.asyncio
async def test_document_scope_never_calls_corpus_retrieval(monkeypatch):
    from app.services import rag_pipeline
    from app.services.document_scope import document_evidence

    document = SimpleNamespace(
        metadata=DocumentMetadata(7, "45/2019/QH14", "Bộ luật Lao động", "https://vbpl.vn/7", "Luật", "", "Quốc hội", None),
        content="Điều 25. Thử việc\nThời gian thử việc tối đa 60 ngày.",
    )
    outcome = document_evidence("Điều 25 thử việc", document)
    corpus = AsyncMock(side_effect=AssertionError("scope escaped"))
    monkeypatch.setattr(rag_pipeline, "retrieve_configured_legal_evidence", corpus)
    generation = AsyncMock(return_value=SimpleNamespace(text="Theo Điều 25", status="success", observed=False,
        observed_provider="none", observed_model="none", project=None, location=None, provider_latency_ms=None,
        fallback_used=False, primary_error_kind=None, prompt_token_count=None, output_token_count=None,
        thought_token_count=None, total_token_count=None))
    monkeypatch.setattr(rag_pipeline, "generate_response_with_metadata", generation)
    _, contexts, _ = await rag_pipeline.run_advanced_rag("Điều 25 thử việc", scoped_outcome=outcome)
    assert contexts and "60 ngày" in contexts[0]
    from app.services.evidence_presenter import present_context
    assert present_context(contexts[0]).document_id == 7
    assert all(item.document_id == 7 for item in outcome.evidence)
    corpus.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_article_does_not_generate_or_expand_scope(monkeypatch):
    from app.services import rag_pipeline
    from app.services.document_scope import document_evidence

    document = SimpleNamespace(
        metadata=DocumentMetadata(7, "45/2019/QH14", "Luật", "https://vbpl.vn/7", "Luật", "", "", None),
        content="Điều 25. Thử việc\nThử việc tối đa 60 ngày.",
    )
    outcome = document_evidence("Điều 99", document)
    assert not outcome.evidence
    generation = AsyncMock(side_effect=AssertionError("empty evidence must not generate"))
    monkeypatch.setattr(rag_pipeline, "generate_response_with_metadata", generation)
    monkeypatch.setattr(rag_pipeline, "retrieve_configured_legal_evidence", generation)
    text, contexts, _ = await rag_pipeline.run_advanced_rag("Điều 99", scoped_outcome=outcome)
    assert not contexts
    assert "trong văn bản này" in text
    generation.assert_not_awaited()

def test_document_scope_works_without_offline_pyvi_dependency(monkeypatch):
    import sys
    from app.services.document_scope import document_evidence

    # Production's hash-locked online package intentionally excludes PyVi.
    monkeypatch.setitem(sys.modules, 'pyvi', None)
    document = SimpleNamespace(
        metadata=DocumentMetadata(333670, '45/2019/QH14', 'Bộ luật Lao động', '', 'Luật', '', '', None),
        content='Điều 25. Thời gian thử việc\n1. Không quá 180 ngày.\n2. Không quá 60 ngày đối với công việc cần trình độ cao đẳng.',
    )
    outcome = document_evidence('Khoản 2 Điều 25 thời gian thử việc cao đẳng', document)
    assert outcome.evidence
    assert all(chunk.document_id == 333670 for chunk in outcome.evidence)
    assert all(chunk.clause == '2' for chunk in outcome.evidence)
    assert '60 ngày' in outcome.evidence[0].text
