# AGENTS.md - Quy tắc Vận hành cho AI Coding Agents (Vietlex Legal RAG)

Tài liệu này định nghĩa các nguyên tắc phát triển bắt buộc mà mọi AI Agent phải tuân thủ nghiêm ngặt khi xây dựng, sửa đổi mã nguồn hoặc triển khai các tính năng trong dự án `vietlex-rag`.

---

## 🚨 BẮT BUỘC: QUY TẮC NỀN TẢNG (CORE POLICIES)

### 1. BẢO MẬT & GATEWAY AUTHENTICATION
- **Nghiêm cấm** hardcode các API Key (ví dụ: `QDRANT_API_KEY`, `COHERE_API_KEY`, `OMNIGATE_API_KEY`). Mọi biến môi trường phải được tải thông qua `app/config.py` sử dụng Pydantic `BaseSettings`.
- LangChain LLM client bắt buộc phải truyền `LITELLM_MASTER_KEY` trong headers/credentials để xác thực khi kết nối với cổng OmniGate.

### 2. TUÂN THỦ KIẾN TRÚC SẠCH (CLEAN ARCHITECTURE COMPLIANCE)
Dự án được phân rã theo cấu trúc Kiến trúc Sạch (Clean Architecture). AI Agent không được tùy ý tạo file ngoài các layer đã được quy định:
- **`app/main.py`**: Điểm khởi chạy FastAPI, cấu hình Middleware, Rate Limiting, và Logfire.
- **`app/api/`**: Chứa router và dependencies. Logic xử lý request/response và CORS/CSRF.
- **`app/services/`**: Chứa core business logic (RAG pipeline, Semantic Cache, Guardrails, Evaluator).
- **`app/ingestion/`**: Chứa parser văn bản luật và indexer lên Qdrant.
- **`app/templates/`**: Chứa HTMX templates (`index.html`, `chat_message.html`).

### 3. THỰC THI BẢO MẬT REQUEST (MIDDLEWARE & LIMITING)
- **CORS**: Chỉ cho phép domain được cấu hình qua biến môi trường `FRONTEND_URL`.
- **Rate Limiting**: Sử dụng `slowapi`. Giới hạn endpoint `POST /chat` ở mức tối đa **5 requests/phút trên mỗi IP**.
- **CSRF Protection**: Token bảo mật phải được tạo khi `GET /` và được validate nghiêm ngặt trong `POST /chat`.

### 4. LOGIC PIPELINES BẮT BUỘC
- **Semantic Cache (Flow 1)**: Vector search với embedding `text-embedding-004` trên collection `vietlex_semantic_cache`. Chỉ chấp nhận hit cache khi score >= **0.96**.
- **Advanced Retrieval (Flow 2)**:
  1. Sử dụng LLM rewrite query sang thuật ngữ pháp lý chính thống.
  2. Thực hiện Hybrid Search (Dense: `text-embedding-004` [Top 15] + Sparse: BM25 phân tách từ bởi PyVi [Top 15]).
  3. Hợp nhất bằng Reciprocal Rank Fusion (RRF) -> Lấy Top 15.
  4. Rerank bằng Cohere `rerank-multilingual-v3.0` -> Lấy Top 3.
  5. Đưa Top 3 chunks vào prompt template LangChain để sinh câu trả lời qua model `legal-core-model`.
- **Guardrails & Evaluation (Flow 3)**:
  - Input Check (NeMo Guardrails) -> Advanced Retrieval -> Output Check (NeMo Guardrails).
  - Kích hoạt Evaluator (Ragas) chạy dưới dạng background task sau khi hoàn thành sinh câu trả lời.

### 5. GIÁM SÁT HIỆU NĂNG (OBSERVABILITY)
- Phải khởi tạo Logfire trong `main.py`: `logfire.configure()` và `logfire.instrument_fastapi(app)`.
- Sử dụng decorator `@logfire.instrument` cho mọi hàm chính trong `app/services/` để đo lường độ trễ (latency tracking).

---

## 🗺️ BẢN ĐỒ SỔ TAY CHUYÊN MÔN
AI Agent chỉ được tải các tài liệu hướng dẫn khi thực sự xử lý tác vụ tương ứng:
- **Hướng dẫn API & Config**: [instructions.md](file:///d:/Download/ProfessionalLegalRAG/instructions.md)
- **Sơ đồ Kiến trúc & Logic Flows**: [architecture/architecture.md](file:///d:/Download/ProfessionalLegalRAG/architecture/architecture.md)
