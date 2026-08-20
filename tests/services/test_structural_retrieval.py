from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.ingestion.structural_qdrant import (
    InferenceUsageReceipt,
    StructuralProviderError,
    StructuralQdrantContract,
)
from app.services.remote_reranker import RerankOutcome, RerankResult
from app.services.structural_retrieval import (
    StructuralCandidate,
    StructuralRetrievalError,
    StructuralRetriever,
    StructuralSourceHit,
    build_structural_retriever,
    reciprocal_rank_fusion,
)


def _settings(**updates: object) -> Settings:
    values: dict[str, object] = {
        "STRUCTURAL_BACKEND_ENABLED": True,
        "DATASET_REVISION": "revision-1",
        "RERANK_INPUT_LIMIT": 24,
        "RERANK_RETURN_LIMIT": 6,
        "FINAL_EVIDENCE_LIMIT": 3,
        "LLM_CONTEXT_MAX_TOKENS": 720,
        "LLM_CONTEXT_PER_DOCUMENT_LIMIT": 2,
    }
    values.update(updates)
    return Settings(_env_file=None, **values)


def _payload(
    record_id: str,
    *,
    document_id: int = 1,
    body: str | None = None,
    revision: str = "revision-1",
    article: str = "Điều 1",
    clause: str | None = None,
) -> dict[str, object]:
    text = body or f"Điều 1. Nội dung {record_id}"
    return {
        "body": text,
        "document_id": document_id,
        "document_number": f"{document_id}/2026/QH15",
        "title": f"Luật thử nghiệm {document_id}",
        "source_url": f"https://example.invalid/{document_id}",
        "legal_type": "Luật",
        "issuing_authority": "Quốc hội",
        "issuance_date": "01/01/2026",
        "article": article,
        "clause": clause,
        "heading_path": ", ".join(value for value in (article, clause) if value),
        "citation": f"{document_id}/2026/QH15, {article}",
        "token_count": max(1, len(text.split())),
        "dataset_revision": revision,
        "content_sha256": "a" * 64,
        "chunk_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "inference_text_sha256": "f" * 64,
    }


def _candidate(
    record_id: str,
    *,
    document_id: int = 1,
    body: str | None = None,
) -> StructuralCandidate:
    return StructuralCandidate(record_id=record_id, **_payload(
        record_id,
        document_id=document_id,
        body=body,
    ))


def _source_hit(
    record_id: str,
    score: float,
    *,
    document_id: int = 1,
) -> StructuralSourceHit:
    return StructuralSourceHit(
        record_id=record_id,
        candidate=_candidate(record_id, document_id=document_id),
        source_score=score,
    )


def _point(
    record_id: str,
    score: float,
    *,
    document_id: int = 1,
    revision: str = "revision-1",
):
    return SimpleNamespace(
        id=record_id,
        score=score,
        payload=_payload(
            record_id,
            document_id=document_id,
            revision=revision,
        ),
    )


def test_rrf_retains_source_ranks_scores_and_prioritizes_exact_ties() -> None:
    rows = reciprocal_rank_fusion(
        dense=[_source_hit("a", 0.9), _source_hit("b", 0.8)],
        bm25=[_source_hit("b", 7.0), _source_hit("c", 6.0)],
        exact=[_source_hit("c", 1.0)],
        rrf_k=60,
    )

    assert [row.record_id for row in rows] == ["c", "b", "a"]
    assert rows[1].dense_rank == 2
    assert rows[1].bm25_rank == 1
    assert rows[1].dense_score == 0.8
    assert rows[1].bm25_score == 7.0


class FakeTransport:
    def __init__(
        self,
        contract: StructuralQdrantContract,
        *,
        dense=None,
        bm25=None,
        exact=None,
        dense_error: Exception | None = None,
        bm25_error: Exception | None = None,
        exact_error: Exception | None = None,
        neighbors=None,
        neighbor_error: Exception | None = None,
    ) -> None:
        self.contract = contract
        self.results = {
            "dense": dense if dense is not None else [_point("dense-1", 0.9)],
            "bm25": bm25 if bm25 is not None else [_point("bm25-1", 7.0)],
            "exact": exact if exact is not None else [_point("exact-1", 6.0)],
        }
        self.errors = {
            "dense": dense_error,
            "bm25": bm25_error,
            "exact": exact_error,
        }
        self.calls: list[dict[str, object]] = []
        self.neighbors = neighbors if neighbors is not None else []
        self.neighbor_error = neighbor_error

    def query_with_usage(self, **kwargs):
        lane = (
            "dense"
            if kwargs["using"] == self.contract.dense_vector_name
            else "exact"
            if kwargs.get("query_filter") is not None
            else "bm25"
        )
        self.calls.append({"lane": lane, **kwargs})
        error = self.errors[lane]
        if error is not None:
            raise error
        model = (
            self.contract.dense_model
            if lane == "dense"
            else self.contract.sparse_model
        )
        return self.results[lane], InferenceUsageReceipt(
            status="completed",
            elapsed_seconds=0.01,
            model_tokens={model: 10 if lane == "dense" else 11},
        )

    def read_by_filter(self, *, query_filter, limit):
        self.calls.append(
            {"lane": "structural_neighbors", "query_filter": query_filter, "limit": limit}
        )
        if self.neighbor_error is not None:
            raise self.neighbor_error
        return self.neighbors


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


