from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

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


class _FakeFts:
    def __init__(self, ids: list[int]) -> None:
        self.ids = ids
        self.queries: list[tuple[str, int]] = []

    def search(self, query: str, *, limit: int) -> list[int]:
        self.queries.append((query, limit))
        return list(self.ids)


class _FakeContentStore:
    def __init__(self, documents: dict[int, object]) -> None:
        self.documents = documents
        self.requests: list[list[int]] = []

    def get_many(self, document_ids: list[int]) -> dict[int, object]:
        self.requests.append(list(document_ids))
        return {
            document_id: self.documents[document_id]
            for document_id in document_ids
            if document_id in self.documents
        }


def _stored_document(document_id: int, *, number: str, content: str):
    from types import SimpleNamespace

    return SimpleNamespace(
        metadata=SimpleNamespace(
            document_id=document_id,
            document_number=number,
            title=f"Title {document_id}",
            source_url=f"https://example.test/doc-{document_id}",
        ),
        content=content,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def test_candidate_discovery_is_bounded_per_case_and_preserves_anchor_provenance():
    # Break caught: discovery searches/fetches for each evidence row, loses source ordering,
    # or reports an inferred structural location not backed by the shared anchor matcher.
    from app.evaluation.adjudication_candidates import discover_adjudication_candidates

    case = GoldenCase(
        case_id="discovery-case",
        question="Ap dung 12/2026/ND-CP the nao?",
        question_type="multi-hop",
        answerable=True,
        reference_answer="Theo 13/2026/ND-CP.",
        reference_contexts=[
            "\u0110i\u1ec1u 2\n1. Neo dung cua mot doan tham chieu dai du de xac minh nguon tai lieu nay.",
            "Tham chieu 14/2026/ND-CP.",
        ],
    )
    anchor = case.reference_contexts[0]
    labels = [
        GoldEvidence(
            evidence_item_id="evidence-source", case_id=case.case_id,
            document_id=2, document_number="12/2026/ND-CP", article="\u0110i\u1ec1u 2",
            clause="Kho\u1ea3n 1", required=True, required_level="clause",
            status=EvidenceStatus.AMBIGUOUS,
        ),
        GoldEvidence(
            evidence_item_id="evidence-second", case_id=case.case_id,
            required=False, status=EvidenceStatus.AMBIGUOUS,
        ),
    ]
    fts = _FakeFts([3, 2, 4])
    store = _FakeContentStore({
        2: _stored_document(2, number="12/2026/ND-CP", content=anchor),
        3: _stored_document(3, number="13/2026/ND-CP", content="No anchor."),
        4: _stored_document(4, number="14/2026/ND-CP", content="No anchor either."),
    })

    discovered = discover_adjudication_candidates(
        cases_by_id={case.case_id: case}, labels_by_case_id={case.case_id: labels},
        selected_case_ids=[case.case_id], content_store=store, fts_index=fts,
        candidate_limit=3,
    )

    assert len(fts.queries) == 1
    query, limit = fts.queries[0]
    assert limit == 3
    assert "Ap dung 12/2026/ND-CP the nao?" in query
    assert {"12/2026/ND-CP", "13/2026/ND-CP", "14/2026/ND-CP"} <= set(query.split())
    assert store.requests == [[2, 3, 4]]
    candidates = discovered[case.case_id]
    assert [candidate.document_id for candidate in candidates] == [2, 3, 4, 2, 3, 4]
    assert [candidate.rank for candidate in candidates] == [1, 2, 3, 1, 2, 3]
    reordered = discover_adjudication_candidates(
        cases_by_id={case.case_id: case}, labels_by_case_id={case.case_id: labels},
        selected_case_ids=[case.case_id], content_store=store, fts_index=_FakeFts([4, 3, 2]),
        candidate_limit=3,
    )
    assert candidates[0].candidate_id == reordered[case.case_id][0].candidate_id
    assert candidates[0].document_number == "12/2026/ND-CP"
    assert candidates[0].title == "Title 2"
    assert candidates[0].source_url == "https://example.test/doc-2"
    assert candidates[0].content_sha256 == hashlib.sha256(anchor.encode("utf-8")).hexdigest()
    assert candidates[0].discovery_method == "source_sidecar_document_id"
    assert candidates[0].anchor_match_method == "full_anchor_exact"
    assert candidates[0].anchor_diagnostics == {"full_anchor_matched": True}
    assert candidates[0].article == "\u0110i\u1ec1u 2"
    assert candidates[0].clause == "1"
    assert candidates[0].required_level_supported is True
    assert candidates[1].anchor_match_method == "none"
    assert candidates[1].required_level_supported is False


def test_candidate_discovery_keeps_multihop_evidence_anchors_and_locators_separate():
    # Break caught: one evidence row's anchor or structural locator is reused for another row.
    from app.evaluation.adjudication_candidates import discover_adjudication_candidates

    first_anchor = "\u0110i\u1ec1u 2\n1. Noi dung chung cua bang chung thu nhat du dai de neo."
    second_anchor = "\u0110i\u1ec1u 7\n2. Noi dung chung cua bang chung thu hai du dai de neo."
    case = GoldenCase(
        case_id="multihop-candidates", question="Cau hoi", question_type="multi-hop",
        answerable=True, reference_answer="Tra loi", reference_contexts=[first_anchor, second_anchor],
    )
    labels = [
        GoldEvidence(
            evidence_item_id="first", case_id=case.case_id, context_index=1,
            document_id=11, article="\u0110i\u1ec1u 2", clause="Kho\u1ea3n 1", required=True,
            required_level="clause", status=EvidenceStatus.AMBIGUOUS,
        ),
        GoldEvidence(
            evidence_item_id="second", case_id=case.case_id, context_index=2,
            document_id=12, article="\u0110i\u1ec1u 7", required=True,
            required_level="article", status=EvidenceStatus.AMBIGUOUS,
        ),
    ]
    store = _FakeContentStore({
        11: _stored_document(11, number="11/2026/ND-CP", content=first_anchor),
        12: _stored_document(12, number="12/2026/ND-CP", content=second_anchor),
    })
    fts = _FakeFts([12, 11])

    discovered = discover_adjudication_candidates(
        cases_by_id={case.case_id: case}, labels_by_case_id={case.case_id: labels},
        selected_case_ids=[case.case_id], content_store=store, fts_index=fts,
        candidate_limit=2,
    )[case.case_id]

    assert len(fts.queries) == 1
    assert store.requests == [[11, 12]]
    assert [(item.evidence_item_id, item.document_id) for item in discovered] == [
        ("first", 11), ("first", 12), ("second", 11), ("second", 12),
    ]
    first = discovered[0]
    second = discovered[3]
    assert (first.article, first.clause, first.required_level_supported) == ("\u0110i\u1ec1u 2", "1", True)
    assert (second.article, second.clause, second.required_level_supported) == ("\u0110i\u1ec1u 7", "2", True)
    assert discovered[1].anchor_match_method == "none"
    assert discovered[2].anchor_match_method == "none"


@pytest.mark.parametrize("sha256", ["A" * 64, "a" * 63, "not-a-hash"])
def test_candidate_discovery_rejects_noncanonical_content_hashes(sha256):
    # Break caught: a candidate is emitted for corpus content without a canonical verified hash.
    from app.evaluation.adjudication_candidates import discover_adjudication_candidates

    case = _case("hash-case", "factoid")
    document = _stored_document(9, number="9/2026/ND-CP", content="content")
    document.content_sha256 = sha256
    with pytest.raises(ValueError, match="invalid corpus document identity"):
        discover_adjudication_candidates(
            cases_by_id={case.case_id: case}, labels_by_case_id={case.case_id: [_label(case.case_id)]},
            selected_case_ids=[case.case_id], content_store=_FakeContentStore({9: document}),
            fts_index=_FakeFts([9]), candidate_limit=1,
        )


def test_candidate_discovery_rejects_content_hash_mismatch():
    # Break caught: an apparently canonical content hash is trusted without recomputing the body digest.
    from app.evaluation.adjudication_candidates import discover_adjudication_candidates

    case = _case("mismatch-case", "factoid")
    document = _stored_document(10, number="10/2026/ND-CP", content="content")
    document.content_sha256 = "a" * 64
    with pytest.raises(ValueError, match="invalid corpus document identity"):
        discover_adjudication_candidates(
            cases_by_id={case.case_id: case}, labels_by_case_id={case.case_id: [_label(case.case_id)]},
            selected_case_ids=[case.case_id], content_store=_FakeContentStore({10: document}),
            fts_index=_FakeFts([10]), candidate_limit=1,
        )


def test_candidate_discovery_rejects_boolean_metadata_document_id():
    # Break caught: Python equality permits True == 1 and accepts a corrupted corpus identity.
    from app.evaluation.adjudication_candidates import discover_adjudication_candidates

    case = _case("boolean-metadata-id", "factoid")
    document = _stored_document(1, number="1/2026/ND-CP", content="content")
    document.metadata.document_id = True
    with pytest.raises(ValueError, match="invalid corpus document identity"):
        discover_adjudication_candidates(
            cases_by_id={case.case_id: case}, labels_by_case_id={case.case_id: [_label(case.case_id)]},
            selected_case_ids=[case.case_id], content_store=_FakeContentStore({1: document}),
            fts_index=_FakeFts([1]), candidate_limit=1,
        )


def test_candidate_discovery_chunks_each_document_once_across_evidence_rows(monkeypatch):
    # Break caught: cache lookup evaluates chunk_document again for every matching evidence row.
    import app.evaluation.adjudication_candidates as candidates_module

    anchor = "\u0110i\u1ec1u 2\n1. Bang chung chung du dai de neo van ban nay."
    case = GoldenCase(
        case_id="chunk-cache", question="Cau hoi", question_type="multi-hop",
        answerable=True, reference_answer="Tra loi", reference_contexts=[anchor, anchor],
    )
    labels = [
        GoldEvidence(evidence_item_id="one", case_id=case.case_id, context_index=1, required=True, status=EvidenceStatus.AMBIGUOUS),
        GoldEvidence(evidence_item_id="two", case_id=case.case_id, context_index=2, required=True, status=EvidenceStatus.AMBIGUOUS),
    ]
    document = _stored_document(21, number="21/2026/ND-CP", content=anchor)
    original = candidates_module.chunk_document
    calls = 0

    def counted_chunk_document(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(candidates_module, "chunk_document", counted_chunk_document)
    candidates_module.discover_adjudication_candidates(
        cases_by_id={case.case_id: case}, labels_by_case_id={case.case_id: labels},
        selected_case_ids=[case.case_id], content_store=_FakeContentStore({21: document}),
        fts_index=_FakeFts([21]), candidate_limit=1,
    )

    assert calls == 1


@pytest.mark.parametrize(
    ("candidate_limit", "selected_case_ids", "labels", "documents", "message"),
    [
        (0, ["case"], [GoldEvidence(evidence_item_id="zero", case_id="case", required=True, status=EvidenceStatus.AMBIGUOUS)], {}, "candidate_limit"),
        (1, ["missing"], [], {}, "unknown selected case"),
        (1, ["case"], [], {}, "missing labels"),
        (1, ["case"], [GoldEvidence(evidence_item_id="missing", case_id="case", required=True, status=EvidenceStatus.AMBIGUOUS)], {}, "missing retrieved documents"),
        (1, ["case"], [GoldEvidence(evidence_item_id="bad", case_id="case", document_id="bad", required=True, status=EvidenceStatus.AMBIGUOUS)], {}, "invalid corpus document identity"),
    ],
)
def test_candidate_discovery_fails_closed_for_invalid_inputs(
    candidate_limit, selected_case_ids, labels, documents, message,
):
    # Break caught: invalid discovery inputs silently produce partial or unbounded candidate lists.
    from app.evaluation.adjudication_candidates import discover_adjudication_candidates

    case = _case("case", "factoid")
    with pytest.raises(ValueError, match=message):
        discover_adjudication_candidates(
            cases_by_id={case.case_id: case}, labels_by_case_id={"case": labels},
            selected_case_ids=selected_case_ids, content_store=_FakeContentStore(documents),
            fts_index=_FakeFts([1]), candidate_limit=candidate_limit,
        )


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
    with pytest.raises(ValidationError):
        AdjudicationCandidate(candidate_id=" ", document_id=0, document_number=" ", source_url=" ")

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


@pytest.mark.parametrize("document_id", [True, False, 1.0, 0.0, "", "  "])
def test_candidate_document_id_rejects_coerced_and_blank_values(document_id):
    # Break caught: Pydantic coercion changes booleans/floats into valid integer identities.
    with pytest.raises(ValidationError):
        AdjudicationCandidate(candidate_id="candidate", document_id=document_id)


@pytest.mark.parametrize("document_id", [1, "doc-1"])
def test_candidate_document_id_accepts_strict_positive_int_or_nonblank_string(document_id):
    # Break caught: strict identity validation rejects either supported identifier representation.
    candidate = AdjudicationCandidate(candidate_id="candidate", document_id=document_id)
    assert candidate.document_id == document_id


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
