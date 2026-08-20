import importlib
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.ingestion.content_store import (
    ContentIntegrityError,
    StoredDocument,
)
from app.ingestion.legal_text import DocumentMetadata, EvidenceChunk
from app.services.remote_reranker import RerankOutcome, RerankResult


def _retrieval_module():
    return importlib.import_module("app.services.retrieval")


def _metadata(document_id: int) -> DocumentMetadata:
    return DocumentMetadata(
        document_id=document_id,
        document_number=f"{document_id}/2026/NĐ-CP",
        title="Quy định thuế thu nhập cá nhân",
        source_url=f"https://example.invalid/{document_id}",
        legal_type="Nghị định",
        legal_sectors="Thuế",
        issuing_authority="Chính phủ",
        issuance_date="2026-01-01",
    )


def _stored_document(document_id: int = 1) -> StoredDocument:
    return StoredDocument(
        metadata=_metadata(document_id),
        content=(
            "Chương I\nĐiều 1. Khấu trừ thuế\n"
            "1. Cá nhân được khấu trừ thuế thu nhập theo quy định."
        ),
        content_sha256="b" * 64,
        content_store_key=str(document_id),
        quality_flags=(),
    )


class FakePinecone:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            matches=[
                SimpleNamespace(
                    metadata={
                        "document_id": 1,
                        "content_store_key": "1",
                        "content_sha256": "b" * 64,
                        "dataset_revision": (
                            "4d4e10b201544e8a4c49a1d3fa496595a7d486d0"
                        ),
                    }
                )
            ]
        )


class FlakyPinecone(FakePinecone):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures

    def query(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) <= self.failures:
            raise TimeoutError("pinecone timeout")
        return super().query(**kwargs)


class InMemoryStore:
    def build_report(self):
        return SimpleNamespace(average_sparse_document_length=100.0)

    def get_many(self, document_ids: list[int]):
        assert document_ids == [1]
        return {1: _stored_document()}


class BrokenStore:
    def build_report(self):
        return SimpleNamespace(average_sparse_document_length=100.0)

    def get_many(self, document_ids: list[int]):
        raise ContentIntegrityError("hash mismatch")


class CountingStore:
    def __init__(self) -> None:
        self.requested_ids: list[int] = []

    def build_report(self):
        return SimpleNamespace(average_sparse_document_length=100.0)

    def get_many(self, document_ids: list[int]):
        self.requested_ids = list(document_ids)
        return {
            document_id: _stored_document(document_id)
            for document_id in document_ids
        }


class FakeReranker:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, list[str]]] = []

    async def rerank(self, query: str, documents: list[str], mode: str = "current", **kwargs):
        self.calls.append((query, documents))
        if self.error is not None:
            raise self.error
        return RerankOutcome(
            results=[RerankResult(index=0, score=0.95)],
            provider="qdrant",
            model="answerdotai/answerai-colbert-small-v1",
            latency=0.01,
        )


class FakeFts:
    def __init__(
        self,
        document_ids: list[int] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.document_ids = document_ids or []
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, limit: int) -> list[int]:
        self.calls.append((query, limit))
        if self.error is not None:
            raise self.error
        return self.document_ids[:limit]


def test_lexical_prefilter_bounds_remote_rerank_input() -> None:
    retrieval = _retrieval_module()
    chunks = [
        EvidenceChunk(
            document_id=index,
            document_number=f"{index}/QĐ",
            title="Thuế" if index == 2 else "Khác",
            source_url=f"https://example/{index}",
            heading_path="",
            article=None,
            clause=None,
            citation=f"{index}/QĐ",
            text=(
                "khấu trừ thuế thu nhập cá nhân"
                if index == 2
                else f"nội dung hành chính {index}"
            ),
            token_count=6,
        )
        for index in range(5)
    ]

    selected = retrieval.lexical_prefilter(
        "thuế thu nhập cá nhân",
        chunks,
        limit=3,
    )

    assert len(selected) == 3
    assert selected[0].document_id == 2


