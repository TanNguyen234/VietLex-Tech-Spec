from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
import inspect
import json
import re
import time
from typing import Any, AsyncIterator, Optional

import httpx
import logfire
from google.genai import types

from app.account_database import effective_role
from app.config import get_settings
from app.evaluation.provider_catalog import (
    GEMINI_PRIMARY_MODEL,
    GEMINI_SECONDARY_MODEL,
    GROQ_PRIMARY_MODEL,
    GROQ_SECONDARY_MODEL,
    NVIDIA_PRIMARY_MODEL,
    OMNIGATE_PRIMARY_MODEL,
    OPENROUTER_PRIMARY_MODEL,
    RUNTIME_PROVIDER_LABELS,
    RUNTIME_PROVIDER_MODELS,
)
from app.services.vertex_ai import VertexAIError, get_vertex_provider
from app.services.provider_runtime import record_generation_result
from app.services.provider_http_budget import (
    ProviderHttpAsyncTransport,
    ProviderHttpAttemptBudgetExceeded,
    _wrap_client_transports,
    provider_identity_scope,
)


settings = get_settings()

_JSON_FENCE_RE = re.compile(
    r"^\s*```(?:json|JSON)?\s*\r?\n?(.*?)\r?\n?\s*```\s*$",
    re.DOTALL,
)
_CLOSED_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_GOOGLE_MODEL_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_OPENAI_MODEL_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")


def _strip_reasoning_blocks(text: str) -> str:
    if not isinstance(text, str) or "<think>" not in text.lower():
        return text
    return _CLOSED_THINK_BLOCK_RE.sub("", text).strip()


def _safe_token_int(value: Any) -> int | None:
    return value if type(value) is int and 0 <= value <= 10**12 else None


def strip_markdown_json_fence(text: str) -> str:
    """Strip outer Markdown ```json ... ``` fences before JSON validation."""
    if not isinstance(text, str):
        return ""
    stripped = _strip_reasoning_blocks(text).strip()
    match = _JSON_FENCE_RE.match(stripped)
    if match:
        return match.group(1).strip()
    if "```" in stripped:
        block = re.search(
            r"```(?:json|JSON)?\s*\r?\n?(.*?)\r?\n?\s*```",
            stripped,
            re.DOTALL,
        )
        if block:
            candidate = block.group(1).strip()
            if candidate.startswith(("{", "[")):
                return candidate
    return stripped


_strip_json_fences = strip_markdown_json_fence


class _ProviderText(str):
    """Keep the public text API while retaining usage and model identity."""

    def __new__(
        cls,
        text: str,
        usage: dict,
        finish_reason: str | None = "STOP",
        *,
        observed_model: str | None = None,
    ):
        result = super().__new__(cls, text)
        result.usage = {
            key: value
            for key, value in usage.items()
            if type(value) is int and 0 <= value <= 10**12
        }
        if isinstance(finish_reason, str) and finish_reason:
            result.usage["finish_reason"] = finish_reason
        result.observed_model = observed_model
        return result


_cooldowns: dict[str, float] = {
    "openrouter": 0.0,
    "gemini": 0.0,
    "nvidia": 0.0,
    "groq": 0.0,
    "omnigate": 0.0,
}
_http_client: Optional[httpx.AsyncClient] = None


def _cooldown_key(provider: str, model: str) -> str:
    return f"{provider}:{model}"


def _is_in_cooldown(provider: str, model: str) -> bool:
    now = time.time()
    return (
        now < _cooldowns.get(_cooldown_key(provider, model), 0.0)
        or now < _cooldowns.get(provider, 0.0)
    )


class LLMUseCase(str, Enum):
    ANSWER = "answer"
    GUARDRAIL = "guardrail"
    EVALUATION = "evaluation"
    STRUCTURED_ANALYSIS = "structured_analysis"


@dataclass(frozen=True)
class LLMRoutingPolicy:
    use_case: LLMUseCase
    providers: tuple[str, ...]


@dataclass(frozen=True)
class LLMRouteSelection:
    provider: str = "auto"
    model: str | None = None

    def normalized_provider(self) -> str:
        raw = (self.provider or "auto").strip().lower()
        return raw or "auto"

    def cache_key(self) -> str:
        prov = self.normalized_provider()
        if prov == "auto":
            return "auto:"
        return f"{prov}:{(self.model or '').strip()}"


_active_llm_route: ContextVar[LLMRouteSelection | None] = ContextVar(
    "active_llm_route",
    default=None,
)


@contextmanager
def llm_route_scope(route: LLMRouteSelection | None):
    token = _active_llm_route.set(route)
    try:
        yield
    finally:
        _active_llm_route.reset(token)


def can_select_custom_llm_route(
    user: dict | None = None,
    *,
    settings: Any = None,
) -> bool:
    active_settings = settings or globals()["settings"]
    app_env = getattr(active_settings, "APP_ENV", "production")
    if app_env in {"development", "test"}:
        return True
    return bool(
        user
        and user.get("status", "active") == "active"
        and user.get("email_verified")
        and effective_role(user) == "admin"
    )


def _sanitize_model_id(provider: str, model: str | None) -> str | None:
    raw = (model or "").strip()
    if not raw or ".." in raw:
        return None
    if provider in {"gemini", "google_vertex_ai"}:
        raw = raw.removeprefix("models/")
        return raw if _GOOGLE_MODEL_ID_RE.fullmatch(raw) else None
    return raw if _OPENAI_MODEL_ID_RE.fullmatch(raw) else None


def resolve_llm_route(
    provider: str | None = None,
    model: str | None = None,
    *,
    user: dict | None = None,
    settings: Any = None,
) -> LLMRouteSelection:
    active_settings = settings or globals()["settings"]
    if not can_select_custom_llm_route(user, settings=active_settings):
        return LLMRouteSelection("auto", None)
    chosen_provider = (provider or "auto").strip().lower() or "auto"
    if chosen_provider == "auto":
        return LLMRouteSelection("auto", None)
    valid_providers = {
        "google_vertex_ai",
        "gemini",
        "groq",
        "openrouter",
        "nvidia",
        "omnigate",
    }
    if chosen_provider not in valid_providers:
        return LLMRouteSelection("auto", None)
    clean_model = _sanitize_model_id(chosen_provider, model)
    return LLMRouteSelection(chosen_provider, clean_model)


