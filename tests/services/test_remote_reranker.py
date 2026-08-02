from types import SimpleNamespace
import time

import pytest

from app.config import Settings
from app.services.remote_reranker import RemoteReranker


class ProviderError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"provider returned {status_code}")
        self.status_code = status_code


class FakeQdrant:
    def __init__(
        self,
        *,
        error: Exception | None = None,
        delay: float = 0.0,
        empty: bool = False,
        point_count: int = 0,
    ) -> None:
        self.error = error
        self.delay = delay
        self.empty = empty
        self.point_count = point_count
        self.created = 0
        self.upserts: list[dict] = []
        self.queries: list[dict] = []
        self.deletes: list[dict] = []
        self.payload_indexes: list[dict] = []

    def collection_exists(self, _name: str) -> bool:
        return self.created > 0

    def create_collection(self, **_kwargs) -> bool:
        self.created += 1
        return True

    def create_payload_index(self, **kwargs):
        self.payload_indexes.append(kwargs)

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None:
            raise self.error

    def query_points(self, **kwargs):
        self.queries.append(kwargs)
        if self.empty:
            return SimpleNamespace(points=[])
        return SimpleNamespace(
            points=[
                SimpleNamespace(payload={"candidate_index": 1}, score=0.9),
                SimpleNamespace(payload={"candidate_index": 0}, score=0.8),
            ]
        )

    def delete(self, **kwargs):
        self.deletes.append(kwargs)

    def count(self, **_kwargs):
        return SimpleNamespace(count=self.point_count)


class FakeInference:
    def __init__(self, *, empty: bool = False) -> None:
        self.empty = empty
        self.calls: list[dict] = []

    def rerank(self, **kwargs):
        self.calls.append(kwargs)
        if self.empty:
            return SimpleNamespace(data=[])
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
    assert qdrant.payload_indexes[0]["field_name"] == "request_id"
    assert len(qdrant.queries) == 1
    assert len(qdrant.deletes) == 2
    assert {item["field_name"] for item in qdrant.payload_indexes} == {
        "request_id",
        "created_at",
    }


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


@pytest.mark.asyncio
async def test_outer_qdrant_timeout_falls_back_to_pinecone() -> None:
    settings = Settings(
        _env_file=None,
        QDRANT_RERANK_TIMEOUT_SECONDS=0.01,
        QDRANT_RERANK_MAX_RETRIES=1,
    )
    pinecone = SimpleNamespace(inference=FakeInference())
    reranker = RemoteReranker(
        settings=settings,
        qdrant=FakeQdrant(delay=0.05),
        pinecone=pinecone,
    )

    outcome = await reranker.rerank("thuế", ["Điều 1"])

    assert outcome.provider == "pinecone"
    assert outcome.fallback_reason == "qdrant_transient"
    assert outcome.attempts == 2


@pytest.mark.asyncio
async def test_empty_qdrant_ranking_uses_pinecone_fallback() -> None:
    settings = Settings(_env_file=None, QDRANT_RERANK_MAX_RETRIES=1)
    pinecone = SimpleNamespace(inference=FakeInference())
    reranker = RemoteReranker(
        settings=settings,
        qdrant=FakeQdrant(empty=True),
        pinecone=pinecone,
    )

    outcome = await reranker.rerank("thuế", ["Điều 1"])

    assert outcome.provider == "pinecone"
    assert outcome.results


@pytest.mark.asyncio
async def test_empty_fallback_ranking_is_a_provider_error() -> None:
    settings = Settings(_env_file=None, QDRANT_RERANK_MAX_RETRIES=1)
    reranker = RemoteReranker(
        settings=settings,
        qdrant=FakeQdrant(empty=True),
        pinecone=SimpleNamespace(inference=FakeInference(empty=True)),
    )

    with pytest.raises(RuntimeError, match="no valid results"):
        await reranker.rerank("thuế", ["Điều 1"])


@pytest.mark.asyncio
async def test_stale_points_are_swept_before_new_request() -> None:
    settings = Settings(_env_file=None, QDRANT_RERANK_MAX_RETRIES=1)
    qdrant = FakeQdrant(point_count=10)
    reranker = RemoteReranker(
        settings=settings,
        qdrant=qdrant,
        pinecone=SimpleNamespace(inference=FakeInference()),
    )

    await reranker.rerank("thuế", ["Điều 1"])

    assert len(qdrant.deletes) == 2
    assert qdrant.deletes[0]["wait"] is True
    assert qdrant.deletes[1]["wait"] is True


@pytest.mark.asyncio
async def test_staging_hard_limit_uses_pinecone_without_upsert() -> None:
    settings = Settings(
        _env_file=None,
        QDRANT_RERANK_MAX_RETRIES=1,
        QDRANT_RERANK_MAX_STAGING_POINTS=2,
    )
    qdrant = FakeQdrant(point_count=2)
    reranker = RemoteReranker(
        settings=settings,
        qdrant=qdrant,
        pinecone=SimpleNamespace(inference=FakeInference()),
    )

    outcome = await reranker.rerank("thuế", ["Điều 1"])

    assert outcome.provider == "pinecone"
    assert qdrant.upserts == []