def test_candidate_selection_prefers_matches_and_preserves_document_diversity() -> None:
    retrieval = _retrieval_module()
    chunks = [
        EvidenceChunk(
            document_id=document_id,
            document_number=f"{document_id}/QĐ",
            title="Văn bản",
            source_url=f"https://example/{document_id}",
            heading_path="",
            article="Điều 1",
            clause=str(index + 1),
            citation=f"{document_id}/QĐ, Điều 1, Khoản {index + 1}",
            text=text,
            token_count=len(text.split()),
        )
        for document_id, index, text in (
            (1, 0, "thuế thu nhập cá nhân áp dụng"),
            (1, 1, "thuế thu nhập cá nhân bổ sung"),
            (2, 0, "khấu trừ thuế thu nhập"),
            (3, 0, "quy định hành chính khác"),
        )
    ]

    selected = retrieval.select_rerank_candidates(
        "thuế thu nhập cá nhân",
        chunks,
        limit=3,
        per_document_limit=1,
    )

    assert [chunk.document_id for chunk in selected] == [1, 2, 3]
    assert selected[0].text == "thuế thu nhập cá nhân áp dụng"


def test_candidate_selection_normalizes_query_once(monkeypatch) -> None:
    retrieval = _retrieval_module()
    calls: list[str] = []

    def capture(text: str) -> list[str]:
        calls.append(text)
        return text.casefold().split()

    monkeypatch.setattr(retrieval, "normalized_terms", capture)
    chunks = [
        EvidenceChunk(
            document_id=index,
            document_number=f"{index}/QĐ",
            title="Văn bản",
            source_url=f"https://example/{index}",
            heading_path="",
            article=None,
            clause=None,
            citation=f"{index}/QĐ",
            text=f"thuế nội dung {index}",
            token_count=3,
        )
        for index in range(4)
    ]

    retrieval.select_rerank_candidates(
        "thuế thu nhập",
        chunks,
        limit=3,
        per_document_limit=1,
    )

    assert calls == ["thuế thu nhập"]


def test_lexical_and_pinecone_ids_are_merged_without_duplicates() -> None:
    retrieval = _retrieval_module()

    assert retrieval.merge_document_ids(
        [431147, 7],
        [7, 9],
    ) == [431147, 7, 9]


def test_candidate_document_budget_preserves_lexical_and_semantic_sources() -> None:
    retrieval = _retrieval_module()

    selected = retrieval.balanced_document_ids(
        list(range(1, 13)),
        list(range(101, 113)),
        limit=12,
    )

    assert selected[:4] == [1, 101, 2, 102]
    assert len([item for item in selected if item < 100]) == 6
    assert len([item for item in selected if item > 100]) == 6


def test_ranked_evidence_respects_score_document_and_token_limits() -> None:
    retrieval = _retrieval_module()
    ranked = [
        (
            score,
            EvidenceChunk(
                document_id=document_id,
                document_number=f"{document_id}/QĐ",
                title="Văn bản",
                source_url=f"https://example/{document_id}",
                heading_path="",
                article="Điều 1",
                clause=str(position),
                citation=f"{document_id}/QĐ, Điều 1, Khoản {position}",
                text="nội dung " * token_count,
                token_count=token_count,
            ),
        )
        for position, (score, document_id, token_count) in enumerate(
            (
                (0.95, 1, 120),
                (0.90, 1, 120),
                (0.85, 2, 120),
                (0.80, 3, 120),
            ),
            start=1,
        )
    ]

    selected = retrieval.select_ranked_evidence(
        ranked,
        max_chunks=3,
        max_tokens=250,
        per_document_limit=1,
        min_score=0.05,
    )

    assert [chunk.document_id for chunk in selected] == [1, 2]
    assert sum(chunk.token_count for chunk in selected) == 240


