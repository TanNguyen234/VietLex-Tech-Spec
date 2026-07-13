# Tài liệu Kiến trúc Hệ thống (System Architecture) - Vietlex Legal RAG

Tài liệu này chi tiết hóa kiến trúc kỹ thuật và các luồng xử lý dữ liệu của hệ thống **VIETLEX (ADVANCED LEGAL RAG)**.

---

## 1. Tổng quan Kiến trúc (Clean Architecture)

Hệ thống được thiết kế theo mô hình Clean Architecture phân tách rõ ràng giữa hạ tầng (infrastructure), giao tiếp bên ngoài (API routes, templates) và lõi nghiệp vụ (services, ingestion).

```mermaid
graph TD
    %% Định nghĩa các node chính
    Client[HTMX / Web Browser] <--> API[FastAPI Routes: app/api/routes.py]
    
    subgraph FastAPI App [app/main.py]
        API
        Middleware[CORS, Slowapi Rate Limiter, CSRF Validate]
    end

    subgraph Service Layer [app/services/]
        SC[Semantic Cache: semantic_cache.py]
        RAG[Advanced RAG Pipeline: rag_pipeline.py]
        GR[Guardrails: guardrails.py]
        Eval[Evaluator: evaluator.py]
    end

    subgraph Data Ingestion [app/ingestion/]
        Parser[Regex Parser: parser.py]
        Indexer[Indexer & Segmentation: indexer.py]
    end

    subgraph External Infrastructure
        Qdrant[(Qdrant Cloud)]
        OmniGate[OmniGate LLM Gateway]
        Cohere[Cohere Multilingual Rerank]
    end

    %% Mối liên kết giữa các component
    Client --> Middleware
    Middleware --> API
    API --> SC
    API --> GR
    API --> RAG
    API -.->|Background Task| Eval
    
    SC <-->|Query/Upsert Vectors| Qdrant
    RAG -->|Rewrite Query / Generate Answer| OmniGate
    RAG -->|Dense Search| Qdrant
    RAG -->|Rerank Chunks| Cohere
    
    Parser --> Indexer
    Indexer -->|Upsert Chunks| Qdrant
```

---

## 2. Các Luồng Dữ liệu (Logic Flows)

### Luồng 1: Semantic Caching (Bộ nhớ đệm Ngữ nghĩa)
- Nhằm tối ưu hóa chi phí và tốc độ phản hồi đối với các câu hỏi trùng lặp hoặc tương đương.
- Sử dụng mô hình `text-embedding-004` của Google (thông qua OmniGate) để embedding query.
- Truy vấn Qdrant collection `vietlex_semantic_cache` và lấy 1 kết quả duy nhất có điểm số cao nhất.
- Điểm tương đồng cosine threshold >= **0.96** được định cấu hình làm mốc quyết định hit/miss.

```mermaid
sequenceDiagram
    autonumber
    participant Client
    participant routes.py
    participant semantic_cache.py
    participant Qdrant
    
    Client->>routes.py: Gửi user_query
    routes.py->>semantic_cache.py: check_semantic_cache(user_query)
    semantic_cache.py->>semantic_cache.py: Nhận vector từ text-embedding-004
    semantic_cache.py->>Qdrant: Tìm kiếm collection 'vietlex_semantic_cache' (limit=1)
    Qdrant-->>semantic_cache.py: Trả về kết quả khớp nhất + match.score
    alt match.score >= 0.96 (Hit)
        semantic_cache.py-->>routes.py: bot_response
        routes.py-->>Client: Trả về chat_message.html (Render cache)
    else match.score < 0.96 (Miss)
        semantic_cache.py-->>routes.py: None
        routes.py->>routes.py: Tiếp tục luồng RAG nâng cao
    end
```

### Luồng 2: Advanced Retrieval Pipeline (RAG nâng cao)
- **Query Rewriter**: Chuyển đổi câu hỏi phi cấu trúc của người dùng sang dạng thuật ngữ pháp lý.
- **Hybrid Search**: Tìm kiếm song song Dense Search (Vector) và Sparse Search (BM25 được tokenize bởi PyVi).
- **RRF (Reciprocal Rank Fusion)**: Hợp nhất kết quả Dense và Sparse để giữ độ phủ.
- **Reranker (Cohere)**: Tái định vị mức độ liên quan sử dụng mô hình multilingual chuyên dụng để chọn 3 kết quả chất lượng nhất.

```mermaid
flowchart TD
    A[Bắt đầu: user_query] --> B[LLM Query Rewriter]
    B --> C[Query Pháp lý đã viết lại]
    C --> D[Dense Search: text-embedding-004]
    C --> E[Sparse Search: BM25 + PyVi]
    
    D -->|Lấy Top 15| F[Reciprocal Rank Fusion]
    E -->|Lấy Top 15| F
    
    F -->|Lấy Top 15 Hợp nhất| G[Cohere Rerank: rerank-multilingual-v3.0]
    G -->|Lấy Top 3 Chunks| H[LangChain Prompt Context Injection]
    H --> I[OmniGate: legal-core-model Generation]
    I --> J[Trả về bot_response & context]
```

### Luồng 3: Request Lifecycle với Guardrails & Evals
- Quản lý quy trình kiểm duyệt nội dung đầu vào, đầu ra và đánh giá chất lượng tự động sau khi phản hồi.

```mermaid
sequenceDiagram
    autonumber
    participant Client
    participant API as routes.py
    participant Cache as semantic_cache.py
    participant GR as guardrails.py
    participant RAG as rag_pipeline.py
    participant Eval as evaluator.py

    Client->>API: POST /chat (message, csrf_token)
    API->>API: Xác thực CSRF Token & Rate Limiting
    API->>Cache: Kiểm tra Semantic Cache
    alt Hit (score >= 0.96)
        Cache-->>API: bot_response
        API-->>Client: Trả về chat_message.html
    else Miss
        API->>GR: Guardrails Input Check
        alt Bị chặn (Malicious/Out of scope)
            GR-->>API: Thông báo từ chối cấu hình sẵn
            API-->>Client: Trả về chat_message.html
        else Hợp lệ
            GR-->>API: Đi tiếp
            API->>RAG: Chạy run_advanced_rag(user_query)
            RAG-->>API: Trả về (bot_response, context)
            API->>GR: Guardrails Output Check (Hallucination check)
            alt Phát hiện Ảo giác
                GR-->>API: Trả về safe fallback message
            else Hợp lệ
                GR-->>API: bot_response
            end
            API->>Cache: Lưu (user_query, bot_response) vào Qdrant
            API->>Eval: Kích hoạt Background Task: run_llm_as_judge(...)
            API-->>Client: Trả về chat_message.html (Kết quả cuối)
        end
    end
```
