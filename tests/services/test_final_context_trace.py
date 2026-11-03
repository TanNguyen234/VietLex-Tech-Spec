from types import SimpleNamespace

from app.services.research_presenter import sanitize_retrieval_trace, build_public_retrieval_trace


def test_final_count_is_after_filter_not_retrieval_selection():
    result = sanitize_retrieval_trace(
        {'retrieval_diagnostics': {'stage_trace': SimpleNamespace(final_evidence_chunks=[1, 2, 3])}},
        [], SimpleNamespace(), query='question', cached=False,
    )
    assert result['candidate_counts']['retrieval_selected_chunks'] == 3
    assert result['candidate_counts']['final_evidence_chunks'] == 0
    assert result['prompt_context_count'] == 0


def test_context_stage_trace_keeps_hashes_counts_but_no_bodies():
    result = sanitize_retrieval_trace(
        {'retrieval_diagnostics': {'context_stages': [
            {'stage': 'prompt', 'count': 1, 'sha256': ['a' * 64], 'text': 'private source'},
        ]}}, ['one context'], SimpleNamespace(), query='question', cached=False,
    )
    assert result['context_stages'] == [{'stage': 'prompt', 'count': 1, 'sha256': ['a' * 64]}]
    assert 'private source' not in str(result)


def test_legacy_candidate_counts_are_labeled_as_retrieval_selection():
    result = build_public_retrieval_trace({'retrieval_trace': {
        'candidate_counts': {'final_evidence_chunks': 3}, 'final_evidence_count': 0,
    }})
    assert result['candidate_counts'] == {'retrieval_selected_chunks': 3}
    assert result['prompt_context_count'] is None
    assert result['count_semantics'] == 'legacy'


def test_recorded_prompt_count_survives_history_source_redaction():
    result = build_public_retrieval_trace({'retrieval_trace': {
        'prompt_context_count': 2, 'count_semantics': 'prompt-contexts-v1',
        'context_stages': [{'stage': 'prompt', 'count': 2, 'sha256': []}],
    }, 'contexts': ['persisted corpus excerpt']})
    assert result['prompt_context_count'] == 2
    assert result['displayed_evidence_count'] == 1


def test_cache_hit_does_not_claim_a_new_prompt_or_retrieval():
    result = sanitize_retrieval_trace({}, ['cached excerpt'], SimpleNamespace(),
                                     query='question', cached=True)
    assert result['prompt_context_count'] == 0
    assert result['count_semantics'] == 'cache-response-v1'
    assert result['candidate_counts'] == {'cache_response_contexts': 1}
    public = build_public_retrieval_trace({'retrieval_trace': result, 'cached': True})
    assert public['count_semantics'] == 'cache-response-v1'
    assert public['prompt_context_count'] == 0


def test_display_count_matches_emitted_limit_for_deep_contexts():
    result = build_public_retrieval_trace({'retrieval_trace': {
        'count_semantics': 'prompt-contexts-v1', 'prompt_context_count': 16,
    }, 'contexts': ['context'] * 16})
    assert result['prompt_context_count'] == 16
    assert result['displayed_evidence_count'] == len(result['evidence']) == 10
