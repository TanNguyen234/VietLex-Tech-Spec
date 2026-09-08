import pytest

from app.services.document_redline import compare_documents


def _document(document_id: str, *clauses: dict) -> dict:
    return {"document_id": document_id, "clauses": list(clauses)}


def _clause(clause_id: str, title: str, text: str, page: int = 1) -> dict:
    return {
        "clause_id": clause_id,
        "title": title,
        "text": text,
        "page": page,
    }


def test_compare_documents_reports_textual_changes_and_exact_spans() -> None:
    result = compare_documents(
        _document("draft-a", _clause("a-1", "Điều 1", "Thanh toán trong 30 ngày.")),
        _document("draft-b", _clause("b-1", "Điều 1", "Thanh toán trong 45 ngày.")),
    )

    assert result["schema_version"] == "document-redline-v1"
    assert result["document_a_id"] == "draft-a"
    assert result["document_b_id"] == "draft-b"
    assert result["legal_conclusion"] == "not_evaluated"
    assert result["added"] == []
    assert result["removed"] == []
    assert result["same"] == []
    changed = result["changed"]
    assert changed[0]["before"]["clause_id"] == "a-1"
    assert changed[0]["after"]["clause_id"] == "b-1"
    assert changed[0]["changes"] == [
        {
            "kind": "replace",
            "before": {"start": 17, "end": 19, "quote": "30"},
            "after": {"start": 17, "end": 19, "quote": "45"},
        }
    ]
    assert result["coverage"] == {
        "documents": {
            "numerator": 2,
            "denominator": 2,
            "omitted": 0,
            "omitted_reasons": [],
        },
        "clauses": {
            "numerator": 2,
            "denominator": 2,
            "omitted": 0,
            "omitted_reasons": [],
        },
    }


def test_compare_documents_handles_insertion_deletion_and_reordered_identical_clauses() -> (
    None
):
    result = compare_documents(
        _document(
            "draft-a",
            _clause("a-1", "Điều 1", "Giữ nguyên."),
            _clause("a-2", "Điều 2", "Bị xóa."),
        ),
        _document(
            "draft-b",
            _clause("b-3", "Điều 3", "Được thêm."),
            _clause("b-1", "Điều 1", "Giữ nguyên."),
        ),
    )

    assert result["same"] == [
        {
            "before": {"clause_id": "a-1", "title": "Điều 1", "page": 1},
            "after": {"clause_id": "b-1", "title": "Điều 1", "page": 1},
            "before_quote": {"start": 0, "end": 11, "quote": "Giữ nguyên."},
            "after_quote": {"start": 0, "end": 11, "quote": "Giữ nguyên."},
        }
    ]
    assert result["removed"] == [
        {
            "before": {"clause_id": "a-2", "title": "Điều 2", "page": 1},
            "before_quote": {"start": 0, "end": 7, "quote": "Bị xóa."},
        }
    ]
    assert result["added"] == [
        {
            "after": {"clause_id": "b-3", "title": "Điều 3", "page": 1},
            "after_quote": {"start": 0, "end": 10, "quote": "Được thêm."},
        }
    ]
    assert result["coverage"]["clauses"]["numerator"] == 4
    assert result["coverage"]["clauses"]["denominator"] == 4


def test_compare_documents_preserves_server_extracted_clause_order() -> None:
    result = compare_documents(
        _document(
            "draft-a", {**_clause("shared", "Điều 1", "Giữ nguyên."), "order": 4}
        ),
        _document(
            "draft-b", {**_clause("shared", "Điều 1", "Giữ nguyên."), "order": 7}
        ),
    )

    assert result["same"][0]["before"]["order"] == 4
    assert result["same"][0]["after"]["order"] == 7


def test_compare_documents_uses_a_bounded_coarse_span_for_long_repeated_text() -> None:
    before = "a" * 20_000
    after = "b" * 20_000

    result = compare_documents(
        _document("draft-a", _clause("a-1", "Điều 1", before)),
        _document("draft-b", _clause("b-1", "Điều 1", after)),
    )

    changed = result["changed"][0]
    assert changed["comparison_mode"] == "bounded_coarse_span"
    change = changed["changes"][0]
    assert change["kind"] == "replace"
    assert change["before"]["start"] == 0
    assert change["before"]["end"] == len(before)
    assert change["before"]["quote"] == before
    assert change["after"]["start"] == 0
    assert change["after"]["end"] == len(after)
    assert change["after"]["quote"] == after


@pytest.mark.parametrize(
    ("document_a", "document_b", "message"),
    [
        (
            _document("same", _clause("a-1", "Điều 1", "A")),
            _document("same", _clause("b-1", "Điều 1", "B")),
            "different document ids",
        ),
        (
            _document(
                "draft-a",
                _clause("duplicate", "Điều 1", "A"),
                _clause("duplicate", "Điều 2", "B"),
            ),
            _document("draft-b", _clause("b-1", "Điều 1", "A")),
            "duplicate clause_id",
        ),
        (
            _document(
                "draft-a", *[_clause(f"a-{index}", "Điều", "x") for index in range(101)]
            ),
            _document("draft-b", _clause("b-1", "Điều 1", "A")),
            "at most 100 clauses",
        ),
        (
            _document("draft-a", _clause("a-1", "Điều 1", "x" * 250_001)),
            _document("draft-b", _clause("b-1", "Điều 1", "A")),
            "250000 characters",
        ),
    ],
)
def test_compare_documents_rejects_invalid_or_over_limit_documents(
    document_a: dict, document_b: dict, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        compare_documents(document_a, document_b)
