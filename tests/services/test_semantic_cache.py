import importlib

import pytest

def _cache_module():
    return importlib.import_module("app.services.semantic_cache")


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
async def test_cache_hit_requires_versioned_nonempty_evidence(monkeypatch) -> None:
    cache = _cache_module()
    contexts = ["[Luật 1, Điều 2]\nNội dung có căn cứ."]
    evidence_json = cache.serialize_evidence(contexts)
    payload = {
        "bot_response": "Câu trả lời có căn cứ.",
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

    hit = await cache.check_semantic_cache("Câu hỏi")

    assert hit is not None
    assert hit.response == "Câu trả lời có căn cứ."
    assert hit.contexts == contexts


@pytest.mark.asyncio
async def test_cache_hit_rejects_missing_or_tampered_evidence(monkeypatch) -> None:
    cache = _cache_module()
    base_payload = {
        "bot_response": "Câu trả lời cũ.",
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
