# VIETLEX EVALUATION REPORT — answer-representative3-output1024-probe-live-20260822

**Run ID**: `answer-representative3-output1024-probe-live-20260822`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-08-22T14:11:00.289080+00:00`  
**Git Commit SHA**: `6dd558c3e163941690eb9a75490c886a898d52d5`  
**Source State SHA-256**: `09fe23a5b3c02db056796a642687b9e45be42700c0bd9e7695f9b6f9477aa3d5`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `52d6fcfa1f5aa88466562720543452cb729b7477c6f365b913db816d118bf299`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `b458880e2c2fc4f2813965d57dc96517555488a5ada3702da12fb811f05fb90b`  
**Configuration Fingerprint**: `c25d9b50f60c85863d7f87347dfa66b6c542f7548e35952e5a6de1200c72dbb0`  
**Execution Command**: `run_answer_eval.py --case-ids case_261 case_329 case_397 --verified-only --gold-policy all-required-verified --profile separated_intent --rewrite off --guardrails enforce --reranker current --concurrency 1 --judge ragas --run-id answer-representative3-output1024-probe-live-20260822`  
**Evaluation Mode**: `answer` | **Judge**: `ragas` | **Guardrails**: `enforce`  

Metric schema: `3.0.0`
Scored / Total: `3 / 3`
Skipped cases: `0`
Skip reasons: `none`

## 1. Reliability and coverage

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons | Notes |
| :--- | ---: | ---: | :---: | :---: | :--- | :--- |
| Scored gold coverage | 100.0% | 100.0% | 3.0000/3.0000 | 3 / 0 | none | Cases with applicable verified required evidence |
| No-candidate rate | 0.0% | 0.0% | 0.0000/3.0000 | 3 / 0 | none | Completed retrievals with zero candidates |
| Retrieval technical-error rate | 0.0% | 0.0% | 0.0000/3.0000 | 3 / 0 | none | Status retrieval_error or partial_retrieval_error |
| Reranker technical-error rate | 0.0% | 0.0% | 0.0000/3.0000 | 3 / 0 | none | Exact status reranker_error |

## 2. Retrieval quality

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons |
| :--- | ---: | ---: | :---: | :---: | :--- |
| Document Recall @ 1 | 0.0000 | 0.0000 | 0.0000/5.0000 | 3 / 0 | none |
| Document Recall @ 3 | 1.0000 | 1.0000 | 5.0000/5.0000 | 3 / 0 | none |
| Document Recall @ 5 | 1.0000 | 1.0000 | 5.0000/5.0000 | 3 / 0 | none |
| Document Recall @ 10 | 1.0000 | 1.0000 | 5.0000/5.0000 | 3 / 0 | none |
| Document Recall @ 24 | 1.0000 | 1.0000 | 5.0000/5.0000 | 3 / 0 | none |
| Article Recall @ 1 | 0.5000 | 0.3333 | 1.0000/3.0000 | 2 / 1 | no_applicable_gold=1 |
| Article Recall @ 3 | 0.7500 | 0.6667 | 2.0000/3.0000 | 2 / 1 | no_applicable_gold=1 |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 3 | k_exceeds_configured_capacity=3 |
| Clause Recall @ 1 | 0.5000 | 0.3333 | 1.0000/3.0000 | 2 / 1 | no_applicable_gold=1 |
| Clause Recall @ 3 | 0.7500 | 0.6667 | 2.0000/3.0000 | 2 / 1 | no_applicable_gold=1 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 3 | k_exceeds_configured_capacity=3 |
| Article MRR | 0.6666 | 0.6667 | 1.3333/2.0000 | 2 / 1 | no_applicable_gold=1 |
| Clause MRR | 0.6666 | 0.6667 | 1.3333/2.0000 | 2 / 1 | no_applicable_gold=1 |
| Document MRR | 0.4444 | 0.4444 | 1.3333/3.0000 | 3 / 0 | none |
| nDCG @ 10 | 0.8479 | 0.8254 | 3.5178/4.2619 | 3 / 0 | none |
| Exact legal-reference hit | 1.0000 | 1.0000 | 3.0000/3.0000 | 3 / 0 | none |
| Multi-hop all-required coverage | 1.0000 | 1.0000 | 3.0000/3.0000 | 3 / 0 | none |
| Multi-hop partial coverage | 1.0000 | 1.0000 | 5.0000/5.0000 | 3 / 0 | none |

## 3. Stage metrics

| Pipeline stage | Capacity | Scored cases | Candidate p50 / p95 | Matched / Applicable documents | First-loss evidence count | Null reasons |
| :--- | ---: | ---: | :---: | :---: | ---: | :--- |
| `pinecone_document_metrics` | 48 | 3 | 48.0000 / 48.0000 | 5 / 5 | 0 | stage_does_not_expose_structural_locators=24 |
| `fts_document_metrics` | 48 | 3 | 48.0000 / 48.0000 | 5 / 5 | 0 | stage_does_not_expose_structural_locators=24 |
| `source_retrieval_metrics` | 64 | 3 | 14.0000 / 14.0000 | 5 / 5 | 0 | stage_does_not_expose_structural_locators=24 |
| `merged_document_metrics` | 64 | 3 | 48.0000 / 51.6000 | 5 / 5 | 0 | stage_does_not_expose_structural_locators=24 |
| `resolved_document_metrics` | 64 | 3 | 48.0000 / 51.6000 | 5 / 5 | 0 | stage_does_not_expose_structural_locators=24 |
| `structural_chunk_metrics` | 64 | 3 | 48.0000 / 51.6000 | 5 / 5 | 0 | no_applicable_gold=8 |
| `local_selection_metrics` | N/A | 3 | 48.0000 / 51.6000 | 5 / 5 | 0 | configured_capacity_unknown=33, no_applicable_gold=2 |
| `reranker_input_metrics` | 64 | 3 | 48.0000 / 51.6000 | 5 / 5 | 0 | no_applicable_gold=8 |
| `reranker_output_metrics` | 6 | 3 | 6.0000 / 6.0000 | 5 / 5 | 0 | k_exceeds_configured_capacity=6, no_applicable_gold=8 |
| `final_evidence_metrics` | 5 | 3 | 3.0000 / 4.8000 | 5 / 5 | 0 | k_exceeds_configured_capacity=12, no_applicable_gold=6 |

## 4. Interpretation notes

- Recall@K is undefined when K exceeds the configured stage capacity; nDCG@10 still treats unreturned ranks as zero gain so capacity effects remain measurable.
- Configured provider candidates are provenance only; they do not prove which provider answered a request.

## 5. Deterministic answer metrics

Answer scored / total: `3 / 3`
Answer skip reasons: `none`

| Metric | Value |
| :--- | ---: |
| `answer_similarity_pass_rate` | 0.0000 |
| `unanswerable_accuracy` | N/A |
| `refusal_precision` | N/A |
| `refusal_recall` | N/A |
| `token_f1` | 0.2361 |
| `char_f1` | 0.2197 |
| `rouge_l` | 0.2361 |
| `chrf` | 0.3872 |
| `citation_precision` | N/A |
| `invalid_citation_rate` | N/A |

## 6. Latency

| Stage | P50 (s) | P95 (s) | Mean (s) |
| :--- | ---: | ---: | ---: |
| `t_input_guardrail` | 1.1159 | 1.2126 | 1.1146 |
| `t_output_guardrail` | 1.2857 | 1.3761 | 1.2782 |
| `t_retrieval` | 2.3759 | 4.5481 | 3.1702 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 9.7440 | 11.4878 | 10.2380 |

## 7. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 8. Case statuses

| Case ID | Status | Total latency (s) |
| :--- | :--- | ---: |
| `case_261` | `ok` | 11.6816 |
| `case_329` | `ok` | 9.2885 |
| `case_397` | `ok` | 9.7440 |