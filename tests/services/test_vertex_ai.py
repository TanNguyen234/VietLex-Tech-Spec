import importlib
import math
import os
from types import SimpleNamespace

import httpx
import pytest
import requests
from google.auth import exceptions as google_auth_exceptions
from google.genai import types
from pydantic import BaseModel


def _module():
    try:
        return importlib.import_module("app.services.vertex_ai")
    except ModuleNotFoundError:
        pytest.fail("Vertex AI provider boundary is missing")


def _settings(**overrides):
    values = {
        "GOOGLE_CLOUD_PROJECT": "vietlex-test-project",
        "GOOGLE_CLOUD_LOCATION": "global",
        "VERTEX_LLM_MODEL": "gemini-3.5-flash",
        "VERTEX_EMBEDDING_MODEL": "gemini-embedding-2",
        "VERTEX_REQUEST_TIMEOUT_SECONDS": 3.0,
        "VERTEX_MAX_RETRIES": 2,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _Models:
    def __init__(self):
        self.generation_error = None
        self.embedding_error = None
        self.embedding_dimension = 384
        self.generation_calls = []
        self.embedding_calls = []
        self.generation_response = SimpleNamespace(text="Câu trả lời Vertex")

    async def generate_content(self, **kwargs):
        self.generation_calls.append(kwargs)
        if self.generation_error:
            raise self.generation_error
        return self.generation_response

    async def embed_content(self, **kwargs):
        self.embedding_calls.append(kwargs)
        if self.embedding_error:
            raise self.embedding_error
        values = [0.0] * self.embedding_dimension
        values[0] = 1.0
        return SimpleNamespace(
            embeddings=[SimpleNamespace(values=values)]
        )


class _Client:
    def __init__(self, models):
        self.aio = SimpleNamespace(models=models)


class _ProviderAPIError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


@pytest.mark.asyncio
async def test_generation_returns_typed_vertex_metadata_without_credentials() -> None:
    vertex_ai = _module()
    models = _Models()
    captured_client_args = {}

    def client_factory(**kwargs):
        captured_client_args.update(kwargs)
        return _Client(models)

    provider = vertex_ai.VertexAIProvider(
        settings=_settings(),
        credentials_loader=lambda: (object(), "adc-project"),
        client_factory=client_factory,
    )

    result = await provider.generate(
        "Câu hỏi",
        system_instruction="Chỉ dùng bằng chứng.",
        max_output_tokens=64,
        thinking_level=types.ThinkingLevel.MINIMAL,
    )

    assert result.text == "Câu trả lời Vertex"
    assert result.metadata.provider == "google_vertex_ai"
    assert result.metadata.model == "gemini-3.5-flash"
    assert result.metadata.project == "vietlex-test-project"
    assert result.metadata.location == "global"
    assert result.metadata.status == "success"
    assert result.metadata.latency_ms >= 0
    assert "credentials" in captured_client_args
    assert "api_key" not in captured_client_args
    assert "credentials" not in result.metadata.to_dict()
    generation_config = models.generation_calls[0]["config"]
    assert generation_config.thinking_config.thinking_level == "MINIMAL"


@pytest.mark.asyncio
async def test_structured_generation_uses_vertex_response_schema() -> None:
    vertex_ai = _module()

    class Verdict(BaseModel):
        value: int

    models = _Models()
    models.generation_response = SimpleNamespace(parsed=Verdict(value=1))
    provider = vertex_ai.VertexAIProvider(
        settings=_settings(),
        credentials_loader=lambda: (object(), "adc-project"),
        client_factory=lambda **_kwargs: _Client(models),
    )

    result = await provider.generate_structured(
        "Return a verdict.",
        response_model=Verdict,
        max_output_tokens=64,
    )

    assert result == Verdict(value=1)
    config = models.generation_calls[0]["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema is Verdict


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_type", "expected_kind"),
    [
        (_ProviderAPIError(403, "permission denied"), "VertexPermissionError", "permission"),
        (_ProviderAPIError(429, "quota exceeded"), "VertexQuotaError", "quota"),
        (_ProviderAPIError(404, "model not found"), "VertexModelError", "invalid_model"),
        (httpx.ConnectError("network unavailable"), "VertexNetworkError", "network"),
        (requests.exceptions.SSLError("certificate failed"), "VertexNetworkError", "network"),
        (google_auth_exceptions.RefreshError("invalid_scope"), "VertexAuthenticationError", "authentication"),
    ],
)
async def test_provider_failures_are_typed(error, expected_type, expected_kind) -> None:
    vertex_ai = _module()
    models = _Models()
    models.generation_error = error
    provider = vertex_ai.VertexAIProvider(
        settings=_settings(),
        credentials_loader=lambda: (object(), "adc-project"),
        client_factory=lambda **_kwargs: _Client(models),
    )

    with pytest.raises(getattr(vertex_ai, expected_type)) as captured:
        await provider.generate("Câu hỏi")

    assert captured.value.kind == expected_kind


@pytest.mark.asyncio
async def test_missing_adc_fails_explicitly_without_leaking_key_material() -> None:
    vertex_ai = _module()
    secret = "-----BEGIN PRIVATE KEY----- do-not-log -----END PRIVATE KEY-----"

    def missing_adc():
        raise RuntimeError(f"ADC missing at C:\\secret\\key.json {secret}")

    provider = vertex_ai.VertexAIProvider(
        settings=_settings(),
        credentials_loader=missing_adc,
        client_factory=lambda **_kwargs: pytest.fail("client must not be built"),
    )

    with pytest.raises(vertex_ai.VertexAuthenticationError) as captured:
        await provider.generate("Câu hỏi")

    message = str(captured.value)
    assert captured.value.kind == "authentication"
    assert message == "Application Default Credentials could not be discovered."
    assert "do-not-log" not in message
    assert "key.json" not in message


@pytest.mark.asyncio
@pytest.mark.parametrize("dimension", [384, 768, 1024])
async def test_embedding_validates_dimensions_and_uses_asymmetric_format(
    dimension,
) -> None:
    vertex_ai = _module()
    models = _Models()
    models.embedding_dimension = dimension
    provider = vertex_ai.VertexAIProvider(
        settings=_settings(),
        credentials_loader=lambda: (object(), "adc-project"),
        client_factory=lambda **_kwargs: _Client(models),
    )

    query = await provider.embed_query(
        "Điều kiện khấu trừ thuế?",
        output_dimensionality=dimension,
    )
    document = await provider.embed_document(
        "Cá nhân được khấu trừ theo quy định.",
        title="Điều 1",
        output_dimensionality=dimension,
    )

    assert len(query.values) == dimension
    assert len(document.values) == dimension
    assert all(math.isfinite(value) for value in query.values)
    assert query.l2_norm == pytest.approx(1.0)
    assert models.embedding_calls[0]["contents"].startswith(
        "task: question answering | query: "
    )
    assert models.embedding_calls[1]["contents"].startswith(
        "title: Điều 1 | text: "
    )


@pytest.mark.asyncio
async def test_embedding_rejects_wrong_dimension_before_any_vector_write() -> None:
    vertex_ai = _module()
    models = _Models()
    models.embedding_dimension = 383
    provider = vertex_ai.VertexAIProvider(
        settings=_settings(),
        credentials_loader=lambda: (object(), "adc-project"),
        client_factory=lambda **_kwargs: _Client(models),
    )

    with pytest.raises(vertex_ai.VertexInvalidResponseError):
        await provider.embed_query("Câu hỏi", output_dimensionality=384)


@pytest.mark.asyncio
async def test_local_dotenv_can_supply_adc_path_without_modeling_credentials(
    tmp_path,
    monkeypatch,
) -> None:
    vertex_ai = _module()
    credential_path = tmp_path / "local-adc.json"
    credential_path.write_text("{}", encoding="utf-8")
    (tmp_path / ".env").write_text(
        f"GOOGLE_APPLICATION_CREDENTIALS={credential_path}\n"
        "GOOGLE_CLOUD_PROJECT=must-not-be-exported\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

    def credentials_loader():
        assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == str(
            credential_path
        )
        return object(), "adc-project"

    provider = vertex_ai.VertexAIProvider(
        settings=_settings(),
        credentials_loader=credentials_loader,
        client_factory=lambda **_kwargs: _Client(_Models()),
    )

    result = await provider.generate("Câu hỏi")

    assert result.metadata.status == "success"
    assert "GOOGLE_CLOUD_PROJECT" not in os.environ


@pytest.mark.asyncio
async def test_provider_installs_system_trust_before_adc(monkeypatch) -> None:
    vertex_ai = _module()
    events = []
    monkeypatch.setattr(
        vertex_ai,
        "install_system_trust_store",
        lambda: events.append("trust"),
        raising=False,
    )

    def credentials_loader():
        events.append("adc")
        return object(), "adc-project"

    provider = vertex_ai.VertexAIProvider(
        settings=_settings(),
        credentials_loader=credentials_loader,
        client_factory=lambda **_kwargs: _Client(_Models()),
    )

    await provider.generate("Câu hỏi")

    assert events[:2] == ["trust", "adc"]


@pytest.mark.asyncio
async def test_default_adc_loader_requests_cloud_platform_scope(monkeypatch) -> None:
    vertex_ai = _module()
    captured = {}

    def default_credentials(*, scopes=None):
        captured["scopes"] = scopes
        return object(), "adc-project"

    monkeypatch.setattr(vertex_ai.google_auth, "default", default_credentials)
    provider = vertex_ai.VertexAIProvider(
        settings=_settings(GOOGLE_CLOUD_PROJECT=None),
        client_factory=lambda **_kwargs: _Client(_Models()),
    )

    await provider.generate("Câu hỏi")

    assert captured["scopes"] == [
        "https://www.googleapis.com/auth/cloud-platform"
    ]
