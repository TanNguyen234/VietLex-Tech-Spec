import logfire
import hashlib
import json
import re
import asyncio
import os
from typing import Tuple, List
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from nemoguardrails import LLMRails, RailsConfig
from app.config import get_settings, install_system_trust_store
from app.services.direct_llm import (
    generate_llm_response,
    generate_llm_response_with_metadata,
)

settings = get_settings()

GUARDRAIL_UNAVAILABLE_MESSAGE = (
    "Hệ thống kiểm tra an toàn đang tạm thời không khả dụng. "
    "Vui lòng thử lại sau."
)


class GuardrailUnavailableError(RuntimeError):
    def __init__(self, stage: str, reason: str) -> None:
        self.stage = stage
        super().__init__(f"{stage} guardrail unavailable: {reason}")

def redact_pii(text: str) -> str:
    """
    Tự động nhận diện và ẩn thông tin cá nhân nhạy cảm (PII) trong tiếng Việt.
    Bao gồm: Email, Số điện thoại di động Việt Nam, Số CCCD/CMND.
    """
    if not text:
        return text
        
    # 1. Email Regex
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    text = re.sub(email_pattern, "[EMAIL_ĐÃ_ẨN]", text)
    
    # 2. Số điện thoại di động Việt Nam (các đầu số 03, 05, 07, 08, 09 và định dạng quốc tế +84/84)
    phone_pattern = r'(?:\+?84|0)[35789]\d{8}\b'
    text = re.sub(phone_pattern, "[SĐT_ĐÃ_ẨN]", text)
    
    # 3. Số CCCD/CMND (9 số cũ hoặc 12 số mới)
    cccd_pattern = r'\b(?:\d{12}|\d{9})\b'
    text = re.sub(cccd_pattern, "[CCCD_ĐÃ_ẨN]", text)
    
    return text

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
    except Exception as e:
        logfire.warning("Không thể parse JSON từ LLM Guardrails: {error}. Raw text: {text}", error=str(e), text=text)
        return {}

async def call_llm_guard(prompt: str) -> str:
    try:
        return await generate_llm_response(prompt)
    except Exception as e:
        logfire.warning("LLM Guard call failed: {err}", err=str(e))
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
        )
        return ChatResult(
            generations=[
                ChatGeneration(message=AIMessage(content=result.text))
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
        
        _rails_instance = LLMRails(
            config,
            llm=VertexPrimaryGuardrailModel(),
        )
    return _rails_instance


async def warm_guardrails() -> None:
    """Initialize NeMo and prime the Vertex input rail before evaluation."""
    try:
        rails = await asyncio.to_thread(get_rails)
        await asyncio.wait_for(
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
    except Exception as error:
        logfire.error(
            "Guardrails startup warm-up failed: {error}",
            error=str(error),
        )
        raise

# Fast pattern detection for obvious out-of-scope non-legal queries
OUT_OF_SCOPE_PATTERNS = [
    r"mã nguồn python", r"bún bò huế", r"bài thơ", r"phương trình bậc hai",
    r"thủ đô của nước pháp", r"hack into a database", r"virus máy tính",
    r"bánh mì việt nam", r"bộ phim chiếu rạp", r"mã javascript"
]

@logfire.instrument("Kiểm tra an toàn Input Guardrails")
async def check_input_guardrails(message: str) -> Tuple[bool, str]:
    logfire.info("Đang kiểm tra bảo mật đầu vào cho câu hỏi: {msg}", msg=message)
    msg_lower = message.lower()
    
    # 1. Fast regex pattern match (Instant < 1ms)
    for pattern in OUT_OF_SCOPE_PATTERNS:
        if re.search(pattern, msg_lower):
            return False, "Hệ thống chỉ hỗ trợ giải đáp các thắc mắc liên quan đến pháp luật Việt Nam. Vui lòng đặt câu hỏi phù hợp."
            
    # 2. NeMo Guardrails check with strict timeout (5s max)
    try:
        rails = get_rails()
        res = await asyncio.wait_for(
            rails.generate_async(
                messages=[{"role": "user", "content": message}],
                options={"rails": ["input"]}
            ),
            timeout=settings.GUARDRAIL_TIMEOUT_SECONDS,
        )
        
        response_content = ""
        if hasattr(res, "response") and res.response:
            response_content = res.response[0].get("content", "")
            
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
        logfire.error("Lỗi khi chạy Input Guardrails: {error}", error=str(e))
        raise GuardrailUnavailableError("input", str(e)) from e

@logfire.instrument("Kiểm tra an toàn Output Guardrails")
async def check_output_guardrails(response: str, context: List[str], user_query: str = "") -> Tuple[bool, str]:
    logfire.info("Đang kiểm tra an toàn câu trả lời đầu ra")
    if not context:
        return True, ""
        
    context_str = "\n\n".join([doc[:3000] for doc in context])
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
        
        response_content = ""
        if hasattr(res, "response") and res.response:
            response_content = res.response[0].get("content", "")
            
        if response_content == "I'm sorry, I can't respond to that.":
            logfire.warning(
                "Output guardrail blocked response",
                response_sha256=hashlib.sha256(
                    response.encode("utf-8")
                ).hexdigest(),
                context_count=len(context),
            )
            return False, "Hệ thống phát hiện nội dung câu trả lời không đồng nhất với tài liệu pháp luật chính thống. Vui lòng thử lại sau."
            
        return True, ""
    except asyncio.TimeoutError as error:
        logfire.warning(
            "Output Guardrails NeMo timed out; blocking response.",
            timeout_seconds=settings.GUARDRAIL_TIMEOUT_SECONDS,
        )
        raise GuardrailUnavailableError("output", "timeout") from error
    except Exception as e:
        logfire.error("Lỗi khi chạy Output Guardrails: {error}", error=str(e))
        raise GuardrailUnavailableError("output", str(e)) from e
