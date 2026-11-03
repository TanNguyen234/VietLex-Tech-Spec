import logfire
import hashlib
import json
import asyncio
import os
from typing import Tuple, List
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from nemoguardrails import LLMRails, RailsConfig
from app.config import get_settings, install_system_trust_store
from app.services.direct_llm import (
    LLMUseCase,
    generate_llm_response,
    generate_llm_response_with_metadata,
)
from app.services.runtime_errors import (
    GUARDRAIL_UNAVAILABLE_MESSAGE as GUARDRAIL_UNAVAILABLE_MESSAGE,
    GuardrailUnavailableError,
    guardrail_error_reason,
)
from app.services.guardrail_prompts import output_guardrail_evidence, parse_guardrail_decision

settings = get_settings()

def _normalize_guardrail_decision(text: str) -> str:
    return parse_guardrail_decision(text, "model")


def _guardrail_failure(stage: str, error: Exception) -> GuardrailUnavailableError:
    # NeMo wraps model exceptions once. Read only our typed cause, never raw text.
    cause = error if isinstance(error, GuardrailUnavailableError) else error.__cause__
    reason = cause.reason if isinstance(cause, GuardrailUnavailableError) else type(error).__name__
    return GuardrailUnavailableError(stage, guardrail_error_reason(reason))


def _guardrail_response_content(result) -> str:
    responses = getattr(result, "response", None)
    if (
        not isinstance(responses, list)
        or not responses
        or not isinstance(responses[0], dict)
        or not isinstance(responses[0].get("content"), str)
        or not responses[0]["content"].strip()
    ):
        raise ValueError("invalid_guardrail_response")
    return responses[0]["content"]

def parse_json_safely(text: str) -> dict:
    """
    Giải phân tích chuỗi JSON trả về từ LLM một cách an toàn, hỗ trợ lọc markdown code block.
    """
    try:
        clean_text = text.strip()
        if "```" in clean_text:
            start = clean_text.find("{")
            end = clean_text.rfind("}")
            if start != -1 and end != -1:
                clean_text = clean_text[start:end+1]
        return json.loads(clean_text)
    except Exception as error:
        logfire.warning(
            "Không thể parse JSON từ LLM Guardrails",
            error_kind=type(error).__name__,
            response_length=len(text),
        )
        return {}

async def call_llm_guard(prompt: str) -> str:
    try:
        return await generate_llm_response(prompt, use_case=LLMUseCase.GUARDRAIL)
    except Exception as error:
        logfire.warning(
            "LLM Guard call failed", error_kind=type(error).__name__
        )
        return ""

_rails_instance = None


class VertexPrimaryGuardrailModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "vietlex_vertex_primary_guardrail"

    @property
    def _identifying_params(self) -> dict:
        return {
            "primary_provider": "google_vertex_ai",
            "primary_model": settings.VERTEX_LLM_MODEL,
        }

    @staticmethod
    def _prompt(messages: List[BaseMessage]) -> str:
        return "\n".join(str(message.content) for message in messages)

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop=None,
        run_manager=None,
        **kwargs,
    ) -> ChatResult:
        result = await generate_llm_response_with_metadata(
            self._prompt(messages),
            max_output_tokens=64,
            thinking_level="MINIMAL",
            use_case=LLMUseCase.GUARDRAIL,
        )
        if (
            not isinstance(getattr(result, "text", None), str)
            or not result.text.strip()
            or getattr(result, "status", None) != "success"
            or not hasattr(result, "finish_reason")
            or result.finish_reason not in {None, "STOP", "stop"}
        ):
            raise GuardrailUnavailableError("model", "generation_incomplete")
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content=_normalize_guardrail_decision(result.text)
                    )
                )
            ],
            llm_output={
                "provider": result.observed_provider,
                "model": result.observed_model,
                "fallback_used": result.fallback_used,
                "primary_error_kind": result.primary_error_kind,
            },
        )

    def _generate(
        self,
        messages: List[BaseMessage],
        stop=None,
        run_manager=None,
        **kwargs,
    ) -> ChatResult:
        return asyncio.run(
            self._agenerate(
                messages,
                stop=stop,
                run_manager=run_manager,
                **kwargs,
            )
        )

