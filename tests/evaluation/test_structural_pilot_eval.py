from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.evaluation.provenance import GitProvenance
from app.evaluation.schemas import (
    EvidenceStatus,
    GoldenCase,
    GoldEvidence,
    RequiredLevel,
)
from app.evaluation.structural_pilot_eval import (
    StructuralEvaluationBinding,
    StructuralEvaluationTrace,
    decide_pilot_acceptance,
    run_structural_pilot_evaluation,
    to_metric_v3_trace,
    validate_p2_baseline,
)
from app.ingestion.legal_text import EvidenceChunk
from app.services.structural_retrieval import (
    StructuralCandidate,
    StructuralRetrievalOutcome,
    StructuralRetrievalTrace,
    StructuralSourceHit,
    StructuralTechnicalError,
)


SHA = "a" * 64


def _candidate(
    record_id: str,
    document_id: int,
    *,
    article: str = "Điều 1",
    clause: str | None = None,
) -> StructuralCandidate:
    import hashlib

    body = f"Nội dung {record_id}"
    return StructuralCandidate(
        record_id=record_id,
        document_id=document_id,
        body=body,
        document_number=f"VB-{document_id}",
        title=f"Văn bản {document_id}",
        source_url=f"https://example.test/{document_id}",
        legal_type="Luật",
        article=article,
        clause=clause,
        heading_path=article,
        citation=f"{clause + ', ' if clause else ''}{article}, VB-{document_id}",
        token_count=3,
        dataset_revision="revision-1",
        content_sha256=SHA,
        chunk_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        fused_score=0.5,
    )


def _case(
    case_id: str,
    document_id: int,
    *,
    level: RequiredLevel,
    clause: str | None = None,
) -> GoldenCase:
    return GoldenCase(
        case_id=case_id,
        question=f"Câu hỏi {document_id}",
        question_type="factoid",
        answerable=True,
        reference_answer="Đáp án",
        gold_evidence=[
            GoldEvidence(
                evidence_item_id=f"e-{case_id}",
                case_id=case_id,
                document_id=document_id,
                document_number=f"VB-{document_id}",
                article="Điều 1",
                clause=clause,
                required=True,
                required_level=level,
                status=EvidenceStatus.VERIFIED,
            )
        ],
    )


class FakeRetriever:
    def __init__(self) -> None:
        self.calls = 0

    async def retrieve(self, query: str) -> StructuralRetrievalOutcome:
        self.calls += 1
        document_id = 1 if query.endswith("1") else 2
        clause = "Khoản 1" if document_id == 2 else None
        candidate = _candidate(
            f"r-{document_id}",
            document_id,
            clause=clause,
        )
        source = StructuralSourceHit(
            record_id=candidate.record_id,
            candidate=candidate,
            source_score=0.9,
        )
        return StructuralRetrievalOutcome(
            status="ok",
            evidence=[
                EvidenceChunk(
                    document_id=document_id,
                    document_number=candidate.document_number,
                    title=candidate.title,
                    source_url=candidate.source_url,
                    heading_path=candidate.heading_path,
                    article=candidate.article,
                    clause=candidate.clause,
                    citation=candidate.citation,
                    text=candidate.body,
                    token_count=candidate.token_count,
                )
            ],
            trace=StructuralRetrievalTrace(
                dense_hits=[source],
                bm25_hits=[source],
                exact_hits=[source],
                exact_document_ids=[document_id],
                fused_hits=[candidate],
                reranker_input=[candidate],
                reranker_output=[candidate],
                final_hits=[candidate],
                provider_usage_by_lane={
                    "dense": {"intfloat/multilingual-e5-small": 3}
                },
            ),
            latency={"dense": 0.01, "total": 0.02},
            technical_errors={},
            provider_usage={"intfloat/multilingual-e5-small": 3},
        )


