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
