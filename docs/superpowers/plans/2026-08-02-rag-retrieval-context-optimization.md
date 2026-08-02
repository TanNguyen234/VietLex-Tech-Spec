# RAG Retrieval and Context Optimization Implementation Plan

> Execute in the current workspace without rebuilding or deleting the completed Pinecone index.

**Goal:** Reduce inference latency and prompt size while improving legal evidence precision and retaining compatibility with the completed document-level index.

**Architecture:** Keep document retrieval in Pinecone and managed inference in Qdrant. Split retrieved documents into clause-aware chunks locally, select a small diverse rerank set, rerank compact evidence, then enforce a global LLM context budget. Prepare separate dense/sparse ingestion representations only for a future explicit rebuild.

**Tech stack:** Python 3.12, pytest, Pinecone SDK, Qdrant Client, FastAPI/Pydantic settings.

---

### Task 1: Add behavior tests for legal structural chunking

**Files:**
- Modify: `tests/ingestion/test_legal_text.py`
- Modify: `app/ingestion/legal_text.py`

1. Add a fixture containing one long article with multiple numbered clauses.
2. Assert clause citations are accurate, independent short clauses do not overlap, and every chunk stays within the limit.
3. Run the focused test and observe failure against the current article-window implementation.
4. Implement article-then-clause splitting with fallback overlap only inside an oversized structural unit.
5. Re-run the focused test.

### Task 2: Add behavior tests for compact, diverse retrieval

**Files:**
- Modify: `tests/services/test_retrieval.py`
- Modify: `app/services/retrieval.py`
- Modify: `app/config.py`

1. Add tests proving positive lexical candidates are preferred, zero-score semantic fallback remains available, and per-document limits are enforced.
2. Add a test proving dense embedding receives the rewritten query while sparse encoding receives the original query.
3. Add a test proving the reranker receives no more than the configured candidate limit and returns evidence within document/token limits.
4. Run the tests and observe the expected failures.
5. Add configurable chunk, candidate, rerank, and context limits.
6. Implement separate dense/sparse query routing, candidate selection, compact rerank documents, and final evidence budgeting.
7. Re-run focused retrieval tests.

### Task 3: Add a global prompt-context budget

**Files:**
- Modify: `tests/test_rag_pipeline.py`
- Modify: `app/services/rag_pipeline.py`

1. Add tests proving context assembly never exceeds the global word budget and preserves the highest-ranked evidence first.
2. Add a test proving the original query is passed to sparse retrieval while the rewrite is used for dense retrieval.
3. Run tests and observe failure.
4. Implement bounded context assembly and dual-query retrieval invocation.
5. Re-run focused RAG tests.

### Task 4: Prepare future ingestion v2 without touching the current index

**Files:**
- Modify: `tests/ingestion/test_legal_text.py`
- Modify: `tests/ingestion/test_hf_pipeline.py`
- Modify: `app/ingestion/legal_text.py`
- Modify: `app/ingestion/hf_pipeline.py`

1. Add tests proving the dense representation places the structural outline before body text and remains bounded.
2. Add a pipeline test proving dense and sparse encoders receive separate representations.
3. Observe the tests fail with the current shared representation.
4. Implement the v2 representation and separate sparse input.
5. Run focused ingestion tests only; do not run `full` ingestion.

### Task 5: Document, review, and verify

**Files:**
- Modify: `README.md`
- Modify: `docs/huggingface-ingestion-runbook.md`

1. Document the runtime query path, operational limits, and the fact that ingestion-v2 requires an explicit rebuild.
2. Run focused tests for ingestion, retrieval, and RAG.
3. Run the broader relevant test set if focused tests pass.
4. Use the repository change graph to inspect affected flows and review the diff.
5. Report exact verification commands and any remaining calibration work. Do not commit or push without user approval.
