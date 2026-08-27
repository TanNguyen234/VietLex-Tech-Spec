from __future__ import annotations

import pytest

from app.ingestion.legal_text import EvidenceChunk


def _evidence(document_id: int, text: str) -> EvidenceChunk:
    return EvidenceChunk(
        document_id=document_id,
        document_number=f"{document_id}/2026/QH15",
        title="Luật",
        source_url=f"https://example.test/{document_id}",
        heading_path="Điều 1",
        article="Điều 1",
        clause=None,
        citation=f"{document_id}/2026/QH15, Điều 1",
        text=text,
        token_count=len(text.split()),
    )


def test_candidate_pool_hash_changes_with_order_or_text() -> None:
    from app.evaluation.candidate_pool import build_candidate_pool

    first = build_candidate_pool(
        "case", [_evidence(1, "alpha"), _evidence(2, "beta")], "contract"
    )
    reordered = build_candidate_pool(
        "case", [_evidence(2, "beta"), _evidence(1, "alpha")], "contract"
    )
    changed = build_candidate_pool(
        "case", [_evidence(1, "changed"), _evidence(2, "beta")], "contract"
    )

    assert first.candidate_ids_sha256 != reordered.candidate_ids_sha256
    assert first.candidate_payload_sha256 != changed.candidate_payload_sha256


def test_identical_pool_validation_fails_closed() -> None:
    from app.evaluation.candidate_pool import assert_identical_candidate_pool, build_candidate_pool

    first = build_candidate_pool("case", [_evidence(1, "alpha")], "contract")
    changed = build_candidate_pool("case", [_evidence(1, "beta")], "contract")

    with pytest.raises(ValueError, match="candidate pool"):
        assert_identical_candidate_pool(first, changed)
