# Remote Reranking and RAG Reliability Design

**Date:** 2026-08-02  
**Status:** Approved in conversation  
**Scope:** Complete the high-priority fixes from the system evaluation while keeping all model inference remote.

## Goals

- Keep Pinecone as the only durable vector store for the legal corpus.
- Use Qdrant Cloud Inference as the primary reranking provider.
- Fall back to Pinecone Inference when Qdrant is unavailable or transiently overloaded.
- Never download or execute an embedding or reranking model locally.
- Improve retrieval recall, failure classification, evaluation validity, and end-to-end latency without reingesting Pinecone.
- Keep local indexes and caches under the project data directory on drive D.

## Constraints

- Existing Pinecone embeddings remain `intfloat/multilingual-e5-small`, dimension 384. Query embeddings must use the same model and dimension.
- The Qdrant cluster must not become a durable copy of the corpus. Its reranking collection is bounded staging only.
- Provider failures must not be reported as a valid knowledge refusal.
- Reranker requests must be bounded by candidate count, document length, timeout, and retry policy.
- Existing evaluation artifacts in `docs/system_evaluation_report.md` and `docs/eval_checkpoints.json` are user-owned and must not be overwritten by implementation work.

## Architecture

```text
User query
  -> query rewrite
  -> exact legal-reference routing + local SQLite FTS5
  -> Pinecone hybrid dense/sparse retrieval
  -> merge and deduplicate document candidates
  -> resolve and score bounded chunks
  -> Qdrant Cloud ColBERT rerank (primary)
       -> Pinecone bge-reranker-v2-m3 (transient fallback)
  -> select Top 3 within context token budget
  -> answer generation and output guardrail
```

### Durable storage

Pinecone remains the durable vector database. No Qdrant collection will contain the full legal dataset.

### Local lexical retrieval

A SQLite FTS5 index will be built from the existing content store. It will index document number, title, legal type, issuing authority, dates, and article-level text where available. Its path will be configurable and will default below `data/huggingface/` on drive D.

Exact references such as `Luật số 72/2020/QH14`, `Điều 15`, or a known issuing authority will be routed to the lexical path. Lexical candidates will be merged with Pinecone candidates before reranking. MongoDB is not introduced because it does not improve the identified recall failure and adds another remote dependency.

## Reranking Provider Chain

### Primary: Qdrant Cloud Inference

Qdrant does not expose a standalone cross-encoder rerank method equivalent to Pinecone. The supported design uses the multilingual late-interaction model `answerdotai/answerai-colbert-small-v1` and Qdrant's native MaxSim scoring.

A dedicated staging collection will contain only candidates currently being reranked:

- named multivector configured for the model's 96-dimensional token vectors;
- HNSW indexing disabled because candidate sets are tiny and short-lived;
- payload kept minimal: request identifier and original candidate index;
- unique request-scoped point IDs to support concurrent requests;
- request filter prevents candidates from different requests mixing;
- request points are deleted after completion on a best-effort basis;
- a bounded cleanup policy removes stale request points left by interrupted calls.

Each request performs remote document inference during upsert and remote query inference during `query_points`. MaxSim executes in Qdrant. No local model or local vector scoring is used.

### Fallback: Pinecone Inference

On Qdrant timeout, connection failure, HTTP 429, or HTTP 5xx, reranking falls back to:

```python
pinecone.inference.rerank(
    model="bge-reranker-v2-m3",
    query=query,
    documents=documents,
    top_n=return_limit,
    return_documents=False,
)
```

Invalid configuration, authentication failures, malformed responses, and other permanent errors are surfaced instead of silently retried.

### Resilience controls

- Qdrant gets one retry for transient failures with short jittered backoff.
- A process-local circuit breaker opens after consecutive transient failures and temporarily routes calls directly to Pinecone.
- Pinecone gets SDK retry handling only for documented transient status codes.
- If both providers fail, retrieval returns a typed `reranker_error`; it does not return an empty context as an honest refusal.
- Provider name, model, attempt count, fallback reason, input count, output count, and latency are recorded for every rerank call.

