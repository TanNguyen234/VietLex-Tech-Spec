# OFFLINE FULL-METRIC RESCORE — no new provider/database calls

All answers, prompt contexts, retrieval results, generation/guard observations and latencies come unchanged from live parent `answer-golden50-production-timeout20-20261103-f93a41fe` (source26). Only deterministic citation metrics are recomputed using3.3 on source27. This is not a new live50 run on deployment27. Source/dependency proof and paired old/new metrics are in rescore-proof.json and paired-metrics.json.

# VIETLEX EVALUATION REPORT — answer-golden50-offline-metrics33-20261103-2349369e

**Run ID**: `answer-golden50-offline-metrics33-20261103-2349369e`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-11-03T14:58:16.397847+00:00`  
**Git Commit SHA**: `7519cd1aea4a3639140b9188de1843ebf0ddb1c0`  
**Source State SHA-256**: `9a36bd2928f6087ed1ac385e1c1342414927e3f4be03a9d7986e03b9b26593b7`  
**Git Dirty Status**: `True` (Diff: `redacted`, SHA-256: `N/A`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `caa3fc19cd22bcce4b87e96adf13544d0c3cc174cca2d0e365a848e0da9a981f`  
**Configuration Fingerprint**: `6462ba07bd1c5be3a7ce78943ce657177d2bf91723a22d1d408c6b1ef6e5c773`  
**Execution Command**: `D:\Download\ProfessionalLegalRAG\.venv\Scripts\python.exe -X utf8 .tmp-finish-real-20261030\crg-golden50-af33f34f\offline_rescore33.py`  
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
| Document MRR | 0.9458 | 0.9458 | 37.8333/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| nDCG @ 10 | 0.8832 | 0.8647 | 41.6784/48.2021 | 40 / 10 | no_verified_gold_label=10 |
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
| `token_precision` | 0.1367 | macro_case_mean | 6.833100 | 50 | 100.0% | 50 / 0 | none | N/A |
| `token_recall` | 0.9577 | macro_case_mean | 47.887400 | 50 | 100.0% | 50 / 0 | none | N/A |
| `token_f1` | 0.2323 | macro_case_mean | 11.613800 | 50 | 100.0% | 50 / 0 | none | N/A |
| `char_f1` | 0.2291 | macro_case_mean | 11.453900 | 50 | 100.0% | 50 / 0 | none | N/A |
| `rouge_l` | 0.2241 | macro_case_mean | 11.205600 | 50 | 100.0% | 50 / 0 | none | N/A |
| `chrf` | 0.3836 | macro_case_mean | 19.178600 | 50 | 100.0% | 50 / 0 | none | N/A |
| `number_precision` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_numbers=50 | no_applicable_values |
| `number_recall` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_numbers=50 | no_applicable_values |
| `date_precision` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_dates=50 | no_applicable_values |
| `date_recall` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_dates=50 | no_applicable_values |
| `entity_precision` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_entities=50 | no_applicable_values |
| `entity_recall` | N/A | macro_case_mean | 0.000000 | 0 | 0.0% | 0 / 50 | no_expected_entities=50 | no_applicable_values |
| `citation_precision` | 0.9679 | macro_case_mean | 47.427700 | 49 | 98.0% | 49 / 1 | no_retrieved_evidence_citations=1 | N/A |
| `citation_recall` | 1.0000 | macro_case_mean | 1.000000 | 1 | 2.0% | 1 / 49 | no_reference_citations=49 | N/A |
| `citation_coverage` | 1.0000 | macro_case_mean | 1.000000 | 1 | 2.0% | 1 / 49 | no_reference_citations=49 | N/A |
| `invalid_citation_rate` | 0.0321 | macro_case_mean | 1.572300 | 49 | 98.0% | 49 / 1 | no_retrieved_evidence_citations=1 | N/A |
| `answer_similarity_pass_rate` | 0.0000 | case_count_ratio | 0.000000 | 50 | 100.0% | 50 / 0 | none | N/A |
| `unanswerable_accuracy` | N/A | case_count_ratio | 0.000000 | 0 | 0.0% | 0 / 50 | answerable_case=50 | no_unanswerable_cases |
| `refusal_precision` | 0.0000 | case_count_ratio | 0.000000 | 1 | 2.0% | 1 / 49 | not_predicted_refusal=49 | N/A |
| `refusal_recall` | N/A | case_count_ratio | 0.000000 | 0 | 0.0% | 0 / 50 | answerable_case=50 | no_unanswerable_cases |
| `mixed_claim_refusal_rate` | 0.0000 | case_count_ratio | 0.000000 | 50 | 100.0% | 50 / 0 | none | N/A |

## 6. Generation, guardrail, and judge coverage

Generation STOP / total: `49 / 50`
Input safe / total: `50 / 50`
Output safe / total: `50 / 50`
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
| `t_evidence_fallback` | 50.0145 | 53.2469 | 43.0558 |
| `t_input_guardrail` | 0.6888 | 1.7404 | 0.8886 |
| `t_llm` | 2.7275 | 4.5170 | 2.8690 |
| `t_output_guardrail` | 0.8848 | 1.3656 | 0.9479 |
| `t_retrieval` | 2.6590 | 5.4851 | 2.8527 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 56.9511 | 62.6539 | 50.6176 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_001` | `ok` | `STOP` | `no` | `none` | 62.8605 |
| `case_002` | `ok` | `STOP` | `no` | `none` | 33.3587 |
| `case_003` | `ok` | `STOP` | `no` | `none` | 52.7747 |
| `case_004` | `ok` | `STOP` | `no` | `none` | 53.7123 |
| `case_005` | `ok` | `STOP` | `no` | `none` | 64.7966 |
| `case_006` | `ok` | `STOP` | `no` | `none` | 57.7394 |
| `case_007` | `ok` | `STOP` | `no` | `none` | 10.5320 |
| `case_008` | `ok` | `STOP` | `no` | `none` | 9.4978 |
| `case_009` | `ok` | `STOP` | `no` | `none` | 9.4563 |
| `case_010` | `ok` | `STOP` | `no` | `none` | 56.1919 |
| `case_011` | `ok` | `STOP` | `no` | `none` | 58.8015 |
| `case_012` | `ok` | `STOP` | `no` | `none` | 54.9629 |
| `case_013` | `ok` | `N/A` | `no` | `none` | 10.5435 |
| `case_014` | `ok` | `STOP` | `no` | `none` | 57.0679 |
| `case_015` | `ok` | `STOP` | `no` | `none` | 60.3456 |
| `case_016` | `ok` | `STOP` | `no` | `none` | 58.2985 |
| `case_017` | `ok` | `STOP` | `no` | `none` | 56.4740 |
| `case_018` | `ok` | `STOP` | `no` | `none` | 55.4916 |
| `case_019` | `ok` | `STOP` | `no` | `none` | 57.0034 |
| `case_020` | `ok` | `STOP` | `no` | `none` | 46.7296 |
| `case_021` | `ok` | `STOP` | `no` | `none` | 8.5203 |
| `case_022` | `ok` | `STOP` | `no` | `none` | 51.1133 |
| `case_023` | `ok` | `STOP` | `no` | `none` | 60.3097 |
| `case_024` | `ok` | `STOP` | `no` | `none` | 54.5339 |
| `case_025` | `ok` | `STOP` | `no` | `none` | 53.5289 |
| `case_026` | `ok` | `STOP` | `no` | `none` | 57.6428 |
| `case_027` | `ok` | `STOP` | `no` | `none` | 56.6678 |
| `case_028` | `ok` | `STOP` | `no` | `none` | 56.9855 |
| `case_029` | `ok` | `STOP` | `no` | `none` | 65.0125 |
| `case_030` | `ok` | `STOP` | `no` | `none` | 58.1382 |
| `case_031` | `ok` | `STOP` | `no` | `none` | 57.7256 |
| `case_032` | `ok` | `STOP` | `no` | `none` | 62.2839 |
| `case_033` | `ok` | `STOP` | `no` | `none` | 56.0915 |
| `case_034` | `ok` | `STOP` | `no` | `none` | 60.2578 |
| `case_035` | `ok` | `STOP` | `no` | `none` | 61.9258 |
| `case_036` | `ok` | `STOP` | `no` | `none` | 60.7994 |
| `case_037` | `ok` | `STOP` | `no` | `none` | 59.3666 |
| `case_038` | `ok` | `STOP` | `no` | `none` | 56.6853 |
| `case_039` | `ok` | `STOP` | `no` | `none` | 56.4816 |
| `case_040` | `ok` | `STOP` | `no` | `none` | 58.5714 |
| `case_041` | `ok` | `STOP` | `no` | `none` | 58.3471 |
| `case_042` | `ok` | `STOP` | `no` | `none` | 60.9350 |
| `case_043` | `ok` | `STOP` | `no` | `none` | 62.4014 |
| `case_044` | `ok` | `STOP` | `no` | `none` | 11.3499 |
| `case_045` | `ok` | `STOP` | `no` | `none` | 61.8915 |
| `case_046` | `ok` | `STOP` | `no` | `none` | 56.9168 |
| `case_047` | `ok` | `STOP` | `no` | `none` | 56.8977 |
| `case_048` | `ok` | `STOP` | `no` | `none` | 60.7064 |
| `case_049` | `ok` | `STOP` | `no` | `none` | 10.4457 |
| `case_050` | `ok` | `STOP` | `no` | `none` | 51.7055 |