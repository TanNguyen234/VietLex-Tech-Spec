from types import SimpleNamespace

from app.services.research_presenter import (
    build_claim_support,
    build_public_retrieval_trace,
    sanitize_retrieval_trace,
)


def test_claim_support_uses_observable_citation_anchors_only() -> None:
    contexts = [
        "[45/2019/QH14, Điều 25]\nID tài liệu: 123\nThời gian thử việc tối đa là 60 ngày."
    ]

    result = build_claim_support(
        "Theo Điều 25, thời gian thử việc tối đa là 60 ngày. "
        "Theo 45/2019/QH14, thử việc có giới hạn tối đa. "
        "Người lao động luôn được bồi thường.",
        contexts,
    )

    assert result[0]["support_state"] == "directly_supported"
    assert result[0]["evidence_indices"] == [0]
    assert result[1]["support_state"] == "partially_supported"
    assert result[2]["support_state"] == "unresolved"
    assert all("confidence" not in item for item in result)


def test_claim_links_do_not_confuse_article_prefixes_or_documents() -> None:
    contexts = ["[45/2019/QH14, Điều 2]\nA", "[12/2020/QH14, Điều 2]\nB"]
    result = build_claim_support(
        "Theo Điều 25, đây là quy định. Theo Điều 2, có nghĩa vụ.", contexts
    )
    assert all(item["support_state"] == "unresolved" for item in result)


def test_claim_support_is_unresolved_without_evidence_and_bounded() -> None:
    answer = " ".join(f"Mệnh đề {index}." for index in range(30))

    result = build_claim_support(answer, [])

    assert 1 <= len(result) <= 12
    assert {item["support_state"] for item in result} == {"unresolved"}


def test_retrieval_trace_keeps_counts_and_drops_candidate_payloads() -> None:
    stage_trace = SimpleNamespace(
        pinecone_hits=[1, 2],
        fts_hits=[1],
        structural_chunks_generated=[{"text": "private body"}] * 4,
        reranker_output_chunks=[1, 2, 3],
        final_evidence_chunks=[1, 2],
    )
    latency = {
        "t_total": 1.5,
        "rewritten_query": "thử việc",
        "retrieval_status": "ok",
        "retrieval_diagnostics": {
            "backend": "vertex-qdrant-v3",
            "collection": "vietlex-legal-rag-v3-vertex-1024",
            "ranking": "rrf-dbsf",
            "stage_trace": stage_trace,
            "secret": "do-not-copy",
        },
    }

    trace = sanitize_retrieval_trace(
        latency,
        ["evidence-a", "evidence-b"],
        SimpleNamespace(LLM_CONTEXT_MAX_TOKENS=720, USE_LEGACY_FREE_PIPELINE=False),
        query="Thử việc?",
        cached=False,
    )

    assert trace["backend"] == "vertex-qdrant-v3"
    assert trace["candidate_counts"]["structural_chunks_generated"] == 4
    assert trace["final_evidence_count"] == 2
    assert "private body" not in str(trace)
    assert "do-not-copy" not in str(trace)


def test_public_retrieval_trace_handles_legacy_record() -> None:
    trace = build_public_retrieval_trace(
        {
            "user_query": "Câu hỏi",
            "cached": False,
            "safety_status": {"input_safe": True, "output_safe": True},
            "metrics": {
                "request_status": "technical_error",
                "observed_provider": "google_vertex_ai",
                "observed_model": "model",
                "latency": {"t_total": 1.0},
                "technical_error": {"stage": "retrieval", "message": "Bearer secret"},
            },
        }
    )

    assert trace["status"] == "unavailable"
    assert trace["reason"] == "trace_not_recorded"
    assert trace["request_status"] == "technical_error"
    assert trace["diagnostics"]["stage"] == "retrieval"
    assert "secret" not in trace["diagnostics"]["message"]


def test_public_trace_projects_fields_again_and_preserves_partial_error() -> None:
    trace = build_public_retrieval_trace(
        {
            "retrieval_trace": {
                "status": "available",
                "backend": "vertex-qdrant-v3",
                "api_key": "secret",
            },
            "contexts": ["[45/2019/QH14, Điều 25]\nID tài liệu: 123\nExcerpt"],
            "metrics": {
                "request_status": "partial",
                "technical_error": {"stage": "retrieval", "message": "Bearer secret"},
            },
        }
    )
    assert "secret" not in str(trace)
    assert trace["diagnostics"]["stage"] == "retrieval"
    assert trace["evidence"][0]["document_id"] == 123
