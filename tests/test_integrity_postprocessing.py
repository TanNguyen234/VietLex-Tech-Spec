from app.ingestion.schemas import LegalDocumentSchema, ProcessingDisposition
from app.ingestion.postprocessing.pipeline import LegalPreprocessingPipeline


def _doc_text(number: str = "01/2026/UT", article: str = "Scope") -> str:
    return "\n".join([
        "LAW",
        f"So: {number}",
        f"Dieu 1. {article}",
        "This article defines the scope.",
        "1. First clause.",
        "a) First point.",
    ])


def _html_for(text: str) -> str:
    blocks = "".join(f"<p>{line}</p>" for line in text.splitlines())
    return f"<html><body><main data-template='unit-legal-v1'>{blocks}</main></body></html>"


def _pipeline_result(doc: LegalDocumentSchema):
    return LegalPreprocessingPipeline().process(doc)


def test_equivalent_full_text_and_html_merge_with_evidence_graph():
    text = _doc_text()
    doc = LegalDocumentSchema(
        source_id="unit_equivalent",
        source="unit.test",
        url="https://unit.test/legal/1",
        title="Unit legal fixture",
        official_number="01/2026/UT",
        full_text=text,
        html_text=_html_for(text),
    )

    result = _pipeline_result(doc)

    assert result.disposition in {
        ProcessingDisposition.PASS,
        ProcessingDisposition.PASS_WITH_UNKNOWN_METADATA,
    }
    assert result.candidate_decision == "Winner"
    assert result.confidence_explanation.winner == "merged_equivalent"
    assert result.evidence_graph is not None
    assert result.evidence_graph.body_hash == result.body_hash
    assert result.chunks


def test_conflicting_valid_body_candidates_are_quarantined():
    full_text = _doc_text(number="01/2026/UT", article="Full text body")
    html_text = _html_for(_doc_text(number="01/2026/UT", article="HTML body"))
    doc = LegalDocumentSchema(
        source_id="unit_conflict",
        source="unit.test",
        url="https://unit.test/legal/conflict",
        title="Unit legal fixture",
        official_number="01/2026/UT",
        full_text=full_text,
        html_text=html_text,
    )

    result = _pipeline_result(doc)

    assert result.disposition == ProcessingDisposition.AMBIGUOUS
    assert result.chunks == []
    assert "Multiple valid body candidates disagree" in result.confidence_explanation.reason


def test_missing_body_fails_closed():
    doc = LegalDocumentSchema(
        source_id="unit_missing",
        source="unit.test",
        url="https://unit.test/legal/missing",
        title="Empty",
        full_text="",
        html_text="",
    )

    result = _pipeline_result(doc)

    assert result.disposition == ProcessingDisposition.FAIL
    assert result.chunks == []
    assert result.confidence_explanation.winner == "none"


def test_unknown_html_template_is_not_indexable():
    text = _doc_text()
    doc = LegalDocumentSchema(
        source_id="unit_unknown_template",
        source="unknown.example",
        url="https://unknown.example/legal/1",
        title="Unknown template",
        full_text="",
        html_text=_html_for(text),
    )

    result = _pipeline_result(doc)

    assert result.disposition == ProcessingDisposition.FAIL
    assert result.chunks == []
    assert any("UNKNOWN_HTML_TEMPLATE" in err for err in result.validation.errors)


def test_root_level_clause_becomes_unresolved_and_blocks_indexing():
    doc = LegalDocumentSchema(
        source_id="unit_root_clause",
        source="unit.test",
        url="https://unit.test/legal/root-clause",
        title="Root clause",
        full_text="1. Clause without article parent.",
    )

    result = _pipeline_result(doc)

    assert result.disposition == ProcessingDisposition.FAIL
    assert result.chunks == []
    assert result.validation.unresolved_blocks


def test_metadata_conflict_is_logged_without_silent_trust():
    doc = LegalDocumentSchema(
        source_id="unit_meta_conflict",
        source="unit.test",
        url="https://unit.test/legal/meta-conflict",
        title="Metadata conflict",
        official_number="11/2026/UT",
        full_text=_doc_text(number="99/2026/UT"),
    )

    result = _pipeline_result(doc)

    assert result.metadata.official_number.method == "direct_with_conflict"
    assert result.metadata.official_number.conflicts


def test_chunk_ids_and_audit_id_are_deterministic():
    doc = LegalDocumentSchema(
        source_id="unit_deterministic",
        source="unit.test",
        url="https://unit.test/legal/deterministic",
        title="Deterministic",
        official_number="01/2026/UT",
        full_text=_doc_text(),
    )

    first = _pipeline_result(doc)
    second = _pipeline_result(doc)

    assert first.audit_id == second.audit_id
    assert [chunk.chunk_id for chunk in first.chunks] == [chunk.chunk_id for chunk in second.chunks]


def test_appendix_blocks_are_chunked_once():
    text = "\n".join([
        "LAW",
        "So: 02/2026/UT",
        "Dieu 1. Scope",
        "Article body.",
        "1. Clause body.",
        "PHU LUC I",
        "Appendix body.",
    ])
    doc = LegalDocumentSchema(
        source_id="unit_appendix",
        source="unit.test",
        url="https://unit.test/legal/appendix",
        title="Appendix",
        official_number="02/2026/UT",
        full_text=text,
    )

    result = _pipeline_result(doc)

    assert result.disposition in {
        ProcessingDisposition.PASS,
        ProcessingDisposition.PASS_WITH_UNKNOWN_METADATA,
    }
    assert any(chunk.node_type == "appendix" for chunk in result.chunks)
    assert all(count == 1 for count in result.validation.block_coverage.values())
