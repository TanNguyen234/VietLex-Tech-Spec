import pytest


def _evidence() -> list[dict]:
    return [
        {
            "evidence_id": "ev-1",
            "source_url": "https://vbpl.vn/van-ban/01",
            "excerpt": (
                "Văn bản 01/2020/QH14 có hiệu lực thi hành từ ngày 01/01/2021. "
                "Văn bản 01/2020/QH14 bị bãi bỏ ngày 01/01/2024."
            ),
        }
    ]


@pytest.mark.parametrize("kind, expected", [("repeal", "partially_effective"), ("replace", "partially_effective"), ("amend", "amended")])
def test_later_partial_event_qualifies_effective_status(kind, expected):
    from app.services.legal_effect import review_legal_effect

    evidence = _evidence()
    events = [
        dict(event_kind="effective", effective_date="2021-01-01",
             document_number="01/2020/QH14", target_document_number="01/2020/QH14",
             evidence_id="ev-1", exact_quote=evidence[0]["excerpt"].split(". ")[0] + ".",
             scope="whole_document"),
        dict(event_kind=kind, effective_date="2024-01-01",
             document_number="01/2020/QH14", target_document_number="01/2020/QH14",
             evidence_id="ev-1", exact_quote="Văn bản 01/2020/QH14 bị bãi bỏ ngày 01/01/2024.",
             scope="partial"),
    ]
    assert review_legal_effect(evidence, "2023-01-01", events)["result"]["effects"][0]["status"] == "effective"
    assert review_legal_effect(evidence, "2024-01-01", events)["result"]["effects"][0]["status"] == expected
    events[1]["event_kind"] = "repeal"
    events[1]["scope"] = "whole_document"
    assert review_legal_effect(evidence, "2024-01-01", events)["result"]["effects"][0]["status"] == "repealed"


def test_duplicate_evidence_ids_are_rejected_instead_of_overwriting_provenance():
    from app.services.legal_effect import review_legal_effect

    with pytest.raises(ValueError, match="invalid_legal_effect_event"):
        review_legal_effect(_evidence() * 2, "2023-01-01", [])


def test_legal_effect_uses_explicit_official_effective_event_only() -> None:
    from app.services.legal_effect import review_legal_effect

    result = review_legal_effect(
        _evidence(),
        "2023-06-01",
        [
            {
                "event_kind": "effective",
                "effective_date": "2021-01-01",
                "document_number": "01/2020/QH14",
                "target_document_number": "01/2020/QH14",
                "evidence_id": "ev-1",
                "exact_quote": "Văn bản 01/2020/QH14 có hiệu lực thi hành từ ngày 01/01/2021.",
                "scope": "whole_document",
            }
        ],
    )

    assert result["status"] == "reviewed"
    assert result["result"]["method"] == "human_admin_reviewed_events"
    assert result["result"]["legal_certification"] is False
    assert result["result"]["effects"] == [
        {
            "target_document_number": "01/2020/QH14",
            "as_of": "2023-06-01",
            "status": "effective",
            "reasons": [],
        }
    ]
    assert (
        result["result"]["assertions"][0]["source_url"] == "https://vbpl.vn/van-ban/01"
    )
    assert result["result"]["assertions"][0]["source_sha256"]


def test_legal_effect_does_not_infer_status_from_amendment() -> None:
    from app.services.legal_effect import review_legal_effect

    evidence = _evidence()
    evidence[0]["excerpt"] = (
        "Văn bản 02/2021/QH15 sửa đổi Văn bản 01/2020/QH14 ngày 01/01/2022."
    )
    result = review_legal_effect(
        evidence,
        "2023-06-01",
        [
            {
                "event_kind": "amend",
                "effective_date": "2022-01-01",
                "document_number": "02/2021/QH15",
                "target_document_number": "01/2020/QH14",
                "evidence_id": "ev-1",
                "exact_quote": "Văn bản 02/2021/QH15 sửa đổi Văn bản 01/2020/QH14 ngày 01/01/2022.",
                "scope": "whole_document",
            }
        ],
    )

    assert result["status"] == "unknown"
    assert result["result"]["effects"][0]["status"] == "unknown"
    assert result["result"]["effects"][0]["reasons"] == [
        "amendment_does_not_establish_effect"
    ]


