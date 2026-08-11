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
2. **Query Rewrite**: Optional short query rewriting using LLM.
3. **Hybrid Search & Document Resolution**:
   - Pinecone hybrid search (up to `RETRIEVAL_DOCUMENT_LIMIT`).
   - SQLite FTS lookup (up to `LEGAL_FTS_RESULT_LIMIT`).
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
   - Remote LLM call via OmniGate / provider chain.

## Verification & Provenance

- Configuration declarations in `app/config.py` do not prove runtime usage until verified by code execution.
- Evaluation runs from dirty working trees are marked with `git_dirty=true` and `git_diff_sha256`.

## Opt-in structural v2 path (not production)

The codebase also contains an explicitly gated Qdrant structural pilot. It does not alter `get_legal_retriever()` or the Pinecone v1 topology above.

```text
Pinned local primary-legislation scope (827 documents)
        |
        v
134,334 immutable structural records (420 max tokens / 48 overlap)
        |
        +--> Qdrant Cloud Inference dense: Qwen3-Embedding-0.6B, 1024d
        +--> Qdrant corpus-level sparse: qdrant/bm25 with IDF
        |
        v
Opt-in collection vietlex-legal-rag-v2-pilot
        |
        +--> concurrent dense / BM25 / exact-reference lanes
        +--> deterministic RRF and per-document cap
        +--> existing remote reranker chain
        +--> direct structural evidence (no second local re-chunk)
```

Each inference document is contract-versioned as `vietlex-structural-document-v2` and contains the corpus title, document number, legal type, structural path, citation, and unchanged chunk body. Its SHA-256 is persisted separately from the body/chunk hash and participates in checkpoint identity.

The pre-upload model probe is corpus-discriminative rather than relevant-only: 1,748 real verified rows, 825 deterministic real hard negatives (one per non-gold primary-law document), and 64 stratified title canaries. Default probe execution uses Qdrant Cloud Inference only; Pinecone reference inference is not constructed. Absolute pass gates are gold Document Recall@10 `1.0`, gold structural Recall@10 at least `0.95`, and canary Document Recall@10 at least `0.90`.

The final pilot benchmark requires fused Document Recall@24 `1.0`, applicable Article Recall@24 at least `0.95`, applicable Clause Recall@24 at least `0.90`, all-required coverage at least `0.95`, and zero no-candidate/retrieval/reranker error rates. It reports reranker input/output deltas on identical cases; it does not infer reranker quality when verified evidence is absent from its input.

Remote execution is ordered and artifact-bound: `create -> probe-model -> upload -> finalize -> verify -> benchmark`. The benchmark requires an exact `PASS_VERIFY` receipt and exact P2 comparison provenance before any remote client is constructed. Its raw trace uses only `dense_hits`, `bm25_hits`, `exact_hits`, `fused_hits`, `reranker_input`, `reranker_output`, and `final_hits`; legacy metric-v3 names exist only in a declared offline adapter.
