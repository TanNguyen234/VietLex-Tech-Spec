import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import pytest
from app.services.rag_pipeline import dense_search, cohere_rerank

@pytest.mark.asyncio
async def test_cohere_rerank_top3():
    docs = [
        "[Văn bản A]\nNội dung điều 1",
        "[Văn bản B]\nNội dung điều 2",
        "[Văn bản C]\nNội dung điều 3",
        "[Văn bản D]\nNội dung điều 4"
    ]
    top_docs = await cohere_rerank("Nội dung điều 2", docs, top_k=3)
    assert len(top_docs) <= 3
