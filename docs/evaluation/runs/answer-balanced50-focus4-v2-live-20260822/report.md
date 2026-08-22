# VIETLEX EVALUATION REPORT — answer-balanced50-focus4-v2-live-20260822

**Run ID**: `answer-balanced50-focus4-v2-live-20260822`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-08-22T14:53:53.445789+00:00`  
**Git Commit SHA**: `6dd558c3e163941690eb9a75490c886a898d52d5`  
**Source State SHA-256**: `19a37f4d7f58ec97e1d55fd588c4e8329bcc881e9adb14c69cf2645c33ba6fcc`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `fd68462d142a112a299ab0b432b50e37031ed5cf0c390507e25d359538489e94`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `b458880e2c2fc4f2813965d57dc96517555488a5ada3702da12fb811f05fb90b`  
**Configuration Fingerprint**: `76346edbb8f7ff4cb8d36a87432451c6552f75bdc896be56d3f25b978480283b`  
**Execution Command**: `run_answer_eval.py --case-ids case_021 case_031 case_183 case_325 --gold-policy none --profile separated_intent --rewrite off --guardrails enforce --reranker current --concurrency 1 --judge ragas --run-id answer-balanced50-focus4-v2-live-20260822`  
**Evaluation Mode**: `answer` | **Judge**: `ragas` | **Guardrails**: `enforce`  

Metric schema: `3.0.0`
Scored / Total: `2 / 4`
Skipped cases: `2`
Skip reasons: `no_verified_gold_label=2`

## 1. Reliability and coverage

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons | Notes |
| :--- | ---: | ---: | :---: | :---: | :--- | :--- |
| Scored gold coverage | 50.0% | 50.0% | 2.0000/4.0000 | 4 / 0 | no_verified_gold_label=2 | Cases with applicable verified required evidence |
| No-candidate rate | 0.0% | 0.0% | 0.0000/4.0000 | 4 / 0 | none | Completed retrievals with zero candidates |
| Retrieval technical-error rate | 0.0% | 0.0% | 0.0000/4.0000 | 4 / 0 | none | Status retrieval_error or partial_retrieval_error |
| Reranker technical-error rate | 0.0% | 0.0% | 0.0000/4.0000 | 4 / 0 | none | Exact status reranker_error |

## 2. Retrieval quality

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons |
| :--- | ---: | ---: | :---: | :---: | :--- |
| Document Recall @ 1 | 0.5000 | 0.6667 | 2.0000/3.0000 | 2 / 2 | no_verified_gold_label=2 |
| Document Recall @ 3 | 1.0000 | 1.0000 | 3.0000/3.0000 | 2 / 2 | no_verified_gold_label=2 |
| Document Recall @ 5 | 1.0000 | 1.0000 | 3.0000/3.0000 | 2 / 2 | no_verified_gold_label=2 |
| Document Recall @ 10 | 1.0000 | 1.0000 | 3.0000/3.0000 | 2 / 2 | no_verified_gold_label=2 |
| Document Recall @ 24 | 1.0000 | 1.0000 | 3.0000/3.0000 | 2 / 2 | no_verified_gold_label=2 |
| Article Recall @ 1 | 0.0000 | 0.0000 | 0.0000/1.0000 | 1 / 3 | no_applicable_gold=1, no_verified_gold_label=2 |
| Article Recall @ 3 | 1.0000 | 1.0000 | 1.0000/1.0000 | 1 / 3 | no_applicable_gold=1, no_verified_gold_label=2 |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 4 | k_exceeds_configured_capacity=2, no_verified_gold_label=2 |
| Clause Recall @ 1 | N/A | N/A | 0.0000/0.0000 | 0 / 4 | no_applicable_gold=2, no_verified_gold_label=2 |
| Clause Recall @ 3 | N/A | N/A | 0.0000/0.0000 | 0 / 4 | no_applicable_gold=2, no_verified_gold_label=2 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 4 | k_exceeds_configured_capacity=2, no_verified_gold_label=2 |
| Article MRR | 0.5000 | 0.5000 | 0.5000/1.0000 | 1 / 3 | no_applicable_gold=1, no_verified_gold_label=2 |
| Clause MRR | N/A | N/A | 0.0000/0.0000 | 0 / 4 | no_applicable_gold=2, no_verified_gold_label=2 |
| Document MRR | 0.7500 | 0.7500 | 1.5000/2.0000 | 2 / 2 | no_verified_gold_label=2 |
| nDCG @ 10 | 1.0000 | 1.0000 | 2.6309/2.6309 | 2 / 2 | no_verified_gold_label=2 |
| Exact legal-reference hit | 1.0000 | 1.0000 | 2.0000/2.0000 | 2 / 2 | no_verified_gold_label=2 |
| Multi-hop all-required coverage | 1.0000 | 1.0000 | 2.0000/2.0000 | 2 / 2 | no_verified_gold_label=2 |
| Multi-hop partial coverage | 1.0000 | 1.0000 | 3.0000/3.0000 | 2 / 2 | no_verified_gold_label=2 |

## 3. Stage metrics

| Pipeline stage | Capacity | Scored cases | Candidate p50 / p95 | Matched / Applicable documents | First-loss evidence count | Null reasons |
| :--- | ---: | ---: | :---: | :---: | ---: | :--- |
| `pinecone_document_metrics` | 48 | 2 | 48.0000 / 48.0000 | 3 / 3 | 0 | no_verified_gold_label=28, stage_does_not_expose_structural_locators=16 |
| `fts_document_metrics` | 48 | 2 | 48.0000 / 48.0000 | 3 / 3 | 0 | no_verified_gold_label=28, stage_does_not_expose_structural_locators=16 |
| `source_retrieval_metrics` | 64 | 2 | 21.0000 / 24.8500 | 3 / 3 | 0 | no_verified_gold_label=28, stage_does_not_expose_structural_locators=16 |
| `merged_document_metrics` | 64 | 2 | 61.5000 / 63.8500 | 3 / 3 | 0 | no_verified_gold_label=28, stage_does_not_expose_structural_locators=16 |
| `resolved_document_metrics` | 64 | 2 | 61.5000 / 63.8500 | 3 / 3 | 0 | no_verified_gold_label=28, stage_does_not_expose_structural_locators=16 |
| `structural_chunk_metrics` | 64 | 2 | 61.5000 / 63.8500 | 3 / 3 | 0 | no_applicable_gold=12, no_verified_gold_label=28 |
| `local_selection_metrics` | N/A | 2 | 61.5000 / 63.8500 | 3 / 3 | 0 | configured_capacity_unknown=22, no_applicable_gold=3, no_verified_gold_label=28 |
| `reranker_input_metrics` | 64 | 2 | 61.5000 / 63.8500 | 3 / 3 | 0 | no_applicable_gold=12, no_verified_gold_label=28 |
| `reranker_output_metrics` | 6 | 2 | 6.0000 / 6.0000 | 3 / 3 | 0 | k_exceeds_configured_capacity=4, no_applicable_gold=12, no_verified_gold_label=28 |
| `final_evidence_metrics` | 5 | 2 | 4.0000 / 4.8500 | 3 / 3 | 0 | k_exceeds_configured_capacity=8, no_applicable_gold=9, no_verified_gold_label=28 |

## 4. Interpretation notes

- Recall@K is undefined when K exceeds the configured stage capacity; nDCG@10 still treats unreturned ranks as zero gain so capacity effects remain measurable.
- Configured provider candidates are provenance only; they do not prove which provider answered a request.

## 5. Deterministic answer metrics

Answer scored / total: `4 / 4`
Answer skip reasons: `none`

| Metric | Value |
| :--- | ---: |
| `answer_similarity_pass_rate` | 0.0000 |
| `unanswerable_accuracy` | N/A |
| `refusal_precision` | N/A |
| `refusal_recall` | N/A |
| `token_f1` | 0.2030 |
| `char_f1` | 0.1946 |
| `rouge_l` | 0.1927 |
| `chrf` | 0.3332 |
| `citation_precision` | N/A |
| `invalid_citation_rate` | N/A |

## 6. Generation, guardrail, and judge coverage

Generation STOP / total: `4 / 4`
Input safe / total: `4 / 4`
Output safe / total: `4 / 4`
Ragas scored / eligible: `4 / 4`
Judge technical errors: `0`

| Ragas metric | Mean | Scored cases |
| :--- | ---: | ---: |
| `faithfulness` | 0.8601 | 4 |
| `answer_accuracy` | 0.9375 | 4 |
| `context_precision` | 0.7500 | 4 |
| `context_recall` | 0.8750 | 4 |

## 7. Latency

| Stage | P50 (s) | P95 (s) | Mean (s) |
| :--- | ---: | ---: | ---: |
| `t_input_guardrail` | 1.0116 | 1.2894 | 1.0724 |
| `t_output_guardrail` | 1.0659 | 1.0985 | 1.0607 |
| `t_retrieval` | 3.0295 | 4.2338 | 3.1543 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 9.4258 | 10.9275 | 9.1068 |

## 8. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 9. Case statuses

| Case ID | Status | Finish reason | Ragas scored | Technical error stages | Total latency (s) |
| :--- | :--- | :--- | :---: | :--- | ---: |
| `case_021` | `ok` | `STOP` | `yes` | `none` | 10.7550 |
| `case_031` | `ok` | `STOP` | `yes` | `none` | 6.6177 |
| `case_183` | `ok` | `STOP` | `yes` | `none` | 10.9579 |
| `case_325` | `ok` | `STOP` | `yes` | `none` | 8.0965 |