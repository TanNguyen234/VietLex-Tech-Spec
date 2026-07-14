# AGENTS.md - Quy tắc Vận hành AI Agent (Vietlex Legal RAG)

Tài liệu này chứa các quy tắc phát triển bắt buộc khi chỉnh sửa mã nguồn hoặc triển khai tính năng trong `vietlex-rag`.

---

## 🚨 QUY TẮC BẮT BUỘC (CORE POLICIES)

### 1. BẢO MẬT & XÁC THỰC
- **Không hardcode API Key** (`QDRANT_API_KEY`, `COHERE_API_KEY`, `OMNIGATE_API_KEY`). Load qua `app/config.py` (sử dụng Pydantic `BaseSettings`).
- API client gọi OmniGate phải truyền `LITELLM_MASTER_KEY` (hoặc `OMNIGATE_API_KEY`) trong header Authorization Bearer.

### 2. KIẾN TRÚC SẠCH (CLEAN ARCHITECTURE)
Tuyệt đối không tạo file ngoài các layer quy định:
- `app/main.py`: Khởi chạy FastAPI, Middleware, Rate Limiting, Logfire.
- `app/api/`: Router (`routes.py`) và Dependencies (`dependencies.py`).
- `app/services/`: Core logic:
  - `rag_pipeline.py`: RAG logic, query rewriter, hybrid search, RRF, Reranker.
  - `semantic_cache.py`: Logic check/save cache vector.
  - `guardrails.py`: NeMo Guardrails check.
  - `evaluator.py`: Đánh giá Ragas (background task).
- `app/ingestion/`: Parser luật và Qdrant indexer.
- `app/templates/`: HTMX templates (`index.html`, `chat_message.html`).

### 3. BẢO MẬT HTTP REQUEST
- **CORS**: Chỉ cho phép domain cấu hình trong `FRONTEND_URL`.
- **Rate Limiting**: Giới hạn `POST /chat` tối đa **5 requests/phút/IP** (dùng `slowapi`).
- **CSRF**: Tạo token tại `GET /`, validate nghiêm ngặt trong `POST /chat`.

### 4. THÔNG SỐ PIPELINE BẮT BUỘC
- **Semantic Cache**:
  - Vector search `text-embedding-004` trên collection `vietlex_semantic_cache`.
  - Chỉ chấp nhận hit cache khi similarity score >= **0.96**.
- **Retrieval & RAG**:
  - Rewrite query bằng LLM.
  - Hybrid Search Qdrant: Dense (`text-embedding-004`, Top 15) + Sparse (BM25 với PyVi segmentation, Top 15).
  - Hợp nhất RRF (Reciprocal Rank Fusion) -> Lấy Top 15.
  - Rerank qua Cohere `rerank-multilingual-v3.0` -> Lấy Top 3.
  - Sinh câu trả lời qua model `legal-core-model` trên OmniGate.
- **Guardrails & Evaluation**:
  - Input Check -> RAG -> Output Check (dùng NeMo Guardrails).
  - Chạy đánh giá Ragas dưới dạng background task.

### 5. GIÁM SÁT (OBSERVABILITY)
- Cấu hình Logfire trong `main.py`.
- Sử dụng `@logfire.instrument` cho mọi hàm xử lý chính trong `app/services/` để đo độ trễ.

### 6. KHÔNG MOCK TRONG PRODUCTION (PRODUCTION-GRADE EXECUTION)
- **Tuyệt đối không sử dụng mock/placeholder** cho các module cốt lõi (Semantic Cache, RAG pipeline, Guardrails, Evaluator, Parser) khi triển khai thực tế. Mọi logic phải gọi API thực, kết nối Qdrant/Cohere thực và xử lý lỗi hoàn chỉnh.


---

## 🗺️ TÀI LIỆU THAM KHẢO
- **Thiết lập & Cấu hình**: [instructions.md](file:///d:/Download/ProfessionalLegalRAG/instructions.md)
- **Sơ đồ chi tiết & Kế hoạch**: [plan.md](file:///d:/Download/ProfessionalLegalRAG/plan.md)
