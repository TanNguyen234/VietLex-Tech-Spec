"""Run three bounded, live Vertex/Qdrant natural-language diagnostics.

This is an opt-in harness. It calls the online RAG services directly, so it
does not create a browser session, invoke semantic cache, write application
state, run a judge, or run OCR. Vertex calls are counted at the SDK's injected
HTTPX transport before the network request is sent.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import sys
import threading
from typing import Any, Callable, Iterator
from urllib.parse import urlsplit, urlunsplit
import uuid

import httpx


HARD_MAX_VERTEX_REQUESTS = 12
DEFAULT_MAX_VERTEX_REQUESTS = 6
DEFAULT_OUTPUT_ROOT = Path("docs/evaluation/runs")
VERTEX_HOST_SUFFIX = "aiplatform.googleapis.com"

_TOKEN_RE = re.compile(
    r"(?i)(?:bearer\s+|access[_-]?token[=:]\s*|api[_-]?key[=:]\s*)[^\s,;]+"
)
_PEM_RE = re.compile(
    r"-----BEGIN [^-]+-----.*?-----END [^-]+-----", re.DOTALL
)
_JSON_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/)[^\s\"']+\.json", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s\]\)\}\"']+", re.IGNORECASE)
_SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "api-key",
    "x-goog-api-key",
    "access_token",
    "refresh_token",
    "service_account_json",
    "credentials",
    "password",
    "secret",
    "private_key",
    "headers",
    "request_body",
    "raw_prompt",
}
_OMITTED_DIAGNOSTIC_KEYS = {"text", "body", "prompt", "query", "contents"}


@dataclass(frozen=True)
class ProbeCase:
    case_id: str
    question: str


class ProbePreflightError(RuntimeError):
    """A local contract check failed before a live model request."""


class VertexRequestCapExceeded(RuntimeError):
    """Raised before an HTTP request that would exceed the hard cap."""


def probe_cases() -> tuple[ProbeCase, ...]:
    """Fixed ordinary-language cases; none needs a numeric legal answer."""
    return (
        ProbeCase(
            "rental_deposit",
            "Tôi thuê nhà, chủ nhà giữ tiền đặt cọc sau khi tôi đã bàn giao nhà. "
            "Tôi cần biết quyền và nghĩa vụ của mỗi bên như thế nào?",
        ),
        ProbeCase(
            "probationary_work",
            "Tôi đang thử việc nhưng công ty nói không cần trả lương cho thời gian "
            "này. Tôi có được trả lương không, và phải làm gì khi hết thời gian thử việc?",
        ),
        ProbeCase(
            "environmental_permit",
            "Tôi muốn nhập khẩu phế liệu làm nguyên liệu sản xuất. Theo quy định "
            "hiện nay, doanh nghiệp cần đáp ứng điều kiện gì và có phải xin giấy "
            "phép môi trường không?",
        ),
    )


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return str(value)


def _safe_string(value: str) -> str:
    value = _PEM_RE.sub("[REDACTED]", value)
    value = _JSON_PATH_RE.sub("[REDACTED_PATH]", value)
    value = _TOKEN_RE.sub("[REDACTED_TOKEN]", value)

    def strip_url_query(match: re.Match[str]) -> str:
        raw = match.group(0)
        try:
            parts = urlsplit(raw)
            return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        except ValueError:
            return "[REDACTED_URL]"

    return _URL_RE.sub(strip_url_query, value)


def sanitize_artifact_data(value: Any, *, _inside_diagnostic: bool = False) -> Any:
    """Serialize only safe diagnostic data; omit prompts and transport secrets."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif hasattr(value, "__dict__") and not isinstance(value, type):
        value = dict(value.__dict__)

    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized_key = key.casefold().replace("-", "_")
            if normalized_key in _SENSITIVE_KEYS:
                safe[key] = "[REDACTED]"
                continue
            if _inside_diagnostic and normalized_key in _OMITTED_DIAGNOSTIC_KEYS:
                continue
            safe[key] = sanitize_artifact_data(
                item,
                _inside_diagnostic=_inside_diagnostic or key == "retrieval_diagnostics",
            )
        return safe
    if isinstance(value, (list, tuple, set)):
        return [
            sanitize_artifact_data(item, _inside_diagnostic=_inside_diagnostic)
            for item in value
        ]
    if isinstance(value, str):
        return _safe_string(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _safe_string(str(value))


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    encoded = json.dumps(
        sanitize_artifact_data(payload),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=_json_default,
    ).encode("utf-8")
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class VertexRequestLedger:
    """Durably count every Vertex endpoint attempt before transport dispatch."""

    def __init__(
        self,
        path: Path,
        *,
        max_requests: int,
        configured_models: dict[str, str] | None = None,
    ) -> None:
        if not 1 <= max_requests <= HARD_MAX_VERTEX_REQUESTS:
            raise ValueError(
                f"max_requests must be between 1 and {HARD_MAX_VERTEX_REQUESTS}"
            )
        self.path = Path(path)
        self.max_requests = max_requests
        self.configured_models = configured_models or {}
        self._lock = threading.RLock()
        self._payload: dict[str, Any] = {
            "schema_version": 1,
            "provider": "google_vertex_ai",
            "max_vertex_requests": max_requests,
            "actual_vertex_requests": 0,
            "blocked_attempts": 0,
            "attempts": [],
        }
        self.persist()

    @property
    def actual_vertex_requests(self) -> int:
        with self._lock:
            return int(self._payload["actual_vertex_requests"])

    @property
    def blocked_attempts(self) -> int:
        with self._lock:
            return int(self._payload["blocked_attempts"])

    @property
    def attempts(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._payload["attempts"]]

    def begin_attempt(self, request: httpx.Request) -> dict[str, Any]:
        operation, model = _vertex_request_identity(
            request,
            configured_models=self.configured_models,
        )
        with self._lock:
            if self._payload["actual_vertex_requests"] >= self.max_requests:
                self._payload["blocked_attempts"] += 1
                self._payload["last_blocked_attempt"] = {
                    "timestamp_utc": _utc_now(),
                    "operation": operation,
                    "model": model,
                    "reason": "hard_request_cap_reached",
                }
                self.persist()
                raise VertexRequestCapExceeded(
                    "Vertex HTTP request was blocked by the configured cap."
                )
            attempt_number = int(self._payload["actual_vertex_requests"]) + 1
            entry = {
                "attempt": attempt_number,
                "timestamp_utc": _utc_now(),
                "provider": "google_vertex_ai",
                "operation": operation,
                "model": model,
                "method": request.method,
                "status": "in_flight",
                "http_status": None,
                "transport_error_type": None,
            }
            self._payload["actual_vertex_requests"] = attempt_number
            self._payload["attempts"].append(entry)
            self.persist()
            return entry

    def finish_attempt(
        self,
        entry: dict[str, Any],
        *,
        response: httpx.Response | None = None,
        error: BaseException | None = None,
    ) -> None:
        with self._lock:
            if response is not None:
                entry["http_status"] = response.status_code
                entry["status"] = (
                    "http_success" if response.is_success else "http_error"
                )
            elif error is not None:
                entry["status"] = "transport_error"
                entry["transport_error_type"] = type(error).__name__
            self.persist()

    def persist(self) -> None:
        with self._lock:
            _atomic_write_json(self.path, self._payload)


def _vertex_request_identity(
    request: httpx.Request,
    *,
    configured_models: dict[str, str],
) -> tuple[str, str]:
    path = request.url.path
    operation = "other_vertex"
    model = "unidentified"
    last_segment = path.rsplit("/", 1)[-1]
    if ":" in last_segment:
        model_from_path, operation_from_path = last_segment.rsplit(":", 1)
        operation = operation_from_path
        if re.fullmatch(r"[A-Za-z0-9._-]{1,100}", model_from_path):
            model = model_from_path
    if operation == "embedContent":
        model = configured_models.get("embedding", model)
    elif operation == "generateContent":
        model = configured_models.get("generation", model)
    return operation, model


class VertexAttemptTransport(httpx.AsyncBaseTransport):
    """Count only Vertex model HTTP requests and delegate all other traffic."""

    def __init__(
        self,
        ledger: VertexRequestLedger,
        inner: httpx.AsyncBaseTransport,
    ) -> None:
        self.ledger = ledger
        self.inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = (request.url.host or "").casefold()
        if not host.endswith(VERTEX_HOST_SUFFIX):
            return await self.inner.handle_async_request(request)
        entry = self.ledger.begin_attempt(request)
        try:
            response = await self.inner.handle_async_request(request)
        except BaseException as error:
            self.ledger.finish_attempt(entry, error=error)
            raise
        self.ledger.finish_attempt(entry, response=response)
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


def vertex_only_generation(
    generate: Callable[..., Any],
) -> Callable[..., Any]:
    """Wrap the existing LLM adapter with no retries and no provider fallback."""
    async def call(*args: Any, **kwargs: Any) -> Any:
        kwargs["allow_fallback"] = False
        kwargs["max_retries"] = 0
        return await generate(*args, **kwargs)

    return call


@contextmanager
def serverless_probe_settings(settings: Any) -> Iterator[None]:
    """Apply only in-process online-only/no-judge/no-retry overrides."""
    if bool(getattr(settings, "USE_LEGACY_FREE_PIPELINE", False)):
        raise ProbePreflightError(
            "legacy pipeline is selected; refusing to cross-fallback to Vertex"
        )
    updates = {
        "SERVERLESS_ONLINE_ONLY": True,
        "RAGAS_EVALUATION_MODE": "off",
        "VERTEX_MAX_RETRIES": 0,
    }
    missing = [name for name in updates if not hasattr(settings, name)]
    if missing:
        raise ProbePreflightError(
            "runtime settings are missing required fields: " + ", ".join(missing)
        )
    previous = {name: getattr(settings, name) for name in updates}
    try:
        for name, value in updates.items():
            setattr(settings, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(settings, name, value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _credential_presence(settings: Any) -> dict[str, bool]:
    env_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    service_json_present = bool(os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"))
    dotenv_path_present = False
    if "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ:
        try:
            from dotenv import dotenv_values, find_dotenv

            dotenv_path = find_dotenv(usecwd=True)
            if dotenv_path:
                dotenv_path_present = bool(
                    dotenv_values(dotenv_path).get(
                        "GOOGLE_APPLICATION_CREDENTIALS"
                    )
                )
        except Exception:
            # Keep credential paths and parser errors out of the manifest.
            dotenv_path_present = False
    default_file = False
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            default_file = (
                Path(appdata) / "gcloud" / "application_default_credentials.json"
            ).is_file()
    else:
        default_file = (
            Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
        ).is_file()
    return {
        "google_cloud_project_configured": bool(
            getattr(settings, "GOOGLE_CLOUD_PROJECT", None)
        ),
        "adc_path_env_present": bool(env_path),
        "adc_dotenv_path_present": dotenv_path_present,
        "service_account_json_env_present": service_json_present,
        "default_adc_file_present": default_file,
    }


def _safe_runtime_configuration(settings: Any, max_requests: int) -> dict[str, Any]:
    values = {
        "runtime_contract": "vertex_qdrant_v3",
        "serverless_online_only": True,
        "legacy_pipeline_selected": bool(settings.USE_LEGACY_FREE_PIPELINE),
        "qdrant_collection": settings.VERTEX_QDRANT_COLLECTION_NAME,
        "qdrant_vector_size": settings.VERTEX_QDRANT_VECTOR_SIZE,
        "embedding_model": settings.VERTEX_EMBEDDING_MODEL,
        "generation_model": settings.VERTEX_LLM_MODEL,
        "google_cloud_location": settings.GOOGLE_CLOUD_LOCATION,
        "vertex_max_retries": 0,
        "chat_official_supplement_enabled": bool(
            getattr(settings, "CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED", False)
        ),
        "official_web_research_enabled": bool(
            getattr(settings, "OFFICIAL_WEB_RESEARCH_ENABLED", False)
        ),
        "official_brave_search_enabled": bool(
            getattr(settings, "OFFICIAL_BRAVE_SEARCH_ENABLED", False)
        ),
        "semantic_cache": "not_invoked",
        "judges": "off",
        "ocr": "not_invoked",
        "persistent_application_writes": "none",
        "max_vertex_requests": max_requests,
        "dataset": {
            "repository": settings.DATASET_REPOSITORY,
            "revision": settings.DATASET_REVISION,
            "expected_document_count": settings.EXPECTED_DOCUMENT_COUNT,
            "dataset_sha256": None,
            "dataset_sha256_status": "not_applicable_online_remote_read",
        },
    }
    return sanitize_artifact_data(values)


def _runtime_fingerprint(config: dict[str, Any]) -> str:
    encoded = json.dumps(config, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _configured_command(args: argparse.Namespace) -> str:
    return (
        "python scripts/probe_natural_rag.py --allow-live "
        f"--max-vertex-requests {args.max_vertex_requests}"
    )


def _run_provenance(root: Path) -> dict[str, Any]:
    from app.evaluation.provenance import collect_git_provenance

    provenance = collect_git_provenance(root)
    return {
        "status": provenance.status,
        "git_sha": provenance.git_sha,
        "git_dirty": provenance.git_dirty,
        "git_tracked_dirty": provenance.git_tracked_dirty,
        "git_staged_dirty": provenance.git_staged_dirty,
        "git_untracked_dirty": provenance.git_untracked_dirty,
        "git_diff_sha256": provenance.git_diff_sha256,
        "git_diff_status": provenance.git_diff_status,
        "git_diff_reason": provenance.git_diff_reason,
        "source_state_sha256": provenance.source_state_sha256,
    }


def _live_provenance_is_usable(provenance: dict[str, Any]) -> bool:
    if provenance.get("status") != "ok":
        return False
    git_dirty = provenance.get("git_dirty")
    if not isinstance(git_dirty, bool):
        return False
    if not git_dirty:
        return True
    return all(
        isinstance(provenance.get(key), str)
        and re.fullmatch(r"[0-9a-f]{64}", provenance[key]) is not None
        for key in ("git_diff_sha256", "source_state_sha256")
    )


def _vertex_failure_in_exception(error: BaseException | None) -> bool:
    if error is None:
        return False
    try:
        from app.services.vertex_ai import VertexAIError
    except Exception:
        return False

    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, VertexAIError):
            return True
        for nested in (
            getattr(current, "__cause__", None),
            getattr(current, "__context__", None),
        ):
            if isinstance(nested, BaseException):
                pending.append(nested)
        nested_errors = getattr(current, "exceptions", ())
        if isinstance(nested_errors, tuple):
            pending.extend(
                item for item in nested_errors if isinstance(item, BaseException)
            )
    return False


def _case_has_vertex_failure(
    *,
    error: BaseException | None,
    latency: dict[str, Any],
    ledger: VertexRequestLedger,
    attempts_before_case: int,
) -> bool:
    if _vertex_failure_in_exception(error):
        return True
    if any(
        attempt.get("status") != "http_success"
        for attempt in ledger.attempts[attempts_before_case:]
    ):
        return True
    provider_usage = latency.get("provider_usage")
    answer_usage = (
        provider_usage.get("answer_generation")
        if isinstance(provider_usage, dict)
        else None
    )
    return bool(
        isinstance(answer_usage, dict)
        and answer_usage.get("provider") == "google_vertex_ai"
        and (
            answer_usage.get("primary_error_kind")
            or answer_usage.get("status") not in (None, "success")
        )
    )


def _case_has_retrieval_failure(
    error: BaseException | None,
    latency: dict[str, Any],
) -> bool:
    status = latency.get("retrieval_status") or getattr(error, "status", None)
    return status in {"retrieval_error", "reranker_error", "partial_retrieval_error"}


async def _run_probe_cases(
    run_case: Callable[[ProbeCase], Any],
    ledger: VertexRequestLedger,
    *,
    max_requests: int,
    on_result: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Run cases sequentially and stop as soon as Vertex reports a failure."""
    import time

    results: list[dict[str, Any]] = []
    stop_reason: str | None = None
    for case in probe_cases():
        started = time.perf_counter()
        attempts_before_case = len(ledger.attempts)
        answer: str | None = None
        contexts: list[str] = []
        latency: dict[str, Any] = {}
        case_error: BaseException | None = None
        try:
            answer, contexts, latency = await run_case(case)
        except Exception as error:
            case_error = error
            latency = _case_latency_from_error(error)
        result = _case_result(
            case,
            started=started,
            answer=answer,
            contexts=contexts,
            latency=latency,
            error=case_error,
        )
        results.append(result)
        if on_result is not None:
            on_result(result)

        if _case_has_retrieval_failure(case_error, latency):
            stop_reason = "retrieval_pipeline_error"
            break
        if _case_has_vertex_failure(
            error=case_error,
            latency=latency,
            ledger=ledger,
            attempts_before_case=attempts_before_case,
        ):
            stop_reason = "vertex_provider_error"
            break
        if ledger.blocked_attempts:
            stop_reason = "vertex_request_cap_intercepted"
            break
        if ledger.actual_vertex_requests >= max_requests:
            stop_reason = "vertex_request_cap_reached"
            break
    return results, stop_reason


def _usage_summary(latency: dict[str, Any]) -> dict[str, Any]:
    usage = latency.get("provider_usage")
    if not isinstance(usage, dict):
        return {}
    safe_usage: dict[str, Any] = {}
    for stage in ("query_rewrite", "answer_generation", "guardrails"):
        stage_usage = usage.get(stage)
        if not isinstance(stage_usage, dict):
            continue
        allowed = {
            "provider",
            "model",
            "observed",
            "status",
            "latency_ms",
            "prompt_token_count",
            "output_token_count",
            "thought_token_count",
            "total_token_count",
            "fallback_used",
            "primary_error_kind",
        }
        safe_usage[stage] = {
            key: value
            for key, value in stage_usage.items()
            if key in allowed
        }
    return sanitize_artifact_data(safe_usage)


def _case_result(
    case: ProbeCase,
    *,
    started: float,
    answer: str | None,
    contexts: list[str],
    latency: dict[str, Any],
    error: BaseException | None,
) -> dict[str, Any]:
    try:
        import time

        elapsed = round(time.perf_counter() - started, 3)
    except Exception:
        elapsed = None
    diagnostics = latency.get("retrieval_diagnostics", {})
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    timing_values = {
        key: value
        for key, value in latency.items()
        if key.startswith("t_") and isinstance(value, (float, int))
    }
    generation_status = latency.get("generation_status")
    retrieval_status = latency.get("retrieval_status")
    if error is not None:
        case_status = "technical_error"
    elif generation_status == "no_contexts":
        case_status = "no_evidence"
    elif generation_status in (None, "success", "completed"):
        case_status = "completed"
    else:
        case_status = str(generation_status)
    result = {
        "case_id": case.case_id,
        "question": case.question,
        "status": case_status,
        "answer": answer,
        "evidence": contexts,
        "evidence_count": len(contexts),
        "retrieval_status": retrieval_status,
        "retrieval_diagnostics": diagnostics,
        "generation_status": generation_status,
        "actual_provider_model_usage": _usage_summary(latency),
        "timings_seconds": {
            **timing_values,
            "harness_case_elapsed": elapsed,
        },
    }
    if error is not None:
        result["error_type"] = type(error).__name__
    return sanitize_artifact_data(result)


def _report_markdown(
    results: list[dict[str, Any]],
    ledger: VertexRequestLedger,
    stop_reason: str | None,
) -> str:
    lines = [
        "# Natural-language RAG diagnostic",
        "",
        "Live, bounded diagnostics only. These observations do not establish legal correctness or production readiness.",
        "",
        f"Vertex model HTTP attempts: {ledger.actual_vertex_requests}/{ledger.max_requests}.",
        f"Attempts blocked at the hard cap: {ledger.blocked_attempts}.",
        "",
        "| Case | Status | Retrieval | Generation | Evidence contexts |",
        "| --- | --- | --- | --- | ---: |",
    ]
    for result in results:
        lines.append(
            "| {case_id} | {status} | {retrieval} | {generation} | {evidence} |".format(
                case_id=result.get("case_id", "unknown"),
                status=result.get("status", "unknown"),
                retrieval=result.get("retrieval_status") or "unknown",
                generation=result.get("generation_status") or "not_called",
                evidence=result.get("evidence_count", 0),
            )
        )
    if stop_reason:
        lines.extend(["", f"Stop reason: `{stop_reason}`."])
    if results and all(
        item.get("generation_status") == "no_contexts" for item in results
    ):
        lines.extend(
            [
                "",
                "No answer-generation call was made because retrieval and the online supplement returned no usable evidence.",
            ]
        )
    lines.extend(["", "Oracle: none. No LLM judge or quality score was run.", ""])
    return "\n".join(lines)


def _verify_genai_transport_boundary() -> dict[str, Any]:
    """Fail closed unless installed google-genai exposes the inspected hook."""
    try:
        from google import genai
        from google.genai import types
        import google.genai._api_client as api_client
    except Exception as error:
        raise ProbePreflightError(
            f"google-genai is unavailable ({type(error).__name__})"
        ) from None

    if "httpx_async_client" not in types.HttpOptions.model_fields:
        raise ProbePreflightError(
            "google-genai does not expose HttpOptions.httpx_async_client"
        )
    if "attempts" not in types.HttpRetryOptions.model_fields:
        raise ProbePreflightError(
            "google-genai does not expose HttpRetryOptions.attempts"
        )
    request_source = inspect.getsource(api_client.BaseApiClient._async_request_once)
    constructor_source = inspect.getsource(api_client.BaseApiClient.__init__)
    if "self._async_httpx_client.send" not in request_source:
        raise ProbePreflightError(
            "google-genai async request path no longer uses the inspected HTTPX client"
        )
    if "self._async_httpx_client = self._http_options.httpx_async_client" not in constructor_source:
        raise ProbePreflightError(
            "google-genai no longer installs the injected HTTPX client"
        )
    return {
        "google_genai_version": getattr(genai, "__version__", "unknown"),
        "transport_hook": "HttpOptions.httpx_async_client",
        "http_attempt_boundary": "BaseApiClient._async_request_once HTTPX send",
        "default_retry_suppression": "HttpRetryOptions(attempts=1)",
    }


def _make_client_factory(
    ledger: VertexRequestLedger,
    *,
    created_clients: list[httpx.AsyncClient],
) -> Callable[..., Any]:
    from google import genai
    from google.genai import types

    from app.config import system_ssl_context

    def factory(**kwargs: Any) -> Any:
        options = kwargs.get("http_options")
        if options is None or not hasattr(options, "model_copy"):
            raise ProbePreflightError(
                "Vertex provider did not construct typed HTTP options"
            )
        inner = httpx.AsyncHTTPTransport(
            verify=system_ssl_context(),
            retries=0,
        )
        transport = VertexAttemptTransport(ledger, inner)
        async_client = httpx.AsyncClient(transport=transport)
        created_clients.append(async_client)
        kwargs["http_options"] = options.model_copy(
            update={
                "httpx_async_client": async_client,
                "retry_options": types.HttpRetryOptions(attempts=1),
            }
        )
        return genai.Client(**kwargs)

    return factory


def _case_latency_from_error(error: BaseException) -> dict[str, Any]:
    latency = getattr(error, "latency", None)
    return latency if isinstance(latency, dict) else {}


def _create_run_directory(root: Path, fingerprint: str) -> tuple[str, Path]:
    from app.evaluation.run_manifest import prepare_run_directory

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    for _ in range(5):
        run_id = f"natural-rag-{stamp}-{fingerprint[:8]}-{uuid.uuid4().hex[:6]}"
        try:
            return run_id, prepare_run_directory(root, run_id)
        except FileExistsError:
            continue
    raise RuntimeError("unable to allocate a unique live run directory")


async def run_live_probe(args: argparse.Namespace) -> Path:
    """Execute the fixed online-only cases and write a unique diagnostic run."""
    from app.config import get_settings
    from app.services import vertex_ai

    max_requests = int(args.max_vertex_requests)
    if not 1 <= max_requests <= HARD_MAX_VERTEX_REQUESTS:
        raise ProbePreflightError(
            f"request cap must be between 1 and {HARD_MAX_VERTEX_REQUESTS}"
        )

    settings = get_settings()
    if settings.USE_LEGACY_FREE_PIPELINE:
        raise ProbePreflightError(
            "legacy pipeline is selected; refusing to cross-fallback to Vertex"
        )
    sdk_boundary = _verify_genai_transport_boundary()
    runtime_config = _safe_runtime_configuration(settings, max_requests)
    config_fingerprint = _runtime_fingerprint(runtime_config)
    run_id, run_dir = _create_run_directory(
        Path(args.output_root).resolve(), config_fingerprint
    )
    run_root = Path.cwd().resolve()
    provenance: dict[str, Any]
    try:
        provenance = _run_provenance(run_root)
    except Exception as error:
        provenance = {
            "status": "unavailable",
            "error_type": type(error).__name__,
            "git_sha": "unknown",
            "git_dirty": None,
            "git_diff_sha256": None,
            "source_state_sha256": None,
        }

    command = _configured_command(args)
    credential_presence = _credential_presence(settings)
    ledger = VertexRequestLedger(
        run_dir / "attempt_ledger.json",
        max_requests=max_requests,
        configured_models={
            "embedding": settings.VERTEX_EMBEDDING_MODEL,
            "generation": settings.VERTEX_LLM_MODEL,
        },
    )
    raw_results: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "evidence_level": "live",
        "status": "in_progress",
        "cases": [],
    }
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at_utc": _utc_now(),
        "status": "in_progress",
        "evidence_level": "live",
        "command": command,
        "git_sha": provenance.get("git_sha"),
        "git_dirty": provenance.get("git_dirty"),
        "git_diff_sha256": provenance.get("git_diff_sha256"),
        "source_state_sha256": provenance.get("source_state_sha256"),
        "git_provenance": provenance,
        "dataset_revision": runtime_config["dataset"]["revision"],
        "dataset_configuration_fingerprint": _runtime_fingerprint(
            runtime_config["dataset"]
        ),
        "dataset_sha256": None,
        "dataset_sha256_status": runtime_config["dataset"][
            "dataset_sha256_status"
        ],
        "configuration_fingerprint": config_fingerprint,
        "configuration": runtime_config,
        "configured_provider_models": {
            "retrieval_embedding": settings.VERTEX_EMBEDDING_MODEL,
            "answer_generation": settings.VERTEX_LLM_MODEL,
            "retrieval_collection": settings.VERTEX_QDRANT_COLLECTION_NAME,
        },
        "credential_presence": credential_presence,
        "sdk_transport_preflight": sdk_boundary,
        "case_ids": [case.case_id for case in probe_cases()],
        "max_vertex_requests": max_requests,
        "oracle": "none",
        "judge": "off",
    }
    _atomic_write_json(run_dir / "configuration.json", runtime_config)
    _atomic_write_json(run_dir / "raw_results.json", raw_results)
    _atomic_write_json(run_dir / "manifest.json", manifest)

    stop_reason: str | None = None
    created_clients: list[httpx.AsyncClient] = []
    original_vertex_provider = vertex_ai._provider
    retrieval_backends = None
    rag_pipeline = None
    original_generation_call = None
    provider = None
    try:
        if not _live_provenance_is_usable(provenance):
            raise ProbePreflightError(
                "Git provenance is unavailable or incomplete; refusing live requests"
            )
        if not credential_presence["google_cloud_project_configured"]:
            raise ProbePreflightError("Google Cloud project is not configured")
        if not any(
            credential_presence[key]
            for key in (
                "adc_path_env_present",
                "adc_dotenv_path_present",
                "service_account_json_env_present",
                "default_adc_file_present",
            )
        ):
            raise ProbePreflightError(
                "no local ADC credential source was found"
            )

        with serverless_probe_settings(settings):
            import logfire

            # Instrumented app services may be imported below; do not export
            # their prompts, retrieved passages, or errors to a telemetry sink.
            logfire.configure(send_to_logfire=False, console=False)

            from app.evaluation import retrieval_backends
            from app.services import rag_pipeline

            retrieval_backends.get_vertex_qdrant_retriever.cache_clear()
            provider = vertex_ai.VertexAIProvider(
                settings=settings,
                client_factory=_make_client_factory(
                    ledger,
                    created_clients=created_clients,
                ),
            )
            vertex_ai._provider = provider
            original_generation_call = rag_pipeline.generate_llm_response_with_metadata
            rag_pipeline.generate_llm_response_with_metadata = vertex_only_generation(
                original_generation_call
            )

            def save_case_result(result: dict[str, Any]) -> None:
                raw_results["cases"].append(result)
                _atomic_write_json(run_dir / "raw_results.json", raw_results)

            async def run_case(case: ProbeCase):
                return await rag_pipeline.run_advanced_rag(
                    case.question,
                    rewrite_mode="off",
                )

            case_results, stop_reason = await _run_probe_cases(
                run_case,
                ledger,
                max_requests=max_requests,
                on_result=save_case_result,
            )
            raw_results["cases"] = case_results
    except ProbePreflightError as error:
        stop_reason = f"preflight_failed:{type(error).__name__}"
        manifest["preflight_error_type"] = type(error).__name__
    except BaseException as error:
        stop_reason = f"harness_failed:{type(error).__name__}"
        manifest["harness_error_type"] = type(error).__name__
    finally:
        if rag_pipeline is not None and original_generation_call is not None:
            rag_pipeline.generate_llm_response_with_metadata = original_generation_call
        if retrieval_backends is not None:
            retrieval_backends.get_vertex_qdrant_retriever.cache_clear()
        vertex_ai._provider = original_vertex_provider
        if provider is not None and provider._client is not None:
            try:
                await provider._client.aio.aclose()
            except Exception:
                pass
            try:
                provider._client.close()
            except Exception:
                pass
        for client in created_clients:
            if not client.is_closed:
                await client.aclose()

    if not raw_results["cases"]:
        if stop_reason and stop_reason.startswith("preflight_failed"):
            evidence_level = "NOT RUN"
            status = "preflight_failed"
        else:
            evidence_level = "NOT RUN"
            status = "failed_before_first_case"
    else:
        evidence_level = "live" if ledger.actual_vertex_requests else "NOT RUN"
        status = "completed" if stop_reason is None else "stopped"
    if (
        raw_results["cases"]
        and all(
            item.get("generation_status") == "no_contexts"
            for item in raw_results["cases"]
        )
    ):
        stop_reason = stop_reason or "no_evidence_prevented_answer_generation"
    raw_results.update(
        {
            "status": status,
            "evidence_level": evidence_level,
            "stop_reason": stop_reason,
        }
    )
    manifest.update(
        {
            "completed_at_utc": _utc_now(),
            "status": status,
            "evidence_level": evidence_level,
            "stop_reason": stop_reason,
            "actual_vertex_requests": ledger.actual_vertex_requests,
            "blocked_vertex_attempts": ledger.blocked_attempts,
            "actual_provider_operations": {
                operation: sum(
                    item.get("operation") == operation
                    for item in ledger.attempts
                )
                for operation in ("embedContent", "generateContent", "other_vertex")
            },
            "answer_generation_observed": any(
                result.get("actual_provider_model_usage", {})
                .get("answer_generation", {})
                .get("observed")
                for result in raw_results["cases"]
            ),
            "legal_quality_claim": False,
        }
    )
    _atomic_write_json(run_dir / "raw_results.json", raw_results)
    _atomic_write_json(run_dir / "manifest.json", manifest)
    (run_dir / "report.md").write_text(
        _report_markdown(raw_results["cases"], ledger, stop_reason),
        encoding="utf-8",
    )
    return run_dir


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run three fixed live natural-language RAG probes against the "
            "online-only Vertex/Qdrant v3 runtime. No request is sent without --allow-live."
        )
    )
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="authorize the fixed read-only Qdrant/Supabase probes and Vertex model calls",
    )
    parser.add_argument(
        "--max-vertex-requests",
        type=int,
        default=DEFAULT_MAX_VERTEX_REQUESTS,
        help=f"hard cap for actual Vertex HTTP attempts (1-{HARD_MAX_VERTEX_REQUESTS}; default: {DEFAULT_MAX_VERTEX_REQUESTS})",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="parent directory for a new unique run artifact",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.allow_live:
        parser.error("live execution requires explicit --allow-live")
    if not 1 <= args.max_vertex_requests <= HARD_MAX_VERTEX_REQUESTS:
        parser.error(
            f"--max-vertex-requests must be between 1 and {HARD_MAX_VERTEX_REQUESTS}"
        )
    run_dir = asyncio.run(run_live_probe(args))
    print(f"run_artifact={run_dir.as_posix()}")
    exit_code = 1
    try:
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        print(
            "status={status} evidence_level={evidence_level} "
            "vertex_requests={actual_vertex_requests}/{max_vertex_requests}".format(
                status=manifest.get("status"),
                evidence_level=manifest.get("evidence_level"),
                actual_vertex_requests=manifest.get("actual_vertex_requests", 0),
                max_vertex_requests=manifest.get("max_vertex_requests", 0),
            )
        )
        exit_code = 0 if manifest.get("status") == "completed" else 1
    except Exception:
        pass
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
