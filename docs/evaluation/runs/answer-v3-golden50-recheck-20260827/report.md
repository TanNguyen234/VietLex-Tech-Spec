# VIETLEX EVALUATION REPORT — answer-v3-golden50-recheck-20260827

**Run ID**: `answer-v3-golden50-recheck-20260827`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-08-27T14:19:55.782833+00:00`  
**Git Commit SHA**: `c5fa8121d3080ac401d5a79e1beedaa1ffa2241f`  
**Source State SHA-256**: `06515a1e1e71db7cbb4a11a9acc15221d74680442ad4aabaa00c8c3d3f493444`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `96ffe0663a2db452e455e3fb7c50d2bf45987f0f941f377bd17719e9635754b8`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `caa3fc19cd22bcce4b87e96adf13544d0c3cc174cca2d0e365a848e0da9a981f`  
**Configuration Fingerprint**: `f7d8f32cfee8e4c4de5f84bb955211e880e632d66ad72a68c1d9c6f2104f187b`  
**Execution Command**: `run_answer_eval.py --dataset docs/evaluation/golden50-v3/cases.json --sidecar docs/evaluation/golden50-v3/labels.json --backend vertex-qdrant-v3 --ranking raw-rrf --retrieval-run docs/evaluation/runs/retrieval-v3-golden50-recheck-20260827 --profile separated_intent --rewrite off --guardrails enforce --reranker current --concurrency 1 --gold-policy none --judge ragas --run-id answer-v3-golden50-recheck-20260827`  
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
| Document Recall @ 1 | 0.9750 | 0.9623 | 51.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
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
| Document MRR | 0.9875 | 0.9875 | 39.5000/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| nDCG @ 10 | 0.9275 | 0.9084 | 43.7856/48.2021 | 40 / 10 | no_verified_gold_label=10 |
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
| `token_f1` | 0.2352 |
| `char_f1` | 0.2270 |
| `rouge_l` | 0.2236 |
| `chrf` | 0.3840 |
| `citation_precision` | 0.9560 |
| `invalid_citation_rate` | 0.0440 |

## 6. Generation, guardrail, and judge coverage

Generation STOP / total: `50 / 50`
Input safe / total: `50 / 50`
Output safe / total: `50 / 50`
Ragas scored / eligible: `50 / 50`
Judge technical errors: `0`

| Ragas metric | Mean | Scored cases |
| :--- | ---: | ---: |
| `faithfulness` | 0.8640 | 50 |
| `answer_accuracy` | 0.9200 | 50 |
| `context_precision` | 0.8700 | 50 |
| `context_recall` | 0.9367 | 50 |

## 7. Latency

| Stage | P50 (s) | P95 (s) | Mean (s) |
| :--- | ---: | ---: | ---: |
| `t_input_guardrail` | 1.1999 | 1.7060 | 1.2705 |
| `t_output_guardrail` | 1.2409 | 1.5573 | 1.3489 |
| `t_retrieval` | 2.8160 | 4.0537 | 3.2122 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 5.7741 | 7.4859 | 6.0173 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_001` | `ok` | `STOP` | `yes` | `none` | 5.2092 |
| `case_002` | `ok` | `STOP` | `yes` | `none` | 6.3862 |
| `case_003` | `ok` | `STOP` | `yes` | `none` | 6.5606 |
| `case_004` | `ok` | `STOP` | `yes` | `none` | 7.4797 |
| `case_005` | `ok` | `STOP` | `yes` | `none` | 5.8766 |
| `case_006` | `ok` | `STOP` | `yes` | `none` | 6.5884 |
| `case_007` | `ok` | `STOP` | `yes` | `none` | 7.2451 |
| `case_008` | `ok` | `STOP` | `yes` | `none` | 4.7803 |
| `case_009` | `ok` | `STOP` | `yes` | `none` | 7.2905 |
| `case_010` | `ok` | `STOP` | `yes` | `none` | 5.2014 |
| `case_011` | `ok` | `STOP` | `yes` | `none` | 7.3416 |
| `case_012` | `ok` | `STOP` | `yes` | `none` | 5.5023 |
| `case_013` | `ok` | `STOP` | `yes` | `none` | 5.2001 |
| `case_014` | `ok` | `STOP` | `yes` | `none` | 4.8516 |
| `case_015` | `ok` | `STOP` | `yes` | `none` | 5.8220 |
| `case_016` | `ok` | `STOP` | `yes` | `none` | 5.8252 |
| `case_017` | `ok` | `STOP` | `yes` | `none` | 5.2101 |
| `case_018` | `ok` | `STOP` | `yes` | `none` | 6.3918 |
| `case_019` | `ok` | `STOP` | `yes` | `none` | 6.2731 |
| `case_020` | `ok` | `STOP` | `yes` | `none` | 5.7161 |
| `case_021` | `ok` | `STOP` | `yes` | `none` | 10.6277 |
| `case_022` | `ok` | `STOP` | `yes` | `none` | 6.1594 |
| `case_023` | `ok` | `STOP` | `yes` | `none` | 7.4910 |
| `case_024` | `ok` | `STOP` | `yes` | `none` | 5.1285 |
| `case_025` | `ok` | `STOP` | `yes` | `none` | 5.7563 |
| `case_026` | `ok` | `STOP` | `yes` | `none` | 6.9082 |
| `case_027` | `ok` | `STOP` | `yes` | `none` | 5.1980 |
| `case_028` | `ok` | `STOP` | `yes` | `none` | 5.1813 |
| `case_029` | `ok` | `STOP` | `yes` | `none` | 8.5060 |
| `case_030` | `ok` | `STOP` | `yes` | `none` | 6.5521 |
| `case_031` | `ok` | `STOP` | `yes` | `none` | 5.0748 |
| `case_032` | `ok` | `STOP` | `yes` | `none` | 5.1732 |
| `case_033` | `ok` | `STOP` | `yes` | `none` | 6.3997 |
| `case_034` | `ok` | `STOP` | `yes` | `none` | 6.5212 |
| `case_035` | `ok` | `STOP` | `yes` | `none` | 4.7352 |
| `case_036` | `ok` | `STOP` | `yes` | `none` | 5.1697 |
| `case_037` | `ok` | `STOP` | `yes` | `none` | 7.2259 |
| `case_038` | `ok` | `STOP` | `yes` | `none` | 5.5341 |
| `case_039` | `ok` | `STOP` | `yes` | `none` | 4.5334 |
| `case_040` | `ok` | `STOP` | `yes` | `none` | 5.3278 |
| `case_041` | `ok` | `STOP` | `yes` | `none` | 5.1439 |
| `case_042` | `ok` | `STOP` | `yes` | `none` | 5.1808 |
| `case_043` | `ok` | `STOP` | `yes` | `none` | 7.0886 |
| `case_044` | `ok` | `STOP` | `yes` | `none` | 4.8496 |
| `case_045` | `ok` | `STOP` | `yes` | `none` | 5.3323 |
| `case_046` | `ok` | `STOP` | `yes` | `none` | 4.8278 |
| `case_047` | `ok` | `STOP` | `yes` | `none` | 7.1039 |
| `case_048` | `ok` | `STOP` | `yes` | `none` | 5.7918 |
| `case_049` | `ok` | `STOP` | `yes` | `none` | 5.6589 |
| `case_050` | `ok` | `STOP` | `yes` | `none` | 5.9309 |