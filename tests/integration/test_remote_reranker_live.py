import os

import pytest
from pinecone import Pinecone

from app.config import get_settings, install_system_trust_store
from app.ingestion.content_store import ContentStore
from app.ingestion.legal_text import chunk_document
from app.ingestion.qdrant_inference import create_inference_client
from app.services.remote_reranker import RemoteReranker


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE_RERANK_TEST") != "1",
        reason="Set RUN_LIVE_RERANK_TEST=1 for two real provider calls.",
    ),
]


@pytest.mark.asyncio
async def test_real_corpus_reranks_with_qdrant_and_pinecone() -> None:
    settings = get_settings()
    store = ContentStore(settings.CONTENT_STORE_PATH)
    stored = store.get_many([259730, 427301, 431147])
    chunks = [
        chunk_document(
            stored[document_id].metadata,
            stored[document_id].content,
            max_tokens=180,
            overlap_tokens=12,
        )[0]
        for document_id in (259730, 427301, 431147)
    ]
    documents = [
        f"[{chunk.citation}]\n{chunk.text}" for chunk in chunks
    ]
    query = (
        "Luật số 72/2020/QH14 quy định phạm vi điều chỉnh "
        "về lĩnh vực gì?"
    )

    install_system_trust_store()
    qdrant = create_inference_client(settings)
    pinecone = Pinecone(
        api_key=settings.pinecone_api_key,
        timeout=settings.PINECONE_RERANK_TIMEOUT_SECONDS,
    )
    reranker = RemoteReranker(
        settings=settings,
        qdrant=qdrant,
        pinecone=pinecone,
    )
    try:
        primary = await reranker.rerank(query, documents)
        fallback = await reranker._pinecone_rerank(
            query,
            documents,
            fallback_reason="live_smoke",
        )
    finally:
        qdrant.close()
        pinecone.close()

    assert primary.provider == "qdrant"
    assert fallback.provider == "pinecone"
    assert primary.results
    assert fallback.results
    assert chunks[primary.results[0].index].document_number == "72/2020/QH14"
    assert chunks[fallback.results[0].index].document_number == "72/2020/QH14"