def test_legal_effect_marks_conflicting_same_date_effect_events_unknown() -> None:
    from app.services.legal_effect import review_legal_effect

    evidence = _evidence()
    evidence[0]["excerpt"] = evidence[0]["excerpt"].replace("01/01/2024", "01/01/2021")
    result = review_legal_effect(
        evidence,
        "2023-06-01",
        [
            {
                "event_kind": "effective",
                "effective_date": "2021-01-01",
                "document_number": "01/2020/QH14",
                "target_document_number": "01/2020/QH14",
                "evidence_id": "ev-1",
                "exact_quote": "Văn bản 01/2020/QH14 có hiệu lực thi hành từ ngày 01/01/2021.",
                "scope": "whole_document",
            },
            {
                "event_kind": "repeal",
                "effective_date": "2021-01-01",
                "document_number": "01/2020/QH14",
                "target_document_number": "01/2020/QH14",
                "evidence_id": "ev-1",
                "exact_quote": "Văn bản 01/2020/QH14 bị bãi bỏ ngày 01/01/2021.",
                "scope": "whole_document",
            },
        ],
    )

    assert result["status"] == "unknown"
    assert result["result"]["effects"][0]["reasons"] == ["conflicting_effect_events"]


@pytest.mark.parametrize(
    "url, quote",
    [
        (
            "https://example.com/law",
            "Văn bản 01/2020/QH14 có hiệu lực thi hành từ ngày 01/01/2021.",
        ),
        ("https://vbpl.vn/law", "   "),
    ],
)
def test_legal_effect_rejects_nonofficial_sources_and_invalid_quotes(
    url: str, quote: str
) -> None:
    from app.services.legal_effect import review_legal_effect

    evidence = _evidence()
    evidence[0]["source_url"] = url
    with pytest.raises(ValueError, match="invalid_legal_effect_event"):
        review_legal_effect(
            evidence,
            "2023-06-01",
            [
                {
                    "event_kind": "effective",
                    "effective_date": "2021-01-01",
                    "document_number": "01/2020/QH14",
                    "target_document_number": "01/2020/QH14",
                    "evidence_id": "ev-1",
                    "exact_quote": quote,
                    "scope": "whole_document",
                }
            ],
        )


def test_legal_effect_requires_known_state_when_no_reviewed_event_exists() -> None:
    from app.services.legal_effect import review_legal_effect

    result = review_legal_effect(_evidence(), "2023-06-01", [])

    assert result["status"] == "unknown"
    assert result["result"]["effects"] == []
    assert result["result"]["reasons"] == ["no_reviewed_events"]


def test_legal_effect_allows_registered_chinhphu_source_and_requires_scope() -> None:
    from app.services.legal_effect import review_legal_effect

    evidence = _evidence()
    evidence[0]["source_url"] = "https://vanban.chinhphu.vn/van-ban/01"
    event = {
        "event_kind": "effective",
        "effective_date": "2021-01-01",
        "document_number": "01/2020/QH14",
        "target_document_number": "01/2020/QH14",
        "evidence_id": "ev-1",
        "exact_quote": "Văn bản 01/2020/QH14 có hiệu lực thi hành từ ngày 01/01/2021.",
        "scope": "partial",
    }

    result = review_legal_effect(evidence, "2023-06-01", [event])

    assert result["result"]["effects"][0]["reasons"] == [
        "partial_scope_does_not_establish_document_effect"
    ]
    event.pop("scope")
    with pytest.raises(ValueError, match="invalid_legal_effect_event"):
        review_legal_effect(evidence, "2023-06-01", [event])
