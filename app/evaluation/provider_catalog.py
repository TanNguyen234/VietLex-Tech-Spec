from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderModel:
    provider: str
    model: str


OPENROUTER_PRIMARY_MODEL = "meta-llama/llama-3.3-70b-instruct"
GEMINI_PRIMARY_MODEL = "gemini-2.0-flash"
NVIDIA_PRIMARY_MODEL = "meta/llama-3.3-70b-instruct"
GROQ_PRIMARY_MODEL = "llama-3.3-70b-versatile"
GEMINI_SECONDARY_MODEL = "gemini-1.5-flash"
GROQ_SECONDARY_MODEL = "llama3-8b-8192"

GENERATION_PROVIDER_MODELS = (
    ProviderModel("OpenRouter", OPENROUTER_PRIMARY_MODEL),
    ProviderModel("Gemini", GEMINI_PRIMARY_MODEL),
    ProviderModel("NVIDIA NIM", NVIDIA_PRIMARY_MODEL),
    ProviderModel("Groq", GROQ_PRIMARY_MODEL),
    ProviderModel("OpenRouter", OPENROUTER_PRIMARY_MODEL),
    ProviderModel("Gemini", GEMINI_SECONDARY_MODEL),
    ProviderModel("Groq", GROQ_SECONDARY_MODEL),
)

JUDGE_PROVIDER_MODELS = (
    ProviderModel("Gemini", GEMINI_PRIMARY_MODEL),
    ProviderModel("NVIDIA NIM", NVIDIA_PRIMARY_MODEL),
    ProviderModel("Groq", GROQ_PRIMARY_MODEL),
    ProviderModel("OpenRouter", OPENROUTER_PRIMARY_MODEL),
    ProviderModel("OmniGate", "legal-core-model"),
)
