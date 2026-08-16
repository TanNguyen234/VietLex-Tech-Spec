from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

import app.evaluation.adjudication as adjudication_module
from app.evaluation.adjudication import (
    AdjudicationCandidate,
    artifact_sha256,
    build_promotion_summary,
    build_promotion_preview,
    build_decision_template,
    build_queue_payload,
    canonical_sha256,
    select_stratified_case_ids,
    validate_preview_approval,
    validate_decisions,
)
from app.evaluation.artifact_io import (
    ArtifactCollisionError,
    canonical_json_bytes,
    write_immutable_json,
)
from app.evaluation.gold_sidecar import GoldSidecar, GoldSidecarMetadata, load_gold_sidecar
from app.evaluation.provenance import GitProvenance
from app.evaluation.schemas import EvidenceStatus, GoldEvidence, GoldenCase


def test_adjudication_json_artifacts_are_checked_out_with_lf_bytes() -> None:
    # Break caught: core.autocrlf rewrites immutable JSON bytes after checkout.
    root = Path(__file__).resolve().parents[2]
    sample = "docs/evaluation/adjudication/queues/example/queue.json"
    result = subprocess.run(
        ["git", "check-attr", "text", "eol", "--", sample],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert f"{sample}: text: set" in result.stdout
    assert f"{sample}: eol: lf" in result.stdout


def test_artifact_sha256_hashes_exact_canonical_artifact_bytes():
    # Break caught: an immutable artifact hash is computed from compact semantic JSON bytes.
    payload = {"text": "Luật", "nested": {"value": 1}}
    expected = hashlib.sha256(
        b'{\n  "nested": {\n    "value": 1\n  },\n  "text": "Lu\xe1\xba\xadt"\n}\n'
    ).hexdigest()

    assert adjudication_module.artifact_sha256(payload) == expected
    assert adjudication_module.artifact_sha256(payload) != canonical_sha256(payload)


def test_candidate_identity_sha256_binds_corpus_identity_fields():
    # Break caught: a candidate ID omits a corpus identity field or uses unstable JSON bytes.
    expected = hashlib.sha256(
        b'{"content_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        b'"document_id":7,"document_number":"7/2026/ND-CP",'
        b'"source_url":"https://example.test/doc-7"}'
    ).hexdigest()

    assert adjudication_module.candidate_identity_sha256(
        7,
        "7/2026/ND-CP",
        "https://example.test/doc-7",
        "a" * 64,
    ) == expected


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


class _ScanningFakeContentStore(_FakeContentStore):
    def __init__(self, documents: dict[int, object]) -> None:
        super().__init__(documents)
        self.scan_requests: list[tuple[tuple[str, ...], int, int]] = []

    def iter_document_ids_by_legal_types(
        self,
        legal_types: list[str] | tuple[str, ...],
        *,
        after_id: int,
        limit: int,
    ) -> list[int]:
        requested = tuple(legal_types)
        self.scan_requests.append((requested, after_id, limit))
        return [
            document_id
            for document_id, document in sorted(self.documents.items())
            if document_id > after_id
            and document.metadata.legal_type in requested
        ][:limit]


def _stored_document(
    document_id: int,
    *,
    number: str,
    content: str,
    legal_type: str = "Quyết định",
):
    from types import SimpleNamespace

    return SimpleNamespace(
        metadata=SimpleNamespace(
            document_id=document_id,
            document_number=number,
            title=f"Title {document_id}",
            source_url=f"https://example.test/doc-{document_id}",
            legal_type=legal_type,
        ),
        content=content,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def test_normalized_anchor_match_preserves_exact_match_contract():
    # Break caught: the scan-optimized matcher diverges from the shared exact
    # anchor contract used by the audit and adjudication paths.
    from audit_golden_dataset import check_normalized_anchor_match

    assert check_normalized_anchor_match(
        "điều 2 nội dung nguồn",
        "mở đầu điều 2 nội dung nguồn kết thúc",
    ) == (
        True,
        "full_anchor_exact",
        {"full_anchor_matched": True},
    )


def test_candidate_discovery_scans_normative_anchors_before_fts_noise():
    # Break caught: a raw golden anchor cannot surface its source law when the
    # source title and document number are absent from the golden row.
    from app.evaluation.adjudication_candidates import discover_adjudication_candidates

    anchor = (
        "Điều 2\n"
        "1. Nội dung nguồn pháp luật đủ dài để xác minh chính xác."
    )
    case = GoldenCase(
        case_id="anchor-scan",
        question="Nội dung được quy định thế nào?",
        question_type="factoid",
        answerable=True,
        reference_answer="Trả lời",
        reference_contexts=[anchor],
    )
    evidence = GoldEvidence(
        evidence_item_id="anchor-evidence",
        case_id=case.case_id,
        article="Điều 2",
        required=True,
        required_level="article",
        status=EvidenceStatus.NO_CITATION_EXTRACTED,
    )
    store = _ScanningFakeContentStore({
        2: _stored_document(
            2,
            number="2/QĐ",
            content="Không có anchor.",
        ),
        9: _stored_document(
            9,
            number="9/2026/QH15",
            content=anchor,
            legal_type="Luật",
        ),
    })

    candidates = discover_adjudication_candidates(
        cases_by_id={case.case_id: case},
        labels_by_case_id={case.case_id: [evidence]},
        selected_case_ids=[case.case_id],
        content_store=store,
        fts_index=_FakeFts([2]),
        candidate_limit=2,
    )[case.case_id]

    assert [item.document_id for item in candidates] == [9, 2]
    assert candidates[0].discovery_method == "normative_anchor_scan"
    assert candidates[0].required_level_supported is True
    assert candidates[0].anchor_diagnostics["anchor_scan_tier"] == (
        "primary_normative"
    )
    assert candidates[0].anchor_diagnostics["corpus_search_complete"] is False
    assert {
        request[0] for request in store.scan_requests
    } == {("Hiến pháp", "Luật", "Pháp lệnh")}


def test_candidate_discovery_falls_back_to_secondary_normative_tier():
    # Break caught: an anchor absent from primary sources never reaches the
    # bounded secondary normative tier.
    from app.evaluation.adjudication_candidates import discover_adjudication_candidates

    anchor = "Điều 3\n1. Nội dung nghị định dùng làm nguồn tham chiếu."
    case = GoldenCase(
        case_id="secondary-anchor-scan",
        question="Nguồn quy định thế nào?",
        question_type="factoid",
        answerable=True,
        reference_answer="Trả lời",
        reference_contexts=[anchor],
    )
    evidence = GoldEvidence(
        evidence_item_id="secondary-anchor-evidence",
        case_id=case.case_id,
        required=True,
        required_level="document",
        status=EvidenceStatus.NO_CITATION_EXTRACTED,
    )
    store = _ScanningFakeContentStore({
        3: _stored_document(
            3,
            number="3/2026/NĐ-CP",
            content=anchor,
            legal_type="Nghị định",
        ),
    })

    candidate = discover_adjudication_candidates(
        cases_by_id={case.case_id: case},
        labels_by_case_id={case.case_id: [evidence]},
        selected_case_ids=[case.case_id],
        content_store=store,
        fts_index=_FakeFts([]),
        candidate_limit=1,
    )[case.case_id][0]

    assert candidate.document_id == 3
    assert candidate.anchor_diagnostics["anchor_scan_tier"] == (
        "secondary_normative"
    )
    assert {request[0] for request in store.scan_requests} == {
        ("Hiến pháp", "Luật", "Pháp lệnh"),
        (
            "Nghị định",
            "Nghị quyết",
            "Thông tư",
            "Thông tư liên tịch",
            "Văn bản hợp nhất",
            "Quy định",
            "Quy chế",
        ),
    }


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


def test_candidate_discovery_rejects_out_of_range_context_index():
    # Break caught: discovery continues with an empty anchor for an invalid context binding.
    case = _case("discovery-context-index", "factoid")
    evidence = GoldEvidence(
        evidence_item_id="bad-context",
        case_id=case.case_id,
        context_index=2,
        required=True,
        status=EvidenceStatus.AMBIGUOUS,
    )
    document = _stored_document(8, number="8/2026/ND-CP", content="content")

    with pytest.raises(ValueError, match="context_index"):
        from app.evaluation.adjudication_candidates import discover_adjudication_candidates

        discover_adjudication_candidates(
            cases_by_id={case.case_id: case},
            labels_by_case_id={case.case_id: [evidence]},
            selected_case_ids=[case.case_id],
            content_store=_FakeContentStore({8: document}),
            fts_index=_FakeFts([8]),
            candidate_limit=1,
        )


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


def _label(
    case_id: str,
    *,
    status: EvidenceStatus = EvidenceStatus.AMBIGUOUS,
    required: bool = True,
    required_level: str = "article",
    **updates,
) -> GoldEvidence:
    payload = {
        "evidence_item_id": f"evidence-{case_id}",
        "case_id": case_id,
        "required": required,
        "required_level": required_level,
        "status": status,
    }
    payload.update(updates)
    return GoldEvidence(**payload)


def test_stratified_selection_is_deterministic_and_covers_factoid_and_multihop():
    # Break caught: selection ignores the requested seed, range, or question-type strata.
    cases = [
        *[_case(f"factoid-{index:02d}", "factoid") for index in range(20)],
        *[_case(f"multi-hop-{index:02d}", "multi-hop") for index in range(20)],
    ]
    labels_by_case = {case.case_id: [_label(case.case_id)] for case in cases}
    cases_by_id = {case.case_id: case for case in cases}

    selected = select_stratified_case_ids(
        cases, labels_by_case, target_cases=20, seed="p1-v1"
    )

    assert len(selected) == 20
    assert selected == select_stratified_case_ids(
        cases, labels_by_case, target_cases=20, seed="p1-v1"
    )
    assert {cases_by_id[item].question_type for item in selected} == {
        "factoid",
        "multi-hop",
    }
    with pytest.raises(ValueError, match="must be exactly 20"):
        select_stratified_case_ids(cases, labels_by_case, target_cases=19, seed="p1-v1")


def test_stratified_selection_round_robins_compound_required_level_strata():
    # Break caught: selection quotas only by question type and drops a sparse evidence level.
    cases = [_case(f"document-{index:02d}", "factoid") for index in range(30)]
    cases.extend([
        _case("factoid-clause", "factoid"),
        _case("multi-article", "multi-hop"),
    ])
    labels_by_case = {
        case.case_id: [
            GoldEvidence(
                evidence_item_id=f"evidence-{case.case_id}",
                case_id=case.case_id,
                required=True,
                required_level=(
                    "clause" if case.case_id == "factoid-clause"
                    else "article" if case.case_id == "multi-article"
                    else "document"
                ),
                status=EvidenceStatus.AMBIGUOUS,
            )
        ]
        for case in cases
    }
    labels_by_case["factoid-clause"].append(
        GoldEvidence(
            evidence_item_id="factoid-clause-document",
            case_id="factoid-clause",
            required=True,
            required_level="document",
            status=EvidenceStatus.AMBIGUOUS,
        )
    )

    selected = select_stratified_case_ids(
        cases, labels_by_case, target_cases=20, seed="compound-v1"
    )

    assert len(selected) == 20
    assert "factoid-clause" in selected
    assert "multi-article" in selected
    assert selected == select_stratified_case_ids(
        cases, labels_by_case, target_cases=20, seed="compound-v1"
    )


def test_stratified_selection_fails_closed_when_fewer_than_target():
    # Break caught: fewer than 20 eligible cases fails closed with ValueError.
    cases = [_case(f"scarce-{index:02d}", "factoid") for index in range(7)]
    labels_by_case = {case.case_id: [_label(case.case_id)] for case in cases}

    with pytest.raises(ValueError, match="insufficient_eligible_cases"):
        select_stratified_case_ids(
            cases, labels_by_case, target_cases=20, seed="scarce-v1"
        )


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
    candidate = _candidate(
        evidence.evidence_item_id,
        document_id=1,
        document_number="72/2020/QH14",
        citation="Điều 3 Khoản 8",
        text="candidate text",
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
    assert row["candidates"][0]["candidate_id"] == candidate.candidate_id
    assert row["citation_parse_status"] == "parsed"
    assert row["decision"] == {
        "status": "pending", "selected_candidate_id": None,
        "confidence": "unreviewed", "notes": "", "reviewer_identity": None,
        "reviewed_at_utc": None,
    }
    assert len(canonical_sha256(payload)) == 64
    assert payload["provenance"]["sidecar_sha256"] == "a" * 64


def test_queue_metadata_blocks_insufficient_selection_with_compound_diagnostics():
    # Break caught: an undersized queue is labeled blocked with deterministic shortfall.
    case = _case("blocked-case", "factoid")
    evidence = _label(case.case_id)
    sidecar = GoldSidecar(
        metadata=GoldSidecarMetadata(sidecar_sha256="a" * 64),
        labels=[evidence],
        labels_by_case_id={case.case_id: [evidence]},
    )

    payload = build_queue_payload(
        cases=[case],
        sidecar=sidecar,
        candidates_by_evidence_id={},
        selected_case_ids=[case.case_id],
        dataset_sha256="d" * 64,
        corpus_revision="pinned-revision",
        provenance=_provenance(),
        command=["python"],
        candidate_limit=5,
        selection_seed="vietlex-p2-v1",
        target_case_count=20,
    )

    assert payload["target_case_count"] == 20
    assert payload["selected_case_count"] == 1
    assert payload["provider_calls"] == 0
    assert payload["queue_status"] == "BLOCKED_INSUFFICIENT_ELIGIBLE_CASES"
    assert payload["selection_diagnostics"]["eligible_case_count"] == 1
    assert payload["selection_diagnostics"]["shortfall"] == 19
    assert payload["selection_diagnostics"]["selection_policy"] == "underrepresented_document_then_legal_type_then_sha256"


def test_queue_binds_exact_indexed_context_and_preserves_legacy_anchor_hash():
    # Break caught: a 16-character legacy hash replaces the full hash of context_index=2.
    first_context = "First reference context."
    second_context = "Second reference context."
    case = _case("indexed-context", "multi-hop")
    case.reference_contexts = [first_context, second_context]
    evidence = GoldEvidence(
        evidence_item_id="indexed-evidence",
        case_id=case.case_id,
        context_index=2,
        citation_index=3,
        reference_anchor_hash="086708511bbf4d19",
        required=True,
        status=EvidenceStatus.AMBIGUOUS,
    )
    sidecar = GoldSidecar(
        metadata=GoldSidecarMetadata(sidecar_sha256="a" * 64),
        labels=[evidence],
        labels_by_case_id={case.case_id: [evidence]},
    )

    row = _queue(case, sidecar, _provenance())["rows"][0]

    assert row["context_index"] == 2
    assert row["citation_index"] == 3
    assert row["reference_anchor_sha256"] == hashlib.sha256(
        second_context.encode("utf-8")
    ).hexdigest()
    assert row["reference_anchor_sha256"] != hashlib.sha256(
        first_context.encode("utf-8")
    ).hexdigest()
    assert row["reference_anchor_legacy_hash"] == "086708511bbf4d19"


def test_queue_rejects_out_of_range_reference_context_index():
    # Break caught: an invalid positive context index silently binds the first context.
    case = _case("bad-context-index", "factoid")
    evidence = GoldEvidence(
        evidence_item_id="bad-context-evidence",
        case_id=case.case_id,
        context_index=2,
        required=True,
        status=EvidenceStatus.AMBIGUOUS,
    )
    sidecar = GoldSidecar(
        metadata=GoldSidecarMetadata(sidecar_sha256="a" * 64),
        labels=[evidence],
        labels_by_case_id={case.case_id: [evidence]},
    )

    with pytest.raises(ValueError, match="context_index"):
        _queue(case, sidecar, _provenance())


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
    queue_sha256 = artifact_sha256(payload)
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

    no_citation = _candidate(
        evidence.evidence_item_id,
        document_id=4,
        document_number="4/2020/QH14",
    )
    payload = _queue(case, sidecar, _provenance(), {evidence.evidence_item_id: [no_citation]})
    assert payload["rows"][0]["citation_parse_status"] == "none"


@pytest.mark.parametrize(
    ("candidate_update", "message"),
    [
        ({"content_sha256": None}, "content_sha256"),
        ({"content_sha256": "A" * 64}, "content_sha256"),
        ({"candidate_id": "a" * 64}, "candidate_id"),
        ({"evidence_item_id": "other-evidence"}, "evidence_item_id"),
        ({"rank": 0}, "rank"),
    ],
)
def test_queue_rejects_unbound_candidate_identity_fields(candidate_update, message):
    # Break caught: a queue persists a candidate not bound to exact content and evidence.
    case = _case("candidate-binding", "factoid")
    evidence = _label(case.case_id)
    sidecar = GoldSidecar(
        metadata=GoldSidecarMetadata(sidecar_sha256="a" * 64),
        labels=[evidence],
        labels_by_case_id={case.case_id: [evidence]},
    )
    candidate = _candidate(evidence.evidence_item_id).model_copy(update=candidate_update)

    with pytest.raises(ValueError, match=message):
        _queue(
            case,
            sidecar,
            _provenance(),
            {evidence.evidence_item_id: [candidate]},
        )


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
        adjudicated_at_utc="2026-08-08T00:00:00Z", adjudication_notes_sha256="d" * 64,
        adjudication_notes="retained",
    )
    sidecar = GoldSidecar(
        metadata=GoldSidecarMetadata(sidecar_sha256="c" * 64), labels=[evidence],
        labels_by_case_id={case.case_id: [evidence]},
    )

    payload = _queue(case, sidecar, _provenance())

    row = payload["rows"][0]
    assert row["source_evidence_status"] == status.value
    assert row["source_adjudication_provenance"]["adjudication_candidate_id"] == "old-candidate"
    assert row["source_adjudication_provenance"]["adjudication_notes_sha256"] == "d" * 64
    assert "adjudication_notes" not in row["source_adjudication_provenance"]
    assert "retained" not in json.dumps(payload)
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
    candidate = _candidate(
        evidence.evidence_item_id,
        document_id=" doc-1 ",
        document_number="1/2020/QH14",
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


def _candidate(
    evidence_item_id: str,
    *,
    document_id: int | str = 7,
    document_number: str = "7/2026/ND-CP",
    source_url: str | None = None,
    content_sha256: str = "e" * 64,
    rank: int = 1,
    **updates,
) -> AdjudicationCandidate:
    normalized_document_id = document_id.strip() if isinstance(document_id, str) else document_id
    normalized_document_number = document_number.strip()
    normalized_source_url = (
        source_url or f"https://example.test/doc-{normalized_document_id}"
    ).strip()
    payload = {
        "candidate_id": adjudication_module.candidate_identity_sha256(
            normalized_document_id,
            normalized_document_number,
            normalized_source_url,
            content_sha256,
        ),
        "evidence_item_id": evidence_item_id,
        "document_id": document_id,
        "document_number": document_number,
        "source_url": normalized_source_url,
        "content_sha256": content_sha256,
        "rank": rank,
        "article": "Article 2",
        "clause": "1",
        "anchor_match_method": "full_anchor_exact",
        "structural_chunk_sha256": "f" * 64,
        "required_level_supported": True,
    }
    payload.update(updates)
    return AdjudicationCandidate(**payload)


def _queue(
    case: GoldenCase,
    sidecar: GoldSidecar,
    provenance: GitProvenance,
    candidates_by_evidence_id: dict[str, list[AdjudicationCandidate]] | None = None,
) -> dict:
    return build_queue_payload(
        cases=[case],
        sidecar=sidecar,
        candidates_by_evidence_id=candidates_by_evidence_id or {},
        selected_case_ids=[case.case_id],
        dataset_sha256="d" * 64,
        corpus_revision="pinned-revision",
        provenance=provenance,
        command=["python"],
        candidate_limit=5,
        selection_seed="vietlex-p2-v1",
        target_case_count=20,
    )


def _review_queue(*, required_level: str = "article") -> tuple[dict, str]:
    case = _case("review-case", "factoid")
    evidence = GoldEvidence(
        evidence_item_id="review-evidence", case_id=case.case_id, required=True,
        required_level=required_level, status=EvidenceStatus.AMBIGUOUS,
    )
    sidecar = GoldSidecar(
        metadata=GoldSidecarMetadata(sidecar_sha256="a" * 64), labels=[evidence],
        labels_by_case_id={case.case_id: [evidence]},
    )
    candidate = _candidate(evidence.evidence_item_id)
    queue = _queue(
        case, sidecar, _provenance(), {evidence.evidence_item_id: [candidate]}
    )
    return queue, artifact_sha256(queue)


def _review_decisions(queue_sha256: str, *, status: str = "verified", **updates) -> dict:
    decision = {
        "status": status,
        "selected_candidate_id": (
            _candidate("review-evidence").candidate_id if status == "verified" else None
        ),
        "confidence": "high",
        "notes": "Reviewed against the cited legal text.",
        "reviewer_identity": "legal-reviewer-01",
        "reviewed_at_utc": "2026-08-08T01:02:03Z",
    }
    decision.update(updates)
    return {
        "schema_version": "1.0.0", "queue_sha256": queue_sha256,
        "decisions": [{
            "queue_row_id": "5d236ae10bc9abf4ef3e0ce259cc0c9b919db8dcf113abf172cc2b23ed1e959c",
            "evidence_item_id": "review-evidence", "decision": decision,
        }],
    }


def _source_sidecar() -> dict:
    return {
        "schema_version": "2.0.0", "dataset_name": "test", "total_cases": 2,
        "total_evidence_items": 2,
        "labels": [
            {"evidence_item_id": "review-evidence", "case_id": "review-case", "required": True,
             "required_level": "article", "status": "ambiguous"},
            {"evidence_item_id": "other-evidence", "case_id": "other-case", "required": False,
             "required_level": "document", "status": "rejected"},
        ],
    }


def test_validate_decisions_normalizes_complete_resolved_decision_in_queue_order():
    # Break caught: a decision artifact can be accepted without binding every resolved review to its queue row.
    queue, queue_sha256 = _review_queue()
    decisions = _review_decisions(queue_sha256)
    decisions["decisions"][0]["queue_row_id"] = queue["rows"][0]["queue_row_id"]

    validated = validate_decisions(queue, decisions, queue_sha256=queue_sha256)

    assert [item.status for item in validated] == ["verified"]
    assert validated[0].reviewer_identity == "legal-reviewer-01"
    assert validated[0].reviewed_at_utc == "2026-08-08T01:02:03Z"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda queue, decisions: decisions.update(queue_sha256="b" * 64), "queue_sha256"),
        (lambda queue, decisions: decisions.update(schema_version="2.0.0"), "schema_version"),
        (lambda queue, decisions: decisions["decisions"].append(dict(decisions["decisions"][0])), "duplicate"),
        (lambda queue, decisions: decisions["decisions"][0]["decision"].update(status="pending"), "pending"),
        (lambda queue, decisions: decisions["decisions"][0]["decision"].update(reviewer_identity=" "), "reviewer"),
        (lambda queue, decisions: decisions["decisions"][0]["decision"].update(reviewed_at_utc="2026-08-08T01:02:03+01:00"), "UTC"),
        (lambda queue, decisions: decisions["decisions"][0]["decision"].update(confidence="certain"), "confidence"),
        (lambda queue, decisions: decisions["decisions"][0]["decision"].update(confidence="medium", notes=""), "notes"),
        (lambda queue, decisions: decisions["decisions"][0]["decision"].update(selected_candidate_id="missing"), "candidate"),
    ],
)
def test_validate_decisions_fails_closed_for_unbound_or_incomplete_resolution(mutate, message):
    # Break caught: malformed human artifacts silently yield a partial promotion preview.
    queue, queue_sha256 = _review_queue()
    decisions = _review_decisions(queue_sha256)
    decisions["decisions"][0]["queue_row_id"] = queue["rows"][0]["queue_row_id"]
    mutate(queue, decisions)

    with pytest.raises(ValueError, match=message):
        validate_decisions(queue, decisions, queue_sha256=queue_sha256)