class FakeReranker:
    def __init__(
        self,
        *,
        error: Exception | None = None,
        provider: str = "qdrant",
        fallback_reason: str | None = None,
    ) -> None:
        self.error = error
        self.provider = provider
        self.fallback_reason = fallback_reason
        self.calls: list[tuple[str, list[str], int | None, str]] = []

    async def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        rerank_return_limit: int | None = None,
        mode: str = "current",
        **_kwargs,
    ) -> RerankOutcome:
        self.calls.append((query, documents, rerank_return_limit, mode))
        if self.error is not None:
            raise self.error
        limit = min(len(documents), rerank_return_limit or len(documents))
        return RerankOutcome(
            results=[
                RerankResult(index=index, score=0.95 - index * 0.01)
                for index in range(limit)
            ],
            provider=self.provider,
            model=(
                "answerdotai/answerai-colbert-small-v1"
                if self.provider == "qdrant"
                else "bge-reranker-v2-m3"
            ),
            latency=0.01,
            fallback_reason=self.fallback_reason,
            attempts=1,
            input_count=len(documents),
            output_count=limit,
        )


def _retriever(
    *,
    dense=None,
    bm25=None,
    exact=None,
    dense_error: Exception | None = None,
    bm25_error: Exception | None = None,
    exact_error: Exception | None = None,
    fts: FakeFts | None = None,
    reranker: FakeReranker | None = None,
    settings: Settings | None = None,
    reranker_mode: str = "current",
    neighbors=None,
    neighbor_error: Exception | None = None,
) -> tuple[StructuralRetriever, FakeTransport, FakeFts, FakeReranker]:
    resolved_settings = settings or _settings()
    contract = StructuralQdrantContract.from_settings(resolved_settings)
    transport = FakeTransport(
        contract,
        dense=dense,
        bm25=bm25,
        exact=exact,
        dense_error=dense_error,
        bm25_error=bm25_error,
        exact_error=exact_error,
        neighbors=neighbors,
        neighbor_error=neighbor_error,
    )
    resolved_fts = fts or FakeFts()
    resolved_reranker = reranker or FakeReranker()
    return (
        StructuralRetriever(
            settings=resolved_settings,
            contract=contract,
            transport=transport,
            fts_index=resolved_fts,
            reranker=resolved_reranker,
            reranker_mode=reranker_mode,  # type: ignore[arg-type]
        ),
        transport,
        resolved_fts,
        resolved_reranker,
    )


@pytest.mark.asyncio
async def test_structural_neighbor_expansion_adds_adjacent_article_and_sibling_clause() -> None:
    seed = _point("seed", 0.9)
    seed.payload.update(_payload("seed", article="Điều 123"))
    sibling = _point("sibling", 0.0)
    sibling.payload.update(_payload("sibling", article="Điều 123", clause="Khoản 2"))
    adjacent = _point("adjacent", 0.0)
    adjacent.payload.update(_payload("adjacent", article="Điều 124"))
    settings = _settings(
        STRUCTURAL_NEIGHBOR_EXPANSION_ENABLED=True,
        STRUCTURAL_NEIGHBOR_READ_LIMIT=8,
    )
    retriever, transport, _fts, _reranker = _retriever(
        dense=[seed],
        bm25=[],
        exact=[],
        neighbors=[sibling, adjacent],
        settings=settings,
    )

    outcome = await retriever.retrieve("Điều 124")

    assert outcome.status == "ok"
    assert {row.record_id for row in outcome.trace.reranker_input} >= {
        "seed", "sibling", "adjacent"
    }
    neighbor_call = next(
        call for call in transport.calls
        if call["lane"] == "structural_neighbors"
    )
    assert neighbor_call["limit"] == 8
    serialized_filter = neighbor_call["query_filter"].model_dump()
    articles = {
        value
        for branch in serialized_filter["should"]
        for condition in branch["must"]
        if condition.get("key") == "article"
        for value in condition["match"]["any"]
    }
    assert {"Điều 122", "Điều 123", "Điều 124"} <= articles
    assert 2 not in {
        condition["match"]["value"]
        for branch in serialized_filter["should"]
        for condition in branch["must"]
        if condition.get("key") == "document_id"
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("neighbors", "neighbor_error", "category"),
    [
        ([object()] * 9, None, "read_overflow"),
        ([_point("bad", 0.0, revision="wrong")], None, "malformed_payload"),
        (None, TimeoutError("private"), "timeout"),
    ],
)
async def test_structural_neighbor_failures_are_typed_and_fail_closed(
    neighbors, neighbor_error, category
) -> None:
    retriever, _transport, _fts, reranker = _retriever(
        settings=_settings(
            STRUCTURAL_NEIGHBOR_EXPANSION_ENABLED=True,
            STRUCTURAL_NEIGHBOR_READ_LIMIT=8,
        ),
        neighbors=neighbors,
        neighbor_error=neighbor_error,
    )

    outcome = await retriever.retrieve("Điều 2")

    assert outcome.status == "retrieval_error"
    assert outcome.evidence == []
    assert outcome.technical_errors["structural_neighbors"].category == category
    assert reranker.calls == []


