# VIETLEX EVALUATION REPORT — answer-golden50-production-enforce-20261103-82280547

**Run ID**: `answer-golden50-production-enforce-20261103-82280547`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-11-03T09:36:51.519044+00:00`  
**Git Commit SHA**: `7519cd1aea4a3639140b9188de1843ebf0ddb1c0`  
**Source State SHA-256**: `b80e52534d9ed4c68fd694666b1ba92553dab3d361e5a6214713d1af8935f70b`  
**Git Dirty Status**: `True` (Diff: `redacted`, SHA-256: `N/A`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `caa3fc19cd22bcce4b87e96adf13544d0c3cc174cca2d0e365a848e0da9a981f`  
**Configuration Fingerprint**: `ae2ced3166fcae95f0dac4e6d7028f2c0535974f7ddb2930eb2e483a322da82a`  
**Execution Command**: `run_answer_eval.py --dataset docs/evaluation/golden50-v3/cases.json --sidecar docs/evaluation/golden50-v3/labels.json --backend production --ranking rrf-dbsf --profile separated_intent --rewrite off --guardrails enforce --reranker current --concurrency 2 --gold-policy none --judge none --run-id answer-golden50-production-enforce-20261103-82280547`  
**Evaluation Mode**: `answer` | **Judge**: `none` | **Guardrails**: `enforce`  

Metric schema: `3.0.0`
Answer metric version: `3.1.0`
Answer pipeline: `chat_service_v1`
Runtime environment: `{'app_env': 'development', 'serverless_online_only': True}`
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
| Document Recall @ 1 | 0.9000 | 0.8679 | 46.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 3 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 5 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 10 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 24 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Article Recall @ 1 | 0.8148 | 0.8000 | 24.0000/30.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Article Recall @ 3 | 0.9815 | 0.9667 | 29.0000/30.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 50 | k_exceeds_configured_capacity=40, no_verified_gold_label=10 |
| Clause Recall @ 1 | 0.6538 | 0.6429 | 9.0000/14.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Clause Recall @ 3 | 0.9231 | 0.9286 | 13.0000/14.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 50 | k_exceeds_configured_capacity=40, no_verified_gold_label=10 |
| Article MRR | 0.9198 | 0.9198 | 24.8333/27.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Clause MRR | 0.7949 | 0.7949 | 10.3333/13.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Document MRR | 0.9500 | 0.9500 | 38.0000/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| nDCG @ 10 | 0.8852 | 0.8674 | 41.8093/48.2021 | 40 / 10 | no_verified_gold_label=10 |
| Exact legal-reference hit | 0.9750 | 0.9750 | 39.0000/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| Multi-hop all-required coverage | 0.9500 | 0.9500 | 38.0000/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| Multi-hop partial coverage | 0.9625 | 0.9623 | 51.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |

## 3. Stage metrics

| Pipeline stage | Capacity | Scored cases | Candidate p50 / p95 | Matched / Applicable documents | First-loss evidence count | Null reasons |
| :--- | ---: | ---: | :---: | :---: | ---: | :--- |
| `pinecone_document_metrics` | N/A | 40 | 0.0000 / 0.0000 | 0 / 53 | 0 | configured_capacity_unknown=200, no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `fts_document_metrics` | N/A | 40 | 0.0000 / 0.0000 | 0 / 53 | 0 | configured_capacity_unknown=200, no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `source_retrieval_metrics` | 24 | 40 | 24.0000 / 24.0000 | 53 / 53 | 0 | no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `merged_document_metrics` | 24 | 40 | 0.0000 / 0.0000 | 0 / 53 | 53 | no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `resolved_document_metrics` | 24 | 40 | 0.0000 / 0.0000 | 0 / 53 | 0 | no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `structural_chunk_metrics` | 24 | 40 | 24.0000 / 24.0000 | 53 / 53 | 0 | no_applicable_gold=160, no_verified_gold_label=140 |
| `local_selection_metrics` | N/A | 40 | 0.0000 / 1.0000 | 17 / 53 | 0 | configured_capacity_unknown=440, no_applicable_gold=40, no_verified_gold_label=140 |
| `reranker_input_metrics` | 24 | 40 | 24.0000 / 24.0000 | 53 / 53 | 0 | no_applicable_gold=160, no_verified_gold_label=140 |
| `reranker_output_metrics` | 3 | 40 | 3.0000 / 3.0000 | 53 / 53 | 0 | k_exceeds_configured_capacity=200, no_applicable_gold=120, no_verified_gold_label=140 |
| `final_evidence_metrics` | 3 | 40 | 3.0000 / 3.0000 | 53 / 53 | 0 | k_exceeds_configured_capacity=200, no_applicable_gold=120, no_verified_gold_label=140 |

## 4. Interpretation notes

- Recall@K is undefined when K exceeds the configured stage capacity; nDCG@10 still treats unreturned ranks as zero gain so capacity effects remain measurable.
- Configured provider candidates are provenance only; they do not prove which provider answered a request.

## 5. Deterministic answer metrics

Answer scored / total: `50 / 50`
Answer skip reasons: `none`

| Metric | Value | Aggregation | Numerator | Denominator | Coverage | Scored / Skipped | Skip reasons | Reason |
| :--- | ---: | :--- | ---: | ---: | ---: | ---: | :--- | :--- |
| `exact_match` | 0.0000 | macro_case_mean | 0.000000 | 50 | 100.0% | 50 / 0 | none | N/A |
| `token_precision` | 0.1323 | macro_case_mean | 6.617100 | 50 | 100.0% | 50 / 0 | none | N/A |
| `token_recall` | 0.9347 | macro_case_mean | 46.736900 | 50 | 100.0% | 50 / 0 | none | N/A |
| `token_f1` | 0.2248 | macro_case_mean | 11.240200 | 50 | 100.0% | 50 / 0 | none | N/A |
| `char_f1` | 0.2244 | macro_case_mean | 11.221600 | 50 | 100.0% | 50 / 0 | none | N/A |
| `rouge_l` | 0.2143 | macro_case_mean | 10.716400 | 50 | 100.0% | 50 / 0 | none | N/A |
| `chrf` | 0.3749 | macro_case_mean | 18.743500 | 50 | 100.0% | 50 / 0 | none | N/A |
| `number_precision` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_numbers=50 | no_applicable_values |
| `number_recall` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_numbers=50 | no_applicable_values |
| `date_precision` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_dates=50 | no_applicable_values |
| `date_recall` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_dates=50 | no_applicable_values |
| `entity_precision` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_entities=50 | no_applicable_values |
| `entity_recall` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_entities=50 | no_applicable_values |
| `citation_precision` | 0.7872 | macro_case_mean | 37.783500 | 48 | 96.0% | 48 / 2 | no_retrieved_evidence_citations=2 | N/A |
| `citation_recall` | 1.0000 | macro_case_mean | 1.000000 | 1 | 2.0% | 1 / 49 | no_reference_citations=49 | N/A |
| `citation_coverage` | 1.0000 | macro_case_mean | 1.000000 | 1 | 2.0% | 1 / 49 | no_reference_citations=49 | N/A |
| `invalid_citation_rate` | 0.2128 | macro_case_mean | 10.216500 | 48 | 96.0% | 48 / 2 | no_retrieved_evidence_citations=2 | N/A |
| `answer_similarity_pass_rate` | 0.0200 | case_count_ratio | 1.000000 | 50 | 100.0% | 50 / 0 | none | N/A |
| `unanswerable_accuracy` | N/A | case_count_ratio | 0.000000 | 0 | 0.0% | 0 / 50 | answerable_case=50 | no_unanswerable_cases |
| `refusal_precision` | 0.0000 | case_count_ratio | 0.000000 | 2 | 4.0% | 2 / 48 | not_predicted_refusal=48 | N/A |
| `refusal_recall` | N/A | case_count_ratio | 0.000000 | 0 | 0.0% | 0 / 50 | answerable_case=50 | no_unanswerable_cases |
| `mixed_claim_refusal_rate` | 0.0000 | case_count_ratio | 0.000000 | 50 | 100.0% | 50 / 0 | none | N/A |

## 6. Generation, guardrail, and judge coverage

Generation STOP / total: `48 / 50`
Input safe / total: `50 / 50`
Output safe / total: `50 / 50`
Ragas scored / eligible: `0 / 48`
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
| `t_evidence_fallback` | 52.4285 | 56.0014 | 45.0309 |
| `t_input_guardrail` | 0.9964 | 2.5915 | 1.1789 |
| `t_llm` | 3.0065 | 5.3046 | 3.1528 |
| `t_output_guardrail` | 1.2256 | 2.0173 | 1.3605 |
| `t_retrieval` | 2.4755 | 6.7483 | 3.1795 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 59.7807 | 69.4692 | 53.9068 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_001` | `ok` | `STOP` | `no` | `none` | 69.2012 |
| `case_002` | `ok` | `STOP` | `no` | `none` | 33.8855 |
| `case_003` | `ok` | `STOP` | `no` | `none` | 58.5574 |
| `case_004` | `ok` | `STOP` | `no` | `none` | 60.0871 |
| `case_005` | `ok` | `STOP` | `no` | `none` | 70.6671 |
| `case_006` | `ok` | `STOP` | `no` | `none` | 60.2799 |
| `case_007` | `ok` | `STOP` | `no` | `none` | 10.1003 |
| `case_008` | `ok` | `STOP` | `no` | `none` | 11.5438 |
| `case_009` | `ok` | `STOP` | `no` | `none` | 15.3627 |
| `case_010` | `ok` | `STOP` | `no` | `none` | 61.3489 |
| `case_011` | `ok` | `STOP` | `no` | `none` | 63.6115 |
| `case_012` | `ok` | `STOP` | `no` | `none` | 58.5274 |
| `case_013` | `ok` | `N/A` | `no` | `none` | 12.2105 |
| `case_014` | `ok` | `STOP` | `no` | `none` | 58.9363 |
| `case_015` | `ok` | `STOP` | `no` | `none` | 59.0045 |
| `case_016` | `ok` | `STOP` | `no` | `none` | 59.7988 |
| `case_017` | `ok` | `STOP` | `no` | `none` | 64.6832 |
| `case_018` | `ok` | `STOP` | `no` | `none` | 60.1873 |
| `case_019` | `ok` | `STOP` | `no` | `none` | 59.9105 |
| `case_020` | `ok` | `STOP` | `no` | `none` | 57.7458 |
| `case_021` | `ok` | `STOP` | `no` | `none` | 13.7078 |
| `case_022` | `ok` | `STOP` | `no` | `none` | 58.0108 |
| `case_023` | `ok` | `STOP` | `no` | `none` | 64.3141 |
| `case_024` | `ok` | `STOP` | `no` | `none` | 59.2846 |
| `case_025` | `ok` | `STOP` | `no` | `none` | 56.5465 |
| `case_026` | `ok` | `STOP` | `no` | `none` | 59.4787 |
| `case_027` | `ok` | `STOP` | `no` | `none` | 59.2708 |
| `case_028` | `ok` | `STOP` | `no` | `none` | 59.7627 |
| `case_029` | `ok` | `STOP` | `no` | `none` | 69.6885 |
| `case_030` | `ok` | `STOP` | `no` | `none` | 63.1444 |
| `case_031` | `ok` | `STOP` | `no` | `none` | 63.5379 |
| `case_032` | `ok` | `STOP` | `no` | `none` | 65.5052 |
| `case_033` | `ok` | `STOP` | `no` | `none` | 67.1608 |
| `case_034` | `ok` | `STOP` | `no` | `none` | 70.2144 |
| `case_035` | `ok` | `N/A` | `no` | `none` | 65.3318 |
| `case_036` | `ok` | `STOP` | `no` | `none` | 66.9612 |
| `case_037` | `ok` | `STOP` | `no` | `none` | 64.4248 |
| `case_038` | `ok` | `STOP` | `no` | `none` | 58.5865 |
| `case_039` | `ok` | `STOP` | `no` | `none` | 65.0452 |
| `case_040` | `ok` | `STOP` | `no` | `none` | 67.5700 |
| `case_041` | `ok` | `STOP` | `no` | `none` | 57.8190 |
| `case_042` | `ok` | `STOP` | `no` | `none` | 61.3909 |
| `case_043` | `ok` | `STOP` | `no` | `none` | 62.4104 |
| `case_044` | `ok` | `STOP` | `no` | `none` | 12.0303 |
| `case_045` | `ok` | `STOP` | `no` | `none` | 56.0313 |
| `case_046` | `ok` | `STOP` | `no` | `none` | 60.2767 |
| `case_047` | `ok` | `STOP` | `no` | `none` | 55.3324 |
| `case_048` | `ok` | `STOP` | `no` | `none` | 58.8801 |
| `case_049` | `ok` | `STOP` | `no` | `none` | 10.6168 |
| `case_050` | `ok` | `STOP` | `no` | `none` | 37.3561 |