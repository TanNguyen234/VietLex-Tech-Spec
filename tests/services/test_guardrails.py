from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage
from pathlib import Path

from app.services import guardrails
from app.services.direct_llm import LLMGenerationResult


def configured_rails():
    return SimpleNamespace(models=[], rails=SimpleNamespace(
        input=SimpleNamespace(flows=['self check input']),
        output=SimpleNamespace(flows=['self check facts custom'])))


@pytest.mark.parametrize('missing_stage', ['input', 'output'])
def test_disabled_required_nemo_flow_is_typed_failure_before_client_creation(monkeypatch, missing_stage):
    from unittest.mock import Mock
    flows = {'input': ['self check input'], 'output': ['self check facts custom']}
    flows[missing_stage] = []
    config = SimpleNamespace(rails=SimpleNamespace(**{
        stage: SimpleNamespace(flows=value) for stage, value in flows.items()}))
    monkeypatch.setattr(guardrails, '_rails_instance', None)
    monkeypatch.setattr(guardrails.RailsConfig, 'from_path', lambda _: config)
    monkeypatch.setattr(guardrails, 'install_system_trust_store', lambda: None)
    constructor = Mock()
    monkeypatch.setattr(guardrails, 'LLMRails', constructor)
    with pytest.raises(guardrails.GuardrailUnavailableError) as error:
        guardrails.get_rails()
    assert error.value.reason == 'configuration_invalid'
    constructor.assert_not_called()


def test_input_prompt_allows_lawful_government_and_policy_questions() -> None:
    prompt = (
        Path(guardrails.__file__).parents[2]
        / "guardrails_config"
        / "prompts.yml"
    ).read_text(encoding="utf-8")

    assert "cơ quan nhà nước" in prompt
    assert "trường hợp mơ hồ" in prompt


def test_output_fact_prompt_matches_nemo_accuracy_score_polarity() -> None:
    prompt = (
        Path(guardrails.__file__).parents[2]
        / "guardrails_config"
        / "prompts.yml"
    ).read_text(encoding="utf-8")

    assert 'Trả lời "yes" nếu câu trả lời hoàn toàn chính xác' in prompt
    assert 'Trả lời "no" nếu câu trả lời chứa thông tin sai lệch' in prompt


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


@pytest.mark.parametrize(
    "text,status,finish_reason",
    [
        ("no", "quota", None),
        ("no", "success", "MAX_TOKENS"),
        ("", "success", "STOP"),
    ],
)
@pytest.mark.asyncio
async def test_guardrail_model_rejects_incomplete_generation(
    monkeypatch, text, status, finish_reason
) -> None:
    async def fake_generate(_prompt, **_kwargs):
        return LLMGenerationResult(
            text=text,
            observed_provider="google_vertex_ai",
            observed_model="gemini-3.5-flash",
            status=status,
            finish_reason=finish_reason,
        )

    monkeypatch.setattr(
        guardrails, "generate_llm_response_with_metadata", fake_generate
    )

    with pytest.raises(guardrails.GuardrailUnavailableError):
        await guardrails.VertexPrimaryGuardrailModel()._agenerate(
            [HumanMessage(content="Câu hỏi pháp luật")]
        )


@pytest.mark.asyncio
async def test_guardrail_model_rejects_missing_generation_metadata(monkeypatch) -> None:
    async def fake_generate(_prompt, **_kwargs):
        return SimpleNamespace(text="no")

    monkeypatch.setattr(
        guardrails, "generate_llm_response_with_metadata", fake_generate
    )

    with pytest.raises(guardrails.GuardrailUnavailableError):
        await guardrails.VertexPrimaryGuardrailModel()._agenerate(
            [HumanMessage(content="Câu hỏi pháp luật")]
        )


