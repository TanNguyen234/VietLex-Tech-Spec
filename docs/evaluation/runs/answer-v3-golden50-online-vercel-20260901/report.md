# VIETLEX EVALUATION REPORT — answer-v3-golden50-online-vercel-20260901

**Run ID**: `answer-v3-golden50-online-vercel-20260901`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-09-01T13:20:23.576533+00:00`  
**Git Commit SHA**: `c5fa8121d3080ac401d5a79e1beedaa1ffa2241f`  
**Source State SHA-256**: `7fb04d6a3b5ae33eb0b77f95ed31789ba75a5c5bf073ab7e10a874cdfb62f252`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `a4df82d0d3838c6b90fccc61f836fd0b50e9f5cfb157efa032694580c801de97`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `caa3fc19cd22bcce4b87e96adf13544d0c3cc174cca2d0e365a848e0da9a981f`  
**Configuration Fingerprint**: `f7d8f32cfee8e4c4de5f84bb955211e880e632d66ad72a68c1d9c6f2104f187b`  
**Execution Command**: `run_answer_eval.py --dataset docs/evaluation/golden50-v3/cases.json --sidecar docs/evaluation/golden50-v3/labels.json --backend vertex-qdrant-v3 --ranking raw-rrf --retrieval-run docs/evaluation/runs/retrieval-v3-golden50-online-vercel-20260901 --profile separated_intent --rewrite off --guardrails enforce --reranker current --concurrency 1 --gold-policy none --judge ragas --run-id answer-v3-golden50-online-vercel-20260901`  
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

## 5. Deterministic answer metrics

Answer scored / total: `50 / 50`
Answer skip reasons: `none`

| Metric | Value |
| :--- | ---: |
| `answer_similarity_pass_rate` | 0.0000 |
| `unanswerable_accuracy` | N/A |
| `refusal_precision` | N/A |
| `refusal_recall` | N/A |
| `token_f1` | 0.2336 |
| `char_f1` | 0.2250 |
| `rouge_l` | 0.2210 |
| `chrf` | 0.3796 |
| `citation_precision` | 0.9567 |
| `invalid_citation_rate` | 0.0433 |

## 6. Generation, guardrail, and judge coverage

Generation STOP / total: `50 / 50`
Input safe / total: `50 / 50`
Output safe / total: `50 / 50`
Ragas scored / eligible: `50 / 50`
Judge technical errors: `0`

| Ragas metric | Mean | Scored cases |
| :--- | ---: | ---: |
| `faithfulness` | 0.9197 | 50 |
| `answer_accuracy` | 0.9150 | 50 |
| `context_precision` | 0.8733 | 50 |
| `context_recall` | 0.9367 | 50 |

## 7. Latency

| Stage | P50 (s) | P95 (s) | Mean (s) |
| :--- | ---: | ---: | ---: |
| `t_input_guardrail` | 1.0061 | 1.2432 | 1.0293 |
| `t_output_guardrail` | 1.1252 | 1.4889 | 1.1524 |
| `t_retrieval` | 0.6842 | 1.6051 | 0.9698 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 5.3818 | 6.7163 | 5.4094 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_001` | `ok` | `STOP` | `yes` | `none` | 6.4260 |
| `case_002` | `ok` | `STOP` | `yes` | `none` | 4.9929 |
| `case_003` | `ok` | `STOP` | `yes` | `none` | 6.0006 |
| `case_004` | `ok` | `STOP` | `yes` | `none` | 6.7305 |
| `case_005` | `ok` | `STOP` | `yes` | `none` | 5.9633 |
| `case_006` | `ok` | `STOP` | `yes` | `none` | 5.4500 |
| `case_007` | `ok` | `STOP` | `yes` | `none` | 7.1404 |
| `case_008` | `ok` | `STOP` | `yes` | `none` | 4.5261 |
| `case_009` | `ok` | `STOP` | `yes` | `none` | 5.8345 |
| `case_010` | `ok` | `STOP` | `yes` | `none` | 5.4950 |
| `case_011` | `ok` | `STOP` | `yes` | `none` | 6.5039 |
| `case_012` | `ok` | `STOP` | `yes` | `none` | 5.4623 |
| `case_013` | `ok` | `STOP` | `yes` | `none` | 5.1089 |
| `case_014` | `ok` | `STOP` | `yes` | `none` | 4.5577 |
| `case_015` | `ok` | `STOP` | `yes` | `none` | 5.1054 |
| `case_016` | `ok` | `STOP` | `yes` | `none` | 5.0440 |
| `case_017` | `ok` | `STOP` | `yes` | `none` | 4.4764 |
| `case_018` | `ok` | `STOP` | `yes` | `none` | 5.8199 |
| `case_019` | `ok` | `STOP` | `yes` | `none` | 5.5560 |
| `case_020` | `ok` | `STOP` | `yes` | `none` | 5.6879 |
| `case_021` | `ok` | `STOP` | `yes` | `none` | 4.8581 |
| `case_022` | `ok` | `STOP` | `yes` | `none` | 4.7625 |
| `case_023` | `ok` | `STOP` | `yes` | `none` | 6.6262 |
| `case_024` | `ok` | `STOP` | `yes` | `none` | 4.2959 |
| `case_025` | `ok` | `STOP` | `yes` | `none` | 5.1692 |
| `case_026` | `ok` | `STOP` | `yes` | `none` | 6.8617 |
| `case_027` | `ok` | `STOP` | `yes` | `none` | 5.3301 |
| `case_028` | `ok` | `STOP` | `yes` | `none` | 5.7973 |
| `case_029` | `ok` | `STOP` | `yes` | `none` | 6.6990 |
| `case_030` | `ok` | `STOP` | `yes` | `none` | 5.4596 |
| `case_031` | `ok` | `STOP` | `yes` | `none` | 5.0875 |
| `case_032` | `ok` | `STOP` | `yes` | `none` | 5.8841 |
| `case_033` | `ok` | `STOP` | `yes` | `none` | 5.4335 |
| `case_034` | `ok` | `STOP` | `yes` | `none` | 5.4655 |
| `case_035` | `ok` | `STOP` | `yes` | `none` | 4.6250 |
| `case_036` | `ok` | `STOP` | `yes` | `none` | 4.2907 |
| `case_037` | `ok` | `STOP` | `yes` | `none` | 6.1330 |
| `case_038` | `ok` | `STOP` | `yes` | `none` | 4.4572 |
| `case_039` | `ok` | `STOP` | `yes` | `none` | 4.7477 |
| `case_040` | `ok` | `STOP` | `yes` | `none` | 4.4259 |
| `case_041` | `ok` | `STOP` | `yes` | `none` | 4.6755 |
| `case_042` | `ok` | `STOP` | `yes` | `none` | 5.4944 |
| `case_043` | `ok` | `STOP` | `yes` | `none` | 5.5859 |
| `case_044` | `ok` | `STOP` | `yes` | `none` | 4.5902 |
| `case_045` | `ok` | `STOP` | `yes` | `none` | 4.7267 |
| `case_046` | `ok` | `STOP` | `yes` | `none` | 5.3280 |
| `case_047` | `ok` | `STOP` | `yes` | `none` | 6.0245 |
| `case_048` | `ok` | `STOP` | `yes` | `none` | 5.2737 |
| `case_049` | `ok` | `STOP` | `yes` | `none` | 5.1604 |
| `case_050` | `ok` | `STOP` | `yes` | `none` | 5.3199 |