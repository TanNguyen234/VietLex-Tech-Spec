from __future__ import annotations

from app.evaluation.retrieval_metrics import match_gold_to_stage_candidate
from app.evaluation.schemas import CandidateChunk, EvidenceStatus, GoldEvidence, RequiredLevel


def _gold_clause(clause: str = "2") -> GoldEvidence:
    return GoldEvidence(
        evidence_item_id="ev-1",
        case_id="case_001",
        document_id=431147,
        document_number="72/2020/QH14",
        article="Điều 16",
        clause=clause,
        required=True,
        required_level=RequiredLevel.CLAUSE,
        status=EvidenceStatus.VERIFIED,
    )


def test_whole_article_candidate_satisfies_literal_sequential_ordinal_clause() -> None:
    whole_article = CandidateChunk(
        document_id=431147,
        document_number="72/2020/QH14",
        title="Luật Bảo vệ môi trường 2020",
        source_url="https://vbpl.vn/431147",
        citation="72/2020/QH14, Điều 16",
        article="Điều 16",
        clause=None,
        text=(
            "Điều 16. Phân loại khu vực ô nhiễm môi trường đất "
            "1. Khu vực ô nhiễm môi trường đất là khu vực đất có chất ô nhiễm vượt mức cho phép. "
            "2. Khu vực ô nhiễm môi trường đất được phân loại theo tiêu chí nguồn gây ô nhiễm, khả năng lan truyền, đối tượng chịu tác động. "
            "3. Khu vực ô nhiễm môi trường đất được phân loại theo mức độ ô nhiễm."
        ),
        token_count=75,
    )
    assert match_gold_to_stage_candidate(_gold_clause("1"), whole_article) == (True, True, True)
    assert match_gold_to_stage_candidate(_gold_clause("2"), whole_article) == (True, True, True)
    assert match_gold_to_stage_candidate(_gold_clause("Khoản 3"), whole_article) == (True, True, True)
    # Non-existent clause 4 must NOT match
    assert match_gold_to_stage_candidate(_gold_clause("4"), whole_article) == (True, True, False)


def test_partial_fragment_and_cross_reference_do_not_falsely_match_clause() -> None:
    # Mid-article tail fragment missing sequential 1. start
    tail_fragment = CandidateChunk(
        document_id=431147,
        document_number="72/2020/QH14",
        title="Luật Bảo vệ môi trường 2020",
        source_url="https://vbpl.vn/431147",
        citation="72/2020/QH14, Điều 16",
        article="Điều 16",
        clause=None,
        text="Điều 16. Phân loại khu vực ô nhiễm môi trường đất 2. Chỉ còn đoạn giữa mà thiếu khoản 1.",
        token_count=20,
    )
    assert match_gold_to_stage_candidate(_gold_clause("2"), tail_fragment) == (True, True, False)

    # Cross-reference "theo khoản 2. " inside clause 1 must NOT count as literal clause 2
    cross_ref = CandidateChunk(
        document_id=431147,
        document_number="72/2020/QH14",
        title="Luật Bảo vệ môi trường 2020",
        source_url="https://vbpl.vn/431147",
        citation="72/2020/QH14, Điều 16",
        article="Điều 16",
        clause=None,
        text="Điều 16. Phân loại 1. Thực hiện theo khoản 2. Quy định chi tiết.",
        token_count=14,
    )
    assert match_gold_to_stage_candidate(_gold_clause("2"), cross_ref) == (True, True, False)
