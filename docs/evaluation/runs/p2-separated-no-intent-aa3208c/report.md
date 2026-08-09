# VIETLEX EVALUATION REPORT — p2-separated-no-intent-aa3208c

**Run ID**: `p2-separated-no-intent-aa3208c`  
**Profile**: `separated_no_intent`  
**UTC Timestamp**: `2026-08-09T15:38:23.072971+00:00`  
**Git Commit SHA**: `aa3208c850d8b8f8782bab98ca925228202dfff8`  
**Source State SHA-256**: `4c4a9c600ee59271052b746944bf5273ad6e64ae36b2332c45afa624a6b8b91d`  
**Git Dirty Status**: `False` (Diff: `clean`, SHA-256: `N/A`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `d6e125030e8dda700667ba00f25162fac76472a9bfa2d087f54e2b5bc73a1fee`  
**Configuration Fingerprint**: `7193cbac5ae9474cce6dbbf951266a8389ea9e686314f3f9ba70228821631613`  
**Execution Command**: `run_retrieval_eval.py --dataset app/data/namsyntax_legal_qa_420_curated_v1.json --sidecar docs/evaluation/adjudication/promotions/gold-adjudication-promotion-curated-v4_20260809_151015_227377/labels_v2.json --profile separated_no_intent --rewrite off --reranker current --concurrency 1 --verified-only --gold-policy all-required-verified --require-clean-git --run-id p2-separated-no-intent-aa3208c`  
**Evaluation Mode**: `retrieval-only` | **Judge**: `none` | **Guardrails**: `off`  

Metric schema: `3.0.0`
Scored / Total: `40 / 40`
Skipped cases: `0`
Skip reasons: `none`

## 1. Reliability and coverage

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons | Notes |
| :--- | ---: | ---: | :---: | :---: | :--- | :--- |
| Scored gold coverage | 100.0% | 100.0% | 40.0000/40.0000 | 40 / 0 | none | Cases with applicable verified required evidence |
| No-candidate rate | 0.0% | 0.0% | 0.0000/40.0000 | 40 / 0 | none | Completed retrievals with zero candidates |
| Retrieval technical-error rate | 0.0% | 0.0% | 0.0000/40.0000 | 40 / 0 | none | Exact status retrieval_error |
| Reranker technical-error rate | 0.0% | 0.0% | 0.0000/40.0000 | 40 / 0 | none | Exact status reranker_error |

## 2. Retrieval quality

| Metric | Macro | Micro | Numerator / Denominator | Scored / Skipped | Skip reasons |
| :--- | ---: | ---: | :---: | :---: | :--- |
| Document Recall @ 1 | 0.0000 | 0.0000 | 0.0000/53.0000 | 40 / 0 | none |
| Document Recall @ 3 | 0.0000 | 0.0000 | 0.0000/53.0000 | 40 / 0 | none |
| Document Recall @ 5 | 0.0000 | 0.0000 | 0.0000/53.0000 | 40 / 0 | none |
| Document Recall @ 10 | 0.0000 | 0.0000 | 0.0000/53.0000 | 40 / 0 | none |
| Document Recall @ 24 | 0.0000 | 0.0000 | 0.0000/53.0000 | 40 / 0 | none |
| Article Recall @ 1 | 0.0000 | 0.0000 | 0.0000/30.0000 | 27 / 13 | no_applicable_gold=13 |
| Article Recall @ 3 | 0.0000 | 0.0000 | 0.0000/30.0000 | 27 / 13 | no_applicable_gold=13 |
| Article Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 40 | k_exceeds_configured_capacity=40 |
| Clause Recall @ 1 | 0.0000 | 0.0000 | 0.0000/14.0000 | 13 / 27 | no_applicable_gold=27 |
| Clause Recall @ 3 | 0.0000 | 0.0000 | 0.0000/14.0000 | 13 / 27 | no_applicable_gold=27 |
| Clause Recall @ 6 | N/A | N/A | 0.0000/0.0000 | 0 / 40 | k_exceeds_configured_capacity=40 |
| Article MRR | 0.0000 | 0.0000 | 0.0000/27.0000 | 27 / 13 | no_applicable_gold=13 |
| Clause MRR | 0.0000 | 0.0000 | 0.0000/13.0000 | 13 / 27 | no_applicable_gold=27 |
| Document MRR | 0.0000 | 0.0000 | 0.0000/40.0000 | 40 / 0 | none |
| nDCG @ 10 | 0.0000 | 0.0000 | 0.0000/48.2021 | 40 / 0 | none |
| Exact legal-reference hit | 0.0000 | 0.0000 | 0.0000/40.0000 | 40 / 0 | none |
| Multi-hop all-required coverage | 0.0000 | 0.0000 | 0.0000/40.0000 | 40 / 0 | none |
| Multi-hop partial coverage | 0.0000 | 0.0000 | 0.0000/53.0000 | 40 / 0 | none |

## 3. Stage metrics

| Pipeline stage | Capacity | Scored cases | Candidate p50 / p95 | Matched / Applicable documents | First-loss evidence count | Null reasons |
| :--- | ---: | ---: | :---: | :---: | ---: | :--- |
| `pinecone_document_metrics` | 24 | 40 | 24.0000 / 24.0000 | 0 / 53 | 0 | stage_does_not_expose_structural_locators=320 |
| `fts_document_metrics` | 12 | 40 | 12.0000 / 12.0000 | 0 / 53 | 0 | k_exceeds_configured_capacity=40, stage_does_not_expose_structural_locators=320 |
| `source_retrieval_metrics` | 36 | 40 | 35.0000 / 36.0000 | 0 / 53 | 53 | stage_does_not_expose_structural_locators=320 |
| `merged_document_metrics` | 36 | 40 | 12.0000 / 12.0000 | 0 / 53 | 0 | stage_does_not_expose_structural_locators=320 |
| `resolved_document_metrics` | 16 | 40 | 16.0000 / 16.0000 | 0 / 53 | 0 | k_exceeds_configured_capacity=40, stage_does_not_expose_structural_locators=320 |
| `structural_chunk_metrics` | N/A | 40 | 590.5000 / 1702.0500 | 0 / 53 | 0 | configured_capacity_unknown=440, no_applicable_gold=40 |
| `local_selection_metrics` | 64 | 40 | 61.0000 / 64.0000 | 0 / 53 | 0 | no_applicable_gold=160 |
| `reranker_input_metrics` | 24 | 40 | 24.0000 / 24.0000 | 0 / 53 | 0 | no_applicable_gold=160 |
| `reranker_output_metrics` | 3 | 40 | 3.0000 / 3.0000 | 0 / 53 | 0 | k_exceeds_configured_capacity=200, no_applicable_gold=120 |
| `final_evidence_metrics` | 3 | 40 | 3.0000 / 3.0000 | 0 / 53 | 0 | k_exceeds_configured_capacity=200, no_applicable_gold=120 |

## 4. Interpretation notes

- Recall@K is undefined when K exceeds the configured stage capacity; nDCG@10 still treats unreturned ranks as zero gain so capacity effects remain measurable.
- Configured provider candidates are provenance only; they do not prove which provider answered a request.

## 6. Latency

| Stage | P50 (s) | P95 (s) | Mean (s) |
| :--- | ---: | ---: | ---: |
| `t_retrieval` | 4.7377 | 14.1178 | 6.9185 |
| `t_rewrite` | 0.0000 | 0.0000 | 0.0000 |
| `t_total` | 4.7377 | 14.1178 | 6.9185 |

## 7. Runtime candidate trace summary

The runtime trace summary is diagnostic only; quality denominators come from the validated v3 metric contract above.

## 8. Case statuses

| Case ID | Status | Total latency (s) |
| :--- | :--- | ---: |
| `case_017` | `ok` | 11.6037 |
| `case_019` | `ok` | 8.3093 |
| `case_021` | `ok` | 10.2374 |
| `case_031` | `ok` | 3.9226 |
| `case_036` | `ok` | 6.8940 |
| `case_039` | `ok` | 4.8546 |
| `case_043` | `ok` | 4.5938 |
| `case_061` | `ok` | 4.3312 |
| `case_065` | `ok` | 7.5107 |
| `case_075` | `ok` | 12.0303 |
| `case_101` | `ok` | 4.0223 |
| `case_121` | `ok` | 4.7182 |
| `case_127` | `ok` | 4.3921 |
| `case_133` | `ok` | 3.9451 |
| `case_135` | `ok` | 4.9399 |
| `case_165` | `ok` | 4.1910 |
| `case_171` | `ok` | 7.7548 |
| `case_177` | `ok` | 10.2044 |
| `case_187` | `ok` | 5.8591 |
| `case_204` | `ok` | 5.7829 |
| `case_227` | `ok` | 4.5628 |
| `case_243` | `ok` | 4.7572 |
| `case_253` | `ok` | 4.2909 |
| `case_257` | `ok` | 8.8023 |
| `case_261` | `ok` | 14.0722 |
| `case_263` | `ok` | 5.5980 |
| `case_285` | `ok` | 4.5596 |
| `case_309` | `ok` | 4.3987 |
| `case_323` | `ok` | 4.4496 |
| `case_329` | `ok` | 10.3427 |
| `case_331` | `ok` | 31.5816 |
| `case_339` | `ok` | 6.0274 |
| `case_355` | `ok` | 14.9840 |
| `case_361` | `ok` | 3.9181 |
| `case_371` | `ok` | 3.7886 |
| `case_374` | `ok` | 4.2784 |
| `case_375` | `ok` | 4.0752 |
| `case_379` | `ok` | 3.6996 |
| `case_397` | `ok` | 4.6305 |
| `case_411` | `ok` | 3.8245 |