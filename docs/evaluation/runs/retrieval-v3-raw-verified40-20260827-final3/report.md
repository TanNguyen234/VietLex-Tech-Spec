# VIETLEX EVALUATION REPORT — retrieval-v3-raw-verified40-20260827-final3

**Run ID**: `retrieval-v3-raw-verified40-20260827-final3`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-08-27T11:05:33.576482+00:00`  
**Git Commit SHA**: `aa76cf855699d6fd98f94b73b84cc20fb3cf9112`  
**Source State SHA-256**: `677c88072c415ef95148498b422498bf915fe980a7ed9b8f1fdc7de7cddc24aa`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `3d96e19b37008fb06d813955ccd5a1645cefb96d40d61e4d3c2a0d636900e15a`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `d6e125030e8dda700667ba00f25162fac76472a9bfa2d087f54e2b5bc73a1fee`  
**Configuration Fingerprint**: `b6750f59135be3222c417f75df1e0ed383c707f359889ac910126c52858d4315`  
**Execution Command**: `run_retrieval_eval.py --verified-only --backend vertex-qdrant-v3 --ranking raw-rrf --profile separated_intent --rewrite off --reranker current --concurrency 1 --run-id retrieval-v3-raw-verified40-20260827-final3`  
**Evaluation Mode**: `retrieval-only` | **Judge**: `none` | **Guardrails**: `off`  

Metric schema: `3.0.0`
Scored / Total: `40 / 40`
Skipped cases: `0`
Skip reasons: `none`

## 1. Reliability and coverage

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons | Notes |
| :--- | ---: | ---: | :---: | :---: | :--- | :--- |
| Scored gold coverage | 100.0% | 100.0% | 40.0000/40.0000 | 40 / 0 | none | Cases with applicable verified required evidence |
| No-candidate rate | 0.0% | 0.0% | 0.0000/40.0000 | 40 / 0 | none | Completed retrievals with zero candidates |
| Retrieval technical-error rate | 0.0% | 0.0% | 0.0000/40.0000 | 40 / 0 | none | Status retrieval_error or partial_retrieval_error |
| Reranker technical-error rate | 0.0% | 0.0% | 0.0000/40.0000 | 40 / 0 | none | Exact status reranker_error |

## 2. Retrieval quality

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons |
| :--- | ---: | ---: | :---: | :---: | :--- |
| Document Recall @ 1 | 0.9500 | 0.9245 | 49.0000/53.0000 | 40 / 0 | none |
| Document Recall @ 3 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 0 | none |
| Document Recall @ 5 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 0 | none |
| Document Recall @ 10 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 0 | none |
| Document Recall @ 24 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 0 | none |
| Article Recall @ 1 | 0.8148 | 0.8000 | 24.0000/30.0000 | 27 / 13 | no_applicable_gold=13 |
| Article Recall @ 3 | 1.0000 | 1.0000 | 30.0000/30.0000 | 27 / 13 | no_applicable_gold=13 |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 40 | k_exceeds_configured_capacity=40 |
| Clause Recall @ 1 | 0.6538 | 0.6429 | 9.0000/14.0000 | 13 / 27 | no_applicable_gold=27 |
| Clause Recall @ 3 | 0.9231 | 0.9286 | 13.0000/14.0000 | 13 / 27 | no_applicable_gold=27 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 40 | k_exceeds_configured_capacity=40 |
| Article MRR | 0.9259 | 0.9259 | 25.0000/27.0000 | 27 / 13 | no_applicable_gold=13 |
| Clause MRR | 0.7949 | 0.7949 | 10.3333/13.0000 | 13 / 27 | no_applicable_gold=27 |
| Document MRR | 0.9750 | 0.9750 | 39.0000/40.0000 | 40 / 0 | none |
| nDCG @ 10 | 0.9218 | 0.9007 | 43.4165/48.2021 | 40 / 0 | none |
| Exact legal-reference hit | 1.0000 | 1.0000 | 40.0000/40.0000 | 40 / 0 | none |
| Multi-hop all-required coverage | 0.9750 | 0.9750 | 39.0000/40.0000 | 40 / 0 | none |
| Multi-hop partial coverage | 0.9875 | 0.9811 | 52.0000/53.0000 | 40 / 0 | none |

## 3. Stage metrics

| Pipeline stage | Capacity | Scored cases | Candidate p50 / p95 | Matched / Applicable documents | First-loss evidence count | Null reasons |
| :--- | ---: | ---: | :---: | :---: | ---: | :--- |
| `pinecone_document_metrics` | N/A | 40 | 0.0000 / 0.0000 | 0 / 53 | 0 | configured_capacity_unknown=200, stage_does_not_expose_structural_locators=320 |
| `fts_document_metrics` | N/A | 40 | 0.0000 / 0.0000 | 0 / 53 | 0 | configured_capacity_unknown=200, stage_does_not_expose_structural_locators=320 |
| `source_retrieval_metrics` | 24 | 40 | 24.0000 / 24.0000 | 53 / 53 | 0 | stage_does_not_expose_structural_locators=320 |
| `merged_document_metrics` | 24 | 40 | 0.0000 / 0.0000 | 0 / 53 | 53 | stage_does_not_expose_structural_locators=320 |
| `resolved_document_metrics` | 24 | 40 | 0.0000 / 0.0000 | 0 / 53 | 0 | stage_does_not_expose_structural_locators=320 |
| `structural_chunk_metrics` | 24 | 40 | 24.0000 / 24.0000 | 53 / 53 | 0 | no_applicable_gold=160 |
| `local_selection_metrics` | N/A | 40 | 0.0000 / 0.0000 | 0 / 53 | 0 | configured_capacity_unknown=440, no_applicable_gold=40 |
| `reranker_input_metrics` | 24 | 40 | 24.0000 / 24.0000 | 53 / 53 | 0 | no_applicable_gold=160 |
| `reranker_output_metrics` | 3 | 40 | 3.0000 / 3.0000 | 53 / 53 | 0 | k_exceeds_configured_capacity=200, no_applicable_gold=120 |
| `final_evidence_metrics` | 3 | 40 | 3.0000 / 3.0000 | 53 / 53 | 0 | k_exceeds_configured_capacity=200, no_applicable_gold=120 |

## 4. Interpretation notes

- Recall@K is undefined when K exceeds the configured stage capacity; nDCG@10 still treats unreturned ranks as zero gain so capacity effects remain measurable.
- Configured provider candidates are provenance only; they do not prove which provider answered a request.

## 6. Generation, guardrail, and judge coverage

Generation STOP / total: `0 / 40`
Input safe / total: `0 / 40`
Output safe / total: `0 / 40`
Ragas scored / eligible: `0 / 40`
Judge technical errors: `0`

| Ragas metric | Mean | Scored cases |
| :--- | ---: | ---: |
| `faithfulness` | N/A | 0 |
| `answer_accuracy` | N/A | 0 |
| `context_precision` | N/A | 0 |
| `context_recall` | N/A | 0 |

## 7. Latency

| Stage | P50 (s) | P95 (s) | Mean (s) |
| :--- | ---: | ---: | ---: |
| `t_retrieval` | 2.8561 | 4.1698 | 3.3397 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 2.8563 | 4.1699 | 3.3398 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_017` | `ok` | `N/A` | `no` | `none` | 23.5867 |
| `case_019` | `ok` | `N/A` | `no` | `none` | 2.0260 |
| `case_021` | `ok` | `N/A` | `no` | `none` | 3.2413 |
| `case_031` | `ok` | `N/A` | `no` | `none` | 2.8395 |
| `case_036` | `ok` | `N/A` | `no` | `none` | 1.8827 |
| `case_039` | `ok` | `N/A` | `no` | `none` | 3.0307 |
| `case_043` | `ok` | `N/A` | `no` | `none` | 2.9884 |
| `case_061` | `ok` | `N/A` | `no` | `none` | 2.8532 |
| `case_065` | `ok` | `N/A` | `no` | `none` | 1.5639 |
| `case_075` | `ok` | `N/A` | `no` | `none` | 4.1448 |
| `case_101` | `ok` | `N/A` | `no` | `none` | 2.5996 |
| `case_121` | `ok` | `N/A` | `no` | `none` | 2.3932 |
| `case_127` | `ok` | `N/A` | `no` | `none` | 3.2589 |
| `case_133` | `ok` | `N/A` | `no` | `none` | 3.4184 |
| `case_135` | `ok` | `N/A` | `no` | `none` | 4.6469 |
| `case_165` | `ok` | `N/A` | `no` | `none` | 2.4784 |
| `case_171` | `ok` | `N/A` | `no` | `none` | 3.3805 |
| `case_177` | `ok` | `N/A` | `no` | `none` | 2.0065 |
| `case_187` | `ok` | `N/A` | `no` | `none` | 2.7752 |
| `case_204` | `ok` | `N/A` | `no` | `none` | 2.5430 |
| `case_227` | `ok` | `N/A` | `no` | `none` | 1.2447 |
| `case_243` | `ok` | `N/A` | `no` | `none` | 3.2339 |
| `case_253` | `ok` | `N/A` | `no` | `none` | 3.4932 |
| `case_257` | `ok` | `N/A` | `no` | `none` | 1.3389 |
| `case_261` | `ok` | `N/A` | `no` | `none` | 2.9409 |
| `case_263` | `ok` | `N/A` | `no` | `none` | 2.5270 |
| `case_285` | `ok` | `N/A` | `no` | `none` | 1.8486 |
| `case_309` | `ok` | `N/A` | `no` | `none` | 3.0728 |
| `case_323` | `ok` | `N/A` | `no` | `none` | 2.4449 |
| `case_329` | `ok` | `N/A` | `no` | `none` | 2.5604 |
| `case_331` | `ok` | `N/A` | `no` | `none` | 2.8593 |
| `case_339` | `ok` | `N/A` | `no` | `none` | 3.2847 |
| `case_355` | `ok` | `N/A` | `no` | `none` | 3.2916 |
| `case_361` | `ok` | `N/A` | `no` | `none` | 3.6194 |
| `case_371` | `ok` | `N/A` | `no` | `none` | 2.7829 |
| `case_374` | `ok` | `N/A` | `no` | `none` | 2.8107 |
| `case_375` | `ok` | `N/A` | `no` | `none` | 3.4130 |
| `case_379` | `ok` | `N/A` | `no` | `none` | 3.6349 |
| `case_397` | `ok` | `N/A` | `no` | `none` | 3.0167 |
| `case_411` | `ok` | `N/A` | `no` | `none` | 2.5156 |