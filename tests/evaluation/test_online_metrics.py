from app.evaluation.online_metrics import (
    build_online_metrics,
    is_sampled_for_ragas,
)



def test_deterministic_sampling_is_stable_and_pure() -> None:
    trace_id_1 = "00000000-0000-0000-0000-000000000001"
    trace_id_2 = "00000000-0000-0000-0000-000000000002"

    # Stability: same trace_id + sample_rate always returns identical boolean
    decision_1a = is_sampled_for_ragas(trace_id_1, sample_rate=0.5)
    decision_1b = is_sampled_for_ragas(trace_id_1, sample_rate=0.5)
    assert decision_1a == decision_1b

    decision_2a = is_sampled_for_ragas(trace_id_2, sample_rate=0.5)
    decision_2b = is_sampled_for_ragas(trace_id_2, sample_rate=0.5)
    assert decision_2a == decision_2b

    # Edge cases: 0.0 always False, 1.0 always True
    assert is_sampled_for_ragas(trace_id_1, sample_rate=0.0) is False
    assert is_sampled_for_ragas(trace_id_2, sample_rate=0.0) is False
    assert is_sampled_for_ragas(trace_id_1, sample_rate=1.0) is True
    assert is_sampled_for_ragas(trace_id_2, sample_rate=1.0) is True


def test_online_metrics_contain_required_observable_fields() -> None:
    metrics = build_online_metrics(
        trace_id="test-trace-123",
        request_status="ok",
        latency={"t_total": 1.23, "t_retrieval": 0.45, "t_llm": 0.78},
        context_used=["Chunk 1 content citing 12/2026/NĐ-CP Điều 1"],
        bot_response="Theo Nghị định 12/2026/NĐ-CP Điều 1 Khoản 2, cá nhân được miễn thuế.",
        cached=False,
        input_safe=True,
        output_safe=True,
        rejection_reason=None,
        ragas_mode="off",
        observed_provider=None,
    )

    assert metrics.trace_id == "test-trace-123"
    assert metrics.request_status == "ok"
    assert metrics.latency["t_total"] == 1.23
    assert metrics.context_count == 1
    # Observable citation count from response via deterministic regex parser
    assert metrics.citation_count >= 1
    assert metrics.no_evidence is False
    assert metrics.refusal_category is None
    assert metrics.technical_error is None
    # If not explicitly observed from generation, must be 'unobserved' or 'unknown', never inferred from config
    assert metrics.observed_provider in ("unobserved", "unknown")
    assert metrics.observed_model in ("unobserved", "unknown")
    assert "query_rewrite" in metrics.provider_usage
    assert "answer_generation" in metrics.provider_usage
    assert metrics.ragas_mode == "off"
    assert metrics.ragas_selected is False
    assert metrics.ragas_executed is False
    assert metrics.ragas_status == "disabled"


def test_online_metrics_resolves_provider_usage_and_model() -> None:
    provider_usage = {
        "query_rewrite": {"provider": "gemini", "model": "gemini-2.5-flash", "observed": True},
        "answer_generation": {"provider": "openrouter", "model": "google/gemini-2.5-flash", "observed": True},
        "guardrails": {"provider": "unobserved", "model": "unobserved", "observed": False},
    }
    metrics = build_online_metrics(
        trace_id="trace-provider-test",
        request_status="ok",
        context_used=["Context"],
        bot_response="Trả lời",
        provider_usage=provider_usage,
    )
    assert metrics.observed_provider == "openrouter"
    assert metrics.observed_model == "google/gemini-2.5-flash"
    assert metrics.provider_usage["query_rewrite"]["provider"] == "gemini"



