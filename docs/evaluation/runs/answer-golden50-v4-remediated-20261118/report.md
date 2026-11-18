# VIETLEX EVALUATION REPORT — answer-golden50-v4-remediated-20261118

**Run ID**: `answer-golden50-v4-remediated-20261118`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-11-18T07:24:52.953433+00:00`  
**Git Commit SHA**: `431003ace17e15c7b7bf3443b1d78c261840dc2b`  
**Source State SHA-256**: `5da63932a0d90075a5339504585e6b3f6cac27e6191aae7856a7b167b16fbefe`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `d9ac31ed1b66f389c4b9c26199d6d1238171ef2021a8175c658100ceda60a2f5`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `caa3fc19cd22bcce4b87e96adf13544d0c3cc174cca2d0e365a848e0da9a981f`  
**Configuration Fingerprint**: `2aa34fa98601879ccdaba388e9dcaba5d5dc95515a82bdaa302156ac37f837cd`  
**Execution Command**: `run_answer_eval.py --dataset docs/evaluation/golden50-v3/cases.json --sidecar docs/evaluation/golden50-v3/labels.json --backend production --ranking rrf-dbsf --profile separated_intent --rewrite off --guardrails enforce --reranker current --concurrency 2 --gold-policy none --judge none --run-id answer-golden50-v4-remediated-20261118`  
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
| Clause Recall @ 1 | 0.4231 | 0.4286 | 6.0000/14.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Clause Recall @ 3 | 0.6154 | 0.6429 | 9.0000/14.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 50 | k_exceeds_configured_capacity=40, no_verified_gold_label=10 |
| Article MRR | 0.8086 | 0.8086 | 21.8333/27.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Clause MRR | 0.5256 | 0.5256 | 6.8333/13.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Document MRR | 0.8583 | 0.8583 | 34.3304/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| nDCG @ 10 | 0.7321 | 0.7222 | 34.8093/48.2021 | 40 / 10 | no_verified_gold_label=10 |
| Exact legal-reference hit | 0.7250 | 0.7250 | 29.0000/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| Multi-hop all-required coverage | 0.8000 | 0.8000 | 32.0000/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| Multi-hop partial coverage | 0.8250 | 0.8302 | 44.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |

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

Answer scored / total: `50 / 50`
Answer skip reasons: `none`

| Metric | Value | Aggregation | Numerator | Denominator | Coverage | Scored / Skipped | Skip reasons | Reason |
| :--- | ---: | :--- | ---: | ---: | ---: | ---: | :--- | :--- |
| `exact_match` | 0.0000 | macro_case_mean | 0.000000 | 50 | 100.0% | 50 / 0 | none | N/A |
| `token_precision` | 0.1394 | macro_case_mean | 6.971800 | 50 | 100.0% | 50 / 0 | none | N/A |
| `token_recall` | 0.9721 | macro_case_mean | 48.607400 | 50 | 100.0% | 50 / 0 | none | N/A |
| `token_f1` | 0.2356 | macro_case_mean | 11.782000 | 50 | 100.0% | 50 / 0 | none | N/A |
| `char_f1` | 0.2321 | macro_case_mean | 11.603500 | 50 | 100.0% | 50 / 0 | none | N/A |
| `rouge_l` | 0.2226 | macro_case_mean | 11.129900 | 50 | 100.0% | 50 / 0 | none | N/A |
| `chrf` | 0.3865 | macro_case_mean | 19.326100 | 50 | 100.0% | 50 / 0 | none | N/A |
| `number_precision` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_numbers=50 | no_applicable_values |
| `number_recall` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_numbers=50 | no_applicable_values |
| `date_precision` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_dates=50 | no_applicable_values |
| `date_recall` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_dates=50 | no_applicable_values |
| `entity_precision` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_entities=50 | no_applicable_values |
| `entity_recall` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_entities=50 | no_applicable_values |
| `citation_precision` | 0.8560 | macro_case_mean | 42.800000 | 50 | 100.0% | 50 / 0 | none | N/A |
| `citation_recall` | 1.0000 | macro_case_mean | 1.000000 | 1 | 2.0% | 1 / 49 | no_reference_citations=49 | N/A |
| `citation_coverage` | 1.0000 | macro_case_mean | 1.000000 | 1 | 2.0% | 1 / 49 | no_reference_citations=49 | N/A |
| `invalid_citation_rate` | 0.1440 | macro_case_mean | 7.200000 | 50 | 100.0% | 50 / 0 | none | N/A |
| `answer_similarity_pass_rate` | 0.0400 | case_count_ratio | 2.000000 | 50 | 100.0% | 50 / 0 | none | N/A |
| `unanswerable_accuracy` | N/A | case_count_ratio | 0.000000 | 0 | 0.0% | 0 / 50 | answerable_case=50 | no_unanswerable_cases |
| `refusal_precision` | N/A | case_count_ratio | 0.000000 | 0 | 0.0% | 0 / 50 | not_predicted_refusal=50 | no_predicted_refusals |
| `refusal_recall` | N/A | case_count_ratio | 0.000000 | 0 | 0.0% | 0 / 50 | answerable_case=50 | no_unanswerable_cases |
| `mixed_claim_refusal_rate` | 0.0400 | case_count_ratio | 2.000000 | 50 | 100.0% | 50 / 0 | none | N/A |

## 6. Generation, guardrail, and judge coverage

Generation STOP / total: `50 / 50`
Input safe / total: `50 / 50`
Output safe / total: `50 / 50`
Ragas scored / eligible: `0 / 50`
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
| `t_evidence_fallback` | 0.0735 | 34.4216 | 4.2297 |
| `t_input_guardrail` | 0.7749 | 3.4056 | 1.2732 |
| `t_llm` | 2.2950 | 11.6671 | 4.5096 |
| `t_output_guardrail` | 1.1306 | 4.7839 | 1.7984 |
| `t_retrieval` | 1.8870 | 4.1261 | 2.3169 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 8.9576 | 44.8162 | 14.1333 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_001` | `ok` | `STOP` | `no` | `none` | 8.8066 |
| `case_002` | `ok` | `STOP` | `no` | `none` | 7.6976 |
| `case_003` | `ok` | `STOP` | `no` | `none` | 7.8310 |
| `case_004` | `ok` | `STOP` | `no` | `none` | 12.0649 |
| `case_005` | `ok` | `STOP` | `no` | `none` | 15.7320 |
| `case_006` | `ok` | `STOP` | `no` | `none` | 12.4861 |
| `case_007` | `ok` | `STOP` | `no` | `none` | 8.5193 |
| `case_008` | `ok` | `STOP` | `no` | `none` | 13.2085 |
| `case_009` | `ok` | `STOP` | `no` | `none` | 9.0632 |
| `case_010` | `ok` | `STOP` | `no` | `none` | 14.1924 |
| `case_011` | `ok` | `STOP` | `no` | `none` | 15.1114 |
| `case_012` | `ok` | `STOP` | `no` | `none` | 6.5843 |
| `case_013` | `ok` | `STOP` | `no` | `none` | 4.2490 |
| `case_014` | `ok` | `STOP` | `no` | `none` | 6.8082 |
| `case_015` | `ok` | `STOP` | `no` | `none` | 58.0567 |
| `case_016` | `ok` | `STOP` | `no` | `none` | 49.8436 |
| `case_017` | `ok` | `STOP` | `no` | `none` | 46.7448 |
| `case_018` | `ok` | `STOP` | `no` | `none` | 42.4591 |
| `case_019` | `ok` | `STOP` | `no` | `none` | 9.6919 |
| `case_020` | `ok` | `STOP` | `no` | `none` | 5.4138 |
| `case_021` | `ok` | `STOP` | `no` | `none` | 5.8733 |
| `case_022` | `ok` | `STOP` | `no` | `none` | 4.0206 |
| `case_023` | `ok` | `STOP` | `no` | `none` | 6.7235 |
| `case_024` | `ok` | `STOP` | `no` | `none` | 4.6111 |
| `case_025` | `ok` | `STOP` | `no` | `none` | 7.7154 |
| `case_026` | `ok` | `STOP` | `no` | `none` | 41.4635 |
| `case_027` | `ok` | `STOP` | `no` | `none` | 9.1645 |
| `case_028` | `ok` | `STOP` | `no` | `none` | 5.6507 |
| `case_029` | `ok` | `STOP` | `no` | `none` | 8.3148 |
| `case_030` | `ok` | `STOP` | `no` | `none` | 5.9434 |
| `case_031` | `ok` | `STOP` | `no` | `none` | 6.2924 |
| `case_032` | `ok` | `STOP` | `no` | `none` | 25.6258 |
| `case_033` | `ok` | `STOP` | `no` | `none` | 13.3965 |
| `case_034` | `ok` | `STOP` | `no` | `none` | 9.4775 |
| `case_035` | `ok` | `STOP` | `no` | `none` | 31.5971 |
| `case_036` | `ok` | `STOP` | `no` | `none` | 8.8520 |
| `case_037` | `ok` | `STOP` | `no` | `none` | 17.1932 |
| `case_038` | `ok` | `STOP` | `no` | `none` | 11.5719 |
| `case_039` | `ok` | `STOP` | `no` | `none` | 10.7217 |
| `case_040` | `ok` | `STOP` | `no` | `none` | 6.4309 |
| `case_041` | `ok` | `STOP` | `no` | `none` | 6.2831 |
| `case_042` | `ok` | `STOP` | `no` | `none` | 33.3510 |
| `case_043` | `ok` | `STOP` | `no` | `none` | 6.5473 |
| `case_044` | `ok` | `STOP` | `no` | `none` | 12.5099 |
| `case_045` | `ok` | `STOP` | `no` | `none` | 8.7000 |
| `case_046` | `ok` | `STOP` | `no` | `none` | 8.3854 |
| `case_047` | `ok` | `STOP` | `no` | `none` | 10.0011 |
| `case_048` | `ok` | `STOP` | `no` | `none` | 7.9972 |
| `case_049` | `ok` | `STOP` | `no` | `none` | 7.6661 |
| `case_050` | `ok` | `STOP` | `no` | `none` | 10.0218 |