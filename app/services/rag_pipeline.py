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
async def run_advanced_rag(user_query: str) -> Tuple[str, List[str], Dict[str, float]]:
    t_start = time.time()
    
    # 1. Query Rewriter
    t0 = time.time()
    rewritten_query = await rewrite_query(user_query)
    t_rewrite = round(time.time() - t0, 3)
    
    # 2. Dual-Query Multi-Path Hybrid Search (Parallel via asyncio.gather)
    import asyncio
    t0 = time.time()
    dense_orig_task = dense_search(user_query)
    dense_rewr_task = dense_search(rewritten_query)
    dense_orig, dense_rewr = await asyncio.gather(dense_orig_task, dense_rewr_task)
    t_dense = round(time.time() - t0, 3)
    
    t0 = time.time()
    sparse_orig_task = sparse_search(user_query)
    sparse_rewr_task = sparse_search(rewritten_query)
    sparse_orig, sparse_rewr = await asyncio.gather(sparse_orig_task, sparse_rewr_task)
    t_sparse = round(time.time() - t0, 3)
    
    # 3. Fusion: Reciprocal Rank Fusion (RRF) across 4 branches -> Top 35
    t0 = time.time()
    fused_results = apply_rrf_multi([dense_orig, dense_rewr, sparse_orig, sparse_rewr], top_k=35)
    t_rrf = round(time.time() - t0, 4)
    
    latency_info = {
        "t_rewrite": t_rewrite,
        "t_dense": t_dense,
        "t_sparse": t_sparse,
        "t_rrf": t_rrf,
        "t_rerank": 0.0,
        "t_llm": 0.0,
        "t_total": 0.0
    }
    
    if not fused_results:
        logfire.warning("Không tìm thấy kết quả truy vấn phù hợp từ Qdrant")
        latency_info["t_total"] = round(time.time() - t_start, 3)
        return "Xin lỗi, tôi không tìm thấy tài liệu pháp luật nào phù hợp để trả lời câu hỏi này.", [], latency_info
        
    # Extract unique text contents with title metadata for rerank
    docs_to_rerank = []
    seen_texts = set()
    for doc in fused_results:
        text = doc.payload.get("source_text", "")
        title = doc.payload.get("title", "")
        formatted_chunk = f"[{title}]\n{text}" if title else text
        if text and text not in seen_texts:
            docs_to_rerank.append(formatted_chunk)
            seen_texts.add(text)
            
    # 4. Reranking: BGE-Reranker-v2-M3 -> Top 3
    t0 = time.time()
    reranked_results = await cohere_rerank(user_query, docs_to_rerank, top_k=3)
    t_rerank = round(time.time() - t0, 3)
    latency_info["t_rerank"] = t_rerank
    
    if not reranked_results:
        latency_info["t_total"] = round(time.time() - t_start, 3)
        return "Xin lỗi, không tìm thấy ngữ cảnh pháp lý đủ độ tin cậy để trả lời câu hỏi này.", [], latency_info
    
    # 5. Context Injection & LLM Generation
    t0 = time.time()
    bot_response = await generate_response(user_query, rewritten_query, reranked_results)
    t_llm = round(time.time() - t0, 3)
    latency_info["t_llm"] = t_llm
    
    latency_info["t_total"] = round(time.time() - t_start, 3)
    return bot_response, reranked_results, latency_info


import time

_http_client: httpx.AsyncClient = None

def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=30.0, limits=httpx.Limits(max_keepalive_connections=20, max_connections=50))
    return _http_client

async def rewrite_query(query: str) -> str:
    # Skip rewriting for short queries to reduce latency by 1-2 seconds
    if len(query.split()) <= 10:
        return query

    logfire.info("Đang rewrite query qua Direct API: {query}", query=query)
    prompt = (
        "Bạn là chuyên gia pháp luật Việt Nam. Hãy viết lại câu hỏi sau đây thành một câu truy vấn ngắn gọn chứa các thuật ngữ pháp lý chính thống của Việt Nam để tìm kiếm luật hiệu quả nhất.\n"
        f"Câu hỏi: {query}\n"
        "Trả về DUY NHẤT câu truy vấn đã viết lại, không thêm bất kỳ lời dẫn giải nào."
    )
    try:
        rewritten = await generate_llm_response(prompt)
        logfire.info("Query rewritten: {rewritten}", rewritten=rewritten)
        return rewritten
    except Exception as e:
        logfire.warning("Rewrite query failed: {error}, falling back to original query", error=str(e))
        return query

