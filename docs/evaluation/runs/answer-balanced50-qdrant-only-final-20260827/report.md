# VIETLEX EVALUATION REPORT — answer-balanced50-qdrant-only-final-20260827

**Run ID**: `answer-balanced50-qdrant-only-final-20260827`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-08-26T17:29:50.409883+00:00`  
**Git Commit SHA**: `aa76cf855699d6fd98f94b73b84cc20fb3cf9112`  
**Source State SHA-256**: `f2f59c63e30233ac99a3bf2110bc3e7ea121d6ed5cd3629ad208f3e9550b5f3c`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `0c5b26f8ac2cbbddd97cf6e6a319d3f7e3c021c929d9dd943262835af14793a0`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `d6e125030e8dda700667ba00f25162fac76472a9bfa2d087f54e2b5bc73a1fee`  
**Configuration Fingerprint**: `d0b7e7dd601e932a8e54f6c1bb2162c72c057275c346b9f897b30c50601e3462`  
**Execution Command**: `run_answer_eval.py --case-ids case_017 case_019 case_021 case_031 case_036 case_039 case_043 case_061 case_065 case_069 case_075 case_101 case_105 case_115 case_116 case_121 case_127 case_133 case_135 case_165 case_171 case_177 case_183 case_187 case_194 case_204 case_227 case_243 case_253 case_257 case_261 case_263 case_285 case_309 case_323 case_325 case_329 case_331 case_339 case_355 case_361 case_362 case_371 case_374 case_375 case_379 case_397 case_411 case_415 case_417 --gold-policy none --profile separated_intent --rewrite off --guardrails enforce --reranker qdrant-only --concurrency 1 --judge ragas --run-id answer-balanced50-qdrant-only-final-20260827`  
**Evaluation Mode**: `answer` | **Judge**: `ragas` | **Guardrails**: `enforce`  

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
| Document Recall @ 1 | 0.0000 | 0.0000 | 0.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 3 | 0.0000 | 0.0000 | 0.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 5 | 0.0000 | 0.0000 | 0.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 10 | 0.0000 | 0.0000 | 0.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 24 | 0.0000 | 0.0000 | 0.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Article Recall @ 1 | 0.0000 | 0.0000 | 0.0000/30.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Article Recall @ 3 | 0.0000 | 0.0000 | 0.0000/30.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 50 | k_exceeds_configured_capacity=40, no_verified_gold_label=10 |
| Clause Recall @ 1 | 0.0000 | 0.0000 | 0.0000/14.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Clause Recall @ 3 | 0.0000 | 0.0000 | 0.0000/14.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 50 | k_exceeds_configured_capacity=40, no_verified_gold_label=10 |
| Article MRR | 0.0000 | 0.0000 | 0.0000/27.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Clause MRR | 0.0000 | 0.0000 | 0.0000/13.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Document MRR | 0.0000 | 0.0000 | 0.0000/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| nDCG @ 10 | 0.0000 | 0.0000 | 0.0000/48.2021 | 40 / 10 | no_verified_gold_label=10 |
| Exact legal-reference hit | 0.0000 | 0.0000 | 0.0000/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| Multi-hop all-required coverage | 0.0000 | 0.0000 | 0.0000/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| Multi-hop partial coverage | 0.0000 | 0.0000 | 0.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |

## 3. Stage metrics

| Pipeline stage | Capacity | Scored cases | Candidate p50 / p95 | Matched / Applicable documents | First-loss evidence count | Null reasons |
| :--- | ---: | ---: | :---: | :---: | ---: | :--- |
| `pinecone_document_metrics` | 24 | 40 | 24.0000 / 24.0000 | 0 / 53 | 0 | no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `fts_document_metrics` | 12 | 40 | 12.0000 / 12.0000 | 0 / 53 | 0 | k_exceeds_configured_capacity=40, no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `source_retrieval_metrics` | 36 | 40 | 36.0000 / 36.0000 | 0 / 53 | 53 | no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `merged_document_metrics` | 36 | 40 | 12.0000 / 12.0000 | 0 / 53 | 0 | no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `resolved_document_metrics` | 16 | 40 | 16.0000 / 16.0000 | 0 / 53 | 0 | k_exceeds_configured_capacity=40, no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `structural_chunk_metrics` | N/A | 40 | 490.5000 / 1460.1500 | 0 / 53 | 0 | configured_capacity_unknown=440, no_applicable_gold=40, no_verified_gold_label=140 |
| `local_selection_metrics` | 64 | 40 | 60.0000 / 64.0000 | 0 / 53 | 0 | no_applicable_gold=160, no_verified_gold_label=140 |
| `reranker_input_metrics` | 24 | 40 | 24.0000 / 24.0000 | 0 / 53 | 0 | no_applicable_gold=160, no_verified_gold_label=140 |
| `reranker_output_metrics` | 3 | 40 | 3.0000 / 3.0000 | 0 / 53 | 0 | k_exceeds_configured_capacity=200, no_applicable_gold=120, no_verified_gold_label=140 |
| `final_evidence_metrics` | 3 | 40 | 3.0000 / 3.0000 | 0 / 53 | 0 | k_exceeds_configured_capacity=200, no_applicable_gold=120, no_verified_gold_label=140 |

## 4. Interpretation notes

- Recall@K is undefined when K exceeds the configured stage capacity; nDCG@10 still treats unreturned ranks as zero gain so capacity effects remain measurable.
- Configured provider candidates are provenance only; they do not prove which provider answered a request.

## 5. Deterministic answer metrics

Answer scored / total: `50 / 50`
Answer skip reasons: `none`

| Metric | Value |
| :--- | ---: |
| `answer_similarity_pass_rate` | 0.0000 |
| `unanswerable_accuracy` | N/A |
| `refusal_precision` | N/A |
| `refusal_recall` | N/A |
| `token_f1` | 0.1585 |
| `char_f1` | 0.1801 |
| `rouge_l` | 0.1183 |
| `chrf` | 0.2594 |
| `citation_precision` | 0.0000 |
| `invalid_citation_rate` | 0.0000 |

## 6. Generation, guardrail, and judge coverage

Generation STOP / total: `50 / 50`
Input safe / total: `50 / 50`
Output safe / total: `50 / 50`
Ragas scored / eligible: `50 / 50`
Judge technical errors: `0`

| Ragas metric | Mean | Scored cases |
| :--- | ---: | ---: |
| `faithfulness` | 0.7467 | 50 |
| `answer_accuracy` | 0.1500 | 50 |
| `context_precision` | 0.1600 | 50 |
| `context_recall` | 0.1567 | 50 |

## 7. Latency

| Stage | P50 (s) | P95 (s) | Mean (s) |
| :--- | ---: | ---: | ---: |
| `t_input_guardrail` | 1.1054 | 2.6364 | 1.3872 |
| `t_output_guardrail` | 1.1763 | 1.7451 | 1.2425 |
| `t_retrieval` | 4.8934 | 6.1031 | 5.1401 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 10.6517 | 14.0897 | 10.9701 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_017` | `ok` | `STOP` | `yes` | `none` | 17.5092 |
| `case_019` | `ok` | `STOP` | `yes` | `none` | 11.7396 |
| `case_021` | `ok` | `STOP` | `yes` | `none` | 10.9088 |
| `case_031` | `ok` | `STOP` | `yes` | `none` | 11.0202 |
| `case_036` | `ok` | `STOP` | `yes` | `none` | 13.2194 |
| `case_039` | `ok` | `STOP` | `yes` | `none` | 9.7058 |
| `case_043` | `ok` | `STOP` | `yes` | `none` | 10.1802 |
| `case_061` | `ok` | `STOP` | `yes` | `none` | 10.8744 |
| `case_065` | `ok` | `STOP` | `yes` | `none` | 16.2446 |
| `case_069` | `ok` | `STOP` | `yes` | `none` | 11.1605 |
| `case_075` | `ok` | `STOP` | `yes` | `none` | 12.6103 |
| `case_101` | `ok` | `STOP` | `yes` | `none` | 10.2869 |
| `case_105` | `ok` | `STOP` | `yes` | `none` | 13.3111 |
| `case_115` | `ok` | `STOP` | `yes` | `none` | 9.4249 |
| `case_116` | `ok` | `STOP` | `yes` | `none` | 10.9466 |
| `case_121` | `ok` | `STOP` | `yes` | `none` | 9.9307 |
| `case_127` | `ok` | `STOP` | `yes` | `none` | 8.5204 |
| `case_133` | `ok` | `STOP` | `yes` | `none` | 8.3350 |
| `case_135` | `ok` | `STOP` | `yes` | `none` | 10.1611 |
| `case_165` | `ok` | `STOP` | `yes` | `none` | 11.0273 |
| `case_171` | `ok` | `STOP` | `yes` | `none` | 12.2444 |
| `case_177` | `ok` | `STOP` | `yes` | `none` | 14.6037 |
| `case_183` | `ok` | `STOP` | `yes` | `none` | 11.3875 |
| `case_187` | `ok` | `STOP` | `yes` | `none` | 11.2314 |
| `case_194` | `ok` | `STOP` | `yes` | `none` | 10.8500 |
| `case_204` | `ok` | `STOP` | `yes` | `none` | 13.4614 |
| `case_227` | `ok` | `STOP` | `yes` | `none` | 9.1780 |
| `case_243` | `ok` | `STOP` | `yes` | `none` | 11.6234 |
| `case_253` | `ok` | `STOP` | `yes` | `none` | 11.4551 |
| `case_257` | `ok` | `STOP` | `yes` | `none` | 9.6570 |
| `case_261` | `ok` | `STOP` | `yes` | `none` | 9.4385 |
| `case_263` | `ok` | `STOP` | `yes` | `none` | 9.5781 |
| `case_285` | `ok` | `STOP` | `yes` | `none` | 10.2873 |
| `case_309` | `ok` | `STOP` | `yes` | `none` | 10.1579 |
| `case_323` | `ok` | `STOP` | `yes` | `none` | 11.1437 |
| `case_325` | `ok` | `STOP` | `yes` | `none` | 9.6694 |
| `case_329` | `ok` | `STOP` | `yes` | `none` | 9.4620 |
| `case_331` | `ok` | `STOP` | `yes` | `none` | 9.7953 |
| `case_339` | `ok` | `STOP` | `yes` | `none` | 10.2893 |
| `case_355` | `ok` | `STOP` | `yes` | `none` | 10.1882 |
| `case_361` | `ok` | `STOP` | `yes` | `none` | 9.9744 |
| `case_362` | `ok` | `STOP` | `yes` | `none` | 10.2972 |
| `case_371` | `ok` | `STOP` | `yes` | `none` | 10.4534 |
| `case_374` | `ok` | `STOP` | `yes` | `none` | 10.9817 |
| `case_375` | `ok` | `STOP` | `yes` | `none` | 10.9803 |
| `case_379` | `ok` | `STOP` | `yes` | `none` | 9.9736 |
| `case_397` | `ok` | `STOP` | `yes` | `none` | 11.9249 |
| `case_411` | `ok` | `STOP` | `yes` | `none` | 10.0256 |
| `case_415` | `ok` | `STOP` | `yes` | `none` | 10.0019 |
| `case_417` | `ok` | `STOP` | `yes` | `none` | 11.0714 |