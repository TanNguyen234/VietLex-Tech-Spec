from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_evaluation_parsers_expose_explicit_backend() -> None:
    from run_answer_eval import build_parser as answer_parser
    from run_retrieval_eval import build_parser as retrieval_parser

    assert retrieval_parser().parse_args([]).backend == "production"
    assert answer_parser().parse_args([]).backend == "production"
    assert (
        retrieval_parser().parse_args(["--backend", "vertex-qdrant-v3"]).backend
        == "vertex-qdrant-v3"
    )
    assert retrieval_parser().parse_args(["--ranking", "dbsf"]).ranking == "dbsf"
    assert answer_parser().parse_args(["--ranking", "dbsf"]).ranking == "dbsf"
    assert retrieval_parser().parse_args(["--ranking", "rrf-dbsf"]).ranking == "rrf-dbsf"
    assert answer_parser().parse_args(["--ranking", "rrf-dbsf"]).ranking == "rrf-dbsf"


@pytest.mark.asyncio
async def test_dbsf_ranking_selects_dbsf_fusion(monkeypatch) -> None:
    from app.evaluation.retrieval_backends import retrieve_for_evaluation

    calls = []

    class Retriever:
        async def retrieve_detailed(self, dense_query, *, sparse_query, limit, fusion):
            from app.services.retrieval import RetrievalOutcome

            calls.append((dense_query, sparse_query, limit, fusion))
            return RetrievalOutcome(evidence=[], latency={}, status="no_candidate")

    monkeypatch.setattr(
        "app.evaluation.retrieval_backends.get_vertex_qdrant_retriever",
        lambda: Retriever(),
    )

    result = await retrieve_for_evaluation(
        "vertex-qdrant-v3",
        dense_query="dense",
        sparse_query="original",
        profile=SimpleNamespace(final_evidence_limit=3),
        ranking="dbsf",
    )

    assert result.status == "no_candidate"
    assert calls == [("dense", "original", 3, "dbsf")]


def test_run_configuration_binds_requested_and_effective_backend() -> None:
    from app.config import Settings
    from app.evaluation.run_manifest import build_run_configuration

    configuration = build_run_configuration(
        profile_name="test",
        profile={},
        eval_mode="retrieval-only",
        judge_mode="none",
        guardrail_mode="off",
        rewrite_mode="off",
        reranker_provider="current",
        gold_policy="none",
        selected_case_ids=[],
        selected_case_ids_sha256=(
            "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
        ),
        settings=Settings(_env_file=None),
        requested_backend="vertex-qdrant-v3",
    )

    assert configuration["requested_backend"] == "vertex-qdrant-v3"
    assert configuration["effective_backend"] == "vertex-qdrant-v3"
    assert configuration["retrieval_runtime"]["backend"] == "vertex-qdrant-v3"
    assert configuration["retrieval_runtime"]["collection"] == (
        "vietlex-legal-rag-v3-vertex-1024"
    )


def test_production_manifest_follows_boolean_pipeline_switch() -> None:
    from app.config import Settings
    from app.evaluation.run_manifest import build_run_configuration

    common = {
        "profile_name": "test",
        "profile": {},
        "eval_mode": "answer",
        "judge_mode": "ragas",
        "guardrail_mode": "off",
        "rewrite_mode": "off",
        "reranker_provider": "current",
        "gold_policy": "none",
        "selected_case_ids": [],
        "selected_case_ids_sha256": (
            "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
        ),
        "requested_backend": "production",
    }

    v3 = build_run_configuration(
        **common,
        settings=Settings(_env_file=None, USE_LEGACY_FREE_PIPELINE=False),
    )
    free = build_run_configuration(
        **common,
        settings=Settings(_env_file=None, USE_LEGACY_FREE_PIPELINE=True),
    )

    assert v3["effective_backend"] == "vertex-qdrant-v3"
    assert v3["retrieval_runtime"]["google_cloud_calls_enabled"] is True
    assert v3["configured_provider_models"]["generation"]["candidates"][0][
        "provider"
    ] == "Google Vertex AI"
    assert v3["configured_provider_models"]["reranker_primary"] == {
        "provider": "none",
        "model": "raw-rrf",
    }
    assert v3["configured_provider_models"]["reranker_fallback"] is None
    assert free["effective_backend"] == "pinecone_v1"
    assert free["retrieval_runtime"]["google_cloud_calls_enabled"] is False
    assert all(
        item["provider"] != "Google Vertex AI"
        for kind in ("generation", "judge")
        for item in free["configured_provider_models"][kind]["candidates"]
    )


