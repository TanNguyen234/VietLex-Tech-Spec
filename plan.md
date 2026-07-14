# TECHNICAL SPECIFICATION: VIETLEX (ADVANCED LEGAL RAG)

Tài liệu thiết kế kỹ thuật và trạng thái triển khai dự án Vietlex Legal RAG.

---

## 1. Kiến trúc Hệ thống & Công nghệ
- **Backend**: FastAPI, Uvicorn, Slowapi (Rate Limiting)
- **Giám sát**: Pydantic Logfire (Tracing & Logging)
- **Vector Database**: Qdrant Cloud (Knowledge Base & Semantic Cache)
- **LLM Gateway**: OmniGate (LangChain OpenAI client / embeddings)
- **Advanced RAG**: Cohere Rerank API, NeMo Guardrails, PyVi Tokenizer
- **Đánh giá**: Ragas (LLM-as-a-judge, chạy dưới dạng background task)
- **Frontend**: Jinja2, HTMX, TailwindCSS

---

## 2. Luồng Logic Xử lý (Logic Flows)

### Flow 1: Semantic Caching (`app/services/semantic_cache.py`)
1. Nhận `user_query`, gọi OmniGate `text-embedding-004` sinh vector 768-dim.
2. Tìm kiếm trong Qdrant collection `vietlex_semantic_cache` (limit=1).
3. Nếu similarity score >= **0.96**: Trả về `bot_response` đã cache.
4. Nếu không: Trả về `None` (cache miss).

### Flow 2: Advanced Retrieval Pipeline (`app/services/rag_pipeline.py`)
1. **Query Rewrite**: LLM rewrite câu hỏi của user sang thuật ngữ pháp lý chuẩn.
2. **Hybrid Search**:
   - Dense Search: Tìm kiếm vector (`text-embedding-004`) trên Qdrant -> Top 15.
   - Sparse Search: Tìm kiếm BM25 (dữ liệu tách từ bởi PyVi) -> Top 15.
3. **RRF Fusion**: Áp dụng Reciprocal Rank Fusion kết hợp kết quả Dense & Sparse -> Top 15.
4. **Reranking**: Gọi Cohere API `rerank-multilingual-v3.0` -> Lọc ra Top 3.
5. **LLM Generation**: Format Top 3 vào prompt template, gọi model `legal-core-model` qua OmniGate sinh câu trả lời.

### Flow 3: Request Lifecycle với Guardrails & Evals (`app/api/routes.py`)
1. Nhận form request `POST /chat`. Kiểm tra CSRF Token và Rate Limiting.
2. Check Semantic Cache. Nếu hit -> Trả về kết quả ngay.
3. Apply NeMo Input Guardrails. Nếu vi phạm an toàn -> Trả về từ chối.
4. Chạy Advanced Retrieval Pipeline -> Nhận `(bot_response, context_used)`.
5. Apply NeMo Output Guardrails. Nếu phát hiện ảo giác -> Trả về fallback safe.
6. Ghi interaction mới vào Semantic Cache (background task).
7. Trigger Background Task: Chạy Ragas Evaluator đánh giá chất lượng câu trả lời.
8. Trả về HTML partial `chat_message.html` qua Jinja2.

---

## 3. Bảng Checklist Tiến độ Dự án

