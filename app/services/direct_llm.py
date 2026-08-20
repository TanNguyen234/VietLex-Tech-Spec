from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Optional

import httpx
import logfire
from google.genai import types

from app.config import get_settings
from app.evaluation.provider_catalog import (
    GEMINI_PRIMARY_MODEL,
    GEMINI_SECONDARY_MODEL,
    GROQ_PRIMARY_MODEL,
    GROQ_SECONDARY_MODEL,
    NVIDIA_PRIMARY_MODEL,
    OPENROUTER_PRIMARY_MODEL,
)
from app.services.vertex_ai import VertexAIError, get_vertex_provider


settings = get_settings()
_cooldowns = {
    "openrouter": 0.0,
    "gemini": 0.0,
    "nvidia": 0.0,
    "groq": 0.0,
}
_http_client: Optional[httpx.AsyncClient] = None


def get_direct_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=50,
            ),
        )
    return _http_client


def _record_secondary_failure(provider: str, error: BaseException) -> None:
    logfire.warning(
        "{provider} fallback API error: {error_type}",
        provider=provider,
        error_type=type(error).__name__,
    )


async def _call_openai_compatible_api(
    *,
    provider: str,
    url: str,
    api_key: str | None,
    prompt: str,
    system_prompt: str,
    model: str,
    max_output_tokens: int,
    extra_headers: dict[str, str] | None = None,
) -> Optional[str]:
    if not api_key:
        return None
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        **(extra_headers or {}),
    }
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    try:
        response = await get_direct_client().post(
            url,
            headers=headers,
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": max_output_tokens,
            },
            timeout=25.0,
        )
        if response.status_code in {429, 502, 503, 504}:
            _cooldowns[provider] = time.time() + 30.0
            logfire.warning(
                "{provider} fallback unavailable ({code}); cooldown 30s",
                provider=provider,
                code=response.status_code,
            )
            return None
        response.raise_for_status()
        choices = response.json().get("choices", [])
        if choices:
            text = choices[0].get("message", {}).get("content") or ""
            return text.strip() or None
    except Exception as error:
        _record_secondary_failure(provider, error)
    return None


async def call_openrouter_api(
    prompt: str,
    system_prompt: str = "",
    model: str = OPENROUTER_PRIMARY_MODEL,
    *,
    max_output_tokens: int = 1024,
) -> Optional[str]:
    return await _call_openai_compatible_api(
        provider="openrouter",
        url="https://openrouter.ai/api/v1/chat/completions",
        api_key=settings.OPENROUTER_API_KEY,
        prompt=prompt,
        system_prompt=system_prompt,
        model=model,
        max_output_tokens=max_output_tokens,
        extra_headers={
            "HTTP-Referer": "https://vietlex.rag",
            "X-Title": "VietLex Legal RAG",
        },
    )


async def call_gemini_api(
    prompt: str,
    system_prompt: str = "",
    model: str = GEMINI_PRIMARY_MODEL,
    *,
    max_output_tokens: int = 1024,
) -> Optional[str]:
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        return None
    contents = []
    if system_prompt:
        contents.append(
            {
                "role": "user",
                "parts": [{"text": f"System Instruction: {system_prompt}"}],
            }
        )
    contents.append({"role": "user", "parts": [{"text": prompt}]})
    try:
        response = await get_direct_client().post(
            (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent"
            ),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            json={
                "contents": contents,
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": max_output_tokens,
                },
            },
            timeout=25.0,
        )
        if response.status_code in {429, 502, 503, 504}:
            _cooldowns["gemini"] = time.time() + 30.0
            logfire.warning(
                "Gemini API fallback unavailable ({code}); cooldown 30s",
                code=response.status_code,
            )
            return None
        response.raise_for_status()
        candidates = response.json().get("candidates", [])
        if candidates and candidates[0].get("content"):
            parts = candidates[0]["content"].get("parts", [])
            if parts:
                return (parts[0].get("text") or "").strip() or None
    except Exception as error:
        _record_secondary_failure("gemini", error)
    return None


async def call_nvidia_api(
    prompt: str,
    system_prompt: str = "",
    model: str = NVIDIA_PRIMARY_MODEL,
    *,
    max_output_tokens: int = 1024,
) -> Optional[str]:
    return await _call_openai_compatible_api(
        provider="nvidia",
        url="https://integrate.api.nvidia.com/v1/chat/completions",
        api_key=settings.NVIDIA_API_KEY,
        prompt=prompt,
        system_prompt=system_prompt,
        model=model,
        max_output_tokens=max_output_tokens,
    )


async def call_groq_api(
    prompt: str,
    system_prompt: str = "",
    model: str = GROQ_PRIMARY_MODEL,
    *,
    max_output_tokens: int = 1024,
) -> Optional[str]:
    return await _call_openai_compatible_api(
        provider="groq",
        url="https://api.groq.com/openai/v1/chat/completions",
        api_key=settings.GROQ_API_KEY,
        prompt=prompt,
        system_prompt=system_prompt,
        model=model,
        max_output_tokens=max_output_tokens,
    )


@dataclass(frozen=True)
class LLMGenerationResult:
    text: str
    observed_provider: str
    observed_model: str
    observed: bool = False
    status: str = "success"
    project: str | None = None
    location: str | None = None
    provider_latency_ms: float | None = None
    fallback_used: bool = False
    primary_error_kind: str | None = None