def test_online_only_vertex_retriever_does_not_open_local_store(monkeypatch) -> None:
    from app.evaluation import retrieval_backends

    settings = SimpleNamespace(
        SERVERLESS_ONLINE_ONLY=True,
        V3_AVERAGE_SPARSE_DOCUMENT_LENGTH=979.1241640033913,
        V3_CONTENT_STORE_PATH="missing.sqlite3",
        QDRANT_URL="https://qdrant.example",
        QDRANT_API_KEY="key",
        STRUCTURAL_QDRANT_TIMEOUT_SECONDS=10.0,
        PINECONE_SPARSE_MAX_NONZERO=64,
        VERTEX_QDRANT_COLLECTION_NAME="collection",
        VERTEX_EMBEDDING_MODEL="model",
        VERTEX_QDRANT_VECTOR_SIZE=1024,
        DATASET_REVISION="revision",
    )
    captured = {}

    monkeypatch.setattr(retrieval_backends, "get_settings", lambda: settings)
    monkeypatch.setattr(
        retrieval_backends,
        "ContentStore",
        lambda _path: (_ for _ in ()).throw(AssertionError("local store opened")),
    )
    monkeypatch.setattr(retrieval_backends, "get_vertex_provider", object)
    monkeypatch.setattr(retrieval_backends, "AsyncQdrantClient", lambda **kw: object())

    class Retriever:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(retrieval_backends, "VertexQdrantRetriever", Retriever)
    retrieval_backends.get_vertex_qdrant_retriever.cache_clear()
    retrieval_backends.get_vertex_qdrant_retriever()

    assert captured["sparse_encoder"].average_document_length == pytest.approx(
        979.1241640033913
    )
    retrieval_backends.get_vertex_qdrant_retriever.cache_clear()


@pytest.mark.asyncio
async def test_explicit_vertex_backend_calls_only_vertex_adapter(monkeypatch) -> None:
    from app.evaluation.retrieval_backends import retrieve_for_evaluation

    calls = []

    class Retriever:
        async def retrieve_detailed(self, dense_query, *, sparse_query, limit):
            from app.services.retrieval import RetrievalOutcome

            calls.append((dense_query, sparse_query, limit))
            return RetrievalOutcome(evidence=[], latency={}, status="no_candidate")

    monkeypatch.setattr(
        "app.evaluation.retrieval_backends.get_vertex_qdrant_retriever",
        lambda: Retriever(),
    )
    profile = SimpleNamespace(final_evidence_limit=5)

    result = await retrieve_for_evaluation(
        "vertex-qdrant-v3",
        dense_query="dense",
        sparse_query="original",
        profile=profile,
    )

    assert result.status == "no_candidate"
    assert calls == [("dense", "original", 5)]


@pytest.mark.asyncio
async def test_colbert_reranks_the_persisted_candidate_pool(monkeypatch) -> None:
    from app.evaluation.candidate_pool import build_candidate_pool
    from app.evaluation.retrieval_backends import rerank_persisted_vertex_candidates
    from app.evaluation.schemas import RetrievalCaseResult, RetrievalStageTrace, StageCandidate
    from app.ingestion.legal_text import EvidenceChunk
    from app.services.remote_reranker import RerankOutcome, RerankResult

    evidence = [
        EvidenceChunk(
            document_id=document_id,
            document_number=f"{document_id}/2026/QH15",
            title="Luật",
            source_url=f"https://example.test/{document_id}",
            heading_path="",
            article="Điều 1",
            clause=None,
            citation=f"{document_id}/2026/QH15, Điều 1",
            text=text,
            token_count=1,
        )
        for document_id, text in ((1, "alpha"), (2, "beta"))
    ]
    candidates = [
        StageCandidate(
            document_id=item.document_id,
            document_number=item.document_number,
            title=item.title,
            source_url=item.source_url,
            citation=item.citation,
            article=item.article,
            text=item.text,
            score=score,
            source="vertex-qdrant-v3",
        )
        for item, score in zip(evidence, (0.8, 0.7), strict=True)
    ]
    pool = build_candidate_pool(
        "case_001",
        evidence,
        "vietlex-legal-rag-v3-vertex-1024|gemini-embedding-2|1024",
        scores=[0.8, 0.7],
    )
    raw = RetrievalCaseResult(
        case_id="case_001",
        question="query",
        original_query="query",
        question_type="factoid",
        answerable=True,
        query_used="query",
        status="ok",
        stage_trace=RetrievalStageTrace(structural_chunks_generated=candidates),
        retrieval_diagnostics={"candidate_pool": pool.model_dump(mode="json")},
    )

    class Reranker:
        async def rerank(self, query, documents, **kwargs):
            assert documents == ["alpha", "beta"]
            return RerankOutcome(
                results=[RerankResult(index=1, score=0.9)],
                provider="qdrant",
                model="colbert",
                latency=0.1,
            )

    monkeypatch.setattr(
        "app.services.clients.get_qdrant_only_reranker", lambda: Reranker()
    )

    outcome = await rerank_persisted_vertex_candidates(
        raw,
        query="query",
        profile=SimpleNamespace(final_evidence_limit=1),
    )

    assert outcome.evidence[0].document_id == 2
    assert outcome.diagnostics["candidate_pool"]["candidate_ids_sha256"] == (
        pool.candidate_ids_sha256
    )
