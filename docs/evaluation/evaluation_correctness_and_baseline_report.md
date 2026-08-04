# VietLex Evaluation Framework Correctness Audit & Baseline Benchmark Report

> [!WARNING]
> **SUPERSEDED / INVALID BASELINE NOTICE**: The profile comparison results documented in Section 4 of this report are superseded and invalid for profile comparison due to evaluator profile-passing, limit-coupling, and candidate-tracing defects. See [INVALID_BASELINE_NOTICE.md](file:///d:/Download/ProfessionalLegalRAG/docs/evaluation/INVALID_BASELINE_NOTICE.md) for details. The benchmark tables in this document are retained strictly for historical reference.

**Date**: 2026-08-03  
**Repository**: `TanNguyen234/VietLex-Tech-Spec`  
**Git Commit SHA**: `8bd5423da0daca16532a8c4820b7640fd48fac82`  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0` (518,255 document Pinecone index `vietlex-legal-rag-v1`)

---

## 1. Executive Summary

This report documents the systematic repair of the VietLex evaluation framework, the golden dataset applicability audit across the durable 518,255-document corpus, and clean baseline retrieval benchmarks executed across three evaluation profiles (`legacy`, `separated_no_intent`, `separated_intent`).

### Key Findings
1. **Framework Integrity**: 100% of unit tests pass cleanly (133 passed, 1 skipped). All false-positive metrics, state leakage, dirty git tracking, and candidate truncation issues identified in legacy code have been repaired.
2. **Golden Dataset Mapping**:
   - Out of 420 cases in `namsyntax_legal_qa_420.json`, only **12 cases** (2.86%) map to verifiable gold document/article labels in the current 518,255-document corpus.
   - **175 cases** (41.67%) are unanswerable questions.
   - **233 cases** (55.48%) reference documents or articles not present in the current Pinecone index/content store or have ambiguous metadata anchors.
3. **Retrieval Baseline Benchmarks**:
   - Baseline Document Recall @ 1: **0.0833** (8.33% - 1 hit out of 12 verified cases: `case_349`).
   - Baseline Article Recall @ 1: **0.0833** (8.33%).
   - Technical Error Rate: **0.0%** (100% system execution reliability across all profiles).
   - Mean Retrieval Latency: **6.64s** (`separated_no_intent`), **8.59s** (`separated_intent`), **9.91s** (`legacy`).

---

## 2. Legacy Audit & Correctness Repairs Implemented

The following critical defects identified in legacy evaluation code have been resolved:

| Defect / Deficient Pattern | Impact | Technical Fix Implemented |
| :--- | :--- | :--- |
| **A. Missing Git & Dataset Provenance** | Unverifiable run configs, silent dirty working tree evaluation. | Recorded `git_sha`, `git_dirty`, `git_diff_sha256`, dataset SHA-256, and configuration fingerprint in atomic manifests (`app/evaluation/run_manifest.py`). |
| **B. Implicit Limit Coupling** | Retrieval stage limits were hardcoded to single production constants. | Introduced explicit evaluation profiles (`app/evaluation/profiles.py`) separating candidate limits (`resolved_document_limit`, `local_chunks_per_document`, `rerank_input_limit`, `final_evidence_limit`). |
| **C. Lack of Stage Candidate Tracing** | Zero visibility into where ground-truth evidence drops out. | Added 9-stage candidate tracking (`RetrievalStageTrace` & `StageCandidate`) in `app/services/retrieval.py` tracking candidates from Pinecone/FTS to final output. |
| **D. Silent Reranker Fallback** | Reranker failures defaulted to legacy sorting without reporting errors. | Added explicit `reranker_mode` selection (`current`, `pinecone-only`, `qdrant-only`) and typed `reranker_error` reporting in `app/services/remote_reranker.py`. |
| **E. Flawed Answer & Refusal Metrics** | String match false positives and silent `0.0` values for unanswerable queries. | Updated `app/evaluation/answer_metrics.py` to return `None` (`N/A`) for undefined answerable metrics and enforce top-level refusal classification. |

---

## 3. Golden Dataset Audit & Applicability Report

An automated audit of the 420-case golden dataset (`namsyntax_legal_qa_420.json`) was executed against the local 518,255-document SQLite content store using strict citation parsing and full-text SHA-256 anchor matching (`audit_golden_dataset.py`).

### Dataset Partitioning Results

| Category / Partition | Case Count | % of Dataset | Status & Action |
| :--- | ---: | ---: | :--- |
| **Verified Evidence** | **12** | **2.86%** | Gold evidence document and article verified in 518k corpus. **Used for primary clean baseline evaluation.** |
| **Ambiguous Anchor** | 27 | 6.43% | Document exists but target article/clause anchor missing or ambiguous in text. |
| **Unanswerable Questions** | 175 | 41.67% | Ground truth explicitly unanswerable. Evaluated for refusal precision/recall. |
| **Document Not Found in Corpus** | 206 | 49.05% | Reference document number absent from the 518,255-document store. |
| **Total Dataset** | **420** | **100.00%** | Audit artifacts written to `docs/evaluation/gold_labels/namsyntax_legal_qa_420_labels.json`. |

---

## 4. Clean Baseline Benchmark Results

Evaluations were executed across the verified 12-case benchmark subset for all 3 evaluation profiles.

### Comparison Table across Profiles

| Metric | Legacy Profile (`legacy`) | Separated No Intent (`separated_no_intent`) | Separated Intent (`separated_intent`) |
| :--- | :---: | :---: | :---: |
| **Run ID** | `retrieval_20260803_134331_...` | `retrieval_20260803_134556_...` | `retrieval_20260803_134826_...` |
| **Scored Gold Coverage** | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) |
| **Technical Error Rate** | 0.0% | 0.0% | 0.0% |
| **No Candidate Rate** | 0.0% | 0.0% | 0.0% |
| **Document Recall @ 1** | **0.0833** | **0.0833** | **0.0833** |
| **Document Recall @ 5** | 0.0833 | 0.0833 | 0.0833 |
| **Document Recall @ 24** | 0.0833 | 0.0833 | 0.0833 |
| **Article Recall @ 1** | **0.0833** | **0.0833** | **0.0833** |
| **Article Recall @ 6** | 0.0833 | 0.0833 | 0.0833 |
| **Clause Recall @ 1** | 0.0833 | 0.0833 | 0.0833 |
| **Article MRR** | 0.0833 | 0.0833 | 0.0833 |
| **nDCG @ 10** | 0.0833 | 0.0833 | 0.0833 |
| **Mean Retrieval Latency (`t_retrieval`)** | 9.91s | **6.64s** | 8.59s |
| **Mean Total Latency (`t_total`)** | 10.79s | **7.45s** | 9.15s |

---

## 5. Retrieval Failure Analysis & Bottleneck Root Causes

Across all 3 profiles, baseline retrieval achieved **0.0833 Article Recall** (1 successful hit: `case_349`). The remaining 11 verified cases failed to retrieve the gold evidence. The stage trace logs reveal the primary bottlenecks:

1. **E5 Query Embedding Prefix Mismatch**:
   - Dense query embedding in `app/services/retrieval.py` uses `intfloat/multilingual-e5-small`. E5 models strictly require the `query: ` prefix during inference. Without `query: `, dense vector dot products misalign with `passage: ` indexed vectors in Pinecone, resulting in dense hit irrelevance.
2. **SQLite FTS Title-Only Search Constraint**:
   - The current FTS SQLite index matches exact document title text and document numbers, but does not index full article bodies. When queries contain general legal questions without exact document numbers, FTS returns 0 hits, forcing full reliance on dense hybrid retrieval.
3. **Reranker Input Limit Bottleneck**:
   - In `legacy` profile, reranker candidates were constrained to 12 documents total. If Pinecone initial dense search ranked the target document at rank >24, the gold document was eliminated before chunk resolution or reranking.

---

## 6. Recommendations & Next Steps

1. **Keep Framework Pinned**: Deterministic metrics and atomic run manifests must remain mandatory for all future retrieval optimization experiments.
2. **Prioritize Query Prefix & Hybrid Search Tuning**:
   - Test adding `query: ` prefix to dense query embeddings in `app/services/retrieval.py`.
   - Implement article-body FTS search in SQLite content store.
3. **Dataset Expansion**:
   - Maintain the 12 verified cases as the golden core benchmark while building expanded gold labels for the 206 missing corpus documents.
