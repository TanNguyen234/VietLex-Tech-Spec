from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage
from pathlib import Path

from app.services import guardrails
from app.services.direct_llm import LLMGenerationResult


def test_input_prompt_allows_lawful_government_and_policy_questions() -> None:
    prompt = (
        Path(guardrails.__file__).parents[2]
        / "guardrails_config"
        / "prompts.yml"
    ).read_text(encoding="utf-8")

    assert "cơ quan nhà nước" in prompt
    assert "trường hợp mơ hồ" in prompt


@pytest.mark.asyncio
async def test_guardrail_model_uses_vertex_primary_chain_with_minimal_thinking(
    monkeypatch,
) -> None:
    captured = {}

    async def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        captured.update(kwargs)
        return LLMGenerationResult(
            text="no",
            observed_provider="google_vertex_ai",
            observed_model="gemini-3.5-flash",
            observed=True,
        )

    monkeypatch.setattr(
        guardrails,
        "generate_llm_response_with_metadata",
        fake_generate,
        raising=False,
    )

    result = await guardrails.VertexPrimaryGuardrailModel()._agenerate(
        [HumanMessage(content="Câu hỏi pháp luật")]
    )

    assert result.generations[0].message.content == "no"
    assert captured["prompt"] == "Câu hỏi pháp luật"
    assert captured["thinking_level"] == "MINIMAL"
    assert captured["max_output_tokens"] == 64
    assert result.llm_output["provider"] == "google_vertex_ai"


@pytest.mark.asyncio
async def test_guardrail_model_normalizes_labeled_safe_decision(
    monkeypatch,
) -> None:
    async def fake_generate(_prompt, **_kwargs):
        return LLMGenerationResult(
            text="Đánh giá (yes/no): no",
            observed_provider="google_vertex_ai",
            observed_model="gemini-3.5-flash",
            observed=True,
        )

    monkeypatch.setattr(
        guardrails,
        "generate_llm_response_with_metadata",
        fake_generate,
        raising=False,
    )

    result = await guardrails.VertexPrimaryGuardrailModel()._agenerate(
        [HumanMessage(content="Câu hỏi pháp luật")]
    )

    assert result.generations[0].message.content == "no"


def test_get_rails_injects_vertex_primary_guardrail_model(monkeypatch) -> None:
    guardrail_model = object()
    captured = {}
    monkeypatch.setattr(guardrails, "_rails_instance", None)
    monkeypatch.setattr(
        guardrails.RailsConfig,
        "from_path",
        lambda _path: SimpleNamespace(models=[]),
    )
    monkeypatch.setattr(
        guardrails,
        "VertexPrimaryGuardrailModel",
        lambda: guardrail_model,
        raising=False,
    )
    monkeypatch.setattr(
        guardrails,
        "install_system_trust_store",
        lambda: None,
    )

    def fake_rails(config, *, llm):
        captured["config"] = config
        captured["llm"] = llm
        return object()

    monkeypatch.setattr(guardrails, "LLMRails", fake_rails)

    guardrails.get_rails()

    assert captured["llm"] is guardrail_model


@pytest.mark.asyncio
async def test_warm_guardrails_initializes_rails_once(monkeypatch) -> None:
    calls: list[str] = []

    class WarmRails:
        async def generate_async(self, **kwargs):
            calls.append(kwargs["messages"][0]["content"])
            return SimpleNamespace(response=[])

    monkeypatch.setattr(
        guardrails,
        "get_rails",
        lambda: calls.append("get_rails") or WarmRails(),
    )
    monkeypatch.setattr(
        guardrails,
        "settings",
        SimpleNamespace(
            GUARDRAIL_TIMEOUT_SECONDS=8.0,
            VERTEX_REQUEST_TIMEOUT_SECONDS=30.0,
        ),
    )

    await guardrails.warm_guardrails()

    assert calls == ["get_rails", "Câu hỏi pháp luật Việt Nam."]