def list_available_llm_targets(active_settings: Any = None) -> list[dict[str, str]]:
    s = active_settings or settings
    targets: list[dict[str, str]] = []
    if not bool(getattr(s, "USE_LEGACY_FREE_PIPELINE", False)):
        vertex_model = str(getattr(s, "VERTEX_LLM_MODEL", "gemini-3.5-flash"))
        targets.append(
            {
                "provider": "google_vertex_ai",
                "model": vertex_model,
                "label": f"{RUNTIME_PROVIDER_LABELS['google_vertex_ai']} · {vertex_model}",
            }
        )
    key_map = (
        ("gemini", getattr(s, "GEMINI_API_KEY", None)),
        ("groq", getattr(s, "GROQ_API_KEY", None)),
        ("openrouter", getattr(s, "OPENROUTER_API_KEY", None)),
        ("nvidia", getattr(s, "NVIDIA_API_KEY", None)),
        ("omnigate", getattr(s, "LITELLM_MASTER_KEY", None)),
    )
    for provider_id, api_key in key_map:
        if not api_key:
            continue
        label_prefix = RUNTIME_PROVIDER_LABELS[provider_id]
        for model_id in RUNTIME_PROVIDER_MODELS[provider_id]:
            targets.append(
                {
                    "provider": provider_id,
                    "model": model_id,
                    "label": f"{label_prefix} · {model_id}",
                }
            )
    return targets


def routing_policy_for(use_case: LLMUseCase) -> LLMRoutingPolicy:
    if use_case is LLMUseCase.EVALUATION:
        providers = (
            "google_vertex_ai",
            "gemini",
            "nvidia",
            "groq",
            "openrouter",
            "omnigate",
        )
    else:
        providers = ("google_vertex_ai", "openrouter", "gemini", "nvidia", "groq")
    return LLMRoutingPolicy(use_case=use_case, providers=providers)


def provider_cooldown_snapshot() -> dict[str, float]:
    return dict(_cooldowns)


def get_direct_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = create_direct_httpx_client()
    return _http_client


def create_direct_httpx_client() -> httpx.AsyncClient:
    client = httpx.AsyncClient(
        timeout=30.0,
        limits=httpx.Limits(
            max_keepalive_connections=20,
            max_connections=50,
        ),
        trust_env=True,
    )
    _wrap_client_transports(
        client,
        ProviderHttpAsyncTransport,
        boundary="direct_llm_httpx_async",
        provider=None,
    )
    return client


async def close_direct_client() -> None:
    global _http_client
    client = _http_client
    _http_client = None
    if client is not None and not client.is_closed:
        await client.aclose()


def _record_secondary_failure(provider: str, error: BaseException) -> None:
    logfire.warning(
        "{provider} fallback API error: {error_type}",
        provider=provider,
        error_type=type(error).__name__,
    )


def _omnigate_completions_url(base_url: str | None) -> str:
    cleaned = (base_url or "https://llmgateway.onrender.com").rstrip("/")
    if cleaned.endswith("/chat/completions"):
        return cleaned
    if cleaned.endswith("/v1"):
        return f"{cleaned}/chat/completions"
    return f"{cleaned}/v1/chat/completions"


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
    response_mime_type: str | None = None,
    thinking_level: types.ThinkingLevel | str | None = None,
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
    base_payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_output_tokens,
    }
    payload = dict(base_payload)
    if response_mime_type == "application/json":
        payload["response_format"] = {"type": "json_object"}
    try:
        with provider_identity_scope(provider):
            response = await get_direct_client().post(
                url,
                headers=headers,
                json=payload,
                timeout=25.0,
            )
            if response.status_code == 400 and "response_format" in payload:
                response = await get_direct_client().post(
                    url,
                    headers=headers,
                    json=base_payload,
                    timeout=25.0,
                )
        if response.status_code in {429, 502, 503, 504}:
            _cooldowns[_cooldown_key(provider, model)] = time.time() + 30.0
            logfire.warning(
                "{provider} fallback unavailable ({code}); cooldown 30s",
                provider=provider,
                model=model,
                code=response.status_code,
            )
            return None
        response.raise_for_status()
        body = response.json()
        choices = body.get("choices", [])
        if choices:
            text = choices[0].get("message", {}).get("content") or ""
            finish_reason = choices[0].get("finish_reason") or "STOP"
            usage = body.get("usage") or {}
            details = usage.get("completion_tokens_details") or {}
            raw_model = body.get("model")
            observed_model = (
                raw_model.strip()
                if isinstance(raw_model, str) and raw_model.strip()
                else model
            )
            cleaned = _strip_reasoning_blocks(text).strip()
            return (
                _ProviderText(
                    cleaned,
                    {
                        "prompt_token_count": usage.get("prompt_tokens"),
                        "output_token_count": usage.get("completion_tokens"),
                        "thought_token_count": details.get("reasoning_tokens"),
                        "total_token_count": usage.get("total_tokens"),
                    },
                    finish_reason=finish_reason,
                    observed_model=observed_model,
                )
                if cleaned
                else None
            )
    except ProviderHttpAttemptBudgetExceeded:
        raise
    except Exception as error:
        _record_secondary_failure(provider, error)
    return None


async def call_openrouter_api(
    prompt: str,
    system_prompt: str = "",
    model: str = OPENROUTER_PRIMARY_MODEL,
    *,
    max_output_tokens: int = 1024,
    response_mime_type: str | None = None,
    thinking_level: types.ThinkingLevel | str | None = None,
) -> Optional[str]:
    return await _call_openai_compatible_api(
        provider="openrouter",
        url="https://openrouter.ai/api/v1/chat/completions",
        api_key=getattr(settings, "OPENROUTER_API_KEY", None),
        prompt=prompt,
        system_prompt=system_prompt,
        model=model,
        max_output_tokens=max_output_tokens,
        extra_headers={
            "HTTP-Referer": "https://vietlex.rag",
            "X-Title": "VietLex Legal RAG",
        },
        response_mime_type=response_mime_type,
        thinking_level=thinking_level,
    )


