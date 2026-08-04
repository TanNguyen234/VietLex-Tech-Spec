# NOTICE: INVALIDATION OF HISTORICAL RETRIEVAL BASELINE PROFILE COMPARISON

**Date of Invalidation**: 2026-08-04  
**Superseded Runs**:
- `docs/evaluation/runs/retrieval_20260803_134331_839401_00000000` (`legacy`)
- `docs/evaluation/runs/retrieval_20260803_134556_206053_00000000` (`separated_no_intent`)
- `docs/evaluation/runs/retrieval_20260803_134826_737977_00000000` (`separated_intent`)

---

## 1. Reason for Invalidation

The profile comparison committed on 2026-08-03 across `legacy`, `separated_no_intent`, and `separated_intent` profiles is technically invalid and **unsuitable for retrieval optimization or architectural decisions**.

Detailed audit of the evaluation framework revealed 8 confirmed defects:

1. **Profile Limit Ignorance**: `run_retrieval_eval.py` passed string profile names (`profile="legacy"`) instead of `EvaluationProfile` objects to `retriever.retrieve_detailed()`. As a result, all internal `getattr()` calls fell back to global `Settings` defaults, making every profile execute identical retrieval limits (`top_k=24`, `resolved_docs=16`, `rerank_input=24`).
2. **Pinecone Top-K Unbound**: `_hybrid_documents()` hardcoded `top_k=self._settings.RETRIEVAL_DOCUMENT_LIMIT` (24) directly instead of consuming the profile's `retrieval_document_limit`.
3. **Stage Trace Omission**: `calculate_case_retrieval_metrics()` was invoked without `stage_trace`, preventing calculation of stage-specific candidate recall and loss metrics.
4. **Identical Configuration Fingerprints**: All 3 run manifests recorded `profile_name: custom`, identical configuration dictionaries, and dummy run IDs ending with `00000000`.
5. **Git Provenance Null Diffs**: Manifests generated from dirty working trees recorded `git_dirty: true` but `git_diff_sha256: null` because untracked files were not incorporated into diff hashing.
6. **Sidecar SHA Absence**: Manifests failed to record `gold_label_sidecar_sha256`.
7. **Flawed Candidate Count Reporting**: Summary reports recorded active rate 100% with average candidates 0.00 due to string-replacement key derivation errors.
8. **Unverified Label Contamination**: Metric calculation allowed ambiguous and missing gold labels into quality recall denominators instead of filtering strictly to `status == "verified"`.

---

## 2. Unproven Hypotheses

Because all 3 profiles executed identical global default limits, claims comparing latency or recall differences across profiles in the 2026-08-03 report were invalid. Furthermore, the following failure causes mentioned in the previous report remain **unproven hypotheses** until a clean benchmark is executed post-repair:

- E5 query embedding prefix mismatch as the primary failure cause;
- SQLite FTS title-only indexing as the dominant bottleneck;
- Reranker candidate input truncation as the dominant bottleneck.

---

## 3. Mandatory Remediation Action

Future retrieval benchmarks MUST be executed only after:
1. Repaired evaluation framework code has been committed;
2. Working tree is clean (`git status` clean);
3. Clean benchmarks are executed using `run_retrieval_eval.py` with immutable `effective_profile` objects and atomic manifest directory reservation (`prepare_run_directory`).