def _binding() -> StructuralEvaluationBinding:
    return StructuralEvaluationBinding(
        dataset_revision="revision-1",
        dataset_sha256="b" * 64,
        sidecar_sha256="c" * 64,
        gold_policy="all-required-verified",
        selected_case_ids_sha256="d" * 64,
        source_state_sha256="e" * 64,
        collection_name="vietlex-legal-rag-v2-pilot-384",
        plan_sha256="1" * 64,
        creation_receipt_sha256="2" * 64,
        probe_report_sha256="3" * 64,
        upload_report_sha256="4" * 64,
        finalize_receipt_sha256="5" * 64,
        verify_receipt_sha256="6" * 64,
        p2_baseline_sha256="7" * 64,
        query_instruction="Retrieve Vietnamese legal provisions.",
        dense_top_k=48,
        bm25_top_k=48,
        fused_limit=64,
        rrf_k=60,
        per_document_limit=4,
    )


def _provenance(source_sha: str = "e" * 64) -> GitProvenance:
    return GitProvenance(
        status="ok",
        repository_root="repo",
        git_sha="f" * 40,
        git_dirty=False,
        git_tracked_dirty=False,
        git_staged_dirty=False,
        git_untracked_dirty=False,
        git_diff_sha256=None,
        git_diff_status="clean",
        source_state_sha256=source_sha,
    )


@pytest.mark.asyncio
async def test_raw_trace_keeps_honest_structural_lane_names(tmp_path: Path) -> None:
    retriever = FakeRetriever()
    run = await run_structural_pilot_evaluation(
        [
            _case("case-1", 1, level=RequiredLevel.ARTICLE),
            _case("case-2", 2, level=RequiredLevel.CLAUSE, clause="Khoản 1"),
        ],
        retriever,
        tmp_path,
        run_id="structural-test",
        binding=_binding(),
        p2_source_document_recall_at_24=0.0,
        skipped_cases={"case-outside": "outside_primary_legislation_scope"},
        provenance=_provenance(),
    )

    raw = json.loads((run.run_dir / "raw_results.json").read_text("utf-8"))
    trace = raw["cases"][0]["trace"]
    assert set(trace) >= {
        "dense_hits",
        "bm25_hits",
        "exact_hits",
        "fused_hits",
        "reranker_input",
        "reranker_output",
        "final_hits",
    }
    assert "pinecone_hits" not in trace
    assert "fts_hits" not in trace
    report = json.loads((run.run_dir / "report.json").read_text("utf-8"))
    assert report["metrics"]["fused_document_recall_at_24"] == {
        "numerator": 2,
        "denominator": 2,
        "value": 1.0,
    }
    assert report["metrics"]["fused_clause_recall_at_24"]["value"] == 1.0
    assert report["coverage"]["skipped_cases"] == ["case-outside"]
    assert report["coverage"]["skip_reasons"] == {
        "outside_primary_legislation_scope": 1
    }
    assert report["technical_errors"]["total"] == 0
    assert report["technical_errors"]["dense"] == 0
    assert report["provider_usage"]["intfloat/multilingual-e5-small"] == 6
    assert report["provider_usage_observation_complete"] is True
    assert report["acceptance"] == "PASS_PILOT"
    assert report["reranker_contribution"]["document"] == {
        "input": {"numerator": 2, "denominator": 2, "value": 1.0},
        "output": {"numerator": 2, "denominator": 2, "value": 1.0},
        "delta": 0.0,
    }
    assert retriever.calls == 2
    manifest = json.loads((run.run_dir / "manifest.json").read_text("utf-8"))
    assert manifest["case_statuses"] == {
        "case-1": "ok",
        "case-2": "ok",
        "case-outside": "skipped:outside_primary_legislation_scope",
    }