async def call_gemini_api(
    prompt: str,
    system_prompt: str = "",
    model: str = GEMINI_PRIMARY_MODEL,
    *,
    max_output_tokens: int = 1024,
    response_mime_type: str | None = None,
    thinking_level: types.ThinkingLevel | str | None = None,
) -> Optional[str]:
    api_key = getattr(settings, "GEMINI_API_KEY", None)
    if not api_key:
        return None
    contents = [{"role": "user", "parts": [{"text": prompt}]}]
    generation_config: dict[str, Any] = {
        "temperature": 0.2,
        "maxOutputTokens": max_output_tokens,
    }
    if response_mime_type == "application/json":
        generation_config["responseMimeType"] = "application/json"
    if thinking_level is not None:
        level_str = str(getattr(thinking_level, "value", thinking_level)).upper()
        if level_str == "MINIMAL" and "2.5-flash" in model:
            generation_config["thinkingConfig"] = {"thinkingBudget": 0}
    payload: dict[str, object] = {
        "contents": contents,
        "generationConfig": generation_config,
    }
    if system_prompt:
        payload["system_instruction"] = {
            "parts": [{"text": system_prompt}],
        }
    try:
        with provider_identity_scope("gemini"):
            response = await get_direct_client().post(
                (
                    "https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{model}:generateContent"
                ),
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key,
                },
                json=payload,
                timeout=25.0,
            )
        if response.status_code in {429, 502, 503, 504}:
            _cooldowns[_cooldown_key("gemini", model)] = time.time() + 30.0
            logfire.warning(
                "Gemini API fallback unavailable ({code}); cooldown 30s",
                model=model,
                code=response.status_code,
            )
            return None
        response.raise_for_status()
        body = response.json()
        candidates = body.get("candidates", [])
        if candidates and candidates[0].get("content"):
            parts = candidates[0]["content"].get("parts", [])
            if parts:
                text = "".join(
                    str(part.get("text") or "")
                    for part in parts
                    if not part.get("thought")
                ).strip()
                finish_reason = candidates[0].get("finishReason") or "STOP"
                usage = body.get("usageMetadata") or {}
                raw_model = body.get("modelVersion") or body.get("model")
                observed_model = (
                    raw_model.strip().removeprefix("models/")
                    if isinstance(raw_model, str) and raw_model.strip()
                    else model
                )
                return (
                    _ProviderText(
                        text,
                        {
                            "prompt_token_count": usage.get("promptTokenCount"),
                            "output_token_count": usage.get("candidatesTokenCount"),
                            "thought_token_count": usage.get("thoughtsTokenCount"),
                            "total_token_count": usage.get("totalTokenCount"),
                        },
                        finish_reason=finish_reason,
                        observed_model=observed_model,
                    )
                    if text
                    else None
                )
    except ProviderHttpAttemptBudgetExceeded:
        raise
    except Exception as error:
        _record_secondary_failure("gemini", error)
    return None


async def call_nvidia_api(
    prompt: str,
    system_prompt: str = "",
    model: str = NVIDIA_PRIMARY_MODEL,
    *,
    max_output_tokens: int = 1024,
    response_mime_type: str | None = None,
    thinking_level: types.ThinkingLevel | str | None = None,
) -> Optional[str]:
    return await _call_openai_compatible_api(
        provider="nvidia",
        url="https://integrate.api.nvidia.com/v1/chat/completions",
        api_key=getattr(settings, "NVIDIA_API_KEY", None),
        prompt=prompt,
        system_prompt=system_prompt,
        model=model,
        max_output_tokens=max_output_tokens,
        response_mime_type=response_mime_type,
        thinking_level=thinking_level,
    )


async def call_groq_api(
    prompt: str,
    system_prompt: str = "",
    model: str = GROQ_PRIMARY_MODEL,
    *,
    max_output_tokens: int = 1024,
    response_mime_type: str | None = None,
    thinking_level: types.ThinkingLevel | str | None = None,
) -> Optional[str]:
    return await _call_openai_compatible_api(
        provider="groq",
        url="https://api.groq.com/openai/v1/chat/completions",
        api_key=getattr(settings, "GROQ_API_KEY", None),
        prompt=prompt,
        system_prompt=system_prompt,
        model=model,
        max_output_tokens=max_output_tokens,
        response_mime_type=response_mime_type,
        thinking_level=thinking_level,
    )


