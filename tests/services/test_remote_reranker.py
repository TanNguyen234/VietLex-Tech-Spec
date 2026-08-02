from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services.remote_reranker import RemoteReranker


class ProviderError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"provider returned {status_code}")
        self.status_code = status_code


class FakeQdrant:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.created = 0
        self.upserts: list[dict] = []
        self.queries: list[dict] = []
        self.deletes: list[dict] = []

    def collection_exists(self, _name: str) -> bool:
        return self.created > 0

    def create_collection(self, **_kwargs) -> bool:
        self.created += 1
        return True

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)
        if self.error is not None:
            raise self.error

    def query_points(self, **kwargs):
        self.queries.append(kwargs)
        return SimpleNamespace(
            points=[
                SimpleNamespace(payload={"candidate_index": 1}, score=0.9),
                SimpleNamespace(payload={"candidate_index": 0}, score=0.8),
            ]
        )

    def delete(self, **kwargs):
        self.deletes.append(kwargs)


class FakeInference:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def rerank(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=0, score=0.77),
            ]
        )


@pytest.mark.asyncio
async def test_qdrant_success_does_not_call_pinecone() -> None:
    settings = Settings(_env_file=None, QDRANT_RERANK_MAX_RETRIES=1)
    qdrant = FakeQdrant()
    pinecone = SimpleNamespace(inference=FakeInference())
    reranker = RemoteReranker(
        settings=settings,
        qdrant=qdrant,
        pinecone=pinecone,
    )

    outcome = await reranker.rerank(
        "thuế thu nhập",
        ["Điều 1", "Điều 2"],
    )

    assert outcome.provider == "qdrant"
    assert outcome.model == settings.QDRANT_RERANK_MODEL
    assert [item.index for item in outcome.results] == [1, 0]
    assert pinecone.inference.calls == []
    assert len(qdrant.upserts) == 1
    assert len(qdrant.queries) == 1
    assert len(qdrant.deletes) == 1


@pytest.mark.asyncio
async def test_transient_qdrant_failure_falls_back_to_pinecone() -> None:
    settings = Settings(_env_file=None, QDRANT_RERANK_MAX_RETRIES=1)
    qdrant = FakeQdrant(error=ProviderError(503))
    pinecone = SimpleNamespace(inference=FakeInference())
    reranker = RemoteReranker(
        settings=settings,
        qdrant=qdrant,
        pinecone=pinecone,
    )

    outcome = await reranker.rerank("thuế", ["Điều 1"])

    assert outcome.provider == "pinecone"
    assert outcome.model == settings.PINECONE_RERANK_MODEL
    assert outcome.fallback_reason == "qdrant_transient"
    assert [item.index for item in outcome.results] == [0]
    assert pinecone.inference.calls[0]["return_documents"] is False


@pytest.mark.asyncio
async def test_permanent_qdrant_failure_is_not_hidden_by_fallback() -> None:
    settings = Settings(_env_file=None, QDRANT_RERANK_MAX_RETRIES=1)
    qdrant = FakeQdrant(error=ProviderError(401))
    pinecone = SimpleNamespace(inference=FakeInference())
    reranker = RemoteReranker(
        settings=settings,
        qdrant=qdrant,
        pinecone=pinecone,
    )

    with pytest.raises(ProviderError):
        await reranker.rerank("thuế", ["Điều 1"])

    assert pinecone.inference.calls == []
