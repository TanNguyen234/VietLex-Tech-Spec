# VIETLEX EVALUATION REPORT — retrieval-v3-golden50-expanded14962-colbert-live-20260903

**Run ID**: `retrieval-v3-golden50-expanded14962-colbert-live-20260903`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-09-03T11:35:17.816974+00:00`  
**Git Commit SHA**: `bf60d290716249dcf65835c7e2f149e887a61b3f`  
**Source State SHA-256**: `9c2742a23b4c9f15ce1d8b3720908f724db99aab28a62070eca61aefc9ee14d0`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `771cc7bc34e767404a9011ffd0a38a9ce6783e712c0f5a4165c340557fcad58d`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `caa3fc19cd22bcce4b87e96adf13544d0c3cc174cca2d0e365a848e0da9a981f`  
**Configuration Fingerprint**: `87af37f64b7f130eec66b5d051756077caa73a0754466d081d7ea0997b4641d7`  
**Execution Command**: `run_retrieval_eval.py --dataset docs/evaluation/golden50-v3/cases.json --sidecar docs/evaluation/golden50-v3/labels.json --backend vertex-qdrant-v3 --ranking qdrant-colbert --profile separated_intent --rewrite off --reranker current --concurrency 1 --gold-policy none --run-id retrieval-v3-golden50-expanded14962-colbert-live-20260903`  
**Evaluation Mode**: `retrieval-only` | **Judge**: `none` | **Guardrails**: `off`  

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
| Document Recall @ 1 | 0.8750 | 0.8491 | 45.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 3 | 0.9750 | 0.9623 | 51.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 5 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 10 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Document Recall @ 24 | 1.0000 | 1.0000 | 53.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |
| Article Recall @ 1 | 0.5000 | 0.5000 | 15.0000/30.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Article Recall @ 3 | 0.8519 | 0.8333 | 25.0000/30.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 50 | k_exceeds_configured_capacity=40, no_verified_gold_label=10 |
| Clause Recall @ 1 | 0.1538 | 0.1429 | 2.0000/14.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Clause Recall @ 3 | 0.7692 | 0.7143 | 10.0000/14.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 50 | k_exceeds_configured_capacity=40, no_verified_gold_label=10 |
| Article MRR | 0.6914 | 0.6914 | 18.6667/27.0000 | 27 / 23 | no_applicable_gold=13, no_verified_gold_label=10 |
| Clause MRR | 0.4359 | 0.4359 | 5.6667/13.0000 | 13 / 37 | no_applicable_gold=27, no_verified_gold_label=10 |
| Document MRR | 0.9300 | 0.9300 | 37.2000/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| nDCG @ 10 | 0.6740 | 0.6419 | 30.9402/48.2021 | 40 / 10 | no_verified_gold_label=10 |
| Exact legal-reference hit | 0.8500 | 0.8500 | 34.0000/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| Multi-hop all-required coverage | 0.8000 | 0.8000 | 32.0000/40.0000 | 40 / 10 | no_verified_gold_label=10 |
| Multi-hop partial coverage | 0.8250 | 0.7925 | 42.0000/53.0000 | 40 / 10 | no_verified_gold_label=10 |

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
| `reranker_output_metrics` | 3 | 40 | 3.0000 / 3.0000 | 47 / 53 | 0 | k_exceeds_configured_capacity=200, no_applicable_gold=120, no_verified_gold_label=140 |
| `final_evidence_metrics` | 3 | 40 | 3.0000 / 3.0000 | 47 / 53 | 0 | k_exceeds_configured_capacity=200, no_applicable_gold=120, no_verified_gold_label=140 |

## 4. Interpretation notes

- Recall@K is undefined when K exceeds the configured stage capacity; nDCG@10 still treats unreturned ranks as zero gain so capacity effects remain measurable.
- Configured provider candidates are provenance only; they do not prove which provider answered a request.

## 6. Generation, guardrail, and judge coverage

Generation STOP / total: `0 / 50`
Input safe / total: `0 / 50`
Output safe / total: `0 / 50`
Ragas scored / eligible: `0 / 40`
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
| `t_retrieval` | 3.6633 | 5.1942 | 4.1796 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 3.6634 | 5.1942 | 4.1796 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_001` | `ok` | `N/A` | `no` | `none` | 22.3029 |
| `case_002` | `ok` | `N/A` | `no` | `none` | 3.9664 |
| `case_003` | `ok` | `N/A` | `no` | `none` | 3.4514 |
| `case_004` | `ok` | `N/A` | `no` | `none` | 3.7242 |
| `case_005` | `ok` | `N/A` | `no` | `none` | 3.7779 |
| `case_006` | `ok` | `N/A` | `no` | `none` | 3.7582 |
| `case_007` | `ok` | `N/A` | `no` | `none` | 3.4435 |
| `case_008` | `ok` | `N/A` | `no` | `none` | 3.7309 |
| `case_009` | `ok` | `N/A` | `no` | `none` | 5.2181 |
| `case_010` | `ok` | `N/A` | `no` | `none` | 5.8317 |
| `case_011` | `ok` | `N/A` | `no` | `none` | 4.4290 |
| `case_012` | `ok` | `N/A` | `no` | `none` | 3.3430 |
| `case_013` | `ok` | `N/A` | `no` | `none` | 3.9870 |
| `case_014` | `ok` | `N/A` | `no` | `none` | 3.3075 |
| `case_015` | `ok` | `N/A` | `no` | `none` | 3.4742 |
| `case_016` | `ok` | `N/A` | `no` | `none` | 3.7694 |
| `case_017` | `ok` | `N/A` | `no` | `none` | 4.2294 |
| `case_018` | `ok` | `N/A` | `no` | `none` | 3.4328 |
| `case_019` | `ok` | `N/A` | `no` | `none` | 3.2888 |
| `case_020` | `ok` | `N/A` | `no` | `none` | 3.5883 |
| `case_021` | `ok` | `N/A` | `no` | `none` | 3.5550 |
| `case_022` | `ok` | `N/A` | `no` | `none` | 3.5664 |
| `case_023` | `ok` | `N/A` | `no` | `none` | 3.8610 |
| `case_024` | `ok` | `N/A` | `no` | `none` | 3.7154 |
| `case_025` | `ok` | `N/A` | `no` | `none` | 4.2407 |
| `case_026` | `ok` | `N/A` | `no` | `none` | 4.5595 |
| `case_027` | `ok` | `N/A` | `no` | `none` | 3.5788 |
| `case_028` | `ok` | `N/A` | `no` | `none` | 3.6387 |
| `case_029` | `ok` | `N/A` | `no` | `none` | 3.4169 |
| `case_030` | `ok` | `N/A` | `no` | `none` | 3.4049 |
| `case_031` | `ok` | `N/A` | `no` | `none` | 3.8759 |
| `case_032` | `ok` | `N/A` | `no` | `none` | 3.7984 |
| `case_033` | `ok` | `N/A` | `no` | `none` | 4.9221 |
| `case_034` | `ok` | `N/A` | `no` | `none` | 5.1650 |
| `case_035` | `ok` | `N/A` | `no` | `none` | 3.3686 |
| `case_036` | `ok` | `N/A` | `no` | `none` | 3.7192 |
| `case_037` | `ok` | `N/A` | `no` | `none` | 3.4204 |
| `case_038` | `ok` | `N/A` | `no` | `none` | 3.5840 |
| `case_039` | `ok` | `N/A` | `no` | `none` | 3.2904 |
| `case_040` | `ok` | `N/A` | `no` | `none` | 3.6002 |
| `case_041` | `ok` | `N/A` | `no` | `none` | 3.4936 |
| `case_042` | `ok` | `N/A` | `no` | `none` | 3.5604 |
| `case_043` | `ok` | `N/A` | `no` | `none` | 4.2660 |
| `case_044` | `ok` | `N/A` | `no` | `none` | 3.5627 |
| `case_045` | `ok` | `N/A` | `no` | `none` | 3.7357 |
| `case_046` | `ok` | `N/A` | `no` | `none` | 3.5321 |
| `case_047` | `ok` | `N/A` | `no` | `none` | 3.6880 |
| `case_048` | `ok` | `N/A` | `no` | `none` | 3.8576 |
| `case_049` | `ok` | `N/A` | `no` | `none` | 3.4009 |
| `case_050` | `ok` | `N/A` | `no` | `none` | 3.5489 |