@pytest.mark.asyncio
async def test_dense_failure_is_not_converted_to_empty_success() -> None:
    error = StructuralProviderError(
        stage="query:dense",
        category="timeout",
        message="typed",
        transient=True,
    )
    retriever, _transport, _fts, _reranker = _retriever(dense_error=error)

    outcome = await retriever.retrieve("Điều 16")

    assert outcome.status == "partial_technical_error"
    assert outcome.technical_errors["dense"].category == "timeout"
    assert outcome.trace.dense_hits == []
    assert outcome.trace.bm25_hits


@pytest.mark.asyncio
async def test_structural_chunks_are_returned_without_document_rechunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.ingestion.legal_text.chunk_document",
        lambda *_args, **_kwargs: pytest.fail("rechunk called"),
    )
    retriever, _transport, _fts, _reranker = _retriever()

    outcome = await retriever.retrieve("trách nhiệm môi trường")

    assert outcome.evidence[0].text == outcome.trace.final_hits[0].body
    assert outcome.trace.final_hits[0].inference_text_sha256 == "f" * 64


@pytest.mark.asyncio
async def test_dense_instruction_bm25_raw_and_exact_filter_are_distinct() -> None:
    fts = FakeFts([17, 18])
    retriever, transport, _fts, _reranker = _retriever(fts=fts)

    outcome = await retriever.retrieve("  Điều 16 Nghị định 17/2026/NĐ-CP  ")

    assert outcome.status == "ok"
    calls = {call["lane"]: call for call in transport.calls}
    assert calls["dense"]["document"].text.startswith("Instruct: ")
    assert calls["dense"]["document"].text.endswith(
        "Query:Điều 16 Nghị định 17/2026/NĐ-CP"
    )
    assert calls["bm25"]["document"].text == (
        "Điều 16 Nghị định 17/2026/NĐ-CP"
    )
    assert calls["exact"]["document"].text == (
        "Điều 16 Nghị định 17/2026/NĐ-CP"
    )
    query_filter = calls["exact"]["query_filter"]
    condition = query_filter.must[0]
    assert condition.key == "document_id"
    assert condition.match.any == [17, 18]
    assert fts.calls == [("Điều 16 Nghị định 17/2026/NĐ-CP", 64)]
    assert outcome.trace.exact_document_ids == [17, 18]
    assert outcome.provider_usage == {
        "intfloat/multilingual-e5-small": 10,
        "qdrant/bm25": 22,
    }


@pytest.mark.asyncio
async def test_both_unrestricted_remote_failures_are_retrieval_error() -> None:
    dense_error = StructuralProviderError(
        stage="query:dense",
        category="timeout",
        message="typed",
        transient=True,
    )
    sparse_error = StructuralProviderError(
        stage="query:bm25",
        category="rate_limit",
        message="typed",
        transient=True,
    )
    retriever, _transport, _fts, reranker = _retriever(
        dense_error=dense_error,
        bm25_error=sparse_error,
        fts=FakeFts([1]),
    )

    outcome = await retriever.retrieve("1/2026/QH15")

    assert outcome.status == "retrieval_error"
    assert outcome.evidence == []
    assert outcome.trace.exact_hits
    assert reranker.calls == []