@pytest.mark.parametrize(
    ("candidate_update", "required_level", "message"),
    [
        ({"anchor_match_method": "none"}, "document", "anchor"),
        ({"article": None}, "article", "Article"),
        ({"clause": None}, "clause", "Clause"),
        ({"structural_chunk_sha256": None}, "article", "structural_chunk_sha256"),
        ({"structural_chunk_sha256": "A" * 64}, "clause", "structural_chunk_sha256"),
        ({"required_level_supported": False}, "document", "required_level"),
        ({"evidence_item_id": "other-evidence"}, "document", "evidence"),
        ({"source_url": None}, "document", "source_url"),
    ],
)
def test_validate_decisions_requires_candidate_identity_anchor_and_structure(candidate_update, required_level, message):
    # Break caught: a verified label is derived from a candidate that does not prove the requested evidence level.
    queue, queue_sha256 = _review_queue(required_level=required_level)
    queue["rows"][0]["candidates"][0].update(candidate_update)
    queue_sha256 = artifact_sha256(queue)
    decisions = _review_decisions(queue_sha256)
    decisions["decisions"][0]["queue_row_id"] = queue["rows"][0]["queue_row_id"]

    with pytest.raises(ValueError, match=message):
        validate_decisions(queue, decisions, queue_sha256=queue_sha256)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda queue: queue.update(schema_version="2.0.0"), "queue schema_version"),
        (lambda queue: queue.update(target_case_count=29), "target_case_count"),
        (lambda queue: queue.update(selected_case_count=2), "selected_case_count"),
        (lambda queue: queue.update(provider_calls=1), "provider_calls"),
        (lambda queue: queue.update(selected_case_ids=["review-case", " "]), "nonblank"),
        (lambda queue: queue.update(selected_case_ids=["review-case", "missing-case"], selected_case_count=2), "row case IDs"),
        (lambda queue: queue["rows"][0].update(case_id="injected-case"), "row case IDs"),
        (lambda queue: queue.update(queue_status="READY_FOR_REVIEW"), "queue_status"),
    ],
)
def test_validate_decisions_rejects_selected_case_and_row_set_drift(mutate, message):
    # Break caught: a queue adds/drops a selected case or injects an unselected row.
    queue, _ = _review_queue()
    mutate(queue)
    queue_sha256 = artifact_sha256(queue)
    decisions = _review_decisions(queue_sha256, status="rejected")
    decisions["decisions"][0]["queue_row_id"] = queue["rows"][0]["queue_row_id"]

    with pytest.raises(ValueError, match=message):
        validate_decisions(queue, decisions, queue_sha256=queue_sha256)


