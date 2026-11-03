"""Source-backed regression using an exact local corpus slice, no provider calls."""
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ingestion.legal_text import DocumentMetadata
from app.services.primary_law_rescue import _planned_titles, _search_and_load


@pytest.mark.parametrize('query', [
    'Tôi thử việc hai tháng, lương công việc 12 triệu nhưng nhận 8,4 triệu; thời hạn và mức lương này có đúng không, nghỉ trước có phải báo không?',
    'Thử việc kế toán cần trình độ cao đẳng: thời gian tối đa bao lâu, lương tối thiểu bao nhiêu và có được nghỉ ngay không?',
])
def test_trial_work_multi_issue_rescue_preserves_each_requested_facet(query):
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/browser_audit_labor_20261026.json').read_text(encoding='utf-8'))
    body = fixture['content']
    document = SimpleNamespace(metadata=DocumentMetadata(**fixture['metadata']), content=body,
                               content_sha256=hashlib.sha256(body.encode()).hexdigest())
    browser = SimpleNamespace(search=lambda *args, **kwargs: [document.metadata],
                              get_document=lambda value: document)
    settings = SimpleNamespace(LLM_CONTEXT_MAX_TOKENS=720, FINAL_EVIDENCE_LIMIT=3,
                               QUERY_CHUNK_MAX_TOKENS=220, QUERY_CHUNK_OVERLAP_TOKENS=24)
    evidence, diagnostics = _search_and_load(query, _planned_titles(query), settings, browser, time.monotonic()+10)
    assert {chunk.article for chunk in evidence} == {'Điều 25', 'Điều 26', 'Điều 27'}
    assert any('85%' in chunk.text for chunk in evidence)
    assert any('không cần báo trước' in chunk.text for chunk in evidence)
    college_limit = next(chunk for chunk in evidence if '60 ngày' in chunk.text)
    assert college_limit.article == 'Điều 25'
    assert college_limit.clause is None
    assert len(college_limit.formatted_context().split()) < 720
    assert diagnostics['selected_context_tokens'] <= 720
    assert diagnostics['current_effect_status'] == 'unverified'


@pytest.mark.asyncio
async def test_followup_keeps_sparse_original_and_stage_counts_match_prompt(monkeypatch):
    from unittest.mock import AsyncMock
    from app.services import rag_pipeline
    from app.services.primary_law_rescue import PrimaryLawRescueResult
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/browser_audit_labor_20261026.json').read_text(encoding='utf-8'))
    body = fixture['content']
    document = SimpleNamespace(metadata=DocumentMetadata(**fixture['metadata']), content=body,
                               content_sha256=hashlib.sha256(body.encode()).hexdigest())
    browser = SimpleNamespace(search=lambda *args, **kwargs: [document.metadata], get_document=lambda value: document)
    settings = SimpleNamespace(USE_LEGACY_FREE_PIPELINE=False, CHAT_OFFICIAL_DEEP_READING_ENABLED=False,
                               LLM_CONTEXT_MAX_TOKENS=720, FINAL_EVIDENCE_LIMIT=3,
                               QUERY_CHUNK_MAX_TOKENS=220, QUERY_CHUNK_OVERLAP_TOKENS=24)
    current = 'Thế nếu công việc thử việc cần trình độ cao đẳng thì thời hạn, lương và nghỉ trước ra sao?'
    previous = 'Tôi thử việc hai tháng, lương công việc 12 triệu, nhận 8,4 triệu.'
    evidence, diagnostics = _search_and_load(current, _planned_titles(current), settings, browser, time.monotonic()+10)
    retrieval = AsyncMock(return_value=rag_pipeline.RetrievalOutcome(evidence=[], latency={}, diagnostics={}))
    monkeypatch.setattr(rag_pipeline, 'get_settings', lambda: settings)
    monkeypatch.setattr(rag_pipeline, 'retrieve_configured_legal_evidence', retrieval)
    monkeypatch.setattr(rag_pipeline, 'rescue_primary_law_evidence', AsyncMock(return_value=PrimaryLawRescueResult(tuple(evidence), diagnostics)))
    monkeypatch.setattr(rag_pipeline, 'corpus_evidence_covers_topic', lambda *args: True)
    sent = []
    async def generate(original, rewritten, contexts, *, current_question=None):
        assert previous in original and current in original
        assert current_question == current
        sent.extend(contexts)
        return rag_pipeline.LLMGenerationResult('test-only response', 'test', 'test')
    monkeypatch.setattr(rag_pipeline, 'generate_response_with_metadata', generate)
    _, contexts, latency = await rag_pipeline.run_advanced_rag(current, previous_user_query=previous)
    assert retrieval.await_args.args[1] == current
    assert previous in retrieval.await_args.args[0]
    assert contexts == sent
    stages = latency['retrieval_diagnostics']['context_stages']
    assert stages[-1]['stage'] == 'prompt'
    assert stages[-1]['count'] == len(contexts)
    assert stages[-1]['sha256'] == [hashlib.sha256(item.encode()).hexdigest() for item in contexts]
    assert '12 triệu' not in str(stages)
