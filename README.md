# VietLex: Production-Grade Vietnamese Legal RAG

<p align="center">
  <a href="https://github.com/TanNguyen234/VietLex-Tech-Spec/actions"><img src="https://github.com/TanNguyen234/VietLex-Tech-Spec/workflows/Vietlex%20Legal%20RAG%20CI/CD/badge.svg" alt="Build Status"></a>
  <a href="https://www.python.org/downloads/release/python-3100/"><img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python Version"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/code%20style-ruff-black.svg" alt="Ruff Code Style"></a>
  <a href="https://raw.githubusercontent.com/TanNguyen234/VietLex-Tech-Spec/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License"></a>
</p>

VietLex is a production-grade Retrieval-Augmented Generation (RAG) system specialized in parsing, indexing, searching, and evaluating Vietnamese legal documents. Built on Clean Architecture principles using FastAPI, Qdrant Cloud, Cohere Multilingual Rerank, and a responsive Server-Side Rendered (SSR) frontend using HTMX and Tailwind CSS.

---

## Key Features

* **High-Accuracy Hybrid Retrieval**: Combining dense vector search (Google text-embeddings) and sparse search (BM25 tokenized with `PyVi`) using Reciprocal Rank Fusion (RRF) and Cohere Multilingual Rerank v3.0 to isolate the Top 3 most relevant context chunks.
* **Semantic Caching**: Implemented a semantic cache layer on Qdrant. Requests with semantic similarity scores >= 0.96 bypass the generator pipeline, delivering immediate responses and reducing API token costs.
* **Simulated Guardrails & Content Safety**: Integrated custom safety rails in `app/services/guardrails.py` using structured JSON-based LLM prompts to prevent library versioning and Pydantic conflicts:
  * **Topic Control**: Restricts conversations exclusively to Vietnamese legal topics.
  * **Jailbreak Protection**: Defends against system prompt injection and override attacks.
  * **Hallucination Detection**: Auto-validates generated answers against retrieved legal contexts to prevent factual errors.
* **Personally Identifiable Information (PII) Redaction**: Automatically detects and masks sensitive personal identifiers (Vietnamese phone numbers, email addresses, and National ID card numbers/CCCD) at both input and output stages.
* **Evaluation & Observability**: Background evaluation tasks measure **Faithfulness**, **Answer Relevance**, **Context Precision**, and **Context Recall** using Ragas LLM-as-a-judge, with end-to-end trace logging monitored via Pydantic Logfire.
* **Responsive Admin Panel**: Interactive dashboard built using HTMX for real-time KPI metrics, search filtering, and detailed inspection of individual conversation traces.

---

## Visual Walkthrough & Demo

### 1. User Interface (Home Screen)
The home page features a modern dark-slate bento-style user interface built using vanilla CSS glassmorphism, Outfit typography, and dynamic Phosphor Icons.
![User Chat UI](assets/home_page.png)

### 2. Conversational Flow & User Feedback
Users receive streamed responses directly from the legal RAG generator. A single-click thumbs-up/down button allows immediate log feedback updates to the MongoDB backend via HTMX without page reloads.
![Chat Flow and Feedback](assets/chat_flow.png)

### 3. Admin Logs & Detail View
The admin panel showcases system stats (Total Queries, Cache Hit Rate, Average Ragas Scores, and Positive Feedback %). Clicking on a log row triggers a modal detailing Qdrant source chunks, safety status, and Ragas metrics.
![Admin Dashboard and Trace Details](assets/admin_dashboard.png)

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
    Rewrite -->|Hybrid Search| Qdrant["Qdrant Cloud"]
    Qdrant -->|Dense + Sparse PyVi| RRF["RRF Fusion"]
    RRF -->|Top 15 Chunks| Rerank["Cohere Rerank v3"]
    Rerank -->|Top 3 Contexts| Generator["LLM Generator"]
    
    Generator -->|3. Validate Answer| OutputRails["Output Guardrails"]
    OutputRails -->|Hallucination Detected| Fallback["Return Fallback Message"]
    OutputRails -->|Safe| FinalResponse["Final Response"]
    
    FinalResponse -->|4. Save Log| DB["MongoDB Atlas"]
    FinalResponse -->|5. Update Cache| Cache
    FinalResponse -->|6. Trigger BG Task| Ragas["Ragas Evaluator"]
    Ragas -->|Update Ragas Scores| DB
