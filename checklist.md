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
  - [x] Sửa đổi và sửa lỗi cú pháp gọi `TemplateResponse` cho Starlette 1.3+ trong `app/main.py` và `app/api/routes.py`.
- [x] **Dữ liệu Ingestion**:
  - [x] Tải dataset pháp luật mẫu từ Hugging Face (`NamSyntax/Vietnamese-Legal-QA-RAG`).
  - [x] Gọi OmniGate Embedding sinh vector 768 chiều cho dữ liệu văn bản.
  - [x] Xử lý lỗi 429 (Rate Limit) khi gọi API Embedding bằng cơ chế exponential backoff.
  - [x] Tạo mới collection và upsert dữ liệu thành công lên Qdrant Cloud ([qdrant_indexer.py](file:///d:/Download/ProfessionalLegalRAG/app/ingestion/qdrant_indexer.py)).
  - [x] Parser Regex hoàn chỉnh phân tách file luật thô theo cấu trúc Chương -> Mục -> Điều ([parser.py](file:///d:/Download/ProfessionalLegalRAG/app/ingestion/parser.py)).
  - [x] Segment tiếng Việt (PyVi) và lập chỉ mục kết hợp đồng bộ hóa Dense & Sparse Vectors lên Qdrant ([indexer.py](file:///d:/Download/ProfessionalLegalRAG/app/ingestion/indexer.py)).
- [x] **Semantic Cache**:
  - [x] Gọi embedding sinh vector cho query mới.
  - [x] Kiểm tra hit/miss bộ nhớ đệm với ngưỡng similarity score >= 0.96 sử dụng phương thức `query_points` bất đồng bộ của Qdrant.
  - [x] Tự động lưu cặp câu hỏi - trả lời mới vào Qdrant cache sau mỗi lượt chat ([semantic_cache.py](file:///d:/Download/ProfessionalLegalRAG/app/services/semantic_cache.py)).
- [x] **RAG Retrieval Pipeline**:
  - [x] Gọi OmniGate rewrite query sang thuật ngữ pháp lý.
  - [x] Thực hiện Dense Search thực tế trên Qdrant (lấy Top 15).
  - [x] Thực hiện Sparse Search thực tế dùng hàm băm từ vựng kết hợp PyVi segmentation trên Qdrant (lấy Top 15).
  - [x] Tính toán Reciprocal Rank Fusion (RRF) để trộn Dense & Sparse.
  - [x] Rerank bằng Cohere API (`rerank-multilingual-v3.0`) để lấy Top 3.
  - [x] Sinh câu trả lời qua model `legal-core-model` sử dụng prompt template trên OmniGate ([rag_pipeline.py](file:///d:/Download/ProfessionalLegalRAG/app/services/rag_pipeline.py)).
- [x] **Safety Guardrails**:
  - [x] Triển khai bộ kiểm duyệt Input (jailbreak, off-topic) sử dụng model LLM OmniGate.
  - [x] Triển khai bộ kiểm duyệt Output (hallucination check) đối chiếu câu trả lời với các điều luật được truy xuất ([guardrails.py](file:///d:/Download/ProfessionalLegalRAG/app/services/guardrails.py)).
- [x] **Ragas Evaluator**:
  - [x] Cài đặt và cấu hình Ragas với `ChatOpenAI` và `OpenAIEmbeddings` trỏ tới LLM Gateway.
  - [x] Đánh giá các chỉ số `faithfulness` và `answer_relevancy` dưới dạng background task bất đồng bộ thông qua `asyncio.to_thread` ([evaluator.py](file:///d:/Download/ProfessionalLegalRAG/app/services/evaluator.py)).
- [x] **Giao diện Người dùng cơ bản**: Giao diện chat bất đồng bộ sử dụng Jinja2 templates tích hợp HTMX và TailwindCSS ([index.html](file:///d:/Download/ProfessionalLegalRAG/app/templates/index.html)).

---

## 🟨 CẦN LÀM (TODO)

- [ ] Không còn nhiệm vụ mock nào chưa giải quyết. Tất cả core pipeline đã được triển khai thực tế.

---

## 🟦 SẼ LÀM (FUTURE OPTIMIZATIONS)

- [ ] **Tối ưu hóa Hiệu năng**: Song song hóa các luồng gọi API (Dense Search, Sparse Search) để giảm latency.
- [ ] **Kiểm thử tự động**: Viết bộ test suite (pytest) kiểm tra tự động hoạt động của các module chính.
- [ ] **Giám sát nâng cao**: Xây dựng dashboard Logfire theo dõi chất lượng câu trả lời và tỷ lệ hit cache theo thời gian thực.
