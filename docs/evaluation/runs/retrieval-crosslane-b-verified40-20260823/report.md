# VIETLEX EVALUATION REPORT — retrieval-crosslane-b-verified40-20260823

**Run ID**: `retrieval-crosslane-b-verified40-20260823`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-08-23T13:31:06.014302+00:00`  
**Git Commit SHA**: `733f95baa2cb72090ed2e6ab8492ca5ca350baba`  
**Source State SHA-256**: `2fd30a9b885a6e17af33c2e3f445d5f1a9b62e4ea219d0f17362b2c50db15924`  
**Git Dirty Status**: `False` (Diff: `clean`, SHA-256: `N/A`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `b458880e2c2fc4f2813965d57dc96517555488a5ada3702da12fb811f05fb90b`  
**Configuration Fingerprint**: `c21e8085d8148b84e626254d9417db2c5183cdcdede16073f779bc9f16de23dc`  
**Execution Command**: `run_retrieval_eval.py --verified-only --gold-policy all-required-verified --profile separated_intent --rewrite off --reranker current --concurrency 1 --require-clean-git --run-id retrieval-crosslane-b-verified40-20260823`  
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
| Document Recall @ 1 | 0.4750 | 0.4340 | 23.0000/53.0000 | 40 / 0 | none |
| Document Recall @ 3 | 0.9250 | 0.9434 | 50.0000/53.0000 | 40 / 0 | none |
| Document Recall @ 5 | 0.9250 | 0.9434 | 50.0000/53.0000 | 40 / 0 | none |
| Document Recall @ 10 | 0.9500 | 0.9623 | 51.0000/53.0000 | 40 / 0 | none |
| Document Recall @ 24 | 0.9750 | 0.9811 | 52.0000/53.0000 | 40 / 0 | none |
| Article Recall @ 1 | 0.7222 | 0.7000 | 21.0000/30.0000 | 27 / 13 | no_applicable_gold=13 |
| Article Recall @ 3 | 0.9259 | 0.9000 | 27.0000/30.0000 | 27 / 13 | no_applicable_gold=13 |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 40 | k_exceeds_configured_capacity=40 |
| Clause Recall @ 1 | 0.6923 | 0.6429 | 9.0000/14.0000 | 13 / 27 | no_applicable_gold=27 |
| Clause Recall @ 3 | 0.8846 | 0.8571 | 12.0000/14.0000 | 13 / 27 | no_applicable_gold=27 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 40 | k_exceeds_configured_capacity=40 |
| Article MRR | 0.8333 | 0.8333 | 22.5000/27.0000 | 27 / 13 | no_applicable_gold=13 |
| Clause MRR | 0.7820 | 0.7821 | 10.1667/13.0000 | 13 / 27 | no_applicable_gold=27 |
| Document MRR | 0.6896 | 0.6896 | 27.5826/40.0000 | 40 / 0 | none |
| nDCG @ 10 | 0.7549 | 0.7189 | 34.6546/48.2021 | 40 / 0 | none |
| Exact legal-reference hit | 0.9250 | 0.9250 | 37.0000/40.0000 | 40 / 0 | none |
| Multi-hop all-required coverage | 0.8500 | 0.8500 | 34.0000/40.0000 | 40 / 0 | none |
| Multi-hop partial coverage | 0.8875 | 0.8491 | 45.0000/53.0000 | 40 / 0 | none |

## 3. Stage metrics

| Pipeline stage | Capacity | Scored cases | Candidate p50 / p95 | Matched / Applicable documents | First-loss evidence count | Null reasons |
| :--- | ---: | ---: | :---: | :---: | ---: | :--- |
| `pinecone_document_metrics` | 48 | 40 | 72.0000 / 72.0000 | 52 / 53 | 0 | stage_does_not_expose_structural_locators=320 |
| `fts_document_metrics` | 48 | 40 | 60.0000 / 60.0000 | 53 / 53 | 0 | stage_does_not_expose_structural_locators=320 |
| `source_retrieval_metrics` | 64 | 40 | 50.0000 / 68.1000 | 53 / 53 | 0 | stage_does_not_expose_structural_locators=320 |
| `merged_document_metrics` | 64 | 40 | 64.5000 / 76.0000 | 53 / 53 | 0 | stage_does_not_expose_structural_locators=320 |
| `resolved_document_metrics` | 64 | 40 | 68.5000 / 80.0000 | 53 / 53 | 0 | stage_does_not_expose_structural_locators=320 |
| `structural_chunk_metrics` | 64 | 40 | 642.0000 / 1757.8500 | 53 / 53 | 1 | no_applicable_gold=160 |
| `local_selection_metrics` | N/A | 40 | 113.0000 / 125.1500 | 53 / 53 | 0 | configured_capacity_unknown=440, no_applicable_gold=40 |
| `reranker_input_metrics` | 64 | 40 | 76.5000 / 88.0000 | 53 / 53 | 0 | no_applicable_gold=160 |
| `reranker_output_metrics` | 6 | 40 | 9.0000 / 9.0000 | 53 / 53 | 0 | k_exceeds_configured_capacity=80, no_applicable_gold=160 |
| `final_evidence_metrics` | 5 | 40 | 3.0000 / 3.0000 | 48 / 53 | 7 | k_exceeds_configured_capacity=160, no_applicable_gold=120 |

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
| `t_retrieval` | 8.9153 | 13.1542 | 8.7398 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 8.9153 | 13.1543 | 8.7399 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_017` | `ok` | `N/A` | `no` | `none` | 20.4815 |
| `case_019` | `ok` | `N/A` | `no` | `none` | 5.6559 |
| `case_021` | `ok` | `N/A` | `no` | `none` | 4.7821 |
| `case_031` | `ok` | `N/A` | `no` | `none` | 4.3329 |
| `case_036` | `ok` | `N/A` | `no` | `none` | 4.8838 |
| `case_039` | `ok` | `N/A` | `no` | `none` | 4.5748 |
| `case_043` | `ok` | `N/A` | `no` | `none` | 4.8700 |
| `case_061` | `ok` | `N/A` | `no` | `none` | 4.4814 |
| `case_065` | `ok` | `N/A` | `no` | `none` | 4.4239 |
| `case_075` | `ok` | `N/A` | `no` | `none` | 4.5394 |
| `case_101` | `ok` | `N/A` | `no` | `none` | 5.6925 |
| `case_121` | `ok` | `N/A` | `no` | `none` | 5.3742 |
| `case_127` | `ok` | `N/A` | `no` | `none` | 4.8061 |
| `case_133` | `ok` | `N/A` | `no` | `none` | 5.5683 |
| `case_135` | `ok` | `N/A` | `no` | `none` | 8.3976 |
| `case_165` | `ok` | `N/A` | `no` | `none` | 8.7568 |
| `case_171` | `ok` | `N/A` | `no` | `none` | 9.6625 |
| `case_177` | `ok` | `N/A` | `no` | `none` | 9.3776 |
| `case_187` | `ok` | `N/A` | `no` | `none` | 10.2434 |
| `case_204` | `ok` | `N/A` | `no` | `none` | 10.4922 |
| `case_227` | `ok` | `N/A` | `no` | `none` | 10.1456 |
| `case_243` | `ok` | `N/A` | `no` | `none` | 11.9559 |
| `case_253` | `ok` | `N/A` | `no` | `none` | 12.1047 |
| `case_257` | `ok` | `N/A` | `no` | `none` | 13.0983 |
| `case_261` | `ok` | `N/A` | `no` | `none` | 9.7957 |
| `case_263` | `ok` | `N/A` | `no` | `none` | 9.3595 |
| `case_285` | `ok` | `N/A` | `no` | `none` | 12.4583 |
| `case_309` | `ok` | `N/A` | `no` | `none` | 11.2298 |
| `case_323` | `ok` | `N/A` | `no` | `none` | 8.4849 |
| `case_329` | `ok` | `N/A` | `no` | `none` | 12.9726 |
| `case_331` | `ok` | `N/A` | `no` | `none` | 12.1096 |
| `case_339` | `ok` | `N/A` | `no` | `none` | 14.2186 |
| `case_355` | `ok` | `N/A` | `no` | `none` | 7.4467 |
| `case_361` | `ok` | `N/A` | `no` | `none` | 7.4807 |
| `case_371` | `ok` | `N/A` | `no` | `none` | 9.1846 |
| `case_374` | `ok` | `N/A` | `no` | `none` | 9.0738 |
| `case_375` | `ok` | `N/A` | `no` | `none` | 7.3315 |
| `case_379` | `ok` | `N/A` | `no` | `none` | 7.5397 |
| `case_397` | `ok` | `N/A` | `no` | `none` | 11.0035 |
| `case_411` | `ok` | `N/A` | `no` | `none` | 11.2042 |