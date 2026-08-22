# VIETLEX EVALUATION REPORT — answer-preflight-case017-vertex-fixed-20260820

**Run ID**: `answer-preflight-case017-vertex-fixed-20260820`  
**Profile**: `separated_intent`  
**UTC Timestamp**: `2026-08-20T15:25:44.748445+00:00`  
**Git Commit SHA**: `1a922af6774b3500ca59e74621bc60106dcbb98d`  
**Source State SHA-256**: `32e8bbf4748205387aef2cd2fbcd05e95bd4129cc0dcd06f86dc01dd8d0b919a`  
**Git Dirty Status**: `True` (Diff: `ok`, SHA-256: `0c78c8a8ee20424494f961567944e84a1ad336841853ad82f03c4fe47917fc16`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `d6e125030e8dda700667ba00f25162fac76472a9bfa2d087f54e2b5bc73a1fee`  
**Configuration Fingerprint**: `45930a0e13c4a7188bbd10f51cba32e2cf77b51dc37be130841106653e9414c9`  
**Execution Command**: `run_answer_eval.py --dataset app/data/namsyntax_legal_qa_420_curated_v1.json --sidecar docs/evaluation/adjudication/promotions/gold-adjudication-promotion-curated-v4_20260809_151015_227377/labels_v2.json --profile separated_intent --rewrite off --guardrails shadow --reranker current --concurrency 1 --case-ids case_017 --verified-only --gold-policy all-required-verified --judge ragas --run-id answer-preflight-case017-vertex-fixed-20260820`  
**Evaluation Mode**: `answer` | **Judge**: `ragas` | **Guardrails**: `shadow`  

Metric schema: `3.0.0`
Scored / Total: `1 / 1`
Skipped cases: `0`
Skip reasons: `none`

## 1. Reliability and coverage

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons | Notes |
| :--- | ---: | ---: | :---: | :---: | :--- | :--- |
| Scored gold coverage | 100.0% | 100.0% | 1.0000/1.0000 | 1 / 0 | none | Cases with applicable verified required evidence |
| No-candidate rate | 0.0% | 0.0% | 0.0000/1.0000 | 1 / 0 | none | Completed retrievals with zero candidates |
| Retrieval technical-error rate | 0.0% | 0.0% | 0.0000/1.0000 | 1 / 0 | none | Exact status retrieval_error |
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
| `pinecone_document_metrics` | 24 | 1 | 0.0000 / 0.0000 | 0 / 1 | 0 | stage_does_not_expose_structural_locators=8 |
| `fts_document_metrics` | 12 | 1 | 12.0000 / 12.0000 | 0 / 1 | 0 | k_exceeds_configured_capacity=1, stage_does_not_expose_structural_locators=8 |
| `source_retrieval_metrics` | 36 | 1 | 12.0000 / 12.0000 | 0 / 1 | 1 | stage_does_not_expose_structural_locators=8 |
| `merged_document_metrics` | 36 | 1 | 12.0000 / 12.0000 | 0 / 1 | 0 | stage_does_not_expose_structural_locators=8 |
| `resolved_document_metrics` | 16 | 1 | 12.0000 / 12.0000 | 0 / 1 | 0 | k_exceeds_configured_capacity=1, stage_does_not_expose_structural_locators=8 |
| `structural_chunk_metrics` | N/A | 1 | 277.0000 / 277.0000 | 0 / 1 | 0 | configured_capacity_unknown=11, no_applicable_gold=1 |
| `local_selection_metrics` | 64 | 1 | 42.0000 / 42.0000 | 0 / 1 | 0 | no_applicable_gold=4 |
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
| `token_f1` | 0.1538 |
| `char_f1` | 0.1916 |
| `rouge_l` | 0.1538 |
| `chrf` | 0.2131 |
| `citation_precision` | N/A |
| `invalid_citation_rate` | N/A |

## 6. Latency

| Stage | P50 (s) | P95 (s) | Mean (s) |
| :--- | ---: | ---: | ---: |
| `t_input_guardrail` | 11.8507 | 11.8507 | 11.8507 |
| `t_output_guardrail` | 1.0614 | 1.0614 | 1.0614 |
| `t_retrieval` | 3.8132 | 3.8132 | 3.8132 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 23.2566 | 23.2566 | 23.2566 |

## 7. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 8. Case statuses

| Case ID | Status | Total latency (s) |
| :--- | :--- | ---: |
| `case_017` | `ok` | 23.2566 |