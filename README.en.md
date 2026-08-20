# VietLex — Vietnamese Legal RAG (English)

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Production-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![RAG](https://img.shields.io/badge/RAG-Legal%20QA-6A5ACD)](#)
[![License](https://img.shields.io/badge/License-CC%20BY%204.0-lightgrey)](https://creativecommons.org/licenses/by/4.0/)

Language: [Tiếng Việt](README.md) | **English**

VietLex is a production-oriented RAG system for Vietnamese legal document
retrieval and grounded QA. The complete corpus is durably stored in Pinecone.
Qdrant Cloud provides remote inference and an opt-in structural collection for
827 primary-legislation documents. When enabled it is the primary retrieval
path, with the full-corpus Pinecone v1 path retained as an observable fallback.

> [!WARNING]
> The corpus comes from a third-party research dataset:
> [`vohuutridung/vietnamese-legal-documents`](https://huggingface.co/datasets/vohuutridung/vietnamese-legal-documents).
> It is **not** an official legal source and does not guarantee legal validity.
> Results are informational only, not legal advice. Always verify against
> official up-to-date legal sources before making decisions.

## ⚡ Quick scripts (professional README style)

| Script | Command | Purpose |
| --- | --- | --- |
| `setup` | `python -m venv .venv`<br>`.venv\Scripts\Activate.ps1`<br>`python -m pip install -r requirements.txt`<br>`Copy-Item .env.example .env` | Initialize local environment |
| `dev` | `uvicorn app.main:app --host 0.0.0.0 --port 8000` | Run local API server |
| `ingest:full` | `python -u -m app.ingestion.hf_pipeline full --delete-existing --yes` | Full corpus ingestion/rebuild |
| `ingest:download` | `python -m app.ingestion.hf_pipeline download` | Download dataset snapshot |
| `ingest:prepare` | `python -m app.ingestion.hf_pipeline prepare` | Prepare ingestion artifacts |
| `ingest:smoke` | `python -m app.ingestion.hf_pipeline smoke` | Ingestion smoke checks |
| `ingest:verify` | `python -m app.ingestion.hf_pipeline verify` | Validate ingestion state |
| `fts:build` | `python -u -m app.ingestion.legal_fts build --batch-size 256` | Build SQLite FTS5 index |
| `eval:full` | `python -u run_eval_suite.py --fresh --factoids 12 --multihop 12 --unanswerable 6 --concurrency 2 --judge-concurrency 4` | Full golden evaluation |
| `eval:smoke` | `python -u run_eval_suite.py --fresh --factoids 2 --multihop 2 --unanswerable 2 --concurrency 1 --judge-concurrency 1 --checkpoint docs/smoke_eval_checkpoints.json --report docs/smoke_evaluation_report.md` | Fast smoke evaluation |
| `test` | `python -m pytest -q` | Run test suite |
| `test:live-rerank` | `$env:RUN_LIVE_RERANK_TEST='1'`<br>`python -m pytest tests/integration/test_remote_reranker_live.py -q`<br>`Remove-Item Env:RUN_LIVE_RERANK_TEST` | Live reranker smoke test |
| `check` | `python -m compileall -q app tests`<br>`git diff --check` | Compile + whitespace checks |

## Corpus

- Revision pin: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`
- Document count: `518,255`
- Publisher-declared license: CC BY 4.0
- Snapshot integrity: 13 files with size + SHA-256 verification
- Full content stays in local SQLite/Zstandard, not in Pinecone payload

## Architecture

```mermaid
flowchart LR
    HF["Pinned Hugging Face snapshot"] --> Store["SQLite + Zstandard"]
    Store --> Text["Dense: metadata + outline + representative body"]
    Text --> Stage["Qdrant inference staging: E5-small 384"]
    Stage --> Vector["Dense vector"]
    Text --> Sparse["Fast Vietnamese lexical sparse, max 64 terms"]
    Vector --> Pinecone["Pinecone serverless"]
    Sparse --> Pinecone

    Query["Original query"] --> QueryEmbed["Dense query via Qdrant staging"]
    Query -. "explicit evaluation only" .-> Rewrite["Optional short legal rewrite"]
    Query --> FTS["SQLite FTS5 + exact document number"]
    Rewrite -.-> QueryEmbed
    Query --> SparseQuery["Exact sparse query"]
    QueryEmbed --> Hybrid["Single Pinecone dense+sparse query"]
    SparseQuery --> Hybrid
    FTS --> Merge["Merge + deduplicate"]
    Hybrid --> Merge
    Merge --> Resolve["Resolve full text from SQLite"]
    Resolve --> Chunk["Chapter → Section → Article → Clause"]
    Chunk --> Bound["Max 12 candidates; ≤2/document"]
    Bound --> Rerank["Qdrant ColBERT; Pinecone BGE fallback"]
    Rerank --> Budget["Top 3; context ≤720 tokens"]
    Budget --> Answer["Vertex AI gemini-3.5-flash via ADC"]
```

## Setup

Requires Python 3.10+:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Required secrets:

- `PIPECONE_API` or `PINECONE_API_KEY`
- `QDRANT_URL`, `QDRANT_API_KEY` (embedding + ColBERT cloud inference)
- Structural primary (optional): `STRUCTURAL_BACKEND_ENABLED=true` and `STRUCTURAL_COLLECTION_NAME=vietlex-legal-rag-v2-pilot-384`; Pinecone v1 remains the full-corpus fallback
- Local: `GOOGLE_APPLICATION_CREDENTIALS=.secrets/vertex-adc.json` (project-relative path to a Git-ignored key)
- Vercel/serverless: `GOOGLE_SERVICE_ACCOUNT_JSON` (the complete service-account JSON stored as a platform secret and loaded in memory)
- `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION=global`
- `VERTEX_LLM_MODEL=gemini-3.5-flash`, `VERTEX_EMBEDDING_MODEL=gemini-embedding-2`
- Optional secondary APIs: `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `NVIDIA_API_KEY`, `GROQ_API_KEY`

Production generation and the guardrail LLM use Vertex AI `gemini-3.5-flash`
as primary. A typed Vertex failure may fall back to OpenRouter, the Gemini Direct API, NVIDIA, and
Groq; runtime metadata records the actual provider/model and primary failure.
Query rewriting is off by default. `gemini-embedding-2` is probe-only at
384/768/1024 dimensions and never queries or mutates the production E5 index.
Ragas is an offline audit only and is never run by `/chat`. Its primary judge is Vertex AI `gemini-3.5-flash` through ADC; legacy APIs and OmniGate are best-effort fallbacks.
When the dense lane fails but FTS remains usable, retrieval reports
`partial_retrieval_error`: lexical evidence is still scored while the provider
failure is counted in the technical-error rate. Lawful questions about public
authorities, policy, and legal powers are explicitly allowed by the input rail.

## Ingestion

Run full ingestion:

```powershell
python -u -m app.ingestion.hf_pipeline full --delete-existing --yes
```

Optional phases:

```powershell
python -m app.ingestion.hf_pipeline download
python -m app.ingestion.hf_pipeline prepare
python -m app.ingestion.hf_pipeline smoke
python -m app.ingestion.hf_pipeline verify
```

Build FTS5 index:

```powershell
python -u -m app.ingestion.legal_fts build --batch-size 256
```

## Run application

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Evaluation

Full golden evaluation:

```powershell
python -u run_eval_suite.py --fresh --factoids 12 --multihop 12 --unanswerable 6 --concurrency 2 --judge-concurrency 4
```

Smoke evaluation:

```powershell
python -u run_eval_suite.py --fresh --factoids 2 --multihop 2 --unanswerable 2 --concurrency 1 --judge-concurrency 1 --checkpoint docs/smoke_eval_checkpoints.json --report docs/smoke_evaluation_report.md
```

## Testing

```powershell
python -m pytest -q
python -m compileall -q app tests
git diff --check
```

Live reranker smoke:

```powershell
$env:RUN_LIVE_RERANK_TEST='1'
python -m pytest tests/integration/test_remote_reranker_live.py -q
Remove-Item Env:RUN_LIVE_RERANK_TEST
```

## Notes

- Runtime uses one Pinecone hybrid read and one SQLite FTS5 read in parallel.
- Semantic cache uses a dedicated namespace with threshold `0.96`.
- Production does not use mock retrieval/rerank paths.
- Detailed operations guide:
  [Hugging Face ingestion runbook](docs/huggingface-ingestion-runbook.md).
