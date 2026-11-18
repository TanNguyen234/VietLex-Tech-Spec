from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderModel:
    provider: str
    model: str


OPENROUTER_PRIMARY_MODEL = "meta-llama/llama-3.3-70b-instruct"
GEMINI_PRIMARY_MODEL = "gemini-2.5-flash"
NVIDIA_PRIMARY_MODEL = "meta/llama-3.3-70b-instruct"
GROQ_PRIMARY_MODEL = "qwen/qwen3.8-27b"
GEMINI_SECONDARY_MODEL = "gemini-2.5-flash-lite"
GROQ_SECONDARY_MODEL = "openai/gpt-oss-20b"
OMNIGATE_PRIMARY_MODEL = "legal-core-model"

GENERATION_PROVIDER_MODELS = (
    ProviderModel("OpenRouter", OPENROUTER_PRIMARY_MODEL),
    ProviderModel("Gemini", GEMINI_PRIMARY_MODEL),
    ProviderModel("NVIDIA NIM", NVIDIA_PRIMARY_MODEL),
    ProviderModel("Groq", GROQ_PRIMARY_MODEL),
    ProviderModel("Gemini", GEMINI_SECONDARY_MODEL),
    ProviderModel("Groq", GROQ_SECONDARY_MODEL),
)

JUDGE_PROVIDER_MODELS = (
    ProviderModel("Gemini", GEMINI_PRIMARY_MODEL),
    ProviderModel("NVIDIA NIM", NVIDIA_PRIMARY_MODEL),
    ProviderModel("Groq", GROQ_PRIMARY_MODEL),
    ProviderModel("OpenRouter", OPENROUTER_PRIMARY_MODEL),
    ProviderModel("OmniGate", OMNIGATE_PRIMARY_MODEL),
)

RUNTIME_PROVIDER_LABELS: dict[str, str] = {
    "google_vertex_ai": "Google Vertex AI",
    "gemini": "Gemini Direct",
    "groq": "Groq",
    "openrouter": "OpenRouter",
    "nvidia": "NVIDIA NIM",
    "omnigate": "OmniGate",
}

RUNTIME_PROVIDER_MODELS: dict[str, tuple[str, ...]] = {
    "gemini": (GEMINI_PRIMARY_MODEL, GEMINI_SECONDARY_MODEL),
    "groq": (GROQ_PRIMARY_MODEL, GROQ_SECONDARY_MODEL),
    "openrouter": (OPENROUTER_PRIMARY_MODEL,),
    "nvidia": (NVIDIA_PRIMARY_MODEL,),
    "omnigate": (OMNIGATE_PRIMARY_MODEL,),
}
