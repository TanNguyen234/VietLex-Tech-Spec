# VIETLEX EVALUATION REPORT — retrieval-v3-raw-verified40-20260827-final5

**Run ID**: `retrieval-v3-raw-verified40-20260827-final5`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-08-27T11:26:52.415739+00:00`  
**Git Commit SHA**: `aa76cf855699d6fd98f94b73b84cc20fb3cf9112`  
**Source State SHA-256**: `b84fa91717df8165f4670b52ed482c58fc2c1a1907d6a2af4e945a883272ae94`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `e52515ea1c3cd9742fdf08549e7e8e9e00667427643929c345025b2497c428f0`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `d6e125030e8dda700667ba00f25162fac76472a9bfa2d087f54e2b5bc73a1fee`  
**Configuration Fingerprint**: `0cb40e49d7719b5d66e810c3b54b6ae8efbe2f91b3d08e4c703fae92d3e7f7c1`  
**Execution Command**: `run_retrieval_eval.py --verified-only --backend vertex-qdrant-v3 --ranking raw-rrf --profile separated_intent --rewrite off --reranker current --concurrency 1 --run-id retrieval-v3-raw-verified40-20260827-final5`  
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
| Document Recall @ 1 | 0.9500 | 0.9434 | 50.0000/53.0000 | 40 / 0 | none |
| Document Recall @ 3 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 0 | none |
| Document Recall @ 5 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 0 | none |
| Document Recall @ 10 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 0 | none |
| Document Recall @ 24 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 0 | none |
| Article Recall @ 1 | 0.8519 | 0.8333 | 25.0000/30.0000 | 27 / 13 | no_applicable_gold=13 |
| Article Recall @ 3 | 1.0000 | 1.0000 | 30.0000/30.0000 | 27 / 13 | no_applicable_gold=13 |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 40 | k_exceeds_configured_capacity=40 |
| Clause Recall @ 1 | 0.6538 | 0.6429 | 9.0000/14.0000 | 13 / 27 | no_applicable_gold=27 |
| Clause Recall @ 3 | 0.9231 | 0.9286 | 13.0000/14.0000 | 13 / 27 | no_applicable_gold=27 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 40 | k_exceeds_configured_capacity=40 |
| Article MRR | 0.9444 | 0.9444 | 25.5000/27.0000 | 27 / 13 | no_applicable_gold=13 |
| Clause MRR | 0.7949 | 0.7949 | 10.3333/13.0000 | 13 / 27 | no_applicable_gold=27 |
| Document MRR | 0.9750 | 0.9750 | 39.0000/40.0000 | 40 / 0 | none |
| nDCG @ 10 | 0.9182 | 0.9007 | 43.4165/48.2021 | 40 / 0 | none |
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
| `t_retrieval` | 2.6532 | 4.1412 | 3.1229 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 2.6533 | 4.1412 | 3.1229 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_017` | `ok` | `N/A` | `no` | `none` | 25.5477 |
| `case_019` | `ok` | `N/A` | `no` | `none` | 2.1629 |
| `case_021` | `ok` | `N/A` | `no` | `none` | 2.7090 |
| `case_031` | `ok` | `N/A` | `no` | `none` | 1.2011 |
| `case_036` | `ok` | `N/A` | `no` | `none` | 2.9727 |
| `case_039` | `ok` | `N/A` | `no` | `none` | 1.2195 |
| `case_043` | `ok` | `N/A` | `no` | `none` | 3.4071 |
| `case_061` | `ok` | `N/A` | `no` | `none` | 2.7045 |
| `case_065` | `ok` | `N/A` | `no` | `none` | 2.9782 |
| `case_075` | `ok` | `N/A` | `no` | `none` | 4.0923 |
| `case_101` | `ok` | `N/A` | `no` | `none` | 3.0639 |
| `case_121` | `ok` | `N/A` | `no` | `none` | 1.2602 |
| `case_127` | `ok` | `N/A` | `no` | `none` | 1.2770 |
| `case_133` | `ok` | `N/A` | `no` | `none` | 2.6552 |
| `case_135` | `ok` | `N/A` | `no` | `none` | 2.3505 |
| `case_165` | `ok` | `N/A` | `no` | `none` | 2.9609 |
| `case_171` | `ok` | `N/A` | `no` | `none` | 2.9387 |
| `case_177` | `ok` | `N/A` | `no` | `none` | 2.4616 |
| `case_187` | `ok` | `N/A` | `no` | `none` | 3.1825 |
| `case_204` | `ok` | `N/A` | `no` | `none` | 4.1916 |
| `case_227` | `ok` | `N/A` | `no` | `none` | 3.3783 |
| `case_243` | `ok` | `N/A` | `no` | `none` | 1.2188 |
| `case_253` | `ok` | `N/A` | `no` | `none` | 2.9569 |
| `case_257` | `ok` | `N/A` | `no` | `none` | 1.3208 |
| `case_261` | `ok` | `N/A` | `no` | `none` | 2.6515 |
| `case_263` | `ok` | `N/A` | `no` | `none` | 2.5339 |
| `case_285` | `ok` | `N/A` | `no` | `none` | 1.5483 |
| `case_309` | `ok` | `N/A` | `no` | `none` | 1.6244 |
| `case_323` | `ok` | `N/A` | `no` | `none` | 3.2503 |
| `case_329` | `ok` | `N/A` | `no` | `none` | 3.4642 |
| `case_331` | `ok` | `N/A` | `no` | `none` | 2.5278 |
| `case_339` | `ok` | `N/A` | `no` | `none` | 2.5076 |
| `case_355` | `ok` | `N/A` | `no` | `none` | 2.5191 |
| `case_361` | `ok` | `N/A` | `no` | `none` | 4.1385 |
| `case_371` | `ok` | `N/A` | `no` | `none` | 1.2015 |
| `case_374` | `ok` | `N/A` | `no` | `none` | 3.8790 |
| `case_375` | `ok` | `N/A` | `no` | `none` | 1.0577 |
| `case_379` | `ok` | `N/A` | `no` | `none` | 2.6152 |
| `case_397` | `ok` | `N/A` | `no` | `none` | 2.7579 |
| `case_411` | `ok` | `N/A` | `no` | `none` | 2.4276 |