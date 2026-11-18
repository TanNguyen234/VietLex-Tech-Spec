# VIETLEX EVALUATION REPORT — answer-golden50-v4-curated-20261118

**Run ID**: `answer-golden50-v4-curated-20261118`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-11-18T06:37:56.755639+00:00`  
**Git Commit SHA**: `431003ace17e15c7b7bf3443b1d78c261840dc2b`  
**Source State SHA-256**: `a9d6887ad5caf9719f00eb0cc11033cfcb1102972463641c72ffdcbf0caf6f80`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `298fea2628ab0602295776910d06d246bd1946e1490a89fd2b1756539ef8d3ce`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `caa3fc19cd22bcce4b87e96adf13544d0c3cc174cca2d0e365a848e0da9a981f`  
**Configuration Fingerprint**: `2aa34fa98601879ccdaba388e9dcaba5d5dc95515a82bdaa302156ac37f837cd`  
**Execution Command**: `run_answer_eval.py --dataset docs/evaluation/golden50-v3/cases.json --sidecar docs/evaluation/golden50-v3/labels.json --backend production --ranking rrf-dbsf --profile separated_intent --rewrite off --guardrails enforce --reranker current --concurrency 2 --gold-policy none --judge none --run-id answer-golden50-v4-curated-20261118`  
**Evaluation Mode**: `answer` | **Judge**: `none` | **Guardrails**: `enforce`  

Metric schema: `3.0.0`
Answer metric version: `3.3.0`
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
| Document Recall @ 1 | 0.7750 | 0.7736 | 41.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 3 | 0.9250 | 0.9245 | 49.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 5 | 0.9250 | 0.9245 | 49.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 10 | 0.9750 | 0.9623 | 51.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 24 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Article Recall @ 1 | 0.6667 | 0.6667 | 20.0000/30.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Article Recall @ 3 | 0.9259 | 0.9333 | 28.0000/30.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 50 | k_exceeds_configured_capacity=40, no_verified_gold_label=10 |
| Clause Recall @ 1 | 0.0000 | 0.0000 | 0.0000/14.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Clause Recall @ 3 | 0.1538 | 0.1429 | 2.0000/14.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 50 | k_exceeds_configured_capacity=40, no_verified_gold_label=10 |
| Article MRR | 0.8086 | 0.8086 | 21.8333/27.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Clause MRR | 0.0513 | 0.0513 | 0.6667/13.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Document MRR | 0.8583 | 0.8583 | 34.3304/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| nDCG @ 10 | 0.6038 | 0.6026 | 29.0474/48.2021 | 40 / 10 | no_verified_gold_label=10 |
| Exact legal-reference hit | 0.7250 | 0.7250 | 29.0000/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| Multi-hop all-required coverage | 0.6500 | 0.6500 | 26.0000/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| Multi-hop partial coverage | 0.6875 | 0.6981 | 37.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |

## 3. Stage metrics

| Pipeline stage | Capacity | Scored cases | Candidate p50 / p95 | Matched / Applicable documents | First-loss evidence count | Null reasons |
| :--- | ---: | ---: | :---: | :---: | ---: | :--- |
| `pinecone_document_metrics` | N/A | 40 | 0.0000 / 0.0000 | 0 / 53 | 0 | configured_capacity_unknown=200, no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `fts_document_metrics` | N/A | 40 | 0.0000 / 0.0000 | 0 / 53 | 0 | configured_capacity_unknown=200, no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `source_retrieval_metrics` | 24 | 40 | 24.0000 / 24.0000 | 53 / 53 | 0 | no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `merged_document_metrics` | 24 | 40 | 0.0000 / 0.0000 | 0 / 53 | 53 | no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `resolved_document_metrics` | 24 | 40 | 0.0000 / 0.0000 | 0 / 53 | 0 | no_verified_gold_label=140, stage_does_not_expose_structural_locators=320 |
| `structural_chunk_metrics` | 24 | 40 | 24.0000 / 24.0000 | 53 / 53 | 0 | no_applicable_gold=160, no_verified_gold_label=140 |
| `local_selection_metrics` | N/A | 40 | 0.0000 / 1.0000 | 8 / 53 | 0 | configured_capacity_unknown=440, no_applicable_gold=40, no_verified_gold_label=140 |
| `reranker_input_metrics` | 24 | 40 | 24.0000 / 24.0000 | 53 / 53 | 0 | no_applicable_gold=160, no_verified_gold_label=140 |
| `reranker_output_metrics` | 3 | 40 | 3.0000 / 3.0000 | 49 / 53 | 0 | k_exceeds_configured_capacity=200, no_applicable_gold=120, no_verified_gold_label=140 |
| `final_evidence_metrics` | 3 | 40 | 3.0000 / 3.0000 | 49 / 53 | 0 | k_exceeds_configured_capacity=200, no_applicable_gold=120, no_verified_gold_label=140 |

## 4. Interpretation notes

- Recall@K is undefined when K exceeds the configured stage capacity; nDCG@10 still treats unreturned ranks as zero gain so capacity effects remain measurable.
- Configured provider candidates are provenance only; they do not prove which provider answered a request.

## 5. Deterministic answer metrics

Answer scored / total: `49 / 50`
Answer skip reasons: `output_guardrail_error=1`

| Metric | Value | Aggregation | Numerator | Denominator | Coverage | Scored / Skipped | Skip reasons | Reason |
| :--- | ---: | :--- | ---: | ---: | ---: | ---: | :--- | :--- |
| `exact_match` | 0.0000 | macro_case_mean | 0.000000 | 49 | 98.0% | 49 / 1 | output_guardrail_error=1 | N/A |
| `token_precision` | 0.1155 | macro_case_mean | 5.657300 | 49 | 98.0% | 49 / 1 | output_guardrail_error=1 | N/A |
| `token_recall` | 0.7281 | macro_case_mean | 35.676900 | 49 | 98.0% | 49 / 1 | output_guardrail_error=1 | N/A |
| `token_f1` | 0.1915 | macro_case_mean | 9.383700 | 49 | 98.0% | 49 / 1 | output_guardrail_error=1 | N/A |
| `char_f1` | 0.2112 | macro_case_mean | 10.349200 | 49 | 98.0% | 49 / 1 | output_guardrail_error=1 | N/A |
| `rouge_l` | 0.1572 | macro_case_mean | 7.704800 | 49 | 98.0% | 49 / 1 | output_guardrail_error=1 | N/A |
| `chrf` | 0.3063 | macro_case_mean | 15.007300 | 49 | 98.0% | 49 / 1 | output_guardrail_error=1 | N/A |
| `number_precision` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_numbers=49, output_guardrail_error=1 | no_applicable_values |
| `number_recall` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_numbers=49, output_guardrail_error=1 | no_applicable_values |
| `date_precision` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_dates=49, output_guardrail_error=1 | no_applicable_values |
| `date_recall` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_dates=49, output_guardrail_error=1 | no_applicable_values |
| `entity_precision` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_entities=49, output_guardrail_error=1 | no_applicable_values |
| `entity_recall` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_entities=49, output_guardrail_error=1 | no_applicable_values |
| `citation_precision` | 0.7262 | macro_case_mean | 35.583300 | 49 | 98.0% | 49 / 1 | output_guardrail_error=1 | N/A |
| `citation_recall` | 0.0000 | macro_case_mean | 0.000000 | 1 | 2.0% | 1 / 49 | no_reference_citations=48, output_guardrail_error=1 | N/A |
| `citation_coverage` | 0.0000 | macro_case_mean | 0.000000 | 1 | 2.0% | 1 / 49 | no_reference_citations=48, output_guardrail_error=1 | N/A |
| `invalid_citation_rate` | 0.0493 | macro_case_mean | 2.416700 | 49 | 98.0% | 49 / 1 | output_guardrail_error=1 | N/A |
| `answer_similarity_pass_rate` | 0.0204 | case_count_ratio | 1.000000 | 49 | 98.0% | 49 / 1 | output_guardrail_error=1 | N/A |
| `unanswerable_accuracy` | N/A | case_count_ratio | 0.000000 | 0 | 0.0% | 0 / 50 | answerable_case=49, output_guardrail_error=1 | no_unanswerable_cases |
| `refusal_precision` | N/A | case_count_ratio | 0.000000 | 0 | 0.0% | 0 / 50 | not_predicted_refusal=49, output_guardrail_error=1 | no_predicted_refusals |
| `refusal_recall` | N/A | case_count_ratio | 0.000000 | 0 | 0.0% | 0 / 50 | answerable_case=49, output_guardrail_error=1 | no_unanswerable_cases |
| `mixed_claim_refusal_rate` | 0.5714 | case_count_ratio | 28.000000 | 49 | 98.0% | 49 / 1 | output_guardrail_error=1 | N/A |

## 6. Generation, guardrail, and judge coverage

Generation STOP / total: `50 / 50`
Input safe / total: `50 / 50`
Output safe / total: `49 / 50`
Ragas scored / eligible: `0 / 49`
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
| `t_evidence_fallback` | 2.9275 | 14.8434 | 4.1703 |
| `t_input_guardrail` | 0.9229 | 3.0145 | 1.2978 |
| `t_llm` | 2.3755 | 7.2836 | 3.5351 |
| `t_output_guardrail` | 0.9626 | 2.7347 | 1.2428 |
| `t_retrieval` | 2.5170 | 6.5725 | 2.9832 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 10.4085 | 31.8900 | 13.2357 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_001` | `ok` | `STOP` | `no` | `none` | 15.9422 |
| `case_002` | `ok` | `STOP` | `no` | `none` | 13.1991 |
| `case_003` | `ok` | `STOP` | `no` | `none` | 8.8838 |
| `case_004` | `ok` | `STOP` | `no` | `none` | 9.3713 |
| `case_005` | `ok` | `STOP` | `no` | `none` | 15.9932 |
| `case_006` | `ok` | `STOP` | `no` | `none` | 17.2915 |
| `case_007` | `ok` | `STOP` | `no` | `none` | 12.0158 |
| `case_008` | `ok` | `STOP` | `no` | `none` | 10.8111 |
| `case_009` | `ok` | `STOP` | `no` | `none` | 12.4625 |
| `case_010` | `ok` | `STOP` | `no` | `none` | 11.4022 |
| `case_011` | `ok` | `STOP` | `no` | `none` | 9.8942 |
| `case_012` | `ok` | `STOP` | `no` | `none` | 9.8047 |
| `case_013` | `ok` | `STOP` | `no` | `none` | 10.3379 |
| `case_014` | `ok` | `STOP` | `no` | `none` | 8.5060 |
| `case_015` | `ok` | `STOP` | `no` | `none` | 35.0272 |
| `case_016` | `ok` | `STOP` | `no` | `none` | 14.0010 |
| `case_017` | `ok` | `STOP` | `no` | `none` | 15.7435 |
| `case_018` | `ok` | `STOP` | `no` | `none` | 9.6005 |
| `case_019` | `ok` | `STOP` | `no` | `none` | 10.3102 |
| `case_020` | `ok` | `STOP` | `no` | `none` | 7.4803 |
| `case_021` | `ok` | `STOP` | `no` | `none` | 9.1510 |
| `case_022` | `ok` | `STOP` | `no` | `none` | 7.7070 |
| `case_023` | `ok` | `STOP` | `no` | `none` | 9.1569 |
| `case_024` | `ok` | `STOP` | `no` | `none` | 8.0271 |
| `case_025` | `ok` | `STOP` | `no` | `none` | 8.3851 |
| `case_026` | `ok` | `STOP` | `no` | `none` | 12.1363 |
| `case_027` | `ok` | `STOP` | `no` | `none` | 9.0404 |
| `case_028` | `ok` | `STOP` | `no` | `none` | 11.6666 |
| `case_029` | `ok` | `STOP` | `no` | `none` | 11.5749 |
| `case_030` | `ok` | `STOP` | `no` | `none` | 11.5108 |
| `case_031` | `ok` | `STOP` | `no` | `none` | 7.9602 |
| `case_032` | `ok` | `STOP` | `no` | `none` | 9.0429 |
| `case_033` | `ok` | `STOP` | `no` | `none` | 9.2373 |
| `case_034` | `ok` | `STOP` | `no` | `none` | 13.2242 |
| `case_035` | `ok` | `STOP` | `no` | `none` | 50.8271 |
| `case_036` | `ok` | `STOP` | `no` | `none` | 8.7524 |
| `case_037` | `ok` | `STOP` | `no` | `none` | 9.6246 |
| `case_038` | `ok` | `STOP` | `no` | `none` | 36.8946 |
| `case_039` | `ok` | `STOP` | `no` | `none` | 14.3562 |
| `case_040` | `ok` | `STOP` | `no` | `none` | 7.4251 |
| `case_041` | `ok` | `STOP` | `no` | `none` | 8.2391 |
| `case_042` | `ok` | `STOP` | `no` | `none` | 28.0556 |
| `case_043` | `ok` | `STOP` | `no` | `none` | 9.2710 |
| `case_044` | `ok` | `STOP` | `no` | `none` | 14.2940 |
| `case_045` | `ok` | `STOP` | `no` | `none` | 14.6580 |
| `case_046` | `ok` | `STOP` | `no` | `none` | 9.9597 |
| `case_047` | `ok` | `STOP` | `no` | `none` | 9.9614 |
| `case_048` | `ok` | `STOP` | `no` | `none` | 19.2233 |
| `case_049` | `ok` | `STOP` | `no` | `none` | 10.4791 |
| `case_050` | `output_guardrail_error` | `STOP` | `no` | `output_guardrail` | 13.8646 |