async def dense_search(query: str, limit: int = 35) -> List[dict]:
    logfire.info("Đang thực hiện Dense Search qua Cloud Run BGE-M3 Embedding (1024-dim)")
    try:
        qdrant_client = AsyncQdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY,
            timeout=30.0
        )
        
        # Get query vector via standard Cloud Run BGE-M3 embedding service (1024 dimensions)
        query_vector = await get_embedding(query)
        
        results = await qdrant_client.query_points(
            collection_name="vietlex_laws_crawler_kb",
            query=query_vector,
            limit=limit
        )
        await qdrant_client.close()
        return results.points
    except Exception as e:
        logfire.error("Error during dense search: {error}", error=str(e))
        return []


async def sparse_search(query: str, limit: int = 35) -> List[dict]:
    logfire.info("Đang thực hiện Sparse Search")
    try:
        qdrant_client = AsyncQdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY,
            timeout=30.0
        )
        # Tokenize query using PyVi
        segmented_query = ViTokenizer.tokenize(query)
        sparse_vec = text_to_sparse_vector(segmented_query)
        
        qdrant_sparse_vec = SparseVector(
            indices=sparse_vec["indices"],
            values=sparse_vec["values"]
        )
        
        results = await qdrant_client.query_points(
            collection_name="vietlex_laws_crawler_kb",
            query=qdrant_sparse_vec,
            using="sparse-text",
            limit=limit
        )
        await qdrant_client.close()
        return results.points
    except Exception as e:
        logfire.error("Error during sparse search: {error}", error=str(e))
        return []

def apply_rrf(dense_results: List, sparse_results: List, k: int = 60, top_k: int = 15) -> List:
    return apply_rrf_multi([dense_results, sparse_results], k=k, top_k=top_k)

def apply_rrf_multi(results_lists: List[List], k: int = 60, top_k: int = 25) -> List:
    logfire.info("Đang chạy Multi-Branch RRF Fusion")
    rrf_scores = {}
    
    for res_list in results_lists:
        for rank, hit in enumerate(res_list, start=1):
            doc_id = hit.id
            if doc_id not in rrf_scores:
                rrf_scores[doc_id] = {"hit": hit, "score": 0.0}
            rrf_scores[doc_id]["score"] += 1.0 / (k + rank)
            
    sorted_docs = sorted(rrf_scores.values(), key=lambda x: x["score"], reverse=True)
    return [item["hit"] for item in sorted_docs[:top_k]]

async def cohere_rerank(query: str, documents: List[str], top_k: int = 5, min_score: float = 0.05) -> List[str]:
    logfire.info("Đang thực hiện Rerank qua Google Cloud Run BGE-Reranker-v2-M3")
    if not documents:
        return []
        
    rerank_url = settings.RERANK_API_URL
    headers = {
        "Content-Type": "application/json"
    }
    if settings.EMBEDDING_SERVICE_API_KEY:
        headers["Authorization"] = f"Bearer {settings.EMBEDDING_SERVICE_API_KEY}"

    payload = {
        "query": query,
        "documents": documents,
        "top_k": top_k
    }
    
    client = get_http_client()
    try:
        response = await client.post(rerank_url, headers=headers, json=payload, timeout=30.0)
        response.raise_for_status()
        results = response.json().get("results", [])
        
        filtered_docs = []
        for item in results:
            score = item.get("score", 0.0)
            if score >= min_score and len(filtered_docs) < top_k:
                filtered_docs.append(item["document"])
                
        # If all scored below min_score, fallback to top 2 highest scored
        if not filtered_docs and results:
            filtered_docs = [item["document"] for item in results[:2]]
            
        return filtered_docs
    except Exception as e:
        logfire.error("Error during Cloud Run rerank: {error}, falling back to top_k of original docs", error=str(e))
        return documents[:top_k]

from app.services.direct_llm import generate_llm_response

async def generate_response(original_query: str, rewritten_query: str, context: List[str]) -> str:
    logfire.info("Đang sinh câu trả lời bằng Direct Gemini/Groq API")
    if not context:
        return "Không có ngữ cảnh pháp lý phù hợp để trả lời câu hỏi."
        
    context_str = "\n\n".join([f"[Tài liệu tham khảo #{i+1}]:\n{doc[:4000]}" for i, doc in enumerate(context)])
    
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
    
    bot_response = await generate_llm_response(user_prompt, system_prompt)
    return bot_response