def test_metric_adapter_is_explicit_and_raw_model_forbids_aliases() -> None:
    trace = StructuralEvaluationTrace(fused_hits=[])
    adapted = to_metric_v3_trace(trace)
    assert adapted.merged_document_candidates == []
    assert adapted.resolved_document_candidates == []
    with pytest.raises(ValueError):
        StructuralEvaluationTrace.model_validate({"pinecone_hits": []})


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"scope_error_count": 1}, "BLOCKED_SCOPE"),
        ({"technical_error_count": 1}, "BLOCKED_TECHNICAL"),
        ({"provenance_drift": True}, "BLOCKED_TECHNICAL"),
        (
            {
                "fused_document_recall_at_24": 1.0,
                "p2_source_document_recall_at_24": 0.0,
                "fused_article_recall_at_24": 0.95,
                "fused_clause_recall_at_24": 0.90,
                "all_required_coverage": 0.95,
                "no_candidate_rate": 0.0,
                "retrieval_error_rate": 0.0,
                "reranker_error_rate": 0.0,
            },
            "PASS_PILOT",
        ),
        (
            {
                "fused_document_recall_at_24": 0.99,
                "fused_article_recall_at_24": 0.95,
                "fused_clause_recall_at_24": 0.90,
                "all_required_coverage": 0.95,
            },
            "FAIL_QUALITY",
        ),
        (
            {
                "fused_document_recall_at_24": 1.0,
                "fused_article_recall_at_24": 0.95,
                "fused_clause_recall_at_24": 0.90,
                "all_required_coverage": 0.95,
                "no_candidate_rate": 0.01,
            },
            "FAIL_QUALITY",
        ),
        ({"fused_document_recall_at_24": 0.0}, "FAIL_QUALITY"),
    ],
)
def test_acceptance_precedence(values: dict[str, object], expected: str) -> None:
    assert decide_pilot_acceptance(values) == expected


@pytest.mark.asyncio
async def test_source_drift_blocks_before_retriever_call(tmp_path: Path) -> None:
    retriever = FakeRetriever()
    run = await run_structural_pilot_evaluation(
        [_case("case-1", 1, level=RequiredLevel.ARTICLE)],
        retriever,
        tmp_path,
        run_id="source-drift",
        binding=_binding(),
        p2_source_document_recall_at_24=0.0,
        provenance=_provenance("9" * 64),
    )
    assert run.acceptance == "BLOCKED_TECHNICAL"
    assert retriever.calls == 0
    report = json.loads((run.run_dir / "report.json").read_text("utf-8"))
    assert report["provenance_drift"] is True


@pytest.mark.asyncio
async def test_scope_error_blocks_and_run_directory_is_immutable(tmp_path: Path) -> None:
    retriever = FakeRetriever()
    arguments = dict(
        run_id="blocked-scope",
        binding=_binding(),
        p2_source_document_recall_at_24=0.0,
        provenance=_provenance(),
        scope_errors=["dataset_sha256_mismatch"],
    )
    run = await run_structural_pilot_evaluation(
        [_case("case-1", 1, level=RequiredLevel.ARTICLE)],
        retriever,
        tmp_path,
        **arguments,
    )
    assert run.acceptance == "BLOCKED_SCOPE"
    assert retriever.calls == 0
    manifest = json.loads((run.run_dir / "manifest.json").read_text("utf-8"))
    assert manifest["case_statuses"] == {"case-1": "blocked_scope"}
    with pytest.raises(FileExistsError):
        await run_structural_pilot_evaluation(
            [], retriever, tmp_path, **arguments
        )


def test_p2_baseline_requires_exact_shared_scope() -> None:
    binding = _binding()
    comparison = {
        "shared_provenance": {
            "dataset_revision": binding.dataset_revision,
            "dataset_sha256": binding.dataset_sha256,
            "gold_label_sidecar_sha256": binding.sidecar_sha256,
            "gold_policy": binding.gold_policy,
            "selected_case_ids_sha256": binding.selected_case_ids_sha256,
        },
        "profiles": {
            "p": {
                "aggregate_metrics": {
                    "stages": {
                        "source_retrieval_metrics": {
                            "recall": {"document": {"24": {"micro": 0.0}}}
                        }
                    }
                }
            }
        },
    }
    baseline = validate_p2_baseline(comparison, binding)
    assert baseline.source_document_recall_at_24 == 0.0
    comparison["shared_provenance"]["dataset_sha256"] = "0" * 64
    assert validate_p2_baseline(comparison, binding).scope_errors == (
        "dataset_sha256_mismatch",
    )


