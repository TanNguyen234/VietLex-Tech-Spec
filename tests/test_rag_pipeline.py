import pytest

from app.evaluation.schemas import RetrievalStageTrace
from app.ingestion.legal_text import EvidenceChunk
from app.services import rag_pipeline
from app.services.structural_retrieval import (
    StructuralRetrievalOutcome,
    StructuralRetrievalTrace,
    StructuralTechnicalError,
)
from app.services.remote_reranker import RerankOutcome, RerankResult


@pytest.mark.asyncio
async def test_rewrite_query_rejects_repetitive_model_output(monkeypatch) -> None:
    query = (
        "Khi chi nhánh chấm dứt hoạt động thì doanh nghiệp chịu trách nhiệm "
        "gì đối với nợ và người lao động?"
    )

    async def repetitive_response(*_args, **_kwargs) -> rag_pipeline.LLMGenerationResult:
        return rag_pipeline.LLMGenerationResult(
            'Trang, "Tr, "Tr, "Tr, "Tr, "Tr, "Tr, "Tr, "Tr, "Tr',
            "test_provider",
            "test_model",
        )

    monkeypatch.setattr(
        rag_pipeline,
        "generate_llm_response_with_metadata",
        repetitive_response,
    )

    assert await rag_pipeline.rewrite_query(query) == query


@pytest.mark.asyncio
async def test_rewrite_query_rejects_provider_exhaustion_message(
    monkeypatch,
) -> None:
    query = (
        "Khi chi nhánh chấm dứt hoạt động thì doanh nghiệp chịu trách nhiệm "
        "gì đối với nợ và người lao động?"
    )

    async def unavailable_response(*_args, **_kwargs) -> rag_pipeline.LLMGenerationResult:
        return rag_pipeline.LLMGenerationResult(
            text=(
                "Hệ thống chưa thể xử lý do toàn bộ API Keys đang bị giới hạn "
                "tốc độ. Vui lòng thử lại sau 30 giây."
            ),
            observed_provider="unobserved",
            observed_model="unobserved",
            observed=False,
            status="providers_exhausted",
        )


    monkeypatch.setattr(
        rag_pipeline,
        "generate_llm_response_with_metadata",
        unavailable_response,
    )

    assert await rag_pipeline.rewrite_query(query) == query


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
    def __init__(self, evidence, *, status: str = "ok", error: str | None = None):
        self.evidence = evidence
        self.status = status
        self.error = error
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
            status=self.status,
            diagnostics={"rerank_provider": "qdrant"},
            error=self.error,
        )