@pytest.mark.parametrize(
    ("candidate_update", "message"),
    [
        ({"content_sha256": None}, "content_sha256"),
        ({"content_sha256": "A" * 64}, "content_sha256"),
        ({"candidate_id": "a" * 64}, "candidate_id"),
        ({"evidence_item_id": "other-evidence"}, "evidence_item_id"),
        ({"rank": 0}, "rank"),
        ({"document_number": " 7/2026/ND-CP"}, "noncanonical"),
    ],
)
def test_validate_decisions_rejects_noncanonical_or_forged_loaded_candidate(
    candidate_update, message,
):
    # Break caught: negative review lets an unbound loaded candidate bypass queue validation.
    queue, _ = _review_queue()
    queue["rows"][0]["candidates"][0].update(candidate_update)
    queue_sha256 = artifact_sha256(queue)
    decisions = _review_decisions(queue_sha256, status="rejected")
    decisions["decisions"][0]["queue_row_id"] = queue["rows"][0]["queue_row_id"]

    with pytest.raises(ValueError, match=message):
        validate_decisions(queue, decisions, queue_sha256=queue_sha256)


def test_validate_decisions_rejects_document_id_whitespace_hidden_by_pydantic():
    # Break caught: Pydantic strips a raw document ID before the noncanonical check sees it.
    queue, _ = _review_queue()
    candidate = queue["rows"][0]["candidates"][0]
    candidate["document_id"] = " doc-7 "
    candidate["candidate_id"] = adjudication_module.candidate_identity_sha256(
        "doc-7",
        candidate["document_number"],
        candidate["source_url"],
        candidate["content_sha256"],
    )
    queue_sha256 = artifact_sha256(queue)
    decisions = _review_decisions(queue_sha256, status="rejected")
    decisions["decisions"][0]["queue_row_id"] = queue["rows"][0]["queue_row_id"]

    with pytest.raises(ValueError, match="noncanonical"):
        validate_decisions(queue, decisions, queue_sha256=queue_sha256)


def test_promotion_preview_is_hashed_pure_and_redacts_notes_while_preserving_negative_decisions():
    # Break caught: preview leaks review notes, loses rejected outcomes, or mutates labels outside the review queue.
    queue, queue_sha256 = _review_queue()
    decisions = _review_decisions(
        queue_sha256, status="rejected", notes="Private note: source was superseded."
    )
    decisions["decisions"][0]["queue_row_id"] = queue["rows"][0]["queue_row_id"]
    source = _source_sidecar()

    preview = build_promotion_preview(
        queue_payload=queue, queue_sha256=queue_sha256, decisions_payload=decisions,
        decisions_sha256=artifact_sha256(decisions),
        source_sidecar_payload=source, source_sidecar_sha256="d" * 64,
        dataset_case_ids=["review-case", "other-case"], provenance=_provenance(),
    )

    proposed = preview["proposed_sidecar"]
    changed, unchanged = proposed["labels"]
    assert changed["status"] == "rejected"
    assert changed["adjudication_notes_sha256"] == hashlib.sha256(
        "Private note: source was superseded.".encode("utf-8")
    ).hexdigest()
    assert "adjudication_notes" not in changed
    assert unchanged == source["labels"][1]
    assert preview["negative_counts"] == {"rejected": 1, "corpus_missing": 0, "ambiguous": 0, "insufficient_evidence": 0}
    assert preview["preview_sha256"] == canonical_sha256({key: value for key, value in preview.items() if key != "preview_sha256"})
    assert "Private note" not in str(preview)


def test_promotion_preview_rejects_mismatched_decisions_artifact_hash():
    # Break caught: preview source hashes bind semantic decisions JSON instead of artifact bytes.
    queue, queue_sha256 = _review_queue()
    decisions = _review_decisions(queue_sha256, status="rejected")
    decisions["decisions"][0]["queue_row_id"] = queue["rows"][0]["queue_row_id"]

    with pytest.raises(ValueError, match="decisions artifact SHA-256"):
        build_promotion_preview(
            queue_payload=queue,
            queue_sha256=queue_sha256,
            decisions_payload=decisions,
            decisions_sha256="0" * 64,
            source_sidecar_payload=_source_sidecar(),
            source_sidecar_sha256="d" * 64,
            dataset_case_ids=["review-case", "other-case"],
            provenance=_provenance(),
        )


def test_promotion_preview_copies_only_selected_candidate_and_rejects_bad_sidecar_identity_sets():
    # Break caught: preview imports document fields from outside the reviewed candidate or tolerates sidecar/dataset drift.
    queue, queue_sha256 = _review_queue()
    decisions = _review_decisions(queue_sha256)
    decisions["decisions"][0]["queue_row_id"] = queue["rows"][0]["queue_row_id"]
    source = _source_sidecar()

    preview = build_promotion_preview(
        queue_payload=queue, queue_sha256=queue_sha256, decisions_payload=decisions,
        decisions_sha256=artifact_sha256(decisions),
        source_sidecar_payload=source, source_sidecar_sha256="d" * 64,
        dataset_case_ids=["review-case", "other-case"], provenance=_provenance(),
    )
    label = preview["proposed_sidecar"]["labels"][0]
    GoldEvidence.model_validate(label)
    assert (label["document_id"], label["document_number"], label["article"], label["clause"]) == (7, "7/2026/ND-CP", "Article 2", "1")
    assert label["adjudication_candidate_id"] == _candidate("review-evidence").candidate_id
    assert label["adjudication_queue_sha256"] == queue_sha256
    assert label["adjudication_decision_sha256"] == canonical_sha256(decisions["decisions"][0])

    source["labels"].append(dict(source["labels"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        build_promotion_preview(
            queue_payload=queue, queue_sha256=queue_sha256, decisions_payload=decisions,
            decisions_sha256=artifact_sha256(decisions),
            source_sidecar_payload=source, source_sidecar_sha256="d" * 64,
            dataset_case_ids=["review-case", "other-case"], provenance=_provenance(),
        )


@pytest.mark.parametrize(
    ("mutate_queue", "mutate_decisions", "message"),
    [
        (lambda queue: queue["rows"][0].update(question="tampered"), lambda decisions: None, "queue_sha256"),
        (lambda queue: None, lambda decisions: decisions.update(queue_sha256="b" * 64), "queue_sha256"),
        (lambda queue: None, lambda decisions: decisions.update(decisions=[]), "exactly one"),
        (lambda queue: None, lambda decisions: decisions.update(decisions=[{
            **decisions["decisions"][0], "queue_row_id": "extra-row", "evidence_item_id": "extra-evidence"
        }]), "missing or extra"),
        (lambda queue: None, lambda decisions: decisions.update(decisions=[
            decisions["decisions"][0], deepcopy(decisions["decisions"][0])
        ]), "duplicate"),
    ],
)
def test_validate_decisions_rejects_queue_binding_and_row_set_drift(mutate_queue, mutate_decisions, message):
    # Break caught: a complete-looking review artifact can be replayed against a changed or incomplete queue.
    queue, queue_sha256 = _review_queue()
    decisions = _review_decisions(queue_sha256)
    decisions["decisions"][0]["queue_row_id"] = queue["rows"][0]["queue_row_id"]
    mutate_queue(queue)
    mutate_decisions(decisions)

    with pytest.raises(ValueError, match=message):
        validate_decisions(queue, decisions, queue_sha256=queue_sha256)


@pytest.mark.parametrize(
    "timestamp",
    ["2026-08-08T01:02:03", "not-a-timestamp", "2026-08-08T01:02:03+01:00"],
)
def test_validate_decisions_rejects_non_utc_or_malformed_timestamps(timestamp):
    # Break caught: timestamp parsing accepts a local, invalid, or non-UTC review instant.
    queue, queue_sha256 = _review_queue()
    decisions = _review_decisions(queue_sha256, reviewed_at_utc=timestamp)
    decisions["decisions"][0]["queue_row_id"] = queue["rows"][0]["queue_row_id"]

    with pytest.raises(ValueError, match="reviewed_at_utc"):
        validate_decisions(queue, decisions, queue_sha256=queue_sha256)


@pytest.mark.parametrize("status", ["rejected", "corpus_missing", "ambiguous", "insufficient_evidence"])
def test_validate_decisions_requires_notes_for_each_negative_status(status):
    # Break caught: a negative outcome loses its human rationale.
    queue, queue_sha256 = _review_queue()
    decisions = _review_decisions(queue_sha256, status=status, notes="")
    decisions["decisions"][0]["queue_row_id"] = queue["rows"][0]["queue_row_id"]

    with pytest.raises(ValueError, match="notes"):
        validate_decisions(queue, decisions, queue_sha256=queue_sha256)


@pytest.mark.parametrize("confidence", ["medium", "low"])
def test_validate_decisions_requires_notes_for_medium_and_low_confidence(confidence):
    # Break caught: qualified review confidence lacks the mandatory audit rationale.
    queue, queue_sha256 = _review_queue()
    decisions = _review_decisions(queue_sha256, confidence=confidence, notes="")
    decisions["decisions"][0]["queue_row_id"] = queue["rows"][0]["queue_row_id"]

    with pytest.raises(ValueError, match="notes"):
        validate_decisions(queue, decisions, queue_sha256=queue_sha256)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda source: source.update(total_cases=99), "total_cases"),
        (lambda source: source.update(total_evidence_items=99), "total_evidence_items"),
        (lambda source: source["labels"].append({
            "evidence_item_id": "extra-evidence", "case_id": "extra-case", "required": False,
            "required_level": "document", "status": "rejected",
        }), "case ID set"),
        (lambda source: source["labels"].append(deepcopy(source["labels"][0])), "duplicate"),
    ],
)
def test_promotion_preview_rejects_malformed_source_counts_and_identity_sets(mutate, message):
    # Break caught: a preview can be generated from a malformed source sidecar.
    queue, queue_sha256 = _review_queue()
    decisions = _review_decisions(queue_sha256)
    decisions["decisions"][0]["queue_row_id"] = queue["rows"][0]["queue_row_id"]
    source = _source_sidecar()
    mutate(source)

    with pytest.raises(ValueError, match=message):
        build_promotion_preview(
            queue_payload=queue, queue_sha256=queue_sha256, decisions_payload=decisions,
            decisions_sha256=artifact_sha256(decisions),
            source_sidecar_payload=source, source_sidecar_sha256="d" * 64,
            dataset_case_ids=["review-case", "other-case"], provenance=_provenance(),
        )


