# VIETLEX EVALUATION FRAMEWORK V2.1.1 ARTIFACT CONSISTENCY & SEMANTICS REPORT

**Date**: 2026-08-04  
**Repository**: `TanNguyen234/VietLex-Tech-Spec`  
**Starting HEAD**: `d70deeb38568f41346ee1168989d5c94288e9f96`  
**Clean Live Retrieval Baseline Status**: `BLOCKED` (Selected verified case count is 0)  
**Git Commit / Push Status**: `PASS` (No git commit or git push executed)  

---

## 1. System Status & Verification Summary

| Check Item | Status | Description |
| :--- | :---: | :--- |
| **Offline Test Suite Execution** | `PASS` | `python -m pytest -q` passed cleanly (136 passed, 1 skipped in 38.73s) |
| **Provider / Network Isolation** | `PASS` | Provider call count = 0 (No Pinecone, Qdrant, or LLM network calls) |
| **Current File-Byte SHA Consistency** | `PASS` | Dataset and sidecar SHAs in preflight artifacts match current file bytes 100% |
| **Canonical Preflight Filename Structure** | `PASS` | Filenames record profile, config fp8, sidecar sha8, and code_state sha8 |
| **Preflight Comparison Artifact** | `PASS` | Immutable `preflight_comparison_8019f9b3_c6d0b090.json` generated |
| **Gold Evidence Schema & Loader Validation** | `PASS` | Mandatory non-empty evidence IDs, status enum, required boolean, and exact case-set equality |
| **Audit Verification Hierarchy** | `PASS` | Explicit 4-level identity resolution & complete metadata uniqueness checks |
| **Level-Specific Verification Matching** | `PASS` | Verified status assigned only when document, article, and clause match complete required level |
| **Configured Stage Capacity Semantics** | `PASS` | Null metrics governed strictly by configured stage capacity (not observed candidate count) |
| **Historical Run Artifact Preservation** | `PASS` | Pre-existing run artifact checksums remain 100% identical |
| **Clean Live Retrieval Benchmark** | `BLOCKED` | Selected case count is 0 under verified gold policy |
| **Generation & Guardrails Execution** | `NOT RUN` | Live answer generation and LLM judge calls disabled per prompt |
| **Corpus / Index Mutation** | `NOT RUN` | No embedding migration, FTS rebuild, or vector collection mutation |
| **Git Push / Commit Execution** | `STATIC ONLY` | Working tree modified for inspection; 0 commits or pushes executed |

---

## 2. Environment & Provenance Identifiers

- **Starting Git HEAD**: `d70deeb38568f41346ee1168989d5c94288e9f96`
- **Ending Git Dirty Status**: `git_dirty = True`
- **Current Dataset SHA-256**: `84c93a522c1bc8eac7179aa808f70b59466fe9a55a4a9f98ddae07797c9662c7` (`app/data/namsyntax_legal_qa_420.json`)
- **Current Sidecar SHA-256**: `8019f9b3e5370130663dc5fe28d051f5a0ed2ec191bcf9d9e422efcefbdad0c8` (`docs/evaluation/gold_labels/namsyntax_legal_qa_420_labels_v2.json`)
- **Gold Sidecar V2 Schema Version**: `2.0.0`
- **Audit Summary JSON**: `docs/evaluation/gold_labels/namsyntax_legal_qa_420_audit_summary_v2.json`

---

## 3. Reconciled Audit Counters & Verification Breakdown

Generated from deterministic audit run (`python audit_golden_dataset.py`):

- **Total Test Cases**: `420`
- **Exact Total Evidence Items**: `482`
- **Exact Verified Evidence Items**: `0`
- **Verified Document Level Count**: `0`
- **Verified Article Level Count**: `0`
- **Verified Clause Level Count**: `0`
- **Unanswerable Cases**: `175`