def test_online_metrics_no_evidence_and_refusal_categorization() -> None:
    # 1. No evidence response
    metrics_no_ev = build_online_metrics(
        trace_id="trace-no-ev",
        request_status="no_evidence",
        latency={"t_total": 0.5},
        context_used=[],
        bot_response="Xin lỗi, tôi không tìm thấy bằng chứng pháp luật đủ tin cậy...",
        cached=False,
        input_safe=True,
        output_safe=True,
        ragas_mode="off",
    )
    assert metrics_no_ev.no_evidence is True
    assert metrics_no_ev.context_count == 0
    assert metrics_no_ev.refusal_category == "no_evidence"

    # 2. Guardrail input blocked
    metrics_blocked_in = build_online_metrics(
        trace_id="trace-blocked-in",
        request_status="blocked_input",
        latency={"t_total": 0.05},
        context_used=[],
        bot_response="Yêu cầu bị từ chối do vi phạm quy tắc an toàn.",
        cached=False,
        input_safe=False,
        output_safe=True,
        rejection_reason="Jailbreak attempt",
        ragas_mode="off",
    )
    assert metrics_blocked_in.refusal_category == "guardrail_input"
    assert metrics_blocked_in.context_count == 0

    # 3. Guardrail output blocked
    metrics_blocked_out = build_online_metrics(
        trace_id="trace-blocked-out",
        request_status="blocked_output",
        latency={"t_total": 1.1},
        context_used=["Context 1"],
        bot_response="Thông tin không thể hiển thị.",
        cached=False,
        input_safe=True,
        output_safe=False,
        rejection_reason="Hallucination detected",
        ragas_mode="off",
    )
    assert metrics_blocked_out.refusal_category == "guardrail_output"


def test_online_metrics_does_not_expose_misleading_quality_field_names() -> None:
    """
    Operational metrics must NEVER expose fields semantically named as:
    legal correctness, Recall@K, citation validity, or faithfulness-to-law.
    """
    metrics = build_online_metrics(
        trace_id="trace-check-names",
        request_status="ok",
        latency={"t_total": 1.0},
        context_used=["Context 1"],
        bot_response="12/2026/NĐ-CP",
        cached=False,
        ragas_mode="off",
    )
    metrics_dict = metrics.to_dict()

    forbidden_substrings = [
        "recall",
        "correctness",
        "citation_validity",
        "faithfulness_to_law",
        "legal_accuracy",
        "gold_hit",
    ]

    for key in metrics_dict.keys():
        key_lower = key.lower()
        for forbidden in forbidden_substrings:
            assert forbidden not in key_lower, (
                f"Forbidden semantic quality metric name '{forbidden}' found in key '{key}'"
            )

    # If ragas proxy fields exist, they MUST have 'proxy' in their name
    for key, val in metrics_dict.items():
        if "faithfulness" in key.lower() or "relevance" in key.lower():
            assert "proxy" in key.lower(), (
                f"Field '{key}' measures proxy Ragas score but lacks 'proxy' designation."
            )


def test_observed_provider_is_truthful_and_not_inferred_from_config() -> None:
    # When provider is explicitly observed (e.g. from direct_llm execution metadata)
    metrics_observed = build_online_metrics(
        trace_id="trace-prov-1",
        request_status="ok",
        latency={"t_total": 0.8},
        context_used=["Context"],
        bot_response="Response",
        cached=False,
        ragas_mode="off",
        observed_provider="OpenRouter",
    )
    assert metrics_observed.observed_provider == "OpenRouter"

    # When provider is None / unobserved, it MUST NOT infer from settings
    metrics_unobserved = build_online_metrics(
        trace_id="trace-prov-2",
        request_status="ok",
        latency={"t_total": 0.8},
        context_used=["Context"],
        bot_response="Response",
        cached=False,
        ragas_mode="off",
        observed_provider=None,
    )
    assert metrics_unobserved.observed_provider in ("unobserved", "unknown")



def test_sanitize_error_message_redacts_credentials_and_truncates() -> None:
    from app.evaluation.online_metrics import sanitize_error_message

    raw_err = "HTTP 401 https://api.openrouter.ai/v1/chat?api_key=sk-or-v1-secret123456789 with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    sanitized = sanitize_error_message(raw_err)

    assert "sk-or-v1-secret123456789" not in sanitized
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in sanitized
    assert "[REDACTED]" in sanitized
    assert len(sanitized) <= 200


def test_build_online_metrics_sanitizes_technical_error_dict_message() -> None:
    from app.evaluation.online_metrics import build_online_metrics

    tech_error = {
        "stage": "retrieval_error",
        "error_type": "RetrievalPipelineError",
        "message": "https://pinecone.io/v1/vectors?key=pcsk_secret_val_9999",
    }
    metrics = build_online_metrics(
        trace_id="trace-err-sanitized",
        request_status="technical_error",
        technical_error=tech_error,
    )
    assert isinstance(metrics.technical_error, dict)
    assert "pcsk_secret_val_9999" not in metrics.technical_error["message"]
    assert "[REDACTED]" in metrics.technical_error["message"]
