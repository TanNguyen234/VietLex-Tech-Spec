# VIETLEX EVALUATION FRAMEWORK V2.1 PREFLIGHT & REPAIR REPORT

**Date**: 2026-08-04  
**Repository**: `TanNguyen234/VietLex-Tech-Spec`  
**Starting HEAD**: `c31fade1c5fdfa3dcbee84a4e39b45d0c1501ffc`  
**Clean Live Retrieval Baseline Status**: `BLOCKED` (Selected verified case count is 0)  
**Git Commit / Push Status**: `PASS` (No git commit or git push executed)  

---

## 1. System Status Summary

| Check Item | Status | Description |
| :--- | :---: | :--- |
| **Offline Test Suite Execution** | `PASS` | `python -m pytest -q` passed cleanly (138 passed, 1 skipped in 67.58s) |
| **Provider / Network Isolation** | `PASS` | Provider call count = 0 (No Pinecone, Qdrant, or LLM network calls) |
| **Preflight Profile Fingerprint Uniqueness** | `PASS` | Distinct fingerprints generated across all 3 profiles |
| **Preflight Selected Case Consistency** | `PASS` | Identical selected case IDs (`[]`, SHA-256: `4f53cda18c2...`) across profiles |
| **Audit Counter Reconciliation** | `PASS` | 100% agreement across sidecar, summary JSON, report v2, and repair report |
| **Historical Run Preservation** | `PASS` | Pre-existing run artifact checksums remain 100% identical |
| **Clean Live Retrieval Benchmark** | `BLOCKED` | Selected case count is 0 under verified gold policy |
| **Generation & Guardrails Execution** | `NOT RUN` | Live answer generation and LLM judge calls disabled per prompt |
| **Corpus / Index Mutation** | `NOT RUN` | No embedding migration, FTS rebuild, or vector collection mutation |
| **Git Push / Commit Execution** | `STATIC ONLY` | Working tree modified for inspection; 0 commits or pushes executed |

---

## 2. Environment & Provenance Identifiers

- **Starting Git HEAD**: `c31fade1c5fdfa3dcbee84a4e39b45d0c1501ffc`
- **Ending Git Dirty Status**: `git_dirty = True` (Modified files: `app/evaluation/retrieval_metrics.py`, `app/evaluation/schemas.py`, `audit_golden_dataset.py`, `run_answer_eval.py`, `run_retrieval_eval.py`, `tests/test_evaluation_framework.py`, `tests/services/test_retrieval.py`, `tests/conftest.py`)
- **Dataset SHA-256**: `84c93a52147321ebf54eb75618ea45731adab74676579cfeb1bf2bbfaaf81cc8` (`app/data/namsyntax_legal_qa_420.json`)
- **Gold Sidecar V2 Schema Version**: `2.0.0`
- **Gold Sidecar SHA-256**: `08d1978280687bd7bfbe65d64ff1eef4539ef2a233b28b7880d9ee07908b8b09` (`docs/evaluation/gold_labels/namsyntax_legal_qa_420_labels_v2.json`)
- **Audit Summary JSON**: `docs/evaluation/gold_labels/namsyntax_legal_qa_420_audit_summary_v2.json`

---

## 3. Reconciled Audit Counters

All counters generated from a single in-memory audit run:

- **Total Test Cases**: `420`
- **Exact Total Evidence Items**: `482`
- **Exact Verified Evidence Items**: `0`
- **Exact Fully Verified Cases**: `0`
- **Exact Fully Verified Factoid Cases**: `0`
- **Exact Fully Verified Multi-Hop Cases**: `0`
- **Exact Partial Verified Multi-Hop Cases**: `0`

### Evidence Item Status Breakdown
| Primary Status | Item Count | Percentage |
| :--- | ---: | ---: |
| `no_citation_extracted` | 228 | 47.3% |
| `unanswerable` | 175 | 36.3% |
| `not_found_by_local_deterministic_audit` | 78 | 16.2% |
| `document_found_anchor_not_found` | 1 | 0.2% |
| **Total** | **482** | **100.0%** |

---

## 4. Offline Preflight Comparison Across Profiles

