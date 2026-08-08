import math

import pytest

from app.evaluation.retrieval_metrics import (
    calculate_case_retrieval_metrics,
)
from app.evaluation.schemas import (
    CandidateChunk,
    EvaluationRunManifest,
    GoldEvidence,
    RetrievalCaseMetricsV3,
    RetrievalStageCapacities,
    RetrievalStageTrace,
    StageCandidate,
)


def gold(
    evidence_id: str,
    *,
    document_id: int,
    document_number: str | None = None,
    article: str | None = None,
    clause: str | None = None,
    level: str = "document",
) -> GoldEvidence:
    return GoldEvidence(
        evidence_item_id=evidence_id,
        case_id="case_001",
        document_id=document_id,
        document_number=document_number,
        article=article,
        clause=clause,
        required=True,
        required_level=level,
        status="verified",
    )


def candidate(
    document_id: int,
    *,
    document_number: str | None = None,
    article: str | None = None,
    clause: str | None = None,
    citation: str = "",
) -> StageCandidate:
    return StageCandidate(
        document_id=document_id,
        document_number=document_number,
        article=article,
        clause=clause,
        citation=citation,
    )


def chunk(
    document_id: int,
    *,
    document_number: str,
    article: str | None = None,
    clause: str | None = None,
    citation: str = "",
) -> CandidateChunk:
    return CandidateChunk(
        document_id=document_id,
        document_number=document_number,
        title="Synthetic legal document",
        source_url=f"https://example.invalid/{document_id}",
        citation=citation,
        article=article,
        clause=clause,
        text="Synthetic evidence text",
        token_count=3,
    )


def capacities() -> RetrievalStageCapacities:
    return RetrievalStageCapacities(
        pinecone_document_limit=24,
        fts_document_limit=12,
        merged_document_limit=36,
        resolved_document_limit=16,
        structural_chunk_limit=None,
        local_chunks_limit=64,
        rerank_input_limit=24,
        rerank_return_limit=3,
        final_evidence_limit=3,
    )


def validated(metrics: dict) -> RetrievalCaseMetricsV3:
    return RetrievalCaseMetricsV3.model_validate(metrics)


def test_required_level_denominators_and_multihop_are_exact() -> None:
    labels = [
        gold("case_001_ev_doc", document_id=1),
        gold(
            "case_001_ev_clause",
            document_id=2,
            document_number="12/2026/NĐ-CP",
            article="Điều 2",
            clause="Khoản 1",
            level="clause",
        ),
    ]
    final = [
        chunk(1, document_number="11/2026/NĐ-CP"),
        chunk(
            2,
            document_number="12/2026/NĐ-CP",
            article="Điều 2",
            clause="Khoản 1",
        ),
    ]

    metrics = validated(
        calculate_case_retrieval_metrics(
            labels,
            final,
            RetrievalStageTrace(
                final_evidence_chunks=[
                    candidate(1, document_number="11/2026/NĐ-CP"),
                    candidate(
                        2,
                        document_number="12/2026/NĐ-CP",
                        article="Điều 2",
                        clause="Khoản 1",
                    ),
                ]
            ),
            capacities(),
        )
    )

    assert metrics.applicable_gold_counts == {
        "document": 2,
        "article": 1,
        "clause": 1,
    }
    assert metrics.matched_gold_counts == {
        "document": 2,
        "article": 1,
        "clause": 1,
    }
    assert metrics.multi_hop.all_required is True
    assert metrics.multi_hop.matched_required_items == 2
    assert metrics.multi_hop.required_items == 2


def test_ndcg_uses_unique_required_evidence_ranks() -> None:
    labels = [
        gold("case_001_ev_01", document_id=1),
        gold("case_001_ev_02", document_id=2),
    ]
    final = [
        chunk(1, document_number="1/2026/QH15"),
        chunk(99, document_number="99/2026/QH15"),
        chunk(2, document_number="2/2026/QH15"),
        chunk(1, document_number="1/2026/QH15"),
    ]
    expected = round(
        (1.0 + 1.0 / math.log2(4))
        / (1.0 + 1.0 / math.log2(3)),
        4,
    )

    metrics = validated(
        calculate_case_retrieval_metrics(
            labels,
            final,
            capacities=capacities(),
        )
    )

    assert metrics.ndcg_at_10.value == expected
    assert metrics.ndcg_at_10.numerator == 1.5
    assert metrics.relevance_definition == (
        "binary_unique_required_evidence_v1"
    )


def test_exact_reference_requires_document_number_and_locators() -> None:
    label = gold(
        "case_001_ev_01",
        document_id=7,
        document_number="12/2026/NĐ-CP",
        article="Điều 5",
        clause="Khoản 2",
        level="clause",
    )
    id_only_match = chunk(
        7,
        document_number="99/2026/NĐ-CP",
        article="Điều 5",
        clause="Khoản 2",
    )
    exact_match = chunk(
        999,
        document_number=" 12/2026/nđ-cp ",
        article="điều 5",
        clause="khoản 2",
    )

    miss = validated(
        calculate_case_retrieval_metrics(
            [label],
            [id_only_match],
            capacities=capacities(),
        )
    )
    hit = validated(
        calculate_case_retrieval_metrics(
            [label],
            [exact_match],
            capacities=capacities(),
        )
    )

    assert miss.exact_reference_hit.value == 0.0
    assert hit.exact_reference_hit.value == 1.0


