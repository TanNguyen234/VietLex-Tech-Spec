import pytest

from app.ingestion.legal_text import EvidenceChunk
from app.services import rag_pipeline


def _evidence() -> EvidenceChunk:
    return EvidenceChunk(
        document_id=1,
        document_number="12/2026/NĐ-CP",
        title="Nghị định thuế",
        source_url="https://example.invalid/1",
        heading_path="Chương I > Điều 1",
        article="Điều 1",
        clause="1",
        citation="12/2026/NĐ-CP, Điều 1, Khoản 1",
        text="Cá nhân được khấu trừ thuế theo quy định.",
        token_count=8,
    )


class FakeRetriever:
    def __init__(self, evidence):
        self.evidence = evidence
        self.queries: list[tuple[str, str | None]] = []

    async def retrieve(self, query: str, sparse_query: str | None = None):
        self.queries.append((query, sparse_query))
        return self.evidence

    async def retrieve_detailed(
        self,
        query: str,
        sparse_query: str | None = None,
    ):
        self.queries.append((query, sparse_query))
        return rag_pipeline.RetrievalOutcome(
            evidence=self.evidence,
            latency={
                "t_hybrid": 0.01,
                "t_resolve_chunk": 0.02,
                "t_candidate": 0.001,
                "t_rerank": 0.03,
            },
        )


@pytest.mark.asyncio
async def test_pipeline_fails_closed_without_calling_answer_model(
    monkeypatch,
) -> None:
    retriever = FakeRetriever([])
    answer_called = False

    async def fake_rewrite(query: str) -> str:
        return query

    async def forbidden_answer(*args, **kwargs):
        nonlocal answer_called
        answer_called = True
        return "không được gọi"

    monkeypatch.setattr(
        rag_pipeline,
        "get_legal_retriever",
        lambda: retriever,
    )
    monkeypatch.setattr(rag_pipeline, "rewrite_query", fake_rewrite)
    monkeypatch.setattr(
        rag_pipeline,
        "generate_response",
        forbidden_answer,
    )

    response, contexts, latency = await rag_pipeline.run_advanced_rag(
        "điều kiện thuế"
    )

    assert "không tìm thấy" in response.lower()
    assert contexts == []
    assert answer_called is False
    assert latency["t_total"] >= 0


@pytest.mark.asyncio
async def test_pipeline_formats_ranked_evidence_for_existing_contract(
    monkeypatch,
) -> None:
    evidence = _evidence()
    retriever = FakeRetriever([evidence])

    async def fake_rewrite(query: str) -> str:
        return "truy vấn pháp lý"

    async def fake_answer(
        original_query: str,
        rewritten_query: str,
        context: list[str],
    ) -> str:
        assert original_query == "điều kiện thuế"
        assert rewritten_query == "truy vấn pháp lý"
        assert context == [evidence.formatted_context()]
        return "Câu trả lời có căn cứ."

    monkeypatch.setattr(
        rag_pipeline,
        "get_legal_retriever",
        lambda: retriever,
    )
    monkeypatch.setattr(rag_pipeline, "rewrite_query", fake_rewrite)
    monkeypatch.setattr(
        rag_pipeline,
        "generate_response",
        fake_answer,
    )

    response, contexts, latency = await rag_pipeline.run_advanced_rag(
        "điều kiện thuế"
    )

    assert response == "Câu trả lời có căn cứ."
    assert contexts == [evidence.formatted_context()]
    assert retriever.queries == [
        ("truy vấn pháp lý", "điều kiện thuế")
    ]
    assert latency["t_retrieval"] >= 0


def test_context_builder_enforces_one_global_budget_in_rank_order() -> None:
    first = "nguồn một " + "quan trọng " * 8
    second = "nguồn hai " + "không nên xuất hiện " * 8

    bounded = rag_pipeline.build_bounded_context(
        [first, second],
        max_tokens=14,
    )

    assert len(bounded.split()) <= 14
    assert "nguồn một" in bounded
    assert "nguồn hai" not in bounded


@pytest.mark.asyncio
async def test_answer_model_receives_external_corpus_reliability_rules(
    monkeypatch,
) -> None:
    captured_system_prompt = ""

    async def fake_generate(
        user_prompt: str,
        system_prompt: str,
        *,
        max_output_tokens: int,
    ) -> str:
        nonlocal captured_system_prompt
        captured_system_prompt = system_prompt
        assert max_output_tokens == 640
        return "Câu trả lời."

    monkeypatch.setattr(
        rag_pipeline,
        "generate_llm_response",
        fake_generate,
    )

    await rag_pipeline.generate_response(
        "Văn bản còn hiệu lực không?",
        "hiệu lực văn bản",
        [_evidence().formatted_context()],
    )

    normalized = captured_system_prompt.lower()
    assert "nguồn dữ liệu bên thứ ba" in normalized
    assert "không xác nhận tình trạng hiệu lực" in normalized
    assert "nguồn chính thức" in normalized
    assert "không phải tư vấn pháp lý" in normalized