### Evidence Item Status Breakdown
| Primary Status | Item Count | Percentage | Description |
| :--- | ---: | ---: | :--- |
| `no_citation_extracted` | 306 | 63.5% | Citation text present but document/article anchor missing in corpus |
| `unanswerable` | 175 | 36.3% | Explicit unanswerable ground-truth case |
| `not_found_by_local_deterministic_audit` | 1 | 0.2% | Document hint not resolved in local 518k corpus |
| **Total** | **482** | **100.0%** | **Reconciled Total Evidence Items** |

---

## 4. Immutable Preflight Artifacts & Provenance Proof

Executed via `run_retrieval_eval.py --preflight --verified-only --gold-policy all-required-verified --rewrite off --reranker current`:

| Profile Name | Config FP8 | Sidecar SHA8 | Code State SHA8 | Canonical Immutable Preflight Artifact | Provider Calls | Preflight Result |
| :--- | :---: | :---: | :---: | :--- | :---: | :---: |
| `legacy` | `84654a25` | `8019f9b3` | `01664121` | `docs/evaluation/preflight/preflight_legacy_84654a25_8019f9b3_01664121.json` | 0 | `BLOCKED` (Exit 1) |
| `separated_no_intent` | `3d70b0f4` | `8019f9b3` | `2dff4e18` | `docs/evaluation/preflight/preflight_separated_no_intent_3d70b0f4_8019f9b3_2dff4e18.json` | 0 | `BLOCKED` (Exit 1) |
| `separated_intent` | `368305af` | `8019f9b3` | `c6d0b090` | `docs/evaluation/preflight/preflight_separated_intent_368305af_8019f9b3_c6d0b090.json` | 0 | `BLOCKED` (Exit 1) |

### Comparison Artifact
- **Canonical Immutable Comparison Artifact**: `docs/evaluation/preflight/preflight_comparison_8019f9b3_c6d0b090.json`
- **Selected Case IDs SHA-256**: `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` (`[]`, case count `0`) across all 3 profiles.

---

## 5. Key V2.1.1 Repairs & Improvements

1. **Dirty Code State Fingerprinting & Artifact Naming**:
   - Formatted preflight artifacts as `preflight_<profile>_<config_fp8>_<sidecar_sha8>_<code_state_sha8>.json`. `code_state_fingerprint` uniquely identifies git commit SHA, dirty status, and git diff SHA256.

2. **Mandatory GoldEvidence Fields & Strict Validation**:
   - Enforced non-empty `evidence_item_id`, `case_id`, `status` (Enum validated), and `required` boolean in `load_gold_sidecar()`. Rejects missing fields without fallback mutation. Validates exact dataset-sidecar case-set equality (`set(sidecar_case_ids) == set(dataset_case_ids)`).

3. **Explicit Identity & Level-Specific Verification Hierarchy**:
   - Resolved document identity in strict order: exact doc ID -> exact URL -> exact metadata document number -> lexical discovery fallback.
   - Verified status (`status="verified"`) assigned only when complete required evidence level (`document`, `article`, `clause`) is proven. Detail unresolved statuses record exact failure modes (`document_verified_article_unresolved`, `article_verified_clause_unresolved`, `structural_anchor_not_found`).

4. **Configured Stage Capacity Semantics & Denominators**:
   - Metric null representation (`None`) is strictly governed by `RetrievalStageCapacities`, not observed candidate counts. If configured capacity = 24 and observed candidates = 2, `Recall@3` returns a valid numeric float.
   - Denominators are filtered strictly by required evidence level (`verified_doc_gold_count`, `verified_article_gold_count`, `verified_clause_gold_count`).

---

## 6. Readiness Verdict & Confirmation

- **Live Retrieval Benchmark Status**: `BLOCKED`
- **Reason**: The ground truth audit against the 518,255-document corpus yielded 0 verified evidence items under strict multi-window verification. Under `--verified-only`, 0 cases are selected. Preflight correctly blocks live evaluation without fabricating fake labels.
- **Git Commit / Push Confirmation**: `PASS` (0 commits or pushes executed).