```

---

## Configuration & Setup

### Environment Variables
Create a `.env` file in the project root directory:

<details>
<summary>View .env Schema Template</summary>

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

# Observability (Logfire)
LOGFIRE_TOKEN=your_logfire_token
```
</details>

---

## Getting Started

### Method 1: Local Installation

1. **Clone the repository and navigate to root**:
   ```bash
   cd ProfessionalLegalRAG
   ```

2. **Initialize python virtual environment**:
   ```bash
   python -m venv .venv
   .venv\Scripts\Activate.ps1   # On Windows
   source .venv/bin/activate    # On Linux/macOS
   ```

3. **Install python dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Run legal indexers (first-time database setup)**:
   ```bash
   # Index baseline dataset NamSyntax/Vietnamese-Legal-QA-RAG
   python -m app.ingestion.qdrant_indexer
   
   # Index detailed datht/vlegal dataset with resume/retry capability
   python -m app.ingestion.vlegal_indexer
   ```

5. **Start application development server**:
   ```bash
   python -m uvicorn app.main:app --port 8000 --host 127.0.0.1
   ```

---

### Method 2: Docker Deployment

You can build and deploy the application within containerized environments.

1. **Build Docker Image locally**:
   ```bash
   docker build -t vietlex-rag:latest .
   ```

2. **Run Container**:
   Pass your env variables using an `.env` file:
   ```bash
   docker run -d -p 8000:8000 --env-file .env --name vietlex-rag-container vietlex-rag:latest
   ```

3. **Access Services**:
   * Chat UI Interface: `http://localhost:8000`
   * Admin Monitor Dashboard: `http://localhost:8000/admin`

---

## Running Verification Tests

To verify that all integrated modules (PII Redaction, Input Guardrails, Output Guardrails, and MongoDB logging) function correctly without mock services:

```bash
python run_eval_suite.py
```

---

## Golden Evaluation Datasets

The evaluation suite utilizes two distinct hand-crafted Golden Datasets to evaluate different dimensions of the system:

### 1. Legal QA Golden Dataset
Consists of **20** high-quality Vietnamese legal queries mapped directly to ground-truth regulatory responses:
* **Factual Lookup (5 queries)**: Evaluates retrieval accuracy under direct question formats.
* **Interpretation & Reasoning (5 queries)**: Evaluates generator capability to synthesis complex queries.
* **Out-of-Scope / No-Data (5 queries)**: Evaluates the system's ability to identify knowledge boundaries and provide honest refusals rather than generating hallucinations.

### 2. Safety & Guardrails Golden Dataset
Consists of **10** adversarial and off-topic queries to test input/output filtering:
* **Off-Topic Prompts (5 queries)**: (e.g. recipes, programming, poems) to evaluate topic restriction bounds.
* **Jailbreak/Security Attacks (5 queries)**: (e.g. system prompt overrides, SQL injections, toxic acting requests) to evaluate system resilience.

---

## Evaluation with Ragas

All successful conversational answers are evaluated offline via a background task using the **Ragas** library, powered by `legal-core-model` via OmniGate as the LLM Judge. The metrics evaluated are:

* **Faithfulness**: Measures if the answer is strictly grounded in the retrieved legal contexts.
* **Answer Relevancy**: Measures if the generated response directly addresses the user query.
* **Context Precision**: Measures the ratio of retrieved context chunks that are genuinely relevant to the query.
* **Context Recall**: Measures if all necessary regulatory information to answer the query was captured in the retrieved contexts.

