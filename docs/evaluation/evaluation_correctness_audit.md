# Evaluation Correctness Audit — VietLex Legal RAG

**Date**: 2026-08-03  
**Commit HEAD**: `8bd5423da0daca16532a8c4820b7640fd48fac82`  
**Repository**: `TanNguyen234/VietLex-Tech-Spec` (`d:\Download\ProfessionalLegalRAG`)  

---

## 1. Overview

This audit verifies critical correctness defects in the current evaluation codebase prior to refactoring.

---

## 2. Defect Breakdown & Verification

### A. Separated Settings Are Not Fully Wired
- **Inspection Findings**:
  - `app/config.py` declares `RESOLVED_DOCUMENT_LIMIT: 16`, `LOCAL_CHUNKS_PER_DOCUMENT: 4`, `RERANK_INPUT_LIMIT: 24`, and `FINAL_EVIDENCE_LIMIT: 3`.
  - However, `app/services/retrieval.py` still directly accesses legacy settings:
    - Line 407: `limit=self._settings.RERANK_CANDIDATE_LIMIT` (used for document resolution).
    - Line 452: `self._settings.RERANK_PER_DOCUMENT_LIMIT` (used for local per-doc chunk selection).
    - Line 615: `limit=self._settings.RERANK_CANDIDATE_LIMIT` (used for reranker candidate bounding).
    - Line 485: `max_chunks=self._settings.RERANK_TOP_K` (used for final evidence output).
- **Consequence**: The new settings fields in `app/config.py` were completely dead/unwired. `RERANK_CANDIDATE_LIMIT` conflated both document resolution limits and total reranker candidate limits.

### B. Answer Evaluation Executes Retrieval Twice
- **Inspection Findings**:
  - In `run_answer_eval.py` (lines 284-289):
    1. Line 284: `stage_a_res = await run_stage_a_online(...)` -> calls `run_advanced_rag()` -> triggers `get_legal_retriever().retrieve_detailed()` -> executes hybrid search, local chunking, reranking, and generation.
    2. Line 289: `retrieval_case_res = await evaluate_single_retrieval_case(...)` -> triggers `get_legal_retriever().retrieve_detailed()` a SECOND time!
- **Consequence**: Full pipeline answer evaluation makes duplicate remote Qdrant, Pinecone, and reranker API calls for every test query. This doubles latency, wastes quota, and risks non-identical evidence between Stage A generation and Stage B retrieval metrics.

### C. CLI Flags Are Not Correctly Wired
- **Inspection Findings**:
  - `--reranker`: Passing `--reranker pinecone-bge` in `run_retrieval_eval.py` set `settings.PINECONE_RERANK_MODEL = "bge-reranker-v2-m3"`. However, `RemoteReranker.rerank()` in `app/services/remote_reranker.py` checks `self._qdrant` first and routes to Qdrant ColBERT regardless of `PINECONE_RERANK_MODEL`!
  - `--mode`: `run_retrieval_eval.py` accepts `--mode answer` but only runs retrieval. `run_answer_eval.py` accepts `--mode retrieval-only` but only runs answer.
  - `--rewrite off`: `rewrite_query` in `run_advanced_rag` was still called if length > 10 words unless `run_advanced_rag` was explicitly rewritten.

### D. Stage Metrics Use Incorrect Candidate Sets
- **Inspection Findings**:
  - In `run_retrieval_eval.py` line 181, `retrieved_chunks` passed to `calculate_case_retrieval_metrics` contained only `outcome.evidence` (top 3 final evidence chunks).
  - `calculate_case_retrieval_metrics` then calculated `doc_recall` at @1, @3, @5, @10, @24 using this 3-element list!
- **Consequence**: Document Recall @5, @10, @24 was computed on a list of at most 3 final evidence chunks, making Recall@24 structurally impossible to exceed 3/24.

### E. Answer Metric Denominator & Formatting Bugs
- **Inspection Findings**:
  - Refusal precision was computed as `(correct_refusals / all_refusals) if all_refusals else 0.0`. When `all_refusals == 0`, it returned `0.0` instead of `None` / `N/A`.
  - Citation precision returned `1.0` when `ref_cites` was empty, artificially inflating precision for reference-less answers.
  - `answerable_accuracy` was named as if measuring factual correctness, but was actually `token_f1 >= 0.50` pass rate.
  - Undefined metrics were formatted as `0.0000` or caused `TypeError: unsupported format string passed to NoneType.__format__`.

---

## 3. Plan of Action

1. **Phase 2 (Run Provenance)**: Add `git_dirty`, `git_diff_sha256`, `evaluation_dataset_sha256`, `gold_label_sidecar_sha256`, `profile_name` to manifest. Fail closed if run directory exists.
2. **Phase 3 (Explicit Evaluation Profiles)**: Create typed `EvaluationProfile` dataclass supporting `legacy`, `separated_no_intent`, `separated_intent`.
3. **Phase 4 & 5 (Wiring & Typed Stage Traces)**: Wire `resolved_document_limit`, `local_chunks_per_document`, `rerank_input_limit`, `final_evidence_limit` strictly to their respective pipeline stages. Capture typed candidate traces for all 8 stages.
4. **Phase 6 (Correct Stage Metrics)**: Calculate Document Recall@K from merged/resolved document hits; calculate Article/Clause Recall@K at local chunks, reranker input, reranker output, and final evidence. Trace gold item first-loss stage.
5. **Phase 7 (Reranker Modes)**: Implement explicit `current`, `qdrant-only`, `pinecone-only` routing in `RemoteReranker`.
6. **Phase 8 & 9 (Single Retrieval & Metric Fixes)**: Ensure Stage A returns single execution result; render undefined metrics as `N/A`; rename `answerable_accuracy` to `answer_similarity_pass_rate`.
7. **Phase 10 (Reporting & Legacy Status)**: Create `docs/evaluation/LEGACY_RUN_STATUS.md` documenting why preliminary runs are invalid for quality decisions.
8. **Phase 11 (Dataset Applicability Audit)**: Create LLM-free `audit_golden_dataset.py` and output sidecar `docs/evaluation/gold_labels/namsyntax_legal_qa_420_labels.json` and report `docs/evaluation/golden_dataset_applicability_report.md`.
9. **Phase 12-14 (Tests, Baselines & Comparison Report)**: Add comprehensive unit tests, run clean deterministic baselines across all 3 profiles, and output `docs/evaluation/evaluation_correctness_and_baseline_report.md`.
