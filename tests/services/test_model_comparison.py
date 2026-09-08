import hashlib
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


@pytest.mark.asyncio
async def test_compare_models_uses_two_exact_configured_aliases_with_the_same_input(
    monkeypatch,
) -> None:
    from app.services import model_comparison

    monkeypatch.setattr(model_comparison.settings, "OPENROUTER_API_KEY", "configured")
    monkeypatch.setattr(model_comparison.settings, "GROQ_API_KEY", "configured")
    invoke = AsyncMock(
        side_effect=[
            model_comparison.ModelGeneration(
                text="Câu trả lời A",
                observed_provider="openrouter",
                observed_model="meta-llama/llama-3.3-70b-instruct",
            ),
            model_comparison.ModelGeneration(
                text="Câu trả lời B",
                observed_provider="groq",
                observed_model="llama-3.3-70b-versatile",
            ),
        ]
    )
    monkeypatch.setattr(model_comparison, "_invoke_exact_model", invoke)

    result = await model_comparison.compare_models(
        "Có phải thông báo?", _evidence(), "openrouter_llama", "groq_llama"
    )

    assert result["generation_call_budget"] == {
        "analysis_attempts": 1,
        "generation_calls": 2,
    }
    assert result["same_input_proof"]["all_models_received_same_input"] is True
    assert result["responses"][0]["requested"]["alias"] == "openrouter_llama"
    assert result["responses"][0]["identity_match"] is True
    assert result["responses"][1]["text"] == "Câu trả lời B"
    assert result["textual_comparison"] == {
        "status": "different",
        "method": "normalized_text_equality",
        "legal_correctness": "not_evaluated",
    }
    prompt = invoke.await_args_list[0].args[1]
    assert prompt == invoke.await_args_list[1].args[1]
    assert (
        hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        == result["same_input_proof"]["input_sha256"]
    )


@pytest.mark.asyncio
async def test_compare_models_rejects_unavailable_alias_before_provider_calls(
    monkeypatch,
) -> None:
    from app.services import model_comparison

    monkeypatch.setattr(model_comparison.settings, "OPENROUTER_API_KEY", None)
    invoke = AsyncMock()
    monkeypatch.setattr(model_comparison, "_invoke_exact_model", invoke)

    with pytest.raises(ValueError, match="model_unavailable"):
        await model_comparison.compare_models(
            "Câu hỏi", _evidence(), "openrouter_llama", "groq_llama"
        )
    invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_compare_models_flags_observed_identity_mismatch_and_preserves_errors(
    monkeypatch,
) -> None:
    from app.services import model_comparison

    monkeypatch.setattr(model_comparison.settings, "OPENROUTER_API_KEY", "configured")
    monkeypatch.setattr(model_comparison.settings, "GROQ_API_KEY", "configured")
    monkeypatch.setattr(
        model_comparison,
        "_invoke_exact_model",
        AsyncMock(
            side_effect=[
                model_comparison.ModelGeneration(
                    text="A", observed_provider="groq", observed_model="other-model"
                ),
                RuntimeError("provider secret detail"),
            ]
        ),
    )

    result = await model_comparison.compare_models(
        "Câu hỏi", _evidence(), "openrouter_llama", "groq_llama"
    )

    assert result["responses"][0]["identity_match"] is False
    assert result["responses"][0]["status"] == "identity_mismatch"
    assert result["responses"][1]["status"] == "provider_error"
    assert result["responses"][1]["error_type"] == "RuntimeError"
    assert "secret" not in str(result)
    assert result["textual_comparison"]["status"] == "not_available"


@pytest.mark.asyncio
async def test_adapter_without_reported_model_does_not_fabricate_identity(monkeypatch):
    from app.services import model_comparison as service

    monkeypatch.setitem(
        service._CALLERS, "openrouter", AsyncMock(return_value="answer")
    )
    generation = await service._invoke_exact_model(service._MODEL_CHOICES[0], "prompt")
    response = service._response_record(service._MODEL_CHOICES[0], generation)
    assert response["observed"]["model"] == "unobserved"
    assert response["identity_status"] == "not_reported"
    assert response["status"] == "success"
