from app.evaluation.retrieval_metrics import extract_citations_from_text
from audit_golden_dataset import decide_evidence_verification
from app.evaluation.schemas import RequiredLevel, EvidenceStatus
from app.evaluation.case_selection import select_evaluation_cases, GoldenCase
from unittest.mock import MagicMock

def test_extract_citations_from_text_sequential():
    # Defect 8: Extract citations sequentially to avoid Cartesian product
    text = "Theo quy định tại Khoản 1 Điều 2 Luật số 12/2026/NĐ-CP và Khoản 3 Điều 4"
    cites = extract_citations_from_text(text)
    
    assert len(cites) == 2
    assert cites[0]["document_number"] == "12/2026/NĐ-CP"
    assert cites[0]["article"] == "Điều 2"
    assert cites[0]["clause"] == "Khoản 1"
    
    assert cites[1]["document_number"] == "12/2026/NĐ-CP"
    assert cites[1]["article"] == "Điều 4"
    assert cites[1]["clause"] == "Khoản 3"

def test_decide_evidence_verification_extracts_vals():
    # Defect 6 & 7: decide_evidence_verification returns art_val and cl_val explicitly
    chunk = MagicMock()
    chunk.article = "Điều 5"
    chunk.clause = "Khoản 2"
    
    status, art_val, cl_val = decide_evidence_verification(
        RequiredLevel.CLAUSE,
        "Điều 5",
        "Khoản 2",
        chunk
    )
    
    assert status == EvidenceStatus.VERIFIED
    assert art_val == "Điều 5"
    assert cl_val == "Khoản 2"

def test_select_evaluation_cases_limit():
    # Defect 9: select_evaluation_cases applies limit
    cases = [
        GoldenCase(case_id="case_001", answerable=True, question="", question_type="factoid", reference_answer=""),
        GoldenCase(case_id="case_002", answerable=True, question="", question_type="factoid", reference_answer=""),
        GoldenCase(case_id="case_003", answerable=True, question="", question_type="factoid", reference_answer=""),
    ]
    
    res = select_evaluation_cases(cases, gold_policy="none", limit=2)
    assert len(res.selected_cases) == 2
    assert res.selected_case_count == 2
    assert res.selected_case_ids == ["case_001", "case_002"]
