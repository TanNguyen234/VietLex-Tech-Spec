import sqlite3
from unittest.mock import create_autospec

from app.evaluation.legal_citations import (
    LegalCitation,
    parse_legal_citations,
)
from app.evaluation.retrieval_metrics import extract_citations_from_text
from app.evaluation.schemas import EvidenceStatus, RequiredLevel
from app.ingestion.legal_fts import LegalFtsIndex
from audit_golden_dataset import (
    decide_evidence_verification,
    resolve_document_identity,
)


def test_two_documents_are_paired_by_position() -> None:
    text = (
        "Khoản 1 Điều 2 văn bản 12/2026/NĐ-CP và "
        "Khoản 3 Điều 4 văn bản 13/2026/NĐ-CP"
    )

    assert parse_legal_citations(text) == [
        LegalCitation(
            document_number="12/2026/NĐ-CP",
            article="Điều 2",
            clause="Khoản 1",
        ),
        LegalCitation(
            document_number="13/2026/NĐ-CP",
            article="Điều 4",
            clause="Khoản 3",
        ),
    ]


def test_second_article_inherits_shared_document_number() -> None:
    text = (
        "Khoản 1 Điều 2 văn bản 12/2026/NĐ-CP và "
        "Khoản 3 Điều 4 cùng văn bản"
    )

    assert parse_legal_citations(text) == [
        LegalCitation("12/2026/NĐ-CP", "Điều 2", "Khoản 1"),
        LegalCitation("12/2026/NĐ-CP", "Điều 4", "Khoản 3"),
    ]


def test_multiple_articles_without_document_are_preserved() -> None:
    assert parse_legal_citations(
        "Khoản 1 Điều 2 và Khoản 3 Điều 4"
    ) == [
        LegalCitation("", "Điều 2", "Khoản 1"),
        LegalCitation("", "Điều 4", "Khoản 3"),
    ]


def test_repeated_units_are_deduplicated_stably() -> None:
    text = "Điều 2 12/2026/NĐ-CP; Điều 2 12/2026/NĐ-CP"

    assert parse_legal_citations(text) == [
        LegalCitation("12/2026/NĐ-CP", "Điều 2", "")
    ]


def test_shared_trailing_document_applies_without_cartesian_product() -> None:
    text = (
        "Khoản 1 Điều 2 và Khoản 3 Điều 4 "
        "văn bản 12/2026/NĐ-CP"
    )

    assert parse_legal_citations(text) == [
        LegalCitation("12/2026/NĐ-CP", "Điều 2", "Khoản 1"),
        LegalCitation("12/2026/NĐ-CP", "Điều 4", "Khoản 3"),
    ]


def test_multiple_clauses_for_one_article_are_preserved() -> None:
    text = "Khoản 1 và Khoản 2 Điều 3 văn bản 12/2026/NĐ-CP"

    assert parse_legal_citations(text) == [
        LegalCitation("12/2026/NĐ-CP", "Điều 3", "Khoản 1"),
        LegalCitation("12/2026/NĐ-CP", "Điều 3", "Khoản 2"),
    ]


def test_compatibility_wrapper_returns_explicit_dictionaries() -> None:
    assert extract_citations_from_text(
        "Khoản 1 Điều 2 văn bản 12/2026/NĐ-CP"
    ) == [
        {
            "document_number": "12/2026/NĐ-CP",
            "article": "Điều 2",
            "clause": "Khoản 1",
        }
    ]


def test_missing_structural_chunk_never_verifies_hint() -> None:
    status, article, clause = decide_evidence_verification(
        RequiredLevel.CLAUSE,
        "Điều 5",
        "Khoản 2",
        None,
    )

    assert status == EvidenceStatus.STRUCTURAL_ANCHOR_NOT_FOUND
    assert article is None
    assert clause is None


def test_document_level_verification_does_not_require_structural_chunk() -> None:
    status, article, clause = decide_evidence_verification(
        RequiredLevel.DOCUMENT,
        "",
        "",
        None,
    )

    assert status == EvidenceStatus.VERIFIED
    assert article is None
    assert clause is None


def identity_db() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE metadata ("
        "document_id INTEGER PRIMARY KEY, "
        "source_url TEXT, document_number TEXT)"
    )
    connection.execute(
        "INSERT INTO metadata VALUES (?, ?, ?)",
        (7, "https://example.invalid/doc-7", "12/2026/NĐ-CP"),
    )
    return connection


def test_identity_without_real_hints_is_not_applicable() -> None:
    connection = identity_db()
    fts = create_autospec(LegalFtsIndex, instance=True, spec_set=True)

    assert resolve_document_identity(
        connection, fts, None, None, None
    ) == ([], "not_applicable", [], True)
    fts.search.assert_not_called()


def test_identity_id_and_url_branches_require_supplied_hints() -> None:
    connection = identity_db()
    fts = create_autospec(LegalFtsIndex, instance=True, spec_set=True)

    assert resolve_document_identity(
        connection, fts, 7, None, None
    ) == ([7], "exact_doc_id", ["dataset_reference_doc_id"], True)
    assert resolve_document_identity(
        connection,
        fts,
        None,
        "https://example.invalid/doc-7",
        None,
    ) == (
        [7],
        "exact_source_url",
        ["dataset_reference_source_url"],
        True,
    )
    fts.search.assert_not_called()
