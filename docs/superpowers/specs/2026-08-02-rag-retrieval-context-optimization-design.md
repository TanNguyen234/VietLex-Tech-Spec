# RAG Retrieval and Context Optimization Design

**Date:** 2026-08-02  
**Status:** Approved by the user after the ingestion audit  
**Scope:** Runtime retrieval, legal chunking, reranking, LLM context budgeting, and future ingestion representation

## Constraints

- The Pinecone corpus has already finished ingesting. This change must not delete, migrate, or rebuild it.
- Pinecone remains the persistent vector store. Qdrant Cloud is used only for managed dense embedding and reranking.
- Runtime changes must stay compatible with the current document-level vectors.
- External API calls are not part of the automated verification run; unit tests exercise the local decision logic.

## Current Problems

1. A retrieved legal document is split into 420-word windows at query time, so a clause boundary can be lost and a window can contain unrelated provisions.
2. Up to 64 chunks are sent to reranking, including zero-overlap lexical candidates; this increases latency and can discard a relevant later document on ties.
3. The rewritten query is used for both dense and sparse retrieval, which can remove exact article numbers, document codes, dates, and named entities from sparse search.
4. Pinecone relevance is discarded before chunk selection and candidate diversity is not bounded per document.
5. The final LLM prompt has a per-chunk character slice but no global context budget.
6. Future ingestion uses the same truncated dense text for both dense and sparse representations, even though sparse retrieval benefits from the full outline and document text.

## Design

### Legal chunking

- Split at article boundaries, then at numbered clause boundaries.
- Keep article and clause labels in each chunk so evidence remains self-contained.
- Target a maximum of 280 whitespace tokens per chunk.
- Use a 24-token overlap only when a single structural unit itself is longer than the limit. Do not overlap independent clauses.
- Preserve the existing fallback for documents without recognizable legal structure.

### Retrieval and candidate selection

- Use the rewritten query for dense semantic retrieval.
- Use the original user query for sparse retrieval so exact legal identifiers survive rewriting.
- Select at most 24 rerank candidates and at most two chunks from the same document.
- Rank positive lexical matches first, then fill remaining capacity in Pinecone document order. This preserves semantic fallback without allowing zero-score ties to crowd out all later documents.
- Send compact citation plus chunk text to reranking; URLs and repeated titles are reserved for the final answer context.

### Reranking and final evidence

- Ask the reranker for more results than the final answer consumes, then apply local diversity and budget rules.
- Keep the reranker score threshold configurable because provider score normalization is deployment-specific.
- Return at most three evidence chunks, with no more than two from one document and within the configured context token budget.

### LLM context budget

- Apply one global token budget to the assembled context rather than independently slicing every chunk.
- Keep only complete high-ranked chunks when possible; truncate only the final accepted chunk if it is the sole way to provide evidence.
- Preserve citations and source URLs in the final prompt.

### Future ingestion v2

- Continue storing one Pinecone point per legal document to avoid a many-million-vector expansion.
- Dense representation order becomes metadata/header, structural outline, then representative body text, bounded conservatively for the embedding model.
- Sparse representation uses `build_sparse_text` independently from dense text.
- These representation changes require an explicit future rebuild and are not applied to the completed index by this task.

## Failure behavior and observability

- A genuine no-hit response remains distinct in logs from an external retrieval failure.
- Retrieval stages record dense/sparse search, content resolution, chunk selection, and rerank latency.
- Existing public service interfaces remain backward compatible where practical.

## Verification

- Unit tests cover clause-aware chunking, per-document candidate diversity, original-vs-rewritten query routing, reranker payload size, and the global LLM context budget.
- The focused tests run without Pinecone/Qdrant writes.
- No full ingestion command is executed as part of verification.
