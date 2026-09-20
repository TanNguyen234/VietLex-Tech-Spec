import pytest


def workspace():
    def row(id, digest, pages):
        return {
            "analysis_id": id,
            "kind": "trusted_sources",
            "result": {
                "sources": [
                    {
                        "url": "https://vanban.chinhphu.vn/?docid=1",
                        "document_sha256": digest,
                        "page_count": 3,
                        "pages": pages,
                        "method": "vertex_ocr",
                        "title": "Law",
                    }
                ]
            },
        }

    return {
        "analyses": [
            row(
                "first",
                "a" * 64,
                [{"page": 1, "text": "First"}, {"page": 2, "text": "Old"}],
            ),
            row("other", "b" * 64, [{"page": 3, "text": "Wrong version"}]),
            row("last", "a" * 64, [{"page": 2, "text": "New"}]),
        ]
    }


def test_collects_same_version_in_page_order_without_inventing_missing_text():
    from app.services.retained_source_analysis import collect_retained_source

    source = collect_retained_source(workspace(), "first", 0)
    assert [(p["page"], p["text"]) for p in source["pages"]] == [
        (1, "First"),
        (2, "New"),
    ]
    assert source["missing_pages"] == [3]
    assert source["readable_pages"] == [1, 2]
    assert source["pages"][1]["analysis_id"] == "last"
    assert "Wrong version" not in str(source)


def test_rejects_oversize_instead_of_silently_cutting():
    from app.services.retained_source_analysis import collect_retained_source

    data = workspace()
    data["analyses"][0]["result"]["sources"][0]["pages"][0]["text"] = "x" * 120001
    with pytest.raises(ValueError, match="source_scope_too_large"):
        collect_retained_source(data, "first", 0)


def test_no_source_or_hash_cannot_expand_scope():
    from app.services.retained_source_analysis import collect_retained_source

    with pytest.raises(ValueError):
        collect_retained_source(workspace(), "missing", 0)
    data = workspace()
    data["analyses"][0]["result"]["sources"][0]["document_sha256"] = ""
    with pytest.raises(ValueError):
        collect_retained_source(data, "first", 0)


def test_pdf_window_truncation_flag_does_not_discard_retained_pages():
    from app.services.retained_source_analysis import collect_retained_source

    data = workspace()
    for row in data["analyses"]:
        row["result"]["sources"][0]["truncated"] = True
    assert collect_retained_source(data, "first", 0)["readable_pages"] == [1, 2]


def test_model_selects_server_passages_without_retyping_legal_text():
    from app.services.retained_source_analysis import (
        collect_retained_source,
        validate_source_answer,
    )

    source = collect_retained_source(workspace(), "first", 0)
    raw = {
        "text": "New (trang 2)",
        "status": "ok",
        "unanswered_parts": [],
        "citations": ["p2-s0"],
    }
    result = validate_source_answer(raw, source)
    assert result["citations"][0]["quote"] == "New"
    assert result["citations"][0]["page"] == 2
    raw["citations"] = ["p999-s0"]
    with pytest.raises(ValueError):
        validate_source_answer(raw, source)


def test_passages_preserve_every_character_without_duplication():
    from app.services.retained_source_analysis import source_passages

    text = ("Điều khoản có dấu.\n" * 150) + "End"
    source = {
        "pages": [{"page": 1, "text": text, "analysis_id": "read", "source_index": 0}]
    }
    passages = list(source_passages(source).values())
    assert "".join(p["quote"] for p in passages) == text
    assert all(len(p["quote"]) <= 900 for p in passages)


@pytest.mark.asyncio
async def test_provider_receives_the_same_ids_accepted_by_validator(monkeypatch):
    import json
    from types import SimpleNamespace
    from app.services import retained_source_analysis as service

    source = service.collect_retained_source(workspace(), "first", 0)

    async def generate(prompt, system):
        supplied = json.loads(prompt)["source"]["passages"]
        assert supplied[1]["passage_id"] == "p2-s0"
        return SimpleNamespace(
            status="success",
            text=json.dumps(
                {
                    "text": "New",
                    "status": "ok",
                    "citations": [supplied[1]["passage_id"]],
                    "unanswered_parts": [],
                }
            ),
            observed_provider="test",
            observed_model="test",
        )

    monkeypatch.setattr(service, "_generate", generate)
    result = await service.analyze_retained_source("Explain", source)
    assert result["citations"][0]["quote"] == "New"


def test_long_document_accepts_32_real_citations_without_dropping_them():
    from app.services.retained_source_analysis import (
        source_passages,
        validate_source_answer,
    )

    source = {
        "pages": [
            {"page": 1, "text": "a " * 16000, "analysis_id": "read", "source_index": 0}
        ]
    }
    ids = list(source_passages(source))[:32]
    result = validate_source_answer(
        {"text": "Summary", "status": "ok", "unanswered_parts": [], "citations": ids},
        source,
    )
    assert len(result["citations"]) == 32


def test_official_metadata_is_citable_but_not_presented_as_pdf_quote():
    from app.services.retained_source_analysis import (
        collect_retained_source,
        validate_source_answer,
        source_passages,
    )

    data = workspace()
    anchor = data["analyses"][0]["result"]["sources"][0]
    anchor.update(
        document_number="68/2026/TT-BXD",
        issued_date="10-09-2026",
        reported_effective_from="01-01-2027",
    )
    source = collect_retained_source(data, "first", 0)
    metadata = source_passages(source)["source-metadata"]
    assert metadata["citation_kind"] == "metadata"
    assert "10-09-2026" in metadata["quote"]
    result = validate_source_answer(
        {
            "text": "Date from portal",
            "status": "ok",
            "unanswered_parts": [],
            "citations": ["source-metadata"],
        },
        source,
    )
    assert result["citations"][0]["analysis_id"] == "first"
