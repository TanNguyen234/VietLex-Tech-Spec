---
name: qdrant-hybrid-search
description: Hướng dẫn kết nối Qdrant Cloud, lập chỉ mục Hybrid Search (Dense & Sparse BM25), thực hiện Reciprocal Rank Fusion (RRF) và Semantic Caching cho dự án Vietlex Legal RAG. Kích hoạt khi cần khởi tạo `AsyncQdrantClient`, viết hàm tìm kiếm Dense/Sparse, tích hợp thư viện tách từ PyVi, tính điểm RRF, hoặc truy vấn bộ nhớ đệm ngữ nghĩa.
---

# Qdrant Hybrid Search & Semantic Caching Skill

Kỹ năng này hướng dẫn cách kết nối và truy vấn cơ sở dữ liệu vector Qdrant, triển khai thuật toán tìm kiếm kết hợp **Hybrid Search** ( Dense Vectors + Sparse Vectors BM25) tối ưu cho Tiếng Việt và thiết lập cơ chế **Semantic Cache** (bộ nhớ đệm ngữ nghĩa) để tối ưu chi phí và độ trễ cho Vietlex Legal RAG.

---

## 1. Cấu hình Kết nối Qdrant Cloud (Async Client)

Để tránh tình trạng chặn luồng xử lý (blocking) của API, luôn sử dụng phiên bản không đồng bộ `AsyncQdrantClient`.

```python
from qdrant_client import AsyncQdrantClient
from app.config import settings

# Khởi tạo client bất đồng bộ bằng cấu hình tập trung
qdrant_client = AsyncQdrantClient(
    url=settings.QDRANT_URL,
    api_key=settings.QDRANT_API_KEY
)
```

---

## 2. Thiết lập Lập chỉ mục Hybrid Search tối ưu Tiếng Việt

Tìm kiếm lai (Hybrid Search) kết hợp thế mạnh của Dense Search (hiểu ngữ nghĩa sâu) và Sparse Search (khớp chính xác từ khóa kỹ thuật pháp lý như số điều luật, tên thông tư, nghị định).

### Tách từ Tiếng Việt (Word Segmentation):
Tiếng Việt sử dụng khoảng trắng để phân cách các âm tiết chứ không phải từ ghép (ví dụ: "luật đất đai" gồm 3 âm tiết nhưng là 1 từ). Nếu không tách từ, thuật toán BM25 (Sparse Vector) sẽ xem chúng là 3 từ độc lập, dẫn đến khớp sai.
*   **Giải pháp**: Sử dụng thư viện `PyVi` để nối các từ ghép bằng ký tự `_` (ví dụ: "luật đất đai" thành "luật_đất_đai").

```python
from pyvi import ViTokenizer

def preprocess_vietnamese_text(text: str) -> str:
    # Ví dụ: "Bộ luật Dân sự" -> "Bộ_luật Dân_sự"
    return ViTokenizer.tokenize(text)
```

### Các vector sử dụng:
1. **Dense Vector**: Embedding sử dụng model `text-embedding-004` (size 768 hoặc 1024).
2. **Sparse Vector**: Cấu hình mô hình BM25 trên Qdrant với dữ liệu văn bản đã được tách từ thông qua `PyVi`.

---

## 3. Reciprocal Rank Fusion (RRF)

### Tại sao cần RRF?
Dense Search và Sparse Search trả về các khoảng điểm số (scores) khác nhau và không thể cộng trực tiếp lại với nhau. RRF giải quyết vấn đề này bằng cách chỉ quan tâm đến vị trí xếp hạng (rank) của tài liệu trong từng kết quả tìm kiếm.

### Công thức:
$$RRF\_Score(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$
*   $M$: Tập hợp các phương pháp tìm kiếm (Dense, Sparse).
*   $r_m(d)$: Thứ hạng của tài liệu $d$ trong danh sách kết quả của phương pháp $m$ (1-indexed).
*   $k$: Hằng số làm mượt, mặc định chọn $k = 60$.

### Mẫu triển khai code RRF:

```python
def reciprocal_rank_fusion(
    dense_results: list, 
    sparse_results: list, 
    k: int = 60, 
    top_n: int = 15
) -> list:
    rrf_scores = {}
    
    # helper cập nhật điểm dựa trên vị trí rank
    def add_ranks(results):
        for rank, hit in enumerate(results, start=1):
            doc_id = hit.id
            if doc_id not in rrf_scores:
                rrf_scores[doc_id] = {"hit": hit, "score": 0.0}
            rrf_scores[doc_id]["score"] += 1.0 / (k + rank)

    add_ranks(dense_results)
    add_ranks(sparse_results)
    
    # Sắp xếp các tài liệu theo điểm RRF giảm dần
    sorted_docs = sorted(rrf_scores.values(), key=lambda x: x["score"], reverse=True)
    return [item["hit"] for item in sorted_docs[:top_n]]
```
*   **Quy trình**: Truy xuất Top 15 Dense + Top 15 Sparse -> Hợp nhất bằng RRF lấy Top 15 -> Rerank bằng Cohere `rerank-multilingual-v3.0` lấy Top 3 đưa vào LLM.

---

## 4. Thuật toán Semantic Cache (Bộ nhớ đệm Ngữ nghĩa)

### Tại sao cần thiết?
Hỏi đáp pháp luật thường có tính chất lặp lại (ví dụ nhiều người cùng hỏi về một quy định mới). Semantic Cache lưu trữ vector câu hỏi cũ và câu trả lời tương ứng. Khi có câu hỏi mới có độ tương đồng cực cao, hệ thống trả về ngay lập tức kết quả cũ mà không cần gọi LLM sinh văn bản, giúp tiết kiệm chi phí token và giảm latency xuống mức < 50ms.

### Quy tắc triển khai:
1. Lưu trữ câu hỏi dạng vector (dense embedding) và câu trả lời trong collection `vietlex_semantic_cache`.
2. Truy vấn tìm kiếm vector với khoảng cách Cosine (Cosine Similarity).
3. **Ngưỡng quyết định**: Chỉ chấp nhận hit cache khi điểm tương đồng `>= 0.96`. Nếu dưới ngưỡng này, bắt buộc phải chạy qua pipeline RAG thông thường để tránh trả về câu trả lời râu ông nọ cắm cằm bà kia.

```python
# app/services/semantic_cache.py
import logfire
from qdrant_client import AsyncQdrantClient

async def check_semantic_cache(
    qdrant: AsyncQdrantClient, 
    query_vector: list[float]
) -> str | None:
    results = await qdrant.search(
        collection_name="vietlex_semantic_cache",
        query_vector=query_vector,
        limit=1
    )
    
    if results:
        best_hit = results[0]
        # Ngưỡng bắt buộc >= 0.96 để tránh sai lệch ngữ nghĩa pháp luật
        if best_hit.score >= 0.96:
            logfire.info("Semantic cache HIT", score=best_hit.score)
            return best_hit.payload.get("bot_response")
            
    logfire.info("Semantic cache MISS")
    return None
```
