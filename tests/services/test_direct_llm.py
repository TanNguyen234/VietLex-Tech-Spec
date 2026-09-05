from types import SimpleNamespace
import httpx
import pytest


from app.services import direct_llm
from app.services.vertex_ai import (
    GenerationResult,
    ProviderMetadata,
    VertexAuthenticationError,
    VertexQuotaError,
)


def test_use_case_policies_keep_answer_and_judge_routing_separate() -> None:
    answer = direct_llm.routing_policy_for(direct_llm.LLMUseCase.ANSWER)
    judge = direct_llm.routing_policy_for(direct_llm.LLMUseCase.EVALUATION)

    assert answer.providers[0] == "google_vertex_ai"
    assert "omnigate" not in answer.providers
    assert judge.providers[-1] == "omnigate"


@pytest.mark.asyncio
async def test_provider_in_cooldown_is_skipped(monkeypatch) -> None:
    called = False

    async def openrouter(*_args, **_kwargs):
        nonlocal called
        called = True
        return "must not run"

    monkeypatch.setattr(
        direct_llm,
        "settings",
        SimpleNamespace(
            OPENROUTER_API_KEY="configured",
            GEMINI_API_KEY=None,
            NVIDIA_API_KEY=None,
            GROQ_API_KEY=None,
        ),
    )
    monkeypatch.setattr(direct_llm, "call_openrouter_api", openrouter)
    monkeypatch.setitem(direct_llm._cooldowns, "openrouter", direct_llm.time.time() + 60)

    result = await direct_llm._run_secondary_fallbacks(
        "prompt", "system", 100, primary_error_kind="quota", started=direct_llm.time.perf_counter()
    )

    assert result is None
    assert called is False


@pytest.mark.asyncio
async def test_openrouter_fallback_honors_the_requested_output_budget(
    monkeypatch,
) -> None:
    captured = {}

    class FakeClient:
        async def post(self, url, *, headers, json, timeout):
            captured.update(json)
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={"choices": [{"message": {"content": "Câu trả lời"}}]},
            )

    monkeypatch.setattr(
        direct_llm,
        "settings",
        SimpleNamespace(OPENROUTER_API_KEY="test-key"),
    )
    monkeypatch.setattr(direct_llm, "get_direct_client", FakeClient)

    response = await direct_llm.call_openrouter_api(
        "Câu hỏi",
        max_output_tokens=640,
    )

    assert response == "Câu trả lời"
    assert captured["max_tokens"] == 640

@pytest.mark.asyncio
async def test_generate_llm_response_with_metadata_observes_provider_and_model(
    monkeypatch,
) -> None:
    vertex_call = {}

    class FakeVertexProvider:
        async def generate(self, *_args, **kwargs):
            vertex_call.update(kwargs)
            return GenerationResult(
                text="Kết quả Vertex",
                metadata=ProviderMetadata(
                    provider="google_vertex_ai",
                    model="gemini-3.5-flash",
                    project="vietlex-test-project",
                    location="global",
                    status="success",
                    latency_ms=12.5,
                ),
            )

    monkeypatch.setattr(
        direct_llm,
        "get_vertex_provider",
        lambda: FakeVertexProvider(),
        raising=False,
    )
    for fallback_name in (
        "call_openrouter_api",
        "call_gemini_api",
        "call_nvidia_api",
        "call_groq_api",
    ):
        monkeypatch.setattr(
            direct_llm,
            fallback_name,
            lambda *_args, **_kwargs: pytest.fail(
                "fallback must not run after Vertex succeeds"
            ),
            raising=False,
        )

    result = await direct_llm.generate_llm_response_with_metadata(
        "Câu hỏi",
        max_output_tokens=512,
        thinking_level="MINIMAL",
    )

    assert isinstance(result, direct_llm.LLMGenerationResult)
    assert result.text == "Kết quả Vertex"
    assert result.observed_provider == "google_vertex_ai"
    assert result.observed_model == "gemini-3.5-flash"
    assert result.observed is True
    assert result.status == "success"
    assert result.project == "vietlex-test-project"
    assert result.location == "global"
    assert result.provider_latency_ms == 12.5
    assert vertex_call["thinking_level"] == "MINIMAL"


