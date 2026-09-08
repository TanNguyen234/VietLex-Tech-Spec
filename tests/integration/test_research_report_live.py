"""Two bounded real generations at most; opt-in and never a legal accuracy gate."""

import asyncio
import json

import pytest


pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_research_report_with_synthetic_evidence():
    from app.services.research_report import generate_research_report

    result = await asyncio.wait_for(generate_research_report(
        "Theo tài liệu thử nghiệm, Bên A giao tài liệu khi nào?",
        [{"evidence_id": "live-synthetic-1", "citation": "Tài liệu kiểm thử",
          "excerpt": "Bên A giao tài liệu vào ngày 15/09/2026."}],
    ), timeout=120)
    print(json.dumps({
        "status": result["status"], "error_stage": result.get("error_stage"),
        "error_code": result.get("error_code"), "diagnostics": result.get("diagnostics"),
        "assessment_diagnostics": result["model_assessment"].get("diagnostics"),
        "coverage": result["coverage"],
    }, ensure_ascii=True))
    assert result["status"] == "ok"
    assert result["coverage"]["report_claims"] > 0
    assert result["coverage"]["verified_claims"] == result["coverage"]["report_claims"]
    assert result["legal_certification"] is False
