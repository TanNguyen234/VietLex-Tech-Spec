from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import Settings
from app.services import direct_llm
from app.services.vertex_ai import (
    GenerationResult,
    ProviderMetadata,
    VertexDisabledError,
    VertexQuotaError,
)


def test_cooldown_is_keyed_by_provider_and_model() -> None:
    assert direct_llm._cooldown_key("gemini", "gemini-2.5-flash") != direct_llm._cooldown_key(
        "gemini", "gemini-2.5-flash-lite"
    )
    assert direct_llm._cooldown_key("groq", "qwen/qwen3.8-27b") != direct_llm._cooldown_key(
        "groq", "openai/gpt-oss-20b"
    )


def test_strip_markdown_json_fence_recovers_fenced_payloads() -> None:
    raw = '```json\n{"verdict": "supported"}\n```'
    assert direct_llm.strip_markdown_json_fence(raw) == '{"verdict": "supported"}'
    assert direct_llm._strip_json_fences(raw) == '{"verdict": "supported"}'
    assert direct_llm.strip_markdown_json_fence('{"clean": true}') == '{"clean": true}'


@pytest.mark.asyncio
async def test_primary_429_does_not_skip_secondary_model_on_same_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        called_urls.append(str(request.url))
        if "gemini-2.5-flash:" in str(request.url):
            return httpx.Response(429, request=request, json={"error": "rate_limited"})
        return httpx.Response(
            200,
            request=request,
            json={
                "modelVersion": "gemini-2.5-flash-lite",
                "candidates": [
                    {
                        "content": {"parts": [{"text": "Kết quả từ flash-lite"}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 5,
                    "totalTokenCount": 15,
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        monkeypatch.setattr(direct_llm, "get_direct_client", lambda: client)
        monkeypatch.setattr(
            direct_llm,
            "settings",
            SimpleNamespace(
                OPENROUTER_API_KEY=None,
                GEMINI_API_KEY="gem-key",
                NVIDIA_API_KEY=None,
                GROQ_API_KEY=None,
                LITELLM_MASTER_KEY=None,
                VERTEX_LLM_MODEL="gemini-3.5-flash",
                GOOGLE_CLOUD_PROJECT="test-proj",
                GOOGLE_CLOUD_LOCATION="global",
            ),
        )
        monkeypatch.setattr(direct_llm, "_cooldowns", {})
        monkeypatch.setattr(
            direct_llm,
            "get_vertex_provider",
            lambda: SimpleNamespace(
                generate=AsyncMock(side_effect=VertexQuotaError("quota", status_code=429))
            ),
        )

        result = await direct_llm.generate_llm_response_with_metadata("Câu hỏi pháp luật")
    finally:
        await client.aclose()

    assert result.status == "success"
    assert result.observed_provider == "gemini"
    assert result.observed_model == "gemini-2.5-flash-lite"
    assert result.text == "Kết quả từ flash-lite"
    assert len(called_urls) == 2


@pytest.mark.asyncio
async def test_provider_text_populates_observed_model_for_model_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import model_comparison

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            request=request,
            json={
                "model": payload["model"],
                "choices": [
                    {
                        "message": {"content": "Phân tích từ Groq"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        monkeypatch.setattr(direct_llm, "get_direct_client", lambda: client)
        monkeypatch.setattr(
            direct_llm,
            "settings",
            SimpleNamespace(GROQ_API_KEY="groq-key"),
        )
        choice = next(c for c in model_comparison._MODEL_CHOICES if c.alias == "groq_llama")
        generation = await model_comparison._invoke_exact_model(choice, "Câu hỏi")
        record = model_comparison._response_record(choice, generation)
    finally:
        await client.aclose()

    assert generation.observed_model == choice.model
    assert record["identity_status"] == "matched"
    assert record["identity_match"] is True


@pytest.mark.asyncio
async def test_explicit_route_selection_and_omnigate_and_catalog_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = Settings(
        _env_file=None,
        APP_ENV="development",
        USE_LEGACY_FREE_PIPELINE=False,
        GEMINI_API_KEY="secret-gem-val-99",
        GROQ_API_KEY="secret-groq-val-99",
        OPENROUTER_API_KEY="secret-or-val-99",
        NVIDIA_API_KEY="secret-nv-val-99",
        LITELLM_MASTER_KEY="secret-omni-val-99",
        OMNIGATE_BASE_URL="https://omnigate.example",
    )
    targets = direct_llm.list_available_llm_targets(cfg)
    providers = {item["provider"] for item in targets}
    assert providers == {
        "google_vertex_ai",
        "gemini",
        "groq",
        "openrouter",
        "nvidia",
        "omnigate",
    }
    serialized_targets = json.dumps(targets)
    for secret in (
        "secret-gem-val-99",
        "secret-groq-val-99",
        "secret-or-val-99",
        "secret-nv-val-99",
        "secret-omni-val-99",
    ):
        assert secret not in serialized_targets

    # Access policy: non-admin in production is pinned to auto; admin in production can pick groq.
    prod_cfg = Settings(
        _env_file=None,
        APP_ENV="production",
        WEB_SESSION_SECRET="x" * 32,
        FRONTEND_URL="https://vietlex.example",
        GROQ_API_KEY="groq",
    )
    assert direct_llm.resolve_llm_route("groq", "openai/gpt-oss-20b", user=None, settings=prod_cfg) == direct_llm.LLMRouteSelection("auto", None)
    assert direct_llm.resolve_llm_route(
        "groq",
        "openai/gpt-oss-20b",
        user={"_id": "a1", "role": "admin", "status": "active", "email_verified": True},
        settings=prod_cfg,
    ) == direct_llm.LLMRouteSelection("groq", "openai/gpt-oss-20b")

    captured_requests: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured_requests.append((str(request.url), body))
        return httpx.Response(
            200,
            request=request,
            json={
                "model": body["model"],
                "choices": [{"message": {"content": f"Trả lời từ {body['model']}"}, "finish_reason": "stop"}],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        monkeypatch.setattr(direct_llm, "get_direct_client", lambda: client)
        monkeypatch.setattr(direct_llm, "settings", cfg)
        monkeypatch.setattr(direct_llm, "_cooldowns", {})
        monkeypatch.setattr(
            direct_llm,
            "get_vertex_provider",
            lambda: pytest.fail("Explicit direct route must not call Vertex first"),
        )

        omni_res = await direct_llm.generate_llm_response_with_metadata(
            "Câu hỏi",
            route=direct_llm.LLMRouteSelection(provider="omnigate", model="legal-core-model"),
            allow_fallback=False,
        )
        groq_res = await direct_llm.generate_llm_response_with_metadata(
            "Câu hỏi",
            route=direct_llm.LLMRouteSelection(provider="groq", model="openai/gpt-oss-20b"),
            allow_fallback=False,
        )
    finally:
        await client.aclose()

    assert omni_res.status == "success"
    assert omni_res.observed_provider == "omnigate"
    assert omni_res.observed_model == "legal-core-model"
    assert captured_requests[0][0] == "https://omnigate.example/v1/chat/completions"

    assert groq_res.status == "success"
    assert groq_res.observed_provider == "groq"
    assert groq_res.observed_model == "openai/gpt-oss-20b"

    # Respect USE_LEGACY_FREE_PIPELINE=True block on google_vertex_ai
    legacy_cfg = Settings(_env_file=None, USE_LEGACY_FREE_PIPELINE=True)
    monkeypatch.setattr(direct_llm, "settings", legacy_cfg)
    monkeypatch.setattr(
        direct_llm,
        "get_vertex_provider",
        lambda: SimpleNamespace(
            generate=AsyncMock(side_effect=VertexDisabledError("blocked by USE_LEGACY_FREE_PIPELINE"))
        ),
    )
    blocked = await direct_llm.generate_llm_response_with_metadata(
        "Câu hỏi",
        route=direct_llm.LLMRouteSelection(provider="google_vertex_ai"),
        allow_fallback=False,
    )
    assert blocked.status == "disabled"


@pytest.mark.asyncio
async def test_json_mode_400_retry_and_fenced_structured_parsers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import research_analysis

    attempts: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        attempts.append(body)
        if "response_format" in body:
            return httpx.Response(400, request=request, json={"error": "response_format unsupported"})
        return httpx.Response(
            200,
            request=request,
            json={
                "model": body["model"],
                "choices": [
                    {
                        "message": {
                            "content": '```json\n{"status":"ok","text":"Đã đối chiếu","evidence_ids":["ev-1"],"unanswered_parts":[]}\n```'
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        monkeypatch.setattr(direct_llm, "get_direct_client", lambda: client)
        monkeypatch.setattr(
            direct_llm,
            "settings",
            SimpleNamespace(
                OPENROUTER_API_KEY="or-key",
                GEMINI_API_KEY=None,
                NVIDIA_API_KEY=None,
                GROQ_API_KEY=None,
                LITELLM_MASTER_KEY=None,
                USE_LEGACY_FREE_PIPELINE=True,
                VERTEX_LLM_MODEL="gemini-3.5-flash",
                GOOGLE_CLOUD_PROJECT=None,
                GOOGLE_CLOUD_LOCATION="global",
            ),
        )
        monkeypatch.setattr(direct_llm, "_cooldowns", {})
        monkeypatch.setattr(
            direct_llm,
            "get_vertex_provider",
            lambda: SimpleNamespace(
                generate=AsyncMock(side_effect=VertexDisabledError("legacy mode"))
            ),
        )

        parsed = await research_analysis.generate_selected_evidence_answer(
            "Câu hỏi?",
            [{"evidence_id": "ev-1", "citation": "Điều 1", "excerpt": "Nội dung điều 1."}],
        )
    finally:
        await client.aclose()

    assert len(attempts) == 2
    assert attempts[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in attempts[1]
    assert parsed["status"] == "ok"
    assert parsed["text"] == "Đã đối chiếu"


@pytest.mark.asyncio
async def test_stream_llm_response_with_metadata_across_sse_and_vertex_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sse_payload = (
        'data: {"model":"qwen/qwen3.8-27b","choices":[{"delta":{"content":"Điều 25 "},"finish_reason":null}]}\n\n'
        'data: {"model":"qwen/qwen3.8-27b","choices":[{"delta":{"content":"quy định tối đa 60 ngày."},"finish_reason":"stop"}],"usage":{"prompt_tokens":20,"completion_tokens":8,"total_tokens":28}}\n\n'
        "data: [DONE]\n\n"
    ).encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/event-stream"},
            content=sse_payload,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        monkeypatch.setattr(direct_llm, "get_direct_client", lambda: client)
        monkeypatch.setattr(
            direct_llm,
            "settings",
            SimpleNamespace(
                OPENROUTER_API_KEY=None,
                GEMINI_API_KEY=None,
                NVIDIA_API_KEY=None,
                GROQ_API_KEY="groq-key",
                LITELLM_MASTER_KEY=None,
                USE_LEGACY_FREE_PIPELINE=False,
                VERTEX_LLM_MODEL="gemini-3.5-flash",
                GOOGLE_CLOUD_PROJECT="proj",
                GOOGLE_CLOUD_LOCATION="global",
            ),
        )
        monkeypatch.setattr(direct_llm, "_cooldowns", {})

        async def failing_vertex_stream(*_args, **_kwargs):
            raise VertexQuotaError("quota", status_code=429)
            yield  # pragma: no cover

        monkeypatch.setattr(
            direct_llm,
            "get_vertex_provider",
            lambda: SimpleNamespace(generate_stream=failing_vertex_stream),
        )

        deltas: list[str] = []
        final_meta: direct_llm.LLMGenerationResult | None = None
        async for item in direct_llm.stream_llm_response_with_metadata("Câu hỏi"):
            if isinstance(item, str):
                deltas.append(item)
            else:
                final_meta = item
    finally:
        await client.aclose()

    assert "".join(deltas) == "Điều 25 quy định tối đa 60 ngày."
    assert final_meta is not None
    assert final_meta.status == "success"
    assert final_meta.observed_provider == "groq"
    assert final_meta.observed_model == "qwen/qwen3.8-27b"
    assert final_meta.fallback_used is True


@pytest.mark.asyncio
async def test_serverless_guardrail_falls_back_to_gemini_direct_with_zero_thinking_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import serverless_guardrails

    captured_gemini_payload: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_gemini_payload.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            request=request,
            json={
                "modelVersion": "gemini-2.5-flash",
                "candidates": [
                    {
                        "content": {"parts": [{"text": "no"}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 30, "candidatesTokenCount": 1, "totalTokenCount": 31},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cfg = Settings(
        _env_file=None,
        USE_LEGACY_FREE_PIPELINE=False,
        GEMINI_API_KEY="gem-key",
    )
    try:
        monkeypatch.setattr(direct_llm, "get_direct_client", lambda: client)
        monkeypatch.setattr(direct_llm, "settings", cfg)
        monkeypatch.setattr(direct_llm, "_cooldowns", {})
        monkeypatch.setattr(serverless_guardrails, "get_settings", lambda: cfg)
        monkeypatch.setattr(
            direct_llm,
            "get_vertex_provider",
            lambda: SimpleNamespace(
                generate=AsyncMock(side_effect=VertexQuotaError("vertex 429", status_code=429))
            ),
        )

        safe, message = await serverless_guardrails.check_input_guardrails(
            "Thời gian thử việc tối đa là bao lâu?"
        )
    finally:
        await client.aclose()

    assert safe is True
    assert message == ""
    gen_cfg = captured_gemini_payload["generationConfig"]
    assert gen_cfg["thinkingConfig"] == {"thinkingBudget": 0}


@pytest.mark.asyncio
async def test_claim_verification_and_research_report_accept_fenced_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import claim_verification, research_report

    evidence = [
        {
            "evidence_id": "ev-labor-25",
            "citation": "Điều 25 Bộ luật Lao động",
            "excerpt": "Không quá 60 ngày đối với công việc có chức danh nghề nghiệp cần trình độ chuyên môn, kỹ thuật từ cao đẳng trở lên.",
        }
    ]
    responses = iter(
        [
            SimpleNamespace(
                status="success",
                finish_reason="STOP",
                observed_provider="groq",
                observed_model="qwen/qwen3.8-27b",
                output_token_count=40,
                thought_token_count=0,
                max_output_tokens=2048,
                text=(
                    '```json\n'
                    '{"status":"ok","issue":"Thời gian thử việc","analysis":[{"text":"Thời gian thử việc tối đa là 60 ngày.","evidence_ids":["E1"]}],'
                    '"exceptions":[],"checklist":[],"sources":["E1"],"unknown":[]}\n'
                    '```'
                ),
            ),
            SimpleNamespace(
                status="success",
                finish_reason="STOP",
                observed_provider="groq",
                observed_model="qwen/qwen3.8-27b",
                output_token_count=35,
                thought_token_count=0,
                max_output_tokens=2048,
                text=(
                    '```json\n'
                    '{"claims":[{"claim_id":"claim-1","verdict":"supported","quotes":[{"evidence_id":"ev-labor-25","quote":"Không quá 60 ngày"}]}]}\n'
                    '```'
                ),
            ),
        ]
    )

    async def fake_generate(*_args, **_kwargs):
        return next(responses)

    monkeypatch.setattr(research_report, "_generate", fake_generate)
    monkeypatch.setattr(claim_verification, "_generate", fake_generate)

    out = await research_report.generate_research_report("Thời gian thử việc?", evidence)
    assert out["status"] == "ok"
    assert out["coverage"]["supported_claims"] == 1


@pytest.mark.asyncio
async def test_stream_llm_tokens_gemini_direct_and_vertex_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1. Vertex primary stream
    async def fake_vertex_stream(*_args, **_kwargs):
        yield "Phần 1 "
        yield "Phần 2."
        yield GenerationResult(
            text="Phần 1 Phần 2.",
            metadata=ProviderMetadata(
                provider="google_vertex_ai",
                model="gemini-3.5-flash",
                project="proj",
                location="global",
                status="success",
                latency_ms=10.0,
            ),
            finish_reason="STOP",
        )

    monkeypatch.setattr(
        direct_llm,
        "get_vertex_provider",
        lambda: SimpleNamespace(generate_stream=fake_vertex_stream),
    )
    monkeypatch.setattr(
        direct_llm,
        "settings",
        Settings(_env_file=None, USE_LEGACY_FREE_PIPELINE=False),
    )
    v_chunks = [c async for c in direct_llm.stream_llm_response("Q")]
    assert "".join(v_chunks) == "Phần 1 Phần 2."

    # 2. Gemini Direct SSE stream via explicit route
    gem_sse = (
        'data: {"modelVersion":"models/gemini-2.5-flash","candidates":[{"content":{"parts":[{"text":"Xin "}]}}]}\n\n'
        'data: {"modelVersion":"models/gemini-2.5-flash","candidates":[{"content":{"parts":[{"text":"chào!"}]},"finishReason":"STOP"}],"usageMetadata":{"promptTokenCount":5,"candidatesTokenCount":2,"totalTokenCount":7}}\n\n'
    ).encode("utf-8")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                request=req,
                headers={"content-type": "text/event-stream"},
                content=gem_sse,
            )
        )
    )
    try:
        monkeypatch.setattr(direct_llm, "get_direct_client", lambda: client)
        monkeypatch.setattr(
            direct_llm,
            "settings",
            Settings(_env_file=None, GEMINI_API_KEY="secret-gem-sse"),
        )
        monkeypatch.setattr(direct_llm, "_cooldowns", {})
        items = [
            item
            async for item in direct_llm.stream_llm_tokens(
                "Q",
                route=direct_llm.LLMRouteSelection("gemini", "gemini-2.5-flash"),
                allow_fallback=False,
            )
        ]
    finally:
        await client.aclose()

    text_deltas = [i for i in items if isinstance(i, str)]
    final = [i for i in items if isinstance(i, direct_llm.LLMGenerationResult)]
    assert "".join(text_deltas) == "Xin chào!"
    assert len(final) == 1
    assert final[0].observed_provider == "gemini"
    assert final[0].observed_model == "gemini-2.5-flash"


def test_resolve_llm_route_validates_model_syntax_and_fails_closed_without_app_env() -> None:
    cfg = Settings(_env_file=None, APP_ENV="development")
    # Path traversal / query injection on Gemini must fall back to model=None
    assert direct_llm.resolve_llm_route(
        "gemini",
        "../../v1beta/files?key=leak",
        settings=cfg,
    ) == direct_llm.LLMRouteSelection("gemini", None)
    assert direct_llm.resolve_llm_route(
        "gemini",
        "models/gemini-2.5-flash",
        settings=cfg,
    ) == direct_llm.LLMRouteSelection("gemini", "gemini-2.5-flash")
    assert direct_llm.resolve_llm_route(
        "openrouter",
        "meta-llama/llama-3.3-70b-instruct:free",
        settings=cfg,
    ) == direct_llm.LLMRouteSelection("openrouter", "meta-llama/llama-3.3-70b-instruct:free")
    # Missing APP_ENV on bare namespace must fail closed (default production)
    assert direct_llm.can_select_custom_llm_route(None, settings=SimpleNamespace()) is False


@pytest.mark.asyncio
async def test_default_llm_provider_honored_inside_auto_route_scope_and_cache_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.guarded_answer_cache import guarded_cache_pipeline_revision

    cfg_auto = Settings(_env_file=None, DEFAULT_LLM_PROVIDER="auto")
    cfg_groq = Settings(_env_file=None, DEFAULT_LLM_PROVIDER="groq", GROQ_API_KEY="g")
    assert guarded_cache_pipeline_revision(cfg_auto) != guarded_cache_pipeline_revision(cfg_groq)

    monkeypatch.setattr(direct_llm, "settings", cfg_groq)
    with direct_llm.llm_route_scope(direct_llm.LLMRouteSelection("auto", None)):
        effective = direct_llm._resolve_effective_route(None, direct_llm.LLMUseCase.ANSWER)
    assert effective.normalized_provider() == "groq"


def test_provider_status_snapshot_reports_per_model_cooldown() -> None:
    import time
    from app.services.provider_runtime import provider_status_snapshot

    cfg = Settings(
        _env_file=None,
        OPENROUTER_API_KEY="or",
        GEMINI_API_KEY="gem",
    )
    future = time.time() + 30.0
    # Single-model openrouter cools down when its primary model is in cooldown
    snap = provider_status_snapshot(
        cfg,
        {"openrouter:meta-llama/llama-3.3-70b-instruct": future},
    )
    by_prov = {row["provider"]: row["state"] for row in snap}
    assert by_prov["openrouter"] == "COOLDOWN"
    assert by_prov["gemini"] != "COOLDOWN"
    # Multi-model gemini cools down only when all configured models are cooling down
    snap_both = provider_status_snapshot(
        cfg,
        {
            "gemini:gemini-2.5-flash": future,
            "gemini:gemini-2.5-flash-lite": future,
        },
    )
    assert {r["provider"]: r["state"] for r in snap_both}["gemini"] == "COOLDOWN"


@pytest.mark.asyncio
async def test_structured_analysis_without_json_prompt_does_not_force_json_mode_on_direct_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured_payloads.append(body)
        return httpx.Response(
            200,
            request=request,
            json={
                "model": body["model"],
                "choices": [{"message": {"content": "<think>suy luận</think>\nthời gian thử việc bộ luật lao động"}, "finish_reason": "stop"}],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        monkeypatch.setattr(direct_llm, "get_direct_client", lambda: client)
        monkeypatch.setattr(
            direct_llm,
            "settings",
            Settings(_env_file=None, USE_LEGACY_FREE_PIPELINE=True, GROQ_API_KEY="groq-key"),
        )
        monkeypatch.setattr(direct_llm, "_cooldowns", {})
        monkeypatch.setattr(
            direct_llm,
            "get_vertex_provider",
            lambda: SimpleNamespace(
                generate=AsyncMock(side_effect=VertexDisabledError("legacy mode"))
            ),
        )
        res = await direct_llm.generate_llm_response_with_metadata(
            "Viết lại câu hỏi: thử việc tối đa bao lâu?",
            "Chỉ trả về truy vấn đã viết lại, không giải thích.",
            use_case=direct_llm.LLMUseCase.STRUCTURED_ANALYSIS,
        )
    finally:
        await client.aclose()

    assert len(captured_payloads) == 1
    assert "response_format" not in captured_payloads[0]
    assert res.status == "success"
    assert res.text == "thời gian thử việc bộ luật lao động"


@pytest.mark.asyncio
async def test_mid_stream_fallback_failure_does_not_concatenate_second_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called_models: list[str] = []

    async def fake_stream_single(provider: str, model: str, **_kwargs):
        called_models.append(f"{provider}:{model}")
        if provider == "openrouter":
            yield "Một nửa câu từ OpenRouter..."
            raise httpx.ReadError("connection reset mid-stream")
        yield "Câu trả lời hoàn toàn mới từ Gemini!"
        yield direct_llm.LLMGenerationResult(
            text="Câu trả lời hoàn toàn mới từ Gemini!",
            observed_provider=provider,
            observed_model=model,
            observed=True,
            status="success",
        )

    async def failing_vertex_stream(*_args, **_kwargs):
        raise VertexQuotaError("quota", status_code=429)
        yield  # pragma: no cover

    monkeypatch.setattr(direct_llm, "_stream_single_direct_target", fake_stream_single)
    monkeypatch.setattr(
        direct_llm,
        "get_vertex_provider",
        lambda: SimpleNamespace(generate_stream=failing_vertex_stream),
    )
    monkeypatch.setattr(
        direct_llm,
        "settings",
        Settings(
            _env_file=None,
            USE_LEGACY_FREE_PIPELINE=False,
            OPENROUTER_API_KEY="or-key",
            GEMINI_API_KEY="gem-key",
        ),
    )
    monkeypatch.setattr(direct_llm, "_cooldowns", {})

    items = [item async for item in direct_llm.stream_llm_response_with_metadata("Câu hỏi")]
    deltas = [i for i in items if isinstance(i, str)]
    finals = [i for i in items if isinstance(i, direct_llm.LLMGenerationResult)]

    assert called_models == ["openrouter:meta-llama/llama-3.3-70b-instruct"]
    assert deltas == ["Một nửa câu từ OpenRouter..."]
    assert len(finals) == 1
    assert finals[0].status == "stream_interrupted"


