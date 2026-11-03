# VIETLEX EVALUATION REPORT — answer-golden50-production-citations32-20261103-476b6d5e

**Run ID**: `answer-golden50-production-citations32-20261103-476b6d5e`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-11-03T12:54:31.899686+00:00`  
**Git Commit SHA**: `7519cd1aea4a3639140b9188de1843ebf0ddb1c0`  
**Source State SHA-256**: `b1fabbfce559a5eadd1f7845f61f1ac859445b7a822ddd0b9e0790018b98f4fe`  
**Git Dirty Status**: `True` (Diff: `redacted`, SHA-256: `N/A`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `caa3fc19cd22bcce4b87e96adf13544d0c3cc174cca2d0e365a848e0da9a981f`  
**Configuration Fingerprint**: `19095de52d9c13f9011d4c18e7223b8223e42d5819d2291c54af977dc74bd00a`  
**Execution Command**: `run_answer_eval.py --dataset docs/evaluation/golden50-v3/cases.json --sidecar docs/evaluation/golden50-v3/labels.json --backend production --ranking rrf-dbsf --profile separated_intent --rewrite off --guardrails enforce --reranker current --concurrency 2 --gold-policy none --judge none --run-id answer-golden50-production-citations32-20261103-476b6d5e`  
**Evaluation Mode**: `answer` | **Judge**: `none` | **Guardrails**: `enforce`  

Metric schema: `3.0.0`
Answer metric version: `3.2.0`
Answer pipeline: `chat_service_v1`
Runtime environment: `{'app_env': 'development', 'serverless_online_only': True}`
Scored / Total: `39 / 50`
Skipped cases: `11`
Skip reasons: `input_guardrail_error=2, no_verified_gold_label=9`

## 1. Reliability and coverage

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons | Notes |
| :--- | ---: | ---: | :---: | :---: | :--- | :--- |
| Scored gold coverage | 78.0% | 78.0% | 39.0000/50.0000 | 50 / 0 | input_guardrail_error=2, no_verified_gold_label=9 | Cases with applicable verified required evidence |
| No-candidate rate | 0.0% | 0.0% | 0.0000/50.0000 | 50 / 0 | none | Completed retrievals with zero candidates |
| Retrieval technical-error rate | 0.0% | 0.0% | 0.0000/50.0000 | 50 / 0 | none | Status retrieval_error or partial_retrieval_error |
| Reranker technical-error rate | 0.0% | 0.0% | 0.0000/50.0000 | 50 / 0 | none | Exact status reranker_error |

## 2. Retrieval quality

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons |
| :--- | ---: | ---: | :---: | :---: | :--- |
| Document Recall @ 1 | 0.8974 | 0.8654 | 45.0000/52.0000 | 39 / 11 | input_guardrail_error=2, no_verified_gold_label=9 |
| Document Recall @ 3 | 1.0000 | 1.0000 | 52.0000/52.0000 | 39 / 11 | input_guardrail_error=2, no_verified_gold_label=9 |
| Document Recall @ 5 | 1.0000 | 1.0000 | 52.0000/52.0000 | 39 / 11 | input_guardrail_error=2, no_verified_gold_label=9 |
| Document Recall @ 10 | 1.0000 | 1.0000 | 52.0000/52.0000 | 39 / 11 | input_guardrail_error=2, no_verified_gold_label=9 |
| Document Recall @ 24 | 1.0000 | 1.0000 | 52.0000/52.0000 | 39 / 11 | input_guardrail_error=2, no_verified_gold_label=9 |
| Article Recall @ 1 | 0.8077 | 0.7931 | 23.0000/29.0000 | 26 / 24 | input_guardrail_error=2, no_applicable_gold=13, no_verified_gold_label=9 |
| Article Recall @ 3 | 0.9808 | 0.9655 | 28.0000/29.0000 | 26 / 24 | input_guardrail_error=2, no_applicable_gold=13, no_verified_gold_label=9 |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 50 | input_guardrail_error=2, k_exceeds_configured_capacity=39, no_verified_gold_label=9 |
| Clause Recall @ 1 | 0.6250 | 0.6154 | 8.0000/13.0000 | 12 / 38 | input_guardrail_error=2, no_applicable_gold=27, no_verified_gold_label=9 |
| Clause Recall @ 3 | 0.9167 | 0.9231 | 12.0000/13.0000 | 12 / 38 | input_guardrail_error=2, no_applicable_gold=27, no_verified_gold_label=9 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 50 | input_guardrail_error=2, k_exceeds_configured_capacity=39, no_verified_gold_label=9 |
| Article MRR | 0.9167 | 0.9167 | 23.8333/26.0000 | 26 / 24 | input_guardrail_error=2, no_applicable_gold=13, no_verified_gold_label=9 |
| Clause MRR | 0.7778 | 0.7778 | 9.3333/12.0000 | 12 / 38 | input_guardrail_error=2, no_applicable_gold=27, no_verified_gold_label=9 |
| Document MRR | 0.9487 | 0.9487 | 37.0000/39.0000 | 39 / 11 | input_guardrail_error=2, no_verified_gold_label=9 |
| nDCG @ 10 | 0.8822 | 0.8646 | 40.8093/47.2021 | 39 / 11 | input_guardrail_error=2, no_verified_gold_label=9 |
| Exact legal-reference hit | 0.9744 | 0.9744 | 38.0000/39.0000 | 39 / 11 | input_guardrail_error=2, no_verified_gold_label=9 |
| Multi-hop all-required coverage | 0.9487 | 0.9487 | 37.0000/39.0000 | 39 / 11 | input_guardrail_error=2, no_verified_gold_label=9 |
| Multi-hop partial coverage | 0.9615 | 0.9615 | 50.0000/52.0000 | 39 / 11 | input_guardrail_error=2, no_verified_gold_label=9 |

## 3. Stage metrics

| Pipeline stage | Capacity | Scored cases | Candidate p50 / p95 | Matched / Applicable documents | First-loss evidence count | Null reasons |
| :--- | ---: | ---: | :---: | :---: | ---: | :--- |
| `pinecone_document_metrics` | N/A | 39 | 0.0000 / 0.0000 | 0 / 52 | 0 | configured_capacity_unknown=195, input_guardrail_error=28, no_verified_gold_label=126, stage_does_not_expose_structural_locators=312 |
| `fts_document_metrics` | N/A | 39 | 0.0000 / 0.0000 | 0 / 52 | 0 | configured_capacity_unknown=195, input_guardrail_error=28, no_verified_gold_label=126, stage_does_not_expose_structural_locators=312 |
| `source_retrieval_metrics` | 24 | 39 | 24.0000 / 24.0000 | 52 / 52 | 0 | input_guardrail_error=28, no_verified_gold_label=126, stage_does_not_expose_structural_locators=312 |
| `merged_document_metrics` | 24 | 39 | 0.0000 / 0.0000 | 0 / 52 | 52 | input_guardrail_error=28, no_verified_gold_label=126, stage_does_not_expose_structural_locators=312 |
| `resolved_document_metrics` | 24 | 39 | 0.0000 / 0.0000 | 0 / 52 | 0 | input_guardrail_error=28, no_verified_gold_label=126, stage_does_not_expose_structural_locators=312 |
| `structural_chunk_metrics` | 24 | 39 | 24.0000 / 24.0000 | 52 / 52 | 0 | input_guardrail_error=28, no_applicable_gold=160, no_verified_gold_label=126 |
| `local_selection_metrics` | N/A | 39 | 0.0000 / 1.0000 | 16 / 52 | 0 | configured_capacity_unknown=429, input_guardrail_error=28, no_applicable_gold=40, no_verified_gold_label=126 |
| `reranker_input_metrics` | 24 | 39 | 24.0000 / 24.0000 | 52 / 52 | 0 | input_guardrail_error=28, no_applicable_gold=160, no_verified_gold_label=126 |
| `reranker_output_metrics` | 3 | 39 | 3.0000 / 3.0000 | 52 / 52 | 0 | input_guardrail_error=28, k_exceeds_configured_capacity=195, no_applicable_gold=120, no_verified_gold_label=126 |
| `final_evidence_metrics` | 3 | 39 | 3.0000 / 3.0000 | 52 / 52 | 0 | input_guardrail_error=28, k_exceeds_configured_capacity=195, no_applicable_gold=120, no_verified_gold_label=126 |

## 4. Interpretation notes

- Recall@K is undefined when K exceeds the configured stage capacity; nDCG@10 still treats unreturned ranks as zero gain so capacity effects remain measurable.
- Configured provider candidates are provenance only; they do not prove which provider answered a request.

## 5. Deterministic answer metrics

Answer scored / total: `48 / 50`
Answer skip reasons: `input_guardrail_error=2`

| Metric | Value | Aggregation | Numerator | Denominator | Coverage | Scored / Skipped | Skip reasons | Reason |
| :--- | ---: | :--- | ---: | ---: | ---: | ---: | :--- | :--- |
| `exact_match` | 0.0000 | macro_case_mean | 0.000000 | 48 | 96.0% | 48 / 2 | input_guardrail_error=2 | N/A |
| `token_precision` | 0.1306 | macro_case_mean | 6.269000 | 48 | 96.0% | 48 / 2 | input_guardrail_error=2 | N/A |
| `token_recall` | 0.9151 | macro_case_mean | 43.923500 | 48 | 96.0% | 48 / 2 | input_guardrail_error=2 | N/A |
| `token_f1` | 0.2227 | macro_case_mean | 10.690500 | 48 | 96.0% | 48 / 2 | input_guardrail_error=2 | N/A |
| `char_f1` | 0.2235 | macro_case_mean | 10.727800 | 48 | 96.0% | 48 / 2 | input_guardrail_error=2 | N/A |
| `rouge_l` | 0.2108 | macro_case_mean | 10.117700 | 48 | 96.0% | 48 / 2 | input_guardrail_error=2 | N/A |
| `chrf` | 0.3741 | macro_case_mean | 17.957900 | 48 | 96.0% | 48 / 2 | input_guardrail_error=2 | N/A |
| `number_precision` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | input_guardrail_error=2, no_expected_numbers=48 | no_applicable_values |
| `number_recall` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | input_guardrail_error=2, no_expected_numbers=48 | no_applicable_values |
| `date_precision` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | input_guardrail_error=2, no_expected_dates=48 | no_applicable_values |
| `date_recall` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | input_guardrail_error=2, no_expected_dates=48 | no_applicable_values |
| `entity_precision` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | input_guardrail_error=2, no_expected_entities=48 | no_applicable_values |
| `entity_recall` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | input_guardrail_error=2, no_expected_entities=48 | no_applicable_values |
| `citation_precision` | 0.8833 | macro_case_mean | 39.750000 | 45 | 90.0% | 45 / 5 | input_guardrail_error=2, no_retrieved_evidence_citations=3 | N/A |
| `citation_recall` | 1.0000 | macro_case_mean | 1.000000 | 1 | 2.0% | 1 / 49 | input_guardrail_error=2, no_reference_citations=47 | N/A |
| `citation_coverage` | 1.0000 | macro_case_mean | 1.000000 | 1 | 2.0% | 1 / 49 | input_guardrail_error=2, no_reference_citations=47 | N/A |
| `invalid_citation_rate` | 0.1167 | macro_case_mean | 5.250000 | 45 | 90.0% | 45 / 5 | input_guardrail_error=2, no_retrieved_evidence_citations=3 | N/A |
| `answer_similarity_pass_rate` | 0.0208 | case_count_ratio | 1.000000 | 48 | 96.0% | 48 / 2 | input_guardrail_error=2 | N/A |
| `unanswerable_accuracy` | N/A | case_count_ratio | 0.000000 | 0 | 0.0% | 0 / 50 | answerable_case=48, input_guardrail_error=2 | no_unanswerable_cases |
| `refusal_precision` | 0.0000 | case_count_ratio | 0.000000 | 3 | 6.0% | 3 / 47 | input_guardrail_error=2, not_predicted_refusal=45 | N/A |
| `refusal_recall` | N/A | case_count_ratio | 0.000000 | 0 | 0.0% | 0 / 50 | answerable_case=48, input_guardrail_error=2 | no_unanswerable_cases |
| `mixed_claim_refusal_rate` | 0.0208 | case_count_ratio | 1.000000 | 48 | 96.0% | 48 / 2 | input_guardrail_error=2 | N/A |

## 6. Generation, guardrail, and judge coverage

Generation STOP / total: `45 / 50`
Input safe / total: `48 / 50`
Output safe / total: `48 / 50`
Ragas scored / eligible: `0 / 45`
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
| `t_evidence_fallback` | 52.2410 | 58.6911 | 44.0255 |
| `t_input_guardrail` | 0.8587 | 4.6782 | 1.4408 |
| `t_llm` | 3.1355 | 10.2973 | 3.7625 |
| `t_output_guardrail` | 1.1804 | 1.8145 | 1.1983 |
| `t_retrieval` | 2.4695 | 10.2256 | 3.5559 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 59.3935 | 76.0304 | 51.8895 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_001` | `ok` | `STOP` | `no` | `none` | 67.0050 |
| `case_002` | `ok` | `STOP` | `no` | `none` | 43.9695 |
| `case_003` | `ok` | `STOP` | `no` | `none` | 56.7049 |
| `case_004` | `ok` | `STOP` | `no` | `none` | 55.3188 |
| `case_005` | `ok` | `STOP` | `no` | `none` | 64.3237 |
| `case_006` | `ok` | `STOP` | `no` | `none` | 53.6915 |
| `case_007` | `ok` | `STOP` | `no` | `none` | 10.4830 |
| `case_008` | `ok` | `STOP` | `no` | `none` | 10.8827 |
| `case_009` | `ok` | `STOP` | `no` | `none` | 12.3637 |
| `case_010` | `ok` | `STOP` | `no` | `none` | 55.0931 |
| `case_011` | `ok` | `STOP` | `no` | `none` | 74.9331 |
| `case_012` | `ok` | `STOP` | `no` | `none` | 58.0991 |
| `case_013` | `ok` | `N/A` | `no` | `none` | 14.1894 |
| `case_014` | `ok` | `STOP` | `no` | `none` | 20.0681 |
| `case_015` | `ok` | `STOP` | `no` | `none` | 59.4287 |
| `case_016` | `ok` | `N/A` | `no` | `none` | 19.1652 |
| `case_017` | `ok` | `STOP` | `no` | `none` | 60.0099 |
| `case_018` | `ok` | `STOP` | `no` | `none` | 22.1707 |
| `case_019` | `ok` | `STOP` | `no` | `none` | 56.3849 |
| `case_020` | `ok` | `STOP` | `no` | `none` | 57.7033 |
| `case_021` | `ok` | `STOP` | `no` | `none` | 9.5004 |
| `case_022` | `ok` | `STOP` | `no` | `none` | 52.5155 |
| `case_023` | `ok` | `STOP` | `no` | `none` | 60.8926 |
| `case_024` | `ok` | `STOP` | `no` | `none` | 59.3868 |
| `case_025` | `ok` | `STOP` | `no` | `none` | 59.4001 |
| `case_026` | `ok` | `STOP` | `no` | `none` | 60.3968 |
| `case_027` | `ok` | `STOP` | `no` | `none` | 60.5611 |
| `case_028` | `ok` | `STOP` | `no` | `none` | 58.9463 |
| `case_029` | `ok` | `STOP` | `no` | `none` | 73.2590 |
| `case_030` | `ok` | `STOP` | `no` | `none` | 62.6777 |
| `case_031` | `ok` | `STOP` | `no` | `none` | 61.1602 |
| `case_032` | `ok` | `STOP` | `no` | `none` | 62.2479 |
| `case_033` | `ok` | `STOP` | `no` | `none` | 59.3219 |
| `case_034` | `ok` | `STOP` | `no` | `none` | 65.1196 |
| `case_035` | `ok` | `N/A` | `no` | `none` | 62.7336 |
| `case_036` | `ok` | `STOP` | `no` | `none` | 65.6046 |
| `case_037` | `ok` | `STOP` | `no` | `none` | 63.7175 |
| `case_038` | `ok` | `STOP` | `no` | `none` | 57.9969 |
| `case_039` | `ok` | `STOP` | `no` | `none` | 61.8575 |
| `case_040` | `ok` | `STOP` | `no` | `none` | 64.9111 |
| `case_041` | `ok` | `STOP` | `no` | `none` | 62.0894 |
| `case_042` | `ok` | `STOP` | `no` | `none` | 64.9311 |
| `case_043` | `ok` | `STOP` | `no` | `none` | 76.9282 |
| `case_044` | `ok` | `STOP` | `no` | `none` | 36.1275 |
| `case_045` | `ok` | `STOP` | `no` | `none` | 68.0505 |
| `case_046` | `input_guardrail_error` | `N/A` | `no` | `input_guardrail` | 8.3261 |
| `case_047` | `ok` | `STOP` | `no` | `none` | 87.3814 |
| `case_048` | `ok` | `STOP` | `no` | `none` | 84.2318 |
| `case_049` | `input_guardrail_error` | `N/A` | `no` | `input_guardrail` | 8.9820 |
| `case_050` | `ok` | `STOP` | `no` | `none` | 43.2296 |