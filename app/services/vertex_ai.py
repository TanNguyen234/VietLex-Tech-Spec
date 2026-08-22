from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Any, Callable

import httpx
import requests
from google import auth as google_auth
from google.auth import exceptions as google_auth_exceptions
from google import genai
from google.genai import types
from google.oauth2 import service_account
from dotenv import dotenv_values, find_dotenv

from app.config import Settings, get_settings, install_system_trust_store


PROVIDER_NAME = "google_vertex_ai"
_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_PEM_PATTERN = re.compile(
    r"-----BEGIN [^-]+-----.*?-----END [^-]+-----",
    re.DOTALL,
)
_JSON_PATH_PATTERN = re.compile(
    r"(?:[A-Za-z]:\\|/)[^\s\"']+\.json",
    re.IGNORECASE,
)
_TOKEN_PATTERN = re.compile(
    r"(?i)(?:bearer\s+|access[_-]?token[=:]\s*|api[_-]?key[=:]\s*)[^\s,;]+"
)


def _safe_error_message(error: BaseException) -> str:
    message = _PEM_PATTERN.sub("[REDACTED]", str(error))
    message = _JSON_PATH_PATTERN.sub("[REDACTED]", message)
    message = _TOKEN_PATTERN.sub("[REDACTED]", message)
    return message[:300] or error.__class__.__name__


class VertexAIError(RuntimeError):
    kind = "technical"

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class VertexAuthenticationError(VertexAIError):
    kind = "authentication"


class VertexPermissionError(VertexAIError):
    kind = "permission"


class VertexQuotaError(VertexAIError):
    kind = "quota"


class VertexModelError(VertexAIError):
    kind = "invalid_model"


class VertexNetworkError(VertexAIError):
    kind = "network"


class VertexInvalidResponseError(VertexAIError):
    kind = "invalid_response"


def _mapped_error(error: BaseException) -> VertexAIError:
    if isinstance(error, VertexAIError):
        return error
    code = getattr(error, "code", None)
    message = _safe_error_message(error)
    if isinstance(
        error,
        (
            google_auth_exceptions.DefaultCredentialsError,
            google_auth_exceptions.RefreshError,
        ),
    ):
        return VertexAuthenticationError(message, status_code=code)
    if code == 401:
        return VertexAuthenticationError(message, status_code=code)
    if code == 403:
        return VertexPermissionError(message, status_code=code)
    if code == 429:
        return VertexQuotaError(message, status_code=code)
    if code in (400, 404):
        return VertexModelError(message, status_code=code)
    if isinstance(
        error,
        (
            httpx.ConnectError,
            httpx.TimeoutException,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ),
    ) or (
        isinstance(code, int) and (code == 408 or code >= 500)
    ):
        return VertexNetworkError(message, status_code=code)
    return VertexAIError(message, status_code=code)


def _load_adc() -> tuple[Any, str | None]:
    service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if service_account_json:
        info = json.loads(service_account_json)
        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=[_CLOUD_PLATFORM_SCOPE],
        )
        return credentials, info.get("project_id")
    return google_auth.default(scopes=[_CLOUD_PLATFORM_SCOPE])


@dataclass(frozen=True)
class ProviderMetadata:
    provider: str
    model: str
    project: str
    location: str
    status: str
    latency_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GenerationResult:
    text: str
    metadata: ProviderMetadata
    finish_reason: str | None = None
    prompt_token_count: int | None = None
    output_token_count: int | None = None
    thought_token_count: int | None = None
    total_token_count: int | None = None
    max_output_tokens: int | None = None
    thinking_level: str = "DEFAULT"


@dataclass(frozen=True)
class EmbeddingResult:
    values: tuple[float, ...]
    output_dimensionality: int
    l2_norm: float
    metadata: ProviderMetadata


