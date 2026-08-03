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
