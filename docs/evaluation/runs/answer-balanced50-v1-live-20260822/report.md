# VIETLEX EVALUATION REPORT — answer-balanced50-v1-live-20260822

**Run ID**: `answer-balanced50-v1-live-20260822`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-08-22T14:37:43.670829+00:00`  
**Git Commit SHA**: `6dd558c3e163941690eb9a75490c886a898d52d5`  
**Source State SHA-256**: `9e28bdaf44062eabac13a05f14ec2559ad07f784e5da6752009755519f9a6af9`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `51841a6b17402050c6e49ce9c2a3dd1778e3ec39f3fcd84b1c52929028e57a06`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `b458880e2c2fc4f2813965d57dc96517555488a5ada3702da12fb811f05fb90b`  
**Configuration Fingerprint**: `6258116451b71681ab6b0fe84d66d2667f92a51e9888eafdbd3d594b6bc68c4d`  
**Execution Command**: `run_answer_eval.py --case-ids case_017 case_019 case_021 case_031 case_036 case_039 case_043 case_061 case_065 case_069 case_075 case_101 case_105 case_115 case_116 case_121 case_127 case_133 case_135 case_165 case_171 case_177 case_183 case_187 case_194 case_204 case_227 case_243 case_253 case_257 case_261 case_263 case_285 case_309 case_323 case_325 case_329 case_331 case_339 case_355 case_361 case_362 case_371 case_374 case_375 case_379 case_397 case_411 case_415 case_417 --gold-policy none --profile separated_intent --rewrite off --guardrails enforce --reranker current --concurrency 1 --judge ragas --run-id answer-balanced50-v1-live-20260822`  
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
| Retrieval technical-error rate | 2.0% | 2.0% | 1.0000/50.0000 | 50 / 0 | none | Status retrieval_error or partial_retrieval_error |
| Reranker technical-error rate | 0.0% | 0.0% | 0.0000/50.0000 | 50 / 0 | none | Exact status reranker_error |

## 2. Retrieval quality

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons |
| :--- | ---: | ---: | :---: | :---: | :--- |
| Document Recall @ 1 | 0.4750 | 0.4340 | 23.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 3 | 0.9250 | 0.9434 | 50.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 5 | 0.9250 | 0.9434 | 50.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 10 | 0.9500 | 0.9623 | 51.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 24 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Article Recall @ 1 | 0.6481 | 0.6333 | 19.0000/30.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Article Recall @ 3 | 0.9259 | 0.9000 | 27.0000/30.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 50 | k_exceeds_configured_capacity=40, no_verified_gold_label=10 |
| Clause Recall @ 1 | 0.7692 | 0.7143 | 10.0000/14.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Clause Recall @ 3 | 0.8846 | 0.8571 | 12.0000/14.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 50 | k_exceeds_configured_capacity=40, no_verified_gold_label=10 |
| Article MRR | 0.8086 | 0.8086 | 21.8333/27.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Clause MRR | 0.8333 | 0.8333 | 10.8333/13.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Document MRR | 0.6904 | 0.6904 | 27.6144/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| nDCG @ 10 | 0.8173 | 0.7836 | 37.7696/48.2021 | 40 / 10 | no_verified_gold_label=10 |
| Exact legal-reference hit | 0.9750 | 0.9750 | 39.0000/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| Multi-hop all-required coverage | 0.9500 | 0.9500 | 38.0000/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| Multi-hop partial coverage | 0.9625 | 0.9623 | 51.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |

## 3. Stage metrics

| Pipeline stage | Capacity | Scored cases | Candidate p50 / p95 | Matched / Applicable documents | First-loss evidence count | Null reasons |
| :--- | ---: | ---: | :---: | :---: | ---: | :--- |
| `pinecone_document_metrics` | 48 | 40 | 48.0000 / 48.0000 | 52 / 53 | 0 | no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `fts_document_metrics` | 48 | 40 | 48.0000 / 48.0000 | 53 / 53 | 0 | no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `source_retrieval_metrics` | 64 | 40 | 18.0000 / 37.2000 | 53 / 53 | 0 | no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `merged_document_metrics` | 64 | 40 | 53.0000 / 64.0000 | 53 / 53 | 0 | no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `resolved_document_metrics` | 64 | 40 | 53.0000 / 64.0000 | 53 / 53 | 0 | no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `structural_chunk_metrics` | 64 | 40 | 53.0000 / 64.0000 | 53 / 53 | 1 | no_applicable_gold=160, no_verified_gold_label=140 |
| `local_selection_metrics` | N/A | 40 | 53.0000 / 64.0000 | 53 / 53 | 0 | configured_capacity_unknown=440, no_applicable_gold=40, no_verified_gold_label=140 |
| `reranker_input_metrics` | 64 | 40 | 53.0000 / 64.0000 | 53 / 53 | 0 | no_applicable_gold=160, no_verified_gold_label=140 |
| `reranker_output_metrics` | 6 | 40 | 6.0000 / 6.0000 | 53 / 53 | 0 | k_exceeds_configured_capacity=80, no_applicable_gold=160, no_verified_gold_label=140 |
| `final_evidence_metrics` | 5 | 40 | 5.0000 / 5.0000 | 52 / 53 | 1 | k_exceeds_configured_capacity=160, no_applicable_gold=120, no_verified_gold_label=140 |

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
| `token_f1` | 0.1984 |
| `char_f1` | 0.1912 |
| `rouge_l` | 0.1887 |
| `chrf` | 0.3321 |
| `citation_precision` | 0.1667 |
| `invalid_citation_rate` | 0.8333 |

## 6. Generation, guardrail, and judge coverage

Generation STOP / total: `50 / 50`
Input safe / total: `50 / 50`
Output safe / total: `50 / 50`
Ragas scored / eligible: `47 / 50`
Judge technical errors: `3`

| Ragas metric | Mean | Scored cases |
| :--- | ---: | ---: |
| `faithfulness` | 0.8592 | 47 |
| `answer_accuracy` | 0.8830 | 47 |
| `context_precision` | 0.8649 | 47 |
| `context_recall` | 0.9184 | 47 |

## 7. Latency

| Stage | P50 (s) | P95 (s) | Mean (s) |
| :--- | ---: | ---: | ---: |
| `t_input_guardrail` | 1.1178 | 1.3924 | 1.1415 |
| `t_output_guardrail` | 1.1926 | 1.5242 | 1.2397 |
| `t_retrieval` | 2.5389 | 5.6923 | 3.3394 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 8.6182 | 12.0751 | 9.5203 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_017` | `ok` | `STOP` | `yes` | `none` | 14.5521 |
| `case_019` | `ok` | `STOP` | `yes` | `none` | 11.7637 |
| `case_021` | `ok` | `STOP` | `no` | `judge` | 7.6913 |
| `case_031` | `ok` | `STOP` | `no` | `judge` | 8.1006 |
| `case_036` | `ok` | `STOP` | `yes` | `none` | 12.3299 |
| `case_039` | `ok` | `STOP` | `yes` | `none` | 7.4786 |
| `case_043` | `ok` | `STOP` | `yes` | `none` | 9.2171 |
| `case_061` | `ok` | `STOP` | `yes` | `none` | 8.1935 |
| `case_065` | `ok` | `STOP` | `yes` | `none` | 8.0310 |
| `case_069` | `ok` | `STOP` | `yes` | `none` | 7.7464 |
| `case_075` | `ok` | `STOP` | `yes` | `none` | 8.6737 |
| `case_101` | `ok` | `STOP` | `yes` | `none` | 8.4298 |
| `case_105` | `ok` | `STOP` | `yes` | `none` | 6.7071 |
| `case_115` | `ok` | `STOP` | `yes` | `none` | 6.9705 |
| `case_116` | `ok` | `STOP` | `yes` | `none` | 8.4900 |
| `case_121` | `ok` | `STOP` | `yes` | `none` | 7.4625 |
| `case_127` | `ok` | `STOP` | `yes` | `none` | 7.5581 |
| `case_133` | `ok` | `STOP` | `yes` | `none` | 8.3942 |
| `case_135` | `ok` | `STOP` | `yes` | `none` | 9.0310 |
| `case_165` | `ok` | `STOP` | `yes` | `none` | 7.6591 |
| `case_171` | `ok` | `STOP` | `yes` | `none` | 7.8951 |
| `case_177` | `ok` | `STOP` | `yes` | `none` | 7.2235 |
| `case_183` | `ok` | `STOP` | `no` | `judge` | 10.4840 |
| `case_187` | `ok` | `STOP` | `yes` | `none` | 10.7261 |
| `case_194` | `ok` | `STOP` | `yes` | `none` | 10.3663 |
| `case_204` | `ok` | `STOP` | `yes` | `none` | 8.5369 |
| `case_227` | `ok` | `STOP` | `yes` | `none` | 10.7144 |
| `case_243` | `ok` | `STOP` | `yes` | `none` | 7.8602 |
| `case_253` | `ok` | `STOP` | `yes` | `none` | 9.7587 |
| `case_257` | `ok` | `STOP` | `yes` | `none` | 10.0364 |
| `case_261` | `ok` | `STOP` | `yes` | `none` | 8.6583 |
| `case_263` | `ok` | `STOP` | `yes` | `none` | 8.6162 |
| `case_285` | `ok` | `STOP` | `yes` | `none` | 8.5689 |
| `case_309` | `ok` | `STOP` | `yes` | `none` | 10.0575 |
| `case_323` | `ok` | `STOP` | `yes` | `none` | 8.9126 |
| `case_325` | `ok` | `STOP` | `yes` | `retrieval_fallback` | 32.7795 |
| `case_329` | `ok` | `STOP` | `yes` | `none` | 8.6202 |
| `case_331` | `ok` | `STOP` | `yes` | `none` | 8.5810 |
| `case_339` | `ok` | `STOP` | `yes` | `none` | 9.4095 |
| `case_355` | `ok` | `STOP` | `yes` | `none` | 9.5305 |
| `case_361` | `ok` | `STOP` | `yes` | `none` | 7.3155 |
| `case_362` | `ok` | `STOP` | `yes` | `none` | 8.2269 |
| `case_371` | `ok` | `STOP` | `yes` | `none` | 10.4271 |
| `case_374` | `ok` | `STOP` | `yes` | `none` | 8.1674 |
| `case_375` | `ok` | `STOP` | `yes` | `none` | 10.4477 |
| `case_379` | `ok` | `STOP` | `yes` | `none` | 10.4923 |
| `case_397` | `ok` | `STOP` | `yes` | `none` | 11.6953 |
| `case_411` | `ok` | `STOP` | `yes` | `none` | 8.5133 |
| `case_415` | `ok` | `STOP` | `yes` | `none` | 9.8537 |
| `case_417` | `ok` | `STOP` | `yes` | `none` | 9.0608 |