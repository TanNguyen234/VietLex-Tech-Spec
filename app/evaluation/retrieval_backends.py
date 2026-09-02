from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from qdrant_client import AsyncQdrantClient

from app.config import get_settings, system_ssl_context
from app.ingestion.content_store import ContentStore
from app.ingestion.pinecone_store import FastSparseEncoder
from app.ingestion.vertex_qdrant_migration import VertexQdrantContract
from app.services.vertex_ai import get_vertex_provider
from app.services.vertex_qdrant_retrieval import VertexQdrantRetriever


RetrievalBackend = Literal[
    "production", "pinecone-v1", "qdrant-v2-parallel", "vertex-qdrant-v3"
]


@lru_cache(maxsize=1)
def get_vertex_qdrant_retriever() -> VertexQdrantRetriever:
    settings = get_settings()
    average_sparse_document_length = (
        settings.V3_AVERAGE_SPARSE_DOCUMENT_LENGTH
        if settings.SERVERLESS_ONLINE_ONLY
        else ContentStore(
            settings.V3_CONTENT_STORE_PATH
        ).build_report().average_sparse_document_length
    )
    return VertexQdrantRetriever(
        provider=get_vertex_provider(),
        client=AsyncQdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY,
            timeout=settings.STRUCTURAL_QDRANT_TIMEOUT_SECONDS,
            verify=system_ssl_context(),
            check_compatibility=False,
        ),
        sparse_encoder=FastSparseEncoder(
            average_document_length=average_sparse_document_length,
            max_nonzero_terms=settings.PINECONE_SPARSE_MAX_NONZERO,
        ),
        contract=VertexQdrantContract(
            collection_name=settings.VERTEX_QDRANT_COLLECTION_NAME,
            embedding_model=settings.VERTEX_EMBEDDING_MODEL,
            vector_size=settings.VERTEX_QDRANT_VECTOR_SIZE,
        ),
        dataset_revision=settings.DATASET_REVISION,
    )


async def retrieve_for_evaluation(
    backend: RetrievalBackend,
    *,
    dense_query: str,
    sparse_query: str,
    profile: Any,
    ranking: str = "raw-rrf",
    case_id: str = "unknown",
) -> Any:
    if backend == "vertex-qdrant-v3":
        from app.evaluation.candidate_pool import build_candidate_pool
        from app.services.clients import get_qdrant_only_reranker
        from app.services.retrieval import RetrievalOutcome

        outcome = await get_vertex_qdrant_retriever().retrieve_detailed(
            dense_query,
            sparse_query=sparse_query,
            limit=getattr(
                profile, "rerank_input_limit", profile.final_evidence_limit
            ),
        )
        trace = outcome.diagnostics.get("stage_trace")
        scores = (
            [candidate.score for candidate in trace.structural_chunks_generated]
            if trace is not None
            else None
        )
        pool = build_candidate_pool(
            case_id,
            outcome.evidence,
            "|".join(
                (
                    get_settings().VERTEX_QDRANT_COLLECTION_NAME,
                    get_settings().VERTEX_EMBEDDING_MODEL,
                    str(get_settings().VERTEX_QDRANT_VECTOR_SIZE),
                )
            ),
            scores=scores,
        )
        diagnostics = {
            **outcome.diagnostics,
            "candidate_pool": pool.model_dump(mode="json"),
            "ranking": ranking,
        }
        if outcome.status not in {"ok", "no_candidate"}:
            return RetrievalOutcome(
                evidence=outcome.evidence,
                latency=outcome.latency,
                status=outcome.status,
                diagnostics=diagnostics,
                error=outcome.error,
            )
        selected = list(outcome.evidence[: profile.final_evidence_limit])
        selected_indices = list(range(len(selected)))
        status = outcome.status
        error = outcome.error
        latency = dict(outcome.latency)
        if ranking == "qdrant-colbert" and outcome.evidence:
            try:
                reranked = await get_qdrant_only_reranker().rerank(
                    sparse_query,
                    [item.text for item in outcome.evidence],
                    mode="qdrant-only",
                    rerank_return_limit=profile.final_evidence_limit,
                )
                selected = [
                    outcome.evidence[item.index]
                    for item in reranked.results
                    if 0 <= item.index < len(outcome.evidence)
                ]
                selected_indices = [
                    item.index
                    for item in reranked.results
                    if 0 <= item.index < len(outcome.evidence)
                ]
                latency["qdrant_colbert"] = reranked.latency
                diagnostics["reranker_provider"] = reranked.provider
                diagnostics["reranker_model"] = reranked.model
            except Exception as rerank_error:
                status = "partial_retrieval_error"
                error = f"{type(rerank_error).__name__}: {rerank_error}"
                diagnostics["reranker_error_type"] = type(rerank_error).__name__
        elif ranking != "raw-rrf":
            raise ValueError(f"unsupported v3 ranking mode: {ranking}")
        trace = diagnostics.get("stage_trace")
        if trace is not None:
            source_candidates = list(trace.structural_chunks_generated)
            trace.reranker_input_chunks = source_candidates
            trace.reranker_output_chunks = [
                source_candidates[index]
                for index in selected_indices
                if index < len(source_candidates)
            ]
            trace.final_evidence_chunks = list(trace.reranker_output_chunks)
        return RetrievalOutcome(
            evidence=selected,
            latency=latency,
            status=status,
            diagnostics=diagnostics,
            error=error,
        )
    if backend == "pinecone-v1":
        from app.services.retrieval import get_legal_retriever

        return await get_legal_retriever().retrieve_detailed(
            dense_query, sparse_query=sparse_query, profile=profile
        )
    from app.services.rag_pipeline import retrieve_configured_legal_evidence

    if backend == "qdrant-v2-parallel" and not get_settings().STRUCTURAL_BACKEND_ENABLED:
        raise RuntimeError(
            "qdrant-v2-parallel requires STRUCTURAL_BACKEND_ENABLED=true; "
            "the evaluator will not silently fall back"
        )
    return await retrieve_configured_legal_evidence(
        dense_query, sparse_query, profile
    )


