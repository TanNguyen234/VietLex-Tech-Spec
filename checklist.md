# BẢNG CHECKLIST TIẾN ĐỘ DỰ ÁN (VIETLEX LEGAL RAG)

Bảng theo dõi các đầu việc đã hoàn thành, cần làm và sẽ làm trong dự án Vietlex Advanced Legal RAG.

---

## 🟩 ĐÃ HOÀN THÀNH (DONE)

- [x] **Thiết lập Cấu trúc dự án**: Tổ chức thư mục theo mô hình Clean Architecture (`app/`, `app/api/`, `app/services/`, `app/ingestion/`, `app/templates/`).
- [x] **Cấu hình Hệ thống**: Định nghĩa `Settings` qua Pydantic `BaseSettings` để quản lý biến môi trường trong file `.env` ([config.py](file:///d:/Download/ProfessionalLegalRAG/app/config.py)).
- [x] **Giám sát & Tracing**: Tích hợp Pydantic Logfire để đo đạc và trace các FastAPI endpoint ([main.py](file:///d:/Download/ProfessionalLegalRAG/app/main.py)).
- [x] **Bảo mật Request**:
  - [x] Giới hạn Rate Limit `POST /chat` ở mức tối đa 5 request/phút/IP bằng thư viện `slowapi`.
  - [x] Cấu hình CORS middleware chỉ cho phép domain chỉ định ở `FRONTEND_URL`.
  - [x] Triển khai bảo mật CSRF: sinh token khi `GET /` và validate tại `POST /chat` qua dependency `verify_csrf`.
- [x] **Dữ liệu Ingestion cơ bản**:
  - [x] Script tải dataset pháp luật mẫu từ Hugging Face (`NamSyntax/Vietnamese-Legal-QA-RAG`).
  - [x] Gọi OmniGate Embedding sinh vector 768 chiều cho dữ liệu văn bản.
  - [x] Xử lý lỗi 429 (Rate Limit) khi gọi API Embedding bằng cơ chế exponential backoff.
  - [x] Tạo mới collection và upsert dữ liệu thành công lên Qdrant Cloud ([qdrant_indexer.py](file:///d:/Download/ProfessionalLegalRAG/app/ingestion/qdrant_indexer.py)).
- [x] **Giao diện Người dùng cơ bản**: Giao diện chat bất đồng bộ sử dụng Jinja2 templates tích hợp HTMX và TailwindCSS ([index.html](file:///d:/Download/ProfessionalLegalRAG/app/templates/index.html)).

---

## 🟨 CẦN LÀM (TODO - KHÔNG MOCK)

- [ ] **Hoàn thiện RAG Retrieval (`rag_pipeline.py`)**:
  - [ ] Gọi OmniGate rewrite query sang thuật ngữ pháp lý.
  - [ ] Kết nối `QdrantClient` để thực hiện Dense Search thực tế (lấy Top 15).
  - [ ] Triển khai Sparse Search thực tế sử dụng BM25 kết hợp tách từ tiếng Việt bằng `PyVi` (lấy Top 15).
  - [ ] Viết hàm tính điểm Reciprocal Rank Fusion (RRF) để trộn Dense & Sparse.
  - [ ] Tích hợp API Cohere Reranker (`rerank-multilingual-v3.0`) để lấy Top 3.
  - [ ] Inject context vào prompt LangChain, gọi model `legal-core-model` qua OmniGate để sinh câu trả lời.
- [ ] **Hoàn thiện Semantic Caching (`semantic_cache.py`)**:
  - [ ] Gọi embedding sinh vector cho query mới.
  - [ ] Truy vấn Qdrant collection `vietlex_semantic_cache`, kiểm tra score >= 0.96.
  - [ ] Viết logic lưu query + vector + response thực tế vào cache collection sau mỗi lượt chat.
- [ ] **Tích hợp Guardrails (`guardrails.py`)**:
  - [ ] Viết file config (`config.yml`, `prompts.yml`) cho NVIDIA NeMo Guardrails.
  - [ ] Gọi Guardrails kiểm duyệt Input và Output thực tế (bỏ qua mock).
- [ ] **Hoàn thiện Evaluator (`evaluator.py`)**:
  - [ ] Gọi Ragas API đánh giá các chỉ số Faithfulness, Answer Relevance, Context Recall dưới dạng background task.
- [ ] **Hoàn thiện Parser Tài liệu (`parser.py`, `indexer.py`)**:
  - [ ] Regex parser hoàn chỉnh phân tách file luật thô theo cấu trúc Chương -> Mục -> Điều.

---

## 🟦 SẼ LÀM (FUTURE OPTIMIZATIONS)

- [ ] **Tối ưu hóa Hiệu năng**: Song song hóa các luồng gọi API (Dense Search, Sparse Search) để giảm latency.
- [ ] **Kiểm thử tự động**: Viết bộ test suite (pytest) kiểm tra hoạt động của RAG Pipeline, Cache, Parser.
- [ ] **Giám sát nâng cao**: Xây dựng dashboard Logfire theo dõi chất lượng câu trả lời (Ragas score) và tỷ lệ hit cache theo thời gian thực.