Executed via `run_retrieval_eval.py --preflight --verified-only --gold-policy all-required-verified --rewrite off --reranker current`:

| Evaluation Profile | Selected Cases | Selected Case IDs SHA-256 | Profile Fingerprint | Provider Calls | Preflight Result |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `legacy` | 0 (`[]`) | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | `c2c47a3cbfa911ffb861c37c2238a3a4b4ab26972959f3368eee464e6e097d40` | 0 | Exit non-zero (`BLOCKED`) |
| `separated_no_intent` | 0 (`[]`) | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | `77e1b3c4895cd483ab18022a8953f28f4157cfd4366146845d37fd81775a7d47` | 0 | Exit non-zero (`BLOCKED`) |
| `separated_intent` | 0 (`[]`) | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | `37101b29b62fe051deac784212bfefad67f6655ee03947e72e8704ac7bc3496d` | 0 | Exit non-zero (`BLOCKED`) |

### Preflight Artifacts Generated
- `docs/evaluation/preflight/preflight_legacy.json`
- `docs/evaluation/preflight/preflight_separated_no_intent.json`
- `docs/evaluation/preflight/preflight_separated_intent.json`
- `docs/evaluation/preflight/latest_preflight.json`
- `docs/evaluation/preflight/preflight_comparison.json`

---

## 5. Summary of V2.1 Framework Repairs

1. **Canonical Sidecar Loader (`app/evaluation/gold_sidecar.py`)**:
   - Implemented `load_gold_sidecar()` and `index_labels_by_case_id()`. Validates V2 schema `2.0.0`, requires `labels` array, rejects duplicate `evidence_item_id`s, verifies declared counters against array lengths, and fails closed on malformed files.

2. **Centralized Case Construction & Policy Engine (`app/evaluation/case_selection.py`)**:
   - Implemented `build_cases()` and `select_evaluation_cases()`. Fixed `all([]) == True` bug so cases with 0 required labels or unanswerable questions cannot pass `all-required-verified`. Added stable JSON array SHA-256 calculation.

3. **Offline Preflight CLI & Pre-Execution Validation (`run_retrieval_eval.py`)**:
   - Added `--preflight` engine and `--require-clean-git`. Validates sidecar counters, policy selection, and git dirty status BEFORE provider calls and BEFORE run directory creation. Exits non-zero when selected case count is 0.

4. **Multi-Window Anchor Audit V2 (`audit_golden_dataset.py`)**:
   - Added deterministic multi-window anchor matching hierarchy (beginning/middle/end token windows requiring at least 2 matching windows). Added unique `evidence_item_id = f"{case_id}_ev_{snip_idx:02d}"`. Generated `namsyntax_legal_qa_420_audit_summary_v2.json`.

5. **Answer Evaluator Signature Repair (`run_answer_eval.py`)**:
   - Corrected `generate_response()` invocation to real 3-argument signature `(original_query, rewritten_query, contexts)`. Formatted contexts preserving citation, title, source URL, and text. Input guardrail enforce rejection returns typed blocked online result with ZERO retrieval calls.

6. **Stage-Specific Retrieval Metrics (`app/evaluation/retrieval_metrics.py`)**:
   - Independent document stage metrics (Pinecone, FTS, merged, resolved) and chunk stage metrics (structural, local selection, reranker input/output, final evidence). Undefined metrics represented as `None` / JSON `null` with `reason: "k_exceeds_effective_stage_limit"`. Reports both macro case-level recall and micro evidence-item recall.

7. **Comprehensive Unit Test Suite (`tests/test_evaluation_framework.py`)**:
   - Expanded test suite covering all 25 specific defects.

---

## 6. Remaining Limitations & Readiness Verdict

- **Clean Live Retrieval Baseline**: `BLOCKED`
- **Reason**: The deterministic audit against the current 518,255-document corpus yielded 0 verified gold labels. Executing a live retrieval benchmark under `--verified-only` would score 0 cases and yield 0.0 coverage.
- **Next Steps Required Before Live Benchmark**: To establish a valid live retrieval benchmark, either expand local corpus document coverage or map ground truth citations to existing indexed document IDs in the SQLite content store.
