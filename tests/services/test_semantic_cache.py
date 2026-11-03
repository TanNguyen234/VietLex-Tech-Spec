import importlib
import time
from unittest.mock import Mock

import pytest

def _cache_module():
    return importlib.import_module("app.services.semantic_cache")


@pytest.fixture(autouse=True)
def disable_embedding_client(monkeypatch) -> None:
    cache = _cache_module()
    monkeypatch.setattr(cache, "_embedding_client", lambda: None)


def test_cache_identity_changes_with_corpus_revision() -> None:
    cache = _cache_module()

    first = cache.semantic_cache_point_id(
        "thuế thu nhập",
        "revision-a",
    )
    second = cache.semantic_cache_point_id(
        "thuế thu nhập",
        "revision-b",
    )

    assert first != second


@pytest.mark.parametrize('query', [
    'Vậy với mức lương công việc ở trên, 85% bằng bao nhiêu tiền? Công ty có được cho tôi thử việc lần hai cho chính công việc đó không?',
    'Với mức lương công việc đó thì 85% bằng bao nhiêu tiền?',
    'Thế nếu công việc cần trình độ cao đẳng thì sao?',
])
@pytest.mark.asyncio
async def test_context_dependent_queries_never_create_cache_clients(query, monkeypatch):
    cache = _cache_module()
    forbidden = Mock(side_effect=AssertionError('context-dependent cache/client call'))
    monkeypatch.setattr(cache, '_embedding_client', forbidden)
    monkeypatch.setattr(cache, 'embed_query', forbidden)
    monkeypatch.setattr(cache, 'get_pinecone_index', forbidden)
    assert not cache.is_cacheable_query(query)
    assert await cache.check_semantic_cache(query) is None
    await cache.save_to_semantic_cache(query, 'contextual answer', ['legal evidence'])
    forbidden.assert_not_called()


def test_cache_identity_normalizes_case_and_whitespace() -> None:
    cache = _cache_module()

    first = cache.semantic_cache_point_id("  CÂU   HỎI\n", "revision-a")
    second = cache.semantic_cache_point_id("câu hỏi", "revision-a")

    assert first == second


def test_pipeline_revision_changes_with_answer_prompt_version(monkeypatch) -> None:
    cache = _cache_module()
    original = cache.semantic_cache_pipeline_revision()

    monkeypatch.setattr(
        cache.settings,
        "ANSWER_PROMPT_VERSION",
        "legal-grounded-test-next",
    )

    assert cache.semantic_cache_pipeline_revision() != original


def test_pipeline_revision_changes_with_retrieval_backend(monkeypatch) -> None:
    cache = _cache_module()
    original = cache.semantic_cache_pipeline_revision()

    monkeypatch.setattr(
        cache.settings,
        "USE_LEGACY_FREE_PIPELINE",
        not cache.settings.USE_LEGACY_FREE_PIPELINE,
    )

    assert cache.semantic_cache_pipeline_revision() != original


def test_pipeline_revision_changes_with_official_supplement_setting(monkeypatch) -> None:
    cache = _cache_module()
    original = cache.semantic_cache_pipeline_revision()

    monkeypatch.setattr(
        cache.settings,
        "CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED",
        not cache.settings.CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED,
    )

    assert cache.semantic_cache_pipeline_revision() != original


def test_cache_filter_requires_exact_corpus_revision() -> None:
    cache = _cache_module()

    query_filter = cache.cache_revision_filter("revision-a", "pipeline-a")

    assert query_filter == {
        "$and": [
            {"corpus_revision": {"$eq": "revision-a"}},
            {"pipeline_revision": {"$eq": "pipeline-a"}},
            {"request_status": {"$eq": "ok"}},
        ]
    }


