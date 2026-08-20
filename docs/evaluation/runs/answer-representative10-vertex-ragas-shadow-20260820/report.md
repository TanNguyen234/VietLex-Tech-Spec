# VIETLEX EVALUATION REPORT — answer-representative10-vertex-ragas-shadow-20260820

**Run ID**: `answer-representative10-vertex-ragas-shadow-20260820`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-08-20T16:09:53.954478+00:00`  
**Git Commit SHA**: `1a922af6774b3500ca59e74621bc60106dcbb98d`  
**Source State SHA-256**: `bbdf44194a5bc80fce48e4560db530b6fd5cd5c763e0602b548606b8716af48f`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `1ed507c7425429b32b18fc3628de7ff317e2fb190c9838e6d72479f3aa019742`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `d6e125030e8dda700667ba00f25162fac76472a9bfa2d087f54e2b5bc73a1fee`  
**Configuration Fingerprint**: `34eb840bd81d01484288a9bf8891f025ffd47fb870680ebbdf9ed27e973d01e7`  
**Execution Command**: `run_answer_eval.py --dataset app/data/namsyntax_legal_qa_420_curated_v1.json --sidecar docs/evaluation/adjudication/promotions/gold-adjudication-promotion-curated-v4_20260809_151015_227377/labels_v2.json --profile separated_intent --rewrite off --guardrails shadow --reranker current --concurrency 1 --case-ids case_017 case_036 case_061 case_101 case_165 case_243 case_261 case_323 case_329 case_397 --verified-only --gold-policy all-required-verified --judge ragas --run-id answer-representative10-vertex-ragas-shadow-20260820`  
**Evaluation Mode**: `answer` | **Judge**: `ragas` | **Guardrails**: `shadow`  

Metric schema: `3.0.0`
Scored / Total: `10 / 10`
Skipped cases: `0`
Skip reasons: `none`

## 1. Reliability and coverage

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons | Notes |
| :--- | ---: | ---: | :---: | :---: | :--- | :--- |
| Scored gold coverage | 100.0% | 100.0% | 10.0000/10.0000 | 10 / 0 | none | Cases with applicable verified required evidence |
| No-candidate rate | 0.0% | 0.0% | 0.0000/10.0000 | 10 / 0 | none | Completed retrievals with zero candidates |
| Retrieval technical-error rate | 0.0% | 0.0% | 0.0000/10.0000 | 10 / 0 | none | Exact status retrieval_error |
| Reranker technical-error rate | 0.0% | 0.0% | 0.0000/10.0000 | 10 / 0 | none | Exact status reranker_error |

## 2. Retrieval quality

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons |
| :--- | ---: | ---: | :---: | :---: | :--- |
| Document Recall @ 1 | 0.0000 | 0.0000 | 0.0000/14.0000 | 10 / 0 | none |
| Document Recall @ 3 | 0.0000 | 0.0000 | 0.0000/14.0000 | 10 / 0 | none |
| Document Recall @ 5 | 0.0000 | 0.0000 | 0.0000/14.0000 | 10 / 0 | none |
| Document Recall @ 10 | 0.0000 | 0.0000 | 0.0000/14.0000 | 10 / 0 | none |
| Document Recall @ 24 | 0.0000 | 0.0000 | 0.0000/14.0000 | 10 / 0 | none |
| Article Recall @ 1 | 0.0000 | 0.0000 | 0.0000/8.0000 | 7 / 3 | no_applicable_gold=3 |
| Article Recall @ 3 | 0.0000 | 0.0000 | 0.0000/8.0000 | 7 / 3 | no_applicable_gold=3 |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 10 | k_exceeds_configured_capacity=10 |
| Clause Recall @ 1 | 0.0000 | 0.0000 | 0.0000/5.0000 | 4 / 6 | no_applicable_gold=6 |
| Clause Recall @ 3 | 0.0000 | 0.0000 | 0.0000/5.0000 | 4 / 6 | no_applicable_gold=6 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 10 | k_exceeds_configured_capacity=10 |
| Article MRR | 0.0000 | 0.0000 | 0.0000/7.0000 | 7 / 3 | no_applicable_gold=3 |
| Clause MRR | 0.0000 | 0.0000 | 0.0000/4.0000 | 4 / 6 | no_applicable_gold=6 |
| Document MRR | 0.0000 | 0.0000 | 0.0000/10.0000 | 10 / 0 | none |
| nDCG @ 10 | 0.0000 | 0.0000 | 0.0000/12.5237 | 10 / 0 | none |
| Exact legal-reference hit | 0.0000 | 0.0000 | 0.0000/10.0000 | 10 / 0 | none |
| Multi-hop all-required coverage | 0.0000 | 0.0000 | 0.0000/10.0000 | 10 / 0 | none |
| Multi-hop partial coverage | 0.0000 | 0.0000 | 0.0000/14.0000 | 10 / 0 | none |

## 3. Stage metrics

| Pipeline stage | Capacity | Scored cases | Candidate p50 / p95 | Matched / Applicable documents | First-loss evidence count | Null reasons |
| :--- | ---: | ---: | :---: | :---: | ---: | :--- |
| `pinecone_document_metrics` | 24 | 10 | 0.0000 / 0.0000 | 0 / 14 | 0 | stage_does_not_expose_structural_locators=80 |
| `fts_document_metrics` | 12 | 10 | 12.0000 / 12.0000 | 0 / 14 | 0 | k_exceeds_configured_capacity=10, stage_does_not_expose_structural_locators=80 |
| `source_retrieval_metrics` | 36 | 10 | 12.0000 / 12.0000 | 0 / 14 | 14 | stage_does_not_expose_structural_locators=80 |
| `merged_document_metrics` | 36 | 10 | 12.0000 / 12.0000 | 0 / 14 | 0 | stage_does_not_expose_structural_locators=80 |
| `resolved_document_metrics` | 16 | 10 | 12.0000 / 12.0000 | 0 / 14 | 0 | k_exceeds_configured_capacity=10, stage_does_not_expose_structural_locators=80 |
| `structural_chunk_metrics` | N/A | 10 | 362.0000 / 1213.6000 | 0 / 14 | 0 | configured_capacity_unknown=110, no_applicable_gold=9 |
| `local_selection_metrics` | 64 | 10 | 45.0000 / 48.0000 | 0 / 14 | 0 | no_applicable_gold=36 |
| `reranker_input_metrics` | 24 | 10 | 24.0000 / 24.0000 | 0 / 14 | 0 | no_applicable_gold=36 |
| `reranker_output_metrics` | 3 | 10 | 3.0000 / 3.0000 | 0 / 14 | 0 | k_exceeds_configured_capacity=50, no_applicable_gold=27 |
| `final_evidence_metrics` | 3 | 10 | 2.5000 / 3.0000 | 0 / 14 | 0 | k_exceeds_configured_capacity=50, no_applicable_gold=27 |

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
| `refusal_precision` | 0.0000 |
| `refusal_recall` | N/A |
| `token_f1` | 0.1281 |
| `char_f1` | 0.1898 |
| `rouge_l` | 0.1074 |
| `chrf` | 0.1776 |
| `citation_precision` | N/A |
| `invalid_citation_rate` | N/A |

## 6. Latency

| Stage | P50 (s) | P95 (s) | Mean (s) |
| :--- | ---: | ---: | ---: |
| `t_input_guardrail` | 0.9757 | 1.2736 | 1.0045 |
| `t_output_guardrail` | 1.0328 | 1.2224 | 1.0639 |
| `t_retrieval` | 2.2596 | 3.3254 | 2.4461 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 8.6495 | 11.9547 | 9.2534 |

## 7. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 8. Case statuses

| Case ID | Status | Total latency (s) |
| :--- | :--- | ---: |
| `case_017` | `ok` | 12.7373 |
| `case_036` | `ok` | 9.2186 |
| `case_061` | `ok` | 8.6917 |
| `case_101` | `ok` | 8.0963 |
| `case_165` | `ok` | 10.9982 |
| `case_243` | `ok` | 8.4950 |
| `case_261` | `ok` | 8.6073 |
| `case_323` | `ok` | 8.7451 |
| `case_329` | `ok` | 8.5425 |
| `case_397` | `ok` | 8.4015 |