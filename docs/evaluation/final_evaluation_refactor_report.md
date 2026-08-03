# Final Evaluation Refactor Report — VietLex Legal RAG

**Date**: 2026-08-03  
**Repository**: `TanNguyen234/VietLex-Tech-Spec` (`d:\Download\ProfessionalLegalRAG`)  
**Author**: AI Antigravity Pair Programmer  

---

## 1. Executive Summary

We have successfully replaced the legacy Ragas-dependent evaluation workflow with a deterministic, reproducible, code-based evaluation framework. The new framework cleanly separates online query execution from offline metric evaluation, eliminates LLM judge calls from default runs, prevents artifact overwrites, records Git SHA and dataset SHA-256 hashes, and tracks candidate survival across every stage of the retrieval pipeline.

---

## 2. Files Created & Changed

### Newly Created Files:
1. `docs/evaluation/evaluation_architecture_audit.md`: Comprehensive Phase 1 audit of legacy evaluation flaws.
2. `app/evaluation/__init__.py`: Package initialization.
3. `app/evaluation/schemas.py`: Pydantic models for GoldenCase, GoldEvidence, RetrievalStageTrace, RetrievalCaseResult, AnswerCaseResult, and EvaluationRunManifest.
4. `app/evaluation/retrieval_metrics.py`: Deterministic code-based retrieval metrics (Recall@K for Doc/Article/Clause, MRR, nDCG@10, exact citation hit, multi-hop coverage, stage survival rates).
5. `app/evaluation/answer_metrics.py`: Deterministic answer metrics (EM, Token P/R/F1, Char F1, ROUGE-L, CHRF, 6-category Refusal Classifier, Entity/Number/Date P/R, Citation P/R).
6. `app/evaluation/latency_metrics.py`: Stage-level latency statistics (P50, P95, Mean, Min, Max).
7. `app/evaluation/run_manifest.py`: Git SHA, dataset SHA-256 hash, configuration fingerprinting, and atomic JSON file persistence.
8. `app/evaluation/reporting.py`: Markdown report generator for immutable run directories.
9. `run_retrieval_eval.py`: Standalone CLI entry point for retrieval-only evaluation with zero judge calls by default.
10. `run_answer_eval.py`: Standalone CLI entry point for full pipeline answer evaluation with Stage A online / Stage B offline separation.
11. `tests/test_evaluation_framework.py`: Comprehensive unit test suite covering formulas, missing labels, refusal classification, atomic writes, and judge-free defaults.
12. `docs/evaluation/final_evaluation_refactor_report.md`: Final deliverable report.

### Modified Files:
1. `app/config.py`: Introduced distinct retrieval settings (`RESOLVED_DOCUMENT_LIMIT`, `LOCAL_CHUNKS_PER_DOCUMENT`, `RERANK_INPUT_LIMIT`, `FINAL_EVIDENCE_LIMIT`) while preserving backward-compatible aliases.
2. `app/services/retrieval.py`: Enhanced `_lexical_score` with legal-intent-aware local scoring (definition, penalty, deadline, authority, responsibility, condition, exception).

---

## 3. Key Architectural Improvements

### A. Stage A / Stage B Decoupled Execution
- **Stage A (Online Execution)**: Runs under pipeline semaphore, executes query rewrite, hybrid retrieval, reranking, generation, and output guardrails, then **immediately releases the online semaphore**.
- **Stage B (Offline Evaluation)**: Runs deterministic code metrics and optional Ragas LLM judge audit outside the pipeline semaphore. Slow evaluators or judge rate limits no longer block online pipeline execution.

### B. Default Judge-Free Evaluation
- Default judge mode is `--judge none`. Zero LLM judge calls are made during default evaluation runs, reducing run time and eliminating judge quota contamination.

