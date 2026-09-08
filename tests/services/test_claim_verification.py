import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _generation(text: str, *, status: str = "success") -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        text=text,
        observed_provider="test-provider",
        observed_model="test-model",
    )


def _evidence() -> list[dict]:
    return [
        {
            "evidence_id": "ev-1",
            "citation": "Điều 1",
            "excerpt": "Người sử dụng lao động phải thông báo bằng văn bản.",
        },
        {
            "evidence_id": "ev-2",
            "citation": "Điều 2",
            "excerpt": "Không được yêu cầu người lao động nộp tiền đặt cọc.",
        },
    ]


@pytest.mark.asyncio
async def test_verify_claims_returns_server_claims_and_exact_quote_provenance(
    monkeypatch,
) -> None:
    from app.services import claim_verification

    generate = AsyncMock(
        return_value=_generation(
            json.dumps(
                {
                    "claims": [
                        {
                            "claim_id": "claim-1",
                            "verdict": "supported",
                            "quotes": [
                                {
                                    "evidence_id": "ev-1",
                                    "quote": "phải thông báo bằng văn bản",
                                }
                            ],
                        },
                        {
                            "claim_id": "claim-2",
                            "verdict": "contradicted",
                            "quotes": [
                                {
                                    "evidence_id": "ev-2",
                                    "quote": "Không được yêu cầu",
                                }
                            ],
                        },
                    ]
                },
                ensure_ascii=False,
            )
        )
    )
    monkeypatch.setattr(claim_verification, "_generate", generate)

    result = await claim_verification.verify_claims(
        "Người sử dụng lao động phải thông báo bằng văn bản. "
        "Người sử dụng lao động được yêu cầu đặt cọc.",
        _evidence(),
    )

    assert result["status"] == "ok"
    assert result["provider"] == "test-provider"
    assert result["model"] == "test-model"
    assert result["result"]["method"] == "model_assessment"
    assert result["result"]["legal_certification"] is False
    assert result["result"]["confidence"] == "not_assessed"
    assert result["result"]["claims"] == [
        {
            "claim_id": "claim-1",
            "text": "Người sử dụng lao động phải thông báo bằng văn bản.",
            "verdict": "supported",
            "quotes": [
                {
                    "evidence_id": "ev-1",
                    "quote": "phải thông báo bằng văn bản",
                }
            ],
        },
        {
            "claim_id": "claim-2",
            "text": "Người sử dụng lao động được yêu cầu đặt cọc.",
            "verdict": "contradicted",
            "quotes": [{"evidence_id": "ev-2", "quote": "Không được yêu cầu"}],
        },
    ]
    assert result["result"]["coverage"] == {
        "total_claims": 2,
        "assessed_claims": 2,
        "supported_claims": 1,
        "contradicted_claims": 1,
        "insufficient_claims": 0,
        "skipped_claims": 0,
    }
    assert result["provenance"] == {
        "source": "selected_server_evidence",
        "evidence_ids": ["ev-1", "ev-2"],
        "claim_ids": ["claim-1", "claim-2"],
        "evidence_is_untrusted": True,
    }
    assert "dữ liệu không đáng tin cậy" in generate.await_args.args[1]


@pytest.mark.asyncio
async def test_verify_claims_preserves_insufficient_and_downgrades_unquoted_verdict(
    monkeypatch,
) -> None:
    from app.services import claim_verification

    generate = AsyncMock(
        return_value=_generation(
            '{"claims":['
            '{"claim_id":"claim-1","verdict":"supported","quotes":[]},'
            '{"claim_id":"claim-2","verdict":"insufficient","quotes":[]}'
            "]}"
        )
    )
    monkeypatch.setattr(claim_verification, "_generate", generate)

    result = await claim_verification.verify_claims(
        "Có nghĩa vụ thông báo. Có nghĩa vụ khác.", _evidence()
    )

    assert result["status"] == "ok"
    assert [item["verdict"] for item in result["result"]["claims"]] == [
        "insufficient",
        "insufficient",
    ]
    assert result["result"]["coverage"]["insufficient_claims"] == 2


