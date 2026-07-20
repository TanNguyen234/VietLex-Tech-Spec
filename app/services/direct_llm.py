import time
import httpx
import logfire
import asyncio
from typing import Optional, List, Dict
from app.config import get_settings

settings = get_settings()

# Global cooldown timestamps for provider rate limits (Unix timestamp)
_cooldowns = {
    "openrouter": 0.0,
    "gemini": 0.0,
    "nvidia": 0.0,
    "groq": 0.0
}

_http_client: Optional[httpx.AsyncClient] = None

def get_direct_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=30.0, limits=httpx.Limits(max_keepalive_connections=20, max_connections=50))
    return _http_client

# 1. OpenRouter API
async def call_openrouter_api(prompt: str, system_prompt: str = "", model: str = "meta-llama/llama-3.3-70b-instruct") -> Optional[str]:
    api_key = settings.OPENROUTER_API_KEY
    if not api_key:
        return None
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://vietlex.rag",
        "X-Title": "VietLex Legal RAG"
    }
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 1024
    }
    client = get_direct_client()
    try:
        res = await client.post(url, headers=headers, json=payload, timeout=25.0)
        if res.status_code in [429, 502, 503, 504]:
            _cooldowns["openrouter"] = time.time() + 30.0
            logfire.warning("OpenRouter Rate Limited ({code}), setting 30s cooldown", code=res.status_code)
            return None
        res.raise_for_status()
        data = res.json()
        choices = data.get("choices", [])
        if choices:
            return choices[0]["message"]["content"].strip()
    except Exception as e:
        logfire.warning("OpenRouter API error: {err}", err=str(e))
    return None

# 2. Gemini Direct API
async def call_gemini_api(prompt: str, system_prompt: str = "", model: str = "gemini-2.0-flash") -> Optional[str]:
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    
    contents = []
    if system_prompt:
        contents.append({"role": "user", "parts": [{"text": f"System Instruction: {system_prompt}"}]})
    contents.append({"role": "user", "parts": [{"text": prompt}]})
    
    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 1024
        }
    }
    client = get_direct_client()
    try:
        res = await client.post(url, headers=headers, json=payload, timeout=25.0)
        if res.status_code in [429, 502, 503, 504]:
            _cooldowns["gemini"] = time.time() + 30.0
            logfire.warning("Gemini API Rate Limited ({code}), setting 30s cooldown", code=res.status_code)
            return None
        res.raise_for_status()
        data = res.json()
        candidates = data.get("candidates", [])
        if candidates and candidates[0].get("content"):
            parts = candidates[0]["content"].get("parts", [])
            if parts:
                return parts[0].get("text", "").strip()
    except Exception as e:
        logfire.warning("Gemini API error: {err}", err=str(e))
    return None

# 3. Nvidia NIM API
async def call_nvidia_api(prompt: str, system_prompt: str = "", model: str = "meta/llama-3.3-70b-instruct") -> Optional[str]:
    api_key = settings.NVIDIA_API_KEY
    if not api_key:
        return None
    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 1024
    }
    client = get_direct_client()
    try:
        res = await client.post(url, headers=headers, json=payload, timeout=25.0)
        if res.status_code in [429, 502, 503, 504]:
            _cooldowns["nvidia"] = time.time() + 30.0
            logfire.warning("Nvidia NIM Rate Limited ({code}), setting 30s cooldown", code=res.status_code)
            return None
        res.raise_for_status()
        data = res.json()
        choices = data.get("choices", [])
        if choices:
            return choices[0]["message"]["content"].strip()
    except Exception as e:
        logfire.warning("Nvidia NIM API error: {err}", err=str(e))
    return None

# 4. Groq Direct API
async def call_groq_api(prompt: str, system_prompt: str = "", model: str = "llama-3.3-70b-versatile") -> Optional[str]:
    api_key = settings.GROQ_API_KEY
    if not api_key:
        return None
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 1024
    }
    client = get_direct_client()
    try:
        res = await client.post(url, headers=headers, json=payload, timeout=25.0)
        if res.status_code in [429, 502, 503, 504]:
            _cooldowns["groq"] = time.time() + 30.0
            logfire.warning("Groq API Rate Limited ({code}), setting 30s cooldown", code=res.status_code)
            return None
        res.raise_for_status()
        data = res.json()
        choices = data.get("choices", [])
        if choices:
            return choices[0]["message"]["content"].strip()
    except Exception as e:
        logfire.warning("Groq API error: {err}", err=str(e))
    return None

async def generate_llm_response(prompt: str, system_prompt: str = "") -> str:
    """
    4-Provider Direct Fallback Engine (OpenRouter -> Gemini -> Nvidia -> Groq).
    Auto-switches provider upon 429 rate limit or HTTP failure.
    """
    now = time.time()
    
    # 1. OpenRouter
    if settings.OPENROUTER_API_KEY and (now >= _cooldowns["openrouter"]):
        res = await call_openrouter_api(prompt, system_prompt)
        if res:
            return res

    # 2. Gemini Direct
    if settings.GEMINI_API_KEY and (now >= _cooldowns["gemini"]):
        res = await call_gemini_api(prompt, system_prompt)
        if res:
            return res

    # 3. Nvidia NIM
    if settings.NVIDIA_API_KEY and (now >= _cooldowns["nvidia"]):
        res = await call_nvidia_api(prompt, system_prompt)
        if res:
            return res

    # 4. Groq Direct
    if settings.GROQ_API_KEY and (now >= _cooldowns["groq"]):
        res = await call_groq_api(prompt, system_prompt)
        if res:
            return res

    # Secondary fallback passes
    if settings.OPENROUTER_API_KEY:
        res = await call_openrouter_api(prompt, system_prompt, model="meta-llama/llama-3.3-70b-instruct")
        if res:
            return res

    if settings.GEMINI_API_KEY:
        res = await call_gemini_api(prompt, system_prompt, model="gemini-1.5-flash")
        if res:
            return res

    if settings.GROQ_API_KEY:
        res = await call_groq_api(prompt, system_prompt, model="llama3-8b-8192")
        if res:
            return res

    return "Hệ thống chưa thể xử lý do toàn bộ API Keys đang bị giới hạn tốc độ. Vui lòng thử lại sau 30 giây."
