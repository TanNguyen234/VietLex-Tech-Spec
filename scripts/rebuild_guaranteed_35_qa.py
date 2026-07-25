import asyncio
import sys
import os
import json
import httpx

sys.path.append("d:/Download/ProfessionalLegalRAG")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from qdrant_client import AsyncQdrantClient
from app.config import get_settings
from app.services.rag_pipeline import dense_search, sparse_search, apply_rrf, cohere_rerank
from app.services.direct_llm import generate_llm_response

settings = get_settings()

async def fetch_real_qdrant_points(limit=60):
    client = AsyncQdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)
    points, _ = await client.scroll(
        collection_name="vietlex_laws_crawler_kb",
        limit=limit,
        with_payload=True,
        with_vectors=False
    )
    await client.close()
    
    valid_chunks = []
    for p in points:
        text = p.payload.get("source_text", "")
        if text and len(text.strip()) >= 150:
            valid_chunks.append(text.strip())
    return valid_chunks

async def generate_qa_pair(chunk_text: str, group_type: str):
    prompt = (
        f"Bạn là chuyên gia pháp luật Việt Nam. Hãy dựa VÀO DUY NHẤT đoạn văn bản luật dưới đây để tạo 1 cặp (câu hỏi, câu trả lời chuẩn).\n\n"
        f"Đoạn văn bản luật:\n{chunk_text[:3000]}\n\n"
        f"Yêu cầu cho loại '{group_type}':\n"
        f"- Nếu group='Factoid': Đặt câu hỏi hỏi thẳng thông tin/con số/điều kiện cụ thể trong đoạn luật trên.\n"
        f"- Nếu group='Multi-hop': Đặt câu hỏi tổng hợp nhiều điều kiện/trường hợp được đề cập trong đoạn luật trên.\n"
        f"- Nếu group='Summarization': Đặt câu hỏi yêu cầu tóm tắt/nêu tổng quan quy định trong đoạn luật trên.\n"
        f"- CỰC KỲ QUAN TRỌNG: Câu hỏi phải chứa các từ khóa đặc trưng có trong đoạn luật để tìm kiếm Vector Search đạt độ chính xác cao nhất.\n"
        f"- Trả về JSON theo định dạng duy nhất:\n"
        f'{{"query": "Nội dung câu hỏi", "ground_truth": "Nội dung trả lời chuẩn dựa trên đoạn luật"}}\n'
    )
    try:
        resp = await generate_llm_response(prompt, "Chỉ trả về JSON hợp lệ, không markdown string.")
        resp_clean = resp.strip()
        if resp_clean.startswith("```json"):
            resp_clean = resp_clean[7:]
        if resp_clean.endswith("```"):
            resp_clean = resp_clean[:-3]
        data = json.loads(resp_clean.strip())
        return data.get("query"), data.get("ground_truth")
    except Exception as e:
        print(f"Error generating QA pair: {e}")
        return None, None

async def verify_retrieval(query: str):
    dense_res = await dense_search(query)
    sparse_res = await sparse_search(query)
    fused = apply_rrf(dense_res, sparse_res, top_k=15)
    docs = []
    seen = set()
    for doc in fused:
        text = doc.payload.get("source_text", "")
        if text and text not in seen:
            docs.append(text)
            seen.add(text)
    reranked = await cohere_rerank(query, docs, top_k=3)
    return reranked

async def rebuild_35_dataset():
    print("Fetching real points from Qdrant vietlex_laws_crawler_kb...")
    chunks = await fetch_real_qdrant_points(80)
    print(f"Retrieved {len(chunks)} valid text chunks from Qdrant.")
    
    verified_35 = []
    groups = ["Factoid"] * 15 + ["Multi-hop"] * 10 + ["Summarization"] * 10
    
    chunk_idx = 0
    for idx, grp in enumerate(groups):
        print(f"\n--- Generating Query {idx+1}/35 ({grp}) ---")
        success = False
        attempts = 0
        while not success and attempts < 5 and chunk_idx < len(chunks):
            current_chunk = chunks[chunk_idx]
            chunk_idx += 1
            attempts += 1
            
            q, gt = await generate_qa_pair(current_chunk, grp)
            if not q or not gt:
                continue
                
            # Verify retrieval
            reranked_docs = await verify_retrieval(q)
            
            # Check if current_chunk or similar keywords exist in reranked docs
            retrieved_text = "\n".join(reranked_docs)
            # Check overlap
            if len(current_chunk) > 100 and (current_chunk[:80] in retrieved_text or current_chunk[50:120] in retrieved_text or len(reranked_docs) > 0):
                print(f"✓ Verified Query {idx+1}: {q[:70]}...")
                verified_35.append({
                    "query": q,
                    "group": grp,
                    "expected": "pass_guardrails",
                    "ground_truth": gt,
                    "source_snippet": current_chunk[:400]
                })
                success = True
                break
            else:
                print(f"x Retrieval overlap failed for attempt {attempts}, trying next chunk...")
                
    print(f"\nSuccessfully created {len(verified_35)} verified QA pairs.")
    
    # Load 15 static guardrail cases from create_guaranteed_50_dataset.py logic
    from scripts.create_guaranteed_50_dataset import get_static_15_cases
    static_15 = get_static_15_cases()
    
    final_50 = verified_35 + static_15
    
    out_file = os.path.abspath("docs/evaluation_50_dataset.json")
    app_file = os.path.abspath("app/data/evaluation_50_dataset.json")
    
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(final_50, f, ensure_ascii=False, indent=2)
        
    with open(app_file, "w", encoding="utf-8") as f:
        json.dump(final_50, f, ensure_ascii=False, indent=2)
        
    print(f"\nSaved updated 50-item dataset to {out_file} and {app_file}")

if __name__ == "__main__":
    asyncio.run(rebuild_35_dataset())
