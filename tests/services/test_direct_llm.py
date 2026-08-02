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