## Candidate and Context Budgets

- Candidate chunks sent to a reranker: default 12.
- Chunk target: 180–220 approximate tokens with legal article/clause boundaries preferred.
- Maximum chunks per source document: 2.
- Reranker return count: up to 6 before diversity and score filtering.
- Final evidence: Top 3.
- Final context budget: default 720 tokens, configurable.

Candidate selection computes normalized query terms once. Chunk text terms are derived without repeatedly invoking PyVi inside the scoring loop. The selection step stops once bounded per-document candidates have been collected instead of chunking and scoring every section of every retrieved document.

## Error Semantics and Observability

`RetrievalOutcome` will carry structured diagnostics:

- outcome status;
- original and rewritten query;
- top Pinecone and lexical document IDs/scores;
- candidate chunk citations before rerank;
- ranked citations and scores after rerank;
- embedding and reranking provider/model;
- per-stage latency and exact error category.

Required statuses include:

- `ok`;
- `retrieval_error`;
- `no_candidate`;
- `reranker_error`;
- `model_refusal_with_evidence`;
- `correct_unanswerable_refusal`.

The RAG pipeline will propagate technical errors distinctly. Only a successful search with no supported evidence may become a knowledge refusal.

## Evaluation Corrections

- Measure queue time, retrieval, reranking, answer generation, guardrails, Ragas, and true wall-clock time separately.
- Store exact Ragas/judge exceptions and provider/model identifiers.
- Report Recall@K, reciprocal rank, golden-context hit, refusal precision/recall, answerable accuracy, and unanswerable accuracy with explicit denominators.
- Use reference contexts when calculating retrieval metrics.
- Make `No Evidence` reachable and distinct from model refusal or output blocking.
- Shuffle/interleave factoid, multi-hop, and unanswerable cases so provider warm-up or degradation is not confounded with question type.
- Keep Ragas concurrency separate from online pipeline concurrency.

## Guardrail and Startup Latency

Guardrails will be initialized during application startup rather than synchronously inside the first request's timeout scope. Output-block events retain an internal audit record of the pre-block answer while returning only the safe public response.

## Configuration

New settings will cover:

- Qdrant rerank collection and model;
- Pinecone fallback model;
- provider timeouts and transient retry counts;
- circuit-breaker threshold and cooldown;
- candidate, return, and context budgets;
- SQLite FTS5 path and result limit.

Secrets continue to load only through `Settings` and `.env`. No API key is written to source, logs, tests, or documentation.

## Testing Strategy

Implementation will follow test-driven development:

1. Provider response normalization and candidate index preservation.
2. Qdrant success path and staging cleanup.
3. Qdrant transient failure to Pinecone fallback.
4. Both providers failing produces `reranker_error`.
5. Circuit breaker bypasses an unhealthy Qdrant provider.
6. Query terms are normalized once per candidate-selection call.
7. Exact legal reference and FTS results merge with Pinecone without duplicates.
8. RAG pipeline distinguishes service errors from honest refusal.
9. Evaluation denominators, outcome matrix, timing, and retrieval metrics are correct.

Tests will use injected clients and deterministic response objects. They will not call paid/cloud APIs. Production code will retain real provider implementations and contain no mock fallback.

## Rollout and Verification

- Run focused unit tests after each red-green-refactor cycle.
- Run the full local test suite without cloud calls.
- Run at most one explicitly authorized small live smoke query per provider after configuration is complete.
- Do not rebuild or reingest the Pinecone index.
- Compare the golden evaluation against the existing report only after the user chooses to run the remote evaluation command.

## Non-goals

- Storing the full corpus or all chunk multivectors in Qdrant.
- Running FastEmbed, sentence-transformers, PyTorch, ONNX, or a local reranker.
- Migrating data to MongoDB.
- Automatically deleting or recreating the existing Pinecone index.
