from __future__ import annotations

import hashlib

import pytest

from app.evaluation.adjudication import (
    AdjudicationCandidate,
    build_decision_template,
    build_queue_payload,
    canonical_sha256,
    select_stratified_case_ids,
)
from app.evaluation.gold_sidecar import GoldSidecar, GoldSidecarMetadata
from app.evaluation.provenance import GitProvenance
from app.evaluation.schemas import EvidenceStatus, GoldEvidence, GoldenCase


def _case(case_id: str, question_type: str) -> GoldenCase:
    return GoldenCase(
        case_id=case_id,
        question=f"Question {case_id}",
        question_type=question_type,
        answerable=True,
        reference_answer="answer",
        reference_contexts=[f"Reference {case_id}"],
    )


def _label(case_id: str) -> GoldEvidence:
    return GoldEvidence(
        evidence_item_id=f"evidence-{case_id}",
        case_id=case_id,
        required=True,
        status=EvidenceStatus.AMBIGUOUS,
    )


def test_stratified_selection_is_deterministic_and_covers_factoid_and_multihop():
    # Break caught: selection ignores the requested seed, range, or question-type strata.
    cases = [
        *[_case(f"factoid-{index:02d}", "factoid") for index in range(30)],
        *[_case(f"multi-hop-{index:02d}", "multi-hop") for index in range(30)],
    ]
    labels_by_case = {case.case_id: [_label(case.case_id)] for case in cases}
    cases_by_id = {case.case_id: case for case in cases}

    selected = select_stratified_case_ids(
        cases, labels_by_case, target_cases=40, seed="p1-v1"
    )

    assert len(selected) == 40
    assert selected == select_stratified_case_ids(
        cases, labels_by_case, target_cases=40, seed="p1-v1"
    )
    assert {cases_by_id[item].question_type for item in selected} == {
        "factoid",
        "multi-hop",
    }
    with pytest.raises(ValueError, match="30 and 50"):
        select_stratified_case_ids(cases, labels_by_case, target_cases=29, seed="p1-v1")


def test_queue_payload_is_pending_only_and_preserves_hashes_citations_and_candidates():
    # Break caught: discovery marks an item verified or loses reference/candidate provenance.
    case = _case("case-1", "factoid")
    evidence = GoldEvidence(
        evidence_item_id="evidence-1",
        case_id=case.case_id,
        document_number="72/2020/QH14",
        article="Điều 3",
        clause="Khoản 8",
        required=True,
        status=EvidenceStatus.AMBIGUOUS,
    )
    sidecar = GoldSidecar(
        metadata=GoldSidecarMetadata(sidecar_sha256="a" * 64),
        labels=[evidence],
        labels_by_case_id={case.case_id: [evidence]},
    )
    provenance = GitProvenance(
        status="ok", repository_root="repo", git_sha="b" * 40,
        git_dirty=False, git_tracked_dirty=False, git_staged_dirty=False,
        git_untracked_dirty=False, git_diff_sha256=None, git_diff_status="clean",
        source_state_sha256="c" * 64,
    )
    candidate = AdjudicationCandidate(
        candidate_id="candidate-1", document_id="doc-1",
        document_number="72/2020/QH14", citation="Điều 3 Khoản 8",
        text="candidate text", source_url="https://example.test/doc-1",
    )

    payload = build_queue_payload(
        cases=[case], sidecar=sidecar,
        candidates_by_evidence_id={evidence.evidence_item_id: [candidate]},
        selected_case_ids=[case.case_id], dataset_sha256="d" * 64,
        corpus_revision="pinned-revision", provenance=provenance,
        command=["python", "-m", "adjudicate"], candidate_limit=5,
        selection_seed="p1-v1",
    )

    row = payload["rows"][0]
    assert row["reference_anchor_sha256"] == hashlib.sha256(
        "Reference case-1".encode("utf-8")
    ).hexdigest()
    assert row["parsed_citation_units"] == {
        "document_number": "72/2020/QH14", "article": "Điều 3", "clause": "Khoản 8"
    }
    assert row["candidates"][0]["candidate_id"] == "candidate-1"
    assert row["decision"] == {
        "status": "pending", "selected_candidate_id": None,
        "confidence": "unreviewed", "notes": "", "reviewer_identity": None,
        "reviewed_at_utc": None,
    }
    assert len(canonical_sha256(payload)) == 64


def test_empty_candidates_stay_pending_and_decision_template_cannot_verify():
    # Break caught: an empty discovery result or generated template auto-promotes evidence.
    case = _case("case-2", "multi-hop")
    evidence = _label(case.case_id)
    sidecar = GoldSidecar(
        metadata=GoldSidecarMetadata(sidecar_sha256="a" * 64), labels=[evidence],
        labels_by_case_id={case.case_id: [evidence]},
    )
    provenance = GitProvenance(
        status="ok", repository_root="repo", git_sha="b" * 40,
        git_dirty=False, git_tracked_dirty=False, git_staged_dirty=False,
        git_untracked_dirty=False, git_diff_sha256=None, git_diff_status="clean",
        source_state_sha256="c" * 64,
    )
    payload = build_queue_payload(
        cases=[case], sidecar=sidecar, candidates_by_evidence_id={},
        selected_case_ids=[case.case_id], dataset_sha256="d" * 64,
        corpus_revision="pinned-revision", provenance=provenance,
        command=["python"], candidate_limit=5, selection_seed="p1-v1",
    )

    assert payload["rows"][0]["candidates"] == []
    queue_sha256 = canonical_sha256(payload)
    template = build_decision_template(payload, queue_sha256)
    assert template["queue_sha256"] == queue_sha256
    assert template["decisions"][0]["decision"]["status"] == "pending"
    assert "verified" not in str(template).casefold()
