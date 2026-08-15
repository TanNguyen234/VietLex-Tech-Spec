from __future__ import annotations

import hashlib
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
    technical_error: Optional[str]
    observed_provider: str
    ragas_mode: str
    ragas_selected: bool
    ragas_executed: bool
    ragas_status: str
    ragas_proxy_faithfulness: Optional[float] = None
    ragas_proxy_answer_relevance: Optional[float] = None
    ragas_proxy_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


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
    technical_error: Optional[str] = None,
) -> OnlineOperationalMetrics:
    """
    Constructs a provider-free operational metrics record containing ONLY observable facts.
    - citation_count is an observable token/regex count (not legal validity).
    - context_count is an observable list length (not retrieval recall).
    - no_evidence is an observable status (not legal correctness).
    - observed_provider is explicitly recorded or 'unobserved'/'unknown' (never inferred from config).
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

    # Provider observation: strictly observed or explicit unobserved/unknown
    if observed_provider and str(observed_provider).strip():
        final_provider = str(observed_provider).strip()
    else:
        final_provider = "unobserved"

    # Ragas sampling & status
    ragas_selected = False
    ragas_executed = False
    if ragas_mode == "off":
        ragas_status = "disabled"
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
        technical_error=technical_error,
        observed_provider=final_provider,
        ragas_mode=ragas_mode,
        ragas_selected=ragas_selected,
        ragas_executed=ragas_executed,
        ragas_status=ragas_status,
    )
