# VIETLEX EVALUATION REPORT — answer-v3-golden50-expanded14962-rrf-dbsf-20260903

**Run ID**: `answer-v3-golden50-expanded14962-rrf-dbsf-20260903`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-09-03T12:48:25.201636+00:00`  
**Git Commit SHA**: `bf60d290716249dcf65835c7e2f149e887a61b3f`  
**Source State SHA-256**: `4d6a5fc5dc660751a7da87c84bf185d608f5f262042921d58bc8a161ed85c506`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `b98ded5a0c31694ca9e3b8ea852bab6b859fec79a24a1a11641cebd659eb5a68`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `caa3fc19cd22bcce4b87e96adf13544d0c3cc174cca2d0e365a848e0da9a981f`  
**Configuration Fingerprint**: `d6a3bf314a11ff61f68220c35b0ecee1704b7c03d8c962d6564b29c055c9e889`  
**Execution Command**: `run_answer_eval.py --dataset docs/evaluation/golden50-v3/cases.json --sidecar docs/evaluation/golden50-v3/labels.json --backend vertex-qdrant-v3 --ranking rrf-dbsf --profile separated_intent --rewrite off --reranker current --concurrency 1 --gold-policy none --guardrails enforce --judge ragas --retrieval-run docs/evaluation/runs/retrieval-v3-golden50-expanded14962-rrf-dbsf-20260903 --run-id answer-v3-golden50-expanded14962-rrf-dbsf-20260903`  
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
| Document Recall @ 1 | 0.9000 | 0.8679 | 46.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 3 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 5 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 10 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 24 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Article Recall @ 1 | 0.8148 | 0.8000 | 24.0000/30.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Article Recall @ 3 | 0.9630 | 0.9667 | 29.0000/30.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 50 | k_exceeds_configured_capacity=40, no_verified_gold_label=10 |
| Clause Recall @ 1 | 0.7308 | 0.7143 | 10.0000/14.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Clause Recall @ 3 | 0.9231 | 0.9286 | 13.0000/14.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 50 | k_exceeds_configured_capacity=40, no_verified_gold_label=10 |
| Article MRR | 0.9074 | 0.9074 | 24.5000/27.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Clause MRR | 0.8462 | 0.8462 | 11.0000/13.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Document MRR | 0.9500 | 0.9500 | 38.0000/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| nDCG @ 10 | 0.9025 | 0.8777 | 42.3093/48.2021 | 40 / 10 | no_verified_gold_label=10 |
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
| `token_f1` | 0.2305 |
| `char_f1` | 0.2230 |
| `rouge_l` | 0.2197 |
| `chrf` | 0.3765 |
| `citation_precision` | 0.9183 |
| `invalid_citation_rate` | 0.0817 |

## 6. Generation, guardrail, and judge coverage

Generation STOP / total: `50 / 50`
Input safe / total: `50 / 50`
Output safe / total: `50 / 50`
Ragas scored / eligible: `50 / 50`
Judge technical errors: `0`

| Ragas metric | Mean | Scored cases |
| :--- | ---: | ---: |
| `faithfulness` | 0.8221 | 50 |
| `answer_accuracy` | 0.9100 | 50 |
| `context_precision` | 0.8600 | 50 |
| `context_recall` | 0.9500 | 50 |

## 7. Latency

| Stage | P50 (s) | P95 (s) | Mean (s) |
| :--- | ---: | ---: | ---: |
| `t_input_guardrail` | 1.1634 | 1.5169 | 1.1850 |
| `t_output_guardrail` | 1.2050 | 1.4412 | 1.2266 |
| `t_retrieval` | 1.4103 | 3.3656 | 2.2066 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 5.7999 | 6.8331 | 5.7633 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_001` | `ok` | `STOP` | `yes` | `none` | 5.4587 |
| `case_002` | `ok` | `STOP` | `yes` | `none` | 5.2790 |
| `case_003` | `ok` | `STOP` | `yes` | `none` | 5.3955 |
| `case_004` | `ok` | `STOP` | `yes` | `none` | 6.4418 |
| `case_005` | `ok` | `STOP` | `yes` | `none` | 5.4806 |
| `case_006` | `ok` | `STOP` | `yes` | `none` | 5.2955 |
| `case_007` | `ok` | `STOP` | `yes` | `none` | 7.3600 |
| `case_008` | `ok` | `STOP` | `yes` | `none` | 4.5179 |
| `case_009` | `ok` | `STOP` | `yes` | `none` | 6.2605 |
| `case_010` | `ok` | `STOP` | `yes` | `none` | 6.0620 |
| `case_011` | `ok` | `STOP` | `yes` | `none` | 5.8919 |
| `case_012` | `ok` | `STOP` | `yes` | `none` | 5.8118 |
| `case_013` | `ok` | `STOP` | `yes` | `none` | 5.1933 |
| `case_014` | `ok` | `STOP` | `yes` | `none` | 5.0085 |
| `case_015` | `ok` | `STOP` | `yes` | `none` | 6.1404 |
| `case_016` | `ok` | `STOP` | `yes` | `none` | 6.0683 |
| `case_017` | `ok` | `STOP` | `yes` | `none` | 4.6488 |
| `case_018` | `ok` | `STOP` | `yes` | `none` | 6.6770 |
| `case_019` | `ok` | `STOP` | `yes` | `none` | 6.9150 |
| `case_020` | `ok` | `STOP` | `yes` | `none` | 6.0771 |
| `case_021` | `ok` | `STOP` | `yes` | `none` | 5.2486 |
| `case_022` | `ok` | `STOP` | `yes` | `none` | 4.9591 |
| `case_023` | `ok` | `STOP` | `yes` | `none` | 6.7330 |
| `case_024` | `ok` | `STOP` | `yes` | `none` | 4.9053 |
| `case_025` | `ok` | `STOP` | `yes` | `none` | 5.6121 |
| `case_026` | `ok` | `STOP` | `yes` | `none` | 6.3790 |
| `case_027` | `ok` | `STOP` | `yes` | `none` | 5.5595 |
| `case_028` | `ok` | `STOP` | `yes` | `none` | 6.7272 |
| `case_029` | `ok` | `STOP` | `yes` | `none` | 7.1785 |
| `case_030` | `ok` | `STOP` | `yes` | `none` | 5.8998 |
| `case_031` | `ok` | `STOP` | `yes` | `none` | 5.3482 |
| `case_032` | `ok` | `STOP` | `yes` | `none` | 5.1589 |
| `case_033` | `ok` | `STOP` | `yes` | `none` | 6.2643 |
| `case_034` | `ok` | `STOP` | `yes` | `none` | 5.7979 |
| `case_035` | `ok` | `STOP` | `yes` | `none` | 4.7224 |
| `case_036` | `ok` | `STOP` | `yes` | `none` | 4.6780 |
| `case_037` | `ok` | `STOP` | `yes` | `none` | 6.5771 |
| `case_038` | `ok` | `STOP` | `yes` | `none` | 5.1448 |
| `case_039` | `ok` | `STOP` | `yes` | `none` | 5.0228 |
| `case_040` | `ok` | `STOP` | `yes` | `none` | 6.0529 |
| `case_041` | `ok` | `STOP` | `yes` | `none` | 5.0686 |
| `case_042` | `ok` | `STOP` | `yes` | `none` | 6.0847 |
| `case_043` | `ok` | `STOP` | `yes` | `none` | 5.7518 |
| `case_044` | `ok` | `STOP` | `yes` | `none` | 5.0397 |
| `case_045` | `ok` | `STOP` | `yes` | `none` | 5.8019 |
| `case_046` | `ok` | `STOP` | `yes` | `none` | 4.9449 |
| `case_047` | `ok` | `STOP` | `yes` | `none` | 6.6487 |
| `case_048` | `ok` | `STOP` | `yes` | `none` | 6.6266 |
| `case_049` | `ok` | `STOP` | `yes` | `none` | 6.0417 |
| `case_050` | `ok` | `STOP` | `yes` | `none` | 6.2051 |