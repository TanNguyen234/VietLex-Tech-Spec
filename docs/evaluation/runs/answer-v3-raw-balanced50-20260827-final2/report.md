# VIETLEX EVALUATION REPORT — answer-v3-raw-balanced50-20260827-final2

**Run ID**: `answer-v3-raw-balanced50-20260827-final2`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-08-27T11:57:14.521493+00:00`  
**Git Commit SHA**: `aa76cf855699d6fd98f94b73b84cc20fb3cf9112`  
**Source State SHA-256**: `558472d9e09510666e469b2eaa1451362ac1067559736a05d9ac8501fc37d580`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `271bb878ea668930d1f643544cfd1ca8a31cc65e63778f83c94d6627c8b4e02e`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `d6e125030e8dda700667ba00f25162fac76472a9bfa2d087f54e2b5bc73a1fee`  
**Configuration Fingerprint**: `1305dd0addb8dec3aeed4cdd29ea0eaad3c8e496b38eb4201ea6dcdda3ce20e4`  
**Execution Command**: `run_answer_eval.py --backend vertex-qdrant-v3 --ranking raw-rrf --retrieval-run docs/evaluation/runs/retrieval-v3-raw-balanced50-20260827-final --profile separated_intent --rewrite off --guardrails enforce --reranker current --concurrency 1 --gold-policy none --judge ragas --case-ids case_017 case_019 case_021 case_031 case_036 case_039 case_043 case_061 case_065 case_069 case_075 case_101 case_105 case_115 case_116 case_121 case_127 case_133 case_135 case_165 case_171 case_177 case_183 case_187 case_194 case_204 case_227 case_243 case_253 case_257 case_261 case_263 case_285 case_309 case_323 case_325 case_329 case_331 case_339 case_355 case_361 case_362 case_371 case_374 case_375 case_379 case_397 case_411 case_415 case_417 --run-id answer-v3-raw-balanced50-20260827-final2`  
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

## 5. Deterministic answer metrics

Answer scored / total: `50 / 50`
Answer skip reasons: `none`

| Metric | Value |
| :--- | ---: |
| `answer_similarity_pass_rate` | 0.0000 |
| `unanswerable_accuracy` | N/A |
| `refusal_precision` | N/A |
| `refusal_recall` | N/A |
| `token_f1` | 0.2423 |
| `char_f1` | 0.2336 |
| `rouge_l` | 0.2296 |
| `chrf` | 0.3914 |
| `citation_precision` | 0.9727 |
| `invalid_citation_rate` | 0.0273 |

## 6. Generation, guardrail, and judge coverage

Generation STOP / total: `50 / 50`
Input safe / total: `50 / 50`
Output safe / total: `50 / 50`
Ragas scored / eligible: `50 / 50`
Judge technical errors: `0`

| Ragas metric | Mean | Scored cases |
| :--- | ---: | ---: |
| `faithfulness` | 0.8841 | 50 |
| `answer_accuracy` | 0.9250 | 50 |
| `context_precision` | 0.8733 | 50 |
| `context_recall` | 0.9367 | 50 |

## 7. Latency

| Stage | P50 (s) | P95 (s) | Mean (s) |
| :--- | ---: | ---: | ---: |
| `t_input_guardrail` | 1.1271 | 1.3797 | 1.1399 |
| `t_output_guardrail` | 1.2053 | 1.5359 | 1.2268 |
| `t_retrieval` | 3.2525 | 4.6265 | 3.5423 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 5.3212 | 7.0488 | 5.5211 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_017` | `ok` | `STOP` | `yes` | `none` | 5.3197 |
| `case_019` | `ok` | `STOP` | `yes` | `none` | 5.2033 |
| `case_021` | `ok` | `STOP` | `yes` | `none` | 6.0657 |
| `case_031` | `ok` | `STOP` | `yes` | `none` | 6.2176 |
| `case_036` | `ok` | `STOP` | `yes` | `none` | 5.1924 |
| `case_039` | `ok` | `STOP` | `yes` | `none` | 5.3227 |
| `case_043` | `ok` | `STOP` | `yes` | `none` | 6.8635 |
| `case_061` | `ok` | `STOP` | `yes` | `none` | 4.7406 |
| `case_065` | `ok` | `STOP` | `yes` | `none` | 6.4044 |
| `case_069` | `ok` | `STOP` | `yes` | `none` | 4.7180 |
| `case_075` | `ok` | `STOP` | `yes` | `none` | 7.4143 |
| `case_101` | `ok` | `STOP` | `yes` | `none` | 4.7226 |
| `case_105` | `ok` | `STOP` | `yes` | `none` | 5.0858 |
| `case_115` | `ok` | `STOP` | `yes` | `none` | 4.2210 |
| `case_116` | `ok` | `STOP` | `yes` | `none` | 5.9482 |
| `case_121` | `ok` | `STOP` | `yes` | `none` | 5.2790 |
| `case_127` | `ok` | `STOP` | `yes` | `none` | 4.4687 |
| `case_133` | `ok` | `STOP` | `yes` | `none` | 6.4060 |
| `case_135` | `ok` | `STOP` | `yes` | `none` | 5.6983 |
| `case_165` | `ok` | `STOP` | `yes` | `none` | 5.9140 |
| `case_171` | `ok` | `STOP` | `yes` | `none` | 4.9842 |
| `case_177` | `ok` | `STOP` | `yes` | `none` | 4.6605 |
| `case_183` | `ok` | `STOP` | `yes` | `none` | 6.5297 |
| `case_187` | `ok` | `STOP` | `yes` | `none` | 4.4227 |
| `case_194` | `ok` | `STOP` | `yes` | `none` | 5.2794 |
| `case_204` | `ok` | `STOP` | `yes` | `none` | 7.2765 |
| `case_227` | `ok` | `STOP` | `yes` | `none` | 4.7244 |
| `case_243` | `ok` | `STOP` | `yes` | `none` | 5.7036 |
| `case_253` | `ok` | `STOP` | `yes` | `none` | 5.9570 |
| `case_257` | `ok` | `STOP` | `yes` | `none` | 7.0627 |
| `case_261` | `ok` | `STOP` | `yes` | `none` | 5.3754 |
| `case_263` | `ok` | `STOP` | `yes` | `none` | 4.9245 |
| `case_285` | `ok` | `STOP` | `yes` | `none` | 5.5573 |
| `case_309` | `ok` | `STOP` | `yes` | `none` | 5.7348 |
| `case_323` | `ok` | `STOP` | `yes` | `none` | 5.4485 |
| `case_325` | `ok` | `STOP` | `yes` | `none` | 5.1702 |
| `case_329` | `ok` | `STOP` | `yes` | `none` | 5.9563 |
| `case_331` | `ok` | `STOP` | `yes` | `none` | 5.3479 |
| `case_339` | `ok` | `STOP` | `yes` | `none` | 5.1761 |
| `case_355` | `ok` | `STOP` | `yes` | `none` | 4.8554 |
| `case_361` | `ok` | `STOP` | `yes` | `none` | 4.8878 |
| `case_362` | `ok` | `STOP` | `yes` | `none` | 4.8885 |
| `case_371` | `ok` | `STOP` | `yes` | `none` | 6.3218 |
| `case_374` | `ok` | `STOP` | `yes` | `none` | 4.9552 |
| `case_375` | `ok` | `STOP` | `yes` | `none` | 5.1651 |
| `case_379` | `ok` | `STOP` | `yes` | `none` | 5.3008 |
| `case_397` | `ok` | `STOP` | `yes` | `none` | 7.0318 |
| `case_411` | `ok` | `STOP` | `yes` | `none` | 5.7251 |
| `case_415` | `ok` | `STOP` | `yes` | `none` | 4.9422 |
| `case_417` | `ok` | `STOP` | `yes` | `none` | 5.4814 |