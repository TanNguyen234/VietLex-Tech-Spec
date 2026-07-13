---
name: qdrant-hybrid-search
description: Hướng dẫn kết nối Qdrant Cloud, lập chỉ mục Hybrid Search (Dense & Sparse BM25), thực hiện Reciprocal Rank Fusion (RRF) và Semantic Caching cho dự án Vietlex Legal RAG.
---

# Qdrant Hybrid Search & Semantic Caching Skill

Kỹ năng này định nghĩa cách thức AI Agent giao tiếp với Qdrant Vector DB để thực hiện tìm kiếm kết hợp (Hybrid Search) và cơ chế bộ nhớ đệm ngữ nghĩa (Semantic Cache).

## 1. Cấu hình Kết nối Qdrant Cloud
- Luôn khởi tạo `AsyncQdrantClient` để thực hiện các cuộc gọi không đồng bộ (non-blocking).
- Đọc `QDRANT_URL` và `QDRANT_API_KEY` từ file cấu hình tập trung.

## 2. Thiết lập Lập chỉ mục Hybrid
Để hỗ trợ tiếng Việt chính xác, kết hợp:
- **Dense Vector**: Embedding bằng `text-embedding-004` (kích thước 768 hoặc 1024 tuỳ thuộc cấu hình).
- **Sparse Vector**: Sử dụng thuật toán BM25. Dữ liệu văn bản đầu vào bắt buộc phải qua thư viện `PyVi` để thực hiện phân tách từ (word segmentation) trước khi index và search.

```python
# Ví dụ phân tách từ bằng PyVi
from pyvi import ViTokenizer
tokenized_text = ViTokenizer.tokenize(raw_text)
```

## 3. Reciprocal Rank Fusion (RRF)
RRF kết hợp xếp hạng từ hai luồng Dense Search và Sparse Search:
- Lấy Top 15 từ Dense Search.
- Lấy Top 15 từ Sparse Search.
- Tính điểm RRF cho từng document:
$$RRF\_Score(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$
Trong đó $M$ là tập hợp các phương pháp tìm kiếm (Dense, Sparse), $r_m(d)$ là thứ hạng của tài liệu $d$ trong phương pháp $m$, và hằng số $k = 60$.
- Chọn Top 15 tài liệu có điểm RRF cao nhất để đưa qua Cohere Rerank.

## 4. Semantic Cache Algorithm
Thực hiện lưu trữ các cặp (User Query Vector, Bot Response) trong collection `vietlex_semantic_cache`:
- Điểm tương đồngCosine (Cosine Similarity) được tính trực tiếp từ vector truy vấn và vector lưu trữ.
- Ngưỡng quyết định hit cache bắt buộc phải `>= 0.96`.
- Nếu hit cache, bỏ qua hoàn toàn bước gọi LLM sinh văn bản, trả về ngay bot response.
