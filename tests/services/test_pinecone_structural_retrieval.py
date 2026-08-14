from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.ingestion.structural_pinecone import PineconeStructuralContract
from app.services.pinecone_structural_retrieval import PineconeStructuralRetriever
from app.services.remote_reranker import RerankOutcome, RerankResult


def _fields(record_id: str, *, document_id: int = 42) -> dict[str, object]:
    body = f"Nội dung của {record_id}."
    return {
        "body": body,
        "document_id": document_id,
        "document_number": "01/2024/QH15",
        "title": "Luật thử nghiệm",
        "source_url": f"https://example.test/{document_id}",
        "legal_type": "Luật",
        "issuing_authority": "Quốc hội",
        "issuance_date": "2024-01-01",
        "article": "Điều 1",
        "clause": "Khoản 1",
        "heading_path": "Điều 1 > Khoản 1",
        "citation": "Điều 1 khoản 1 Luật thử nghiệm",
        "token_count": 5,
        "dataset_revision": "revision-1",
        "content_sha256": "a" * 64,
        "chunk_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "inference_text_sha256": "b" * 64,
    }


def _hit(record_id: str, score: float = 0.9):
    return SimpleNamespace(_id=record_id, _score=score, fields=_fields(record_id))


class FakeIndex:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        hits = [_hit("exact-1")] if kwargs.get("filter") else [_hit("dense-1")]
        return SimpleNamespace(
            result=SimpleNamespace(hits=hits),
            usage=SimpleNamespace(embed_total_tokens=12, read_units=1),
        )


class FakeFts:
    def __init__(self, ids: list[int] | None = None) -> None:
        self.ids = ids or []
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, limit: int):
        self.calls.append((query, limit))
        return self.ids[:limit]


class FakeReranker:
    calls: list[tuple[str, list[str], str]]

    def __init__(self) -> None:
        self.calls = []

    async def rerank(self, query, documents, *, mode, rerank_return_limit):
        self.calls.append((query, documents, mode))
        count = min(len(documents), rerank_return_limit)
        return RerankOutcome(
            results=[RerankResult(index=index, score=0.9) for index in range(count)],
            provider="pinecone",
            model="bge-reranker-v2-m3",
            latency=0.01,
            attempts=1,
            input_count=len(documents),
            output_count=count,
        )


def _settings() -> Settings:
    return Settings(
        DATASET_REVISION="revision-1",
        RERANK_INPUT_LIMIT=48,
        RERANK_RETURN_LIMIT=24,
        FINAL_EVIDENCE_LIMIT=3,
        LLM_CONTEXT_MAX_TOKENS=720,
        LLM_CONTEXT_PER_DOCUMENT_LIMIT=2,
        RERANK_MIN_SCORE=0.0,
    )


@pytest.mark.asyncio
async def test_retriever_runs_dense_and_exact_filtered_search_then_reranks() -> None:
    index = FakeIndex()
    fts = FakeFts([42])
    reranker = FakeReranker()
    retriever = PineconeStructuralRetriever(
        settings=_settings(),
        contract=PineconeStructuralContract(),
        index=index,
        fts_index=fts,
        reranker=reranker,
    )

    outcome = await retriever.retrieve(
        "Theo Điều 1 Luật số 01/2024/QH15 quy định gì?"
    )

    assert outcome.status == "ok"
    assert [hit.record_id for hit in outcome.trace.dense_hits] == ["dense-1"]
    assert [hit.record_id for hit in outcome.trace.exact_hits] == ["exact-1"]
    assert [row.document_id for row in outcome.evidence] == [42, 42]
    assert len(index.calls) == 2
    assert index.calls[0]["inputs"] == {
        "text": "Theo Điều 1 Luật số 01/2024/QH15 quy định gì?"
    }
    assert any(
        call.get("filter") == {"document_id": {"$in": [42]}}
        for call in index.calls
    )
    assert outcome.provider_usage["llama-text-embed-v2"] == 24
    assert outcome.provider_usage["pinecone_read_units"] == 2
    assert reranker.calls[0][2] == "pinecone-only"


@pytest.mark.asyncio
async def test_retriever_fails_closed_on_dense_provider_error() -> None:
    index = FakeIndex(error=TimeoutError("secret response body"))
    retriever = PineconeStructuralRetriever(
        settings=_settings(),
        contract=PineconeStructuralContract(),
        index=index,
        fts_index=FakeFts(),
        reranker=FakeReranker(),
    )

    outcome = await retriever.retrieve("Câu hỏi không có số văn bản")

    assert outcome.status == "retrieval_error"
    assert not outcome.evidence
    assert outcome.technical_errors["dense"].category == "timeout"
    assert "secret" not in outcome.model_dump_json()


@pytest.mark.asyncio
async def test_retriever_rejects_malformed_search_usage() -> None:
    class BadUsageIndex(FakeIndex):
        def search(self, **kwargs):
            response = super().search(**kwargs)
            response.usage.embed_total_tokens = None
            return response

    retriever = PineconeStructuralRetriever(
        settings=_settings(),
        contract=PineconeStructuralContract(),
        index=BadUsageIndex(),
        fts_index=FakeFts(),
        reranker=FakeReranker(),
    )

    outcome = await retriever.retrieve("Câu hỏi không có số văn bản")

    assert outcome.status == "retrieval_error"
    assert outcome.technical_errors["dense"].category == "malformed_usage"