@pytest.mark.parametrize("legacy_notes", [None, "", " \t\n", "legacy private note", 7])
def test_promotion_preview_rejects_malformed_source_hash_and_any_legacy_raw_notes_key_without_mutation(legacy_notes):
    # Break caught: a preview accepts an untraceable source hash or a legacy raw-notes key that could leak into output.
    queue, queue_sha256 = _review_queue()
    decisions = _review_decisions(queue_sha256)
    decisions["decisions"][0]["queue_row_id"] = queue["rows"][0]["queue_row_id"]
    source = _source_sidecar()

    with pytest.raises(ValueError, match="source_sidecar_sha256"):
        build_promotion_preview(
            queue_payload=queue, queue_sha256=queue_sha256, decisions_payload=decisions,
            decisions_sha256=artifact_sha256(decisions),
            source_sidecar_payload=source, source_sidecar_sha256="not-a-hash",
            dataset_case_ids=["review-case", "other-case"], provenance=_provenance(),
        )

    source["labels"][1]["adjudication_notes"] = legacy_notes
    original = deepcopy(source)
    with pytest.raises(ValueError, match="legacy raw adjudication_notes"):
        build_promotion_preview(
            queue_payload=queue, queue_sha256=queue_sha256, decisions_payload=decisions,
            decisions_sha256=artifact_sha256(decisions),
            source_sidecar_payload=source, source_sidecar_sha256="d" * 64,
            dataset_case_ids=["review-case", "other-case"], provenance=_provenance(),
        )
    assert source == original


def test_promotion_preview_rejects_queue_evidence_missing_from_an_otherwise_valid_source_sidecar():
    # Break caught: matching source counts and cases hide that the reviewed evidence label itself is absent.
    queue, queue_sha256 = _review_queue()
    decisions = _review_decisions(queue_sha256)
    decisions["decisions"][0]["queue_row_id"] = queue["rows"][0]["queue_row_id"]
    source = _source_sidecar()
    source["labels"][0]["evidence_item_id"] = "replacement-evidence"

    with pytest.raises(ValueError, match="queue evidence"):
        build_promotion_preview(
            queue_payload=queue, queue_sha256=queue_sha256, decisions_payload=decisions,
            decisions_sha256=artifact_sha256(decisions),
            source_sidecar_payload=source, source_sidecar_sha256="d" * 64,
            dataset_case_ids=["review-case", "other-case"], provenance=_provenance(),
        )


def test_promotion_preview_preserves_nonqueued_labels_and_round_trips_adjudication_provenance():
    # Break caught: preview alters untouched labels or loses the auditable resolved-decision provenance fields.
    queue, queue_sha256 = _review_queue()
    decisions = _review_decisions(queue_sha256, reviewed_at_utc="2026-08-08T01:02:03+00:00")
    decisions["decisions"][0]["queue_row_id"] = queue["rows"][0]["queue_row_id"]
    source = _source_sidecar()
    source["labels"][1]["future_compatible_field"] = {"preserve": ["exactly"]}
    unchanged = deepcopy(source["labels"][1])

    preview = build_promotion_preview(
        queue_payload=queue, queue_sha256=queue_sha256, decisions_payload=decisions,
        decisions_sha256=artifact_sha256(decisions),
        source_sidecar_payload=source, source_sidecar_sha256="d" * 64,
        dataset_case_ids=["review-case", "other-case"], provenance=_provenance(),
    )

    label = GoldEvidence.model_validate(preview["proposed_sidecar"]["labels"][0])
    assert preview["proposed_sidecar"]["labels"][1] == unchanged
    assert label.adjudication_queue_sha256 == queue_sha256
    assert label.adjudication_decision_sha256 == canonical_sha256(decisions["decisions"][0])
    assert label.adjudication_candidate_id == _candidate("review-evidence").candidate_id
    assert label.adjudication_confidence == "high"
    assert label.adjudication_reviewer_identity == "legal-reviewer-01"
    assert label.adjudicated_at_utc == "2026-08-08T01:02:03Z"
    assert label.adjudication_notes_sha256 == hashlib.sha256(
        "Reviewed against the cited legal text.".encode("utf-8")
    ).hexdigest()
    assert label.adjudication_notes is None


def test_validate_decisions_returns_and_preview_applies_two_rows_in_queue_order():
    # Break caught: source updates or output order follow artifact order instead of the immutable queue order.
    queue, _ = _review_queue()
    second = deepcopy(queue["rows"][0])
    second.update(queue_row_id="second-row", evidence_item_id="second-evidence")
    second["candidates"][0].update(evidence_item_id="second-evidence")
    queue["rows"].append(second)
    queue_sha256 = artifact_sha256(queue)
    first_decision = _review_decisions(queue_sha256)["decisions"][0]
    first_decision["queue_row_id"] = queue["rows"][0]["queue_row_id"]
    second_decision = deepcopy(first_decision)
    second_decision.update(queue_row_id="second-row", evidence_item_id="second-evidence")
    second_decision["decision"]["selected_candidate_id"] = second["candidates"][0]["candidate_id"]
    decisions = {"schema_version": "1.0.0", "queue_sha256": queue_sha256, "decisions": [second_decision, first_decision]}
    source = {
        "schema_version": "2.0.0", "dataset_name": "test", "total_cases": 1,
        "total_evidence_items": 2,
        "labels": [
            {"evidence_item_id": "review-evidence", "case_id": "review-case", "required": True, "required_level": "article", "status": "ambiguous"},
            {"evidence_item_id": "second-evidence", "case_id": "review-case", "required": True, "required_level": "article", "status": "ambiguous"},
        ],
    }

    validated = validate_decisions(queue, decisions, queue_sha256=queue_sha256)
    preview = build_promotion_preview(
        queue_payload=queue, queue_sha256=queue_sha256, decisions_payload=decisions,
        decisions_sha256=artifact_sha256(decisions),
        source_sidecar_payload=source, source_sidecar_sha256="d" * 64,
        dataset_case_ids=["review-case"], provenance=_provenance(),
    )

    expected_candidate_id = _candidate("review-evidence").candidate_id
    assert [item.selected_candidate_id for item in validated] == [
        expected_candidate_id, expected_candidate_id,
    ]
    assert [item["evidence_item_id"] for item in preview["per_evidence_diff"]] == ["review-evidence", "second-evidence"]


def _verified_preview() -> dict:
    queue, queue_sha256 = _review_queue()
    decisions = _review_decisions(queue_sha256)
    decisions["decisions"][0]["queue_row_id"] = queue["rows"][0]["queue_row_id"]
    return build_promotion_preview(
        queue_payload=queue, queue_sha256=queue_sha256, decisions_payload=decisions,
        decisions_sha256=artifact_sha256(decisions),
        source_sidecar_payload=_source_sidecar(), source_sidecar_sha256="d" * 64,
        dataset_case_ids=["review-case", "other-case"], provenance=_provenance(),
    )


@pytest.mark.parametrize("approval", [None, "", " ", "not-a-hash", "A" * 64, "b" * 64])
def test_validate_preview_approval_rejects_missing_malformed_or_nonmatching_approval_hash(approval):
    # Break caught: persistence can be authorized by anything other than the exact canonical preview hash.
    preview = _verified_preview()

    with pytest.raises(ValueError, match="approved_preview_sha256"):
        validate_preview_approval(preview, approval)  # type: ignore[arg-type]


@pytest.mark.parametrize("declared_hash", [None, "", "not-a-hash", "A" * 64])
def test_validate_preview_approval_requires_a_well_formed_declared_hash(declared_hash):
    # Break caught: a syntactically invalid self-hash can be approved.
    preview = _verified_preview()
    preview["preview_sha256"] = declared_hash

    with pytest.raises(ValueError, match="preview_sha256"):
        validate_preview_approval(preview, "a" * 64)


def test_validate_preview_approval_recomputes_core_hash_and_is_pure():
    # Break caught: post-preview changes are accepted by replaying the original declared hash.
    preview = _verified_preview()
    original = deepcopy(preview)
    preview["status_counts"]["after"]["verified"] = 999

    with pytest.raises(ValueError, match="canonical"):
        validate_preview_approval(preview, original["preview_sha256"])
    assert preview["preview_sha256"] == original["preview_sha256"]
    assert preview["status_counts"]["after"]["verified"] == 999


def test_validate_preview_approval_rejects_nonobject_or_legacy_notes_proposed_sidecar():
    # Break caught: the promotion gate accepts non-sidecar JSON or private raw notes.
    preview = _verified_preview()
    preview["proposed_sidecar"] = []
    preview["preview_sha256"] = canonical_sha256({key: value for key, value in preview.items() if key != "preview_sha256"})
    with pytest.raises(ValueError, match="proposed_sidecar"):
        validate_preview_approval(preview, preview["preview_sha256"])

    preview = _verified_preview()
    preview["proposed_sidecar"]["labels"][0]["adjudication_notes"] = "private"
    preview["preview_sha256"] = canonical_sha256({key: value for key, value in preview.items() if key != "preview_sha256"})
    with pytest.raises(ValueError, match="adjudication_notes"):
        validate_preview_approval(preview, preview["preview_sha256"])


def test_exact_approval_is_nonpersistent_and_proposed_sidecar_remains_immutable_loadable(tmp_path: Path):
    # Break caught: approval writes as a side effect or promotion persistence loses sidecar compatibility.
    preview = _verified_preview()
    sidecar_path = tmp_path / "gold.json"

    assert validate_preview_approval(preview, preview["preview_sha256"]) is None
    assert not sidecar_path.exists()
    assert write_immutable_json(sidecar_path, preview["proposed_sidecar"]) == "created"
    assert load_gold_sidecar(sidecar_path, dataset_case_ids=["review-case", "other-case"]).metadata.total_evidence_items == 2
    original_bytes = sidecar_path.read_bytes()
    assert write_immutable_json(sidecar_path, preview["proposed_sidecar"]) == "reused"
    with pytest.raises(ArtifactCollisionError):
        write_immutable_json(sidecar_path, {"different": True})
    assert sidecar_path.read_bytes() == original_bytes