async def call_omnigate_api(
    prompt: str,
    system_prompt: str = "",
    model: str = OMNIGATE_PRIMARY_MODEL,
    *,
    max_output_tokens: int = 1024,
    response_mime_type: str | None = None,
    thinking_level: types.ThinkingLevel | str | None = None,
) -> Optional[str]:
    return await _call_openai_compatible_api(
        provider="omnigate",
        url=_omnigate_completions_url(
            getattr(settings, "OMNIGATE_BASE_URL", "https://llmgateway.onrender.com")
        ),
        api_key=getattr(settings, "LITELLM_MASTER_KEY", None),
        prompt=prompt,
        system_prompt=system_prompt,
        model=model,
        max_output_tokens=max_output_tokens,
        response_mime_type=response_mime_type,
        thinking_level=thinking_level,
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
    finish_reason: str | None = None
    prompt_token_count: int | None = None
    output_token_count: int | None = None
    thought_token_count: int | None = None
    total_token_count: int | None = None
    max_output_tokens: int | None = None
    thinking_level: str = "DEFAULT"


def _vertex_failure_result(
    error: VertexAIError,
    *,
    started: float,
    model_override: str | None = None,
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
        observed_model=model_override or getattr(settings, "VERTEX_LLM_MODEL", "gemini-3.5-flash"),
        observed=True,
        status=error.kind,
        project=getattr(settings, "GOOGLE_CLOUD_PROJECT", None),
        location=getattr(settings, "GOOGLE_CLOUD_LOCATION", "global"),
        provider_latency_ms=round((time.perf_counter() - started) * 1000, 3),
        primary_error_kind=error.kind,
    )


def _effective_direct_max_tokens(
    model: str,
    max_output_tokens: int,
    use_case: LLMUseCase,
) -> int:
    if use_case == LLMUseCase.GUARDRAIL and (
        "qwen" in model.lower()
        or "gpt-oss" in model.lower()
        or "deepseek" in model.lower()
    ):
        return max(max_output_tokens, 512)
    return max_output_tokens


async def _invoke_direct_caller(
    operation: Any,
    prompt: str,
    system_prompt: str,
    *,
    model: str,
    max_output_tokens: int,
    response_mime_type: str | None = None,
    thinking_level: types.ThinkingLevel | str | None = None,
) -> Optional[str]:
    kwargs: dict[str, Any] = {
        "model": model,
        "max_output_tokens": max_output_tokens,
    }
    if response_mime_type is not None or thinking_level is not None:
        try:
            sig = inspect.signature(operation)
            accepts_varkw = any(
                p.kind == inspect.Parameter.VAR_KEYWORD
                for p in sig.parameters.values()
            )
            if response_mime_type is not None and (
                accepts_varkw or "response_mime_type" in sig.parameters
            ):
                kwargs["response_mime_type"] = response_mime_type
            if thinking_level is not None and (
                accepts_varkw or "thinking_level" in sig.parameters
            ):
                kwargs["thinking_level"] = thinking_level
        except (TypeError, ValueError):
            pass
    return await operation(prompt, system_prompt, **kwargs)


def _default_direct_attempts(use_case: LLMUseCase) -> tuple[tuple[str, str, str | None, Any], ...]:
    base: list[tuple[str, str, str | None, Any]] = [
        (
            "openrouter",
            OPENROUTER_PRIMARY_MODEL,
            getattr(settings, "OPENROUTER_API_KEY", None),
            call_openrouter_api,
        ),
        (
            "gemini",
            GEMINI_PRIMARY_MODEL,
            getattr(settings, "GEMINI_API_KEY", None),
            call_gemini_api,
        ),
        (
            "nvidia",
            NVIDIA_PRIMARY_MODEL,
            getattr(settings, "NVIDIA_API_KEY", None),
            call_nvidia_api,
        ),
        (
            "groq",
            GROQ_PRIMARY_MODEL,
            getattr(settings, "GROQ_API_KEY", None),
            call_groq_api,
        ),
        (
            "gemini",
            GEMINI_SECONDARY_MODEL,
            getattr(settings, "GEMINI_API_KEY", None),
            call_gemini_api,
        ),
        (
            "groq",
            GROQ_SECONDARY_MODEL,
            getattr(settings, "GROQ_API_KEY", None),
            call_groq_api,
        ),
    ]
    if use_case == LLMUseCase.EVALUATION:
        base.append(
            (
                "omnigate",
                OMNIGATE_PRIMARY_MODEL,
                getattr(settings, "LITELLM_MASTER_KEY", None),
                call_omnigate_api,
            )
        )
    return tuple(base)


def _direct_provider_binding(provider: str) -> tuple[str, str | None, Any] | None:
    mapping: dict[str, tuple[str, str | None, Any]] = {
        "openrouter": (
            OPENROUTER_PRIMARY_MODEL,
            getattr(settings, "OPENROUTER_API_KEY", None),
            call_openrouter_api,
        ),
        "gemini": (
            GEMINI_PRIMARY_MODEL,
            getattr(settings, "GEMINI_API_KEY", None),
            call_gemini_api,
        ),
        "nvidia": (
            NVIDIA_PRIMARY_MODEL,
            getattr(settings, "NVIDIA_API_KEY", None),
            call_nvidia_api,
        ),
        "groq": (
            GROQ_PRIMARY_MODEL,
            getattr(settings, "GROQ_API_KEY", None),
            call_groq_api,
        ),
        "omnigate": (
            OMNIGATE_PRIMARY_MODEL,
            getattr(settings, "LITELLM_MASTER_KEY", None),
            call_omnigate_api,
        ),
    }
    return mapping.get(provider)


def _build_direct_result(
    text: str,
    *,
    provider: str,
    requested_model: str,
    started: float,
    fallback_used: bool,
    primary_error_kind: str | None = None,
) -> LLMGenerationResult:
    usage_meta = dict(getattr(text, "usage", {}) or {})
    finish_reason = usage_meta.pop("finish_reason", "STOP")
    observed_model = getattr(text, "observed_model", None) or requested_model
    return LLMGenerationResult(
        text=str(text),
        observed_provider=provider,
        observed_model=str(observed_model),
        observed=True,
        status="success",
        provider_latency_ms=round((time.perf_counter() - started) * 1000, 3),
        fallback_used=fallback_used,
        primary_error_kind=primary_error_kind,
        finish_reason=finish_reason,
        **usage_meta,
    )


async def _run_secondary_fallbacks(
    prompt: str,
    system_prompt: str,
    max_output_tokens: int,
    *,
    primary_error_kind: str,
    started: float,
    response_mime_type: str | None = None,
    thinking_level: types.ThinkingLevel | str | None = None,
    use_case: LLMUseCase = LLMUseCase.ANSWER,
    skip_target: tuple[str, str] | None = None,
) -> LLMGenerationResult | None:
    attempts = _default_direct_attempts(use_case)
    for provider, model, api_key, operation in attempts:
        if skip_target == (provider, model):
            continue
        if not api_key or _is_in_cooldown(provider, model):
            continue
        effective_tokens = _effective_direct_max_tokens(
            model,
            max_output_tokens,
            use_case,
        )
        text = await _invoke_direct_caller(
            operation,
            prompt,
            system_prompt,
            model=model,
            max_output_tokens=effective_tokens,
            response_mime_type=response_mime_type,
            thinking_level=thinking_level,
        )
        if text:
            return _build_direct_result(
                text,
                provider=provider,
                requested_model=model,
                started=started,
                fallback_used=True,
                primary_error_kind=primary_error_kind,
            )
    return None


def _resolve_effective_route(
    route: LLMRouteSelection | None,
    use_case: LLMUseCase,
) -> LLMRouteSelection:
    if route is not None:
        return route
    if use_case in {LLMUseCase.ANSWER, LLMUseCase.STRUCTURED_ANALYSIS}:
        scoped = _active_llm_route.get()
        if scoped is not None and scoped.normalized_provider() != "auto":
            return scoped
        default_prov = str(getattr(settings, "DEFAULT_LLM_PROVIDER", "auto") or "auto").strip().lower()
        if default_prov in {
            "google_vertex_ai",
            "gemini",
            "groq",
            "openrouter",
            "nvidia",
            "omnigate",
        }:
            return LLMRouteSelection(default_prov, None)
    return LLMRouteSelection("auto", None)


async def _generate_via_vertex(
    prompt: str,
    system_prompt: str,
    *,
    model: str | None = None,
    max_output_tokens: int = 1024,
    thinking_level: types.ThinkingLevel | str | None = None,
    response_mime_type: str | None = None,
    max_retries: int | None = None,
) -> LLMGenerationResult:
    vertex_options: dict[str, Any] = {
        "system_instruction": system_prompt,
        "max_output_tokens": max_output_tokens,
    }
    if model is not None:
        vertex_options["model"] = model
    if thinking_level is not None:
        vertex_options["thinking_level"] = thinking_level
    if max_retries is not None:
        vertex_options["max_retries"] = max_retries
    if response_mime_type is not None:
        vertex_options["response_mime_type"] = response_mime_type
    result = await get_vertex_provider().generate(prompt, **vertex_options)
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
        finish_reason=result.finish_reason,
        prompt_token_count=result.prompt_token_count,
        output_token_count=result.output_token_count,
        thought_token_count=result.thought_token_count,
        total_token_count=result.total_token_count,
        max_output_tokens=result.max_output_tokens,
        thinking_level=result.thinking_level,
    )


