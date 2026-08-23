# VIETLEX EVALUATION REPORT — retrieval-crosslane-a-verified40-20260823

**Run ID**: `retrieval-crosslane-a-verified40-20260823`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-08-23T13:26:21.196817+00:00`  
**Git Commit SHA**: `733f95baa2cb72090ed2e6ab8492ca5ca350baba`  
**Source State SHA-256**: `2fd30a9b885a6e17af33c2e3f445d5f1a9b62e4ea219d0f17362b2c50db15924`  
**Git Dirty Status**: `False` (Diff: `clean`, SHA-256: `N/A`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `b458880e2c2fc4f2813965d57dc96517555488a5ada3702da12fb811f05fb90b`  
**Configuration Fingerprint**: `d46c1bdf8e6160f74ca5fe02bc39a217beba858057215a02e4a4d287c2ccbce6`  
**Execution Command**: `run_retrieval_eval.py --verified-only --gold-policy all-required-verified --profile separated_intent --rewrite off --reranker current --concurrency 1 --require-clean-git --run-id retrieval-crosslane-a-verified40-20260823`  
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
| Retrieval technical-error rate | 5.0% | 5.0% | 2.0000/40.0000 | 40 / 0 | none | Status retrieval_error or partial_retrieval_error |
| Reranker technical-error rate | 0.0% | 0.0% | 0.0000/40.0000 | 40 / 0 | none | Exact status reranker_error |

## 2. Retrieval quality

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons |
| :--- | ---: | ---: | :---: | :---: | :--- |
| Document Recall @ 1 | 0.4750 | 0.4340 | 23.0000/53.0000 | 40 / 0 | none |
| Document Recall @ 3 | 0.9250 | 0.9434 | 50.0000/53.0000 | 40 / 0 | none |
| Document Recall @ 5 | 0.9250 | 0.9434 | 50.0000/53.0000 | 40 / 0 | none |
| Document Recall @ 10 | 0.9500 | 0.9623 | 51.0000/53.0000 | 40 / 0 | none |
| Document Recall @ 24 | 0.9750 | 0.9811 | 52.0000/53.0000 | 40 / 0 | none |
| Article Recall @ 1 | 0.6111 | 0.6000 | 18.0000/30.0000 | 27 / 13 | no_applicable_gold=13 |
| Article Recall @ 3 | 0.8704 | 0.8333 | 25.0000/30.0000 | 27 / 13 | no_applicable_gold=13 |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 40 | k_exceeds_configured_capacity=40 |
| Clause Recall @ 1 | 0.6923 | 0.6429 | 9.0000/14.0000 | 13 / 27 | no_applicable_gold=27 |
| Clause Recall @ 3 | 0.7692 | 0.7143 | 10.0000/14.0000 | 13 / 27 | no_applicable_gold=27 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 40 | k_exceeds_configured_capacity=40 |
| Article MRR | 0.7160 | 0.7160 | 19.3333/27.0000 | 27 / 13 | no_applicable_gold=13 |
| Clause MRR | 0.7179 | 0.7179 | 9.3333/13.0000 | 13 / 27 | no_applicable_gold=27 |
| Document MRR | 0.6896 | 0.6896 | 27.5826/40.0000 | 40 / 0 | none |
| nDCG @ 10 | 0.7206 | 0.6742 | 32.5000/48.2021 | 40 / 0 | none |
| Exact legal-reference hit | 0.8500 | 0.8500 | 34.0000/40.0000 | 40 / 0 | none |
| Multi-hop all-required coverage | 0.8000 | 0.8000 | 32.0000/40.0000 | 40 / 0 | none |
| Multi-hop partial coverage | 0.8250 | 0.7925 | 42.0000/53.0000 | 40 / 0 | none |

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
| `reranker_output_metrics` | 6 | 40 | 9.0000 / 9.0000 | 52 / 53 | 1 | k_exceeds_configured_capacity=80, no_applicable_gold=160 |
| `final_evidence_metrics` | 5 | 40 | 3.0000 / 3.0000 | 44 / 53 | 9 | k_exceeds_configured_capacity=160, no_applicable_gold=120 |

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
| `t_retrieval` | 5.2356 | 20.0716 | 6.4553 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 5.2357 | 20.0716 | 6.4553 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_017` | `ok` | `N/A` | `no` | `none` | 19.4709 |
| `case_019` | `ok` | `N/A` | `no` | `none` | 4.6423 |
| `case_021` | `ok` | `N/A` | `no` | `none` | 4.3388 |
| `case_031` | `ok` | `N/A` | `no` | `none` | 4.1473 |
| `case_036` | `ok` | `N/A` | `no` | `none` | 4.3279 |
| `case_039` | `ok` | `N/A` | `no` | `none` | 4.6494 |
| `case_043` | `ok` | `N/A` | `no` | `none` | 4.2438 |
| `case_061` | `partial_retrieval_error` | `N/A` | `no` | `retrieval_fallback` | 38.1461 |
| `case_065` | `partial_retrieval_error` | `N/A` | `no` | `retrieval_fallback` | 31.4853 |
| `case_075` | `ok` | `N/A` | `no` | `none` | 3.0073 |
| `case_101` | `ok` | `N/A` | `no` | `none` | 1.9328 |
| `case_121` | `ok` | `N/A` | `no` | `none` | 2.8786 |
| `case_127` | `ok` | `N/A` | `no` | `none` | 2.3031 |
| `case_133` | `ok` | `N/A` | `no` | `none` | 2.1943 |
| `case_135` | `ok` | `N/A` | `no` | `none` | 2.0901 |
| `case_165` | `ok` | `N/A` | `no` | `none` | 2.0673 |
| `case_171` | `ok` | `N/A` | `no` | `none` | 1.7727 |
| `case_177` | `ok` | `N/A` | `no` | `none` | 1.8084 |
| `case_187` | `ok` | `N/A` | `no` | `none` | 2.4752 |
| `case_204` | `ok` | `N/A` | `no` | `none` | 1.9295 |
| `case_227` | `ok` | `N/A` | `no` | `none` | 1.8114 |
| `case_243` | `ok` | `N/A` | `no` | `none` | 1.8290 |
| `case_253` | `ok` | `N/A` | `no` | `none` | 8.2359 |
| `case_257` | `ok` | `N/A` | `no` | `none` | 6.9878 |
| `case_261` | `ok` | `N/A` | `no` | `none` | 7.0947 |
| `case_263` | `ok` | `N/A` | `no` | `none` | 5.7036 |
| `case_285` | `ok` | `N/A` | `no` | `none` | 6.9236 |
| `case_309` | `ok` | `N/A` | `no` | `none` | 6.9097 |
| `case_323` | `ok` | `N/A` | `no` | `none` | 6.5916 |
| `case_329` | `ok` | `N/A` | `no` | `none` | 6.1892 |
| `case_331` | `ok` | `N/A` | `no` | `none` | 6.4559 |
| `case_339` | `ok` | `N/A` | `no` | `none` | 6.0029 |
| `case_355` | `ok` | `N/A` | `no` | `none` | 6.1937 |
| `case_361` | `ok` | `N/A` | `no` | `none` | 5.5606 |
| `case_371` | `ok` | `N/A` | `no` | `none` | 5.5452 |
| `case_374` | `ok` | `N/A` | `no` | `none` | 6.4436 |
| `case_375` | `ok` | `N/A` | `no` | `none` | 5.3787 |
| `case_379` | `ok` | `N/A` | `no` | `none` | 5.0927 |
| `case_397` | `ok` | `N/A` | `no` | `none` | 6.2326 |
| `case_411` | `ok` | `N/A` | `no` | `none` | 7.1198 |