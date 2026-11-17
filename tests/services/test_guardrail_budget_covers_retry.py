"""Guardrail deadline must cover a first Vertex attempt, one transient retry, and the retry backoff."""

from app.config import Settings
from app.services import serverless_guardrails


def test_guardrail_budget_covers_two_vertex_attempts_and_backoff():
    settings = Settings(_env_file=None)
    needed = (
        2 * settings.VERTEX_REQUEST_TIMEOUT_SECONDS
        + max(serverless_guardrails.GUARDRAIL_RETRY_BACKOFF_SECONDS)
    )
    assert settings.GUARDRAIL_TIMEOUT_SECONDS >= needed
