from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional



from app.evaluation.legal_citations import parse_legal_citations


def is_sampled_for_ragas(trace_id: str, sample_rate: float) -> bool:
    """
    Deterministic trace-ID sampling for Ragas evaluation.
    Zero random, zero process-dependent hash(), zero timestamp, zero global state.
    """
    if sample_rate <= 0.0:
        return False
    if sample_rate >= 1.0:
        return True

    # Use pure SHA-256 hash of trace_id
    digest = hashlib.sha256(f"vietlex_ragas_sample:{trace_id}".encode("utf-8")).hexdigest()
    # Normalize the first 8 hex characters (32 bits) to [0.0, 1.0)
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    return bucket < sample_rate


@dataclass(frozen=True)
class OnlineOperationalMetrics:
    trace_id: str
    request_status: str
    latency: Dict[str, float]
    context_count: int
    citation_count: int
    no_evidence: bool
    refusal_category: Optional[str]
    technical_error: Optional[Dict[str, Any] | str]
    observed_provider: str
    observed_model: str
    provider_usage: Dict[str, Any]
    ragas_mode: str
    ragas_selected: bool
    ragas_executed: bool
    ragas_status: str
    ragas_proxy_faithfulness: Optional[float] = None
    ragas_proxy_answer_relevance: Optional[float] = None
    ragas_proxy_error: Optional[Dict[str, Any] | str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def sanitize_error_message(error: Any) -> str:
    """
    Sanitize error message to prevent secret/credential leakage into logs/telemetry.
    Redacts URL query param secrets, Bearer tokens, MongoDB connection URI credentials,
    and actual configured Settings secrets.
    Limits bounded length to 200 characters.
    """
    if error is None:
        return ""
    msg = str(error).strip()
    if not msg:
        return ""

    # 1. Redact query param secrets like ?api_key=..., &key=..., ?token=..., etc.
    query_secret_pattern = r"([?&](?:api[_-]?key|key|token|secret|password|auth|bearer)=)[^&\s]+"
    msg = re.sub(query_secret_pattern, r"\1[REDACTED]", msg, flags=re.IGNORECASE)

    # 2. Redact Authorization header values: Bearer <token>
    bearer_pattern = r"\b(bearer\s+)[a-zA-Z0-9_\-\.]+"
    msg = re.sub(bearer_pattern, r"\1[REDACTED]", msg, flags=re.IGNORECASE)

    # 3. Redact embedded MongoDB URI credentials like mongodb://user:pass@host or mongodb+srv://user:pass@host
    mongo_cred_pattern = r"(mongodb(?:\+srv)?:\/\/[^\s:]+:)([^@\s]+)(@[^\s]+)"
    msg = re.sub(mongo_cred_pattern, r"\1[REDACTED]\3", msg, flags=re.IGNORECASE)

    # 4. Redact known configured secrets from actual Settings
    try:
        from app.config import get_settings
        settings = get_settings()
        configured_secrets = [
            getattr(settings, attr, None)
            for attr in (
                "OPENROUTER_API_KEY",
                "GEMINI_API_KEY",
                "NVIDIA_API_KEY",
                "GROQ_API_KEY",
                "LITELLM_MASTER_KEY",
                "PINECONE_API_KEY",
                "PINECONE_API",
                "PIPECONE_API",
                "QDRANT_API_KEY",
                "MONGO_URL",
                "LOGFIRE_TOKEN",
            )
        ]
        for secret in configured_secrets:
            if secret and isinstance(secret, str) and len(secret) > 4:
                msg = msg.replace(secret, "[REDACTED]")
    except Exception:
        pass

    return msg[:200]


def build_online_metrics(
    trace_id: str,
    *,
    request_status: str = "ok",
    latency: Optional[Dict[str, Any]] = None,
    context_used: Optional[List[str]] = None,
    bot_response: str = "",
    cached: bool = False,
    input_safe: bool = True,
    output_safe: bool = True,
    rejection_reason: Optional[str] = None,
    ragas_mode: str = "off",
    ragas_sample_rate: float = 0.1,
    observed_provider: Optional[str] = None,
    observed_model: Optional[str] = None,
    provider_usage: Optional[Dict[str, Any]] = None,
    technical_error: Optional[Dict[str, Any] | str] = None,
) -> OnlineOperationalMetrics:
    """
    Constructs a provider-free operational metrics record containing ONLY observable facts.
    - citation_count is an observable token/regex count (not legal validity).
    - context_count is an observable list length (not retrieval recall).
    - no_evidence is an observable status (not legal correctness).
    - observed_provider/observed_model and provider_usage are strictly recorded facts (never inferred).
    """
    cleaned_latency: Dict[str, float] = {}
    if latency:
        for k, v in latency.items():
            if isinstance(v, (int, float)):
                cleaned_latency[k] = float(v)

    contexts = context_used or []
    context_count = len(contexts)

    # Observable citation count using deterministic regex parser
    citations = parse_legal_citations(bot_response) if bot_response else []
    citation_count = len(citations)

    # Sanitize technical error
    sanitized_technical_error: Optional[Dict[str, Any] | str] = None
    if technical_error:
        if isinstance(technical_error, dict):
            sanitized_technical_error = dict(technical_error)
            if "message" in sanitized_technical_error:
                sanitized_technical_error["message"] = sanitize_error_message(
                    sanitized_technical_error["message"]
                )
        else:
            sanitized_technical_error = sanitize_error_message(technical_error)

    # Determine no-evidence and refusal category
    no_evidence = False
    refusal_category: Optional[str] = None

    if not input_safe:
        refusal_category = "guardrail_input"
    elif not output_safe:
        refusal_category = "guardrail_output"
    elif request_status == "no_evidence" or (
        not contexts and not cached and input_safe and output_safe and not technical_error
    ):
        no_evidence = True
        refusal_category = "no_evidence"

    # Standardize provider_usage
    default_usage: Dict[str, Any] = {
        "query_rewrite": {
            "provider": "unobserved",
            "model": "unobserved",
            "observed": False,
        },
        "answer_generation": {
            "provider": "unobserved",
            "model": "unobserved",
            "observed": False,
        },
        "guardrails": {
            "provider": "unobserved",
            "model": "unobserved",
            "observed": False,
        },
    }
    if provider_usage and isinstance(provider_usage, dict):
        for stage, info in provider_usage.items():
            if isinstance(info, dict):
                default_usage[stage] = {
                    "provider": str(info.get("provider", "unobserved")),
                    "model": str(info.get("model", "unobserved")),
                    "observed": bool(info.get("observed", False)),
                }

    # Provider & model observation resolution
    if observed_provider and str(observed_provider).strip() and str(observed_provider).strip() != "unobserved":
        final_provider = str(observed_provider).strip()
    elif default_usage["answer_generation"]["observed"] and default_usage["answer_generation"]["provider"] != "unobserved":
        final_provider = default_usage["answer_generation"]["provider"]
    elif default_usage["query_rewrite"]["observed"] and default_usage["query_rewrite"]["provider"] != "unobserved":
        final_provider = default_usage["query_rewrite"]["provider"]
    else:
        final_provider = "unobserved"

    if observed_model and str(observed_model).strip() and str(observed_model).strip() != "unobserved":
        final_model = str(observed_model).strip()
    elif default_usage["answer_generation"]["observed"] and default_usage["answer_generation"]["model"] != "unobserved":
        final_model = default_usage["answer_generation"]["model"]
    elif default_usage["query_rewrite"]["observed"] and default_usage["query_rewrite"]["model"] != "unobserved":
        final_model = default_usage["query_rewrite"]["model"]
    else:
        final_model = "unobserved"

    # Ragas sampling & status
    ragas_selected = False
    ragas_executed = False
    if ragas_mode == "off":
        ragas_status = "disabled"
    elif technical_error or request_status == "technical_error":
        ragas_status = "skipped_technical_error"
    elif not contexts:
        ragas_status = "skipped_no_context"
    elif ragas_mode == "all":
        ragas_selected = True
        ragas_status = "selected"
    elif ragas_mode == "sample":
        ragas_selected = is_sampled_for_ragas(trace_id, ragas_sample_rate)
        ragas_status = "selected" if ragas_selected else "not_selected"
    else:
        ragas_status = "unknown"


    return OnlineOperationalMetrics(
        trace_id=trace_id,
        request_status=request_status,
        latency=cleaned_latency,
        context_count=context_count,
        citation_count=citation_count,
        no_evidence=no_evidence,
        refusal_category=refusal_category,
        technical_error=sanitized_technical_error,
        observed_provider=final_provider,
        observed_model=final_model,
        provider_usage=default_usage,
        ragas_mode=ragas_mode,
        ragas_selected=ragas_selected,
        ragas_executed=ragas_executed,
        ragas_status=ragas_status,
    )