@pytest.mark.parametrize(
    ("status", "retrieval_error", "reranker_error"),
    [
        ("retrieval_error", True, False),
        ("reranker_error", False, True),
    ],
)
def test_technical_status_suppresses_quality_scoring(
    status: str,
    retrieval_error: bool,
    reranker_error: bool,
) -> None:
    metrics = validated(
        calculate_case_retrieval_metrics(
            [gold("case_001_ev_01", document_id=1)],
            [],
            RetrievalStageTrace(),
            capacities(),
            status=status,
        )
    )

    assert metrics.applicable is False
    assert metrics.skip_reason == status
    assert metrics.retrieval_technical_error is retrieval_error
    assert metrics.reranker_technical_error is reranker_error
    assert metrics.document_recall[1].denominator == 0
    for stage in metrics.stages.values():
        assert stage.scored_case_count == 0
        assert stage.applicable_gold_counts == {
            "document": 0,
            "article": 0,
            "clause": 0,
        }
        assert stage.matched_gold_counts == {
            "document": 0,
            "article": 0,
            "clause": 0,
        }


def test_no_candidate_is_scored_as_zero_not_skipped() -> None:
    metrics = validated(
        calculate_case_retrieval_metrics(
            [gold("case_001_ev_01", document_id=1)],
            [],
            RetrievalStageTrace(),
            capacities(),
            status="no_candidate",
        )
    )

    assert metrics.applicable is True
    assert metrics.skip_reason is None
    assert metrics.no_candidate is True
    assert metrics.document_recall[1].value == 0.0
    assert metrics.ndcg_at_10.value == 0.0


def test_first_loss_uses_parallel_source_union_then_sequential_path() -> None:
    label = gold(
        "case_001_ev_01",
        document_id=1,
        document_number="12/2026/NĐ-CP",
        article="Điều 2",
        clause="Khoản 1",
        level="clause",
    )
    document_candidate = candidate(1, document_number="12/2026/NĐ-CP")
    structural_candidate = candidate(
        1,
        document_number="12/2026/NĐ-CP",
        article="Điều 2",
        clause="Khoản 1",
    )
    trace = RetrievalStageTrace(
        pinecone_hits=[document_candidate],
        fts_hits=[],
        merged_document_candidates=[document_candidate],
        resolved_document_candidates=[document_candidate],
        structural_chunks_generated=[structural_candidate],
        locally_selected_chunks=[],
        reranker_input_chunks=[],
        reranker_output_chunks=[],
        final_evidence_chunks=[],
    )

    metrics = validated(
        calculate_case_retrieval_metrics(
            [label],
            [],
            trace,
            capacities(),
        )
    )

    assert metrics.first_loss_by_evidence == {
        "case_001_ev_01": "local_selection_metrics"
    }
    assert metrics.stages["pinecone_document_metrics"].matched_gold_counts[
        "document"
    ] == 1
    assert metrics.stages["fts_document_metrics"].matched_gold_counts[
        "document"
    ] == 0
    assert metrics.stages["source_retrieval_metrics"].matched_gold_counts[
        "document"
    ] == 1


def test_stage_capacity_controls_recall_applicability() -> None:
    label = gold(
        "case_001_ev_01",
        document_id=1,
        document_number="12/2026/NĐ-CP",
        article="Điều 2",
        level="article",
    )
    final = [
        chunk(
            1,
            document_number="12/2026/NĐ-CP",
            article="Điều 2",
        )
    ]
    metrics = validated(
        calculate_case_retrieval_metrics(
            [label],
            final,
            RetrievalStageTrace(
                final_evidence_chunks=[
                    candidate(
                        1,
                        document_number="12/2026/NĐ-CP",
                        article="Điều 2",
                    )
                ]
            ),
            capacities(),
        )
    )
    final_stage = metrics.stages["final_evidence_metrics"]

    assert final_stage.recall["article"][3].value == 1.0
    assert final_stage.recall["article"][6].value is None
    assert final_stage.recall["article"][6].reason == (
        "k_exceeds_configured_capacity"
    )


def test_metric_version_is_single_v3_contract() -> None:
    assert (
        EvaluationRunManifest.model_fields["code_metric_version"].default
        == "3.0.0"
    )
    metrics = validated(
        calculate_case_retrieval_metrics(
            [gold("case_001_ev_01", document_id=1)],
            [],
            capacities=capacities(),
            status="no_candidate",
        )
    )
    assert metrics.metric_version == "3.0.0"