@pytest.mark.asyncio
async def test_cache_hit_requires_versioned_evidence_and_normalized_exact_query(monkeypatch) -> None:
    cache = _cache_module()
    contexts = ["[Luật 1, Điều 2]\nNội dung có căn cứ."]
    evidence_json = cache.serialize_evidence(contexts)
    payload = {
        "user_query": "  CÂU   HỎI\n",
        "bot_response": "Câu trả lời có căn cứ.",
        "expires_at": int(time.time()) + 3600,
        "corpus_revision": cache.settings.DATASET_REVISION,
        "pipeline_revision": cache.semantic_cache_pipeline_revision(),
        "request_status": "ok",
        "evidence_json": evidence_json,
        "evidence_sha256": cache.evidence_sha256(evidence_json),
    }

    monkeypatch.setattr(cache, "embed_query", lambda *_args: [0.1, 0.2])
    monkeypatch.setattr(
        cache,
        "get_pinecone_index",
        lambda: type(
            "Index",
            (),
            {"query": lambda *_args, **_kwargs: {"matches": [{"score": 0.99, "metadata": payload}]}},
        )(),
    )

    hit = await cache.check_semantic_cache("câu hỏi")

    assert hit is not None
    assert hit.response == "Câu trả lời có căn cứ."
    assert hit.contexts == contexts


@pytest.mark.asyncio
async def test_old_cache_hit_is_rejected_after_official_supplement_rollout(monkeypatch) -> None:
    cache = _cache_module()
    old_pipeline_revision = cache.semantic_cache_pipeline_revision()
    contexts = ["[Luật 45/2019/QH14, Điều 90]\\nQuy định chung về tiền lương."]
    evidence_json = cache.serialize_evidence(contexts)
    payload = {
        "user_query": "Lương thử việc có đúng không?",
        "bot_response": "Câu trả lời cũ.",
        "expires_at": int(time.time()) + 3600,
        "corpus_revision": cache.settings.DATASET_REVISION,
        "pipeline_revision": old_pipeline_revision,
        "request_status": "ok",
        "evidence_json": evidence_json,
        "evidence_sha256": cache.evidence_sha256(evidence_json),
    }
    monkeypatch.setattr(
        cache.settings,
        "CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED",
        not cache.settings.CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED,
    )
    monkeypatch.setattr(cache, "embed_query", lambda *_args: [0.1, 0.2])
    monkeypatch.setattr(
        cache,
        "get_pinecone_index",
        lambda: type(
            "Index",
            (),
            {"query": lambda *_args, **_kwargs: {"matches": [{"score": 0.99, "metadata": payload}]}},
        )(),
    )

    hit = await cache.check_semantic_cache("Lương thử việc có đúng không?")

    assert hit is None


@pytest.mark.asyncio
@pytest.mark.parametrize('previous_policy', [
    'situation-primary-law-official-deep-v4', 'source-quality-trial-facets-v5',
])
async def test_old_evidence_selection_policy_cache_hit_is_rejected(monkeypatch, previous_policy) -> None:
    cache = _cache_module()
    current_policy = cache.EVIDENCE_SELECTION_VERSION
    assert current_policy != previous_policy
    monkeypatch.setattr(
        cache,
        "EVIDENCE_SELECTION_VERSION",
        previous_policy,
        raising=False,
    )
    old_pipeline_revision = cache.semantic_cache_pipeline_revision()
    monkeypatch.setattr(cache, "EVIDENCE_SELECTION_VERSION", current_policy)
    new_pipeline_revision = cache.semantic_cache_pipeline_revision()
    contexts = ["[Old source]\nTest-only cached context."]
    evidence_json = cache.serialize_evidence(contexts)
    payload = {
        "user_query": "Thử việc có được trả lương và sau đó thế nào?",
        "bot_response": "Stale selection-policy answer.",
        "expires_at": int(time.time()) + 3600,
        "corpus_revision": cache.settings.DATASET_REVISION,
        "pipeline_revision": old_pipeline_revision,
        "request_status": "ok",
        "evidence_json": evidence_json,
        "evidence_sha256": cache.evidence_sha256(evidence_json),
    }
    monkeypatch.setattr(cache, "embed_query", lambda *_args: [0.1, 0.2])
    monkeypatch.setattr(
        cache,
        "get_pinecone_index",
        lambda: type(
            "Index",
            (),
            {
                "query": lambda *_args, **_kwargs: {
                    "matches": [{"score": 0.99, "metadata": payload}]
                }
            },
        )(),
    )

    hit = await cache.check_semantic_cache(
        "Thử việc có được trả lương và sau đó thế nào?"
    )

    assert old_pipeline_revision != new_pipeline_revision
    assert hit is None


