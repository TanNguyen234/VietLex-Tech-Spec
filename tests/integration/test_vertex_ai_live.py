import os

import pytest
from google.genai import types

from app.services.vertex_ai import get_vertex_provider


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_VERTEX_LIVE_TESTS") != "1",
        reason="set RUN_VERTEX_LIVE_TESTS=1 for the opt-in Vertex smoke",
    ),
]


@pytest.mark.asyncio
async def test_vertex_live_generation_and_embedding_smoke() -> None:
    provider = get_vertex_provider()

    generation = await provider.generate(
        "Trả lời đúng một từ: OK",
        max_output_tokens=64,
        thinking_level=types.ThinkingLevel.MINIMAL,
    )
    embedding = await provider.embed_query(
        "quy định thuế",
        output_dimensionality=384,
    )

    assert generation.text.strip()
    assert generation.metadata.provider == "google_vertex_ai"
    assert generation.metadata.model == "gemini-3.5-flash"
    assert embedding.metadata.model == "gemini-embedding-2"
    assert len(embedding.values) == 384
