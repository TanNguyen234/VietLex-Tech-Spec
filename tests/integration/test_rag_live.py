"""Explicit, bounded real-provider check; never part of the default CI bill."""

import asyncio
import json

import pytest

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_configured_rag_retrieves_and_generates_with_observed_usage():
    from app.services.rag_pipeline import run_advanced_rag

    answer, contexts, metadata = await asyncio.wait_for(
        run_advanced_rag(
            "Theo Luật Doanh nghiệp 2020, thời hạn góp vốn của thành viên công ty TNHH hai thành viên là bao lâu?",
            rewrite_mode="off",
        ),
        timeout=180,
    )
    usage = metadata["provider_usage"]["answer_generation"]
    print(json.dumps({
        "retrieval_status": metadata["retrieval_status"],
        "generation_status": metadata.get("generation_status"),
        "context_count": len(contexts),
        "answer_characters": len(answer),
        "provider": usage["provider"],
        "model": usage["model"],
        "observed": usage["observed"],
        "total_token_count": usage.get("total_token_count"),
        "elapsed_seconds": metadata["t_total"],
    }))
    assert contexts and answer.strip()
    assert metadata["generation_status"] == "success"
    assert usage["observed"] is True
    assert usage.get("total_token_count", 0) > 0