@pytest.mark.asyncio
async def test_resolve_chunks_bounds_documents_and_chunks_before_reranking(
    monkeypatch,
) -> None:
    retrieval = _retrieval_module()
    settings = Settings(
        _env_file=None,
        RERANK_CANDIDATE_LIMIT=12,
        RERANK_PER_DOCUMENT_LIMIT=2,
    )
    store = CountingStore()
    retriever = retrieval.LegalRetriever(
        settings=settings,
        pinecone=object(),
        qdrant_inference=object(),
        reranker=FakeReranker(),
        fts_index=FakeFts(),
        content_store=store,
    )
    hits = [
        {
            "metadata": {
                "document_id": document_id,
                "content_store_key": str(document_id),
                "content_sha256": "b" * 64,
                "dataset_revision": settings.DATASET_REVISION,
            }
        }
        for document_id in range(1, 31)
    ]

    def many_chunks(metadata, _content, **_kwargs):
        return [
            EvidenceChunk(
                document_id=metadata.document_id,
                document_number=metadata.document_number,
                title=metadata.title,
                source_url=metadata.source_url,
                heading_path="",
                article=None,
                clause=None,
                citation=f"{metadata.document_number}:{index}",
                text=f"thuế thu nhập nội dung {index}",
                token_count=5,
            )
            for index in range(100)
        ]

    monkeypatch.setattr(retrieval, "chunk_document", many_chunks)

    chunks = await retriever._resolve_chunks(hits, [], "thuế thu nhập")

    assert len(store.requested_ids) == settings.RERANK_CANDIDATE_LIMIT
    assert len(chunks) <= (
        settings.RERANK_CANDIDATE_LIMIT
        * settings.RERANK_PER_DOCUMENT_LIMIT
    )


@pytest.mark.asyncio
async def test_hybrid_search_uses_rewrite_for_dense_and_original_for_sparse(
    monkeypatch,
) -> None:
    retrieval = _retrieval_module()
    settings = Settings(_env_file=None)
    pinecone = FakePinecone()
    dense_queries: list[str] = []
    sparse_queries: list[str] = []

    def capture_dense(_client, _settings, query: str):
        dense_queries.append(query)
        return [0.0] * settings.DENSE_VECTOR_SIZE

    monkeypatch.setattr(retrieval, "embed_query", capture_dense)
    retriever = retrieval.LegalRetriever(
        settings=settings,
        pinecone=pinecone,
        qdrant_inference=object(),
        reranker=FakeReranker(),
        fts_index=FakeFts(),
        content_store=InMemoryStore(),
    )
    original_encoder = retriever._sparse_encoder

    class CapturingSparseEncoder:
        def encode_query(self, query: str):
            sparse_queries.append(query)
            return original_encoder.encode_query(query)

    retriever._sparse_encoder = CapturingSparseEncoder()
    await retriever._hybrid_documents(
        "điều kiện khấu trừ thuế thu nhập cá nhân",
        "Điều 4 Nghị định 12/2026/NĐ-CP",
    )

    assert dense_queries == ["điều kiện khấu trừ thuế thu nhập cá nhân"]
    assert sparse_queries == ["Điều 4 Nghị định 12/2026/NĐ-CP"]


@pytest.mark.asyncio
async def test_retriever_uses_one_hybrid_query_and_returns_evidence(
    monkeypatch,
) -> None:
    retrieval = _retrieval_module()
    pinecone = FakePinecone()
    settings = Settings(_env_file=None)
    monkeypatch.setattr(
        retrieval,
        "embed_query",
        lambda *_args: [0.0] * settings.DENSE_VECTOR_SIZE,
    )
    retriever = retrieval.LegalRetriever(
        settings=settings,
        pinecone=pinecone,
        qdrant_inference=object(),
        reranker=FakeReranker(),
        fts_index=FakeFts(),
        content_store=InMemoryStore(),
    )
    evidence = await retriever.retrieve("điều kiện khấu trừ thuế")

    assert len(pinecone.calls) == 1
    assert pinecone.calls[0]["namespace"] == settings.PINECONE_NAMESPACE
    assert len(pinecone.calls[0]["vector"]) == settings.DENSE_VECTOR_SIZE
    assert pinecone.calls[0]["sparse_vector"]["indices"]
    assert pinecone.calls[0]["top_k"] == settings.RETRIEVAL_DOCUMENT_LIMIT
    assert evidence
    assert evidence[0].article == "Điều 1"