@pytest.mark.asyncio
async def test_cache_rejects_a_different_legal_question_even_with_high_vector_score(
    monkeypatch,
) -> None:
    cache = _cache_module()
    contexts = ["[Luật 72/2020/QH14, Điều 39]\nQuy định gốc."]
    evidence_json = cache.serialize_evidence(contexts)
    payload = {
        "user_query": "Điều 39 Luật 72/2020/QH14 quy định giấy phép môi trường thế nào?",
        "bot_response": "Câu trả lời theo quy định gốc.",
        "expires_at": int(time.time()) + 3600,
        "corpus_revision": cache.settings.DATASET_REVISION,
        "pipeline_revision": cache.semantic_cache_pipeline_revision(),
        "request_status": "ok",
        "evidence_json": evidence_json,
        "evidence_sha256": cache.evidence_sha256(evidence_json),
    }
    monkeypatch.setattr(cache, "embed_query", lambda *_args: [0.1, 0.2])
    monkeypatch.setattr(
        cache,
        "get_pinecone_index",
        lambda: type(
            "Index",
            (),
            {"query": lambda *_args, **_kwargs: {"matches": [{"score": 0.99, "metadata": payload}]}},
        )(),
    )

    hit = await cache.check_semantic_cache(
        "Khoản 9 Điều 1 Luật 146/2025/QH15 sửa Điều 39 Luật 72/2020/QH14 thế nào?"
    )

    assert hit is None


@pytest.mark.asyncio
async def test_cache_hit_rejects_missing_or_tampered_evidence(monkeypatch) -> None:
    cache = _cache_module()
    base_payload = {
        "bot_response": "Câu trả lời cũ.",
        "expires_at": int(time.time()) + 3600,
        "corpus_revision": cache.settings.DATASET_REVISION,
        "pipeline_revision": cache.semantic_cache_pipeline_revision(),
        "request_status": "ok",
        "evidence_json": "[]",
        "evidence_sha256": cache.evidence_sha256("[]"),
    }
    monkeypatch.setattr(cache, "embed_query", lambda *_args: [0.1, 0.2])
    monkeypatch.setattr(
        cache,
        "get_pinecone_index",
        lambda: type(
            "Index",
            (),
            {"query": lambda *_args, **_kwargs: {"matches": [{"score": 0.99, "metadata": base_payload}]}},
        )(),
    )

    assert await cache.check_semantic_cache("Câu hỏi") is None


@pytest.mark.asyncio
async def test_cache_hit_rejects_official_external_context(
    monkeypatch,
) -> None:
    from app.services.evidence_presenter import (
        TrustedOfficialEvidenceContext,
    )

    cache = _cache_module()
    trusted = TrustedOfficialEvidenceContext(
        "[Nguồn chính thức ngoài VietLex · 45/2019/QH14]\n"
        "Nguồn: https://vanban.chinhphu.vn/default.aspx?docid=123\n"
        "Nguồn loại: official_external\n"
        "Hiệu lực pháp lý: unverified\n"
        f"SHA-256 nguồn: {'a' * 64}\n"
        "Thời điểm đọc: 2026-10-15T10:00:00+00:00\n"
        "Phương thức đọc: visible_html_text\n"
        "Tiêu đề: Bộ luật Lao động\n"
        "Mức lương thử việc ít nhất bằng 85%."
    )
    # A plain corpus string can contain the same display text without carrying
    # the validated reader marker.
    plain = str(trusted)
    contexts = [trusted, plain]
    evidence_json = cache.serialize_evidence(contexts)
    payload = {
        "user_query": "Câu hỏi chính xác",
        "bot_response": "Câu trả lời có căn cứ.",
        "expires_at": int(time.time()) + 3600,
        "corpus_revision": cache.settings.DATASET_REVISION,
        "pipeline_revision": cache.semantic_cache_pipeline_revision(),
        "request_status": "ok",
        "evidence_json": evidence_json,
        "evidence_sha256": cache.evidence_sha256(evidence_json),
    }
    monkeypatch.setattr(cache, "embed_query", lambda *_args: [0.1, 0.2])
    monkeypatch.setattr(
        cache,
        "get_pinecone_index",
        lambda: type(
            "Index",
            (),
            {"query": lambda *_args, **_kwargs: {"matches": [{"score": 0.99, "metadata": payload}]}},
        )(),
    )

    hit = await cache.check_semantic_cache("Câu hỏi chính xác")

    assert hit is None


