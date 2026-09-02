# VIETLEX EVALUATION REPORT — preflight-case017-final-test

**Run ID**: `preflight-case017-final-test`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-08-26T12:55:13.362947+00:00`  
**Git Commit SHA**: `aa76cf855699d6fd98f94b73b84cc20fb3cf9112`  
**Source State SHA-256**: `497289fa0106070acd6269cf9984d98cb629b4724b41f368e12d47388dd56192`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `8a223ca3a2651b818fddafe5a5b2bd7086b4626119f23777e8276d863476d981`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `d6e125030e8dda700667ba00f25162fac76472a9bfa2d087f54e2b5bc73a1fee`  
**Configuration Fingerprint**: `787542c468f3580e77d0187db9fc8453750852cdfe0d85c94d5bae5bc39ec686`  
**Execution Command**: `run_answer_eval.py --case-ids case_017 --gold-policy none --profile separated_intent --rewrite off --guardrails enforce --reranker current --concurrency 1 --judge ragas --run-id preflight-case017-final-test`  
**Evaluation Mode**: `answer` | **Judge**: `ragas` | **Guardrails**: `enforce`  

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
| Document Recall @ 1 | 0.0000 | 0.0000 | 0.0000/1.0000 | 1 / 0 | none |
| Document Recall @ 3 | 0.0000 | 0.0000 | 0.0000/1.0000 | 1 / 0 | none |
| Document Recall @ 5 | 0.0000 | 0.0000 | 0.0000/1.0000 | 1 / 0 | none |
| Document Recall @ 10 | 0.0000 | 0.0000 | 0.0000/1.0000 | 1 / 0 | none |
| Document Recall @ 24 | 0.0000 | 0.0000 | 0.0000/1.0000 | 1 / 0 | none |
| Article Recall @ 1 | 0.0000 | 0.0000 | 0.0000/1.0000 | 1 / 0 | none |
| Article Recall @ 3 | 0.0000 | 0.0000 | 0.0000/1.0000 | 1 / 0 | none |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | k_exceeds_configured_capacity=1 |
| Clause Recall @ 1 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | no_applicable_gold=1 |
| Clause Recall @ 3 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | no_applicable_gold=1 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | k_exceeds_configured_capacity=1 |
| Article MRR | 0.0000 | 0.0000 | 0.0000/1.0000 | 1 / 0 | none |
| Clause MRR | N/A | N/A | 0.0000/0.0000 | 0 / 1 | no_applicable_gold=1 |
| Document MRR | 0.0000 | 0.0000 | 0.0000/1.0000 | 1 / 0 | none |
| nDCG @ 10 | 0.0000 | 0.0000 | 0.0000/1.0000 | 1 / 0 | none |
| Exact legal-reference hit | 0.0000 | 0.0000 | 0.0000/1.0000 | 1 / 0 | none |
| Multi-hop all-required coverage | 0.0000 | 0.0000 | 0.0000/1.0000 | 1 / 0 | none |
| Multi-hop partial coverage | 0.0000 | 0.0000 | 0.0000/1.0000 | 1 / 0 | none |

## 3. Stage metrics

| Pipeline stage | Capacity | Scored cases | Candidate p50 / p95 | Matched / Applicable documents | First-loss evidence count | Null reasons |
| :--- | ---: | ---: | :---: | :---: | ---: | :--- |
| `pinecone_document_metrics` | 24 | 1 | 24.0000 / 24.0000 | 0 / 1 | 0 | stage_does_not_expose_structural_locators=8 |
| `fts_document_metrics` | 12 | 1 | 12.0000 / 12.0000 | 0 / 1 | 0 | k_exceeds_configured_capacity=1, stage_does_not_expose_structural_locators=8 |
| `source_retrieval_metrics` | 36 | 1 | 33.0000 / 33.0000 | 0 / 1 | 1 | stage_does_not_expose_structural_locators=8 |
| `merged_document_metrics` | 36 | 1 | 12.0000 / 12.0000 | 0 / 1 | 0 | stage_does_not_expose_structural_locators=8 |
| `resolved_document_metrics` | 16 | 1 | 16.0000 / 16.0000 | 0 / 1 | 0 | k_exceeds_configured_capacity=1, stage_does_not_expose_structural_locators=8 |
| `structural_chunk_metrics` | N/A | 1 | 349.0000 / 349.0000 | 0 / 1 | 0 | configured_capacity_unknown=11, no_applicable_gold=1 |
| `local_selection_metrics` | 64 | 1 | 59.0000 / 59.0000 | 0 / 1 | 0 | no_applicable_gold=4 |
| `reranker_input_metrics` | 24 | 1 | 24.0000 / 24.0000 | 0 / 1 | 0 | no_applicable_gold=4 |
| `reranker_output_metrics` | 3 | 1 | 3.0000 / 3.0000 | 0 / 1 | 0 | k_exceeds_configured_capacity=5, no_applicable_gold=3 |
| `final_evidence_metrics` | 3 | 1 | 3.0000 / 3.0000 | 0 / 1 | 0 | k_exceeds_configured_capacity=5, no_applicable_gold=3 |

## 4. Interpretation notes

- Recall@K is undefined when K exceeds the configured stage capacity; nDCG@10 still treats unreturned ranks as zero gain so capacity effects remain measurable.
- Configured provider candidates are provenance only; they do not prove which provider answered a request.

## 5. Deterministic answer metrics

Answer scored / total: `1 / 1`
Answer skip reasons: `none`

| Metric | Value |
| :--- | ---: |
| `answer_similarity_pass_rate` | 0.0000 |
| `unanswerable_accuracy` | N/A |
| `refusal_precision` | N/A |
| `refusal_recall` | N/A |
| `token_f1` | 0.0706 |
| `char_f1` | 0.0783 |
| `rouge_l` | 0.0647 |
| `chrf` | 0.1416 |
| `citation_precision` | N/A |
| `invalid_citation_rate` | N/A |

## 6. Generation, guardrail, and judge coverage

Generation STOP / total: `1 / 1`
Input safe / total: `1 / 1`
Output safe / total: `1 / 1`
Ragas scored / eligible: `1 / 1`
Judge technical errors: `0`

| Ragas metric | Mean | Scored cases |
| :--- | ---: | ---: |
| `faithfulness` | 0.9091 | 1 |
| `answer_accuracy` | 0.5000 | 1 |
| `context_precision` | 0.0000 | 1 |
| `context_recall` | 0.0000 | 1 |

## 7. Latency

| Stage | P50 (s) | P95 (s) | Mean (s) |
| :--- | ---: | ---: | ---: |
| `t_input_guardrail` | 1.5857 | 1.5857 | 1.5857 |
| `t_output_guardrail` | 1.3165 | 1.3165 | 1.3165 |
| `t_retrieval` | 14.6877 | 14.6877 | 14.6877 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 21.0018 | 21.0018 | 21.0018 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_017` | `ok` | `STOP` | `yes` | `none` | 21.0018 |