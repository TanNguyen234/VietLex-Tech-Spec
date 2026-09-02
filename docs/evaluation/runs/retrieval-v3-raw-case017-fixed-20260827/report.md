# VIETLEX EVALUATION REPORT — retrieval-v3-raw-case017-fixed-20260827

**Run ID**: `retrieval-v3-raw-case017-fixed-20260827`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-08-27T10:47:11.701581+00:00`  
**Git Commit SHA**: `unknown_git_sha`  
**Source State SHA-256**: `unavailable`  
**Git Dirty Status**: `False` (Diff: `unavailable`, SHA-256: `N/A`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `d6e125030e8dda700667ba00f25162fac76472a9bfa2d087f54e2b5bc73a1fee`  
**Configuration Fingerprint**: `dedbbbf0aa66844ba8a290c444a7f215f90d2adf64d55fe67f7f1a29443cdddb`  
**Execution Command**: `run_retrieval_eval.py --case-ids case_017 --backend vertex-qdrant-v3 --ranking raw-rrf --profile separated_intent --rewrite off --reranker current --concurrency 1 --gold-policy none --run-id retrieval-v3-raw-case017-fixed-20260827`  
**Evaluation Mode**: `retrieval-only` | **Judge**: `none` | **Guardrails**: `off`  

Metric schema: `3.0.0`
Scored / Total: `1 / 1`
Skipped cases: `0`
Skip reasons: `none`

## 1. Reliability and coverage

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons | Notes |
| :--- | ---: | ---: | :---: | :---: | :--- | :--- |
| Scored gold coverage | 100.0% | 100.0% | 1.0000/1.0000 | 1 / 0 | none | Cases with applicable verified required evidence |
| No-candidate rate | 0.0% | 0.0% | 0.0000/1.0000 | 1 / 0 | none | Completed retrievals with zero candidates |
| Retrieval technical-error rate | 0.0% | 0.0% | 0.0000/1.0000 | 1 / 0 | none | Status retrieval_error or partial_retrieval_error |
| Reranker technical-error rate | 0.0% | 0.0% | 0.0000/1.0000 | 1 / 0 | none | Exact status reranker_error |

## 2. Retrieval quality

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons |
| :--- | ---: | ---: | :---: | :---: | :--- |
| Document Recall @ 1 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | configured_capacity_unknown=1 |
| Document Recall @ 3 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | configured_capacity_unknown=1 |
| Document Recall @ 5 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | configured_capacity_unknown=1 |
| Document Recall @ 10 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | configured_capacity_unknown=1 |
| Document Recall @ 24 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | configured_capacity_unknown=1 |
| Article Recall @ 1 | 1.0000 | 1.0000 | 1.0000/1.0000 | 1 / 0 | none |
| Article Recall @ 3 | 1.0000 | 1.0000 | 1.0000/1.0000 | 1 / 0 | none |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | k_exceeds_configured_capacity=1 |
| Clause Recall @ 1 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | no_applicable_gold=1 |
| Clause Recall @ 3 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | no_applicable_gold=1 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | k_exceeds_configured_capacity=1 |
| Article MRR | 1.0000 | 1.0000 | 1.0000/1.0000 | 1 / 0 | none |
| Clause MRR | N/A | N/A | 0.0000/0.0000 | 0 / 1 | no_applicable_gold=1 |
| Document MRR | 0.0000 | 0.0000 | 0.0000/1.0000 | 1 / 0 | none |
| nDCG @ 10 | 1.0000 | 1.0000 | 1.0000/1.0000 | 1 / 0 | none |
| Exact legal-reference hit | 1.0000 | 1.0000 | 1.0000/1.0000 | 1 / 0 | none |
| Multi-hop all-required coverage | 1.0000 | 1.0000 | 1.0000/1.0000 | 1 / 0 | none |
| Multi-hop partial coverage | 1.0000 | 1.0000 | 1.0000/1.0000 | 1 / 0 | none |

## 3. Stage metrics

| Pipeline stage | Capacity | Scored cases | Candidate p50 / p95 | Matched / Applicable documents | First-loss evidence count | Null reasons |
| :--- | ---: | ---: | :---: | :---: | ---: | :--- |
| `pinecone_document_metrics` | N/A | 1 | 0.0000 / 0.0000 | 0 / 1 | 0 | configured_capacity_unknown=5, stage_does_not_expose_structural_locators=8 |
| `fts_document_metrics` | N/A | 1 | 0.0000 / 0.0000 | 0 / 1 | 0 | configured_capacity_unknown=5, stage_does_not_expose_structural_locators=8 |
| `source_retrieval_metrics` | N/A | 1 | 0.0000 / 0.0000 | 0 / 1 | 1 | configured_capacity_unknown=5, stage_does_not_expose_structural_locators=8 |
| `merged_document_metrics` | N/A | 1 | 0.0000 / 0.0000 | 0 / 1 | 0 | configured_capacity_unknown=5, stage_does_not_expose_structural_locators=8 |
| `resolved_document_metrics` | N/A | 1 | 0.0000 / 0.0000 | 0 / 1 | 0 | configured_capacity_unknown=5, stage_does_not_expose_structural_locators=8 |
| `structural_chunk_metrics` | 24 | 1 | 24.0000 / 24.0000 | 1 / 1 | 0 | no_applicable_gold=4 |
| `local_selection_metrics` | N/A | 1 | 0.0000 / 0.0000 | 0 / 1 | 0 | configured_capacity_unknown=11, no_applicable_gold=1 |
| `reranker_input_metrics` | 24 | 1 | 24.0000 / 24.0000 | 1 / 1 | 0 | no_applicable_gold=4 |
| `reranker_output_metrics` | 3 | 1 | 3.0000 / 3.0000 | 1 / 1 | 0 | k_exceeds_configured_capacity=5, no_applicable_gold=3 |
| `final_evidence_metrics` | 3 | 1 | 3.0000 / 3.0000 | 1 / 1 | 0 | k_exceeds_configured_capacity=5, no_applicable_gold=3 |

## 4. Interpretation notes

- Recall@K is undefined when K exceeds the configured stage capacity; nDCG@10 still treats unreturned ranks as zero gain so capacity effects remain measurable.
- Configured provider candidates are provenance only; they do not prove which provider answered a request.

## 6. Generation, guardrail, and judge coverage

Generation STOP / total: `0 / 1`
Input safe / total: `0 / 1`
Output safe / total: `0 / 1`
Ragas scored / eligible: `0 / 1`
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
| `t_retrieval` | 23.3291 | 23.3291 | 23.3291 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 23.3292 | 23.3292 | 23.3292 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_017` | `ok` | `N/A` | `no` | `none` | 23.3292 |