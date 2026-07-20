import logfire
import httpx
import hashlib
import asyncio
from typing import Tuple, List, Dict
from pyvi import ViTokenizer
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import SparseVector
from app.config import get_settings
from app.services.semantic_cache import get_embedding

settings = get_settings()

def text_to_sparse_vector(text: str) -> Dict[str, List]:
    tokens = text.lower().split()
    tf = {}
    for token in tokens:
        tf[token] = tf.get(token, 0) + 1
        
    index_values = {}
    for token, count in tf.items():
        hash_val = int(hashlib.md5(token.encode('utf-8')).hexdigest(), 16)
        idx = hash_val % 1000000
        index_values[idx] = index_values.get(idx, 0.0) + float(count)
        
    sorted_indices = sorted(index_values.keys())
    return {
        "indices": sorted_indices,
        "values": [index_values[idx] for idx in sorted_indices]
    }

@logfire.instrument("Chạy luồng Advanced Retrieval Pipeline cho truy vấn: {user_query}")
async def run_advanced_rag(user_query: str) -> Tuple[str, List[str]]:
    # 1. Query Rewriter
    rewritten_query = await rewrite_query(user_query)
    
    # 2. Hybrid Search (Parallel via asyncio.gather)
    import asyncio
    dense_task = dense_search(rewritten_query)
    sparse_task = sparse_search(rewritten_query)
    
    dense_results, sparse_results = await asyncio.gather(dense_task, sparse_task)
    
    # 3. Fusion: Reciprocal Rank Fusion (RRF) -> Top 15
    fused_results = apply_rrf(dense_results, sparse_results, top_k=15)
    
    if not fused_results:
        logfire.warning("Không tìm thấy kết quả truy vấn phù hợp từ Qdrant")
        return "Xin lỗi, tôi không tìm thấy tài liệu pháp luật nào phù hợp để trả lời câu hỏi này.", []
        
    # Extract unique text contents for rerank
    docs_to_rerank = []
    seen_texts = set()
    for doc in fused_results:
        text = doc.payload.get("source_text", "")
        if text and text not in seen_texts:
            docs_to_rerank.append(text)
            seen_texts.add(text)
            
    # 4. Reranking: Cohere Rerank -> Top 3
    reranked_results = await cohere_rerank(rewritten_query, docs_to_rerank, top_k=3)
    
    # 5. Context Injection & LLM Generation
    bot_response = await generate_response(user_query, rewritten_query, reranked_results)
    
    return bot_response, reranked_results

async def rewrite_query(query: str) -> str:
    logfire.info("Đang rewrite query: {query}", query=query)
    base_url = settings.OMNIGATE_BASE_URL.rstrip('/')
    chat_url = f"{base_url}/v1/chat/completions" if not base_url.endswith('/v1') else f"{base_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.LITELLM_MASTER_KEY}"
    }
    prompt = (
        "Bạn là chuyên gia pháp luật Việt Nam. Hãy viết lại câu hỏi sau đây thành một câu truy vấn ngắn gọn chứa các thuật ngữ pháp lý chính thống của Việt Nam để tìm kiếm luật hiệu quả nhất.\n"
        f"Câu hỏi: {query}\n"
        "Trả về DUY NHẤT câu truy vấn đã viết lại, không thêm bất kỳ lời dẫn giải nào."
    )
    payload = {
        "model": "legal-core-model",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0
    }
    
    import asyncio
    for attempt in range(5):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(chat_url, headers=headers, json=payload)
                if response.status_code in [429, 502, 503, 504]:
                    sleep_time = (2 ** attempt) + 1
                    await asyncio.sleep(sleep_time)
                    continue
                response.raise_for_status()
                rewritten = response.json()["choices"][0]["message"]["content"].strip()
                logfire.info("Query rewritten: {rewritten}", rewritten=rewritten)
                return rewritten
        except Exception as e:
            if attempt == 4:
                logfire.error("Error rewriting query after 5 attempts: {error}, falling back to original query", error=str(e))
                return query
            await asyncio.sleep((2 ** attempt) + 1)
    return query

async def dense_search(query: str) -> List[dict]:
    logfire.info("Đang thực hiện Dense Search")
    try:
        qdrant_client = AsyncQdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY
        )
        
        # Get query vector via standard async embeddings
        query_vector = await get_embedding(query)
        # vietlex_knowledge_base dense vector is 384-dimensional (first 384 dimensions of gemini-embedding-2)
        dense_vector = query_vector[:384]
        
        results = await qdrant_client.query_points(
            collection_name="vietlex_knowledge_base",
            query=dense_vector,
            limit=15
        )
        await qdrant_client.close()
        return results.points
    except Exception as e:
        logfire.error("Error during dense search: {error}", error=str(e))
        return []