@pytest.mark.asyncio
async def test_cache_rejects_expired_entry(monkeypatch) -> None:
    cache = _cache_module()
    contexts = ["[Luật 1, Điều 2]\nNội dung có căn cứ."]
    evidence_json = cache.serialize_evidence(contexts)
    payload = {
        "user_query": "Câu hỏi",
        "bot_response": "Câu trả lời cũ.",
        "expires_at": int(time.time()) - 1,
        "corpus_revision": cache.settings.DATASET_REVISION,
        "pipeline_revision": cache.semantic_cache_pipeline_revision(),
        "request_status": "ok",
        "evidence_json": evidence_json,
        "evidence_sha256": cache.evidence_sha256(evidence_json),
    }
    monkeypatch.setattr(cache, "embed_query", lambda *_args: [0.1, 0.2])
    monkeypatch.setattr(
        cache,
        "get_pinecone_index",
        lambda: type(
            "Index",
            (),
            {"query": lambda *_args, **_kwargs: {"matches": [{"score": 0.99, "metadata": payload}]}},
        )(),
    )

    assert await cache.check_semantic_cache("Câu hỏi") is None


@pytest.mark.asyncio
async def test_cache_rejects_legacy_entry_without_expiry(monkeypatch) -> None:
    cache = _cache_module()
    contexts = ["[Luật 1, Điều 2]\nNội dung có căn cứ."]
    evidence_json = cache.serialize_evidence(contexts)
    payload = {
        "user_query": "Câu hỏi",
        "bot_response": "Câu trả lời cũ.",
        "corpus_revision": cache.settings.DATASET_REVISION,
        "pipeline_revision": cache.semantic_cache_pipeline_revision(),
        "request_status": "ok",
        "evidence_json": evidence_json,
        "evidence_sha256": cache.evidence_sha256(evidence_json),
    }
    monkeypatch.setattr(cache, "embed_query", lambda *_args: [0.1, 0.2])
    monkeypatch.setattr(
        cache,
        "get_pinecone_index",
        lambda: type(
            "Index",
            (),
            {"query": lambda *_args, **_kwargs: {"matches": [{"score": 0.99, "metadata": payload}]}},
        )(),
    )

    assert await cache.check_semantic_cache("Câu hỏi") is None


@pytest.mark.asyncio
async def test_time_sensitive_query_skips_cache_embedding(monkeypatch) -> None:
    cache = _cache_module()
    embedding_client = Mock(return_value=None)
    embed_query = Mock(return_value=[0.1, 0.2])
    index = Mock()
    get_index = Mock(return_value=index)
    monkeypatch.setattr(cache, "_embedding_client", embedding_client)
    monkeypatch.setattr(cache, "embed_query", embed_query)
    monkeypatch.setattr(cache, "get_pinecone_index", get_index)

    assert await cache.check_semantic_cache(
        "Mức lương hiện hành theo pháp luật là bao nhiêu?"
    ) is None
    assert embedding_client.call_count == 0
    assert embed_query.call_count == 0
    assert get_index.call_count == 0
    assert index.query.call_count == 0


@pytest.mark.parametrize(
    "query",
    (
        "Quy định thử việc còn áp dụng không?",
        "Quy định thử việc đang áp dụng thế nào?",
        "Quy định thử việc vẫn áp dụng không?",
    ),
)
@pytest.mark.asyncio
async def test_application_tense_queries_skip_cache_lookup_and_save(
    query: str, monkeypatch
) -> None:
    cache = _cache_module()
    embedding_client = Mock(return_value=None)
    embed_query = Mock(return_value=[0.1, 0.2])
    upsert = Mock()
    index = Mock(upsert=upsert)
    get_index = Mock(return_value=index)
    monkeypatch.setattr(cache, "_embedding_client", embedding_client)
    monkeypatch.setattr(cache, "embed_query", embed_query)
    monkeypatch.setattr(cache, "get_pinecone_index", get_index)

    assert not cache.is_cacheable_query(query)
    assert await cache.check_semantic_cache(query) is None
    await cache.save_to_semantic_cache(query, "A current answer", ["legal evidence"])

    assert embedding_client.call_count == 0
    assert embed_query.call_count == 0
    assert get_index.call_count == 0
    assert upsert.call_count == 0