@pytest.mark.asyncio
async def test_warm_guardrails_propagates_initialization_failure(
    monkeypatch,
) -> None:
    def fail():
        raise RuntimeError("guardrail unavailable")

    monkeypatch.setattr(guardrails, "get_rails", fail)

    with pytest.raises(RuntimeError, match="guardrail unavailable"):
        await guardrails.warm_guardrails()


def test_get_rails_installs_system_trust_before_creating_client(
    monkeypatch,
) -> None:
    events: list[str] = []
    config = SimpleNamespace(models=[])
    monkeypatch.setattr(guardrails, "_rails_instance", None)
    monkeypatch.setattr(
        guardrails,
        "settings",
        SimpleNamespace(
            OPENROUTER_API_KEY="key",
            GEMINI_API_KEY=None,
            NVIDIA_API_KEY=None,
            GROQ_API_KEY=None,
            OMNIGATE_BASE_URL="https://example.invalid",
            LITELLM_MASTER_KEY=None,
        ),
    )
    monkeypatch.setattr(
        guardrails.RailsConfig,
        "from_path",
        lambda _path: config,
    )
    monkeypatch.setattr(
        guardrails,
        "install_system_trust_store",
        lambda: events.append("trust"),
        raising=False,
    )
    monkeypatch.setattr(
        guardrails,
        "LLMRails",
        lambda _config, *, llm: events.append("client") or object(),
    )

    guardrails.get_rails()

    assert events == ["trust", "client"]


@pytest.mark.asyncio
async def test_input_guardrail_failure_is_reported_as_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        guardrails,
        "get_rails",
        lambda: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    with pytest.raises(
        guardrails.GuardrailUnavailableError,
        match="input guardrail unavailable",
    ):
        await guardrails.check_input_guardrails(
            "Điều kiện cấp phép là gì?"
        )


@pytest.mark.asyncio
async def test_output_guardrail_timeout_is_reported_as_unavailable(
    monkeypatch,
) -> None:
    class SlowRails:
        async def generate_async(self, **_kwargs):
            raise TimeoutError("timeout")

    monkeypatch.setattr(guardrails, "get_rails", lambda: SlowRails())

    with pytest.raises(
        guardrails.GuardrailUnavailableError,
        match="output guardrail unavailable",
    ):
        await guardrails.check_output_guardrails(
            "Câu trả lời",
            ["Căn cứ pháp lý"],
            "Câu hỏi",
        )


@pytest.mark.asyncio
async def test_input_guardrail_uses_configured_timeout(monkeypatch) -> None:
    class SlowRails:
        async def generate_async(self, **_kwargs):
            await __import__("asyncio").sleep(0.02)
            return SimpleNamespace(response=[])

    monkeypatch.setattr(guardrails, "get_rails", lambda: SlowRails())
    monkeypatch.setattr(
        guardrails,
        "settings",
        SimpleNamespace(GUARDRAIL_TIMEOUT_SECONDS=0.001),
    )

    with pytest.raises(
        guardrails.GuardrailUnavailableError,
        match="input guardrail unavailable: timeout",
    ):
        await guardrails.check_input_guardrails(
            "Điều kiện cấp giấy phép là gì?"
        )


@pytest.mark.asyncio
async def test_output_block_audit_logs_hash_not_raw_answer(
    monkeypatch,
) -> None:
    class FakeRails:
        async def generate_async(self, **_kwargs):
            return SimpleNamespace(
                response=[
                    {"content": "I'm sorry, I can't respond to that."}
                ]
            )

    logged: list[tuple[str, dict]] = []
    monkeypatch.setattr(guardrails, "get_rails", lambda: FakeRails())
    monkeypatch.setattr(
        guardrails.logfire,
        "warning",
        lambda message, **fields: logged.append((message, fields)),
    )

    safe, _ = await guardrails.check_output_guardrails(
        "nội dung không được công bố",
        ["[72/2020/QH14, Điều 1] căn cứ"],
        "câu hỏi",
    )

    assert safe is False
    assert len(logged[0][1]["response_sha256"]) == 64
    assert "nội dung không được công bố" not in str(logged)
