# VietLex Advanced Legal RAG

<p align="center">
  <a href="https://github.com/TanNguyen234/VietLex-Tech-Spec/actions"><img src="https://github.com/TanNguyen234/VietLex-Tech-Spec/workflows/Vietlex%20Legal%20RAG%20CI/CD/badge.svg" alt="Build Status"></a>
  <a href="https://www.python.org/downloads/release/python-3100/"><img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python Version"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/code%20style-ruff-black.svg" alt="Ruff Code Style"></a>
  <a href="https://raw.githubusercontent.com/TanNguyen234/VietLex-Tech-Spec/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License"></a>
</p>

A production-grade Retrieval-Augmented Generation (RAG) system specialized in parsing, indexing, searching, and evaluating Vietnamese legal documents. Built on a Clean Architecture principles using FastAPI, Qdrant Cloud, Cohere Multilingual Rerank, NVIDIA NeMo Guardrails, MongoDB Atlas, and a responsive Server-Side Rendered (SSR) frontend using HTMX and Tailwind CSS.

---

## Key Features

* **High-Accuracy Retrieval Pipeline**: Combining dense vector search (Google text-embeddings) and sparse search (BM25 tokenized with `PyVi`) using Reciprocal Rank Fusion (RRF) and Cohere Multilingual Rerank v3.0.
* **Semantic Caching**: Implemented a semantic cache layer on Qdrant. Requests with semantic similarity scores >= 0.96 bypass the generator pipeline, delivering immediate responses and reducing API costs.
* **Guardrails & Content Safety**: Integrated safety rails powered by NVIDIA NeMo Guardrails:
  * **Topic Control**: Restricts chatbot conversations exclusively to Vietnamese legal topics.
  * **Jailbreak Protection**: Defends against system prompt injection and override attacks.
  * **Content Safety**: Filters toxic, offensive, or inappropriate inputs/outputs.
  * **Hallucination Detection**: Auto-validates generated answers against retrieved legal contexts to prevent factual errors.
* **Personally Identifiable Information (PII) Redaction**: Automatically detects and masks sensitive personal identifiers (Vietnamese phone numbers, email addresses, and National ID card numbers/CCCD) at both input and output stages.
* **Evaluation & Observability**: Real-time logging of interactions and user feedback to MongoDB. Background evaluation tasks measure **Faithfulness** and **Answer Relevance** using Ragas LLM-as-a-judge, with end-to-end trace logging monitored via Pydantic Logfire.
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

4. **Run legal indexer (first-time database setup)**:
   ```bash
   python -m app.ingestion.qdrant_indexer
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
pytest
```
