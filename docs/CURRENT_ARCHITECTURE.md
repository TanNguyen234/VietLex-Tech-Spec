# CURRENT_ARCHITECTURE.md — Technical Source of Truth

## Architectural Topology

```text
Pinned Hugging Face Legal Corpus (518,255 Documents)
        |
        v
Local SQLite Content Store (Compressed Zstandard Full Text)
        |
        +--> Dense Embeddings: Qdrant Cloud Inference (multilingual-e5-small, 384d)
        |       |
        |       v
        +--> Durable Persistence: Pinecone (hybrid dense + sparse)
        |
        +--> Lexical Search: Local SQLite FTS5 (Title + Doc Number)
```

## Runtime Pipeline Stages

1. **User Query**: Original query used for sparse and exact reference search.
2. **Query Rewrite**: Default OFF; an explicit evaluation run may opt in to a short LLM rewrite. The original query always remains sufficient for production retrieval.
3. **Hybrid Search & Document Resolution**:
   - Pinecone hybrid search (up to `RETRIEVAL_DOCUMENT_LIMIT`).
   - SQLite FTS lookup (up to `LEGAL_FTS_RESULT_LIMIT`).
   - A remote dense failure with usable FTS evidence is `partial_retrieval_error`, not a silent success: answer/retrieval scoring continues and the technical-error counter increments.
   - Merged & balanced document selection (up to `RESOLVED_DOCUMENT_LIMIT`).
4. **Local Structural Chunking & Selection**:
   - Documents resolved from local content store.
   - Structural unit chunking (220 tokens max, 24 overlap).
   - Local chunk selection per document (up to `LOCAL_CHUNKS_PER_DOCUMENT`).
5. **Reranker Candidate Bounding**:
   - Bounded total candidate chunks (up to `RERANK_INPUT_LIMIT`).
6. **Reranking**:
   - Primary: Qdrant ColBERT (`answerdotai/answerai-colbert-small-v1`).
   - Fallback: Pinecone (`bge-reranker-v2-m3`).
7. **Final Context Selection**:
   - Top reranked evidence chunks (up to `FINAL_EVIDENCE_LIMIT` within `LLM_CONTEXT_MAX_TOKENS`).
8. **Answer Generation**:
   - Primary: Google Cloud Vertex AI through ADC, `gemini-3.5-flash`.
   - On a typed Vertex technical failure, secondary providers are attempted in order: OpenRouter, Gemini Direct API, NVIDIA NIM, and Groq, followed by the existing secondary-model pass.
   - Current secondary model IDs remain pinned by `app/evaluation/provider_catalog.py`: OpenRouter `meta-llama/llama-3.3-70b-instruct`; Gemini API `gemini-2.0-flash` then `gemini-1.5-flash`; NVIDIA `meta/llama-3.3-70b-instruct`; Groq `llama-3.3-70b-versatile` then `llama3-8b-8192`.
   - Runtime evidence records the actual provider/model, `fallback_used`, and the Vertex `primary_error_kind`. NeMo guardrails use the same Vertex-primary adapter and legacy direct-API fallbacks. OmniGate remains evaluator infrastructure rather than an answer or guardrail primary.

## Phase G0 Google Cloud model boundary

- `app/services/vertex_ai.py` owns ADC discovery, reusable `google-genai` client creation, timeouts/retries, error mapping, generation, and embedding calls.
- `gemini-embedding-2` is probe-only at 384/768/1024 dimensions. It is never used to query the existing E5 Pinecone index.
- `run_vertex_g0_probe.py` performs isolated live checks and writes immutable artifacts without credential material or vector writes.
- Ragas is never enqueued by `/chat`; opt-in offline audits use Vertex AI `gemini-3.5-flash` through ADC as the primary judge and retain legacy APIs as best-effort fallbacks.
- The input-rail prompt explicitly permits lawful legal questions about public authorities, policy, office, and jurisdiction; ambiguous inputs default to allow while clear jailbreak/off-topic/harm requests remain blocked.
- Pinecone `vietlex-legal-rag-v1`, Qdrant staging, SQLite FTS, the content store, and production retrieval topology remain unchanged in G0.

## Verification & Provenance