@pytest.mark.asyncio
async def test_detailed_retrieval_reports_real_stage_timings(
    monkeypatch,
) -> None:
    retrieval = _retrieval_module()
    settings = Settings(_env_file=None)
    monkeypatch.setattr(
        retrieval,
        "embed_query",
        lambda *_args: [0.0] * settings.DENSE_VECTOR_SIZE,
    )
    fts = FakeFts([1])
    retriever = retrieval.LegalRetriever(
        settings=settings,
        pinecone=FakePinecone(),
        qdrant_inference=object(),
        reranker=FakeReranker(),
        fts_index=fts,
        content_store=InMemoryStore(),
    )
    outcome = await retriever.retrieve_detailed(
        "khấu trừ thuế",
        sparse_query="Điều 1 khấu trừ thuế",
    )

    assert outcome.evidence
    assert outcome.error is None
    assert outcome.status == "ok"
    assert fts.calls == [
        ("Điều 1 khấu trừ thuế", settings.LEGAL_FTS_RESULT_LIMIT)
    ]
    assert outcome.diagnostics["lexical_document_ids"] == [1]
    assert outcome.diagnostics["rerank_provider"] == "qdrant"
    assert set(outcome.latency) == {
        "t_hybrid",
        "t_lexical",
        "t_resolve_chunk",
        "t_candidate",
        "t_rerank",
    }
    assert all(value >= 0 for value in outcome.latency.values())


@pytest.mark.asyncio
async def test_retriever_fails_closed_when_content_hash_is_invalid(
    monkeypatch,
) -> None:
    retrieval = _retrieval_module()
    settings = Settings(_env_file=None)
    monkeypatch.setattr(
        retrieval,
        "embed_query",
        lambda *_args: [0.0] * settings.DENSE_VECTOR_SIZE,
    )
    retriever = retrieval.LegalRetriever(
        settings=settings,
        pinecone=FakePinecone(),
        qdrant_inference=object(),
        reranker=FakeReranker(),
        fts_index=FakeFts(),
        content_store=BrokenStore(),
    )

    outcome = await retriever.retrieve_detailed("điều kiện khấu trừ thuế")
    assert outcome.evidence == []
    assert outcome.status == "retrieval_error"


@pytest.mark.asyncio
async def test_reranker_failure_is_not_reported_as_no_candidate(
    monkeypatch,
) -> None:
    retrieval = _retrieval_module()
    settings = Settings(_env_file=None)
    monkeypatch.setattr(
        retrieval,
        "embed_query",
        lambda *_args: [0.0] * settings.DENSE_VECTOR_SIZE,
    )
    retriever = retrieval.LegalRetriever(
        settings=settings,
        pinecone=FakePinecone(),
        qdrant_inference=object(),
        reranker=FakeReranker(error=RuntimeError("rerank unavailable")),
        fts_index=FakeFts(),
        content_store=InMemoryStore(),
    )

    outcome = await retriever.retrieve_detailed("khấu trừ thuế")

    assert outcome.status == "reranker_error"
    assert outcome.error == "rerank unavailable"