def get_rails():
    global _rails_instance
    if _rails_instance is None:
        install_system_trust_store()
        current_dir = os.path.dirname(os.path.abspath(__file__))
        config_dir = os.path.abspath(os.path.join(current_dir, "..", "..", "guardrails_config"))
        
        config = RailsConfig.from_path(config_dir)
        for stage, required_flow in (
            ("input", "self check input"),
            ("output", "self check facts custom"),
        ):
            rail = getattr(getattr(config, "rails", None), stage, None)
            if required_flow not in (getattr(rail, "flows", None) or []):
                raise GuardrailUnavailableError("model", "configuration_invalid")
        
        _rails_instance = LLMRails(
            config,
            llm=VertexPrimaryGuardrailModel(),
        )
    return _rails_instance


async def warm_guardrails() -> None:
    """Initialize NeMo and prime the Vertex input rail before evaluation."""
    try:
        rails = await asyncio.to_thread(get_rails)
        result = await asyncio.wait_for(
            rails.generate_async(
                messages=[
                    {
                        "role": "user",
                        "content": "Câu hỏi pháp luật Việt Nam.",
                    }
                ],
                options={"rails": ["input"]},
            ),
            timeout=max(
                settings.GUARDRAIL_TIMEOUT_SECONDS,
                settings.VERTEX_REQUEST_TIMEOUT_SECONDS,
            ),
        )
        _guardrail_response_content(result)
    except Exception as error:
        logfire.error(
            "Guardrails startup warm-up failed",
            error_kind=type(error).__name__,
        )
        raise

@logfire.instrument("Kiểm tra an toàn Input Guardrails", extract_args=False)
async def check_input_guardrails(message: str) -> Tuple[bool, str]:
    logfire.info(
        "Đang kiểm tra bảo mật đầu vào",
        message_length=len(message),
    )
    # Assess the whole question: legal questions can legitimately mention code,
    # violence or other keywords that also occur in off-topic requests.
    try:
        rails = get_rails()
        res = await asyncio.wait_for(
            rails.generate_async(
                messages=[{"role": "user", "content": message}],
                options={"rails": ["input"]}
            ),
            timeout=settings.GUARDRAIL_TIMEOUT_SECONDS,
        )
        
        response_content = _guardrail_response_content(res)
            
        if response_content == "I'm sorry, I can't respond to that.":
            return False, "Hệ thống chỉ hỗ trợ giải đáp các thắc mắc liên quan đến pháp luật Việt Nam. Vui lòng đặt câu hỏi phù hợp."
            
        return True, ""
    except asyncio.TimeoutError as error:
        logfire.warning(
            "Input Guardrails NeMo timed out; blocking request.",
            timeout_seconds=settings.GUARDRAIL_TIMEOUT_SECONDS,
        )
        raise GuardrailUnavailableError("input", "timeout") from error
    except Exception as e:
        error_kind = type(e).__name__
        logfire.error(
            "Lỗi khi chạy Input Guardrails", error_kind=error_kind
        )
        raise _guardrail_failure("input", e) from None

@logfire.instrument("Kiểm tra an toàn Output Guardrails", extract_args=False)
async def check_output_guardrails(response: str, context: List[str], user_query: str = "") -> Tuple[bool, str]:
    logfire.info("Đang kiểm tra an toàn câu trả lời đầu ra")
    context_str = output_guardrail_evidence(context, user_query)
    try:
        rails = get_rails()
        res = await asyncio.wait_for(
            rails.generate_async(
                messages=[
                    {"role": "context", "content": {
                        "context": context_str,
                        "evidence": context_str,
                        "relevant_chunks": context_str
                    }},
                    {"role": "user", "content": user_query},
                    {"role": "assistant", "content": response}
                ],
                options={"rails": ["output"]}
            ),
            timeout=settings.GUARDRAIL_TIMEOUT_SECONDS,
        )
        
        response_content = _guardrail_response_content(res)
            
        if response_content == "I'm sorry, I can't respond to that.":
            logfire.warning(
                "Output guardrail blocked response",
                response_sha256=hashlib.sha256(
                    response.encode("utf-8")
                ).hexdigest(),
                context_count=len(context),
            )
            return False, "Kiểm tra tự động phát hiện câu trả lời chưa được tài liệu hỗ trợ đầy đủ. Vui lòng kiểm chứng nguồn."
            
        return True, ""
    except asyncio.TimeoutError as error:
        logfire.warning(
            "Output Guardrails NeMo timed out; blocking response.",
            timeout_seconds=settings.GUARDRAIL_TIMEOUT_SECONDS,
        )
        raise GuardrailUnavailableError("output", "timeout") from error
    except Exception as e:
        error_kind = type(e).__name__
        logfire.error(
            "Lỗi khi chạy Output Guardrails", error_kind=error_kind
        )
        raise _guardrail_failure("output", e) from None
