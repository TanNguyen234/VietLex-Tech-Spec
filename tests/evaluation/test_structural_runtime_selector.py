from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.evaluation.profiles import get_evaluation_profile
from app.evaluation.schemas import GoldenCase, RetrievalStageTrace
from app.ingestion.legal_text import EvidenceChunk
from app.services.retrieval import RetrievalOutcome
from run_retrieval_eval import evaluate_single_retrieval_case


@pytest.mark.asyncio
async def test_evaluator_uses_configured_structural_runtime(monkeypatch) -> None:
    settings = SimpleNamespace(
        STRUCTURAL_BACKEND_ENABLED=True,
        STRUCTURAL_DENSE_TOP_K=48,
        STRUCTURAL_BM25_TOP_K=48,
        STRUCTURAL_FUSED_LIMIT=64,
        STRUCTURAL_RERANK_INPUT_LIMIT=64,
        STRUCTURAL_RERANK_RETURN_LIMIT=6,
        STRUCTURAL_FINAL_EVIDENCE_LIMIT=5,
    )
    case = GoldenCase(
        case_id="case_structural",
        question="Điều kiện là gì?",
        question_type="factoid",
        answerable=True,
        reference_answer="Theo Điều 1.",
    )
    evidence = EvidenceChunk(
        document_id=1,
        document_number="1/2026/QH15",
        title="Luật thử nghiệm",
        source_url="https://example.invalid/1",
        heading_path="Điều 1",
        article="Điều 1",
        clause=None,
        citation="1/2026/QH15, Điều 1",
        text="Điều 1. Nội dung.",
        token_count=3,
    )
    configured = AsyncMock(
        return_value=RetrievalOutcome(
            evidence=[evidence],
            latency={},
            diagnostics={
                "retrieval_backend": "qdrant_structural_v2",
                "stage_trace": RetrievalStageTrace(),
            },
        )
    )
    monkeypatch.setattr(
        "app.services.rag_pipeline.retrieve_configured_legal_evidence",
        configured,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.retrieval.get_legal_retriever",
        lambda: pytest.fail("legacy evaluator path must not run"),
    )

    result = await evaluate_single_retrieval_case(
        case,
        settings,
        get_evaluation_profile("separated_intent"),
    )

    configured.assert_awaited_once_with(
        case.question,
        case.question,
        get_evaluation_profile("separated_intent"),
    )
    assert result.status == "ok"
    assert result.retrieved_evidence[0].article == "Điều 1"