def test_build_promotion_summary_is_pure_redacts_sidecar_and_blocks_small_verified_set():
    # Break caught: the handoff summary leaks notes/sidecar or permits fewer than 30 verified cases.
    preview = _verified_preview()
    original = deepcopy(preview)

    summary = build_promotion_summary(preview)

    assert summary["preview_sha256"] == preview["preview_sha256"]
    assert summary["source_hashes"] == preview["source_hashes"]
    assert summary["provenance"] == preview["provenance"]
    assert summary["status_counts"] == preview["status_counts"]
    assert summary["per_evidence_diff"] == preview["per_evidence_diff"]
    assert summary["verified_evidence_count"] == preview["verified_evidence_count"]
    assert summary["fully_verified_selected_case_count"] == 1
    assert summary["negative_counts"] == preview["negative_counts"]
    assert summary["proposed_sidecar_sha256"] == canonical_sha256(preview["proposed_sidecar"])
    assert summary["status"] == "BLOCKED_INSUFFICIENT_VERIFIED_CASES"
    assert "proposed_sidecar" not in summary
    assert "notes" not in str(summary)
    assert preview == original


def test_build_promotion_summary_preserves_negative_diffs_and_sets_ready_only_in_gate_range():
    # Break caught: negative evidence disappears from the summary or the 30–50-case gate is weakened.
    preview = _verified_preview()
    preview["negative_counts"] = {"rejected": 1, "corpus_missing": 0, "ambiguous": 0, "insufficient_evidence": 0}
    preview["per_evidence_diff"][0]["after_status"] = "rejected"
    preview["fully_verified_selected_case_count"] = 30
    preview["preview_sha256"] = canonical_sha256({key: value for key, value in preview.items() if key != "preview_sha256"})

    assert build_promotion_summary(preview)["status"] == "READY_FOR_P2"
    preview["fully_verified_selected_case_count"] = 51
    preview["preview_sha256"] = canonical_sha256({key: value for key, value in preview.items() if key != "preview_sha256"})
    summary = build_promotion_summary(preview)
    assert summary["status"] == "BLOCKED_INSUFFICIENT_VERIFIED_CASES"
    assert summary["negative_counts"]["rejected"] == 1
    assert summary["per_evidence_diff"][0]["after_status"] == "rejected"


def test_validate_preview_approval_rejects_raw_notes_anywhere_in_proposed_sidecar():
    # Break caught: raw review notes can be hidden at the sidecar root rather than in a label.
    preview = _verified_preview()
    preview["proposed_sidecar"]["adjudication_notes"] = "private root note"
    preview["preview_sha256"] = canonical_sha256({
        key: value for key, value in preview.items() if key != "preview_sha256"
    })

    with pytest.raises(ValueError, match="adjudication_notes"):
        validate_preview_approval(preview, preview["preview_sha256"])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda preview: preview.pop("schema_version"),
        lambda preview: preview.update(schema_version=[]),
        lambda preview: preview.pop("exact_case_set"),
        lambda preview: preview.update(exact_case_set=[]),
    ],
)
def test_validate_preview_approval_requires_valid_schema_and_exact_case_sections(mutate):
    # Break caught: a hash-valid preview can omit identity-bearing preview-core sections.
    preview = _verified_preview()
    mutate(preview)
    preview["preview_sha256"] = canonical_sha256({
        key: value for key, value in preview.items() if key != "preview_sha256"
    })

    with pytest.raises(ValueError, match="schema_version|exact_case_set"):
        validate_preview_approval(preview, preview["preview_sha256"])


def _write_cli_review_inputs(
    tmp_path: Path, *, case_count: int = 80,
) -> tuple[Path, Path, dict[int, object]]:
    """Create a hand-checkable exact case set for the provider-free CLI."""
    dataset_rows = []
    labels = []
    documents: dict[int, object] = {}
    for index in range(case_count):
        question_type = "factoid" if index < case_count // 2 else "multi-hop"
        case_id = f"cli-{index:03d}"
        anchor = f"Evidence for {case_id}."
        document_id = index + 1
        dataset_rows.append({
            "case_id": case_id,
            "question": f"Question for {case_id}",
            "question_type": question_type,
            "ground_truth_answer": f"Answer for {case_id}",
            "ground_truth_context": [anchor],
        })
        labels.append({
            "evidence_item_id": f"{case_id}-evidence",
            "case_id": case_id,
            "document_id": document_id,
            "document_number": f"{document_id}/2026/ND-CP",
            "required": True,
            "required_level": "document",
            "status": "ambiguous",
        })
        documents[document_id] = _stored_document(
            document_id,
            number=f"{document_id}/2026/ND-CP",
            content=anchor,
        )
    dataset_path = tmp_path / "dataset.json"
    sidecar_path = tmp_path / "labels.json"
    dataset_path.write_text(json.dumps(dataset_rows), encoding="utf-8")
    sidecar_path.write_text(json.dumps({
        "schema_version": "2.0.0",
        "total_cases": case_count,
        "total_evidence_items": case_count,
        "labels": labels,
    }), encoding="utf-8")
    return dataset_path, sidecar_path, documents


def _configure_cli_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, documents: dict[int, object],
):
    import run_gold_adjudication as cli

    class FakeStore(_FakeContentStore):
        def __init__(self, _path: Path) -> None:
            super().__init__(documents)

    class FakeFts(_FakeFts):
        def __init__(self, *, store: object, path: Path, dataset_revision: str) -> None:
            del store, path, dataset_revision
            super().__init__([])

    original = cli._runtime_dependencies()
    dependencies = cli.RuntimeDependencies(
        **{**original.__dict__, "ContentStore": FakeStore, "LegalFtsIndex": FakeFts}
    )
    monkeypatch.setattr(cli, "_runtime_dependencies", lambda: dependencies)
    monkeypatch.setattr(cli, "repository_root", lambda: tmp_path)
    return cli


def _cli_queue_args(
    dataset_path: Path, sidecar_path: Path, content_store_path: Path, fts_path: Path,
    output_root: Path, run_id: str,
) -> list[str]:
    return [
        "queue", "--dataset", str(dataset_path), "--sidecar", str(sidecar_path),
        "--content-store", str(content_store_path), "--fts", str(fts_path),
        "--output-root", str(output_root), "--run-id", run_id,
    ]


def _write_resolved_decisions(queue_path: Path, decisions_path: Path) -> None:
    template = json.loads(queue_path.read_text(encoding="utf-8"))
    for entry in template["decisions"]:
        entry["decision"] = {
            "status": "rejected", "selected_candidate_id": None,
            "confidence": "high", "notes": "not supported", "reviewer_identity": "reviewer",
            "reviewed_at_utc": "2026-08-08T00:00:00Z",
        }
    decisions_path.write_bytes(canonical_json_bytes(template))


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    }


def _prepare_cli_artifacts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    dataset_path, sidecar_path, documents = _write_cli_review_inputs(tmp_path)
    content_store_path = tmp_path / "content.sqlite3"
    fts_path = tmp_path / "fts.sqlite3"
    content_store_path.touch()
    fts_path.touch()
    cli = _configure_cli_runtime(monkeypatch, tmp_path, documents)
    queue_root = tmp_path / "queue-runs"
    assert cli.main(_cli_queue_args(
        dataset_path, sidecar_path, content_store_path, fts_path, queue_root, "queue-base",
    )) == 0
    decisions_path = tmp_path / "decisions.json"
    _write_resolved_decisions(queue_root / "queue-base" / "decision_template.json", decisions_path)
    preview_root = tmp_path / "preview-runs"
    assert cli.main([
        "preview", "--dataset", str(dataset_path), "--sidecar", str(sidecar_path),
        "--queue", str(queue_root / "queue-base" / "queue.json"), "--decisions", str(decisions_path),
        "--output-root", str(preview_root), "--run-id", "preview-base",
    ]) == 0
    return cli, dataset_path, sidecar_path, content_store_path, fts_path, queue_root, decisions_path, preview_root


def test_gold_adjudication_cli_is_import_safe_and_help_is_provider_free(monkeypatch):
    # Break caught: importing or rendering CLI help constructs a corpus or provider client.
    import run_gold_adjudication as cli

    def forbidden_runtime_dependencies():
        raise AssertionError("help must not load runtime dependencies")

    monkeypatch.setattr(cli, "_runtime_dependencies", forbidden_runtime_dependencies)
    with pytest.raises(SystemExit, match="0"):
        cli.main(["--help"])


def test_gold_adjudication_cli_queue_preview_and_promotion_are_immutable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    # Break caught: CLI skips exact bindings, emits mutable/non-auditable artifacts,
    # or promotes a source sidecar without an exact approved preview.
    dataset_path, sidecar_path, documents = _write_cli_review_inputs(tmp_path)
    content_store_path = tmp_path / "content.sqlite3"
    fts_path = tmp_path / "fts.sqlite3"
    content_store_path.touch()
    fts_path.touch()

    cli = _configure_cli_runtime(monkeypatch, tmp_path, documents)
    dependencies = cli._runtime_dependencies()

    queue_root = tmp_path / "queue-runs"
    assert cli.main([
        "queue", "--dataset", str(dataset_path), "--sidecar", str(sidecar_path),
        "--content-store", str(content_store_path), "--fts", str(fts_path),
        "--candidate-limit", "1", "--output-root", str(queue_root), "--run-id", "queue-1",
    ]) == 0
    queue_run = queue_root / "queue-1"
    assert sorted(path.name for path in queue_run.iterdir()) == [
        "decision_template.json", "queue.json", "queue_summary.json",
    ]
    queue = json.loads((queue_run / "queue.json").read_text(encoding="utf-8"))
    template = json.loads((queue_run / "decision_template.json").read_text(encoding="utf-8"))
    summary = json.loads((queue_run / "queue_summary.json").read_text(encoding="utf-8"))
    assert len(queue["selected_case_ids"]) == 20
    assert {row["question_type"] for row in queue["rows"]} == {"factoid", "multi-hop"}
    assert {entry["decision"]["status"] for entry in template["decisions"]} == {"pending"}
    assert template["queue_sha256"] == dependencies.artifact_sha256(queue)
    assert template["queue_sha256"] == hashlib.sha256(
        (queue_run / "queue.json").read_bytes()
    ).hexdigest()
    assert summary["artifact_hashes"]["decision_template_sha256"] == hashlib.sha256(
        (queue_run / "decision_template.json").read_bytes()
    ).hexdigest()
    assert summary["provider_calls"] == 0
    assert all(not Path(value).is_absolute() and "\\" not in value for value in summary["artifact_paths"].values())

    for index, (entry, row) in enumerate(zip(template["decisions"], queue["rows"], strict=True)):
        entry["decision"] = {
            "status": "rejected" if index < 11 else "verified",
            "selected_candidate_id": None if index < 11 else row["candidates"][0]["candidate_id"],
            "confidence": "high", "notes": "not supported" if index < 11 else "", "reviewer_identity": "reviewer",
            "reviewed_at_utc": "2026-08-08T00:00:00Z",
        }
    decisions_path = tmp_path / "decisions.json"
    decisions_path.write_bytes(canonical_json_bytes(template))
    preview_root = tmp_path / "preview-runs"
    assert cli.main([
        "preview", "--dataset", str(dataset_path), "--sidecar", str(sidecar_path),
        "--queue", str(queue_run / "queue.json"), "--decisions", str(decisions_path),
        "--output-root", str(preview_root), "--run-id", "preview-1",
    ]) == 0
    preview_path = preview_root / "preview-1" / "preview.json"
    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    assert preview["source_hashes"]["decisions_sha256"] == hashlib.sha256(
        decisions_path.read_bytes()
    ).hexdigest()
    assert '"adjudication_notes":' not in json.dumps(preview["proposed_sidecar"])

    source_before = sidecar_path.read_bytes()
    promotion_root = tmp_path / "promotion-runs"
    assert cli.main([
        "promote", "--dataset", str(dataset_path), "--sidecar", str(sidecar_path),
        "--queue", str(queue_run / "queue.json"), "--decisions", str(decisions_path),
        "--preview", str(preview_path), "--approve-preview-sha256", preview["preview_sha256"],
        "--output-root", str(promotion_root), "--run-id", "promotion-1",
    ]) == 0
    promotion_run = promotion_root / "promotion-1"
    assert sorted(path.name for path in promotion_run.iterdir()) == [
        "labels_v2.json", "promotion_summary.json",
    ]
    assert sidecar_path.read_bytes() == source_before
    promotion_summary = json.loads((promotion_run / "promotion_summary.json").read_text(encoding="utf-8"))
    assert promotion_summary["status"] == "BLOCKED_INSUFFICIENT_VERIFIED_CASES"
    assert promotion_summary["negative_counts"]["rejected"] == 11


