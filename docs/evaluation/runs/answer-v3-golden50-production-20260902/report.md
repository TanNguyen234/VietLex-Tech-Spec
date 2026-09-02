# VIETLEX EVALUATION REPORT — answer-v3-golden50-production-20260902

**Run ID**: `answer-v3-golden50-production-20260902`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-09-02T11:24:24.689003+00:00`  
**Git Commit SHA**: `73cd7ca519214f95d69aafb9a2464570d7d888c4`  
**Source State SHA-256**: `3d9904dbd304feb353e8ac76be7f586e0698f4a1745af4e4537f8b09f3b46394`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `d946f6773f5ccd4e4aa6a94829b224fa917e8110b6030a8ac6f011b3ddf5845a`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `caa3fc19cd22bcce4b87e96adf13544d0c3cc174cca2d0e365a848e0da9a981f`  
**Configuration Fingerprint**: `f7d8f32cfee8e4c4de5f84bb955211e880e632d66ad72a68c1d9c6f2104f187b`  
**Execution Command**: `run_answer_eval.py --dataset docs/evaluation/golden50-v3/cases.json --sidecar docs/evaluation/golden50-v3/labels.json --backend vertex-qdrant-v3 --ranking raw-rrf --retrieval-run docs/evaluation/runs/retrieval-v3-golden50-production-20260902 --profile separated_intent --rewrite off --guardrails enforce --reranker current --concurrency 1 --gold-policy none --judge ragas --run-id answer-v3-golden50-production-20260902`  
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
| `token_f1` | 0.2304 |
| `char_f1` | 0.2226 |
| `rouge_l` | 0.2176 |
| `chrf` | 0.3771 |
| `citation_precision` | 0.9470 |
| `invalid_citation_rate` | 0.0530 |

## 6. Generation, guardrail, and judge coverage

Generation STOP / total: `50 / 50`
Input safe / total: `50 / 50`
Output safe / total: `50 / 50`
Ragas scored / eligible: `49 / 50`
Judge technical errors: `1`

| Ragas metric | Mean | Scored cases |
| :--- | ---: | ---: |
| `faithfulness` | 0.8887 | 49 |
| `answer_accuracy` | 0.9184 | 49 |
| `context_precision` | 0.8878 | 49 |
| `context_recall` | 0.9354 | 49 |

## 7. Latency

| Stage | P50 (s) | P95 (s) | Mean (s) |
| :--- | ---: | ---: | ---: |
| `t_input_guardrail` | 1.1212 | 1.3067 | 1.1155 |
| `t_output_guardrail` | 1.1379 | 1.3983 | 1.1721 |
| `t_retrieval` | 0.8146 | 1.1693 | 1.1223 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 5.2812 | 6.4429 | 5.4569 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_001` | `ok` | `STOP` | `yes` | `none` | 5.5830 |
| `case_002` | `ok` | `STOP` | `yes` | `none` | 5.2500 |
| `case_003` | `ok` | `STOP` | `yes` | `none` | 5.6902 |
| `case_004` | `ok` | `STOP` | `yes` | `none` | 6.2997 |
| `case_005` | `ok` | `STOP` | `yes` | `none` | 6.1732 |
| `case_006` | `ok` | `STOP` | `yes` | `none` | 6.0174 |
| `case_007` | `ok` | `STOP` | `yes` | `none` | 6.2651 |
| `case_008` | `ok` | `STOP` | `yes` | `none` | 5.0485 |
| `case_009` | `ok` | `STOP` | `yes` | `none` | 6.0550 |
| `case_010` | `ok` | `STOP` | `yes` | `none` | 5.3416 |
| `case_011` | `ok` | `STOP` | `yes` | `none` | 7.5073 |
| `case_012` | `ok` | `STOP` | `yes` | `none` | 4.6883 |
| `case_013` | `ok` | `STOP` | `yes` | `none` | 4.5023 |
| `case_014` | `ok` | `STOP` | `yes` | `none` | 4.7388 |
| `case_015` | `ok` | `STOP` | `yes` | `none` | 6.1726 |
| `case_016` | `ok` | `STOP` | `yes` | `none` | 5.6426 |
| `case_017` | `ok` | `STOP` | `yes` | `none` | 5.0018 |
| `case_018` | `ok` | `STOP` | `yes` | `none` | 6.4360 |
| `case_019` | `ok` | `STOP` | `yes` | `none` | 5.9048 |
| `case_020` | `ok` | `STOP` | `yes` | `none` | 5.8165 |
| `case_021` | `ok` | `STOP` | `yes` | `none` | 5.1214 |
| `case_022` | `ok` | `STOP` | `yes` | `none` | 4.5632 |
| `case_023` | `ok` | `STOP` | `yes` | `none` | 7.1799 |
| `case_024` | `ok` | `STOP` | `yes` | `none` | 5.1099 |
| `case_025` | `ok` | `STOP` | `yes` | `none` | 5.0037 |
| `case_026` | `ok` | `STOP` | `yes` | `none` | 6.4486 |
| `case_027` | `ok` | `STOP` | `yes` | `none` | 4.7681 |
| `case_028` | `ok` | `STOP` | `yes` | `none` | 5.0102 |
| `case_029` | `ok` | `STOP` | `yes` | `none` | 5.9852 |
| `case_030` | `ok` | `STOP` | `yes` | `none` | 4.9498 |
| `case_031` | `ok` | `STOP` | `yes` | `none` | 4.9840 |
| `case_032` | `ok` | `STOP` | `yes` | `none` | 4.9448 |
| `case_033` | `ok` | `STOP` | `yes` | `none` | 6.2148 |
| `case_034` | `ok` | `STOP` | `yes` | `none` | 6.2041 |
| `case_035` | `ok` | `STOP` | `yes` | `none` | 4.3011 |
| `case_036` | `ok` | `STOP` | `yes` | `none` | 4.4848 |
| `case_037` | `ok` | `STOP` | `no` | `judge` | 6.3029 |
| `case_038` | `ok` | `STOP` | `yes` | `none` | 5.3124 |
| `case_039` | `ok` | `STOP` | `yes` | `none` | 4.5266 |
| `case_040` | `ok` | `STOP` | `yes` | `none` | 4.9173 |
| `case_041` | `ok` | `STOP` | `yes` | `none` | 4.6953 |
| `case_042` | `ok` | `STOP` | `yes` | `none` | 4.9764 |
| `case_043` | `ok` | `STOP` | `yes` | `none` | 5.6415 |
| `case_044` | `ok` | `STOP` | `yes` | `none` | 5.0127 |
| `case_045` | `ok` | `STOP` | `yes` | `none` | 4.9318 |
| `case_046` | `ok` | `STOP` | `yes` | `none` | 4.4376 |
| `case_047` | `ok` | `STOP` | `yes` | `none` | 5.5493 |
| `case_048` | `ok` | `STOP` | `yes` | `none` | 6.3681 |
| `case_049` | `ok` | `STOP` | `yes` | `none` | 5.5815 |
| `case_050` | `ok` | `STOP` | `yes` | `none` | 5.1849 |