def _vertex_failure_result(
    error: VertexAIError,
    *,
    started: float,
) -> LLMGenerationResult:
    messages = {
        "authentication": "Không thể xác thực Google Cloud Vertex AI.",
        "permission": "Tài khoản dịch vụ không đủ quyền gọi Vertex AI.",
        "quota": "Vertex AI đã vượt hạn ngạch hoặc bị giới hạn tốc độ.",
        "invalid_model": "Model Vertex AI được cấu hình không hợp lệ hoặc không khả dụng.",
        "network": "Không thể kết nối tới Google Cloud Vertex AI.",
        "invalid_response": "Vertex AI trả về phản hồi không hợp lệ.",
    }
    return LLMGenerationResult(
        text=messages.get(error.kind, "Vertex AI gặp lỗi kỹ thuật."),
        observed_provider="google_vertex_ai",
        observed_model=getattr(settings, "VERTEX_LLM_MODEL", "gemini-3.5-flash"),
        observed=True,
        status=error.kind,
        project=getattr(settings, "GOOGLE_CLOUD_PROJECT", None),
        location=getattr(settings, "GOOGLE_CLOUD_LOCATION", "global"),
        provider_latency_ms=round((time.perf_counter() - started) * 1000, 3),
        primary_error_kind=error.kind,
    )


async def _run_secondary_fallbacks(
    prompt: str,
    system_prompt: str,
    max_output_tokens: int,
    *,
    primary_error_kind: str,
    started: float,
) -> LLMGenerationResult | None:
    now = time.time()
    attempts = (
        (
            "openrouter",
            OPENROUTER_PRIMARY_MODEL,
            settings.OPENROUTER_API_KEY,
            call_openrouter_api,
            now >= _cooldowns["openrouter"],
        ),
        (
            "gemini",
            GEMINI_PRIMARY_MODEL,
            settings.GEMINI_API_KEY,
            call_gemini_api,
            now >= _cooldowns["gemini"],
        ),
        (
            "nvidia",
            NVIDIA_PRIMARY_MODEL,
            settings.NVIDIA_API_KEY,
            call_nvidia_api,
            now >= _cooldowns["nvidia"],
        ),
        (
            "groq",
            GROQ_PRIMARY_MODEL,
            settings.GROQ_API_KEY,
            call_groq_api,
            now >= _cooldowns["groq"],
        ),
        (
            "openrouter",
            OPENROUTER_PRIMARY_MODEL,
            settings.OPENROUTER_API_KEY,
            call_openrouter_api,
            True,
        ),
        (
            "gemini",
            GEMINI_SECONDARY_MODEL,
            settings.GEMINI_API_KEY,
            call_gemini_api,
            True,
        ),
        (
            "groq",
            GROQ_SECONDARY_MODEL,
            settings.GROQ_API_KEY,
            call_groq_api,
            True,
        ),
    )
    for provider, model, api_key, operation, available in attempts:
        if not api_key or not available:
            continue
        text = await operation(
            prompt,
            system_prompt,
            model=model,
            max_output_tokens=max_output_tokens,
        )
        if text:
            return LLMGenerationResult(
                text=text,
                observed_provider=provider,
                observed_model=model,
                observed=True,
                status="success",
                provider_latency_ms=round(
                    (time.perf_counter() - started) * 1000,
                    3,
                ),
                fallback_used=True,
                primary_error_kind=primary_error_kind,
            )
    return None


async def generate_llm_response_with_metadata(
    prompt: str,
    system_prompt: str = "",
    *,
    max_output_tokens: int = 1024,
    thinking_level: types.ThinkingLevel | str | None = None,
) -> LLMGenerationResult:
    """Use Vertex first, then the legacy direct APIs as secondary models."""
    started = time.perf_counter()
    try:
        vertex_options = {
            "system_instruction": system_prompt,
            "max_output_tokens": max_output_tokens,
        }
        if thinking_level is not None:
            vertex_options["thinking_level"] = thinking_level
        result = await get_vertex_provider().generate(prompt, **vertex_options)
    except VertexAIError as error:
        has_fallback = bool(
            settings.OPENROUTER_API_KEY
            or settings.GEMINI_API_KEY
            or settings.NVIDIA_API_KEY
            or settings.GROQ_API_KEY
        )
        if has_fallback:
            fallback = await _run_secondary_fallbacks(
                prompt,
                system_prompt,
                max_output_tokens,
                primary_error_kind=error.kind,
                started=started,
            )
            if fallback is not None:
                return fallback
            return LLMGenerationResult(
                text=(
                    "Vertex AI và toàn bộ model API phụ đều tạm thời không khả dụng. "
                    "Vui lòng thử lại sau."
                ),
                observed_provider="google_vertex_ai",
                observed_model=getattr(
                    settings,
                    "VERTEX_LLM_MODEL",
                    "gemini-3.5-flash",
                ),
                observed=True,
                status="providers_exhausted",
                project=getattr(settings, "GOOGLE_CLOUD_PROJECT", None),
                location=getattr(settings, "GOOGLE_CLOUD_LOCATION", "global"),
                provider_latency_ms=round(
                    (time.perf_counter() - started) * 1000,
                    3,
                ),
                fallback_used=True,
                primary_error_kind=error.kind,
            )
        return _vertex_failure_result(error, started=started)

    metadata = result.metadata
    return LLMGenerationResult(
        text=result.text,
        observed_provider=metadata.provider,
        observed_model=metadata.model,
        observed=True,
        status=metadata.status,
        project=metadata.project,
        location=metadata.location,
        provider_latency_ms=metadata.latency_ms,
    )


async def generate_llm_response(
    prompt: str,
    system_prompt: str = "",
    *,
    max_output_tokens: int = 1024,
    thinking_level: types.ThinkingLevel | str | None = None,
) -> str:
    result = await generate_llm_response_with_metadata(
        prompt,
        system_prompt,
        max_output_tokens=max_output_tokens,
        thinking_level=thinking_level,
    )
    return result.text
