# Hướng dẫn Phát triển & Thiết lập Hệ thống Vietlex Legal RAG

Dự án **VIETLEX (ADVANCED LEGAL RAG)** được xây dựng theo Clean Architecture dùng FastAPI, Qdrant, Guardrails, Logfire, và HTMX.

---

## 🛠️ THIẾT LẬP MÔI TRƯỜNG & XÁC THỰC

### 1. Cấu hình file `.env`
Tạo file `.env` ở thư mục gốc:
```bash
HOST=0.0.0.0
PORT=8000
FRONTEND_URL=http://localhost:3000

# Qdrant Cloud Vector Database
QDRANT_URL=https://your-qdrant-cluster.cloud.qdrant.io
QDRANT_API_KEY=your_qdrant_api_key

# Cohere API Key (Reranker)
COHERE_API_KEY=your_cohere_api_key

# LLM Gateway (OmniGate)
OMNIGATE_BASE_URL=http://localhost:8000/v1
OMNIGATE_API_KEY=your_litellm_master_key

# Tracing (Logfire)
LOGFIRE_TOKEN=your_logfire_token
```

### 2. Thiết lập Môi trường ảo Python
```bash
# Khởi tạo venv
python -m venv .venv

# Kích hoạt venv (Windows Powershell)
.venv\Scripts\Activate.ps1

# Cài đặt thư viện
pip install -r requirements.txt
```

---

## 📁 CẤU TRÚC THƯ MỤC CHI TIẾT

```text
vietlex-rag/
├── app/
│   ├── main.py                # Điểm khởi chạy, cấu hình Middlewares & Logfire.
│   ├── config.py              # Load & validate biến môi trường qua Pydantic Settings.
│   ├── api/
│   │   ├── routes.py          # Endpoint /chat (HTMX) và /api/feedback.
│   │   └── dependencies.py    # Verify CSRF Token.
│   ├── services/
│   │   ├── rag_pipeline.py    # LLM Query Rewrite, Hybrid Search, RRF, Cohere Rerank.
│   │   ├── semantic_cache.py  # Cache vector trên Qdrant (similarity >= 0.96).
│   │   ├── guardrails.py      # NeMo Guardrails check Input/Output.
│   │   └── evaluator.py       # Tác vụ nền đánh giá Ragas.
│   ├── ingestion/
│   │   ├── parser.py          # Tách văn bản luật thành Chương -> Mục -> Điều.
│   │   ├── indexer.py         # PyVi Tokenizer & đồng bộ hóa Qdrant.
│   │   └── qdrant_indexer.py  # Script import dataset mẫu lên Qdrant.
│   └── templates/
│       ├── index.html         # Giao diện khung chat.
│       └── chat_message.html  # Template tin nhắn HTMX.
├── guardrails_config/         # Cấu hình NeMo Guardrails.
├── requirements.txt
└── .env
```

---

## 🚀 QUY TRÌNH HOẠT ĐỘNG CỦA REQUEST
Mỗi request `POST /chat` trải qua 9 bước:
1. **CSRF & Rate Limit Validation**: Xác thực token CSRF và check rate limit (5/phút).
2. **Semantic Cache Lookup**: Tìm kiếm vector trên Qdrant. Hit (score >= 0.96) -> Trả về ngay.
3. **Input Guardrails Check**: NeMo check tính an toàn của câu hỏi.
4. **Advanced Retrieval Pipeline**: LLM Rewrite -> Hybrid Search (Dense + Sparse PyVi) -> RRF Fusion -> Cohere Rerank -> LLM Generation.
5. **Output Guardrails Check**: NeMo check câu trả lời tránh ảo giác.
6. **Save Cache**: Lưu cặp câu hỏi - trả lời mới vào Semantic Cache.
7. **Generate Trace ID**: Logfire tracing cho request.
8. **Trigger Background Task**: Gọi Evaluator đánh giá Ragas bất đồng bộ.
9. **Return HTML Partial**: Trả về `chat_message.html` cập nhật UI.
