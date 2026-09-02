# VIETLEX EVALUATION REPORT — retrieval-v3-golden50-online-vercel-20260901

**Run ID**: `retrieval-v3-golden50-online-vercel-20260901`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-09-01T13:19:01.500782+00:00`  
**Git Commit SHA**: `c5fa8121d3080ac401d5a79e1beedaa1ffa2241f`  
**Source State SHA-256**: `7fb04d6a3b5ae33eb0b77f95ed31789ba75a5c5bf073ab7e10a874cdfb62f252`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `2cbc7eef45a4370ea505ce7336d519a0872f893d5e40590f739811db58a22431`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `caa3fc19cd22bcce4b87e96adf13544d0c3cc174cca2d0e365a848e0da9a981f`  
**Configuration Fingerprint**: `f4ab971f160537e71e0eb2ba8dce784b07904e8553452fab0dcb3ea40f72d87f`  
**Execution Command**: `run_retrieval_eval.py --dataset docs/evaluation/golden50-v3/cases.json --sidecar docs/evaluation/golden50-v3/labels.json --backend vertex-qdrant-v3 --ranking raw-rrf --profile separated_intent --rewrite off --reranker current --concurrency 1 --gold-policy none --run-id retrieval-v3-golden50-online-vercel-20260901`  
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
| Document Recall @ 1 | 0.9500 | 0.9245 | 49.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 3 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 5 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 10 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 24 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Article Recall @ 1 | 0.7778 | 0.7667 | 23.0000/30.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Article Recall @ 3 | 1.0000 | 1.0000 | 30.0000/30.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 50 | k_exceeds_configured_capacity=40, no_verified_gold_label=10 |
| Clause Recall @ 1 | 0.6538 | 0.6429 | 9.0000/14.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Clause Recall @ 3 | 0.9231 | 0.9286 | 13.0000/14.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 50 | k_exceeds_configured_capacity=40, no_verified_gold_label=10 |
| Article MRR | 0.9074 | 0.9074 | 24.5000/27.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Clause MRR | 0.7949 | 0.7949 | 10.3333/13.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Document MRR | 0.9750 | 0.9750 | 39.0000/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| nDCG @ 10 | 0.9218 | 0.9007 | 43.4165/48.2021 | 40 / 10 | no_verified_gold_label=10 |
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
| `t_retrieval` | 0.6842 | 1.6051 | 0.9698 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 0.6842 | 1.6052 | 0.9698 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_001` | `ok` | `N/A` | `no` | `none` | 10.5741 |
| `case_002` | `ok` | `N/A` | `no` | `none` | 2.0776 |
| `case_003` | `ok` | `N/A` | `no` | `none` | 1.2766 |
| `case_004` | `ok` | `N/A` | `no` | `none` | 1.2114 |
| `case_005` | `ok` | `N/A` | `no` | `none` | 0.6857 |
| `case_006` | `ok` | `N/A` | `no` | `none` | 0.8745 |
| `case_007` | `ok` | `N/A` | `no` | `none` | 0.6559 |
| `case_008` | `ok` | `N/A` | `no` | `none` | 0.8387 |
| `case_009` | `ok` | `N/A` | `no` | `none` | 0.9266 |
| `case_010` | `ok` | `N/A` | `no` | `none` | 0.6668 |
| `case_011` | `ok` | `N/A` | `no` | `none` | 0.9178 |
| `case_012` | `ok` | `N/A` | `no` | `none` | 0.7042 |
| `case_013` | `ok` | `N/A` | `no` | `none` | 0.6295 |
| `case_014` | `ok` | `N/A` | `no` | `none` | 0.7008 |
| `case_015` | `ok` | `N/A` | `no` | `none` | 0.6525 |
| `case_016` | `ok` | `N/A` | `no` | `none` | 0.6619 |
| `case_017` | `ok` | `N/A` | `no` | `none` | 0.7081 |
| `case_018` | `ok` | `N/A` | `no` | `none` | 0.6803 |
| `case_019` | `ok` | `N/A` | `no` | `none` | 0.6163 |
| `case_020` | `ok` | `N/A` | `no` | `none` | 0.6425 |
| `case_021` | `ok` | `N/A` | `no` | `none` | 0.7051 |
| `case_022` | `ok` | `N/A` | `no` | `none` | 0.6399 |
| `case_023` | `ok` | `N/A` | `no` | `none` | 0.9247 |
| `case_024` | `ok` | `N/A` | `no` | `none` | 0.8751 |
| `case_025` | `ok` | `N/A` | `no` | `none` | 0.6774 |
| `case_026` | `ok` | `N/A` | `no` | `none` | 0.6453 |
| `case_027` | `ok` | `N/A` | `no` | `none` | 0.6745 |
| `case_028` | `ok` | `N/A` | `no` | `none` | 0.6883 |
| `case_029` | `ok` | `N/A` | `no` | `none` | 0.6958 |
| `case_030` | `ok` | `N/A` | `no` | `none` | 0.6409 |
| `case_031` | `ok` | `N/A` | `no` | `none` | 0.6291 |
| `case_032` | `ok` | `N/A` | `no` | `none` | 0.6457 |
| `case_033` | `ok` | `N/A` | `no` | `none` | 0.6826 |
| `case_034` | `ok` | `N/A` | `no` | `none` | 0.6865 |
| `case_035` | `ok` | `N/A` | `no` | `none` | 0.6203 |
| `case_036` | `ok` | `N/A` | `no` | `none` | 0.6661 |
| `case_037` | `ok` | `N/A` | `no` | `none` | 0.6506 |
| `case_038` | `ok` | `N/A` | `no` | `none` | 0.7321 |
| `case_039` | `ok` | `N/A` | `no` | `none` | 0.6881 |
| `case_040` | `ok` | `N/A` | `no` | `none` | 0.6882 |
| `case_041` | `ok` | `N/A` | `no` | `none` | 1.8740 |
| `case_042` | `ok` | `N/A` | `no` | `none` | 0.6698 |
| `case_043` | `ok` | `N/A` | `no` | `none` | 0.6268 |
| `case_044` | `ok` | `N/A` | `no` | `none` | 0.6347 |
| `case_045` | `ok` | `N/A` | `no` | `none` | 0.6255 |
| `case_046` | `ok` | `N/A` | `no` | `none` | 0.8439 |
| `case_047` | `ok` | `N/A` | `no` | `none` | 0.6415 |
| `case_048` | `ok` | `N/A` | `no` | `none` | 0.6300 |
| `case_049` | `ok` | `N/A` | `no` | `none` | 0.6910 |
| `case_050` | `ok` | `N/A` | `no` | `none` | 0.6938 |