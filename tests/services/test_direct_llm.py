from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest


from app.services import direct_llm


@pytest.mark.asyncio
async def test_openrouter_request_honors_the_requested_output_budget(
    monkeypatch,
) -> None:
    captured: dict = {}

    class FakeClient:
        async def post(self, url, *, headers, json, timeout):
            captured.update(json)
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "choices": [
                        {"message": {"content": "Câu trả lời"}}
                    ]
                },
            )

    monkeypatch.setattr(
        direct_llm,
        "settings",
        SimpleNamespace(OPENROUTER_API_KEY="test-key"),
    )
    monkeypatch.setattr(direct_llm, "get_direct_client", FakeClient)

    response = await direct_llm.call_openrouter_api(
        "Câu hỏi",
        max_output_tokens=640,
    )

    assert response == "Câu trả lời"
    assert captured["max_tokens"] == 640



@pytest.mark.asyncio
async def test_generate_llm_response_with_metadata_observes_provider_and_model(
    monkeypatch,
) -> None:
    class FakeClient:
        async def post(self, url, *, headers, json, timeout):
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "choices": [
                        {"message": {"content": "Kết quả trực tiếp"}}
                    ]
                },
            )

    monkeypatch.setattr(
        direct_llm,
        "settings",
        SimpleNamespace(
            OPENROUTER_API_KEY="openrouter-test-key",
            GEMINI_API_KEY=None,
            NVIDIA_API_KEY=None,
            GROQ_API_KEY=None,
        ),
    )
    monkeypatch.setattr(direct_llm, "get_direct_client", FakeClient)

    result = await direct_llm.generate_llm_response_with_metadata(
        "Câu hỏi",
        max_output_tokens=512,
    )

    assert isinstance(result, direct_llm.LLMGenerationResult)
    assert result.text == "Kết quả trực tiếp"
    assert result.observed_provider == "openrouter"
    assert result.observed_model is not None
    assert result.observed is True
    assert result.status == "success"


@pytest.mark.asyncio
async def test_generate_llm_response_with_metadata_returns_no_provider_available_when_no_keys(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        direct_llm,
        "settings",
        SimpleNamespace(
            OPENROUTER_API_KEY=None,
            GEMINI_API_KEY=None,
            NVIDIA_API_KEY=None,
            GROQ_API_KEY=None,
        ),
    )

    result = await direct_llm.generate_llm_response_with_metadata(
        "Câu hỏi",
    )

    assert isinstance(result, direct_llm.LLMGenerationResult)
    assert result.observed is False
    assert result.observed_provider in ("unobserved", "none")
    assert result.observed_model in ("unobserved", "none")
    assert result.status == "no_provider_available"
    assert "chưa được cấu hình" in result.text or "chưa thể xử lý" in result.text


@pytest.mark.asyncio
async def test_generate_llm_response_with_metadata_returns_providers_exhausted_when_cooldown_active(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        direct_llm,
        "settings",
        SimpleNamespace(
            OPENROUTER_API_KEY="test-openrouter",
            GEMINI_API_KEY="test-gemini",
            NVIDIA_API_KEY="test-nvidia",
            GROQ_API_KEY="test-groq",
        ),
    )
    # Set all cooldowns to future
    future = direct_llm.time.time() + 3600
    monkeypatch.setattr(
        direct_llm,
        "_cooldowns",
        {"openrouter": future, "gemini": future, "nvidia": future, "groq": future},
    )

    # Mock all 4 provider functions to ensure zero real HTTP/socket calls
    monkeypatch.setattr(direct_llm, "call_openrouter_api", AsyncMock(return_value=None))
    monkeypatch.setattr(direct_llm, "call_gemini_api", AsyncMock(return_value=None))
    monkeypatch.setattr(direct_llm, "call_nvidia_api", AsyncMock(return_value=None))
    monkeypatch.setattr(direct_llm, "call_groq_api", AsyncMock(return_value=None))

    result = await direct_llm.generate_llm_response_with_metadata(
        "Câu hỏi",
    )

    assert isinstance(result, direct_llm.LLMGenerationResult)
    assert result.observed is False
    assert result.observed_provider in ("unobserved", "none")
    assert result.status == "providers_exhausted"
    assert "giới hạn tốc độ" in result.text
