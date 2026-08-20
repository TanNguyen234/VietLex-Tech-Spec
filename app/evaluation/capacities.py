from typing import Any
from app.evaluation.schemas import RetrievalStageCapacities
from app.evaluation.profiles import EvaluationProfile

def build_stage_capacities(profile: EvaluationProfile, settings: Any) -> RetrievalStageCapacities:
    if getattr(settings, "STRUCTURAL_BACKEND_ENABLED", False):
        fused_limit = settings.STRUCTURAL_FUSED_LIMIT
        return RetrievalStageCapacities(
            pinecone_document_limit=settings.STRUCTURAL_DENSE_TOP_K,
            fts_document_limit=settings.STRUCTURAL_BM25_TOP_K,
            merged_document_limit=fused_limit,
            resolved_document_limit=fused_limit,
            structural_chunk_limit=fused_limit,
            local_chunks_limit=None,
            rerank_input_limit=settings.STRUCTURAL_RERANK_INPUT_LIMIT,
            rerank_return_limit=settings.STRUCTURAL_RERANK_RETURN_LIMIT,
            final_evidence_limit=settings.STRUCTURAL_FINAL_EVIDENCE_LIMIT,
        )

    fts_limit = getattr(settings, "LEGAL_FTS_RESULT_LIMIT", 24)
    pinecone_limit = profile.retrieval_document_limit
    
    merged_cap = None
    if fts_limit is not None and pinecone_limit is not None:
        merged_cap = fts_limit + pinecone_limit

    local_limit = None
    if profile.resolved_document_limit is not None and profile.local_chunks_per_document is not None:
        local_limit = profile.resolved_document_limit * profile.local_chunks_per_document

    return RetrievalStageCapacities(
        pinecone_document_limit=pinecone_limit,
        fts_document_limit=fts_limit,
        merged_document_limit=merged_cap,
        resolved_document_limit=profile.resolved_document_limit,
        structural_chunk_limit=None,
        local_chunks_limit=local_limit,
        rerank_input_limit=profile.rerank_input_limit,
        rerank_return_limit=profile.rerank_return_limit,
        final_evidence_limit=profile.final_evidence_limit,
    )