@pytest.mark.asyncio
async def test_pipeline_fails_closed_without_calling_answer_model(
    monkeypatch,
) -> None:
    retriever = FakeRetriever([])
    answer_called = False

    async def fake_rewrite(query: str, *, raise_on_error: bool = False) -> tuple[str, dict]:
        return query, {"provider": "none", "model": "none", "observed": False}

    async def forbidden_answer(*args, **kwargs):
        nonlocal answer_called
        answer_called = True
        return rag_pipeline.LLMGenerationResult("không được gọi", "unobserved", "unobserved")

    monkeypatch.setattr(
        rag_pipeline,
        "get_legal_retriever",
        lambda: retriever,
    )
    monkeypatch.setattr(
        rag_pipeline,
        "get_settings",
        lambda: type(
            "RuntimeSettings",
            (),
            {"STRUCTURAL_BACKEND_ENABLED": False},
        )(),
    )
    monkeypatch.setattr(rag_pipeline, "rewrite_query_with_metadata", fake_rewrite)
    monkeypatch.setattr(
        rag_pipeline,
        "generate_response_with_metadata",
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
async def test_pipeline_does_not_turn_retrieval_error_into_honest_refusal(
    monkeypatch,
) -> None:
    retriever = FakeRetriever(
        [],
        status="reranker_error",
        error="both providers unavailable",
    )

    async def fake_rewrite(query: str, *, raise_on_error: bool = False) -> tuple[str, dict]:
        return query, {"provider": "none", "model": "none", "observed": False}

    monkeypatch.setattr(
        rag_pipeline,
        "get_legal_retriever",
        lambda: retriever,
    )
    monkeypatch.setattr(rag_pipeline, "rewrite_query_with_metadata", fake_rewrite)

    with pytest.raises(rag_pipeline.RetrievalPipelineError) as captured:
        await rag_pipeline.run_advanced_rag("điều kiện thuế")

    assert captured.value.status == "reranker_error"
    assert "both providers unavailable" in str(captured.value)


@pytest.mark.asyncio
async def test_pipeline_formats_ranked_evidence_for_existing_contract(
    monkeypatch,
) -> None:
    evidence = _evidence()
    retriever = FakeRetriever([evidence])

    async def fake_rewrite(query: str, *, raise_on_error: bool = False) -> tuple[str, dict]:
        return "truy vấn pháp lý", {"provider": "test_provider", "model": "test_model", "observed": True}

    async def fake_answer(
        original_query: str,
        rewritten_query: str,
        context: list[str],
    ) -> rag_pipeline.LLMGenerationResult:
        assert original_query == "điều kiện thuế"
        assert rewritten_query == "truy vấn pháp lý"
        assert context == [evidence.formatted_context()]
        return rag_pipeline.LLMGenerationResult(
            text="Câu trả lời có căn cứ.",
            observed_provider="test_provider",
            observed_model="test_model",
            observed=True,
            project="vietlex-test-project",
            location="global",
            provider_latency_ms=12.5,
            fallback_used=True,
            primary_error_kind="quota",
        )

    monkeypatch.setattr(
        rag_pipeline,
        "get_legal_retriever",
        lambda: retriever,
    )
    monkeypatch.setattr(rag_pipeline, "rewrite_query_with_metadata", fake_rewrite)
    monkeypatch.setattr(
        rag_pipeline,
        "generate_response_with_metadata",
        fake_answer,
    )

    response, contexts, latency = await rag_pipeline.run_advanced_rag(
        "điều kiện thuế",
        rewrite_mode="on",
    )

    assert response == "Câu trả lời có căn cứ."
    assert contexts == [evidence.formatted_context()]
    assert retriever.queries == [
        ("truy vấn pháp lý", "điều kiện thuế")
    ]
    assert latency["t_retrieval"] >= 0
    generation_usage = latency["provider_usage"]["answer_generation"]
    assert generation_usage == {
        "provider": "test_provider",
        "model": "test_model",
        "observed": True,
        "project": "vietlex-test-project",
        "location": "global",
        "status": "success",
        "latency_ms": 12.5,
        "fallback_used": True,
        "primary_error_kind": "quota",
    }


@pytest.mark.asyncio
async def test_pipeline_searches_structural_and_full_corpus_when_enabled(
    monkeypatch,
) -> None:
    evidence = _evidence()

    class StructuralRetriever:
        def __init__(self) -> None:
            self.queries = []

        async def retrieve(self, query: str, *, sparse_query: str | None = None):
            self.queries.append((query, sparse_query))
            return StructuralRetrievalOutcome(
                status="ok",
                evidence=[evidence],
                trace=StructuralRetrievalTrace(),
                latency={"total": 0.02},
                technical_errors={},
                provider_usage={"intfloat/multilingual-e5-small": 8},
            )

    structural = StructuralRetriever()
    legacy_evidence = EvidenceChunk(
        document_id=2,
        document_number="99/2026/NĐ-CP",
        title="Văn bản ngoài structural pilot",
        source_url="https://example.invalid/2",
        heading_path="Điều 9",
        article="Điều 9",
        clause="2",
        citation="99/2026/NĐ-CP, Điều 9, Khoản 2",
        text="Bằng chứng từ corpus đầy đủ.",
        token_count=6,
    )
    legacy = FakeRetriever([legacy_evidence])

    monkeypatch.setattr(
        rag_pipeline,
        "get_settings",
        lambda: type(
            "RuntimeSettings",
            (),
            {
                "STRUCTURAL_BACKEND_ENABLED": True,
                "CROSS_LANE_FINAL_RERANK_ENABLED": True,
            },
        )(),
    )
    monkeypatch.setattr(
        rag_pipeline,
        "get_structural_legal_retriever",
        lambda: structural,
    )
    class FinalReranker:
        async def rerank(self, _query, documents, **kwargs):
            assert kwargs["mode"] == "pinecone-only"
            assert len(documents) == 2
            return RerankOutcome(
                results=[
                    RerankResult(index=1, score=0.9),
                    RerankResult(index=0, score=0.4),
                ],
                provider="pinecone",
                model="bge-reranker-v2-m3",
                latency=0.01,
                input_count=2,
                output_count=2,
            )

    monkeypatch.setattr(
        rag_pipeline,
        "get_legal_retriever",
        lambda: legacy,
    )
    monkeypatch.setattr(
        rag_pipeline,
        "get_remote_reranker",
        lambda: FinalReranker(),
    )

    async def fake_answer(*_args, **_kwargs):
        return rag_pipeline.LLMGenerationResult(
            text="Câu trả lời structural.",
            observed_provider="google_vertex_ai",
            observed_model="gemini-3.5-flash",
            observed=True,
        )

    monkeypatch.setattr(
        rag_pipeline,
        "generate_response_with_metadata",
        fake_answer,
    )

    response, contexts, latency = await rag_pipeline.run_advanced_rag(
        "điều kiện thuế"
    )

    assert response == "Câu trả lời structural."
    assert contexts == [
        legacy_evidence.formatted_context(),
        evidence.formatted_context(),
    ]
    assert structural.queries == [("điều kiện thuế", "điều kiện thuế")]
    assert legacy.queries == [("điều kiện thuế", "điều kiện thuế")]
    assert latency["retrieval_diagnostics"]["retrieval_backend"] == (
        "parallel_structural_full_corpus_v1"
    )
    assert isinstance(
        latency["retrieval_diagnostics"]["stage_trace"],
        RetrievalStageTrace,
    )
    assert [
        item.document_id
        for item in latency["retrieval_diagnostics"][
            "stage_trace"
        ].final_evidence_chunks
    ] == [2, 1]
    assert latency["retrieval_diagnostics"]["final_reranker_provider"] == (
        "pinecone"
    )


def test_parallel_pool_keeps_distinct_windows_of_same_provision() -> None:
    first = _evidence()
    duplicate = EvidenceChunk(
        document_id=first.document_id,
        document_number=first.document_number,
        title=first.title,
        source_url=first.source_url,
        heading_path=first.heading_path,
        article=" điều 1 ",
        clause="01",
        citation=first.citation,
        text=first.text + " Nội dung structural dài hơn.",
        token_count=first.token_count + 5,
    )

    merged = rag_pipeline._interleave_evidence(
        [first],
        [duplicate],
        limit=3,
        max_tokens=720,
        per_document_limit=2,
    )

    assert merged == [first, duplicate]


def test_parallel_pool_removes_only_exact_normalized_chunk_duplicate() -> None:
    first = _evidence()
    duplicate = EvidenceChunk(
        **{
            **first.__dict__,
            "text": "  " + first.text.upper() + "  ",
        }
    )

    merged = rag_pipeline._interleave_evidence(
        [first],
        [duplicate],
        limit=3,
        max_tokens=720,
        per_document_limit=2,
    )

    assert merged == [first]


@pytest.mark.asyncio
async def test_final_rerank_zero_survivors_is_not_reported_ok(
    monkeypatch,
) -> None:
    first = _evidence()
    second = EvidenceChunk(
        **{
            **first.__dict__,
            "document_id": 2,
            "document_number": "99/2026/NĐ-CP",
            "citation": "99/2026/NĐ-CP, Điều 2",
            "article": "Điều 2",
            "text": "Bằng chứng thứ hai.",
        }
    )

    class RejectingReranker:
        async def rerank(self, *_args, **_kwargs):
            return RerankOutcome(
                results=[
                    RerankResult(index=0, score=0.01),
                    RerankResult(index=1, score=0.02),
                ],
                provider="pinecone",
                model="bge-reranker-v2-m3",
                latency=0.01,
                input_count=2,
                output_count=2,
            )

    monkeypatch.setattr(
        rag_pipeline,
        "get_settings",
        lambda: type(
            "RuntimeSettings",
            (),
            {
                "FINAL_EVIDENCE_LIMIT": 3,
                "LLM_CONTEXT_MAX_TOKENS": 720,
                "LLM_CONTEXT_PER_DOCUMENT_LIMIT": 2,
                "RERANK_MIN_SCORE": 0.05,
                "CROSS_LANE_FINAL_RERANK_ENABLED": True,
            },
        )(),
    )
    monkeypatch.setattr(
        rag_pipeline,
        "get_remote_reranker",
        lambda: RejectingReranker(),
    )

    outcome = await rag_pipeline._parallel_retrieval_outcome(
        rag_pipeline.RetrievalOutcome([first], {}, diagnostics={}),
        rag_pipeline.RetrievalOutcome([second], {}, diagnostics={}),
        query="câu hỏi",
    )

    assert outcome.status == "no_candidate"
    assert outcome.diagnostics["no_candidate_reason"] == (
        "no_candidate_after_final_rerank"
    )
    assert outcome.diagnostics["pre_final_candidate_count"] == 2
    assert outcome.diagnostics["post_final_candidate_count"] == 0


def test_canonical_identity_does_not_merge_clause_without_article() -> None:
    first = _evidence()
    first = EvidenceChunk(
        **{
            **first.__dict__,
            "article": None,
            "citation": "12/2026/NĐ-CP, Chương I, Khoản 1",
        }
    )
    second = EvidenceChunk(
        **{
            **first.__dict__,
            "citation": "12/2026/NĐ-CP, Chương II, Khoản 1",
            "text": "Một khoản khác không xác định Điều.",
        }
    )

    assert rag_pipeline._evidence_identity(first) != (
        rag_pipeline._evidence_identity(second)
    )


@pytest.mark.asyncio
async def test_pipeline_observes_structural_error_when_legacy_fallback_succeeds(
    monkeypatch,
) -> None:
    evidence = _evidence()
    legacy = FakeRetriever([evidence])

    class FailedStructuralRetriever:
        async def retrieve(
            self,
            _query: str,
            *,
            sparse_query: str | None = None,
        ):
            return StructuralRetrievalOutcome(
                status="retrieval_error",
                evidence=[],
                trace=StructuralRetrievalTrace(),
                latency={"total": 0.02},
                technical_errors={
                    "dense": StructuralTechnicalError(
                        stage="dense",
                        category="unavailable",
                        error_type="ProviderUnavailable",
                        transient=True,
                    )
                },
                provider_usage={},
            )

    monkeypatch.setattr(
        rag_pipeline,
        "get_settings",
        lambda: type(
            "RuntimeSettings",
            (),
            {"STRUCTURAL_BACKEND_ENABLED": True},
        )(),
    )
    monkeypatch.setattr(
        rag_pipeline,
        "get_structural_legal_retriever",
        lambda: FailedStructuralRetriever(),
    )
    monkeypatch.setattr(
        rag_pipeline,
        "get_legal_retriever",
        lambda: legacy,
    )

    async def fake_answer(*_args, **_kwargs):
        return rag_pipeline.LLMGenerationResult(
            text="Câu trả lời fallback.",
            observed_provider="google_vertex_ai",
            observed_model="gemini-3.5-flash",
            observed=True,
        )

    monkeypatch.setattr(
        rag_pipeline,
        "generate_response_with_metadata",
        fake_answer,
    )

    response, contexts, latency = await rag_pipeline.run_advanced_rag(
        "điều kiện thuế"
    )

    assert response == "Câu trả lời fallback."
    assert contexts == [evidence.formatted_context()]
    assert legacy.queries == [("điều kiện thuế", "điều kiện thuế")]
    assert latency["retrieval_status"] == "partial_retrieval_error"
    diagnostics = latency["retrieval_diagnostics"]
    assert diagnostics["retrieval_backend"] == (
        "parallel_structural_full_corpus_v1"
    )
    assert diagnostics["structural_status"] == "retrieval_error"
    assert diagnostics["failed_lanes"] == ["structural"]
    assert diagnostics["structural_diagnostics"][
        "structural_technical_errors"
    ]["dense"][
        "category"
    ] == "unavailable"


@pytest.mark.asyncio
async def test_vertex_shadow_never_changes_production_evidence(monkeypatch) -> None:
    evidence = _evidence()
    legacy = FakeRetriever([evidence])

    monkeypatch.setattr(
        rag_pipeline,
        "get_settings",
        lambda: type(
            "RuntimeSettings",
            (),
            {
                "STRUCTURAL_BACKEND_ENABLED": False,
                "VERTEX_QDRANT_SHADOW_ENABLED": True,
                "VERTEX_QDRANT_SHADOW_TIMEOUT_SECONDS": 1.0,
            },
        )(),
    )
    monkeypatch.setattr(rag_pipeline, "get_legal_retriever", lambda: legacy)

    async def shadow(*_args, **_kwargs):
        return rag_pipeline.RetrievalOutcome(
            evidence=[],
            latency={"vertex_qdrant": 0.1},
            status="no_candidate",
            diagnostics={"candidate_pool": {"candidate_ids_sha256": "a" * 64}},
        )

    monkeypatch.setattr(rag_pipeline, "_run_vertex_shadow", shadow)

    outcome = await rag_pipeline.retrieve_configured_legal_evidence(
        "dense", "original", None
    )

    assert outcome.evidence == [evidence]
    assert outcome.status == "ok"
    assert outcome.diagnostics["vertex_shadow"] == {
        "status": "no_candidate",
        "candidate_ids_sha256": "a" * 64,
        "latency": {"vertex_qdrant": 0.1},
    }


@pytest.mark.asyncio
async def test_pipeline_uses_original_query_when_rewrite_is_not_requested(
    monkeypatch,
) -> None:
    evidence = _evidence()
    retriever = FakeRetriever([evidence])

    async def forbidden_rewrite(*_args, **_kwargs):
        pytest.fail("query rewrite must be opt-in")

    async def fake_answer(
        original_query: str,
        rewritten_query: str,
        context: list[str],
    ) -> rag_pipeline.LLMGenerationResult:
        assert original_query == "điều kiện thuế"
        assert rewritten_query == original_query
        return rag_pipeline.LLMGenerationResult(
            text="Câu trả lời có căn cứ.",
            observed_provider="google_vertex_ai",
            observed_model="gemini-3.5-flash",
            observed=True,
        )

    monkeypatch.setattr(rag_pipeline, "get_legal_retriever", lambda: retriever)
    monkeypatch.setattr(rag_pipeline, "rewrite_query_with_metadata", forbidden_rewrite)
    monkeypatch.setattr(rag_pipeline, "generate_response_with_metadata", fake_answer)

    await rag_pipeline.run_advanced_rag("điều kiện thuế")

    assert retriever.queries == [("điều kiện thuế", "điều kiện thuế")]



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
        thinking_level: str | None = None,
    ) -> rag_pipeline.LLMGenerationResult:
        nonlocal captured_system_prompt
        captured_system_prompt = system_prompt
        assert max_output_tokens == 1536
        assert thinking_level == "MINIMAL"
        return rag_pipeline.LLMGenerationResult(
            text="Câu trả lời.",
            observed_provider="test_provider",
            observed_model="test_model",
        )

    monkeypatch.setattr(
        rag_pipeline,
        "generate_llm_response_with_metadata",
        fake_generate,
    )

    await rag_pipeline.generate_response_with_metadata(
        "Văn bản còn hiệu lực không?",
        "hiệu lực văn bản",
        [_evidence().formatted_context()],
    )

    normalized = captured_system_prompt.lower()
    assert "nguồn dữ liệu bên thứ ba" in normalized
    assert "không xác nhận tình trạng hiệu lực" in normalized
    assert "nguồn chính thức" in normalized
    assert "không phải tư vấn pháp lý" in normalized
