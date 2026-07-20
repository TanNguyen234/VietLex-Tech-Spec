import asyncio
import json
import sys
from app.services.rag_pipeline import execute_rag_pipeline, hybrid_search

sys.stdout.reconfigure(encoding='utf-8')

async def main():
    # Load query from dataset
    with open("docs/evaluation_50_dataset.json", "r", encoding="utf-8") as f:
        dataset = json.load(f)
        
    for idx in range(3):
        item = dataset[idx]
        query = item["query"]
        ground_truth = item.get("ground_truth", "")
        source_snippet = item.get("source_snippet", "")
        
        print(f"\n==========================================")
        print(f"TEST QUERY [{idx+1}]: {query}")
        print(f"GROUND TRUTH: {ground_truth[:120]}...")
        print(f"SOURCE SNIPPET: {source_snippet[:120]}...")
        print(f"------------------------------------------")
        
        # Test hybrid search retrieval
        retrieved_chunks = await hybrid_search(query, dense_top_k=15, sparse_top_k=15, final_top_k=5)
        print(f"RETRIEVED CHUNKS COUNT: {len(retrieved_chunks)}")
        for c_idx, c in enumerate(retrieved_chunks):
            text = c.get("text", "")
            doc_id = c.get("metadata", {}).get("doc_id", "N/A")
            print(f"  [Chunk {c_idx+1}] (doc_id={doc_id}, score={c.get('rerank_score', 0):.4f}): {text[:150]}...")

if __name__ == "__main__":
    asyncio.run(main())