@pytest.mark.asyncio
async def test_malformed_or_wrong_revision_payload_fails_closed_per_lane() -> None:
    malformed = _point("bad", 0.9)
    malformed.payload.pop("chunk_sha256")
    wrong_revision = _point("wrong", 7.0, revision="other")
    retriever, _transport, _fts, reranker = _retriever(
        dense=[malformed],
        bm25=[wrong_revision],
    )

    outcome = await retriever.retrieve("môi trường")

    assert outcome.status == "retrieval_error"
    assert set(outcome.technical_errors) == {"dense", "bm25"}
    assert outcome.trace.dense_hits == []
    assert outcome.trace.bm25_hits == []
    assert reranker.calls == []


@pytest.mark.asyncio
async def test_dedupe_fused_cap_per_document_and_rerank_limits() -> None:
    dense = [
        _point(f"r-{index:03d}", 100 - index, document_id=index // 4 + 1)
        for index in range(48)
    ]
    bm25 = [dense[0]] + [
        _point(
            f"s-{index:03d}",
            100 - index,
            document_id=index // 4 + 13,
        )
        for index in range(47)
    ]
    settings = _settings(
        RERANK_INPUT_LIMIT=5,
        RERANK_RETURN_LIMIT=2,
        FINAL_EVIDENCE_LIMIT=1,
        STRUCTURAL_RERANK_INPUT_LIMIT=24,
        STRUCTURAL_RERANK_RETURN_LIMIT=6,
        STRUCTURAL_FINAL_EVIDENCE_LIMIT=3,
    )
    retriever, _transport, _fts, reranker = _retriever(
        dense=dense,
        bm25=bm25,
        settings=settings,
    )

    outcome = await retriever.retrieve("môi trường")

    assert len(outcome.trace.fused_hits) == 64
    assert len({row.record_id for row in outcome.trace.fused_hits}) == 64
    counts: dict[int, int] = {}
    for row in outcome.trace.fused_hits:
        counts[row.document_id] = counts.get(row.document_id, 0) + 1
    assert max(counts.values()) <= 8
    assert len(outcome.trace.reranker_input) == 24
    assert reranker.calls[0][2] == 6
    assert reranker.calls[0][3] == "current"
    assert outcome.trace.reranker_input_sha256 is not None
    assert len(outcome.trace.reranker_output) == 6
    assert len(outcome.evidence) == 3


@pytest.mark.asyncio
async def test_rewrite_only_changes_dense_query() -> None:
    retriever, transport, _fts, reranker = _retriever(
        dense=[_point("dense", 0.9)],
        bm25=[_point("sparse", 0.8)],
    )

    await retriever.retrieve(
        "truy van viet lai",
        sparse_query="cau hoi goc",
    )

    dense_call, bm25_call = transport.calls[:2]
    assert dense_call["document"].text.endswith("Query:truy van viet lai")
    assert bm25_call["document"].text == "cau hoi goc"
    assert reranker.calls[0][0] == "truy van viet lai"


@pytest.mark.asyncio
async def test_exact_lane_error_and_provider_usage_remain_separate() -> None:
    exact_error = StructuralProviderError(
        stage="query:bm25",
        category="timeout",
        message="typed",
        transient=True,
    )
    retriever, _transport, _fts, _reranker = _retriever(
        exact_error=exact_error,
        fts=FakeFts([1]),
    )

    outcome = await retriever.retrieve("1/2026/QH15")

    assert outcome.status == "partial_technical_error"
    assert outcome.technical_errors["exact_remote"].category == "timeout"
    assert outcome.provider_usage == {
        "intfloat/multilingual-e5-small": 10,
        "qdrant/bm25": 11,
    }
    assert outcome.trace.provider_usage_by_lane == {
        "dense": {"intfloat/multilingual-e5-small": 10},
        "bm25": {"qdrant/bm25": 11},
    }


@pytest.mark.asyncio
async def test_fts_error_is_typed_without_hiding_remote_success() -> None:
    retriever, _transport, _fts, _reranker = _retriever(
        fts=FakeFts(error=RuntimeError("private local path"))
    )

    outcome = await retriever.retrieve("1/2026/QH15")

    assert outcome.status == "partial_technical_error"
    error = outcome.technical_errors["exact_fts"]
    assert error.category == "RuntimeError"
    assert "private local path" not in error.model_dump_json()


@pytest.mark.asyncio
async def test_reranker_error_is_separate_and_fail_closed() -> None:
    retriever, _transport, _fts, _reranker = _retriever(
        reranker=FakeReranker(error=TimeoutError("secret provider detail"))
    )

    outcome = await retriever.retrieve("môi trường")

    assert outcome.status == "reranker_error"
    assert outcome.evidence == []
    assert outcome.technical_errors["reranker"].category == "timeout"
    assert "secret provider detail" not in outcome.model_dump_json()


@pytest.mark.asyncio
async def test_malformed_reranker_indices_are_fail_closed() -> None:
    class MalformedReranker(FakeReranker):
        async def rerank(self, query, documents, **_kwargs):
            return RerankOutcome(
                results=[
                    RerankResult(index=0, score=0.9),
                    RerankResult(index=0, score=0.8),
                ],
                provider="qdrant",
                model="answerdotai/answerai-colbert-small-v1",
                latency=0.01,
                input_count=len(documents),
                output_count=2,
            )

    retriever, _transport, _fts, _reranker = _retriever(
        reranker=MalformedReranker()
    )

    outcome = await retriever.retrieve("môi trường")

    assert outcome.status == "reranker_error"
    assert outcome.technical_errors["reranker"].category == (
        "StructuralRetrievalError"
    )


@pytest.mark.asyncio
async def test_qdrant_reranker_fallback_is_observable_not_mislabeled() -> None:
    retriever, _transport, _fts, _reranker = _retriever(
        reranker=FakeReranker(
            provider="pinecone",
            fallback_reason="qdrant_transient",
        )
    )

    outcome = await retriever.retrieve("môi trường")

    assert outcome.status == "partial_technical_error"
    assert outcome.trace.reranker_provider == "pinecone"
    assert outcome.trace.reranker_fallback_reason == "qdrant_transient"
    assert outcome.technical_errors["reranker_primary"].category == (
        "qdrant_transient"
    )


@pytest.mark.asyncio
async def test_qdrant_unavailable_fallback_is_observable() -> None:
    retriever, _transport, _fts, _reranker = _retriever(
        reranker=FakeReranker(
            provider="pinecone",
            fallback_reason="qdrant_unavailable",
        )
    )

    outcome = await retriever.retrieve("môi trường")

    assert outcome.status == "partial_technical_error"
    assert outcome.trace.reranker_provider == "pinecone"
    assert outcome.trace.reranker_fallback_reason == "qdrant_unavailable"
    assert outcome.technical_errors["reranker_primary"].category == (
        "qdrant_unavailable"
    )
    assert outcome.technical_errors["reranker_primary"].transient is False


def test_factory_is_opt_in_and_does_not_modify_default_retriever() -> None:
    settings = _settings(STRUCTURAL_BACKEND_ENABLED=False)

    with pytest.raises(StructuralRetrievalError, match="disabled"):
        build_structural_retriever(
            settings,
            client=SimpleNamespace(),
            fts_index=FakeFts(),
            reranker=FakeReranker(),
        )

    enabled = build_structural_retriever(
        _settings(),
        client=SimpleNamespace(),
        fts_index=FakeFts(),
        reranker=FakeReranker(),
    )
    assert isinstance(enabled, StructuralRetriever)


def test_factory_accepts_explicit_benchmark_runtime_contract() -> None:
    settings = _settings()
    baseline = StructuralQdrantContract.from_settings(settings)
    runtime = StructuralQdrantContract.model_validate(
        {**baseline.model_dump(mode="python"), "per_document_limit": 8}
    )

    retriever = build_structural_retriever(
        settings,
        client=SimpleNamespace(),
        fts_index=FakeFts(),
        reranker=FakeReranker(),
        contract=runtime,
    )

    assert retriever.contract.per_document_limit == 8


@pytest.mark.asyncio
async def test_explicit_reranker_mode_preserves_hashed_body_inputs() -> None:
    retriever, _transport, _fts, reranker = _retriever(
        reranker_mode="pinecone-only"
    )

    outcome = await retriever.retrieve("môi trường")

    assert reranker.calls[0][3] == "pinecone-only"
    assert reranker.calls[0][1] == [
        candidate.body for candidate in outcome.trace.reranker_input
    ]
    assert outcome.trace.reranker_input_format == "body_v1"
    assert outcome.trace.reranker_input_sha256 == hashlib.sha256(
        json.dumps(
            {"query": "môi trường", "documents": reranker.calls[0][1]},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def test_invalid_programmatic_reranker_mode_is_rejected() -> None:
    retriever, transport, fts, reranker = _retriever()
    with pytest.raises(StructuralRetrievalError, match="reranker mode"):
        StructuralRetriever(
            settings=retriever.settings,
            contract=retriever.contract,
            transport=transport,
            fts_index=fts,
            reranker=reranker,
            reranker_mode="invalid",  # type: ignore[arg-type]
        )