def test_gold_adjudication_cli_persists_blocked_queue_without_replacements(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    # Break caught: fewer than 30 eligible cases aborts or fabricates a ready queue.
    dataset_path, sidecar_path, documents = _write_cli_review_inputs(
        tmp_path, case_count=12
    )
    content_store_path = tmp_path / "content.sqlite3"
    fts_path = tmp_path / "fts.sqlite3"
    content_store_path.touch()
    fts_path.touch()
    cli = _configure_cli_runtime(monkeypatch, tmp_path, documents)
    queue_root = tmp_path / "blocked-queue-runs"

    with pytest.raises(ValueError, match="insufficient_eligible_cases"):
        cli.main(_cli_queue_args(
            dataset_path,
            sidecar_path,
            content_store_path,
            fts_path,
            queue_root,
            "blocked-queue",
        ))

    assert not (queue_root / "blocked-queue").exists()


def test_gold_adjudication_cli_rejects_external_outputs_and_missing_approval_before_writing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    # Break caught: invalid output roots or absent approval values create an artifact directory.
    import run_gold_adjudication as cli

    monkeypatch.setattr(cli, "repository_root", lambda: tmp_path / "repository")
    with pytest.raises(ValueError, match="inside the repository"):
        cli.main(["queue", "--output-root", str(tmp_path / "outside")])
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["promote"])


def test_gold_adjudication_cli_rejects_legacy_raw_notes_before_queue_persistence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    # Break caught: legacy raw reviewer notes reach candidate discovery or queue.json.
    dataset_path, sidecar_path, documents = _write_cli_review_inputs(tmp_path)
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sidecar["labels"][0]["adjudication_notes"] = "private reviewer note"
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
    content_store_path = tmp_path / "content.sqlite3"
    fts_path = tmp_path / "fts.sqlite3"
    content_store_path.touch()
    fts_path.touch()
    cli = _configure_cli_runtime(monkeypatch, tmp_path, documents)
    output_root = tmp_path / "queue-runs"

    with pytest.raises(ValueError, match="adjudication_notes"):
        cli.main(_cli_queue_args(
            dataset_path, sidecar_path, content_store_path, fts_path, output_root, "legacy-notes",
        ))
    assert not output_root.exists()


@pytest.mark.parametrize(
    "failure",
    [
        "missing-content-store", "missing-fts", "invalid-target", "invalid-candidate",
        "run-directory-collision", "stale-queue", "malformed-decisions",
        "reserialized-queue", "reserialized-decisions",
        "blank-approval", "malformed-approval", "wrong-approval",
    ],
)
def test_gold_adjudication_cli_fails_closed_without_writing_new_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str,
):
    # Break caught: invalid queue/preview/promotion input can alter bytes or create a run directory.
    (
        cli, dataset_path, sidecar_path, content_store_path, fts_path, queue_root,
        decisions_path, preview_root,
    ) = _prepare_cli_artifacts(monkeypatch, tmp_path)
    queue_path = queue_root / "queue-base" / "queue.json"
    preview_path = preview_root / "preview-base" / "preview.json"
    output_root = tmp_path / "failed-runs"

    if failure == "missing-content-store":
        arguments = _cli_queue_args(
            dataset_path, sidecar_path, tmp_path / "missing.sqlite3", fts_path, output_root, "missing-store",
        )
    elif failure == "missing-fts":
        arguments = _cli_queue_args(
            dataset_path, sidecar_path, content_store_path, tmp_path / "missing-fts.sqlite3", output_root, "missing-fts",
        )
    elif failure == "invalid-target":
        arguments = _cli_queue_args(
            dataset_path, sidecar_path, content_store_path, fts_path, output_root, "invalid-target",
        ) + ["--target-cases", "29"]
    elif failure == "invalid-candidate":
        arguments = _cli_queue_args(
            dataset_path, sidecar_path, content_store_path, fts_path, output_root, "invalid-candidate",
        ) + ["--candidate-limit", "0"]
    elif failure == "run-directory-collision":
        arguments = _cli_queue_args(
            dataset_path, sidecar_path, content_store_path, fts_path, queue_root, "queue-base",
        )
    else:
        if failure == "stale-queue":
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
            queue["dataset_sha256"] = "0" * 64
            queue_path.write_text(json.dumps(queue), encoding="utf-8")
        elif failure == "malformed-decisions":
            decisions_path.write_text("[]", encoding="utf-8")
        elif failure == "reserialized-queue":
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
            queue_path.write_text(json.dumps(queue), encoding="utf-8")
        elif failure == "reserialized-decisions":
            decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
            decisions_path.write_text(json.dumps(decisions), encoding="utf-8")
        approval = {
            "blank-approval": "",
            "malformed-approval": "not-a-sha",
            "wrong-approval": "0" * 64,
        }.get(failure)
        if failure in {"blank-approval", "malformed-approval", "wrong-approval"}:
            arguments = [
                "promote", "--dataset", str(dataset_path), "--sidecar", str(sidecar_path),
                "--queue", str(queue_path), "--decisions", str(decisions_path),
                "--preview", str(preview_path), "--approve-preview-sha256", approval,
                "--output-root", str(output_root), "--run-id", f"promotion-{failure}",
            ]
        else:
            arguments = [
                "preview", "--dataset", str(dataset_path), "--sidecar", str(sidecar_path),
                "--queue", str(queue_path), "--decisions", str(decisions_path),
                "--output-root", str(output_root), "--run-id", f"preview-{failure}",
            ]
    before = _tree_bytes(tmp_path)
    with pytest.raises((FileNotFoundError, FileExistsError, ValueError, SystemExit)):
        cli.main(arguments)
    assert _tree_bytes(tmp_path) == before
    assert not output_root.exists()


# ==============================================================================
# TASK 2: PROVIDER-FREE VERIFIED-GOLD EXPANSION & DIVERSITY TESTS
# ==============================================================================

def test_task2_selection_determinism_exact_order():
    """A. Determinism: identical inputs produce identical 20-case IDs in identical order."""
    cases = [
        *[_case(f"factoid-{idx:02d}", "factoid") for idx in range(25)],
        *[_case(f"multi-hop-{idx:02d}", "multi-hop") for idx in range(25)],
    ]
    labels_by_case = {case.case_id: [_label(case.case_id)] for case in cases}

    first = select_stratified_case_ids(cases, labels_by_case, target_cases=20, seed="task2-seed-1")
    second = select_stratified_case_ids(cases, labels_by_case, target_cases=20, seed="task2-seed-1")

    assert len(first) == 20
    assert first == second


def test_task2_target_cases_invariant_rejects_non_20():
    """B. Target cases invariant: exactly 20 cases only; rejects 19, 21, 40."""
    cases = [
        *[_case(f"case-f-{idx:02d}", "factoid") for idx in range(20)],
        *[_case(f"case-m-{idx:02d}", "multi-hop") for idx in range(20)],
    ]
    labels_by_case = {case.case_id: [_label(case.case_id)] for case in cases}

    # Valid: target_cases=20
    selected = select_stratified_case_ids(cases, labels_by_case, target_cases=20, seed="batch-20")
    assert len(selected) == 20

    # Invalid: rejects non-20 target_cases
    with pytest.raises(ValueError, match="must be exactly 20"):
        select_stratified_case_ids(cases, labels_by_case, target_cases=19, seed="batch-20")
    with pytest.raises(ValueError, match="must be exactly 20"):
        select_stratified_case_ids(cases, labels_by_case, target_cases=21, seed="batch-20")
    with pytest.raises(ValueError, match="must be exactly 20"):
        select_stratified_case_ids(cases, labels_by_case, target_cases=40, seed="batch-20")

    # Invalid in build_queue_payload
    sidecar = GoldSidecar(
        metadata=GoldSidecarMetadata(sidecar_sha256="a" * 64),
        labels=[_label(c.case_id) for c in cases[:20]],
        labels_by_case_id={c.case_id: [_label(c.case_id)] for c in cases[:20]},
    )
    with pytest.raises(ValueError, match="target_case_count must be exactly 20"):
        build_queue_payload(
            cases=cases[:20],
            sidecar=sidecar,
            candidates_by_evidence_id={},
            selected_case_ids=[c.case_id for c in cases[:20]],
            dataset_sha256="d" * 64,
            corpus_revision="pinned",
            provenance=_provenance(),
            command=["python"],
            candidate_limit=5,
            selection_seed="seed",
            target_case_count=10,
        )
    with pytest.raises(ValueError, match="exceeds target_case_count"):
        build_queue_payload(
            cases=cases[:20],
            sidecar=sidecar,
            candidates_by_evidence_id={},
            selected_case_ids=[c.case_id for c in cases[:20]] + ["extra-case"],
            dataset_sha256="d" * 64,
            corpus_revision="pinned",
            provenance=_provenance(),
            command=["python"],
            candidate_limit=5,
            selection_seed="seed",
            target_case_count=20,
        )


def test_task2_cli_insufficient_eligible_cases_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    """C. Insufficient pool: <20 eligible cases fails closed on real CLI, no directory created."""
    # Write only 19 cases (< 20 target)
    dataset_path, sidecar_path, documents = _write_cli_review_inputs(tmp_path, case_count=19)
    content_store_path = tmp_path / "content.sqlite3"
    fts_path = tmp_path / "fts.sqlite3"
    content_store_path.touch()
    fts_path.touch()

    cli = _configure_cli_runtime(monkeypatch, tmp_path, documents)
    queue_root = tmp_path / "queue-runs-insufficient"
    run_id = "insufficient-19-run"

    with pytest.raises(ValueError, match="insufficient_eligible_cases"):
        cli.main([
            "queue", "--dataset", str(dataset_path), "--sidecar", str(sidecar_path),
            "--content-store", str(content_store_path), "--fts", str(fts_path),
            "--target-cases", "20",
            "--output-root", str(queue_root), "--run-id", run_id,
        ])

    # Assert no output artifact or run directory was created
    assert not (queue_root / run_id).exists()