async def sparse_search(query: str) -> List[dict]:
    logfire.info("Đang thực hiện Sparse Search")
    try:
        qdrant_client = AsyncQdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY
        )
        # Tokenize query using PyVi
        segmented_query = ViTokenizer.tokenize(query)
        sparse_vec = text_to_sparse_vector(segmented_query)
        
        qdrant_sparse_vec = SparseVector(
            indices=sparse_vec["indices"],
            values=sparse_vec["values"]
        )
        
        results = await qdrant_client.query_points(
            collection_name="vietlex_knowledge_base",
            query=qdrant_sparse_vec,
            using="sparse-text",
            limit=15
        )
        await qdrant_client.close()
        return results.points
    except Exception as e:
        logfire.error("Error during sparse search: {error}", error=str(e))
        return []

def apply_rrf(dense_results: List, sparse_results: List, k: int = 60, top_k: int = 15) -> List:
    logfire.info("Đang chạy RRF Fusion")
    rrf_scores = {}
    
    def add_ranks(results):
        for rank, hit in enumerate(results, start=1):
            doc_id = hit.id
            if doc_id not in rrf_scores:
                rrf_scores[doc_id] = {"hit": hit, "score": 0.0}
            rrf_scores[doc_id]["score"] += 1.0 / (k + rank)

    add_ranks(dense_results)
    add_ranks(sparse_results)
    
    sorted_docs = sorted(rrf_scores.values(), key=lambda x: x["score"], reverse=True)
    return [item["hit"] for item in sorted_docs[:top_k]]

async def cohere_rerank(query: str, documents: List[str], top_k: int = 3) -> List[str]:
    logfire.info("Đang thực hiện Rerank qua Cohere")
    if not documents:
        return []
        
    rerank_url = "https://api.cohere.ai/v1/rerank"
    headers = {
        "Authorization": f"Bearer {settings.COHERE_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "rerank-multilingual-v3.0",
        "query": query,
        "documents": documents,
        "top_n": top_k
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(rerank_url, headers=headers, json=payload)
            response.raise_for_status()
            results = response.json().get("results", [])
            reranked = [documents[item["index"]] for item in results[:top_k]]
            return reranked
    except Exception as e:
        logfire.error("Error during Cohere rerank: {error}, falling back to top_k of original docs", error=str(e))
        return documents[:top_k]

async def generate_response(original_query: str, rewritten_query: str, context: List[str]) -> str:
    logfire.info("Đang sinh câu trả lời bằng legal-core-model trên OmniGate")
    if not context:
        return "Không có ngữ cảnh pháp lý phù hợp để trả lời câu hỏi."
        
    base_url = settings.OMNIGATE_BASE_URL.rstrip('/')
    chat_url = f"{base_url}/v1/chat/completions" if not base_url.endswith('/v1') else f"{base_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.LITELLM_MASTER_KEY}"
    }
    
    context_str = "\n\n".join([f"[Tài liệu tham khảo #{i+1}]:\n{doc[:6000]}" for i, doc in enumerate(context)])
    
    system_prompt = (
        "Bạn là Trợ lý Pháp luật Việt Nam thông minh, chính xác và trung thực.\n"
        "Nhiệm vụ của bạn là trả lời câu hỏi của người dùng bằng cách sử dụng THÔNG TIN và ĐIỀU LUẬT được cung cấp trong các Tài liệu tham khảo dưới đây.\n"
        "Quy tắc nghiêm ngặt:\n"
        "1. Trả lời một cách khách quan, rõ ràng, viện dẫn cụ thể theo số Điều, Khoản (nếu có trong tài liệu).\n"
        "2. Chỉ trả lời dựa trên thông tin có trong Tài liệu tham khảo. Tuyệt đối không tự ý thêm thông tin, quy định pháp luật ngoài luồng hoặc tự suy đoán.\n"
        "3. Nếu Tài liệu tham khảo không chứa đủ thông tin để trả lời, hãy báo rằng hệ thống chưa có dữ liệu điều luật chính xác cho câu hỏi này và từ chối trả lời lịch sự."
    )
    
    user_prompt = (
        f"Tài liệu tham khảo:\n{context_str}\n\n"
        f"Câu hỏi của người dùng: {original_query}"
    )
    
    payload = {
        "model": "legal-core-model",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.2
    }
    
    import asyncio
    for attempt in range(5):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(chat_url, headers=headers, json=payload)
                if response.status_code in [429, 502, 503, 504]:
                    sleep_time = (2 ** attempt) + 1
                    await asyncio.sleep(sleep_time)
                    continue
                response.raise_for_status()
                bot_response = response.json()["choices"][0]["message"]["content"].strip()
                return bot_response
        except Exception as e:
            if attempt == 4:
                logfire.error("Error generating answer after 5 attempts: {error}", error=str(e))
                return "Đã xảy ra lỗi khi kết nối với máy chủ sinh câu trả lời pháp luật."
            await asyncio.sleep((2 ** attempt) + 1)
    return "Đã xảy ra lỗi khi kết nối với máy chủ sinh câu trả lời pháp luật."