async def generate_llm_response_with_metadata(
    prompt: str,
    system_prompt: str = "",
    *,
    max_output_tokens: int = 1024,
    thinking_level: types.ThinkingLevel | str | None = None,
    use_case: LLMUseCase = LLMUseCase.ANSWER,
    max_retries: int | None = None,
    allow_fallback: bool = True,
    response_mime_type: str | None = None,
    route: LLMRouteSelection | None = None,
) -> LLMGenerationResult:
    """Use Vertex first on auto, or route to an explicit provider/model."""
    started = time.perf_counter()
    vertex_effective_mime = (
        response_mime_type
        if response_mime_type is not None
        else ("application/json" if use_case == LLMUseCase.STRUCTURED_ANALYSIS else None)
    )
    prompt_mentions_json = "json" in f"{system_prompt}\n{prompt}".lower()
    direct_effective_mime = (
        response_mime_type
        if response_mime_type is not None
        else (
            "application/json"
            if use_case == LLMUseCase.STRUCTURED_ANALYSIS and prompt_mentions_json
            else None
        )
    )
    effective_route = _resolve_effective_route(route, use_case)
    target_provider = effective_route.normalized_provider()

    if target_provider not in {
        "auto",
        "google_vertex_ai",
        "gemini",
        "groq",
        "openrouter",
        "nvidia",
        "omnigate",
    }:
        invalid = LLMGenerationResult(
            text="Provider LLM được yêu cầu không hợp lệ.",
            observed_provider=target_provider or "invalid",
            observed_model=effective_route.model or "unobserved",
            observed=True,
            status="invalid_provider",
            provider_latency_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        record_generation_result(invalid, use_case.value)
        return invalid

    # Explicit direct provider selection (gemini, groq, openrouter, nvidia, omnigate)
    if target_provider not in {"auto", "google_vertex_ai"}:
        binding = _direct_provider_binding(target_provider)
        assert binding is not None
        default_model, api_key, operation = binding
        chosen_model = _sanitize_model_id(target_provider, effective_route.model) or default_model
        if api_key and not _is_in_cooldown(target_provider, chosen_model):
            effective_tokens = _effective_direct_max_tokens(
                chosen_model,
                max_output_tokens,
                use_case,
            )
            text = await _invoke_direct_caller(
                operation,
                prompt,
                system_prompt,
                model=chosen_model,
                max_output_tokens=effective_tokens,
                response_mime_type=direct_effective_mime,
                thinking_level=thinking_level,
            )
            if text:
                direct_ok = _build_direct_result(
                    text,
                    provider=target_provider,
                    requested_model=chosen_model,
                    started=started,
                    fallback_used=False,
                )
                record_generation_result(direct_ok, use_case.value)
                return direct_ok
        if allow_fallback:
            fallback = await _run_secondary_fallbacks(
                prompt,
                system_prompt,
                max_output_tokens,
                primary_error_kind="provider_unavailable",
                started=started,
                response_mime_type=direct_effective_mime,
                thinking_level=thinking_level,
                use_case=use_case,
                skip_target=(target_provider, chosen_model),
            )
            if fallback is not None:
                record_generation_result(fallback, use_case.value)
                return fallback
            if not bool(getattr(settings, "USE_LEGACY_FREE_PIPELINE", False)):
                try:
                    vertex_fb = await _generate_via_vertex(
                        prompt,
                        system_prompt,
                        max_output_tokens=max_output_tokens,
                        thinking_level=thinking_level,
                        response_mime_type=vertex_effective_mime,
                        max_retries=max_retries,
                    )
                    vertex_fb = LLMGenerationResult(
                        **{
                            **vertex_fb.__dict__,
                            "fallback_used": True,
                            "primary_error_kind": "provider_unavailable",
                        }
                    )
                    record_generation_result(vertex_fb, use_case.value)
                    return vertex_fb
                except VertexAIError:
                    pass
        failed_direct = LLMGenerationResult(
            text="Model LLM được chọn hiện không khả dụng. Vui lòng thử lại sau.",
            observed_provider=target_provider,
            observed_model=chosen_model,
            observed=True,
            status="providers_exhausted" if allow_fallback else "provider_unavailable",
            provider_latency_ms=round((time.perf_counter() - started) * 1000, 3),
            fallback_used=allow_fallback,
            primary_error_kind="provider_unavailable",
        )
        record_generation_result(failed_direct, use_case.value)
        return failed_direct

    # Default auto chain OR explicit google_vertex_ai
    vertex_model_override = (
        _sanitize_model_id("google_vertex_ai", effective_route.model)
        if target_provider == "google_vertex_ai"
        else None
    )
    try:
        generation = await _generate_via_vertex(
            prompt,
            system_prompt,
            model=vertex_model_override,
            max_output_tokens=max_output_tokens,
            thinking_level=thinking_level,
            response_mime_type=vertex_effective_mime,
            max_retries=max_retries,
        )
    except VertexAIError as error:
        has_fallback = allow_fallback and bool(
            getattr(settings, "OPENROUTER_API_KEY", None)
            or getattr(settings, "GEMINI_API_KEY", None)
            or getattr(settings, "NVIDIA_API_KEY", None)
            or getattr(settings, "GROQ_API_KEY", None)
            or (
                use_case == LLMUseCase.EVALUATION
                and getattr(settings, "LITELLM_MASTER_KEY", None)
            )
        )
        if has_fallback:
            fallback = await _run_secondary_fallbacks(
                prompt,
                system_prompt,
                max_output_tokens,
                primary_error_kind=error.kind,
                started=started,
                response_mime_type=direct_effective_mime,
                thinking_level=thinking_level,
                use_case=use_case,
            )
            if fallback is not None:
                record_generation_result(fallback, use_case.value)
                return fallback
            exhausted = LLMGenerationResult(
                text=(
                    "Vertex AI và toàn bộ model API phụ đều tạm thời không khả dụng. "
                    "Vui lòng thử lại sau."
                ),
                observed_provider="google_vertex_ai",
                observed_model=vertex_model_override
                or getattr(settings, "VERTEX_LLM_MODEL", "gemini-3.5-flash"),
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
            record_generation_result(exhausted, use_case.value)
            return exhausted
        failure = _vertex_failure_result(
            error,
            started=started,
            model_override=vertex_model_override,
        )
        record_generation_result(failure, use_case.value)
        return failure

    record_generation_result(generation, use_case.value)
    return generation


async def generate_llm_response(
    prompt: str,
    system_prompt: str = "",
    *,
    max_output_tokens: int = 1024,
    thinking_level: types.ThinkingLevel | str | None = None,
    use_case: LLMUseCase = LLMUseCase.ANSWER,
    route: LLMRouteSelection | None = None,
) -> str:
    result = await generate_llm_response_with_metadata(
        prompt,
        system_prompt,
        max_output_tokens=max_output_tokens,
        thinking_level=thinking_level,
        use_case=use_case,
        route=route,
    )
    return result.text


async def _stream_openai_compatible(
    *,
    provider: str,
    url: str,
    api_key: str | None,
    prompt: str,
    system_prompt: str,
    model: str,
    max_output_tokens: int,
    started: float,
    fallback_used: bool,
    primary_error_kind: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> AsyncIterator[str | LLMGenerationResult]:
    if not api_key:
        return
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        **(extra_headers or {}),
    }
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_output_tokens,
        "stream": True,
    }
    pieces: list[str] = []
    observed_model = model
    finish_reason = "STOP"
    usage: dict[str, Any] = {}
    with provider_identity_scope(provider):
        async with get_direct_client().stream(
            "POST",
            url,
            headers=headers,
            json=payload,
            timeout=35.0,
        ) as response:
            if response.status_code in {429, 502, 503, 504}:
                _cooldowns[_cooldown_key(provider, model)] = time.time() + 30.0
                return
            response.raise_for_status()
            async for line in response.aiter_lines():
                stripped = line.strip()
                if not stripped or not stripped.startswith("data:"):
                    continue
                data_str = stripped[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                raw_model = event.get("model")
                if isinstance(raw_model, str) and raw_model.strip():
                    observed_model = raw_model.strip()
                if isinstance(event.get("usage"), dict):
                    usage = event["usage"]
                choices = event.get("choices") or []
                if choices:
                    delta = (choices[0].get("delta") or {}).get("content") or ""
                    if delta:
                        pieces.append(delta)
                        yield delta
                    fr = choices[0].get("finish_reason")
                    if fr:
                        finish_reason = str(fr)
    full_text = "".join(pieces).strip()
    if not full_text:
        return
    details = usage.get("completion_tokens_details") or {}
    yield LLMGenerationResult(
        text=full_text,
        observed_provider=provider,
        observed_model=observed_model,
        observed=True,
        status="success",
        provider_latency_ms=round((time.perf_counter() - started) * 1000, 3),
        fallback_used=fallback_used,
        primary_error_kind=primary_error_kind,
        finish_reason=finish_reason,
        prompt_token_count=_safe_token_int(usage.get("prompt_tokens")),
        output_token_count=_safe_token_int(usage.get("completion_tokens")),
        thought_token_count=_safe_token_int(details.get("reasoning_tokens")),
        total_token_count=_safe_token_int(usage.get("total_tokens")),
        max_output_tokens=max_output_tokens,
    )


async def _stream_gemini_direct(
    *,
    api_key: str | None,
    prompt: str,
    system_prompt: str,
    model: str,
    max_output_tokens: int,
    started: float,
    fallback_used: bool,
    primary_error_kind: str | None = None,
    thinking_level: types.ThinkingLevel | str | None = None,
) -> AsyncIterator[str | LLMGenerationResult]:
    if not api_key:
        return
    generation_config: dict[str, Any] = {
        "temperature": 0.2,
        "maxOutputTokens": max_output_tokens,
    }
    if thinking_level is not None:
        level_str = str(getattr(thinking_level, "value", thinking_level)).upper()
        if level_str == "MINIMAL" and "2.5-flash" in model:
            generation_config["thinkingConfig"] = {"thinkingBudget": 0}
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }
    if system_prompt:
        payload["system_instruction"] = {"parts": [{"text": system_prompt}]}
    pieces: list[str] = []
    observed_model = model
    finish_reason = "STOP"
    usage: dict[str, Any] = {}
    with provider_identity_scope("gemini"):
        async with get_direct_client().stream(
            "POST",
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse",
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            json=payload,
            timeout=35.0,
        ) as response:
            if response.status_code in {429, 502, 503, 504}:
                _cooldowns[_cooldown_key("gemini", model)] = time.time() + 30.0
                return
            response.raise_for_status()
            async for line in response.aiter_lines():
                stripped = line.strip()
                if not stripped or not stripped.startswith("data:"):
                    continue
                data_str = stripped[5:].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                raw_model = event.get("modelVersion") or event.get("model")
                if isinstance(raw_model, str) and raw_model.strip():
                    observed_model = raw_model.strip().removeprefix("models/")
                if isinstance(event.get("usageMetadata"), dict):
                    usage = event["usageMetadata"]
                candidates = event.get("candidates") or []
                if candidates:
                    parts = (candidates[0].get("content") or {}).get("parts") or []
                    for part in parts:
                        if part.get("thought"):
                            continue
                        delta = part.get("text") or ""
                        if delta:
                            pieces.append(delta)
                            yield delta
                    fr = candidates[0].get("finishReason")
                    if fr:
                        finish_reason = str(fr)
    full_text = "".join(pieces).strip()
    if not full_text:
        return
    yield LLMGenerationResult(
        text=full_text,
        observed_provider="gemini",
        observed_model=observed_model,
        observed=True,
        status="success",
        provider_latency_ms=round((time.perf_counter() - started) * 1000, 3),
        fallback_used=fallback_used,
        primary_error_kind=primary_error_kind,
        finish_reason=finish_reason,
        prompt_token_count=_safe_token_int(usage.get("promptTokenCount")),
        output_token_count=_safe_token_int(usage.get("candidatesTokenCount")),
        thought_token_count=_safe_token_int(usage.get("thoughtsTokenCount")),
        total_token_count=_safe_token_int(usage.get("totalTokenCount")),
        max_output_tokens=max_output_tokens,
    )


async def _stream_single_direct_target(
    provider: str,
    model: str,
    *,
    prompt: str,
    system_prompt: str,
    max_output_tokens: int,
    started: float,
    fallback_used: bool,
    primary_error_kind: str | None = None,
    thinking_level: types.ThinkingLevel | str | None = None,
) -> AsyncIterator[str | LLMGenerationResult]:
    if _is_in_cooldown(provider, model):
        return
    if provider == "gemini":
        async for item in _stream_gemini_direct(
            api_key=getattr(settings, "GEMINI_API_KEY", None),
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            max_output_tokens=max_output_tokens,
            started=started,
            fallback_used=fallback_used,
            primary_error_kind=primary_error_kind,
            thinking_level=thinking_level,
        ):
            yield item
        return
    endpoint_map: dict[str, tuple[str, str | None, dict[str, str] | None]] = {
        "openrouter": (
            "https://openrouter.ai/api/v1/chat/completions",
            getattr(settings, "OPENROUTER_API_KEY", None),
            {"HTTP-Referer": "https://vietlex.rag", "X-Title": "VietLex Legal RAG"},
        ),
        "nvidia": (
            "https://integrate.api.nvidia.com/v1/chat/completions",
            getattr(settings, "NVIDIA_API_KEY", None),
            None,
        ),
        "groq": (
            "https://api.groq.com/openai/v1/chat/completions",
            getattr(settings, "GROQ_API_KEY", None),
            None,
        ),
        "omnigate": (
            _omnigate_completions_url(
                getattr(settings, "OMNIGATE_BASE_URL", "https://llmgateway.onrender.com")
            ),
            getattr(settings, "LITELLM_MASTER_KEY", None),
            None,
        ),
    }
    entry = endpoint_map.get(provider)
    if entry is None:
        return
    url, api_key, extra_headers = entry
    async for item in _stream_openai_compatible(
        provider=provider,
        url=url,
        api_key=api_key,
        prompt=prompt,
        system_prompt=system_prompt,
        model=model,
        max_output_tokens=max_output_tokens,
        started=started,
        fallback_used=fallback_used,
        primary_error_kind=primary_error_kind,
        extra_headers=extra_headers,
    ):
        yield item


async def stream_llm_response_with_metadata(
    prompt: str,
    system_prompt: str = "",
    *,
    max_output_tokens: int = 1024,
    thinking_level: types.ThinkingLevel | str | None = None,
    use_case: LLMUseCase = LLMUseCase.ANSWER,
    max_retries: int | None = None,
    allow_fallback: bool = True,
    route: LLMRouteSelection | None = None,
) -> AsyncIterator[str | LLMGenerationResult]:
    """Stream token delta strings followed by a final LLMGenerationResult."""
    started = time.perf_counter()
    effective_route = _resolve_effective_route(route, use_case)
    target_provider = effective_route.normalized_provider()

    if target_provider not in {
        "auto",
        "google_vertex_ai",
        "gemini",
        "groq",
        "openrouter",
        "nvidia",
        "omnigate",
    }:
        invalid = LLMGenerationResult(
            text="Provider LLM được yêu cầu không hợp lệ.",
            observed_provider=target_provider or "invalid",
            observed_model=effective_route.model or "unobserved",
            observed=True,
            status="invalid_provider",
            provider_latency_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        record_generation_result(invalid, use_case.value)
        yield invalid
        return

    if target_provider not in {"auto", "google_vertex_ai"}:
        binding = _direct_provider_binding(target_provider)
        assert binding is not None
        chosen_model = _sanitize_model_id(target_provider, effective_route.model) or binding[0]
        completed: LLMGenerationResult | None = None
        emitted_any = False
        active_provider = target_provider
        active_model = chosen_model
        try:
            async for item in _stream_single_direct_target(
                target_provider,
                chosen_model,
                prompt=prompt,
                system_prompt=system_prompt,
                max_output_tokens=max_output_tokens,
                started=started,
                fallback_used=False,
                thinking_level=thinking_level,
            ):
                if isinstance(item, str):
                    emitted_any = True
                    yield item
                else:
                    completed = item
        except ProviderHttpAttemptBudgetExceeded:
            raise
        except Exception as error:
            _record_secondary_failure(target_provider, error)
        if completed is not None:
            record_generation_result(completed, use_case.value)
            yield completed
            return
        if emitted_any:
            interrupted = LLMGenerationResult(
                text="Luồng phản hồi bị gián đoạn giữa chừng. Vui lòng thử lại.",
                observed_provider=active_provider,
                observed_model=active_model,
                observed=True,
                status="stream_interrupted",
                provider_latency_ms=round((time.perf_counter() - started) * 1000, 3),
                fallback_used=False,
                primary_error_kind="stream_interrupted",
            )
            record_generation_result(interrupted, use_case.value)
            yield interrupted
            return
        if allow_fallback:
            for fb_provider, fb_model, fb_key, _op in _default_direct_attempts(use_case):
                if (fb_provider, fb_model) == (target_provider, chosen_model) or not fb_key:
                    continue
                active_provider, active_model = fb_provider, fb_model
                try:
                    async for item in _stream_single_direct_target(
                        fb_provider,
                        fb_model,
                        prompt=prompt,
                        system_prompt=system_prompt,
                        max_output_tokens=max_output_tokens,
                        started=started,
                        fallback_used=True,
                        primary_error_kind="provider_unavailable",
                        thinking_level=thinking_level,
                    ):
                        if isinstance(item, str):
                            emitted_any = True
                            yield item
                        else:
                            completed = item
                except ProviderHttpAttemptBudgetExceeded:
                    raise
                except Exception as error:
                    _record_secondary_failure(fb_provider, error)
                if completed is not None:
                    record_generation_result(completed, use_case.value)
                    yield completed
                    return
                if emitted_any:
                    interrupted = LLMGenerationResult(
                        text="Luồng phản hồi bị gián đoạn giữa chừng. Vui lòng thử lại.",
                        observed_provider=active_provider,
                        observed_model=active_model,
                        observed=True,
                        status="stream_interrupted",
                        provider_latency_ms=round((time.perf_counter() - started) * 1000, 3),
                        fallback_used=True,
                        primary_error_kind="stream_interrupted",
                    )
                    record_generation_result(interrupted, use_case.value)
                    yield interrupted
                    return
            if not emitted_any and not bool(getattr(settings, "USE_LEGACY_FREE_PIPELINE", False)):
                try:
                    v_opts: dict[str, Any] = {
                        "system_instruction": system_prompt,
                        "max_output_tokens": max_output_tokens,
                    }
                    if thinking_level is not None:
                        v_opts["thinking_level"] = thinking_level
                    if max_retries is not None:
                        v_opts["max_retries"] = max_retries
                    async for item in get_vertex_provider().generate_stream(prompt, **v_opts):
                        if isinstance(item, str):
                            emitted_any = True
                            yield item
                        else:
                            metadata = item.metadata
                            v_gen = LLMGenerationResult(
                                text=item.text,
                                observed_provider=metadata.provider,
                                observed_model=metadata.model,
                                observed=True,
                                status=metadata.status,
                                project=metadata.project,
                                location=metadata.location,
                                provider_latency_ms=metadata.latency_ms,
                                fallback_used=True,
                                primary_error_kind="provider_unavailable",
                                finish_reason=item.finish_reason,
                                prompt_token_count=item.prompt_token_count,
                                output_token_count=item.output_token_count,
                                thought_token_count=item.thought_token_count,
                                total_token_count=item.total_token_count,
                                max_output_tokens=item.max_output_tokens,
                                thinking_level=item.thinking_level,
                            )
                            record_generation_result(v_gen, use_case.value)
                            yield v_gen
                            return
                except VertexAIError:
                    if emitted_any:
                        interrupted_v = LLMGenerationResult(
                            text="Luồng phản hồi bị gián đoạn giữa chừng. Vui lòng thử lại.",
                            observed_provider="google_vertex_ai",
                            observed_model=getattr(settings, "VERTEX_LLM_MODEL", "gemini-3.5-flash"),
                            observed=True,
                            status="stream_interrupted",
                            provider_latency_ms=round((time.perf_counter() - started) * 1000, 3),
                            fallback_used=True,
                            primary_error_kind="stream_interrupted",
                        )
                        record_generation_result(interrupted_v, use_case.value)
                        yield interrupted_v
                        return
        failed = LLMGenerationResult(
            text="Model LLM được chọn hiện không khả dụng. Vui lòng thử lại sau.",
            observed_provider=target_provider,
            observed_model=chosen_model,
            observed=True,
            status="providers_exhausted" if allow_fallback else "provider_unavailable",
            provider_latency_ms=round((time.perf_counter() - started) * 1000, 3),
            fallback_used=allow_fallback,
            primary_error_kind="provider_unavailable",
        )
        record_generation_result(failed, use_case.value)
        yield failed
        return

    # Vertex primary stream (auto or google_vertex_ai)
    vertex_model_override = (
        _sanitize_model_id("google_vertex_ai", effective_route.model)
        if target_provider == "google_vertex_ai"
        else None
    )
    emitted_vertex = False
    try:
        vertex_opts: dict[str, Any] = {
            "system_instruction": system_prompt,
            "max_output_tokens": max_output_tokens,
        }
        if vertex_model_override is not None:
            vertex_opts["model"] = vertex_model_override
        if thinking_level is not None:
            vertex_opts["thinking_level"] = thinking_level
        if max_retries is not None:
            vertex_opts["max_retries"] = max_retries
        async for item in get_vertex_provider().generate_stream(prompt, **vertex_opts):
            if isinstance(item, str):
                emitted_vertex = True
                yield item
            else:
                metadata = item.metadata
                generation = LLMGenerationResult(
                    text=item.text,
                    observed_provider=metadata.provider,
                    observed_model=metadata.model,
                    observed=True,
                    status=metadata.status,
                    project=metadata.project,
                    location=metadata.location,
                    provider_latency_ms=metadata.latency_ms,
                    finish_reason=item.finish_reason,
                    prompt_token_count=item.prompt_token_count,
                    output_token_count=item.output_token_count,
                    thought_token_count=item.thought_token_count,
                    total_token_count=item.total_token_count,
                    max_output_tokens=item.max_output_tokens,
                    thinking_level=item.thinking_level,
                )
                record_generation_result(generation, use_case.value)
                yield generation
                return
    except VertexAIError as error:
        if emitted_vertex:
            interrupted = LLMGenerationResult(
                text="Luồng phản hồi bị gián đoạn giữa chừng. Vui lòng thử lại.",
                observed_provider="google_vertex_ai",
                observed_model=vertex_model_override
                or getattr(settings, "VERTEX_LLM_MODEL", "gemini-3.5-flash"),
                observed=True,
                status="stream_interrupted",
                project=getattr(settings, "GOOGLE_CLOUD_PROJECT", None),
                location=getattr(settings, "GOOGLE_CLOUD_LOCATION", "global"),
                provider_latency_ms=round((time.perf_counter() - started) * 1000, 3),
                fallback_used=False,
                primary_error_kind=error.kind,
            )
            record_generation_result(interrupted, use_case.value)
            yield interrupted
            return
        if allow_fallback:
            for fb_provider, fb_model, fb_key, _op in _default_direct_attempts(use_case):
                if not fb_key:
                    continue
                completed_fb: LLMGenerationResult | None = None
                emitted_fb = False
                try:
                    async for item in _stream_single_direct_target(
                        fb_provider,
                        fb_model,
                        prompt=prompt,
                        system_prompt=system_prompt,
                        max_output_tokens=max_output_tokens,
                        started=started,
                        fallback_used=True,
                        primary_error_kind=error.kind,
                        thinking_level=thinking_level,
                    ):
                        if isinstance(item, str):
                            emitted_fb = True
                            yield item
                        else:
                            completed_fb = item
                except ProviderHttpAttemptBudgetExceeded:
                    raise
                except Exception as fb_err:
                    _record_secondary_failure(fb_provider, fb_err)
                if completed_fb is not None:
                    record_generation_result(completed_fb, use_case.value)
                    yield completed_fb
                    return
                if emitted_fb:
                    interrupted_fb = LLMGenerationResult(
                        text="Luồng phản hồi bị gián đoạn giữa chừng. Vui lòng thử lại.",
                        observed_provider=fb_provider,
                        observed_model=fb_model,
                        observed=True,
                        status="stream_interrupted",
                        provider_latency_ms=round((time.perf_counter() - started) * 1000, 3),
                        fallback_used=True,
                        primary_error_kind=error.kind,
                    )
                    record_generation_result(interrupted_fb, use_case.value)
                    yield interrupted_fb
                    return
            has_any_key = bool(
                getattr(settings, "OPENROUTER_API_KEY", None)
                or getattr(settings, "GEMINI_API_KEY", None)
                or getattr(settings, "NVIDIA_API_KEY", None)
                or getattr(settings, "GROQ_API_KEY", None)
            )
            if has_any_key:
                exhausted = LLMGenerationResult(
                    text=(
                        "Vertex AI và toàn bộ model API phụ đều tạm thời không khả dụng. "
                        "Vui lòng thử lại sau."
                    ),
                    observed_provider="google_vertex_ai",
                    observed_model=vertex_model_override
                    or getattr(settings, "VERTEX_LLM_MODEL", "gemini-3.5-flash"),
                    observed=True,
                    status="providers_exhausted",
                    project=getattr(settings, "GOOGLE_CLOUD_PROJECT", None),
                    location=getattr(settings, "GOOGLE_CLOUD_LOCATION", "global"),
                    provider_latency_ms=round((time.perf_counter() - started) * 1000, 3),
                    fallback_used=True,
                    primary_error_kind=error.kind,
                )
                record_generation_result(exhausted, use_case.value)
                yield exhausted
                return
        failure = _vertex_failure_result(
            error,
            started=started,
            model_override=vertex_model_override,
        )
        record_generation_result(failure, use_case.value)
        yield failure


stream_llm_tokens = stream_llm_response_with_metadata


async def stream_llm_response(
    prompt: str,
    system_prompt: str = "",
    *,
    max_output_tokens: int = 1024,
    thinking_level: types.ThinkingLevel | str | None = None,
    use_case: LLMUseCase = LLMUseCase.ANSWER,
    route: LLMRouteSelection | None = None,
) -> AsyncIterator[str]:
    async for item in stream_llm_response_with_metadata(
        prompt,
        system_prompt,
        max_output_tokens=max_output_tokens,
        thinking_level=thinking_level,
        use_case=use_case,
        route=route,
    ):
        if isinstance(item, str):
            yield item
