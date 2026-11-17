"""Round-6g: an answer cut by the output-token budget (finish_reason MAX_TOKENS) is retried once with a larger
budget and a concise instruction; if still cut, the delivered text carries a visible truncation notice.
Answers that finish normally are not retried."""

import pytest

from app.services import rag_pipeline
from app.services.direct_llm import LLMGenerationResult

QUESTION = "em đi thực tập không có hợp đồng, công ty trả 3 triệu một tháng thì em được hưởng những quyền lợi nào?"
CONTEXT = ["[45/2019/QH14, Điều 35] Người lao động đơn phương chấm dứt hợp đồng phải báo trước ít nhất 45 ngày."]


def _result(text: str, finish_reason: str | None) -> LLMGenerationResult:
    return LLMGenerationResult(
        text=text,
        observed_provider="test_provider",
        observed_model="test_model",
        finish_reason=finish_reason,
    )


@pytest.mark.asyncio
async def test_truncated_answer_is_retried_with_larger_budget_and_concise_instruction(monkeypatch):
    calls = []
    responses = [_result("Phần đầu bị cắt", "MAX_TOKENS"), _result("Câu trả lời đầy đủ.", "STOP")]

    async def fake_generate(user_prompt, system_prompt, *, max_output_tokens, thinking_level=None, use_case=None):
        calls.append((max_output_tokens, system_prompt))
        return responses.pop(0)

    monkeypatch.setattr(rag_pipeline, "generate_llm_response_with_metadata", fake_generate)

    result = await rag_pipeline.generate_response_with_metadata(QUESTION, QUESTION, CONTEXT)

    assert result.text == "Câu trả lời đầy đủ."
    assert len(calls) == 2
    assert calls[1][0] == calls[0][0] * 2
    assert rag_pipeline.ANSWER_CONCISE_RETRY_INSTRUCTION in calls[1][1]
    assert rag_pipeline.ANSWER_CONCISE_RETRY_INSTRUCTION not in calls[0][1]


@pytest.mark.asyncio
async def test_persistently_truncated_answer_carries_visible_notice(monkeypatch):
    async def fake_generate(user_prompt, system_prompt, *, max_output_tokens, thinking_level=None, use_case=None):
        return _result("Phần đầu bị cắt", "MAX_TOKENS")

    monkeypatch.setattr(rag_pipeline, "generate_llm_response_with_metadata", fake_generate)

    result = await rag_pipeline.generate_response_with_metadata(QUESTION, QUESTION, CONTEXT)

    assert result.status == "success"
    assert result.text.endswith(rag_pipeline.ANSWER_TRUNCATED_NOTICE.strip())
    assert result.text.startswith("Phần đầu bị cắt")


@pytest.mark.asyncio
async def test_normally_finished_answer_is_not_retried(monkeypatch):
    calls = []

    async def fake_generate(user_prompt, system_prompt, *, max_output_tokens, thinking_level=None, use_case=None):
        calls.append(max_output_tokens)
        return _result("Câu trả lời ngắn.", "STOP")

    monkeypatch.setattr(rag_pipeline, "generate_llm_response_with_metadata", fake_generate)

    result = await rag_pipeline.generate_response_with_metadata(QUESTION, QUESTION, CONTEXT)

    assert result.text == "Câu trả lời ngắn."
    assert len(calls) == 1
