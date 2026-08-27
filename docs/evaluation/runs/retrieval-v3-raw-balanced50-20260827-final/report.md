# VIETLEX EVALUATION REPORT — retrieval-v3-raw-balanced50-20260827-final

**Run ID**: `retrieval-v3-raw-balanced50-20260827-final`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-08-27T11:34:14.561209+00:00`  
**Git Commit SHA**: `aa76cf855699d6fd98f94b73b84cc20fb3cf9112`  
**Source State SHA-256**: `b84fa91717df8165f4670b52ed482c58fc2c1a1907d6a2af4e945a883272ae94`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `17c2adb75c72eb7088976564cbcb207d7ce98509b375560c9b67204634c90b00`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `d6e125030e8dda700667ba00f25162fac76472a9bfa2d087f54e2b5bc73a1fee`  
**Configuration Fingerprint**: `566bc5db4089dfe5a6e7ed714afbe5e931d6cccacb45fb7e06586d7bcc657500`  
**Execution Command**: `run_retrieval_eval.py --backend vertex-qdrant-v3 --ranking raw-rrf --profile separated_intent --rewrite off --reranker current --concurrency 1 --gold-policy none --case-ids case_017 case_019 case_021 case_031 case_036 case_039 case_043 case_061 case_065 case_069 case_075 case_101 case_105 case_115 case_116 case_121 case_127 case_133 case_135 case_165 case_171 case_177 case_183 case_187 case_194 case_204 case_227 case_243 case_253 case_257 case_261 case_263 case_285 case_309 case_323 case_325 case_329 case_331 case_339 case_355 case_361 case_362 case_371 case_374 case_375 case_379 case_397 case_411 case_415 case_417 --run-id retrieval-v3-raw-balanced50-20260827-final`  
**Evaluation Mode**: `retrieval-only` | **Judge**: `none` | **Guardrails**: `off`  

Metric schema: `3.0.0`
Scored / Total: `40 / 50`
Skipped cases: `10`
Skip reasons: `no_verified_gold_label=10`

## 1. Reliability and coverage

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons | Notes |
| :--- | ---: | ---: | :---: | :---: | :--- | :--- |
| Scored gold coverage | 80.0% | 80.0% | 40.0000/50.0000 | 50 / 0 | no_verified_gold_label=10 | Cases with applicable verified required evidence |
| No-candidate rate | 0.0% | 0.0% | 0.0000/50.0000 | 50 / 0 | none | Completed retrievals with zero candidates |
| Retrieval technical-error rate | 0.0% | 0.0% | 0.0000/50.0000 | 50 / 0 | none | Status retrieval_error or partial_retrieval_error |
| Reranker technical-error rate | 0.0% | 0.0% | 0.0000/50.0000 | 50 / 0 | none | Exact status reranker_error |

## 2. Retrieval quality

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons |
| :--- | ---: | ---: | :---: | :---: | :--- |
| Document Recall @ 1 | 0.9500 | 0.9434 | 50.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 3 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 5 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 10 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 24 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Article Recall @ 1 | 0.8148 | 0.8000 | 24.0000/30.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Article Recall @ 3 | 1.0000 | 1.0000 | 30.0000/30.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 50 | k_exceeds_configured_capacity=40, no_verified_gold_label=10 |
| Clause Recall @ 1 | 0.6538 | 0.6429 | 9.0000/14.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Clause Recall @ 3 | 0.9231 | 0.9286 | 13.0000/14.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 50 | k_exceeds_configured_capacity=40, no_verified_gold_label=10 |
| Article MRR | 0.9259 | 0.9259 | 25.0000/27.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Clause MRR | 0.7949 | 0.7949 | 10.3333/13.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Document MRR | 0.9750 | 0.9750 | 39.0000/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| nDCG @ 10 | 0.9182 | 0.9007 | 43.4165/48.2021 | 40 / 10 | no_verified_gold_label=10 |
| Exact legal-reference hit | 1.0000 | 1.0000 | 40.0000/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| Multi-hop all-required coverage | 0.9750 | 0.9750 | 39.0000/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| Multi-hop partial coverage | 0.9875 | 0.9811 | 52.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |

## 3. Stage metrics

| Pipeline stage | Capacity | Scored cases | Candidate p50 / p95 | Matched / Applicable documents | First-loss evidence count | Null reasons |
| :--- | ---: | ---: | :---: | :---: | ---: | :--- |
| `pinecone_document_metrics` | N/A | 40 | 0.0000 / 0.0000 | 0 / 53 | 0 | configured_capacity_unknown=200, no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `fts_document_metrics` | N/A | 40 | 0.0000 / 0.0000 | 0 / 53 | 0 | configured_capacity_unknown=200, no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `source_retrieval_metrics` | 24 | 40 | 24.0000 / 24.0000 | 53 / 53 | 0 | no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `merged_document_metrics` | 24 | 40 | 0.0000 / 0.0000 | 0 / 53 | 53 | no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `resolved_document_metrics` | 24 | 40 | 0.0000 / 0.0000 | 0 / 53 | 0 | no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `structural_chunk_metrics` | 24 | 40 | 24.0000 / 24.0000 | 53 / 53 | 0 | no_applicable_gold=160, no_verified_gold_label=140 |
| `local_selection_metrics` | N/A | 40 | 0.0000 / 0.0000 | 0 / 53 | 0 | configured_capacity_unknown=440, no_applicable_gold=40, no_verified_gold_label=140 |
| `reranker_input_metrics` | 24 | 40 | 24.0000 / 24.0000 | 53 / 53 | 0 | no_applicable_gold=160, no_verified_gold_label=140 |
| `reranker_output_metrics` | 3 | 40 | 3.0000 / 3.0000 | 53 / 53 | 0 | k_exceeds_configured_capacity=200, no_applicable_gold=120, no_verified_gold_label=140 |
| `final_evidence_metrics` | 3 | 40 | 3.0000 / 3.0000 | 53 / 53 | 0 | k_exceeds_configured_capacity=200, no_applicable_gold=120, no_verified_gold_label=140 |

## 4. Interpretation notes

- Recall@K is undefined when K exceeds the configured stage capacity; nDCG@10 still treats unreturned ranks as zero gain so capacity effects remain measurable.
- Configured provider candidates are provenance only; they do not prove which provider answered a request.

## 6. Generation, guardrail, and judge coverage

Generation STOP / total: `0 / 50`
Input safe / total: `0 / 50`
Output safe / total: `0 / 50`
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
| `t_retrieval` | 3.2525 | 4.6265 | 3.5423 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 3.2525 | 4.6266 | 3.5423 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_017` | `ok` | `N/A` | `no` | `none` | 25.5363 |
| `case_019` | `ok` | `N/A` | `no` | `none` | 1.7454 |
| `case_021` | `ok` | `N/A` | `no` | `none` | 2.8534 |
| `case_031` | `ok` | `N/A` | `no` | `none` | 2.6834 |
| `case_036` | `ok` | `N/A` | `no` | `none` | 2.8118 |
| `case_039` | `ok` | `N/A` | `no` | `none` | 6.1286 |
| `case_043` | `ok` | `N/A` | `no` | `none` | 3.3752 |
| `case_061` | `ok` | `N/A` | `no` | `none` | 3.2665 |
| `case_065` | `ok` | `N/A` | `no` | `none` | 1.8411 |
| `case_069` | `ok` | `N/A` | `no` | `none` | 4.1920 |
| `case_075` | `ok` | `N/A` | `no` | `none` | 4.0957 |
| `case_101` | `ok` | `N/A` | `no` | `none` | 3.6269 |
| `case_105` | `ok` | `N/A` | `no` | `none` | 3.5112 |
| `case_115` | `ok` | `N/A` | `no` | `none` | 2.7644 |
| `case_116` | `ok` | `N/A` | `no` | `none` | 2.5464 |
| `case_121` | `ok` | `N/A` | `no` | `none` | 3.2827 |
| `case_127` | `ok` | `N/A` | `no` | `none` | 4.2840 |
| `case_133` | `ok` | `N/A` | `no` | `none` | 1.5370 |
| `case_135` | `ok` | `N/A` | `no` | `none` | 4.3977 |
| `case_165` | `ok` | `N/A` | `no` | `none` | 3.1740 |
| `case_171` | `ok` | `N/A` | `no` | `none` | 3.3030 |
| `case_177` | `ok` | `N/A` | `no` | `none` | 4.0216 |
| `case_183` | `ok` | `N/A` | `no` | `none` | 3.9192 |
| `case_187` | `ok` | `N/A` | `no` | `none` | 4.0432 |
| `case_194` | `ok` | `N/A` | `no` | `none` | 1.7691 |
| `case_204` | `ok` | `N/A` | `no` | `none` | 3.0681 |
| `case_227` | `ok` | `N/A` | `no` | `none` | 2.8577 |
| `case_243` | `ok` | `N/A` | `no` | `none` | 3.3771 |
| `case_253` | `ok` | `N/A` | `no` | `none` | 1.8645 |
| `case_257` | `ok` | `N/A` | `no` | `none` | 4.2545 |
| `case_261` | `ok` | `N/A` | `no` | `none` | 1.9354 |
| `case_263` | `ok` | `N/A` | `no` | `none` | 3.3677 |
| `case_285` | `ok` | `N/A` | `no` | `none` | 4.8138 |
| `case_309` | `ok` | `N/A` | `no` | `none` | 1.4396 |
| `case_323` | `ok` | `N/A` | `no` | `none` | 3.2585 |
| `case_325` | `ok` | `N/A` | `no` | `none` | 2.5470 |
| `case_329` | `ok` | `N/A` | `no` | `none` | 3.3726 |
| `case_331` | `ok` | `N/A` | `no` | `none` | 1.2926 |
| `case_339` | `ok` | `N/A` | `no` | `none` | 1.5775 |
| `case_355` | `ok` | `N/A` | `no` | `none` | 3.1577 |
| `case_361` | `ok` | `N/A` | `no` | `none` | 2.6225 |
| `case_362` | `ok` | `N/A` | `no` | `none` | 3.2465 |
| `case_371` | `ok` | `N/A` | `no` | `none` | 2.8038 |
| `case_374` | `ok` | `N/A` | `no` | `none` | 1.5376 |
| `case_375` | `ok` | `N/A` | `no` | `none` | 3.3684 |
| `case_379` | `ok` | `N/A` | `no` | `none` | 3.5752 |
| `case_397` | `ok` | `N/A` | `no` | `none` | 2.8920 |
| `case_411` | `ok` | `N/A` | `no` | `none` | 3.5554 |
| `case_415` | `ok` | `N/A` | `no` | `none` | 3.4771 |
| `case_417` | `ok` | `N/A` | `no` | `none` | 3.1438 |