- Configuration declarations in `app/config.py` do not prove runtime usage until verified by code execution.
- Evaluation runs from dirty working trees are marked with `git_dirty=true` and `git_diff_sha256`.

## Opt-in structural v2 parallel path

When `STRUCTURAL_BACKEND_ENABLED=true`, the explicitly gated Qdrant structural pilot and `get_legal_retriever()` (Pinecone v1 + local FTS) execute concurrently. Neither lane can prevent the other from searching. Candidate evidence is always canonically deduplicated by document/Điều/Khoản. `CROSS_LANE_FINAL_RERANK_ENABLED=true` optionally passes the combined pool through one Pinecone BGE final rerank before the shared evidence/token budget; it remains off by default until the required identical-input A/B authorizes cutover. If the optional final reranker fails, the system falls back to bounded canonical rank interleave and reports `partial_retrieval_error`.

```text
Pinned local primary-legislation scope (827 documents)
        |
        v
134,334 immutable structural records (420 max tokens / 48 overlap)
        |
        +--> Qdrant Cloud Inference dense: multilingual-e5-small, 384d
        +--> Qdrant corpus-level sparse: qdrant/bm25 with IDF
        |
        v
Opt-in collection vietlex-legal-rag-v2-pilot-384
        |
        +--> concurrent dense / BM25 / exact-reference lanes
        +--> deterministic RRF and per-document cap
        +--> Pinecone bge-reranker-v2-m3 by default
        +--> direct structural evidence (no second local re-chunk)
        +--> bounded merge with the concurrent Pinecone-v1 + FTS lane
```

A failure in one lane with usable evidence from the other remains observable as `partial_retrieval_error`. If both lanes fail, the pipeline fails closed. Structural coverage remains 827 documents and is not represented as full-corpus coverage.

## Grounded semantic cache

Semantic cache identity binds corpus revision and a pipeline fingerprint covering retrieval/embedding/reranker/answer-model, `ANSWER_PROMPT_VERSION`, and evidence-budget configuration. Prompt or grounding-policy changes must bump this explicit version. Only grounded `ok` responses are written. Evidence contexts are serialized with a SHA-256 and restored on a cache hit; legacy or tampered entries fail open to fresh retrieval.

## Public runtime lifecycle

- `APP_ENV=production` requires a stable `WEB_SESSION_SECRET`; production startup never silently rotates anonymous identities.
- New MongoDB session and interaction records carry `expires_at` and are governed by TTL indexes using `DATA_RETENTION_DAYS` (30 days by default). Explicit session deletion removes both the session and its owned interaction logs.
- Browser progress uses SSE rather than repeated 400 ms HTTP polling. Progress state remains bounded and process-local, so multi-replica deployment still requires sticky routing or a shared event backend.

Each inference document is contract-versioned as `vietlex-structural-document-v2` and contains the corpus title, document number, legal type, structural path, citation, and unchanged chunk body. Its SHA-256 is persisted separately from the body/chunk hash and participates in checkpoint identity.

The pre-upload model probe is corpus-discriminative rather than relevant-only: 1,748 real verified rows, 825 deterministic real hard negatives (one per non-gold primary-law document), and 64 stratified title canaries. Default probe execution uses Qdrant Cloud Inference only; Pinecone reference inference is not constructed. Absolute pass gates are gold Document Recall@10 `1.0`, gold structural Recall@10 at least `0.95`, and canary Document Recall@10 at least `0.90`.

The final pilot benchmark requires fused Document Recall@24 `1.0`, applicable Article Recall@24 at least `0.95`, applicable Clause Recall@24 at least `0.90`, all-required coverage at least `0.95`, and zero no-candidate/retrieval/reranker error rates. It reports reranker input/output deltas on identical cases; it does not infer reranker quality when verified evidence is absent from its input.

Remote ingestion is ordered and artifact-bound: `create -> probe-model -> upload -> finalize -> verify -> benchmark`. Runtime/evaluation reads do not create indexes or mutate payload schemas. Raw structural traces use only `dense_hits`, `bm25_hits`, `exact_hits`, `fused_hits`, `reranker_input`, `reranker_output`, and `final_hits`; legacy metric-v3 names exist only in a declared offline adapter. The evaluator records the effective structural collection, limits, reranker mode, and Pinecone fallback in its configuration fingerprint.
