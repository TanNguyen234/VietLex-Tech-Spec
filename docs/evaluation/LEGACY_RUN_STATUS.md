# LEGACY EVALUATION RUN STATUS — Preliminary Run Status & Validity

**Date**: 2026-08-03  
**Status**: `PRELIMINARY / INVALID FOR DECISION MAKING`  

---

## 1. Executive Notice

The preliminary evaluation run directories created prior to commit `8bd5423` (including `retrieval_20260803_123056_00000000` and `answer_20260803_123339_00000000`) are retained as historical artifacts to ensure strict compliance with non-negotiable run preservation rules.

However, **these legacy runs MUST NOT be used for retrieval quality, model selection, or architecture decisions**.

---

## 2. Invalidating Factors

1. **Zero Verified Gold-Label Coverage**: The 420-case dataset lacked explicit `document_id`/`article` gold labels, resulting in 0 scored cases for exact legal citation identity metrics.
2. **Incomplete Stage Candidate Tracing**: Stage traces did not record candidate elements for document candidates, structural unit chunking, or reranker output candidates.
3. **CLI / Runtime Mismatch**: Configuration settings (`RESOLVED_DOCUMENT_LIMIT`, `LOCAL_CHUNKS_PER_DOCUMENT`, `RERANK_INPUT_LIMIT`, `FINAL_EVIDENCE_LIMIT`) were declared in settings but were not wired into `app/services/retrieval.py`.
4. **Uncommitted Working-Tree State**: Manifests did not record `git_dirty` status or a Git diff SHA-256 hash.
5. **Answer Evaluation Double Retrieval Execution**: `run_answer_eval.py` executed `retrieve_detailed` twice per query, doubling remote latency and risking non-identical evidence.
6. **Undefined Metrics Rendered as Zero/One**: Undefined metrics (e.g. refusal precision with 0 predicted refusals, or citation precision with 0 reference citations) defaulted to `0.0` or `1.0` instead of `N/A`.
