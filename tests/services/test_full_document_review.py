from app.services.full_document_review import (
    aggregate_full_document_review,
    plan_full_document_review,
)


def _document() -> dict:
    return {
        "document_id": "doc-1",
        "clauses": [
            {"clause_id": "c-1", "title": "One", "text": "one two"},
            {"clause_id": "c-2", "title": "Two", "text": "three four"},
        ],
    }


def test_plan_covers_each_clause_and_completion_requires_all_batches(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.full_document_review.get_settings",
        lambda: type("S", (), {"LLM_CONTEXT_MAX_TOKENS": 5})(),
    )
    plan = plan_full_document_review(_document(), [])

    assert plan["coverage"]["scheduled_clauses"] == 2
    assert len(plan["batches"]) == 2
    partial = aggregate_full_document_review(
        plan,
        [
            {
                "kind": "full_document_review",
                "status": "ok",
                "document_id": "doc-1",
                "input_sha256": plan["input_sha256"],
                "clause_ids": ["c-1"],
            }
        ],
    )
    assert partial["status"] == "review_incomplete"
    complete = aggregate_full_document_review(
        plan,
        [
            {
                "kind": "full_document_review",
                "status": "ok",
                "document_id": "doc-1",
                "input_sha256": plan["input_sha256"],
                "clause_ids": ["c-1", "c-2"],
            }
        ],
    )
    assert complete["status"] == "complete"


def test_plan_marks_oversized_clause_as_incomplete(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.full_document_review.get_settings",
        lambda: type("S", (), {"LLM_CONTEXT_MAX_TOKENS": 2})(),
    )
    plan = plan_full_document_review(_document(), [])

    assert plan["status"] == "review_incomplete"
    assert plan["skipped"][0]["reason"] == "clause_exceeds_context_budget"


def test_stored_progress_survives_unrelated_analysis_history(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.full_document_review.get_settings",
        lambda: type("S", (), {"LLM_CONTEXT_MAX_TOKENS": 5})(),
    )
    document = _document()
    initial = plan_full_document_review(document, [])
    document["full_review_progress"] = [
        {"input_sha256": initial["input_sha256"], "completed_clause_ids": ["c-1"]}
    ]
    plan = plan_full_document_review(document, [])

    aggregate = aggregate_full_document_review(
        plan, [{"kind": "other"} for _ in range(50)]
    )

    assert aggregate["coverage"]["reviewed_clauses"] == 1
    assert aggregate["status"] == "review_incomplete"