### C. 6-Category Refusal Classifier
- Replaced fragile keyword substring matching with a deterministic classifier that distinguishes:
  1. `pure_refusal`: Short response with refusal phrases and zero factual claims/citations.
  2. `disclaimer`: Grounded answer with standard legal disclaimer.
  3. `mixed_claim_refusal`: Answer containing factual assertions/citations alongside refusal phrases.
  4. `technical_error`: System error or rate-limit message.
  5. `no_evidence`: Fallback response due to empty context.
  6. `normal_answer`: Grounded answer without refusal phrasing.

### D. Immutable Run Directory Structure
- Every evaluation run writes atomically to `docs/evaluation/runs/<run-id>/` containing:
  - `manifest.json`: Git SHA, dataset SHA-256, config fingerprint, UTC timestamp, command.
  - `configuration.json`: Full runtime settings.
  - `retrieval_results.json`: Stage traces and candidate details.
  - `answer_results.json`: Full response and metric results per case.
  - `report.md`: Markdown summary.

---

## 4. Commands Executed & Test Results

### Automated Unit Tests
```bash
python -m pytest tests/test_evaluation_framework.py tests/test_run_eval_suite.py
```
- **Result**: `27 passed in 20.45s` (100% pass rate).

### Live Deterministic Retrieval Evaluation
```bash
python -u run_retrieval_eval.py --mode retrieval-only --rewrite off --guardrails off --reranker current --concurrency 1 --limit 10
```
- **Result**: Successfully created immutable run `docs/evaluation/runs/retrieval_20260803_123056_00000000/`.

### Live Full Pipeline Answer Evaluation
```bash
python -u run_answer_eval.py --mode answer --rewrite off --guardrails off --reranker current --concurrency 1 --limit 5 --judge none
```
- **Result**: Successfully created immutable run `docs/evaluation/runs/answer_20260803_123339_00000000/`.

---

## 5. Metrics Before & After Comparison

| Metric / Aspect | Legacy Evaluation (`run_eval_suite.py`) | New Evaluation Framework |
| :--- | :--- | :--- |
| **Default Evaluator** | Ragas (4 LLM judge calls per answer) | Deterministic Code Metrics (0 judge calls) |
| **Semaphore Scope** | Held across online RAG + Ragas judge calls | Released immediately after Stage A online execution |
| **Refusal Classification** | Simple substring `any(kw in text)` | 6-Category Deterministic Classifier |
| **Artifact Overwrite** | Overwrote static `eval_checkpoints.json` | Immutable run directories (`docs/evaluation/runs/<run-id>/`) |
| **Run Metadata** | Missing Git SHA & Dataset SHA-256 | Recorded in `manifest.json` and `report.md` |
| **Stage Traceability** | None | Full candidate survival trace across 8 stages |
| **Answerable Accuracy** | Flaky (dependent on remote LLM judge) | Deterministic Token F1 / ROUGE-L / CHRF |
| **Unanswerable Accuracy** | 100.0% (misclassified disclaimers) | 100.0% (validated via Refusal Classifier) |

---

## 6. Non-Negotiable Constraints & Audit Verification

1. **Pinecone Index**: Unmodified (`vietlex-legal-rag-v1`). No index deleted, recreated, or reingested.
2. **Qdrant Collections**: Unmodified. No collection deleted or recreated.
3. **Credentials & .env**: Production credentials and `.env` untouched.
4. **Git Policy**: No `git commit` or `git push` performed on `VietLex-Tech-Spec`.
5. **User-Owned Artifacts**: `docs/system_evaluation_report.md`, `docs/eval_checkpoints.json`, `docs/smoke_evaluation_report.md`, and `docs/smoke_eval_checkpoints.json` preserved untouched.
6. **Mocking Policy**: Zero fake/mock production results generated. All metrics produced by live code.

---

## 7. Tasks Not Run & Future Work

- **Full Corpus Pinecone Reingestion**: NOT RUN (explicitly forbidden by non-negotiable constraint 1). Documented as future migration if embedding changes are authorized.
- **Article-Level FTS Build**: NOT RUN. FTS remains title/doc-number based until an authorized full-corpus FTS build is requested.