def test_task2_unresolved_evidence_only_in_decision_rows():
    """D & 3. Queue decision rows contain only unverified required evidence; verified evidence excluded."""
    # Case with Evidence A = VERIFIED and Evidence B = AMBIGUOUS
    case = _case("multihop-partial-verified", "multi-hop")
    ev_a = GoldEvidence(
        evidence_item_id="ev-a-verified",
        case_id=case.case_id,
        required=True,
        required_level="article",
        document_number="72/2020/QH14",
        status=EvidenceStatus.VERIFIED,  # already verified!
    )
    ev_b = GoldEvidence(
        evidence_item_id="ev-b-ambiguous",
        case_id=case.case_id,
        required=True,
        required_level="clause",
        document_number="83/2015/QH13",
        status=EvidenceStatus.AMBIGUOUS,  # needs human review
    )

    # 19 filler cases to make exact 20 batch
    filler_cases = [_case(f"filler-{idx:02d}", "factoid") for idx in range(19)]
    all_cases = [case, *filler_cases]
    labels_by_case = {case.case_id: [ev_a, ev_b]}
    for fc in filler_cases:
        labels_by_case[fc.case_id] = [_label(fc.case_id)]

    sidecar = GoldSidecar(
        metadata=GoldSidecarMetadata(sidecar_sha256="a" * 64),
        labels=[ev_a, ev_b, *[_label(fc.case_id) for fc in filler_cases]],
        labels_by_case_id=labels_by_case,
    )

    selected = select_stratified_case_ids(all_cases, labels_by_case, target_cases=20)
    assert case.case_id in selected

    cand_b = _candidate(ev_b.evidence_item_id)
    payload = build_queue_payload(
        cases=all_cases,
        sidecar=sidecar,
        candidates_by_evidence_id={ev_b.evidence_item_id: [cand_b]},
        selected_case_ids=selected,
        dataset_sha256="d" * 64,
        corpus_revision="pinned",
        provenance=_provenance(),
        command=["python"],
        candidate_limit=5,
        target_case_count=20,
    )

    # Find rows for multihop-partial-verified
    case_rows = [r for r in payload["rows"] if r["case_id"] == case.case_id]
    # ONLY evidence B is in decision rows!
    assert len(case_rows) == 1
    assert case_rows[0]["evidence_item_id"] == "ev-b-ambiguous"
    assert case_rows[0]["source_evidence_status"] == EvidenceStatus.AMBIGUOUS.value

    # Check decision template
    template = build_decision_template(payload, artifact_sha256(payload))
    template_evidence_ids = [d["evidence_item_id"] for d in template["decisions"]]
    assert "ev-b-ambiguous" in template_evidence_ids
    assert "ev-a-verified" not in template_evidence_ids

    # Case with ALL required evidence items verified -> NEVER selected
    fully_verified_case = _case("fully-verified-case", "factoid")
    fv_ev = GoldEvidence(
        evidence_item_id="fv-ev-1",
        case_id=fully_verified_case.case_id,
        required=True,
        required_level="article",
        status=EvidenceStatus.VERIFIED,
    )
    labels_with_fv = {**labels_by_case, fully_verified_case.case_id: [fv_ev]}
    selected_with_fv = select_stratified_case_ids([*all_cases, fully_verified_case], labels_with_fv, target_cases=20)
    assert fully_verified_case.case_id not in selected_with_fv


