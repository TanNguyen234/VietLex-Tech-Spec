from __future__ import annotations

from types import SimpleNamespace

import pytest
from qdrant_client import models

from app.ingestion.vertex_qdrant_migration import VertexQdrantContract


class Provider:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def embed_query(self, query: str, **kwargs):
        self.queries.append(query)
        return SimpleNamespace(values=[0.1] * 1024)


class Sparse:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def encode_query(self, query: str):
        self.queries.append(query)
        return SimpleNamespace(indices=[1], values=[0.5])


class Client:
    def __init__(self, points):
        self.points = points
        self.kwargs = None

    async def query_points(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(points=self.points)


def _point(**payload_overrides):
    payload = {
        "document_id": 12,
        "document_number": "12/2026/QH15",
        "title": "Luật thử nghiệm",
        "source_url": "https://example.test/12",
        "heading_path": "Điều 1",
        "citation": "12/2026/QH15, Điều 1",
        "article": "Điều 1",
        "clause": None,
        "body": "Nội dung quy định.",
        "token_count": 3,
        "dataset_revision": "rev",
        "chunk_sha256": "a" * 64,
        "embedding_provider": "google_vertex_ai",
        "embedding_model": "gemini-embedding-2",
        "embedding_dimension": 1024,
        "migration_schema": "vietlex-vertex-qdrant-v1",
    }
    payload.update(payload_overrides)
    return SimpleNamespace(id="point-1", score=0.8, payload=payload)


@pytest.mark.asyncio
async def test_vertex_retriever_uses_separate_dense_and_sparse_queries() -> None:
    from app.services.vertex_qdrant_retrieval import VertexQdrantRetriever

    provider = Provider()
    sparse = Sparse()
    client = Client([_point()])
    retriever = VertexQdrantRetriever(
        provider=provider,
        client=client,
        sparse_encoder=sparse,
        contract=VertexQdrantContract(),
        dataset_revision="rev",
    )

    outcome = await retriever.retrieve_detailed(
        "rewritten dense query",
        sparse_query="original legal query",
        limit=3,
    )

    assert provider.queries == ["rewritten dense query"]
    assert sparse.queries == ["original legal query"]
    assert outcome.status == "ok"
    assert outcome.evidence[0].document_id == 12
    assert outcome.diagnostics["stage_trace"].final_evidence_chunks[0].score == 0.8
    assert client.kwargs["collection_name"] == "vietlex-legal-rag-v3-vertex-1024"


@pytest.mark.asyncio
async def test_vertex_retriever_supports_dbsf_fusion() -> None:
    from app.services.vertex_qdrant_retrieval import VertexQdrantRetriever

    client = Client([_point()])
    retriever = VertexQdrantRetriever(
        provider=Provider(),
        client=client,
        sparse_encoder=Sparse(),
        contract=VertexQdrantContract(),
        dataset_revision="rev",
    )

    outcome = await retriever.retrieve_detailed(
        "dense query", sparse_query="sparse query", limit=3, fusion="dbsf"
    )

    assert outcome.status == "ok"
    assert client.kwargs["query"].fusion == models.Fusion.DBSF


@pytest.mark.asyncio
async def test_vertex_retriever_blends_rrf_and_dbsf_ranks() -> None:
    from app.services.vertex_qdrant_retrieval import VertexQdrantRetriever

    points = {
        models.Fusion.RRF: [
            _point(document_id=1),
            _point(document_id=2),
            _point(document_id=3),
        ],
        models.Fusion.DBSF: [
            _point(document_id=3),
            _point(document_id=1),
            _point(document_id=2),
        ],
    }
    for group in points.values():
        for point in group:
            point.id = f"point-{point.payload['document_id']}"

    class BlendedClient:
        def __init__(self) -> None:
            self.fusions = []

        async def query_points(self, **kwargs):
            fusion = kwargs["query"].fusion
            self.fusions.append(fusion)
            return SimpleNamespace(points=points[fusion])

    client = BlendedClient()
    retriever = VertexQdrantRetriever(
        provider=Provider(),
        client=client,
        sparse_encoder=Sparse(),
        contract=VertexQdrantContract(),
        dataset_revision="rev",
    )

    outcome = await retriever.retrieve_detailed(
        "dense query", sparse_query="sparse query", limit=3, fusion="rrf-dbsf"
    )

    assert client.fusions == [models.Fusion.RRF, models.Fusion.DBSF]
    assert [item.document_id for item in outcome.evidence] == [1, 3, 2]


@pytest.mark.asyncio
async def test_vertex_retriever_fails_closed_on_payload_contract_mismatch() -> None:
    from app.services.vertex_qdrant_retrieval import VertexQdrantRetriever

    retriever = VertexQdrantRetriever(
        provider=Provider(),
        client=Client([_point(embedding_dimension=384)]),
        sparse_encoder=Sparse(),
        contract=VertexQdrantContract(),
        dataset_revision="rev",
    )

    outcome = await retriever.retrieve_detailed("query", sparse_query="query", limit=3)

    assert outcome.status == "retrieval_error"
    assert outcome.evidence == []
    assert "embedding_dimension" in (outcome.error or "")


@pytest.mark.asyncio
async def test_vertex_retriever_reports_no_candidate() -> None:
    from app.services.vertex_qdrant_retrieval import VertexQdrantRetriever

    retriever = VertexQdrantRetriever(
        provider=Provider(),
        client=Client([]),
        sparse_encoder=Sparse(),
        contract=VertexQdrantContract(),
        dataset_revision="rev",
    )

    outcome = await retriever.retrieve_detailed("query", sparse_query="query", limit=3)

    assert outcome.status == "no_candidate"
    assert outcome.diagnostics["stage_trace"].final_evidence_chunks == []


@pytest.mark.asyncio
async def test_vertex_retriever_accepts_document_intro_without_heading() -> None:
    from app.services.vertex_qdrant_retrieval import VertexQdrantRetriever

    retriever = VertexQdrantRetriever(
        provider=Provider(),
        client=Client([_point(heading_path="")]),
        sparse_encoder=Sparse(),
        contract=VertexQdrantContract(),
        dataset_revision="rev",
    )

    outcome = await retriever.retrieve_detailed("query", sparse_query="query", limit=3)

    assert outcome.status == "ok"
    assert outcome.evidence[0].heading_path == ""
