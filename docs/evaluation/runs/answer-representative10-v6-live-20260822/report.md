# VIETLEX EVALUATION REPORT — answer-representative10-v6-live-20260822

**Run ID**: `answer-representative10-v6-live-20260822`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-08-22T14:30:47.637423+00:00`  
**Git Commit SHA**: `6dd558c3e163941690eb9a75490c886a898d52d5`  
**Source State SHA-256**: `9e28bdaf44062eabac13a05f14ec2559ad07f784e5da6752009755519f9a6af9`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `c3ac8c5b527d4d57f220560c78ea058591e275dbc3b7e185fa63227e443ab7b7`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `b458880e2c2fc4f2813965d57dc96517555488a5ada3702da12fb811f05fb90b`  
**Configuration Fingerprint**: `225df477a81e703e97ef5e5b673b59a40527cc478f31d94f9381780ec0e24d81`  
**Execution Command**: `run_answer_eval.py --case-ids case_017 case_036 case_061 case_101 case_165 case_243 case_261 case_323 case_329 case_397 --verified-only --gold-policy all-required-verified --profile separated_intent --rewrite off --guardrails enforce --reranker current --concurrency 1 --judge ragas --run-id answer-representative10-v6-live-20260822`  
**Evaluation Mode**: `answer` | **Judge**: `ragas` | **Guardrails**: `enforce`  

Metric schema: `3.0.0`
Scored / Total: `10 / 10`
Skipped cases: `0`
Skip reasons: `none`

## 1. Reliability and coverage

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons | Notes |
| :--- | ---: | ---: | :---: | :---: | :--- | :--- |
| Scored gold coverage | 100.0% | 100.0% | 10.0000/10.0000 | 10 / 0 | none | Cases with applicable verified required evidence |
| No-candidate rate | 0.0% | 0.0% | 0.0000/10.0000 | 10 / 0 | none | Completed retrievals with zero candidates |
| Retrieval technical-error rate | 0.0% | 0.0% | 0.0000/10.0000 | 10 / 0 | none | Status retrieval_error or partial_retrieval_error |
| Reranker technical-error rate | 0.0% | 0.0% | 0.0000/10.0000 | 10 / 0 | none | Exact status reranker_error |

## 2. Retrieval quality

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons |
| :--- | ---: | ---: | :---: | :---: | :--- |
| Document Recall @ 1 | 0.4000 | 0.2857 | 4.0000/14.0000 | 10 / 0 | none |
| Document Recall @ 3 | 1.0000 | 1.0000 | 14.0000/14.0000 | 10 / 0 | none |
| Document Recall @ 5 | 1.0000 | 1.0000 | 14.0000/14.0000 | 10 / 0 | none |
| Document Recall @ 10 | 1.0000 | 1.0000 | 14.0000/14.0000 | 10 / 0 | none |
| Document Recall @ 24 | 1.0000 | 1.0000 | 14.0000/14.0000 | 10 / 0 | none |
| Article Recall @ 1 | 0.7143 | 0.6250 | 5.0000/8.0000 | 7 / 3 | no_applicable_gold=3 |
| Article Recall @ 3 | 0.9286 | 0.8750 | 7.0000/8.0000 | 7 / 3 | no_applicable_gold=3 |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 10 | k_exceeds_configured_capacity=10 |
| Clause Recall @ 1 | 0.7500 | 0.6000 | 3.0000/5.0000 | 4 / 6 | no_applicable_gold=6 |
| Clause Recall @ 3 | 0.8750 | 0.8000 | 4.0000/5.0000 | 4 / 6 | no_applicable_gold=6 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 10 | k_exceeds_configured_capacity=10 |
| Article MRR | 0.8333 | 0.8333 | 5.8333/7.0000 | 7 / 3 | no_applicable_gold=3 |
| Clause MRR | 0.8333 | 0.8333 | 3.3333/4.0000 | 4 / 6 | no_applicable_gold=6 |
| Document MRR | 0.6667 | 0.6667 | 6.6667/10.0000 | 10 / 0 | none |
| nDCG @ 10 | 0.8544 | 0.8104 | 10.1487/12.5237 | 10 / 0 | none |
| Exact legal-reference hit | 1.0000 | 1.0000 | 10.0000/10.0000 | 10 / 0 | none |
| Multi-hop all-required coverage | 1.0000 | 1.0000 | 10.0000/10.0000 | 10 / 0 | none |
| Multi-hop partial coverage | 1.0000 | 1.0000 | 14.0000/14.0000 | 10 / 0 | none |

## 3. Stage metrics

| Pipeline stage | Capacity | Scored cases | Candidate p50 / p95 | Matched / Applicable documents | First-loss evidence count | Null reasons |
| :--- | ---: | ---: | :---: | :---: | ---: | :--- |
| `pinecone_document_metrics` | 48 | 10 | 48.0000 / 48.0000 | 14 / 14 | 0 | stage_does_not_expose_structural_locators=80 |
| `fts_document_metrics` | 48 | 10 | 48.0000 / 48.0000 | 14 / 14 | 0 | stage_does_not_expose_structural_locators=80 |
| `source_retrieval_metrics` | 64 | 10 | 14.0000 / 28.4000 | 14 / 14 | 0 | stage_does_not_expose_structural_locators=80 |
| `merged_document_metrics` | 64 | 10 | 49.5000 / 64.0000 | 14 / 14 | 0 | stage_does_not_expose_structural_locators=80 |
| `resolved_document_metrics` | 64 | 10 | 49.5000 / 64.0000 | 14 / 14 | 0 | stage_does_not_expose_structural_locators=80 |
| `structural_chunk_metrics` | 64 | 10 | 49.5000 / 64.0000 | 14 / 14 | 0 | no_applicable_gold=36 |
| `local_selection_metrics` | N/A | 10 | 49.5000 / 64.0000 | 14 / 14 | 0 | configured_capacity_unknown=110, no_applicable_gold=9 |
| `reranker_input_metrics` | 64 | 10 | 49.5000 / 64.0000 | 14 / 14 | 0 | no_applicable_gold=36 |
| `reranker_output_metrics` | 6 | 10 | 6.0000 / 6.0000 | 14 / 14 | 0 | k_exceeds_configured_capacity=20, no_applicable_gold=36 |
| `final_evidence_metrics` | 5 | 10 | 4.0000 / 5.0000 | 14 / 14 | 0 | k_exceeds_configured_capacity=40, no_applicable_gold=27 |

## 4. Interpretation notes

- Recall@K is undefined when K exceeds the configured stage capacity; nDCG@10 still treats unreturned ranks as zero gain so capacity effects remain measurable.
- Configured provider candidates are provenance only; they do not prove which provider answered a request.

## 5. Deterministic answer metrics

Answer scored / total: `10 / 10`
Answer skip reasons: `none`

| Metric | Value |
| :--- | ---: |
| `answer_similarity_pass_rate` | 0.0000 |
| `unanswerable_accuracy` | N/A |
| `refusal_precision` | N/A |
| `refusal_recall` | N/A |
| `token_f1` | 0.2088 |
| `char_f1` | 0.1967 |
| `rouge_l` | 0.2076 |
| `chrf` | 0.3464 |
| `citation_precision` | N/A |
| `invalid_citation_rate` | N/A |

## 6. Generation, guardrail, and judge coverage

Generation STOP / total: `10 / 10`
Input safe / total: `10 / 10`
Output safe / total: `10 / 10`
Ragas scored / eligible: `10 / 10`
Judge technical errors: `0`

| Ragas metric | Mean | Scored cases |
| :--- | ---: | ---: |
| `faithfulness` | 0.9857 | 10 |
| `answer_accuracy` | 0.9750 | 10 |
| `context_precision` | 0.9400 | 10 |
| `context_recall` | 1.0000 | 10 |

## 7. Latency

| Stage | P50 (s) | P95 (s) | Mean (s) |
| :--- | ---: | ---: | ---: |
| `t_input_guardrail` | 1.2405 | 1.5498 | 1.2802 |
| `t_output_guardrail` | 1.3561 | 1.4925 | 1.3094 |
| `t_retrieval` | 2.5351 | 7.8633 | 3.4849 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 8.9837 | 14.3760 | 9.8849 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_017` | `ok` | `STOP` | `yes` | `none` | 16.5604 |
| `case_036` | `ok` | `STOP` | `yes` | `none` | 9.0304 |
| `case_061` | `ok` | `STOP` | `yes` | `none` | 8.4713 |
| `case_101` | `ok` | `STOP` | `yes` | `none` | 8.8259 |
| `case_165` | `ok` | `STOP` | `yes` | `none` | 7.6709 |
| `case_243` | `ok` | `STOP` | `yes` | `none` | 8.9370 |
| `case_261` | `ok` | `STOP` | `yes` | `none` | 8.9127 |
| `case_323` | `ok` | `STOP` | `yes` | `none` | 9.3414 |
| `case_329` | `ok` | `STOP` | `yes` | `none` | 9.3930 |
| `case_397` | `ok` | `STOP` | `yes` | `none` | 11.7061 |