class VertexAIProvider:
    def __init__(
        self,
        *,
        settings: Settings | Any | None = None,
        credentials_loader: Callable[[], tuple[Any, str | None]] | None = None,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._credentials_loader = credentials_loader or _load_adc
        self._client_factory = client_factory or genai.Client
        self._client: Any | None = None
        self._project: str | None = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        install_system_trust_store()
        dotenv_path = find_dotenv(usecwd=True)
        if dotenv_path and "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ:
            credential_path = dotenv_values(dotenv_path).get(
                "GOOGLE_APPLICATION_CREDENTIALS"
            )
            if credential_path:
                resolved = Path(credential_path)
                if not resolved.is_absolute():
                    resolved = Path(dotenv_path).parent / resolved
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(
                    resolved.resolve()
                )
        try:
            credentials, adc_project = self._credentials_loader()
        except Exception:
            raise VertexAuthenticationError(
                "Application Default Credentials could not be discovered."
            ) from None
        project = self.settings.GOOGLE_CLOUD_PROJECT or adc_project
        if not project:
            raise VertexAuthenticationError(
                "ADC was discovered but no Google Cloud project could be resolved."
            )
        retry_options = types.HttpRetryOptions(
            attempts=self.settings.VERTEX_MAX_RETRIES + 1,
        )
        http_options = types.HttpOptions(
            api_version="v1",
            timeout=int(self.settings.VERTEX_REQUEST_TIMEOUT_SECONDS * 1000),
            retry_options=retry_options,
        )
        try:
            self._client = self._client_factory(
                vertexai=True,
                credentials=credentials,
                project=project,
                location=self.settings.GOOGLE_CLOUD_LOCATION,
                http_options=http_options,
            )
        except Exception as error:
            raise _mapped_error(error) from None
        self._project = project
        return self._client

    def _metadata(self, model: str, started: float) -> ProviderMetadata:
        return ProviderMetadata(
            provider=PROVIDER_NAME,
            model=model,
            project=self._project or self.settings.GOOGLE_CLOUD_PROJECT or "unresolved",
            location=self.settings.GOOGLE_CLOUD_LOCATION,
            status="success",
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    async def generate(
        self,
        prompt: str,
        *,
        system_instruction: str = "",
        max_output_tokens: int = 1024,
        thinking_level: types.ThinkingLevel | None = None,
    ) -> GenerationResult:
        started = time.perf_counter()
        client = self._get_client()
        config = types.GenerateContentConfig(
            system_instruction=system_instruction or None,
            temperature=0.2,
            max_output_tokens=max_output_tokens,
            thinking_config=(
                types.ThinkingConfig(thinking_level=thinking_level)
                if thinking_level is not None
                else None
            ),
        )
        try:
            response = await client.aio.models.generate_content(
                model=self.settings.VERTEX_LLM_MODEL,
                contents=prompt,
                config=config,
            )
        except Exception as error:
            raise _mapped_error(error) from None
        text = (getattr(response, "text", None) or "").strip()
        if not text:
            raise VertexInvalidResponseError(
                "Vertex AI returned an empty generation response."
            )
        candidates = getattr(response, "candidates", None) or []
        finish_reason_value = (
            getattr(candidates[0], "finish_reason", None)
            if candidates
            else None
        )
        finish_reason = getattr(
            finish_reason_value,
            "value",
            finish_reason_value,
        )
        usage = getattr(response, "usage_metadata", None)
        thinking_value = getattr(thinking_level, "value", thinking_level)
        return GenerationResult(
            text=text,
            metadata=self._metadata(self.settings.VERTEX_LLM_MODEL, started),
            finish_reason=(str(finish_reason) if finish_reason else None),
            prompt_token_count=getattr(usage, "prompt_token_count", None),
            output_token_count=getattr(usage, "candidates_token_count", None),
            thought_token_count=getattr(usage, "thoughts_token_count", None),
            total_token_count=getattr(usage, "total_token_count", None),
            max_output_tokens=max_output_tokens,
            thinking_level=(
                str(thinking_value) if thinking_value else "DEFAULT"
            ),
        )

    async def generate_structured(
        self,
        prompt: str,
        *,
        response_model: type[Any],
        max_output_tokens: int = 768,
    ) -> Any:
        """Generate a schema-constrained object for offline judge metrics."""
        client = self._get_client()
        config = types.GenerateContentConfig(
            temperature=0,
            max_output_tokens=max_output_tokens,
            response_mime_type="application/json",
            response_schema=response_model,
            thinking_config=types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.MINIMAL,
            ),
        )
        try:
            response = await client.aio.models.generate_content(
                model=self.settings.VERTEX_LLM_MODEL,
                contents=prompt,
                config=config,
            )
        except Exception as error:
            raise _mapped_error(error) from None
        parsed = getattr(response, "parsed", None)
        if parsed is None:
            raise VertexInvalidResponseError(
                "Vertex AI returned no structured generation response."
            )
        if isinstance(parsed, response_model):
            return parsed
        try:
            return response_model.model_validate(parsed)
        except Exception:
            raise VertexInvalidResponseError(
                "Vertex AI returned an invalid structured generation response."
            ) from None

    async def embed_query(
        self,
        query: str,
        *,
        output_dimensionality: int,
        task: str = "question_answering",
    ) -> EmbeddingResult:
        task_labels = {
            "question_answering": "question answering",
            "search_result": "search result",
        }
        if task not in task_labels:
            raise ValueError(f"Unsupported embedding task: {task}")
        content = f"task: {task_labels[task]} | query: {query}"
        return await self._embed(content, output_dimensionality)

    async def embed_document(
        self,
        text: str,
        *,
        title: str | None = None,
        output_dimensionality: int,
    ) -> EmbeddingResult:
        content = f"title: {title or 'none'} | text: {text}"
        return await self._embed(content, output_dimensionality)

    async def _embed(
        self,
        content: str,
        output_dimensionality: int,
    ) -> EmbeddingResult:
        if not 128 <= output_dimensionality <= 3072:
            raise ValueError("output_dimensionality must be between 128 and 3072")
        started = time.perf_counter()
        client = self._get_client()
        try:
            response = await client.aio.models.embed_content(
                model=self.settings.VERTEX_EMBEDDING_MODEL,
                contents=content,
                config=types.EmbedContentConfig(
                    output_dimensionality=output_dimensionality,
                ),
            )
        except Exception as error:
            raise _mapped_error(error) from None
        embeddings = getattr(response, "embeddings", None) or []
        values = tuple(float(value) for value in (
            getattr(embeddings[0], "values", None) if embeddings else []
        ) or [])
        if len(values) != output_dimensionality or not all(
            math.isfinite(value) for value in values
        ):
            raise VertexInvalidResponseError(
                "Vertex AI returned an invalid embedding vector."
            )
        norm = math.sqrt(sum(value * value for value in values))
        if not math.isclose(norm, 1.0, rel_tol=0.02, abs_tol=0.02):
            raise VertexInvalidResponseError(
                "Vertex AI embedding vector is not L2 normalized."
            )
        return EmbeddingResult(
            values=values,
            output_dimensionality=output_dimensionality,
            l2_norm=norm,
            metadata=self._metadata(
                self.settings.VERTEX_EMBEDDING_MODEL,
                started,
            ),
        )


_provider: VertexAIProvider | None = None


def get_vertex_provider() -> VertexAIProvider:
    global _provider
    if _provider is None:
        _provider = VertexAIProvider()
    return _provider