@pytest.mark.asyncio
async def test_saving_official_external_context_skips_cache(monkeypatch) -> None:
    from app.services.evidence_presenter import TrustedOfficialEvidenceContext

    cache = _cache_module()
    embedding_client = Mock(return_value=None)
    embed_query = Mock(return_value=[0.1, 0.2])
    upsert = Mock()
    index = Mock(upsert=upsert)
    get_index = Mock(return_value=index)
    monkeypatch.setattr(cache, "_embedding_client", embedding_client)
    monkeypatch.setattr(cache, "embed_query", embed_query)
    monkeypatch.setattr(cache, "get_pinecone_index", get_index)

    await cache.save_to_semantic_cache(
        "Câu hỏi chính xác",
        "Câu trả lời có căn cứ.",
        [
            TrustedOfficialEvidenceContext(
                "[Nguồn chính thức ngoài VietLex · 45/2019/QH14]\n"
                "Nguồn: https://vanban.chinhphu.vn/default.aspx?docid=123\n"
                "Nguồn loại: official_external\n"
                "Hiệu lực pháp lý: unverified\n"
                f"SHA-256 nguồn: {'a' * 64}\n"
                "Thời điểm đọc: 2026-10-15T10:00:00+00:00\n"
                "Phương thức đọc: visible_html_text\n"
                "Tiêu đề: Bộ luật Lao động\n"
                "Mức lương thử việc ít nhất bằng 85%."
            )
        ],
    )

    assert embedding_client.call_count == 0
    assert embed_query.call_count == 0
    assert get_index.call_count == 0
    assert upsert.call_count == 0


@pytest.mark.asyncio
async def test_saved_cache_entry_expires_after_configured_ttl(monkeypatch) -> None:
    cache = _cache_module()
    embed_query = Mock(return_value=[0.1, 0.2])
    upsert = Mock()
    monkeypatch.setattr(cache, "embed_query", embed_query)
    monkeypatch.setattr(
        cache,
        "get_pinecone_index",
        lambda: type("Index", (), {"upsert": upsert})(),
    )
    started_at = int(time.time())

    await cache.save_to_semantic_cache(
        "Câu hỏi",
        "Câu trả lời có căn cứ.",
        ["[Luật 1, Điều 2]\nNội dung có căn cứ."],
    )

    assert upsert.call_count == 1
    metadata = upsert.call_args.kwargs["vectors"][0]["metadata"]
    assert metadata["expires_at"] == started_at + cache.CACHE_TTL_SECONDS or (
        metadata["expires_at"] == int(time.time()) + cache.CACHE_TTL_SECONDS
    )

@pytest.mark.parametrize('change', ['source', 'public_config'])
def test_cache_revision_separates_real_runtime_snapshots(tmp_path, change):
    from app.services.runtime_identity import runtime_identity
    cache = _cache_module()
    source = tmp_path / 'module.py'
    source.write_text('VALUE = 1\n', encoding='utf-8')
    first_identity = runtime_identity(cache.settings, source_root=tmp_path)
    first = cache.semantic_cache_pipeline_revision(identity=first_identity)
    if change == 'source':
        source.write_text('VALUE = 2\n', encoding='utf-8')
        next_settings = cache.settings
    else:
        next_settings = cache.settings.model_copy(update={
            'PUBLIC_NEMO_DEFAULT_ENABLED': not cache.settings.PUBLIC_NEMO_DEFAULT_ENABLED,
        })
    second_identity = runtime_identity(next_settings, source_root=tmp_path)
    second = cache.semantic_cache_pipeline_revision(identity=second_identity)
    assert first != second
    assert cache.cache_revision_filter('same-corpus', first) != cache.cache_revision_filter('same-corpus', second)
    assert cache.semantic_cache_point_id('same question', 'same-corpus', first) != cache.semantic_cache_point_id('same question', 'same-corpus', second)


def test_unknown_loaded_source_cannot_become_shared_cache_identity(tmp_path):
    from app.services.runtime_identity import runtime_identity
    cache = _cache_module()
    observed = runtime_identity(cache.settings, source_root=tmp_path)
    observed['app_source_sha256'] = 'unknown'
    with pytest.raises(ValueError, match='runtime_identity_unavailable'):
        cache.semantic_cache_pipeline_revision(identity=observed)
