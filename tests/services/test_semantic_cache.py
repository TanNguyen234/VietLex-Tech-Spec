import importlib

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

    query_filter = cache.cache_revision_filter("revision-a")

    assert query_filter == {"corpus_revision": {"$eq": "revision-a"}}