@pytest.mark.asyncio
async def test_unexpected_retrieval_error_is_typed_and_persisted(
    tmp_path: Path,
) -> None:
    class BrokenRetriever:
        async def retrieve(self, _query: str):
            raise RuntimeError("secret provider detail")

    run = await run_structural_pilot_evaluation(
        [_case("case-1", 1, level=RequiredLevel.ARTICLE)],
        BrokenRetriever(),
        tmp_path,
        run_id="typed-error",
        binding=_binding(),
        p2_source_document_recall_at_24=0.0,
        provenance=_provenance(),
    )
    raw = (run.run_dir / "raw_results.json").read_text("utf-8")
    payload = json.loads(raw)
    assert run.acceptance == "BLOCKED_TECHNICAL"
    assert payload["cases"][0]["status"] == "retrieval_error"
    assert payload["cases"][0]["technical_errors"]["retrieval"][
        "error_type"
    ] == "RuntimeError"
    assert payload["cases"][0]["provider_usage_observation_complete"] is False
    report = json.loads((run.run_dir / "report.json").read_text("utf-8"))
    assert report["provider_usage_observation_complete"] is False
    assert "secret provider detail" not in raw


@pytest.mark.asyncio
async def test_partial_errors_have_separate_honest_operational_rates(
    tmp_path: Path,
) -> None:
    class PartialRetriever:
        def __init__(self) -> None:
            self.inner = FakeRetriever()

        async def retrieve(self, query: str) -> StructuralRetrievalOutcome:
            outcome = await self.inner.retrieve(query)
            stage = "dense" if query.endswith("1") else "reranker_primary"
            outcome.status = "partial_technical_error"
            outcome.technical_errors = {
                stage: StructuralTechnicalError(
                    stage=stage,
                    category="typed_test_error",
                    error_type="RuntimeError",
                    transient=False,
                )
            }
            return outcome

    run = await run_structural_pilot_evaluation(
        [
            _case("case-1", 1, level=RequiredLevel.ARTICLE),
            _case("case-2", 2, level=RequiredLevel.CLAUSE, clause="Khoáº£n 1"),
        ],
        PartialRetriever(),
        tmp_path,
        run_id="partial-errors",
        binding=_binding(),
        p2_source_document_recall_at_24=0.0,
        provenance=_provenance(),
    )

    report = json.loads((run.run_dir / "report.json").read_text("utf-8"))
    metric = report["metrics"]["metric_v3"]
    assert metric["retrieval_technical_error_rate"]["numerator"] == 1
    assert metric["retrieval_technical_error_rate"]["denominator"] == 2
    assert metric["reranker_technical_error_rate"]["numerator"] == 1
    assert metric["reranker_technical_error_rate"]["denominator"] == 2
    assert report["technical_errors"]["dense"] == 1
    assert report["technical_errors"]["bm25"] == 0
    assert report["technical_errors"]["reranker_primary"] == 1
    assert report["technical_errors"]["total"] == 2
    assert run.acceptance == "BLOCKED_TECHNICAL"


@pytest.mark.asyncio
async def test_preflight_block_retains_all_selected_and_skipped_statuses(
    tmp_path: Path,
) -> None:
    retriever = FakeRetriever()
    run = await run_structural_pilot_evaluation(
        [_case("case-1", 1, level=RequiredLevel.ARTICLE)],
        retriever,
        tmp_path,
        run_id="preflight-block",
        binding=_binding(),
        p2_source_document_recall_at_24=0.0,
        skipped_cases={"case-outside": "outside_primary_legislation_scope"},
        provenance=_provenance(),
        technical_preflight_errors=["local_fts_not_ready"],
    )

    manifest = json.loads((run.run_dir / "manifest.json").read_text("utf-8"))
    report = json.loads((run.run_dir / "report.json").read_text("utf-8"))
    assert retriever.calls == 0
    assert manifest["case_statuses"] == {
        "case-1": "blocked_technical",
        "case-outside": "skipped:outside_primary_legislation_scope",
    }
    assert report["coverage"]["selected_case_count"] == 2
    assert report["coverage"]["scored_case_count"] == 0
