# VIETLEX EVALUATION REPORT — answer-golden40-preflight-vertex-20260820

**Run ID**: `answer-golden40-preflight-vertex-20260820`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-08-20T15:08:32.323366+00:00`  
**Git Commit SHA**: `1a922af6774b3500ca59e74621bc60106dcbb98d`  
**Source State SHA-256**: `48667e7bb6afd6df854efcb62f600781dffde9df15dc91fda32834a36251c4fe`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `62c8417d5592d70c72f90b8d80c07dace116935d1c760aa74ea8664a9822e9d3`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `d6e125030e8dda700667ba00f25162fac76472a9bfa2d087f54e2b5bc73a1fee`  
**Configuration Fingerprint**: `2e62d58de57a2d39aaf6c2073089fe2a9cbc7310802db0b64fd1dff68321329a`  
**Execution Command**: `run_answer_eval.py --dataset app/data/namsyntax_legal_qa_420_curated_v1.json --sidecar docs/evaluation/adjudication/promotions/gold-adjudication-promotion-curated-v4_20260809_151015_227377/labels_v2.json --profile separated_intent --rewrite off --guardrails shadow --reranker current --concurrency 1 --limit 1 --verified-only --gold-policy all-required-verified --judge ragas --run-id answer-golden40-preflight-vertex-20260820`  
**Evaluation Mode**: `answer` | **Judge**: `ragas` | **Guardrails**: `shadow`  

Metric schema: `3.0.0`
Scored / Total: `0 / 1`
Skipped cases: `1`
Skip reasons: `reranker_error=1`

## 1. Reliability and coverage

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons | Notes |
| :--- | ---: | ---: | :---: | :---: | :--- | :--- |
| Scored gold coverage | 0.0% | 0.0% | 0.0000/1.0000 | 1 / 0 | reranker_error=1 | Cases with applicable verified required evidence |
| No-candidate rate | 0.0% | 0.0% | 0.0000/1.0000 | 1 / 0 | none | Completed retrievals with zero candidates |
| Retrieval technical-error rate | 0.0% | 0.0% | 0.0000/1.0000 | 1 / 0 | none | Exact status retrieval_error |
| Reranker technical-error rate | 100.0% | 100.0% | 1.0000/1.0000 | 1 / 0 | none | Exact status reranker_error |

## 2. Retrieval quality

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons |
| :--- | ---: | ---: | :---: | :---: | :--- |
| Document Recall @ 1 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | reranker_error=1 |
| Document Recall @ 3 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | reranker_error=1 |
| Document Recall @ 5 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | reranker_error=1 |
| Document Recall @ 10 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | reranker_error=1 |
| Document Recall @ 24 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | reranker_error=1 |
| Article Recall @ 1 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | reranker_error=1 |
| Article Recall @ 3 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | reranker_error=1 |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | reranker_error=1 |
| Clause Recall @ 1 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | reranker_error=1 |
| Clause Recall @ 3 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | reranker_error=1 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | reranker_error=1 |
| Article MRR | N/A | N/A | 0.0000/0.0000 | 0 / 1 | reranker_error=1 |
| Clause MRR | N/A | N/A | 0.0000/0.0000 | 0 / 1 | reranker_error=1 |
| Document MRR | N/A | N/A | 0.0000/0.0000 | 0 / 1 | reranker_error=1 |
| nDCG @ 10 | N/A | N/A | 0.0000/0.0000 | 0 / 1 | reranker_error=1 |
| Exact legal-reference hit | N/A | N/A | 0.0000/0.0000 | 0 / 1 | reranker_error=1 |
| Multi-hop all-required coverage | N/A | N/A | 0.0000/0.0000 | 0 / 1 | reranker_error=1 |
| Multi-hop partial coverage | N/A | N/A | 0.0000/0.0000 | 0 / 1 | reranker_error=1 |

## 3. Stage metrics

| Pipeline stage | Capacity | Scored cases | Candidate p50 / p95 | Matched / Applicable documents | First-loss evidence count | Null reasons |
| :--- | ---: | ---: | :---: | :---: | ---: | :--- |
| `pinecone_document_metrics` | 24 | 0 | 0.0000 / 0.0000 | 0 / 0 | 0 | reranker_error=14 |
| `fts_document_metrics` | 12 | 0 | 12.0000 / 12.0000 | 0 / 0 | 0 | reranker_error=14 |
| `source_retrieval_metrics` | 36 | 0 | 12.0000 / 12.0000 | 0 / 0 | 0 | reranker_error=14 |
| `merged_document_metrics` | 36 | 0 | 12.0000 / 12.0000 | 0 / 0 | 0 | reranker_error=14 |
| `resolved_document_metrics` | 16 | 0 | 12.0000 / 12.0000 | 0 / 0 | 0 | reranker_error=14 |
| `structural_chunk_metrics` | N/A | 0 | 277.0000 / 277.0000 | 0 / 0 | 0 | reranker_error=14 |
| `local_selection_metrics` | 64 | 0 | 42.0000 / 42.0000 | 0 / 0 | 0 | reranker_error=14 |
| `reranker_input_metrics` | 24 | 0 | 24.0000 / 24.0000 | 0 / 0 | 0 | reranker_error=14 |
| `reranker_output_metrics` | 3 | 0 | 0.0000 / 0.0000 | 0 / 0 | 0 | reranker_error=14 |
| `final_evidence_metrics` | 3 | 0 | 0.0000 / 0.0000 | 0 / 0 | 0 | reranker_error=14 |

## 4. Interpretation notes

- Recall@K is undefined when K exceeds the configured stage capacity; nDCG@10 still treats unreturned ranks as zero gain so capacity effects remain measurable.
- Configured provider candidates are provenance only; they do not prove which provider answered a request.

## 5. Deterministic answer metrics

Answer scored / total: `0 / 1`
Answer skip reasons: `reranker_error=1`

| Metric | Value |
| :--- | ---: |
| `answer_similarity_pass_rate` | N/A |
| `unanswerable_accuracy` | N/A |
| `refusal_precision` | N/A |
| `refusal_recall` | N/A |
| `token_f1` | N/A |
| `char_f1` | N/A |
| `rouge_l` | N/A |
| `chrf` | N/A |
| `citation_precision` | N/A |
| `invalid_citation_rate` | N/A |

## 6. Latency

| Stage | P50 (s) | P95 (s) | Mean (s) |
| :--- | ---: | ---: | ---: |
| `t_input_guardrail` | 18.9582 | 18.9582 | 18.9582 |
| `t_output_guardrail` | 0.0020 | 0.0020 | 0.0020 |
| `t_retrieval` | 3.5178 | 3.5178 | 3.5178 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 26.9658 | 26.9658 | 26.9658 |

## 7. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 8. Case statuses

| Case ID | Status | Total latency (s) |
| :--- | :--- | ---: |
| `case_017` | `reranker_error` | 26.9658 |