@pytest.mark.asyncio
async def test_generate_llm_response_with_metadata_returns_typed_adc_failure(
    monkeypatch,
) -> None:
    class MissingADCProvider:
        async def generate(self, *_args, **_kwargs):
            raise VertexAuthenticationError("ADC credentials unavailable")

    monkeypatch.setattr(
        direct_llm,
        "get_vertex_provider",
        lambda: MissingADCProvider(),
        raising=False,
    )
    monkeypatch.setattr(
        direct_llm,
        "settings",
        SimpleNamespace(
            OPENROUTER_API_KEY=None,
            GEMINI_API_KEY=None,
            NVIDIA_API_KEY=None,
            GROQ_API_KEY=None,
            VERTEX_LLM_MODEL="gemini-3.5-flash",
            GOOGLE_CLOUD_PROJECT="vietlex-test-project",
            GOOGLE_CLOUD_LOCATION="global",
        ),
    )

    result = await direct_llm.generate_llm_response_with_metadata(
        "Câu hỏi",
    )

    assert isinstance(result, direct_llm.LLMGenerationResult)
    assert result.observed is True
    assert result.observed_provider == "google_vertex_ai"
    assert result.observed_model == "gemini-3.5-flash"
    assert result.status == "authentication"
    assert "xác thực" in result.text.lower()


@pytest.mark.asyncio
async def test_generate_llm_response_uses_gemini_api_after_vertex_failure(
    monkeypatch,
) -> None:
    events = []
    monkeypatch.setattr(
        direct_llm,
        "settings",
        SimpleNamespace(
            OPENROUTER_API_KEY=None,
            GEMINI_API_KEY="test-gemini",
            NVIDIA_API_KEY=None,
            GROQ_API_KEY=None,
            VERTEX_LLM_MODEL="gemini-3.5-flash",
            GOOGLE_CLOUD_PROJECT="vietlex-test-project",
            GOOGLE_CLOUD_LOCATION="global",
        ),
    )
    class QuotaProvider:
        async def generate(self, *_args, **_kwargs):
            events.append("vertex")
            raise VertexQuotaError("quota exceeded", status_code=429)

    monkeypatch.setattr(
        direct_llm,
        "get_vertex_provider",
        lambda: QuotaProvider(),
        raising=False,
    )

    async def gemini_fallback(*_args, **_kwargs):
        events.append("gemini_api")
        return "Kết quả Gemini API"

    monkeypatch.setattr(
        direct_llm,
        "call_gemini_api",
        gemini_fallback,
        raising=False,
    )
    result = await direct_llm.generate_llm_response_with_metadata(
        "Câu hỏi",
    )

    assert isinstance(result, direct_llm.LLMGenerationResult)
    assert result.text == "Kết quả Gemini API"
    assert result.observed is True
    assert result.observed_provider == "gemini"
    assert result.observed_model == "gemini-2.0-flash"
    assert result.status == "success"
    assert result.fallback_used is True
    assert result.primary_error_kind == "quota"
    assert result.provider_latency_ms is not None
    assert result.provider_latency_ms >= 0
    assert events == ["vertex", "gemini_api"]


@pytest.mark.asyncio
async def test_legacy_free_mode_uses_api_fallback_after_vertex_is_disabled(
    monkeypatch,
) -> None:
    from app.services.vertex_ai import VertexDisabledError

    monkeypatch.setattr(
        direct_llm,
        "settings",
        SimpleNamespace(
            OPENROUTER_API_KEY="free-key",
            GEMINI_API_KEY=None,
            NVIDIA_API_KEY=None,
            GROQ_API_KEY=None,
            VERTEX_LLM_MODEL="gemini-3.5-flash",
            GOOGLE_CLOUD_PROJECT=None,
            GOOGLE_CLOUD_LOCATION="global",
        ),
    )

    def disabled_vertex():
        raise VertexDisabledError("disabled by free pipeline")

    async def free_fallback(*_args, **_kwargs):
        return "Kết quả miễn phí"

    monkeypatch.setattr(direct_llm, "get_vertex_provider", disabled_vertex)
    monkeypatch.setattr(
        direct_llm,
        "call_openrouter_api",
        free_fallback,
    )

    result = await direct_llm.generate_llm_response_with_metadata("Câu hỏi")

    assert result.text == "Kết quả miễn phí"
    assert result.observed_provider == "openrouter"
    assert result.primary_error_kind == "disabled"
@pytest.mark.asyncio
async def test_fallback_retains_provider_reported_usage(monkeypatch):
    class FakeClient:
        async def post(self, url, **kwargs):
            return httpx.Response(200, request=httpx.Request('POST', url), json={
                'choices': [{'message': {'content': 'answer'}}],
                'usage': {'prompt_tokens': 11, 'completion_tokens': 5, 'total_tokens': 16},
            })
    monkeypatch.setattr(direct_llm, 'settings', SimpleNamespace(
        OPENROUTER_API_KEY='test', GEMINI_API_KEY=None, NVIDIA_API_KEY=None, GROQ_API_KEY=None))
    monkeypatch.setattr(direct_llm, 'get_direct_client', FakeClient)
    monkeypatch.setitem(direct_llm._cooldowns, 'openrouter', 0)
    result = await direct_llm._run_secondary_fallbacks('q', '', 100, primary_error_kind='quota', started=direct_llm.time.perf_counter())
    assert result.prompt_token_count == 11
    assert result.output_token_count == 5
    assert result.total_token_count == 16
