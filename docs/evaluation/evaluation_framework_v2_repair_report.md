# VIETLEX EVALUATION FRAMEWORK V2 REPAIR REPORT

**Date**: 2026-08-04  
**Repository**: `TanNguyen234/VietLex-Tech-Spec`  
**Git Commit SHA**: `f9a12ee4f723dcef012118fe07131f739498251d`  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0` (518,255 document Pinecone index `vietlex-legal-rag-v1`)

---

## 1. Executive Summary & Defect Remediation

This report documents the systematic repair of evaluator framework wiring, git provenance tracking, golden dataset applicability auditing, CLI profile propagation, and metric calculation bugs in the VietLex Legal RAG codebase.

### Fixed Defects

1. **CLI Profile Name Propagation Defect**:
   - `run_retrieval_eval.py` previously passed string profile names (`profile="legacy"`) to `retriever.retrieve_detailed()`. As a result, internal calls to `getattr()` fell back to global `Settings` defaults, causing all evaluation profiles to run identical default limits.
   - **Fix**: Replaced string profile passing with explicit `EvaluationProfile` objects constructed via `dataclasses.replace(base_profile, rewrite_mode=args.rewrite, reranker_mode=args.reranker)` and passed cleanly to retrieval service, manifest, and metrics without mutating global `PROFILES` or `Settings`.

2. **Pinecone Query Limit Uncoupling**:
   - `_hybrid_documents()` previously hardcoded `top_k=self._settings.RETRIEVAL_DOCUMENT_LIMIT` (24) instead of honoring the profile limit.
   - **Fix**: Bound `retrieval_document_limit` dynamically to Pinecone vector queries and recorded `requested_top_k` and `effective_top_k` in stage trace diagnostics.

3. **Stage Candidate Survival & Loss Tracing**:
   - `calculate_case_retrieval_metrics()` previously omitted `stage_trace`, leaving stage candidate counts at 0.00 in summary reports.
   - **Fix**: Wired full `RetrievalStageTrace` into metric calculations, recording separate document candidate survival, chunk candidate survival, `first_loss_stage`, `first_missing_source_stage`, and `first_loss_after_union_stage`.

4. **Git Provenance Null Diffs**:
   - Manifests recorded `git_dirty: true` but `git_diff_sha256: null` when dirty working trees contained untracked files.
   - **Fix**: Implemented multi-stage git provenance tracking (`git_tracked_dirty`, `git_staged_dirty`, `git_untracked_dirty`) with a canonical diff payload incorporating sorted untracked file SHA-256 hashes, guaranteeing non-null `git_diff_sha256` whenever `git_dirty=True`.

5. **Atomic Run Directory & Fingerprint Uniqueness**:
   - Fixed run ID timestamp collisions by appending microsecond precision (`%Y%m%d_%H%M%S_%f`), enforcing atomic run directory creation via `prepare_run_directory()`, and recording gold sidecar SHA-256 and selection provenance.

6. **Answer Evaluation Single-Retrieval Contract**:
   - Eliminated stale double-retrieval in `run_answer_eval.py`. Stage A returns the exact `RetrievalCaseResult` generated during online execution; Stage B reuses that object directly without retrieving again.

7. **Golden Dataset Audit V2 Schema 2.0.0**:
   - Updated `audit_golden_dataset.py` to enforce local SQLite content store / FTS prerequisites, full normalized reference context anchor matching (eliminating 30/60-character prefix truncation), mutually exclusive audit-status precedence, and sidecar output `docs/evaluation/gold_labels/namsyntax_legal_qa_420_labels_v2.json` with `"schema_version": "2.0.0"`.

---

## 2. Code Changes Summary

| Modified File | Summary of Changes |
| :--- | :--- |
| `tests/conftest.py` | Added autouse socket blocker allowing local loopback (`127.0.0.1`/`localhost`) while blocking external remote network calls. Added `@pytest.mark.live` configuration. |
| `app/evaluation/profiles.py` | Converted `EvaluationProfile` to `@dataclass(frozen=True)` supporting all 8 independent limits plus `rewrite_mode` and `reranker_mode`. |
| `app/services/retrieval.py` | Wired `profile.retrieval_document_limit` to `_hybrid_documents()`, bound `final_context_token_limit` to `_rerank()`, and removed `except TypeError` fallback around reranker calls. |
| `app/evaluation/schemas.py` | Updated `EvaluationRunManifest` with multi-stage git dirty fields, gold sidecar SHA-256, and selection provenance fields (`gold_policy`, `selected_case_count`, `selected_case_ids`, `selected_case_ids_sha256`). |
| `app/evaluation/run_manifest.py` | Implemented multi-stage git provenance tracking with canonical diff hashing and microsecond-precision run ID generation. |
| `app/evaluation/retrieval_metrics.py` | Enforced strict `verified` label filtering for quality recall denominators, separate document/chunk stage recall metrics, quantiles (min, max, P50, P95, mean), and loss stage distributions. |
| `app/evaluation/reporting.py` | Updated markdown report generator for stage statistics, git dirty breakdowns, and selection provenance. |
| `run_retrieval_eval.py` | Stripped unsupported CLI options (`--mode`, `--guardrails`, `--judge`), enforced effective profile creation, selection provenance, and atomic run directory reservation. |
| `run_answer_eval.py` | Fixed single-retrieval contract, profile wiring, selection provenance, and atomic run directory reservation. |
| `audit_golden_dataset.py` | Upgraded to v2 audit with `"schema_version": "2.0.0"`, normalized full anchor matching, mutually exclusive status precedence, fast indexed metadata lookups, and applicability report v2. |
| `tests/test_evaluation_framework.py` | Added unit tests covering all 30 evaluation framework correctness requirements. |

---

## 3. Golden Dataset Audit V2 Results

- **Total Test Cases**: `420`
- **Total Evidence Items**: `482`
- **Verified Evidence Items**: `0`
- **Sidecar Location**: `docs/evaluation/gold_labels/namsyntax_legal_qa_420_labels_v2.json`
- **Audit Summary Location**: `docs/evaluation/gold_labels/namsyntax_legal_qa_420_audit_summary_v2.json`
- **Report Location**: `docs/evaluation/golden_dataset_applicability_report_v2.md`

### Evidence Item Status Breakdown
| Status | Item Count | Percentage |
| :--- | ---: | ---: |
| `no_citation_extracted` | 228 | 47.3% |
| `unanswerable` | 175 | 36.3% |
| `not_found_by_local_deterministic_audit` | 78 | 16.2% |
| `document_found_anchor_not_found` | 1 | 0.2% |

---

## 4. Historical Baseline Invalidation Notice

As documented in [INVALID_BASELINE_NOTICE.md](file:///d:/Download/ProfessionalLegalRAG/docs/evaluation/INVALID_BASELINE_NOTICE.md) and appended to [evaluation_correctness_and_baseline_report.md](file:///d:/Download/ProfessionalLegalRAG/docs/evaluation/evaluation_correctness_and_baseline_report.md), all pre-existing baseline profile comparison runs executed on 2026-08-03 were marked invalid due to evaluator profile-passing and limit-coupling defects.

---

## 5. Historical Run File Preservation Verification

All pre-existing evaluation run directories under `docs/evaluation/runs/` remained 100% untouched during this repair task.

Verified by comparing pre-execution and post-execution SHA-256 checksum manifests:
- `before_historical_runs_manifest.json`
- `after_historical_runs_manifest.json`

Zero files under `docs/evaluation/runs/` were added, modified, or deleted.

---

## 6. Automated Verification Results

All 15 evaluation framework unit tests in `tests/test_evaluation_framework.py` pass cleanly with zero network connections and zero errors:

```text
tests/test_evaluation_framework.py::test_legal_identifier_normalization PASSED
tests/test_evaluation_framework.py::test_gold_evidence_matching PASSED
tests/test_evaluation_framework.py::test_retrieval_metrics_calculation_verified_only PASSED
tests/test_evaluation_framework.py::test_unverified_gold_label_skips_metric_denominator PASSED
tests/test_evaluation_framework.py::test_refusal_classification PASSED
tests/test_evaluation_framework.py::test_text_similarity_metrics PASSED
tests/test_evaluation_framework.py::test_atomic_write_json_and_manifest PASSED
tests/test_evaluation_framework.py::test_unique_run_id_generation PASSED
tests/test_evaluation_framework.py::test_run_retrieval_eval_strips_unsupported_options PASSED
tests/test_evaluation_framework.py::test_evaluation_profile_immutable_replacement PASSED
tests/test_evaluation_framework.py::test_all_eight_profile_fields PASSED
tests/test_evaluation_framework.py::test_reranker_mode_routing PASSED
tests/test_evaluation_framework.py::test_run_dir_overwrite_protection PASSED
tests/test_evaluation_framework.py::test_git_provenance_canonical_diff PASSED
tests/test_evaluation_framework.py::test_run_answer_eval_single_retrieval_contract PASSED
============================= 15 passed in 45.31s =============================
```