@pytest.mark.asyncio
async def test_optional_fts_failure_keeps_pinecone_retrieval_available(
    monkeypatch,
) -> None:
    retrieval = _retrieval_module()
    settings = Settings(_env_file=None)
    monkeypatch.setattr(
        retrieval,
        "embed_query",
        lambda *_args: [0.0] * settings.DENSE_VECTOR_SIZE,
    )
    retriever = retrieval.LegalRetriever(
        settings=settings,
        pinecone=FakePinecone(),
        qdrant_inference=object(),
        reranker=FakeReranker(),
        fts_index=FakeFts(error=RuntimeError("fts unavailable")),
        content_store=InMemoryStore(),
    )

    outcome = await retriever.retrieve_detailed("khấu trừ thuế")

    assert outcome.status == "ok"
    assert outcome.evidence
    assert outcome.diagnostics["lexical_error"] == "fts unavailable"


@pytest.mark.asyncio
async def test_pinecone_timeout_retries_before_succeeding(monkeypatch) -> None:
    retrieval = _retrieval_module()
    settings = Settings(
        _env_file=None,
        HYBRID_MAX_RETRIES=2,
        HYBRID_RETRY_BASE_SECONDS=0,
    )
    monkeypatch.setattr(
        retrieval,
        "embed_query",
        lambda *_args: [0.0] * settings.DENSE_VECTOR_SIZE,
    )
    pinecone = FlakyPinecone(failures=1)
    retriever = retrieval.LegalRetriever(
        settings=settings,
        pinecone=pinecone,
        qdrant_inference=object(),
        reranker=FakeReranker(),
        fts_index=FakeFts(),
        content_store=InMemoryStore(),
    )

    outcome = await retriever.retrieve_detailed("khấu trừ thuế")

    assert outcome.status == "ok"
    assert outcome.diagnostics["hybrid_query_attempts"] == 2


@pytest.mark.asyncio
async def test_hybrid_timeout_falls_back_to_lexical_results(
    monkeypatch,
) -> None:
    retrieval = _retrieval_module()
    settings = Settings(
        _env_file=None,
        HYBRID_MAX_RETRIES=1,
    )
    monkeypatch.setattr(
        retrieval,
        "embed_query",
        lambda *_args: [0.0] * settings.DENSE_VECTOR_SIZE,
    )
    retriever = retrieval.LegalRetriever(
        settings=settings,
        pinecone=FlakyPinecone(failures=10),
        qdrant_inference=object(),
        reranker=FakeReranker(),
        fts_index=FakeFts([1]),
        content_store=InMemoryStore(),
    )

    outcome = await retriever.retrieve_detailed("khấu trừ thuế")

    assert outcome.status == "partial_retrieval_error"
    assert outcome.evidence
    assert outcome.diagnostics["retrieval_mode"] == "lexical_fallback"
    assert outcome.diagnostics["hybrid_error_stage"] == "pinecone_query"
    assert outcome.error is not None


def test_structural_runtime_factory_uses_configured_reranker_mode(
    monkeypatch,
) -> None:
    retrieval = _retrieval_module()
    structural = importlib.import_module(
        "app.services.structural_retrieval"
    )
    sentinel = object()
    captured = {}
    settings = SimpleNamespace(
        CONTENT_STORE_PATH="content.sqlite3",
        LEGAL_FTS_PATH="fts.sqlite3",
        DATASET_REVISION="revision-1",
        STRUCTURAL_RERANKER_MODE="qdrant-only",
    )

    monkeypatch.setattr(retrieval, "_structural_retriever", None)
    monkeypatch.setattr(retrieval, "get_settings", lambda: settings)
    monkeypatch.setattr(retrieval, "ContentStore", lambda _path: object())
    monkeypatch.setattr(
        retrieval,
        "LegalFtsIndex",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        retrieval,
        "get_qdrant_inference_client",
        lambda: object(),
    )
    monkeypatch.setattr(
        retrieval,
        "get_remote_reranker",
        lambda: object(),
    )

    def build(*_args, **kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(structural, "build_structural_retriever", build)

    result = retrieval.get_structural_legal_retriever()

    assert result is sentinel
    assert captured["reranker_mode"] == "qdrant-only"
