from types import SimpleNamespace

from app.evaluation.capacities import build_stage_capacities
from app.evaluation.profiles import get_evaluation_profile


def test_structural_backend_reports_actual_stage_capacities() -> None:
    settings = SimpleNamespace(
        STRUCTURAL_BACKEND_ENABLED=True,
        STRUCTURAL_DENSE_TOP_K=48,
        STRUCTURAL_BM25_TOP_K=48,
        STRUCTURAL_FUSED_LIMIT=64,
        STRUCTURAL_RERANK_INPUT_LIMIT=64,
        STRUCTURAL_RERANK_RETURN_LIMIT=6,
        STRUCTURAL_FINAL_EVIDENCE_LIMIT=5,
    )

    capacities = build_stage_capacities(
        get_evaluation_profile("separated_intent"),
        settings,
    )

    assert capacities.pinecone_document_limit == 48
    assert capacities.fts_document_limit == 48
    assert capacities.merged_document_limit == 64
    assert capacities.resolved_document_limit == 64
    assert capacities.structural_chunk_limit == 64
    assert capacities.local_chunks_limit is None
    assert capacities.rerank_input_limit == 64
    assert capacities.rerank_return_limit == 6
    assert capacities.final_evidence_limit == 5
