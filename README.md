# VietLex Advanced Legal RAG

Hệ thống RAG nâng cao truy vấn văn bản luật Việt Nam (Chương -> Mục -> Điều) được xây dựng trên FastAPI, Qdrant Cloud, NeMo Guardrails, Logfire, Ragas và giao diện HTMX + TailwindCSS.

## Cấu trúc Dự án (Clean Architecture)

```text
vietlex-rag/
├── app/
│   ├── main.py                # FastAPI app initialization, Middleware, Logfire init
│   ├── config.py              # Pydantic BaseSettings for env vars
│   ├── api/
│   │   ├── routes.py          # /chat endpoint, /api/feedback endpoint
│   │   └── dependencies.py    # Auth, RateLimiter injections
│   ├── services/
│   │   ├── rag_pipeline.py    # Core retrieval logic, RRF, Langchain prompts
│   │   ├── semantic_cache.py  # Qdrant threshold search logic
│   │   ├── guardrails.py      # NeMo initialization & invoke
│   │   └── evaluator.py       # Background task running LLM-as-a-judge
│   ├── ingestion/
│   │   ├── parser.py          # Regex parser (Chương -> Mục -> Điều)
│   │   └── indexer.py         # PyVi segmentation, Upsert to Qdrant
│   └── templates/
│       ├── index.html         # HTMX injected base UI
│       └── chat_message.html  # HTMX partial response
├── guardrails_config/
│   ├── config.yml             # NeMo policies
│   └── prompts.yml
├── requirements.txt
└── .env
```

## Các tính năng chính

1. **Semantic Cache (Bộ nhớ đệm Ngữ nghĩa)**: vector search trên Qdrant với độ tương đồng >= 0.96.
2. **Advanced Retrieval Pipeline**: Hybrid Search (Dense + Sparse BM25 + PyVi) -> Reciprocal Rank Fusion (RRF) -> Cohere Rerank v3.0 -> legal-core-model.
3. **Guardrails & Evals**: NVIDIA NeMo Guardrails kiểm duyệt Input/Output và Ragas LLM-as-a-judge chạy ngầm.
4. **HTMX Frontend**: Single-page application nhẹ nhàng, mượt mà.
5. **Observability**: Logfire tracing cho toàn bộ hệ thống.
