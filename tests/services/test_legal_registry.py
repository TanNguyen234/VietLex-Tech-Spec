import pytest
from app.services.legal_effect import review_legal_effect


def review():
    text = "Văn bản A/2020 có hiệu lực từ ngày 01/01/2021. Văn bản B/2024 bãi bỏ A/2020 từ ngày 01/01/2024."
    evidence = [
        dict(
            evidence_id="private-evidence",
            source_url="https://vanban.chinhphu.vn/?docid=1",
            excerpt=text,
            note="PRIVATE NOTE",
        )
    ]
    events = [
        dict(
            event_kind="effective",
            effective_date="2021-01-01",
            document_number="A/2020",
            target_document_number="A/2020",
            evidence_id="private-evidence",
            exact_quote=text.split(". ")[0] + ".",
            scope="whole_document",
        ),
        dict(
            event_kind="repeal",
            effective_date="2024-01-01",
            document_number="B/2024",
            target_document_number="A/2020",
            evidence_id="private-evidence",
            exact_quote=text.split(". ")[1],
            scope="whole_document",
        ),
    ]
    return dict(
        analysis_id="review-1",
        kind="legal_effect_review",
        reviewer_id="reviewer-private",
        reviewed_at="2026-09-19T00:00:00+00:00",
        evidence_snapshot=evidence,
        **review_legal_effect(evidence, "2026-09-19", events),
    )


def test_published_projection_respects_as_of_and_hides_private_fields():
    from app.services.legal_registry import publication_record, registry_view

    record = publication_record(review(), "publisher-private")
    old = registry_view("a/2020", "2023-01-01", [record])
    new = registry_view("A/2020", "2024-01-01", [record])
    assert old["status"] == "effective" and new["status"] == "repealed"
    assert old["effective_from"] == "2021-01-01" and old["effective_to"] == "2024-01-01"
    assert new["legal_certification"] is False and new["history_complete"] is False
    assert (
        "PRIVATE NOTE" not in str(new)
        and "reviewer-private" not in str(new)
        and "private-evidence" not in str(new)
    )
    assert new["events"][0]["official_source"].startswith("https://vanban.chinhphu.vn/")


def test_withdrawn_events_do_not_establish_status():
    from app.services.legal_registry import publication_record, registry_view

    record = publication_record(review(), "publisher")
    record["state"] = "withdrawn"
    assert registry_view("A/2020", "2026-09-19", [record])["status"] == "unknown"
    assert (
        registry_view(
            "X/2020", "2026-09-19", [publication_record(review(), "publisher")]
        )["status"]
        == "unknown"
    )


def test_publication_revalidates_quote_and_requires_recorded_human_review():
    from app.services.legal_registry import publication_record

    invalid = review()
    invalid["result"]["assertions"][0]["exact_quote"] = "invented"
    with pytest.raises(ValueError):
        publication_record(invalid, "publisher")
    invalid = review()
    invalid["reviewer_id"] = ""
    with pytest.raises(ValueError):
        publication_record(invalid, "publisher")


def test_relations_are_directional_and_not_active_before_the_event():
    from app.services.legal_registry import publication_record, registry_view

    record = publication_record(review(), "publisher")
    event = record["assertions"][1]
    event["event_kind"] = "replace"
    source = registry_view("B/2024", "2024-01-01", [record])
    target = registry_view("A/2020", "2024-01-01", [record])
    assert source["replaces"] == ["A/2020"] and target["replaced_by"] == ["B/2024"]
    assert registry_view("A/2020", "2023-01-01", [record])["replaced_by"] == []
