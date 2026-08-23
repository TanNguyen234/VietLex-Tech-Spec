# VIETLEX EVALUATION REPORT — retrieval-crosslane-b-rep10-20260823

**Run ID**: `retrieval-crosslane-b-rep10-20260823`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-08-23T13:23:06.136681+00:00`  
**Git Commit SHA**: `733f95baa2cb72090ed2e6ab8492ca5ca350baba`  
**Source State SHA-256**: `2fd30a9b885a6e17af33c2e3f445d5f1a9b62e4ea219d0f17362b2c50db15924`  
**Git Dirty Status**: `False` (Diff: `clean`, SHA-256: `N/A`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `b458880e2c2fc4f2813965d57dc96517555488a5ada3702da12fb811f05fb90b`  
**Configuration Fingerprint**: `6ce61fa2f640ddb303801ed49c8f3d74a7ee52c0f689f685e6e8bf73531a70b8`  
**Execution Command**: `run_retrieval_eval.py --case-ids case_017 case_036 case_061 case_101 case_165 case_243 case_261 case_323 case_329 case_397 --verified-only --gold-policy all-required-verified --profile separated_intent --rewrite off --reranker current --concurrency 1 --require-clean-git --run-id retrieval-crosslane-b-rep10-20260823`  
**Evaluation Mode**: `retrieval-only` | **Judge**: `none` | **Guardrails**: `off`  

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
| Article Recall @ 1 | 0.5714 | 0.5000 | 4.0000/8.0000 | 7 / 3 | no_applicable_gold=3 |
| Article Recall @ 3 | 0.9286 | 0.8750 | 7.0000/8.0000 | 7 / 3 | no_applicable_gold=3 |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 10 | k_exceeds_configured_capacity=10 |
| Clause Recall @ 1 | 0.7500 | 0.6000 | 3.0000/5.0000 | 4 / 6 | no_applicable_gold=6 |
| Clause Recall @ 3 | 0.8750 | 0.8000 | 4.0000/5.0000 | 4 / 6 | no_applicable_gold=6 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 10 | k_exceeds_configured_capacity=10 |
| Article MRR | 0.7619 | 0.7619 | 5.3333/7.0000 | 7 / 3 | no_applicable_gold=3 |
| Clause MRR | 0.8750 | 0.8750 | 3.5000/4.0000 | 4 / 6 | no_applicable_gold=6 |
| Document MRR | 0.6667 | 0.6667 | 6.6667/10.0000 | 10 / 0 | none |
| nDCG @ 10 | 0.7807 | 0.7395 | 9.2619/12.5237 | 10 / 0 | none |
| Exact legal-reference hit | 1.0000 | 1.0000 | 10.0000/10.0000 | 10 / 0 | none |
| Multi-hop all-required coverage | 0.9000 | 0.9000 | 9.0000/10.0000 | 10 / 0 | none |
| Multi-hop partial coverage | 0.9500 | 0.9286 | 13.0000/14.0000 | 10 / 0 | none |

## 3. Stage metrics

| Pipeline stage | Capacity | Scored cases | Candidate p50 / p95 | Matched / Applicable documents | First-loss evidence count | Null reasons |
| :--- | ---: | ---: | :---: | :---: | ---: | :--- |
| `pinecone_document_metrics` | 48 | 10 | 72.0000 / 72.0000 | 14 / 14 | 0 | stage_does_not_expose_structural_locators=80 |
| `fts_document_metrics` | 48 | 10 | 60.0000 / 60.0000 | 14 / 14 | 0 | stage_does_not_expose_structural_locators=80 |
| `source_retrieval_metrics` | 64 | 10 | 49.0000 / 62.9500 | 14 / 14 | 0 | stage_does_not_expose_structural_locators=80 |
| `merged_document_metrics` | 64 | 10 | 61.5000 / 76.0000 | 14 / 14 | 0 | stage_does_not_expose_structural_locators=80 |
| `resolved_document_metrics` | 64 | 10 | 65.5000 / 80.0000 | 14 / 14 | 0 | stage_does_not_expose_structural_locators=80 |
| `structural_chunk_metrics` | 64 | 10 | 832.5000 / 1771.5500 | 14 / 14 | 0 | no_applicable_gold=36 |
| `local_selection_metrics` | N/A | 10 | 108.0000 / 124.5500 | 14 / 14 | 0 | configured_capacity_unknown=110, no_applicable_gold=9 |
| `reranker_input_metrics` | 64 | 10 | 73.5000 / 88.0000 | 14 / 14 | 0 | no_applicable_gold=36 |
| `reranker_output_metrics` | 6 | 10 | 9.0000 / 9.0000 | 14 / 14 | 0 | k_exceeds_configured_capacity=20, no_applicable_gold=36 |
| `final_evidence_metrics` | 5 | 10 | 3.0000 / 3.0000 | 14 / 14 | 1 | k_exceeds_configured_capacity=40, no_applicable_gold=27 |

## 4. Interpretation notes

- Recall@K is undefined when K exceeds the configured stage capacity; nDCG@10 still treats unreturned ranks as zero gain so capacity effects remain measurable.
- Configured provider candidates are provenance only; they do not prove which provider answered a request.

## 6. Generation, guardrail, and judge coverage

Generation STOP / total: `0 / 10`
Input safe / total: `0 / 10`
Output safe / total: `0 / 10`
Ragas scored / eligible: `0 / 10`
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
| `t_retrieval` | 6.6749 | 15.6846 | 8.3060 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 6.6749 | 15.6846 | 8.3060 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_017` | `ok` | `N/A` | `no` | `none` | 21.9852 |
| `case_036` | `ok` | `N/A` | `no` | `none` | 7.6618 |
| `case_061` | `ok` | `N/A` | `no` | `none` | 5.5565 |
| `case_101` | `ok` | `N/A` | `no` | `none` | 6.7778 |
| `case_165` | `ok` | `N/A` | `no` | `none` | 7.9795 |
| `case_243` | `ok` | `N/A` | `no` | `none` | 7.9839 |
| `case_261` | `ok` | `N/A` | `no` | `none` | 6.5231 |
| `case_323` | `ok` | `N/A` | `no` | `none` | 6.0742 |
| `case_329` | `ok` | `N/A` | `no` | `none` | 6.5721 |
| `case_397` | `ok` | `N/A` | `no` | `none` | 5.9459 |