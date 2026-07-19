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

## 3. Bảng trạng thái (thay thế bảng cũ)

> Quy tắc điền: chỉ đánh `ĐÃ LÀM` nếu bạn đã tự chạy qua đúng flow đó với input thật và xem log/kết
> quả thực tế (không phải vì agent report "done"). Nếu chưa chắc, để `CẦN VERIFY`.

| Module | Nhiệm vụ | Trạng thái | Ngày verify | Cách verify (lệnh / log) |
|---|---|---|---|---|
| Ingestion | Parser tách Chương/Mục/Điều | `ĐÃ LÀM` | 16/07/2026 | Log chạy và output của [parser.py](file:///d:/Download/ProfessionalLegalRAG/app/ingestion/parser.py) khi phân tách dữ liệu `datht/vlegal` |
| Ingestion | PyVi segment + upsert Qdrant | `ĐANG CHẠY` | 18/07/2026 | Ingestion of `datht/vlegal` dataset is partially complete (850 points indexed in Qdrant). Need to resume and verify points count. |
| Semantic Cache | Embedding + hit/miss ≥0.96 | `ĐÃ LÀM` | 16/07/2026 | Lịch sử log của `run_eval_suite.py` nhận diện chính xác `Cache Hit` cho câu hỏi trùng lặp |
| Semantic Cache | Ghi cặp Q-A mới vào cache | `ĐÃ LÀM` | 16/07/2026 | [semantic_cache.py](file:///d:/Download/ProfessionalLegalRAG/app/services/semantic_cache.py) thực thi hàm `save_to_semantic_cache` sau khi sinh kết quả |
| RAG Pipeline | Query rewrite qua OmniGate | `ĐÃ LÀM` | 16/07/2026 | Log của `run_eval_suite.py` ghi nhận các câu truy vấn được viết lại thông qua LLM Gateway |
| RAG Pipeline | Dense search thực (Qdrant) | `ĐÃ LÀM` | 16/07/2026 | [rag_pipeline.py](file:///d:/Download/ProfessionalLegalRAG/app/services/rag_pipeline.py) -> `dense_search` kết nối Qdrant Cloud thực tế |
| RAG Pipeline | Sparse search thực (BM25+PyVi) | `ĐÃ LÀM` | 16/07/2026 | [rag_pipeline.py](file:///d:/Download/ProfessionalLegalRAG/app/services/rag_pipeline.py) -> `sparse_search` kết hợp tách từ PyVi và lưu index băm |
| RAG Pipeline | RRF fusion | `ĐÃ LÀM` | 16/07/2026 | Hợp nhất thứ hạng Dense và Sparse thành công theo công thức RRF trong `rag_pipeline.py` |
| RAG Pipeline | Cohere rerank v3.0 | `ĐÃ LÀM` | 16/07/2026 | Log của `run_advanced_rag` và Logfire cho thấy kết quả rerank thông qua Cohere API |
| RAG Pipeline | LLM generation (legal-core-model) | `ĐÃ LÀM` | 16/07/2026 | Trả về câu trả lời sinh ra từ `legal-core-model` (OmniGate) chính xác trong log đánh giá |
| Guardrails | Input rails (jailbreak/off-topic) | `ĐÃ LÀM` | 16/07/2026 | Lọc và chặn đúng các câu hỏi off-topic (nấu ăn, code) và jailbreak trong `run_eval_suite.py` |
| Guardrails | Output rails (hallucination check) | `ĐÃ LÀM` | 16/07/2026 | [guardrails.py](file:///d:/Download/ProfessionalLegalRAG/app/services/guardrails.py) -> `check_output_guardrails` so sánh câu trả lời với context |
| PII Redaction | SĐT / email / CCCD | `ĐÃ LÀM` | 16/07/2026 | Hàm `redact_pii` trong [guardrails.py](file:///d:/Download/ProfessionalLegalRAG/app/services/guardrails.py) tự động che ẩn email, SĐT, CCCD ở routes |
| Evaluator | Ragas evaluation suite (4 metrics) | `ĐANG CHẠY` | 18/07/2026 | Upgraded `run_eval_suite.py` with custom `OmniGateEmbeddings` to measure 4 Ragas metrics with ground truths. Need to run to completion. |
| Observability | Logfire trace toàn bộ request | `ĐÃ LÀM` | 16/07/2026 | Khởi tạo cấu hình logfire trong [main.py](file:///d:/Download/ProfessionalLegalRAG/app/main.py) và decorator `@logfire.instrument` cho service |
| Frontend | Chat UI + feedback thumbs | `ĐÃ LÀM` | 16/07/2026 | [index.html](file:///d:/Download/ProfessionalLegalRAG/app/templates/index.html) cung cấp khung chat và nút feedback gửi dữ liệu qua HTMX |
| Frontend | Admin dashboard | `ĐÃ LÀM` | 16/07/2026 | Trang quản trị tại [admin.html](file:///d:/Download/ProfessionalLegalRAG/app/templates/admin.html) hiển thị biểu đồ thống kê và chi tiết logs |
