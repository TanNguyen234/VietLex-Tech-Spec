from __future__ import annotations

from app.evaluation.schemas import EvidenceStatus, GoldEvidence, RequiredLevel


def _label(case: str, document: int, level: RequiredLevel) -> GoldEvidence:
    return GoldEvidence(
        evidence_item_id=f"{case}-{document}-{level.value}",
        case_id=case,
        document_id=document,
        document_number=str(document),
        required=True,
        required_level=level,
        status=EvidenceStatus.VERIFIED,
    )


def test_gold_distribution_reports_concentration_and_coverage() -> None:
    from scripts.audit_gold_distribution import audit_gold_distribution

    report = audit_gold_distribution(
        [
            _label("case_1", 1, RequiredLevel.DOCUMENT),
            _label("case_2", 1, RequiredLevel.ARTICLE),
            _label("case_3", 2, RequiredLevel.CLAUSE),
        ],
        legal_types={1: "Luật", 2: "Nghị định"},
    )

    assert report["verified_evidence"]["numerator"] == 3
    assert report["distinct_documents"] == 2
    assert report["distinct_legal_types"] == 2
    assert report["level_counts"] == {"article": 1, "clause": 1, "document": 1}
    assert report["max_document_evidence_share"] == 2 / 3
