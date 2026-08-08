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
        candidate_id="candidate-1", document_id=1,
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
    assert row["citation_parse_status"] == "parsed"
    assert row["decision"] == {
        "status": "pending", "selected_candidate_id": None,
        "confidence": "unreviewed", "notes": "", "reviewer_identity": None,
        "reviewed_at_utc": None,
    }
    assert len(canonical_sha256(payload)) == 64
    assert payload["provenance"]["sidecar_sha256"] == "a" * 64


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


def test_queue_rejects_missing_reference_binding_and_malformed_sidecar_hash():
    # Break caught: a row is emitted without a full context/anchor hash or sidecar identity.
    case = _case("case-3", "factoid")
    case.reference_contexts = []
    evidence = _label(case.case_id)
    sidecar = GoldSidecar(
        metadata=GoldSidecarMetadata(sidecar_sha256="not-a-sha"), labels=[evidence],
        labels_by_case_id={case.case_id: [evidence]},
    )
    provenance = _provenance()

    with pytest.raises(ValueError, match="sidecar_sha256"):
        _queue(case, sidecar, provenance)

    sidecar.metadata.sidecar_sha256 = "a" * 64
    with pytest.raises(ValueError, match="reference context"):
        _queue(case, sidecar, provenance)


def test_queue_validates_candidates_and_marks_missing_citation_explicitly():
    # Break caught: malformed discovered candidates pass through, or no citation is ambiguous.
    case = _case("case-4", "factoid")
    evidence = _label(case.case_id)
    sidecar = GoldSidecar(
        metadata=GoldSidecarMetadata(sidecar_sha256="a" * 64), labels=[evidence],
        labels_by_case_id={case.case_id: [evidence]},
    )
    invalid = AdjudicationCandidate(candidate_id=" ", document_id=0, document_number=" ", source_url=" ")

    with pytest.raises(ValueError, match="candidate"):
        _queue(case, sidecar, _provenance(), {evidence.evidence_item_id: [invalid]})

    no_citation = AdjudicationCandidate(
        candidate_id="candidate-4", document_id=4, document_number="4/2020/QH14",
        source_url="https://example.test/doc-4",
    )
    payload = _queue(case, sidecar, _provenance(), {evidence.evidence_item_id: [no_citation]})
    assert payload["rows"][0]["citation_parse_status"] == "none"


@pytest.mark.parametrize(
    "status",
    [EvidenceStatus.REJECTED, EvidenceStatus.CORPUS_MISSING, EvidenceStatus.INSUFFICIENT_EVIDENCE],
)
def test_queue_preserves_negative_source_evidence_and_adjudication_provenance(status):
    # Break caught: queued review erases a prior negative evidence outcome or its audit trail.
    case = _case(f"case-{status.value}", "multi-hop")
    evidence = GoldEvidence(
        evidence_item_id=f"evidence-{status.value}", case_id=case.case_id,
        required=True, status=status, adjudication_queue_sha256="a" * 64,
        adjudication_decision_sha256="b" * 64, adjudication_candidate_id="old-candidate",
        adjudication_confidence="high", adjudication_reviewer_identity="reviewer",
        adjudicated_at_utc="2026-08-08T00:00:00Z", adjudication_notes="retained",
    )
    sidecar = GoldSidecar(
        metadata=GoldSidecarMetadata(sidecar_sha256="c" * 64), labels=[evidence],
        labels_by_case_id={case.case_id: [evidence]},
    )

    payload = _queue(case, sidecar, _provenance())

    row = payload["rows"][0]
    assert row["source_evidence_status"] == status.value
    assert row["source_adjudication_provenance"]["adjudication_candidate_id"] == "old-candidate"
    assert row["decision"]["status"] == "pending"


def test_queue_normalizes_blank_citation_units_to_none_and_rejects_malformed_partial_units():
    # Break caught: whitespace or an invalid locator becomes a false parsed citation.
    case = _case("case-citation-normalization", "factoid")
    blank_evidence = GoldEvidence(
        evidence_item_id="blank-citation", case_id=case.case_id, required=True,
        status=EvidenceStatus.AMBIGUOUS, document_number="  ", article="\t", clause="\n",
    )
    blank_sidecar = GoldSidecar(
        metadata=GoldSidecarMetadata(sidecar_sha256="a" * 64), labels=[blank_evidence],
        labels_by_case_id={case.case_id: [blank_evidence]},
    )
    blank_payload = _queue(case, blank_sidecar, _provenance())
    blank_row = blank_payload["rows"][0]
    assert blank_row["citation_parse_status"] == "none"
    assert blank_row["parsed_citation_units"] == {
        "document_number": None, "article": None, "clause": None,
    }

    malformed_evidence = blank_evidence.model_copy(
        update={"evidence_item_id": "malformed-citation", "article": "not an article"}
    )
    malformed_sidecar = GoldSidecar(
        metadata=GoldSidecarMetadata(sidecar_sha256="a" * 64), labels=[malformed_evidence],
        labels_by_case_id={case.case_id: [malformed_evidence]},
    )
    with pytest.raises(ValueError, match="citation"):
        _queue(case, malformed_sidecar, _provenance())


def test_queue_accepts_and_normalizes_nonblank_string_document_id():
    # Break caught: resolved opaque string document IDs are rejected despite being stable identities.
    case = _case("case-string-document-id", "factoid")
    evidence = _label(case.case_id)
    sidecar = GoldSidecar(
        metadata=GoldSidecarMetadata(sidecar_sha256="a" * 64), labels=[evidence],
        labels_by_case_id={case.case_id: [evidence]},
    )
    candidate = AdjudicationCandidate(
        candidate_id="candidate-string", document_id=" doc-1 ",
        document_number="1/2020/QH14", source_url="https://example.test/doc-1",
    )

    payload = _queue(
        case, sidecar, _provenance(), {evidence.evidence_item_id: [candidate]}
    )

    assert payload["rows"][0]["candidates"][0]["document_id"] == "doc-1"


def _provenance() -> GitProvenance:
    return GitProvenance(
        status="ok", repository_root="repo", git_sha="b" * 40,
        git_dirty=False, git_tracked_dirty=False, git_staged_dirty=False,
        git_untracked_dirty=False, git_diff_sha256=None, git_diff_status="clean",
        source_state_sha256="c" * 64,
    )


def _queue(
    case: GoldenCase,
    sidecar: GoldSidecar,
    provenance: GitProvenance,
    candidates_by_evidence_id: dict[str, list[AdjudicationCandidate]] | None = None,
) -> dict:
    return build_queue_payload(
        cases=[case], sidecar=sidecar, candidates_by_evidence_id=candidates_by_evidence_id or {},
        selected_case_ids=[case.case_id], dataset_sha256="d" * 64,
        corpus_revision="pinned-revision", provenance=provenance,
        command=["python"], candidate_limit=5, selection_seed="p1-v1",
    )
