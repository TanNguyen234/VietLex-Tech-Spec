from types import SimpleNamespace

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


@pytest.mark.asyncio
async def test_generate_llm_response_with_metadata_returns_all_rate_limited_when_no_keys(
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
    assert result.observed_provider == "all_rate_limited"
    assert result.observed_model == "none"
    assert "giới hạn tốc độ" in result.text
