# VietLex: Production-Grade Vietnamese Legal RAG

<p align="center">
  <a href="https://github.com/TanNguyen234/VietLex-Tech-Spec/actions"><img src="https://github.com/TanNguyen234/VietLex-Tech-Spec/workflows/Vietlex%20Legal%20RAG%20CI/CD/badge.svg" alt="Build Status"></a>
  <a href="https://www.python.org/downloads/release/python-3100/"><img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python Version"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/code%20style-ruff-black.svg" alt="Ruff Code Style"></a>
  <a href="https://raw.githubusercontent.com/TanNguyen234/VietLex-Tech-Spec/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License"></a>
</p>

VietLex is a production-grade Retrieval-Augmented Generation (RAG) system specialized in parsing, indexing, searching, and evaluating Vietnamese legal documents. Built on Clean Architecture principles using FastAPI, Qdrant Cloud, MongoDB Atlas, Cohere Multilingual Rerank, and a responsive Server-Side Rendered (SSR) frontend using HTMX and Tailwind CSS.

---

## Key Features

* **Dual Storage Architecture (Data Lake + Vector Store)**:
  * **MongoDB Atlas (`raw_legal_documents`)**: Stores raw crawled legal documents with full metadata, law attributes, signer information, and validity status.
  * **Qdrant Cloud (`vietlex_laws_crawler_kb`)**: Stores chunked legal articles with dense embeddings (`legal-embedding-model`) and BM25 sparse vectors for hybrid retrieval.
* **High-Accuracy Hybrid Retrieval**: Combining dense vector search (Google text-embeddings via OmniGate) and sparse search (BM25 tokenized with `PyVi`) using Reciprocal Rank Fusion (RRF) and Cohere Multilingual Rerank v3.0 to isolate the Top 3 most relevant context chunks.
* **Semantic Caching**: Implemented a semantic cache layer on Qdrant (`vietlex_semantic_cache`). Requests with semantic similarity scores >= 0.96 bypass the generator pipeline, delivering immediate responses and reducing API token costs.
* **Simulated Guardrails & Content Safety**: Integrated custom safety rails in `app/services/guardrails.py` using structured JSON-based LLM prompts:
  * **Topic Control**: Restricts conversations exclusively to Vietnamese legal topics.
  * **Jailbreak Protection**: Defends against system prompt injection and override attacks.
  * **Hallucination Detection**: Auto-validates generated answers against retrieved legal contexts to prevent factual errors.
* **Personally Identifiable Information (PII) Redaction**: Automatically detects and masks sensitive personal identifiers (Vietnamese phone numbers, email addresses, and National ID card numbers/CCCD) at both input and output stages.
* **Evaluation & Observability**: Background evaluation tasks measure **Faithfulness**, **Answer Relevance**, **Context Precision**, and **Context Recall** using Ragas LLM-as-a-judge, with end-to-end trace logging monitored via Pydantic Logfire.
* **Responsive Admin Panel**: Interactive dashboard built using HTMX for real-time KPI metrics, search filtering, and detailed inspection of individual conversation traces.

---

## System Architecture

```mermaid
graph TD
    User["User"] -->|POST /chat| API["FastAPI Endpoints"]
    API -->|1. Redact PII| PII["PII Redactor"]
    PII -->|2. Check Cache| Cache["Semantic Cache Qdrant"]
    Cache -->|Cache Hit| Return["Return Response"]
    Cache -->|Cache Miss| InputRails["Input Guardrails"]
    InputRails -->|Blocked| Block["Return Safety Message"]
    InputRails -->|Safe| RAG["Advanced Retrieval"]

    RAG -->|Query Rewrite| Rewrite["LLM Rewrite"]
    Rewrite -->|Hybrid Search| Qdrant["Qdrant Cloud Collection"]
    Qdrant -->|Dense + Sparse PyVi| RRF["RRF Fusion"]
    RRF -->|Top 15 Chunks| Rerank["Cohere Rerank v3"]
    Rerank -->|Top 3 Contexts| Generator["LLM Generator"]

    Generator -->|3. Validate Answer| OutputRails["Output Guardrails"]
    OutputRails -->|Hallucination Detected| Fallback["Return Fallback Message"]
    OutputRails -->|Safe| FinalResponse["Final Response"]

    FinalResponse -->|4. Save Log| DB["MongoDB Atlas Logs"]
    FinalResponse -->|5. Update Cache| Cache
    FinalResponse -->|6. Trigger BG Task| Ragas["Ragas Evaluator"]
    Ragas -->|Update Ragas Scores| DB
```

---

## Data Pipeline & Indexing

### 1. Push Raw Documents to MongoDB Atlas
Sync raw crawled legal files (`.json.gz` or `.json`) into MongoDB Atlas collection `raw_legal_documents`:
```bash
python -m app.ingestion.mongo_indexer app/data/raw_data
```

### 2. Chunk & Index Vectors to Qdrant Cloud
Parse legal text into Chapter/Section/Article structure, extract embeddings via OmniGate, generate BM25 sparse vectors, and upsert points to Qdrant collection `vietlex_laws_crawler_kb`:
```bash
python -m app.ingestion.crawler_indexer app/data/raw_data --collection vietlex_laws_crawler_kb
```

---

## Configuration & Setup

### Environment Variables
Create a `.env` file in the project root directory:

```env
# Server Configuration
HOST=0.0.0.0
PORT=8000
FRONTEND_URL=http://localhost:8000

# Qdrant Database
QDRANT_URL=https://your-qdrant-cluster.cloud.qdrant.io
QDRANT_API_KEY=your_qdrant_api_key

# Cohere API Key (for Reranker)
COHERE_API_KEY=your_cohere_api_key

# LLM Gateway (OmniGate)
OMNIGATE_BASE_URL=https://llmgateway.onrender.com
LITELLM_MASTER_KEY=your_litellm_master_key

# MongoDB Connection URL
MONGO_URL=mongodb+srv://user:pass@cluster.mongodb.net/Legal-RAG

# Logfire Tracing
LOGFIRE_TOKEN=your_logfire_token
```

### Running Locally
```bash
# Install dependencies
pip install -r requirements.txt

# Launch FastAPI development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Testing & Quality Assurance

Run complete test suite including RAG pipeline tests, Qdrant search, Guardrails, and Ingestion logic:
```bash
pytest
```
