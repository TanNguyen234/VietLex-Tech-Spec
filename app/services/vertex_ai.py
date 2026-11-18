from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import random
import re
import time
from typing import Any, AsyncIterator, Callable

import httpx
import requests
from google import auth as google_auth
from google.auth import exceptions as google_auth_exceptions
from google.auth.transport import mtls
from google.auth.transport.requests import Request as GoogleAuthRequest
from google import genai
from google.genai import types
from google.oauth2 import service_account
from dotenv import dotenv_values, find_dotenv

from app.config import (
    Settings,
    get_settings,
    install_system_trust_store,
    system_ssl_context,
)
from app.services.provider_http_budget import (
    ProviderHttpAsyncTransport,
    ProviderHttpAttemptBudgetExceeded,
    _wrap_client_transports,
    create_vertex_httpx_clients,
    current_provider_http_budget,
)


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


class VertexDisabledError(VertexAIError):
    kind = "disabled"


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


class VertexMTLSUnsupportedError(VertexAIError):
    kind = "unsupported_transport_configuration"


def _mtls_required_for_default_client() -> bool:
    """Whether the SDK would select its client-certificate mTLS path."""

    return bool(
        mtls.should_use_client_cert() and mtls.has_default_client_cert_source()
    )


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
        self._uses_default_client_factory = self._client_factory is genai.Client
        self._client: Any | None = None
        self._project: str | None = None
        self._credentials: Any | None = None
        self._token_refreshed_at: float | None = None
        self._token_lock: asyncio.Lock | None = None
        self._batch_embed_http2_client: httpx.AsyncClient | None = None
        self._owned_httpx_clients: tuple[httpx.Client, httpx.AsyncClient] | None = None

    def _get_client(self) -> Any:
        if getattr(self.settings, "USE_LEGACY_FREE_PIPELINE", False):
            raise VertexDisabledError(
                "Google Cloud is disabled by USE_LEGACY_FREE_PIPELINE."
            )
        if self._client is not None:
            return self._client
        if self._uses_default_client_factory and _mtls_required_for_default_client():
            raise VertexMTLSUnsupportedError(
                "Vertex HTTP attempt accounting does not support the configured mTLS client certificate."
            )
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
        quota_project = getattr(
            self.settings, "GOOGLE_CLOUD_QUOTA_PROJECT", None
        )
        if quota_project:
            try:
                credentials = credentials.with_quota_project(quota_project)
            except Exception:
                raise VertexAuthenticationError(
                    "Google Cloud quota project could not be applied to credentials."
                ) from None
        retry_options = types.HttpRetryOptions(
            attempts=self.settings.VERTEX_MAX_RETRIES + 1,
        )
        options: dict[str, Any] = {
            "api_version": "v1",
            "timeout": int(self.settings.VERTEX_REQUEST_TIMEOUT_SECONDS * 1000),
            "retry_options": retry_options,
        }
        if self._uses_default_client_factory:
            if self._owned_httpx_clients is None:
                try:
                    self._owned_httpx_clients = create_vertex_httpx_clients(
                        timeout_seconds=self.settings.VERTEX_REQUEST_TIMEOUT_SECONDS,
                        verify=system_ssl_context(),
                    )
                except Exception as error:
                    raise _mapped_error(error) from None
            options["httpx_client"] = self._owned_httpx_clients[0]
            options["httpx_async_client"] = self._owned_httpx_clients[1]
        http_options = types.HttpOptions(**options)
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
        self._credentials = credentials
        return self._client

    async def close(self) -> None:
        client = self._client
        self._client = None
        self._credentials = None
        h2_client = self._batch_embed_http2_client
        self._batch_embed_http2_client = None
        clients = self._owned_httpx_clients
        self._owned_httpx_clients = None
        try:
            if h2_client is not None and not h2_client.is_closed:
                await h2_client.aclose()
            if client is not None:
                close = getattr(client, "close", None)
                if callable(close):
                    close()
                aio = getattr(client, "aio", None)
                aclose = getattr(aio, "aclose", None)
                if callable(aclose):
                    await aclose()
        finally:
            if clients is not None:
                sync_client, async_client = clients
                try:
                    if not sync_client.is_closed:
                        sync_client.close()
                finally:
                    if not async_client.is_closed:
                        await async_client.aclose()

    def _metadata(self, model: str, started: float) -> ProviderMetadata:
        return ProviderMetadata(
            provider=PROVIDER_NAME,
            model=model,
            project=self._project or self.settings.GOOGLE_CLOUD_PROJECT or "unresolved",
            location=self.settings.GOOGLE_CLOUD_LOCATION,
            status="success",
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    @staticmethod
    def _ensure_async_model_capacity() -> None:
        budget = current_provider_http_budget()
        if budget is not None:
            budget.ensure_capacity(
                boundary="vertex_model_httpx_async",
                provider=PROVIDER_NAME,
            )

    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        system_instruction: str = "",
        max_output_tokens: int = 1024,
        thinking_level: types.ThinkingLevel | None = None,
        response_mime_type: str | None = None,
        response_json_schema: dict[str, Any] | None = None,
        pdf_bytes: bytes | None = None,
        max_retries: int | None = None,
    ) -> GenerationResult:
        if pdf_bytes is not None and (
            not isinstance(pdf_bytes, bytes) or not pdf_bytes.startswith(b"%PDF-")
            or len(pdf_bytes) > 3_700_000
        ):
            raise ValueError("invalid_pdf_payload")
        if max_retries is not None and not 0 <= max_retries <= 5:
            raise ValueError("invalid_retry_limit")
        self._ensure_async_model_capacity()
        started = time.perf_counter()
        client = self._get_client()
        effective_model = model or self.settings.VERTEX_LLM_MODEL
        config = types.GenerateContentConfig(
            system_instruction=system_instruction or None,
            temperature=0.2,
            max_output_tokens=max_output_tokens,
            response_mime_type=response_mime_type,
            response_json_schema=response_json_schema,
            http_options=(types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=max_retries + 1))
                          if max_retries is not None else None),
            thinking_config=(
                types.ThinkingConfig(thinking_level=thinking_level)
                if thinking_level is not None
                else None
            ),
        )
        try:
            response = await client.aio.models.generate_content(
                model=effective_model,
                contents=prompt if pdf_bytes is None else [prompt, types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")],
                config=config,
            )
        except ProviderHttpAttemptBudgetExceeded:
            raise
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
            metadata=self._metadata(effective_model, started),
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

    async def generate_stream(
        self,
        prompt: str,
        *,
        model: str | None = None,
        system_instruction: str = "",
        max_output_tokens: int = 1024,
        thinking_level: types.ThinkingLevel | None = None,
        response_mime_type: str | None = None,
        max_retries: int | None = None,
    ) -> AsyncIterator[str | GenerationResult]:
        if max_retries is not None and not 0 <= max_retries <= 5:
            raise ValueError("invalid_retry_limit")
        self._ensure_async_model_capacity()
        started = time.perf_counter()
        client = self._get_client()
        effective_model = model or self.settings.VERTEX_LLM_MODEL
        config = types.GenerateContentConfig(
            system_instruction=system_instruction or None,
            temperature=0.2,
            max_output_tokens=max_output_tokens,
            response_mime_type=response_mime_type,
            http_options=(
                types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=max_retries + 1))
                if max_retries is not None
                else None
            ),
            thinking_config=(
                types.ThinkingConfig(thinking_level=thinking_level)
                if thinking_level is not None
                else None
            ),
        )
        pieces: list[str] = []
        finish_reason: str | None = None
        usage = None
        stream = None
        try:
            stream = await client.aio.models.generate_content_stream(
                model=effective_model,
                contents=prompt,
                config=config,
            )
            async for chunk in stream:
                chunk_text = getattr(chunk, "text", None) or ""
                if chunk_text:
                    pieces.append(chunk_text)
                    yield chunk_text
                candidates = getattr(chunk, "candidates", None) or []
                if candidates:
                    fr = getattr(candidates[0], "finish_reason", None)
                    fr_val = getattr(fr, "value", fr)
                    if fr_val:
                        finish_reason = str(fr_val)
                chunk_usage = getattr(chunk, "usage_metadata", None)
                if chunk_usage is not None:
                    usage = chunk_usage
        except ProviderHttpAttemptBudgetExceeded:
            raise
        except Exception as error:
            raise _mapped_error(error) from None
        finally:
            if stream is not None and hasattr(stream, "aclose"):
                await stream.aclose()
        full_text = "".join(pieces).strip()
        if not full_text:
            raise VertexInvalidResponseError(
                "Vertex AI returned an empty streaming generation response."
            )
        thinking_value = getattr(thinking_level, "value", thinking_level)
        yield GenerationResult(
            text=full_text,
            metadata=self._metadata(effective_model, started),
            finish_reason=finish_reason or "STOP",
            prompt_token_count=getattr(usage, "prompt_token_count", None),
            output_token_count=getattr(usage, "candidates_token_count", None),
            thought_token_count=getattr(usage, "thoughts_token_count", None),
            total_token_count=getattr(usage, "total_token_count", None),
            max_output_tokens=max_output_tokens,
            thinking_level=str(thinking_value) if thinking_value else "DEFAULT",
        )

    async def generate_structured(
        self,
        prompt: str,
        *,
        response_model: type[Any],
        max_output_tokens: int = 768,
    ) -> Any:
        """Generate a schema-constrained object for offline judge metrics."""
        self._ensure_async_model_capacity()
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
        except ProviderHttpAttemptBudgetExceeded:
            raise
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

    async def _get_valid_bearer_token(self) -> str:
        self._get_client()
        if self._token_lock is None:
            self._token_lock = asyncio.Lock()
        async with self._token_lock:
            creds = self._credentials
            if creds is None:
                raise VertexAuthenticationError(
                    "Vertex AI credentials were not initialized."
                )
            now = time.monotonic()
            token = getattr(creds, "token", None)
            valid = bool(getattr(creds, "valid", False))
            if (
                not token
                or not valid
                or self._token_refreshed_at is None
                or (now - self._token_refreshed_at) > 2400
            ):
                try:
                    await asyncio.to_thread(creds.refresh, GoogleAuthRequest())
                except Exception as error:
                    raise _mapped_error(error) from None
                self._token_refreshed_at = time.monotonic()
                token = getattr(creds, "token", None)
            if not token:
                raise VertexAuthenticationError(
                    "Vertex AI access token could not be refreshed."
                )
            return str(token)

    def _get_batch_http2_client(self) -> httpx.AsyncClient:
        if (
            self._batch_embed_http2_client is not None
            and not self._batch_embed_http2_client.is_closed
        ):
            return self._batch_embed_http2_client
        try:
            import h2  # noqa: F401

            use_http2 = True
        except ImportError:
            use_http2 = False
        h2_client = httpx.AsyncClient(
            verify=system_ssl_context(),
            http2=use_http2,
            timeout=httpx.Timeout(self.settings.VERTEX_REQUEST_TIMEOUT_SECONDS),
            limits=httpx.Limits(
                max_connections=256,
                max_keepalive_connections=192,
            ),
            follow_redirects=True,
            trust_env=True,
        )
        _wrap_client_transports(
            h2_client,
            ProviderHttpAsyncTransport,
            boundary="vertex_model_httpx_async",
            provider="google_vertex_ai",
        )
        self._batch_embed_http2_client = h2_client
        return self._batch_embed_http2_client

    async def _embed_single_http2(
        self,
        formatted_content: str,
        output_dimensionality: int,
    ) -> EmbeddingResult:
        location = str(self.settings.GOOGLE_CLOUD_LOCATION or "global").strip()
        host = (
            "aiplatform.googleapis.com"
            if location == "global"
            else f"{location}-aiplatform.googleapis.com"
        )
        model_name = self.settings.VERTEX_EMBEDDING_MODEL
        url = (
            f"https://{host}/v1/projects/{self._project}/locations/{location}"
            f"/publishers/google/models/{model_name}:embedContent"
        )
        h2_client = self._get_batch_http2_client()
        max_attempts = 6
        started = time.perf_counter()
        payload = {
            "content": {
                "role": "user",
                "parts": [{"text": formatted_content}],
            },
            "outputDimensionality": output_dimensionality,
        }
        data: dict[str, Any] = {}
        for attempt in range(max_attempts):
            self._ensure_async_model_capacity()
            token = await self._get_valid_bearer_token()
            started = time.perf_counter()
            try:
                resp = await h2_client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    break
                if resp.status_code in {429, 408, 500, 502, 503, 504} and attempt + 1 < max_attempts:
                    await asyncio.sleep(0.5 * (2**attempt) + random.uniform(0.0, 0.25))
                    continue
                if resp.status_code == 401 and attempt + 1 < max_attempts:
                    self._token_refreshed_at = None
                    await asyncio.sleep(0.05 * (attempt + 1))
                    continue
                if resp.status_code == 429:
                    raise VertexQuotaError("Vertex AI embedding quota exceeded.", status_code=429)
                if resp.status_code == 403:
                    raise VertexPermissionError("Vertex AI embedding permission denied.", status_code=403)
                if resp.status_code == 401:
                    raise VertexAuthenticationError("Vertex AI embedding authentication failed.", status_code=401)
                if resp.status_code in {400, 404}:
                    raise VertexModelError(
                        f"Vertex AI embedding model error ({resp.status_code}).",
                        status_code=resp.status_code,
                    )
                raise VertexNetworkError(
                    f"Vertex AI embedding HTTP {resp.status_code}.",
                    status_code=resp.status_code,
                )
            except ProviderHttpAttemptBudgetExceeded:
                raise
            except VertexAIError:
                raise
            except Exception as error:
                mapped = _mapped_error(error)
                if isinstance(mapped, (VertexQuotaError, VertexNetworkError)) and attempt + 1 < max_attempts:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                raise mapped from None

        raw_values = (data.get("embedding") or {}).get("values") or []
        values = tuple(float(v) for v in raw_values)
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
            metadata=self._metadata(model_name, started),
        )

    async def embed_documents_batch(
        self,
        items: Sequence[tuple[str, str | None]],
        *,
        output_dimensionality: int,
    ) -> list[EmbeddingResult]:
        if not 128 <= output_dimensionality <= 3072:
            raise ValueError("output_dimensionality must be between 128 and 3072")
        if not items:
            return []
        formatted = [
            f"title: {title or 'none'} | text: {text}" for text, title in items
        ]
        # Multimodal `gemini-embedding-2` on Vertex AI accepts 1 content per `:embedContent`
        # request (`list[str]` is treated by google-genai as a single multi-part Content).
        # Multiplex up to 64 items concurrently over HTTP/2 keep-alive connections!
        if (
            self._uses_default_client_factory
            and "gemini-embedding-2" in str(self.settings.VERTEX_EMBEDDING_MODEL)
        ):
            self._get_client()
            await self._get_valid_bearer_token()
            results: list[EmbeddingResult] = []
            for offset in range(0, len(formatted), 64):
                batch = formatted[offset : offset + 64]
                batch_res = await asyncio.gather(
                    *(
                        self._embed_single_http2(text_item, output_dimensionality)
                        for text_item in batch
                    )
                )
                results.extend(batch_res)
            return results

        results = []
        for offset in range(0, len(formatted), 64):
            batch = formatted[offset : offset + 64]
            results.extend(
                await self._embed_contents_batch(batch, output_dimensionality)
            )
        return results

    async def _embed_contents_batch(
        self,
        contents_list: list[str],
        output_dimensionality: int,
    ) -> list[EmbeddingResult]:
        client = self._get_client()
        response = None
        started = time.perf_counter()
        max_attempts = 4
        for attempt in range(max_attempts):
            self._ensure_async_model_capacity()
            started = time.perf_counter()
            try:
                response = await client.aio.models.embed_content(
                    model=self.settings.VERTEX_EMBEDDING_MODEL,
                    contents=contents_list,
                    config=types.EmbedContentConfig(
                        output_dimensionality=output_dimensionality,
                    ),
                )
                break
            except ProviderHttpAttemptBudgetExceeded:
                raise
            except Exception as error:
                mapped = _mapped_error(error)
                if (
                    isinstance(mapped, VertexModelError)
                    and mapped.status_code == 400
                    and len(contents_list) > 1
                ):
                    mid = len(contents_list) // 2
                    left = await self._embed_contents_batch(
                        contents_list[:mid],
                        output_dimensionality,
                    )
                    right = await self._embed_contents_batch(
                        contents_list[mid:],
                        output_dimensionality,
                    )
                    return [*left, *right]
                if (
                    isinstance(mapped, (VertexQuotaError, VertexNetworkError))
                    and attempt + 1 < max_attempts
                ):
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                raise mapped from None

        embeddings = getattr(response, "embeddings", None) or []
        if len(embeddings) != len(contents_list):
            raise VertexInvalidResponseError(
                "Vertex AI returned mismatched batch embedding count."
            )
        meta = self._metadata(self.settings.VERTEX_EMBEDDING_MODEL, started)
        batch_results: list[EmbeddingResult] = []
        for item in embeddings:
            values = tuple(
                float(value)
                for value in (getattr(item, "values", None) or [])
            )
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
            batch_results.append(
                EmbeddingResult(
                    values=values,
                    output_dimensionality=output_dimensionality,
                    l2_norm=norm,
                    metadata=meta,
                )
            )
        return batch_results

    async def _embed(
        self,
        content: str,
        output_dimensionality: int,
    ) -> EmbeddingResult:
        if not 128 <= output_dimensionality <= 3072:
            raise ValueError("output_dimensionality must be between 128 and 3072")
        self._ensure_async_model_capacity()
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
        except ProviderHttpAttemptBudgetExceeded:
            raise
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
    if get_settings().USE_LEGACY_FREE_PIPELINE:
        raise VertexDisabledError(
            "Google Cloud is disabled by USE_LEGACY_FREE_PIPELINE."
        )
    if _provider is None:
        _provider = VertexAIProvider()
    return _provider


async def close_vertex_provider(
    provider: VertexAIProvider | None = None,
) -> None:
    global _provider
    target = provider or _provider
    if target is None:
        return
    await target.close()
    if target is _provider:
        _provider = None