@pytest.mark.asyncio
async def test_verify_claims_validates_quotes_against_prompted_original_fallback(
    monkeypatch,
) -> None:
    from app.services import claim_verification

    evidence = _evidence()
    evidence[0] = {**evidence[0], "original": evidence[0].pop("excerpt")}
    monkeypatch.setattr(
        claim_verification,
        "_generate",
        AsyncMock(
            return_value=_generation(
                '{"claims":[{"claim_id":"claim-1","verdict":"supported",'
                '"quotes":[{"evidence_id":"ev-1",'
                '"quote":"phải thông báo bằng văn bản"}]}]}'
            )
        ),
    )

    result = await claim_verification.verify_claims("Có nghĩa vụ thông báo.", evidence)

    assert result["status"] == "ok"
    assert result["result"]["claims"][0]["verdict"] == "supported"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        '{"claims":[{"claim_id":"claim-1","verdict":"supported",'
        '"quotes":[{"evidence_id":"ev-1","quote":"invented quote"}]},'
        '{"claim_id":"claim-2","verdict":"insufficient","quotes":[]}]}',
        '{"claims":[{"claim_id":"claim-1","verdict":"supported",'
        '"quotes":[{"evidence_id":"unselected","quote":"anything"}]},'
        '{"claim_id":"claim-2","verdict":"insufficient","quotes":[]}]}',
        '{"claims":[{"claim_id":"claim-1","verdict":"supported",'
        '"quotes":[{"evidence_id":"ev-1","quote":"\\n"}]},'
        '{"claim_id":"claim-2","verdict":"insufficient","quotes":[]}]}',
    ],
)
async def test_verify_claims_rejects_fabricated_quotes_and_unselected_evidence(
    monkeypatch, response: str
) -> None:
    from app.services import claim_verification

    monkeypatch.setattr(
        claim_verification, "_generate", AsyncMock(return_value=_generation(response))
    )

    result = await claim_verification.verify_claims(
        "Có nghĩa vụ thông báo. Có nghĩa vụ khác.", _evidence()
    )

    assert result["status"] == "invalid_structured_response"
    assert result["error_type"] == "ClaimVerificationValidationError"
    assert "invented quote" not in str(result)
    assert "unselected" not in str(result)


@pytest.mark.asyncio
async def test_verify_claims_rejects_missing_or_duplicate_claim_coverage(
    monkeypatch,
) -> None:
    from app.services import claim_verification

    response = (
        '{"claims":['
        '{"claim_id":"claim-1","verdict":"insufficient","quotes":[]},'
        '{"claim_id":"claim-1","verdict":"insufficient","quotes":[]}'
        "]}"
    )
    monkeypatch.setattr(
        claim_verification, "_generate", AsyncMock(return_value=_generation(response))
    )

    result = await claim_verification.verify_claims(
        "Có nghĩa vụ thông báo. Có nghĩa vụ khác.", _evidence()
    )

    assert result["status"] == "invalid_structured_response"
    assert result["result"]["coverage"]["total_claims"] == 2
    assert result["result"]["coverage"]["assessed_claims"] == 0


@pytest.mark.asyncio
async def test_verify_claims_reports_provider_error_without_semantic_fallback(
    monkeypatch,
) -> None:
    from app.services import claim_verification

    monkeypatch.setattr(
        claim_verification,
        "_generate",
        AsyncMock(return_value=_generation("unavailable", status="quota")),
    )

    result = await claim_verification.verify_claims(
        "Có nghĩa vụ thông báo.", _evidence()
    )

    assert result["status"] == "provider_error"
    assert result["provider_status"] == "quota"
    assert result["result"]["claims"] == []
    assert result["result"]["coverage"] == {
        "total_claims": 1,
        "assessed_claims": 0,
        "supported_claims": 0,
        "contradicted_claims": 0,
        "insufficient_claims": 0,
        "skipped_claims": 1,
        "skip_reason": "provider_error",
    }


@pytest.mark.asyncio
async def test_verify_claims_reports_safe_provider_exception_diagnostics(
    monkeypatch,
) -> None:
    from app.services import claim_verification

    monkeypatch.setattr(
        claim_verification, "_generate", AsyncMock(side_effect=RuntimeError("secret"))
    )

    result = await claim_verification.verify_claims(
        "Có nghĩa vụ thông báo.", _evidence()
    )

    assert result["status"] == "provider_error"
    assert result["error_type"] == "RuntimeError"
    assert result["result"]["coverage"]["skip_reason"] == "provider_exception"
    assert "secret" not in str(result)


@pytest.mark.asyncio
async def test_verify_claims_rejects_scope_overflow_before_provider_call(
    monkeypatch,
) -> None:
    from app.services import claim_verification

    generate = AsyncMock()
    monkeypatch.setattr(claim_verification, "_generate", generate)

    with pytest.raises(ValueError, match="claim_scope_too_large"):
        await claim_verification.verify_claims("x" * 2_001, _evidence())

    with pytest.raises(ValueError, match="claim_scope_too_large"):
        await claim_verification.verify_claims("Claim.\n" * 11, _evidence())

    generate.assert_not_awaited()
