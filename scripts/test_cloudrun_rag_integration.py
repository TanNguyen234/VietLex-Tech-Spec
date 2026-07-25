import asyncio
import sys
import os

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from app.services.rag_pipeline import run_advanced_rag
from app.services.semantic_cache import get_embedding, check_semantic_cache, save_to_semantic_cache

async def test_integration():
    print("=" * 70)
    print("1. Testing Cloud Run Embedding via get_embedding() ...")
    print("=" * 70)
    vec = await get_embedding("Quy định về thời hạn góp vốn công ty TNHH")
    print(f"Generated Vector Dim: {len(vec)}")
    print(f"Sample Vector [:5]: {vec[:5]}")
    assert len(vec) == 1024, f"Expected 1024 dims, got {len(vec)}"
    print("✅ get_embedding() PASSED!\n")

    print("=" * 70)
    print("2. Testing full Advanced RAG Pipeline (Embedding + Qdrant + Rerank + LLM) ...")
    print("=" * 70)
    query = "Thời hạn góp vốn thành lập công ty TNHH 2 thành viên là bao lâu?"
    answer, contexts = await run_advanced_rag(query)
    print(f"Query: {query}")
    print(f"Reranked Contexts Count: {len(contexts)}")
    for idx, ctx in enumerate(contexts, 1):
        print(f"  [Context #{idx}]: {ctx[:120]}...")
    print(f"\nBot Response:\n{answer}\n")
    print("✅ run_advanced_rag() PASSED!\n")

if __name__ == "__main__":
    asyncio.run(test_integration())