def test_task2_selection_seed_recorded_matches_selector_reproducibility(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    """4. Provenance: recorded selection_seed matches seed used and reproduces exact case order."""
    from app.evaluation.adjudication import TASK2_SELECTION_SEED

    dataset_path, sidecar_path, documents = _write_cli_review_inputs(tmp_path, case_count=30)
    content_store_path = tmp_path / "content.sqlite3"
    fts_path = tmp_path / "fts.sqlite3"
    content_store_path.touch()
    fts_path.touch()

    cli = _configure_cli_runtime(monkeypatch, tmp_path, documents)
    queue_root = tmp_path / "queue-runs-seed"

    assert cli.main([
        "queue", "--dataset", str(dataset_path), "--sidecar", str(sidecar_path),
        "--content-store", str(content_store_path), "--fts", str(fts_path),
        "--target-cases", "20",
        "--output-root", str(queue_root), "--run-id", "seed-run",
    ]) == 0

    queue_data = json.loads((queue_root / "seed-run" / "queue.json").read_text(encoding="utf-8"))
    recorded_seed = queue_data["selection_seed"]
    assert recorded_seed == TASK2_SELECTION_SEED == "vietlex-p2-v1"

    # Re-run selector directly with recorded seed
    dependencies = cli._runtime_dependencies()
    cases = dependencies.build_cases(json.loads(dataset_path.read_text(encoding="utf-8")), {})
    sidecar_obj = dependencies.load_gold_sidecar(sidecar_path)
    rerun_selected = select_stratified_case_ids(
        cases, sidecar_obj.labels_by_case_id, target_cases=20, seed=recorded_seed
    )
    assert rerun_selected == queue_data["selected_case_ids"]


def test_task2_conservative_legal_type_inference():
    """5. Conservative legal-type inference: avoids over-generalizing /QH or /UBTVQH."""
    from app.evaluation.adjudication import infer_conservative_legal_type

    # Specific suffixes
    assert infer_conservative_legal_type(document_number="12/2020/NĐ-CP") == "Nghị định"
    assert infer_conservative_legal_type(document_number="05/2021/TT-BXD") == "Thông tư"
    assert infer_conservative_legal_type(document_number="01/2020/TTLT-BCA-BQP") == "Thông tư liên tịch"
    assert infer_conservative_legal_type(document_number="15/2019/QĐ-TTg") == "Quyết định"
    assert infer_conservative_legal_type(document_number="42/2021/NQ-CP") == "Nghị quyết"
    assert infer_conservative_legal_type(document_number="08/2020/CT-TTg") == "Chỉ thị"
    assert infer_conservative_legal_type(document_number="01/VBHN-VPQH") == "Văn bản hợp nhất"

    # /QH and /UBTVQH alone without text keywords should NOT assume Luật/Pháp lệnh
    assert infer_conservative_legal_type(document_number="72/2020/QH14") == "unspecified"
    assert infer_conservative_legal_type(document_number="10/2018/UBTVQH14") == "unspecified"

    # With text keywords, correctly resolves
    assert infer_conservative_legal_type(document_number="72/2020/QH14", text="Luật Bảo vệ môi trường 2020") == "Luật"
    assert infer_conservative_legal_type(document_number="91/2015/QH13", text="Bộ luật Dân sự 2015") == "Bộ luật"
    assert infer_conservative_legal_type(document_number="10/2018/UBTVQH14", text="Pháp lệnh số 10 về cán bộ") == "Pháp lệnh"
    assert infer_conservative_legal_type(text="Hiến pháp nước CHXHCN Việt Nam") == "Hiến pháp"


def test_task2_selection_diagnostics_audit_trail():
    """6. Diagnostics audit trail: exposes representation counts, stratum, digest, and policy."""
    cases = [
        *[_case(f"factoid-{idx:02d}", "factoid") for idx in range(10)],
        *[_case(f"multi-hop-{idx:02d}", "multi-hop") for idx in range(10)],
    ]
    labels_by_case = {case.case_id: [_label(case.case_id)] for case in cases}
    sidecar = GoldSidecar(
        metadata=GoldSidecarMetadata(sidecar_sha256="a" * 64),
        labels=[_label(c.case_id) for c in cases],
        labels_by_case_id=labels_by_case,
    )

    selected = select_stratified_case_ids(cases, labels_by_case, target_cases=20)
    payload = build_queue_payload(
        cases=cases,
        sidecar=sidecar,
        candidates_by_evidence_id={},
        selected_case_ids=selected,
        dataset_sha256="d" * 64,
        corpus_revision="pinned",
        provenance=_provenance(),
        command=["python"],
        candidate_limit=5,
        target_case_count=20,
    )

    diagnostics = payload["selection_diagnostics"]
    assert diagnostics["selection_policy"] == "underrepresented_document_then_legal_type_then_sha256"
    assert len(diagnostics["case_diagnostics"]) == 20

    first_diag = diagnostics["case_diagnostics"][0]
    assert "case_id" in first_diag
    assert "document_key" in first_diag
    assert "legal_type" in first_diag
    assert "verified_document_representation_before" in first_diag
    assert "verified_legal_type_representation_before" in first_diag
    assert "selection_stratum" in first_diag
    assert "tie_break_digest" in first_diag
    assert first_diag["selection_policy"] == "underrepresented_document_then_legal_type_then_sha256"


def test_task2_diversity_aware_selection_prioritizes_underrepresented_documents():
    """F & 4. Diversity-aware selection: prefers underrepresented documents over overrepresented documents."""
    cases = []
    labels_by_case = {}

    # 1. Baseline verified cases in sidecar (20 cases for doc 101) -> doc_counts["101/2020/NĐ-CP"] = 20
    for i in range(20):
        cid = f"base-101-{i:02d}"
        c = _case(cid, "factoid")
        cases.append(c)
        ev = GoldEvidence(
            evidence_item_id=f"ev-{cid}",
            case_id=cid,
            document_id=101,
            document_number="101/2020/NĐ-CP",
            required=True,
            required_level="article",
            status=EvidenceStatus.VERIFIED,  # already verified baseline
        )
        labels_by_case[cid] = [ev]

    # 2. Candidate UNRESOLVED cases for overrepresented doc 101 (20 cases, doc_rep=20)
    for i in range(20):
        cid = f"cand-over101-{i:02d}"
        c = _case(cid, "factoid")
        cases.append(c)
        ev = GoldEvidence(
            evidence_item_id=f"ev-{cid}",
            case_id=cid,
            document_id=101,
            document_number="101/2020/NĐ-CP",
            required=True,
            required_level="article",
            status=EvidenceStatus.AMBIGUOUS,  # unverified candidate
        )
        labels_by_case[cid] = [ev]

    # 3. Candidate UNRESOLVED cases for novel doc 201 (20 cases, doc_rep=0)
    for i in range(20):
        cid = f"cand-under201-{i:02d}"
        c = _case(cid, "factoid")
        cases.append(c)
        ev = GoldEvidence(
            evidence_item_id=f"ev-{cid}",
            case_id=cid,
            document_id=201,
            document_number="201/2020/NĐ-CP",
            required=True,
            required_level="article",
            status=EvidenceStatus.AMBIGUOUS,  # unverified candidate
        )
        labels_by_case[cid] = [ev]

    # Run selection with target_cases=20
    selected = select_stratified_case_ids(cases, labels_by_case, target_cases=20, seed="diversity-doc-test")
    assert len(selected) == 20

    # All 20 selected cases MUST be from novel doc 201 (doc_rep=0)
    selected_under = [cid for cid in selected if "under201" in cid]
    selected_over = [cid for cid in selected if "over101" in cid]
    assert len(selected_under) == 20
    assert len(selected_over) == 0


def test_task2_diversity_aware_selection_prioritizes_underrepresented_legal_types():
    """2 & 4. Diversity-aware selection: prefers underrepresented legal types when doc_rep is equal."""
    cases = []
    labels_by_case = {}

    # 1. Baseline verified cases in sidecar (20 cases for Nghị định) -> legal_type_counts["Nghị định"] = 20, "Thông tư" = 0
    for i in range(20):
        cid = f"base-nd-{i:02d}"
        c = _case(cid, "factoid")
        cases.append(c)
        ev = GoldEvidence(
            evidence_item_id=f"ev-{cid}",
            case_id=cid,
            document_id=101,
            document_number="101/2020/NĐ-CP",
            required=True,
            required_level="article",
            status=EvidenceStatus.VERIFIED,  # already verified baseline
        )
        labels_by_case[cid] = [ev]

    # 2. Candidate UNRESOLVED cases for novel doc 301 (Nghị định, doc_rep=0, ltype_rep=20)
    for i in range(20):
        cid = f"cand-nd301-{i:02d}"
        c = _case(cid, "factoid")
        cases.append(c)
        ev = GoldEvidence(
            evidence_item_id=f"ev-{cid}",
            case_id=cid,
            document_id=301,
            document_number="301/2020/NĐ-CP",
            required=True,
            required_level="article",
            status=EvidenceStatus.AMBIGUOUS,
        )
        labels_by_case[cid] = [ev]

    # 3. Candidate UNRESOLVED cases for novel doc 401 (Thông tư, doc_rep=0, ltype_rep=0)
    for i in range(20):
        cid = f"cand-tt401-{i:02d}"
        c = _case(cid, "factoid")
        cases.append(c)
        ev = GoldEvidence(
            evidence_item_id=f"ev-{cid}",
            case_id=cid,
            document_id=401,
            document_number="401/2020/TT-BXD",
            required=True,
            required_level="article",
            status=EvidenceStatus.AMBIGUOUS,
        )
        labels_by_case[cid] = [ev]

    # Both candidate groups have doc_rep=0; selector must prefer ltype_rep=0 ("Thông tư")
    selected = select_stratified_case_ids(cases, labels_by_case, target_cases=20, seed="diversity-ltype-test")
    assert len(selected) == 20

    selected_tt = [cid for cid in selected if "tt401" in cid]
    selected_nd = [cid for cid in selected if "nd301" in cid]
    assert len(selected_tt) == 20
    assert len(selected_nd) == 0


def test_task2_eligible_case_count_computation():
    """3. eligible_case_count accurately reflects only truly eligible cases."""
    from app.evaluation.adjudication import is_case_eligible_for_adjudication

    # 1: Fully verified case (2/2 required verified)
    c1 = _case("case-fv-1", "factoid")
    ev1 = _label(c1.case_id, status=EvidenceStatus.VERIFIED)
    ev2 = _label(c1.case_id, status=EvidenceStatus.VERIFIED)

    # 2: Fully verified case (1/1 required verified)
    c2 = _case("case-fv-2", "multi-hop")
    ev3 = _label(c2.case_id, status=EvidenceStatus.VERIFIED)

    # 3: Unanswerable case
    c3 = _case("case-unanswerable", "factoid")
    c3.answerable = False
    ev4 = _label(c3.case_id, status=EvidenceStatus.AMBIGUOUS)

    # 4: Eligible case (1 required unresolved)
    c4 = _case("case-eligible-1", "factoid")
    ev5 = _label(c4.case_id, status=EvidenceStatus.AMBIGUOUS)

    # 5: Eligible case (1 verified, 1 unresolved required)
    c5 = _case("case-eligible-2", "multi-hop")
    ev6 = _label(c5.case_id, status=EvidenceStatus.VERIFIED)
    ev7 = _label(c5.case_id, status=EvidenceStatus.AMBIGUOUS)

    five_cases = [c1, c2, c3, c4, c5]
    labels_by_case = {
        c1.case_id: [ev1, ev2],
        c2.case_id: [ev3],
        c3.case_id: [ev4],
        c4.case_id: [ev5],
        c5.case_id: [ev6, ev7],
    }

    # Test predicate directly
    assert not is_case_eligible_for_adjudication(c1, labels_by_case[c1.case_id])
    assert not is_case_eligible_for_adjudication(c2, labels_by_case[c2.case_id])
    assert not is_case_eligible_for_adjudication(c3, labels_by_case[c3.case_id])
    assert is_case_eligible_for_adjudication(c4, labels_by_case[c4.case_id])
    assert is_case_eligible_for_adjudication(c5, labels_by_case[c5.case_id])

    # 18 filler eligible cases + 5 cases = 23 total cases (20 eligible)
    filler = [_case(f"filler-el-{i:02d}", "factoid") for i in range(18)]
    all_23 = [*five_cases, *filler]
    all_labels = {**labels_by_case}
    for fc in filler:
        all_labels[fc.case_id] = [_label(fc.case_id, status=EvidenceStatus.AMBIGUOUS)]

    sidecar_23 = GoldSidecar(
        metadata=GoldSidecarMetadata(sidecar_sha256="a" * 64),
        labels=[ev for evs in all_labels.values() for ev in evs],
        labels_by_case_id=all_labels,
    )
    eligible_20_ids = [c.case_id for c in all_23 if is_case_eligible_for_adjudication(c, all_labels.get(c.case_id))]
    assert len(eligible_20_ids) == 20

    payload = build_queue_payload(
        cases=all_23,
        sidecar=sidecar_23,
        candidates_by_evidence_id={},
        selected_case_ids=eligible_20_ids,
        dataset_sha256="d" * 64,
        corpus_revision="pinned",
        provenance=_provenance(),
        command=["python"],
        candidate_limit=5,
        target_case_count=20,
    )
    # Total cases passed = 23, but eligible_case_count accurately = 20
    assert payload["selection_diagnostics"]["eligible_case_count"] == 20


def test_task2_current_promoted_verified_checkpoint_integration():
    """1. Task 2 binds to the frozen promoted verified-gold checkpoint."""
    import run_gold_adjudication as cli
    from app.evaluation.adjudication import is_case_eligible_for_adjudication

    parser = cli.build_parser()
    queue_parser = parser._subparsers._actions[1].choices["queue"]  # type: ignore[attr-defined]
    default_dataset = queue_parser.get_default("dataset")
    default_sidecar = queue_parser.get_default("sidecar")

    assert default_dataset.exists()
    assert default_sidecar.exists()
    assert "curated_v1" in default_dataset.name
    assert "labels_v2.json" in default_sidecar.name or "promotions" in str(default_sidecar)

    # Load live sources
    dependencies = cli._runtime_dependencies()
    dataset_raw = json.loads(default_dataset.read_text(encoding="utf-8"))
    assert len(dataset_raw) == 420

    cases = dependencies.build_cases(dataset_raw, {})
    assert len(cases) == 420
    dataset_case_ids = [c.case_id for c in cases]

    sidecar = dependencies.load_gold_sidecar(
        default_sidecar,
        dataset_case_ids=dataset_case_ids,
    )
    assert len(sidecar.labels) == 484

    # Assert exact promoted counts
    verified_labels = [
        label for label in sidecar.labels
        if label.status == "verified" or label.status == EvidenceStatus.VERIFIED
    ]
    assert len(verified_labels) == 53

    cases = dependencies.build_cases(dataset_raw, sidecar.labels_by_case_id)
    assert len(cases) == 420

    # Check all-required-verified count
    all_required_verified_cases = []
    for c in cases:
        c_labels = sidecar.labels_by_case_id.get(c.case_id, [])
        required = [label for label in c_labels if label.required]
        if required and all(label.status in ("verified", EvidenceStatus.VERIFIED) for label in required):
            all_required_verified_cases.append(c.case_id)
    assert len(all_required_verified_cases) == 40

    # Check eligible cases for Task 2 expansion
    eligible_cases = [
        c for c in cases
        if is_case_eligible_for_adjudication(c, sidecar.labels_by_case_id.get(c.case_id))
    ]
    assert len(eligible_cases) == 205

    # Run selector on live promoted checkpoint
    selected = select_stratified_case_ids(
        cases,
        sidecar.labels_by_case_id,
        target_cases=20,
        seed="vietlex-p2-v1",
    )
    assert len(selected) == 20
    # None of the 40 already-verified cases should be selected
    assert set(selected).isdisjoint(set(all_required_verified_cases))


def test_task2_provider_free_strict_network_guard(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """7 & G. Strict provider-free boundary guard: monkeypatch network calls to raise immediately."""
    import http.client
    import socket
    import urllib.request

    def _forbidden_network(*args, **kwargs):
        raise RuntimeError("FORBIDDEN_NETWORK_CALL: Task 2 must be 100% provider-free local execution")

    monkeypatch.setattr(socket.socket, "connect", _forbidden_network)
    monkeypatch.setattr(urllib.request, "urlopen", _forbidden_network)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", _forbidden_network)

    try:
        import requests
        monkeypatch.setattr(requests.Session, "send", _forbidden_network)
    except ImportError:
        pass

    # Run the full queue CLI flow with 30 cases -> exactly 20 selected
    dataset_path, sidecar_path, documents = _write_cli_review_inputs(tmp_path, case_count=30)
    content_store_path = tmp_path / "content.sqlite3"
    fts_path = tmp_path / "fts.sqlite3"
    content_store_path.touch()
    fts_path.touch()

    cli = _configure_cli_runtime(monkeypatch, tmp_path, documents)
    queue_root = tmp_path / "queue-guard"

    result = cli.main([
        "queue", "--dataset", str(dataset_path), "--sidecar", str(sidecar_path),
        "--content-store", str(content_store_path), "--fts", str(fts_path),
        "--target-cases", "20", "--write-preview",
        "--output-root", str(queue_root), "--run-id", "guard-run",
    ])
    assert result == 0
    assert (queue_root / "guard-run" / "queue.json").exists()


def test_task2_cli_queue_with_20_cases_and_preview_and_input_immutability(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    """B, E, H. CLI generates 20-case batch, writes preview, leaves inputs strictly immutable."""
    dataset_path, sidecar_path, documents = _write_cli_review_inputs(tmp_path, case_count=30)
    content_store_path = tmp_path / "content.sqlite3"
    fts_path = tmp_path / "fts.sqlite3"
    content_store_path.touch()
    fts_path.touch()

    dataset_bytes_before = dataset_path.read_bytes()
    sidecar_bytes_before = sidecar_path.read_bytes()

    cli = _configure_cli_runtime(monkeypatch, tmp_path, documents)
    queue_root = tmp_path / "queue-runs-task2"

    assert cli.main([
        "queue", "--dataset", str(dataset_path), "--sidecar", str(sidecar_path),
        "--content-store", str(content_store_path), "--fts", str(fts_path),
        "--target-cases", "20", "--write-preview",
        "--output-root", str(queue_root), "--run-id", "task2-queue-20",
    ]) == 0

    # Verify input immutability (E)
    assert dataset_path.read_bytes() == dataset_bytes_before
    assert sidecar_path.read_bytes() == sidecar_bytes_before

    # Verify output artifacts
    run_dir = queue_root / "task2-queue-20"
    assert (run_dir / "queue.json").exists()
    assert (run_dir / "decision_template.json").exists()
    assert (run_dir / "queue_summary.json").exists()
    assert (run_dir / "queue_preview.md").exists()

    queue_data = json.loads((run_dir / "queue.json").read_text(encoding="utf-8"))
    assert queue_data["target_case_count"] == 20
    assert queue_data["selected_case_count"] == 20
    assert len(queue_data["selected_case_ids"]) == 20
    assert queue_data["queue_status"] == "READY_FOR_REVIEW"
    assert queue_data["provider_calls"] == 0

    preview_text = (run_dir / "queue_preview.md").read_text(encoding="utf-8")
    assert "ADJUDICATION CANDIDATE QUEUE" in preview_text
    assert "NOT verified legal facts" in preview_text
    assert "PENDING_HUMAN" in preview_text


def test_task2_rerun_safety_prevents_overwrite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    """I. Re-run safety: attempting to re-execute with identical run-id fails closed without overwrite."""
    dataset_path, sidecar_path, documents = _write_cli_review_inputs(tmp_path, case_count=30)
    content_store_path = tmp_path / "content.sqlite3"
    fts_path = tmp_path / "fts.sqlite3"
    content_store_path.touch()
    fts_path.touch()

    cli = _configure_cli_runtime(monkeypatch, tmp_path, documents)
    queue_root = tmp_path / "queue-runs-task2-rerun"

    args = [
        "queue", "--dataset", str(dataset_path), "--sidecar", str(sidecar_path),
        "--content-store", str(content_store_path), "--fts", str(fts_path),
        "--target-cases", "20",
        "--output-root", str(queue_root), "--run-id", "rerun-target",
    ]

    assert cli.main(args) == 0

    # Second run with same run-id must raise FileExistsError
    with pytest.raises(FileExistsError):
        cli.main(args)
