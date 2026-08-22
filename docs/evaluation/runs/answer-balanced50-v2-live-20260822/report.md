# VIETLEX EVALUATION REPORT — answer-balanced50-v2-live-20260822

**Run ID**: `answer-balanced50-v2-live-20260822`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-08-22T14:59:05.151642+00:00`  
**Git Commit SHA**: `6dd558c3e163941690eb9a75490c886a898d52d5`  
**Source State SHA-256**: `19a37f4d7f58ec97e1d55fd588c4e8329bcc881e9adb14c69cf2645c33ba6fcc`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `5e2b7b9ca9bc60956712cc84ac2aebe6abb3ece69ca7b7970de800ecc813be71`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `b458880e2c2fc4f2813965d57dc96517555488a5ada3702da12fb811f05fb90b`  
**Configuration Fingerprint**: `6258116451b71681ab6b0fe84d66d2667f92a51e9888eafdbd3d594b6bc68c4d`  
**Execution Command**: `run_answer_eval.py --case-ids case_017 case_019 case_021 case_031 case_036 case_039 case_043 case_061 case_065 case_069 case_075 case_101 case_105 case_115 case_116 case_121 case_127 case_133 case_135 case_165 case_171 case_177 case_183 case_187 case_194 case_204 case_227 case_243 case_253 case_257 case_261 case_263 case_285 case_309 case_323 case_325 case_329 case_331 case_339 case_355 case_361 case_362 case_371 case_374 case_375 case_379 case_397 case_411 case_415 case_417 --gold-policy none --profile separated_intent --rewrite off --guardrails enforce --reranker current --concurrency 1 --judge ragas --run-id answer-balanced50-v2-live-20260822`  
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
| `source_retrieval_metrics` | 64 | 40 | 17.5000 / 37.2000 | 53 / 53 | 0 | no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
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
| `token_f1` | 0.1961 |
| `char_f1` | 0.1890 |
| `rouge_l` | 0.1863 |
| `chrf` | 0.3280 |
| `citation_precision` | 0.1667 |
| `invalid_citation_rate` | 0.8333 |

## 6. Generation, guardrail, and judge coverage

Generation STOP / total: `50 / 50`
Input safe / total: `50 / 50`
Output safe / total: `50 / 50`
Ragas scored / eligible: `50 / 50`
Judge technical errors: `0`

| Ragas metric | Mean | Scored cases |
| :--- | ---: | ---: |
| `faithfulness` | 0.9158 | 50 |
| `answer_accuracy` | 0.8950 | 50 |
| `context_precision` | 0.8757 | 50 |
| `context_recall` | 0.9333 | 50 |

## 7. Latency

| Stage | P50 (s) | P95 (s) | Mean (s) |
| :--- | ---: | ---: | ---: |
| `t_input_guardrail` | 1.0079 | 1.2076 | 1.0238 |
| `t_output_guardrail` | 1.0619 | 1.3249 | 1.0894 |
| `t_retrieval` | 2.2153 | 3.3337 | 2.4198 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 7.9802 | 10.1376 | 8.1963 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_017` | `ok` | `STOP` | `yes` | `none` | 7.9829 |
| `case_019` | `ok` | `STOP` | `yes` | `none` | 7.3104 |
| `case_021` | `ok` | `STOP` | `yes` | `none` | 7.9357 |
| `case_031` | `ok` | `STOP` | `yes` | `none` | 6.9718 |
| `case_036` | `ok` | `STOP` | `yes` | `none` | 8.7835 |
| `case_039` | `ok` | `STOP` | `yes` | `none` | 6.4635 |
| `case_043` | `ok` | `STOP` | `yes` | `none` | 7.8952 |
| `case_061` | `ok` | `STOP` | `yes` | `none` | 7.2765 |
| `case_065` | `ok` | `STOP` | `yes` | `none` | 6.8463 |
| `case_069` | `ok` | `STOP` | `yes` | `none` | 7.0998 |
| `case_075` | `ok` | `STOP` | `yes` | `none` | 7.9775 |
| `case_101` | `ok` | `STOP` | `yes` | `none` | 7.4136 |
| `case_105` | `ok` | `STOP` | `yes` | `none` | 7.0742 |
| `case_115` | `ok` | `STOP` | `yes` | `none` | 7.0047 |
| `case_116` | `ok` | `STOP` | `yes` | `none` | 7.8447 |
| `case_121` | `ok` | `STOP` | `yes` | `none` | 6.8910 |
| `case_127` | `ok` | `STOP` | `yes` | `none` | 6.5066 |
| `case_133` | `ok` | `STOP` | `yes` | `none` | 7.5456 |
| `case_135` | `ok` | `STOP` | `yes` | `none` | 9.5676 |
| `case_165` | `ok` | `STOP` | `yes` | `none` | 7.4449 |
| `case_171` | `ok` | `STOP` | `yes` | `none` | 9.2605 |
| `case_177` | `ok` | `STOP` | `yes` | `none` | 8.2250 |
| `case_183` | `ok` | `STOP` | `yes` | `none` | 13.7325 |
| `case_187` | `ok` | `STOP` | `yes` | `none` | 7.5124 |
| `case_194` | `ok` | `STOP` | `yes` | `none` | 10.1154 |
| `case_204` | `ok` | `STOP` | `yes` | `none` | 8.0862 |
| `case_227` | `ok` | `STOP` | `yes` | `none` | 9.6527 |
| `case_243` | `ok` | `STOP` | `yes` | `none` | 8.0844 |
| `case_253` | `ok` | `STOP` | `yes` | `none` | 8.8251 |
| `case_257` | `ok` | `STOP` | `yes` | `none` | 9.4868 |
| `case_261` | `ok` | `STOP` | `yes` | `none` | 7.1462 |
| `case_263` | `ok` | `STOP` | `yes` | `none` | 8.3855 |
| `case_285` | `ok` | `STOP` | `yes` | `none` | 8.7396 |
| `case_309` | `ok` | `STOP` | `yes` | `none` | 9.9644 |
| `case_323` | `ok` | `STOP` | `yes` | `none` | 6.9478 |
| `case_325` | `ok` | `STOP` | `yes` | `none` | 7.1479 |
| `case_329` | `ok` | `STOP` | `yes` | `none` | 8.1842 |
| `case_331` | `ok` | `STOP` | `yes` | `none` | 7.6165 |
| `case_339` | `ok` | `STOP` | `yes` | `none` | 9.1154 |
| `case_355` | `ok` | `STOP` | `yes` | `none` | 8.0080 |
| `case_361` | `ok` | `STOP` | `yes` | `none` | 8.2472 |
| `case_362` | `ok` | `STOP` | `yes` | `none` | 6.8203 |
| `case_371` | `ok` | `STOP` | `yes` | `none` | 8.7092 |
| `case_374` | `ok` | `STOP` | `yes` | `none` | 7.6576 |
| `case_375` | `ok` | `STOP` | `yes` | `none` | 8.5064 |
| `case_379` | `ok` | `STOP` | `yes` | `none` | 10.1558 |
| `case_397` | `ok` | `STOP` | `yes` | `none` | 10.9326 |
| `case_411` | `ok` | `STOP` | `yes` | `none` | 8.6740 |
| `case_415` | `ok` | `STOP` | `yes` | `none` | 8.3673 |
| `case_417` | `ok` | `STOP` | `yes` | `none` | 7.6729 |