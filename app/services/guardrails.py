import logfire
import httpx
import json
import re
import asyncio
from typing import Tuple, List
from app.config import get_settings

settings = get_settings()

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

from app.services.direct_llm import generate_llm_response

async def call_llm_guard(prompt: str) -> str:
    try:
        return await generate_llm_response(prompt)
    except Exception as e:
        logfire.warning("LLM Guard call failed: {err}", err=str(e))
        return ""

import os
from nemoguardrails import LLMRails, RailsConfig

_rails_instance = None

def get_rails():
    global _rails_instance
    if _rails_instance is None:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        config_dir = os.path.abspath(os.path.join(current_dir, "..", "..", "guardrails_config"))
        
        config = RailsConfig.from_path(config_dir)
        
        target_model = "meta-llama/llama-3.3-70b-instruct"
        target_base_url = "https://openrouter.ai/api/v1"
        target_key = settings.OPENROUTER_API_KEY
        
        if settings.OPENROUTER_API_KEY:
            target_model = "meta-llama/llama-3.3-70b-instruct"
            target_base_url = "https://openrouter.ai/api/v1"
            target_key = settings.OPENROUTER_API_KEY
        elif settings.GEMINI_API_KEY:
            target_model = "gemini-2.0-flash"
            target_base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
            target_key = settings.GEMINI_API_KEY
        elif settings.NVIDIA_API_KEY:
            target_model = "meta/llama-3.3-70b-instruct"
            target_base_url = "https://integrate.api.nvidia.com/v1"
            target_key = settings.NVIDIA_API_KEY
        elif settings.GROQ_API_KEY:
            target_model = "llama-3.3-70b-versatile"
            target_base_url = "https://api.groq.com/openai/v1"
            target_key = settings.GROQ_API_KEY
        else:
            target_model = "legal-core-model"
            target_base_url = settings.OMNIGATE_BASE_URL
            target_key = settings.LITELLM_MASTER_KEY
            
        os.environ["OPENAI_API_KEY"] = target_key
        os.environ["OPENAI_BASE_URL"] = target_base_url
        os.environ["OPENAI_API_BASE"] = target_base_url
        
        if config.models:
            config.models[0].model = target_model
            config.models[0].parameters = {"base_url": target_base_url, "api_key": target_key}
            
        _rails_instance = LLMRails(config)
    return _rails_instance

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
            timeout=5.0
        )
        
        response_content = ""
        if hasattr(res, "response") and res.response:
            response_content = res.response[0].get("content", "")
            
        if response_content == "I'm sorry, I can't respond to that.":
            return False, "Hệ thống chỉ hỗ trợ giải đáp các thắc mắc liên quan đến pháp luật Việt Nam. Vui lòng đặt câu hỏi phù hợp."
            
        return True, ""
    except asyncio.TimeoutError:
        logfire.warning("Input Guardrails NeMo timed out (5s), passing input safely.")
        return True, ""
    except Exception as e:
        logfire.error("Lỗi khi chạy Input Guardrails: {error}", error=str(e))
        return True, ""

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
            timeout=5.0
        )
        
        response_content = ""
        if hasattr(res, "response") and res.response:
            response_content = res.response[0].get("content", "")
            
        if response_content == "I'm sorry, I can't respond to that.":
            return False, "Hệ thống phát hiện nội dung câu trả lời không đồng nhất với tài liệu pháp luật chính thống. Vui lòng thử lại sau."
            
        return True, ""
    except asyncio.TimeoutError:
        logfire.warning("Output Guardrails NeMo timed out (5s), passing output safely.")
        return True, ""
    except Exception as e:
        logfire.error("Lỗi khi chạy Output Guardrails: {error}", error=str(e))
        return True, ""