| Module / Tính năng | Nhiệm vụ chi tiết | Trạng thái | File ảnh hưởng |
| :--- | :--- | :---: | :--- |
| **Hạ tầng & Setup** | Thiết lập cấu trúc thư mục Clean Architecture | `ĐÃ LÀM` | `app/` |
| | Cấu hình biến môi trường và BaseSettings | `ĐÃ LÀM` | [config.py](file:///d:/Download/ProfessionalLegalRAG/app/config.py) |
| | Tích hợp Logfire tracing cho FastAPI | `ĐÃ LÀM` | [main.py](file:///d:/Download/ProfessionalLegalRAG/app/main.py) |
| **Bảo mật Request** | Giới hạn Rate Limiting 5 request/phút/IP | `ĐÃ LÀM` | [main.py](file:///d:/Download/ProfessionalLegalRAG/app/main.py) |
| | CORS Middleware giới hạn theo domain | `ĐÃ LÀM` | [main.py](file:///d:/Download/ProfessionalLegalRAG/app/main.py) |
| | CSRF Protection sinh & xác thực token | `ĐÃ LÀM` | [routes.py](file:///d:/Download/ProfessionalLegalRAG/app/api/routes.py), [dependencies.py](file:///d:/Download/ProfessionalLegalRAG/app/api/dependencies.py) |
| **Ingestion Pipeline**| Tải dataset mẫu từ Hugging Face | `ĐÃ LÀM` | [qdrant_indexer.py](file:///d:/Download/ProfessionalLegalRAG/app/ingestion/qdrant_indexer.py) |
| | Gọi OmniGate sinh embedding, giải quyết rate limit 429 | `ĐÃ LÀM` | [qdrant_indexer.py](file:///d:/Download/ProfessionalLegalRAG/app/ingestion/qdrant_indexer.py) |
| | Upsert dữ liệu pháp luật hoàn chỉnh lên Qdrant | `ĐÃ LÀM` | [qdrant_indexer.py](file:///d:/Download/ProfessionalLegalRAG/app/ingestion/qdrant_indexer.py) |
| | Parser tách văn bản thô theo Chương/Mục/Điều | `CẦN LÀM` (Đang Mock) | [parser.py](file:///d:/Download/ProfessionalLegalRAG/app/ingestion/parser.py) |
| | Segment tiếng Việt (PyVi) + Indexer tự động | `CẦN LÀM` (Đang Mock) | [indexer.py](file:///d:/Download/ProfessionalLegalRAG/app/ingestion/indexer.py) |
| **Semantic Cache** | Gọi embedding, truy vấn similarity >= 0.96 trên Qdrant | `CẦN LÀM` (Đang Mock) | [semantic_cache.py](file:///d:/Download/ProfessionalLegalRAG/app/services/semantic_cache.py) |
| | Lưu cặp câu hỏi - trả lời mới vào Qdrant cache | `CẦN LÀM` (Đang Mock) | [semantic_cache.py](file:///d:/Download/ProfessionalLegalRAG/app/services/semantic_cache.py) |
| **RAG Pipeline** | Query Rewrite bằng LLM qua OmniGate | `CẦN LÀM` (Đang Mock) | [rag_pipeline.py](file:///d:/Download/ProfessionalLegalRAG/app/services/rag_pipeline.py) |
| | Thực hiện Dense Search thực tế trên Qdrant | `CẦN LÀM` (Đang Mock) | [rag_pipeline.py](file:///d:/Download/ProfessionalLegalRAG/app/services/rag_pipeline.py) |
| | Thực hiện Sparse Search thực tế kết hợp PyVi | `CẦN LÀM` (Đang Mock) | [rag_pipeline.py](file:///d:/Download/ProfessionalLegalRAG/app/services/rag_pipeline.py) |
| | Triển khai thuật toán RRF Fusion | `CẦN LÀM` (Đang Mock) | [rag_pipeline.py](file:///d:/Download/ProfessionalLegalRAG/app/services/rag_pipeline.py) |
| | Gọi Cohere API `rerank-multilingual-v3.0` | `CẦN LÀM` (Đang Mock) | [rag_pipeline.py](file:///d:/Download/ProfessionalLegalRAG/app/services/rag_pipeline.py) |
| | Sinh câu trả lời qua model `legal-core-model` | `CẦN LÀM` (Đang Mock) | [rag_pipeline.py](file:///d:/Download/ProfessionalLegalRAG/app/services/rag_pipeline.py) |
| **Guardrails** | Cấu hình file YAML cho NVIDIA NeMo | `CẦN LÀM` (Đang Mock) | `guardrails_config/` |
| | Tích hợp gọi check Input & Output thực tế | `CẦN LÀM` (Đang Mock) | [guardrails.py](file:///d:/Download/ProfessionalLegalRAG/app/services/guardrails.py) |
| **Evaluator** | Tích hợp thư viện Ragas chạy offline/background | `CẦN LÀM` (Đang Mock) | [evaluator.py](file:///d:/Download/ProfessionalLegalRAG/app/services/evaluator.py) |
| | Tính các chỉ số Faithfulness, Answer Relevance, Context Recall | `CẦN LÀM` (Đang Mock) | [evaluator.py](file:///d:/Download/ProfessionalLegalRAG/app/services/evaluator.py) |
| **Frontend UI** | Dựng giao diện chat cơ bản với HTMX + Tailwind | `ĐÃ LÀM` | [index.html](file:///d:/Download/ProfessionalLegalRAG/app/templates/index.html) |
| | Cải thiện UX/UI nâng cao, xử lý loading state | `SẼ LÀM` | [index.html](file:///d:/Download/ProfessionalLegalRAG/app/templates/index.html) |
| **Tối ưu & Vận hành**| Song song hóa truy vấn Dense & Sparse Search | `SẼ LÀM` | [rag_pipeline.py](file:///d:/Download/ProfessionalLegalRAG/app/services/rag_pipeline.py) |
| | Viết bộ kiểm thử tự động pytest | `SẼ LÀM` | `tests/` |
| | Dashboard giám sát Logfire nâng cao | `SẼ LÀM` | Logfire Cloud |