async def rerank_persisted_vertex_candidates(
    result: Any,
    *,
    query: str,
    profile: Any,
) -> Any:
    from app.evaluation.candidate_pool import (
        CandidatePool,
        assert_identical_candidate_pool,
        build_candidate_pool,
    )
    from app.ingestion.legal_text import EvidenceChunk
    from app.services.clients import get_qdrant_only_reranker
    from app.services.retrieval import RetrievalOutcome

    candidates = list(result.stage_trace.structural_chunks_generated)
    evidence = []
    for candidate in candidates:
        if not all(
            (
                candidate.document_id is not None,
                candidate.document_number,
                candidate.title,
                candidate.source_url,
                candidate.citation,
                candidate.text,
            )
        ):
            raise ValueError("persisted v3 candidate is missing evidence fields")
        evidence.append(
            EvidenceChunk(
                document_id=int(candidate.document_id),
                document_number=candidate.document_number,
                title=candidate.title,
                source_url=candidate.source_url,
                heading_path="",
                article=candidate.article,
                clause=candidate.clause,
                citation=candidate.citation,
                text=candidate.text,
                token_count=len(candidate.text.split()),
            )
        )
    expected = CandidatePool.model_validate(
        result.retrieval_diagnostics["candidate_pool"]
    )
    actual = build_candidate_pool(
        result.case_id,
        evidence,
        "|".join(
            (
                get_settings().VERTEX_QDRANT_COLLECTION_NAME,
                get_settings().VERTEX_EMBEDDING_MODEL,
                str(get_settings().VERTEX_QDRANT_VECTOR_SIZE),
            )
        ),
        scores=[candidate.score for candidate in candidates],
    )
    assert_identical_candidate_pool(expected, actual)
    reranked = await get_qdrant_only_reranker().rerank(
        query,
        [item.text for item in evidence],
        mode="qdrant-only",
        rerank_return_limit=profile.final_evidence_limit,
    )
    indices = [
        item.index
        for item in reranked.results
        if 0 <= item.index < len(evidence)
    ]
    trace = result.stage_trace.model_copy(deep=True)
    trace.reranker_input_chunks = candidates
    trace.reranker_output_chunks = [candidates[index] for index in indices]
    trace.final_evidence_chunks = list(trace.reranker_output_chunks)
    return RetrievalOutcome(
        evidence=[evidence[index] for index in indices],
        latency={"qdrant_colbert": reranked.latency},
        status="ok" if indices else "no_candidate",
        diagnostics={
            "stage_trace": trace,
            "backend": "vertex-qdrant-v3",
            "candidate_pool": expected.model_dump(mode="json"),
            "ranking": "qdrant-colbert",
            "reranker_provider": reranked.provider,
            "reranker_model": reranked.model,
        },
    )
