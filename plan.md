# TECHNICAL SPECIFICATION: VIETLEX (ADVANCED LEGAL RAG)

**Target Audience:** AI Coding Agents / Backend Developers
**Purpose:** Production-grade RAG pipeline using FastAPI, Qdrant, Guardrails, Logfire tracing, Semantic Caching, and asynchronous LLM evaluations.

---

## 1. System Architecture & Tech Stack
- **Backend:** FastAPI, Uvicorn, Slowapi (Rate Limiting)
- **Observability:** Pydantic Logfire
- **Vector DB:** Qdrant Cloud (for Hybrid Search & Semantic Cache)
- **LLM Communication:** LangChain (OpenAI client configured to point to OmniGate)
- **Advanced RAG:** Cohere API (Reranker), NeMo Guardrails
- **Evals:** Ragas (Automated background task)
- **Frontend:** Jinja2 Templates, HTMX, TailwindCSS

---

## 2. Directory Structure (Clean Architecture)
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

---

## 3. Security Requirements (Strict Enforcement)
AI Coder must implement these exactly in `main.py`:
- **CORS:** Restrict to specified `FRONTEND_URL` environment variable.
- **Rate Limiting:** Use `slowapi`. Restrict `POST /chat` to 5/minute per IP.
- **CSRF Protection:** Generate secure token on `GET /`. Validate token on `POST /chat`.
- **Gateway Auth:** Ensure LangChain LLM client uses `LITELLM_MASTER_KEY` to hit OmniGate.

---

## 4. Logic Flows for AI Implementation

### Flow 1: Semantic Caching (in `semantic_cache.py`)
```text
ALGORITHM check_semantic_cache(user_query):
1. Call OmniGate text-embedding-004 to get vector of user_query.
2. Search Qdrant collection 'vietlex_semantic_cache' with vector. limit=1.
3. IF match.score >= 0.96:
     RETURN match.payload['bot_response']
4. ELSE:
     RETURN None
```

### Flow 2: Advanced Retrieval Pipeline (in `rag_pipeline.py`)
```text
ALGORITHM run_advanced_rag(user_query):
1. Query Rewriter: LLM reformulates user_query to formal legal terms.
2. Hybrid Search (Qdrant):
   a. Dense Search (text-embedding-004 vector) -> Top 15
   b. Sparse Search (BM25, pre-tokenized by PyVi) -> Top 15
3. Fusion: Apply Reciprocal Rank Fusion (RRF) on a & b -> Top 15 combined.
4. Reranking: Call Cohere Rerank API (rerank-multilingual-v3.0) -> Top 3.
5. Context Injection: Format Top 3 chunks into LangChain prompt template.
6. LLM Generation: Call OmniGate (model="legal-core-model") with prompt.
7. Return (bot_response, context_used).
```

### Flow 3: Request Lifecycle with Guardrails & Evals (in `routes.py`)
```text
ENDPOINT POST /chat:
1. Extract form data (message, csrf_token). Validate CSRF.
2. Check Semantic Cache. If hit, generate trace_id and return immediately.
3. Apply NeMo Guardrails (Input check). If malicious/out-of-scope, return predefined rejection.
4. Run Advanced Retrieval Pipeline -> gets (bot_response, context).
5. Apply NeMo Guardrails (Output check). If hallucination detected, return safe fallback.
6. Save interaction to Semantic Cache (Qdrant).
7. Generate trace_id (UUID).
8. TRIGGER BACKGROUND TASK: evaluator.run_llm_as_judge(user_query, context, bot_response, trace_id)
9. RETURN HTML partial response (chat_message.html) via Jinja2.
```

---

## 5. Observability (Logfire)
Initialize Logfire in `main.py`: `logfire.configure()` and `logfire.instrument_fastapi(app)`. Use `@logfire.instrument` decorator on key functions in `services/` to trace latency spanning.

---

## 6. External Dependencies to Inject
- `QDRANT_URL` and `QDRANT_API_KEY`
- `COHERE_API_KEY` (for Reranker)
- `OMNIGATE_BASE_URL` (e.g., http://localhost:8000/v1)
- `OMNIGATE_API_KEY` (matches `LITELLM_MASTER_KEY`)
