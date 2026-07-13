# Hướng dẫn Phát triển & Thiết lập Hệ thống Vietlex Legal RAG

Chào mừng bạn đến với không gian phát triển dự án **VIETLEX (ADVANCED LEGAL RAG)**. Hệ thống này được thiết kế theo cấu trúc Kiến trúc Sạch (Clean Architecture) sử dụng FastAPI, Qdrant, Guardrails, Logfire và HTMX.

---

## 🛠️ Thiết lập Môi trường & Xác thực

### 1. Cấu hình Biến môi trường (.env)
Tạo file `.env` ở thư mục gốc của dự án với các biến môi trường sau:
```bash
# Cổng API chính (FastAPI)
HOST=0.0.0.0
PORT=8000
FRONTEND_URL=http://localhost:3000

# Vector Database (Qdrant Cloud)
QDRANT_URL=https://your-qdrant-cluster.cloud.qdrant.io
QDRANT_API_KEY=your_qdrant_api_key

# Reranker (Cohere API)
COHERE_API_KEY=your_cohere_api_key

# Cổng LLM Gateway (OmniGate)
OMNIGATE_BASE_URL=http://localhost:8000/v1
OMNIGATE_API_KEY=your_litellm_master_key # Khớp với LITELLM_MASTER_KEY

# Tracing & Logging (Logfire)
LOGFIRE_TOKEN=your_logfire_token
```

### 2. Thiết lập Môi trường ảo Python
Khởi tạo và cài đặt các thư viện cần thiết:
```bash
# Tạo virtual environment
python -m venv .venv

# Kích hoạt virtual environment (Windows Powershell)
.venv\Scripts\Activate.ps1

# Cài đặt dependencies từ requirements.txt
pip install -r requirements.txt
```

---

## 📁 Cấu trúc Thư mục Chi tiết

- `app/`: Thư mục chính chứa mã nguồn ứng dụng FastAPI.
  - `main.py`: Điểm khởi chạy, cấu hình middlewares (CORS, slowapi, CSRF), và tích hợp Pydantic Logfire.
  - `config.py`: Định nghĩa Pydantic `BaseSettings` để tải và kiểm tra kiểu dữ liệu các biến môi trường.
  - `api/`: Xử lý HTTP request-response.
    - `routes.py`: Endpoint `/chat` (giao tiếp HTMX) và `/api/feedback`.
    - `dependencies.py`: Dependency injection để xác thực người dùng và áp dụng rate limiter.
  - `services/`: Core logic của hệ thống.
    - `rag_pipeline.py`: Logic truy xuất nâng cao, query rewriter, hybrid search và RRF fusion.
    - `semantic_cache.py`: Quản lý lưu trữ/truy vấn semantic cache trên Qdrant với ngưỡng độ tương đồng >= 0.96.
    - `guardrails.py`: Cấu hình và kích hoạt NeMo Guardrails để kiểm tra input/output.
    - `evaluator.py`: Tác vụ nền (background task) chạy đánh giá Ragas dưới dạng LLM-as-a-judge.
  - `ingestion/`: Layer tiền xử lý dữ liệu.
    - `parser.py`: Phân tách văn bản luật theo cấu trúc (Chương -> Mục -> Điều).
    - `indexer.py`: Sử dụng PyVi phân tách từ tiếng Việt và đồng bộ hóa (upsert) lên Qdrant.
  - `templates/`: Giao diện người dùng sử dụng Jinja2 + HTMX.
    - `index.html`: Giao diện chính chứa khung chat.
    - `chat_message.html`: Template phản hồi tin nhắn dạng partial htmx.

- `guardrails_config/`: Cấu hình bảo mật và an toàn cho AI.
  - `config.yml`: Quy định luồng hoạt động chính của NeMo.
  - `prompts.yml`: Cấu hình prompts kiểm tra an toàn hệ thống.

---

## 🚀 Quy trình Hoạt động của Request
Mọi request gửi tới endpoint `POST /chat` sẽ trải qua vòng đời sau:
1. **CSRF Validation & Rate Limiting**: Xác thực CSRF Token và slowapi limiter (5/phút).
2. **Semantic Cache Lookup**: Nếu khớp với score >= 0.96, trả về kết quả ngay lập tức và sinh Logfire trace.
3. **Input Guardrails Check**: Kiểm tra tính an toàn thông tin qua NeMo.
4. **Advanced Retrieval Pipeline (RAG)**: LLM Query Rewrite -> Hybrid Search (Dense + Sparse PyVi) -> RRF Fusion -> Cohere Reranker (Multilingual v3) -> LLM Generation.
5. **Output Guardrails Check**: Kiểm tra câu trả lời sinh ra có bị ảo giác (hallucination) hay độc hại không.
6. **Save Cache & Evaluate**: Lưu phản hồi vào Semantic Cache và kích hoạt Background Task gọi Ragas đánh giá chất lượng câu trả lời.
7. **HTML Partial Return**: Trả về `chat_message.html` qua Jinja2 cho frontend cập nhật.
