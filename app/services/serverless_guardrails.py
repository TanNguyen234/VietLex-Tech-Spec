"""Explicit serverless self-check engine; same prompts/primary model as NeMo.

Only an unambiguous, complete decision can pass. Technical failures propagate
separately from a semantic rejection. This does not certify legal correctness.
"""
from __future__ import annotations

import asyncio

from jinja2 import Template

from app.config import get_settings
from app.services.direct_llm import LLMUseCase, generate_llm_response_with_metadata
from app.services.guardrail_prompts import (
    INPUT_PROMPT, OUTPUT_PROMPT, output_guardrail_evidence, parse_guardrail_decision,
)
from app.services.runtime_errors import GuardrailUnavailableError


async def _decision(stage: str, prompt: str) -> str:
    current_settings = get_settings()
    allow_fallback = bool(getattr(current_settings, "USE_LEGACY_FREE_PIPELINE", False))
    try:
        result = await asyncio.wait_for(
            generate_llm_response_with_metadata(
                prompt, max_output_tokens=64, thinking_level="MINIMAL",
                use_case=LLMUseCase.GUARDRAIL,
                max_retries=0, allow_fallback=allow_fallback,
            ),
            timeout=current_settings.GUARDRAIL_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        raise GuardrailUnavailableError(stage, "timeout") from None
    except Exception as error:
        raise GuardrailUnavailableError(stage, type(error).__name__) from None
    if (
        not isinstance(getattr(result, "text", None), str)
        or not isinstance(getattr(result, "status", None), str)
        or not hasattr(result, "finish_reason")
    ):
        raise GuardrailUnavailableError(stage, "invalid_generation_result")
    if result.status != "success" or result.finish_reason not in {None, "STOP", "stop"}:
        raise GuardrailUnavailableError(stage, "generation_incomplete")
    return parse_guardrail_decision(result.text, stage)


async def check_input_guardrails(message: str) -> tuple[bool, str]:
    decision = await _decision("input", Template(INPUT_PROMPT).render(user_input=message))
    if decision == "yes":
        return False, "Hệ thống chỉ hỗ trợ câu hỏi phù hợp về pháp luật Việt Nam. Vui lòng điều chỉnh câu hỏi."
    return True, ""


async def check_output_guardrails(response: str, contexts: list[str], query: str = "") -> tuple[bool, str]:
    evidence = output_guardrail_evidence(contexts, query)
    decision = await _decision("output", Template(OUTPUT_PROMPT).render(evidence=evidence, response=response))
    if decision == "no":
        return False, "Kiểm tra tự động phát hiện câu trả lời chưa được tài liệu hỗ trợ đầy đủ. Vui lòng kiểm chứng nguồn."
    return True, ""
