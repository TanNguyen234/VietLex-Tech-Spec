import logfire
import httpx
import json
import re
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

async def call_llm_guard(prompt: str) -> str:
    base_url = settings.OMNIGATE_BASE_URL.rstrip('/')
    chat_url = f"{base_url}/v1/chat/completions" if not base_url.endswith('/v1') else f"{base_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.LITELLM_MASTER_KEY}"
    }
    payload = {
        "model": "legal-core-model",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0
    }
    import asyncio
    for attempt in range(5):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(chat_url, headers=headers, json=payload)
                if response.status_code in [429, 502, 503, 504]:
                    sleep_time = (2 ** attempt) + 1
                    await asyncio.sleep(sleep_time)
                    continue
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            if attempt == 4:
                raise e
            await asyncio.sleep((2 ** attempt) + 1)
    raise RuntimeError("Failed to call LLM guard after 5 attempts.")

import os
from nemoguardrails import LLMRails, RailsConfig

_rails_instance = None

def get_rails():
    global _rails_instance
    if _rails_instance is None:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        config_dir = os.path.abspath(os.path.join(current_dir, "..", "..", "guardrails_config"))
        
        # Ensure LITELLM_MASTER_KEY is exported as OPENAI_API_KEY
        if "OPENAI_API_KEY" not in os.environ:
            os.environ["OPENAI_API_KEY"] = settings.LITELLM_MASTER_KEY
            
        config = RailsConfig.from_path(config_dir)
        _rails_instance = LLMRails(config)
    return _rails_instance

@logfire.instrument("Kiểm tra an toàn Input Guardrails")
async def check_input_guardrails(message: str) -> Tuple[bool, str]:
    logfire.info("Đang kiểm tra bảo mật đầu vào cho câu hỏi: {msg}", msg=message)
    try:
        rails = get_rails()
        res = await rails.generate_async(
            messages=[{"role": "user", "content": message}],
            options={"rails": ["input"]}
        )
        
        response_content = ""
        if hasattr(res, "response") and res.response:
            response_content = res.response[0].get("content", "")
            
        if response_content == "I'm sorry, I can't respond to that.":
            return False, "Hệ thống chỉ hỗ trợ giải đáp các thắc mắc liên quan đến pháp luật Việt Nam. Vui lòng đặt câu hỏi phù hợp."
            
        return True, ""
    except Exception as e:
        logfire.error("Lỗi khi chạy Input Guardrails: {error}", error=str(e))
        return True, ""

@logfire.instrument("Kiểm tra an toàn Output Guardrails")
async def check_output_guardrails(response: str, context: List[str], user_query: str = "") -> Tuple[bool, str]:
    logfire.info("Đang kiểm tra an toàn câu trả lời đầu ra")
    if not context:
        return True, ""
        
    context_str = "\n\n".join([doc[:6000] for doc in context])
    try:
        rails = get_rails()
        res = await rails.generate_async(
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
        )
        
        response_content = ""
        if hasattr(res, "response") and res.response:
            response_content = res.response[0].get("content", "")
            
        if response_content == "I'm sorry, I can't respond to that.":
            return False, "Hệ thống phát hiện nội dung câu trả lời không đồng nhất với tài liệu pháp luật chính thống. Vui lòng thử lại sau."
            
        return True, ""
    except Exception as e:
        logfire.error("Lỗi khi chạy Output Guardrails: {error}", error=str(e))
        return True, ""
