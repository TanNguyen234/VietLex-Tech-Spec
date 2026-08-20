import importlib
from types import SimpleNamespace

import pytest


def _module():
    try:
        return importlib.import_module("app.evaluation.vertex_g0_probe")
    except ModuleNotFoundError:
        pytest.fail("Vertex G0 isolated probe is missing")


class _Provider:
    def __init__(self):
        self.calls = []

    async def embed_query(self, text, *, output_dimensionality, task):
        self.calls.append(("query", text, output_dimensionality, task))
        values = (1.0,) + (0.0,) * (output_dimensionality - 1)
        return SimpleNamespace(
            values=values,
            output_dimensionality=output_dimensionality,
            l2_norm=1.0,
            metadata=SimpleNamespace(
                provider="google_vertex_ai",
                model="gemini-embedding-2",
                project="vietlex-test-project",
                location="global",
                status="success",
                latency_ms=1.25,
                to_dict=lambda: {
                    "provider": "google_vertex_ai",
                    "model": "gemini-embedding-2",
                    "project": "vietlex-test-project",
                    "location": "global",
                    "status": "success",
                    "latency_ms": 1.25,
                },
            ),
        )

    async def embed_document(self, text, *, title, output_dimensionality):
        self.calls.append(("document", text, output_dimensionality, title))
        return await self.embed_query(
            text,
            output_dimensionality=output_dimensionality,
            task="document-internal",
        )


@pytest.mark.asyncio
async def test_probe_checks_repeat_similarity_for_all_dimensions() -> None:
    probe = _module()
    provider = _Provider()

    result = await probe.run_dimension_probe(
        provider,
        query="Điều kiện khấu trừ thuế?",
        document="Cá nhân được khấu trừ theo quy định.",
        document_title="Điều 1",
    )

    assert [item["dimension"] for item in result["dimensions"]] == [
        384,
        768,
        1024,
    ]
    assert all(item["status"] == "pass" for item in result["dimensions"])
    assert all(
        item["query_repeat_cosine"] == pytest.approx(1.0)
        for item in result["dimensions"]
    )
    assert all(
        item["document_repeat_cosine"] == pytest.approx(1.0)
        for item in result["dimensions"]
    )
    assert result["vector_write_attempted"] is False