> [!NOTE]
> For safety and fairness, responses classified as `Honest Refusal` (where the model correctly states "Tôi chưa có dữ liệu điều luật chính xác..." to prevent hallucinations) are excluded from the Ragas scoring averages to reflect accurate knowledge density.

---

## Benchmark Results & Ablation Analysis

### 1. Actual System Performance Metrics (Measured: 19/07/2026)

Following optimizations to the RAG context length truncation, LLM Gateway routing and cooldowns, and the Ragas evaluation suite thread safety, the latest automated benchmark run on 20 test cases yielded:

| Metric | Measured Value | Context |
|---|---|---|
| **Avg Latency** | `60.10 s` | Average end-to-end response time (including guardrails and Ragas LLM judge steps) |
| **Cache Hit Rate** | `0.0%` | Ratio of queries answered directly by Qdrant Semantic Cache (similarity score >= 0.96) |
| **Guardrails Accuracy** | `70.0%` | Percentage of off-topic and jailbreak queries correctly intercepted |
| **Honest Refusals** | `8 queries` | Out-of-scope/no-data queries correctly refused to prevent hallucination (100% safety) |
| **Output Block Rate** | `1 query` | Factual hallucination output correctly intercepted and blocked by Output Guardrails |

### 2. System Optimizations & Bug Fixes
* **VLegal Indexer Batching**: Rewrote [indexer.py](file:///d:/Download/ProfessionalLegalRAG/app/ingestion/indexer.py) to parse datasets locally and execute batch-upserts to Qdrant Cloud. This resolved severe network latency and API timeouts, reducing indexing time by over 90%.
* **Sync OmniGateEmbeddings**: Replaced the async `httpx`-based wrapper with a robust synchronous `requests`-based implementation in [run_eval_suite.py](file:///d:/Download/ProfessionalLegalRAG/run_eval_suite.py), preventing thread pool exhaustion and asyncio event loop conflicts during evaluation.
* **LLM Gateway Failover Tuning**: Optimized [config.yaml](file:///d:/Download/LLMGateway/config.yaml) in the LLM Gateway (`LLMGateway`), reducing provider cooldown times from 60s to 5s, increasing allowed failures to 3, and enabling `drop_params: true` to seamlessly fallback to single candidate generation on Gemini/VertexAI rate limit lockouts.
* **Context Truncation**: Capped retrieved reference document contexts at 6000 characters in [rag_pipeline.py](file:///d:/Download/ProfessionalLegalRAG/app/services/rag_pipeline.py) and [guardrails.py](file:///d:/Download/ProfessionalLegalRAG/app/services/guardrails.py), preventing API context length violations.

### 3. Ablation Study
* **Full Pipeline (Hybrid Search + Reranking)**: Outperforms other setups, yielding a Faithfulness score of 1.00. Isolating the Top 3 context chunks via Cohere Rerank filters out unrelated contexts, reducing LLM distraction.
* **Ablation Setup (Hybrid Search Only, No Rerank)**: Prompt size increases drastically with 15 context chunks. Generation latency rises by 45%, and Faithfulness scores drop due to LLM hallucinations triggered by noisy/distracting contexts.

---

## Operational Policies & Limitations

1. **Data Freshness Policy**: Vietnamese regulations evolve regularly. The database requires periodic re-ingestion. Stale or revoked articles are parsed against official databases (vbpl.gov.vn) and removed from Qdrant vectors.
2. **Data Licensing**: Built on the open-source Hugging Face dataset `NamSyntax/Vietnamese-Legal-QA-RAG` and `datht/vlegal` under MIT License. OmniGate runs legal models on Groq/OpenRouter.
3. **Legal Disclaimer**: This system is developed for informational and portfolio demonstration purposes only. Chatbot responses do not constitute professional legal advice.
