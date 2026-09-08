from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _evidence() -> list[dict]:
    return [
        {
            "evidence_id": "ev-1",
            "citation": "Điều 1",
            "excerpt": "Người sử dụng lao động phải thông báo bằng văn bản.",
        }
    ]


def _generation(text: str, status: str = "success"):
    return SimpleNamespace(
        text=text,
        status=status,
        observed_provider="test-provider",
        observed_model="test-model",
    )


@pytest.mark.asyncio
async def test_generate_report_verifies_source_linked_claims(monkeypatch) -> None:
    from app.services import research_report

    raw = """{
      "status":"ok",
      "issue":"Nghĩa vụ thông báo",
      "analysis":[{"text":"Người sử dụng lao động phải thông báo bằng văn bản.","evidence_ids":["ev-1"]}],
      "exceptions":[],
      "checklist":[{"text":"Kiểm tra việc thông báo.","evidence_ids":["ev-1"]}],
      "sources":["ev-1"],
      "unknown":["Chưa có thông tin về thời hạn thông báo."]
    }"""
    generate = AsyncMock(return_value=_generation(raw))
    verify = AsyncMock(
        return_value={
            "status": "ok",
            "result": {"coverage": {"total_claims": 2, "assessed_claims": 2}},
        }
    )
    monkeypatch.setattr(research_report, "_generate", generate)
    monkeypatch.setattr(research_report, "verify_claims", verify)

    result = await research_report.generate_research_report("Cần làm gì?", _evidence())

    assert result["status"] == "ok"
    assert result["report"]["sources"] == ["ev-1"]
    assert result["coverage"] == {"report_claims": 2, "verified_claims": 2}
    assert result["unknown"] == ["Chưa có thông tin về thời hạn thông báo."]
    verify.assert_awaited_once_with(
        "Người sử dụng lao động phải thông báo bằng văn bản.\nKiểm tra việc thông báo.",
        _evidence(),
    )
    assert generate.await_count == 1


@pytest.mark.asyncio
async def test_generate_report_rejects_unknown_evidence_id(monkeypatch) -> None:
    from app.services import research_report

    raw = """{
      "status":"ok", "issue":"I",
      "analysis":[{"text":"Claim.","evidence_ids":["forged"]}],
      "exceptions":[], "checklist":[], "sources":["forged"], "unknown":[]
    }"""
    monkeypatch.setattr(
        research_report, "_generate", AsyncMock(return_value=_generation(raw))
    )
    verify = AsyncMock()
    monkeypatch.setattr(research_report, "verify_claims", verify)

    result = await research_report.generate_research_report("Q", _evidence())

    assert result["status"] == "invalid_structured_response"
    assert result["error_type"] == "ResearchReportValidationError"
    assert result["error_code"] == "invalid_evidence_reference"
    verify.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_report_marks_verification_failure_without_certification(
    monkeypatch,
) -> None:
    from app.services import research_report

    raw = """{
      "status":"ok", "issue":"I",
      "analysis":[{"text":"Claim.","evidence_ids":["ev-1"]}],
      "exceptions":[], "checklist":[], "sources":["ev-1"], "unknown":[]
    }"""
    monkeypatch.setattr(
        research_report, "_generate", AsyncMock(return_value=_generation(raw))
    )
    monkeypatch.setattr(
        research_report,
        "verify_claims",
        AsyncMock(
            return_value={
                "status": "invalid_structured_response",
                "result": {"coverage": {"total_claims": 1, "assessed_claims": 0}},
            }
        ),
    )

    result = await research_report.generate_research_report("Q", _evidence())

    assert result["status"] == "invalid_structured_response"
    assert result["model_assessment"]["status"] == "invalid_structured_response"
    assert result["legal_certification"] is False


@pytest.mark.asyncio
async def test_generate_report_rejects_multi_sentence_claim_before_verification(
    monkeypatch,
) -> None:
    from app.services import research_report

    raw = """{
      "status":"ok", "issue":"I",
      "analysis":[{"text":"Claim one. Claim two.","evidence_ids":["ev-1"]}],
      "exceptions":[], "checklist":[], "sources":["ev-1"], "unknown":[]
    }"""
    monkeypatch.setattr(
        research_report, "_generate", AsyncMock(return_value=_generation(raw))
    )
    verify = AsyncMock()
    monkeypatch.setattr(research_report, "verify_claims", verify)

    result = await research_report.generate_research_report("Q", _evidence())

    assert result["status"] == "invalid_structured_response"
    verify.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_report_marks_unlinked_verifier_quote_as_citation_mismatch(
    monkeypatch,
) -> None:
    from app.services import research_report

    evidence = _evidence() + [{"evidence_id": "ev-2", "excerpt": "Other evidence."}]
    raw = """{
      "status":"ok", "issue":"I",
      "analysis":[{"text":"Claim.","evidence_ids":["ev-1"]}],
      "exceptions":[], "checklist":[], "sources":["ev-1"], "unknown":[]
    }"""
    monkeypatch.setattr(
        research_report, "_generate", AsyncMock(return_value=_generation(raw))
    )
    monkeypatch.setattr(
        research_report,
        "verify_claims",
        AsyncMock(
            return_value={
                "status": "ok",
                "result": {
                    "claims": [
                        {
                            "claim_id": "claim-1",
                            "text": "Claim.",
                            "verdict": "supported",
                            "quotes": [
                                {"evidence_id": "ev-2", "quote": "Other evidence."}
                            ],
                        }
                    ],
                    "coverage": {
                        "total_claims": 1,
                        "assessed_claims": 1,
                        "supported_claims": 1,
                        "contradicted_claims": 0,
                        "insufficient_claims": 0,
                        "skipped_claims": 0,
                    },
                },
            }
        ),
    )

    result = await research_report.generate_research_report("Q", evidence)

    assert result["status"] == "citation_mismatch"
    assert (
        result["model_assessment"]["result"]["claims"][0]["verdict"] == "insufficient"
    )
    assert result["model_assessment"]["citation_mismatch_claim_ids"] == ["claim-1"]