def test_get_rails_injects_vertex_primary_guardrail_model(monkeypatch) -> None:
    guardrail_model = object()
    captured = {}
    monkeypatch.setattr(guardrails, "_rails_instance", None)
    monkeypatch.setattr(
        guardrails.RailsConfig,
        "from_path",
        lambda _path: configured_rails(),
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
            return SimpleNamespace(response=[{"content": "Đã kiểm tra"}])

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
async def test_warm_guardrails_rejects_empty_response(monkeypatch) -> None:
    class WarmRails:
        async def generate_async(self, **_kwargs):
            return SimpleNamespace(response=[])

    monkeypatch.setattr(guardrails, "get_rails", lambda: WarmRails())

    with pytest.raises(ValueError, match="invalid_guardrail_response"):
        await guardrails.warm_guardrails()


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
    config = configured_rails()
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


@pytest.mark.parametrize("stage", ["input", "output"])
@pytest.mark.parametrize(
    "rail_response",
    [None, SimpleNamespace(response=[]), SimpleNamespace(response=[{}])],
)
@pytest.mark.asyncio
async def test_guardrail_missing_response_is_unavailable(
    monkeypatch, stage, rail_response
) -> None:
    class FakeRails:
        async def generate_async(self, **_kwargs):
            return rail_response

    monkeypatch.setattr(guardrails, "get_rails", lambda: FakeRails())

    with pytest.raises(
        guardrails.GuardrailUnavailableError,
        match=f"{stage} guardrail unavailable",
    ):
        if stage == "input":
            await guardrails.check_input_guardrails("Điều kiện cấp phép là gì?")
        else:
            await guardrails.check_output_guardrails(
                "Câu trả lời", ["Căn cứ pháp lý"], "Câu hỏi"
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


@pytest.mark.asyncio
async def test_input_guardrail_log_omits_raw_question(monkeypatch) -> None:
    class FakeRails:
        async def generate_async(self, **_kwargs):
            return SimpleNamespace(response=[{"content": "Đã kiểm tra"}])

    private_question = "Hồ sơ riêng của Nguyễn Văn A mã 849201"
    logged: list[tuple[str, dict]] = []
    monkeypatch.setattr(guardrails, "get_rails", lambda: FakeRails())
    monkeypatch.setattr(
        guardrails,
        "settings",
        SimpleNamespace(GUARDRAIL_TIMEOUT_SECONDS=1.0),
    )
    monkeypatch.setattr(
        guardrails.logfire,
        "info",
        lambda message, **fields: logged.append((message, fields)),
    )

    safe, _ = await guardrails.check_input_guardrails(private_question)

    assert safe is True
    assert private_question not in repr(logged)
    assert logged[0][1] == {"message_length": len(private_question)}


@pytest.mark.parametrize("stage", ["input", "output"])
@pytest.mark.asyncio
async def test_guardrail_errors_do_not_log_or_expose_raw_provider_error(
    monkeypatch, stage
) -> None:
    private_error = "upstream echoed private value: client secret 238491"
    logged: list[tuple[str, dict]] = []

    class FailingRails:
        async def generate_async(self, **_kwargs):
            raise RuntimeError(private_error)

    monkeypatch.setattr(guardrails, "get_rails", lambda: FailingRails())
    monkeypatch.setattr(
        guardrails,
        "settings",
        SimpleNamespace(GUARDRAIL_TIMEOUT_SECONDS=1.0),
    )
    monkeypatch.setattr(
        guardrails.logfire,
        "error",
        lambda message, **fields: logged.append((message, fields)),
    )

    with pytest.raises(guardrails.GuardrailUnavailableError) as caught:
        if stage == "input":
            await guardrails.check_input_guardrails("Câu hỏi pháp luật")
        else:
            await guardrails.check_output_guardrails(
                "Câu trả lời", ["Căn cứ"], "Câu hỏi"
            )

    assert str(caught.value) == f"{stage} guardrail unavailable: RuntimeError"
    assert private_error not in repr(logged)
    assert private_error not in str(caught.value)


def test_json_parse_failure_log_omits_raw_model_response(monkeypatch) -> None:
    private_response = "Tên khách hàng Nguyễn Văn A và hồ sơ 938271"
    logged: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        guardrails.logfire,
        "warning",
        lambda message, **fields: logged.append((message, fields)),
    )

    assert guardrails.parse_json_safely(private_response) == {}

    assert private_response not in repr(logged)
    assert logged[0][1] == {
        "error_kind": "JSONDecodeError",
        "response_length": len(private_response),
    }
