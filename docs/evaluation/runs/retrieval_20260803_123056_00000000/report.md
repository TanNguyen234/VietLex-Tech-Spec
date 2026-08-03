# VIETLEX EVALUATION REPORT — retrieval_20260803_123056_00000000

**Run ID**: `retrieval_20260803_123056_00000000`  
**UTC Timestamp**: `2026-08-03T12:30:56.208148+00:00`  
**Git Commit SHA**: `ff8d478ad011622544dab5892f13ac16b81fed91`  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `84c93a522c1bc8eac7179aa808f70b59466fe9a55a4a9f98ddae07797c9662c7`  
**Configuration Fingerprint**: `2c24c152fd2d786eb3367067a887a52d408a04eb60a22969ef48bcd0a35b2c4a`  
**Execution Command**: `run_retrieval_eval.py --mode retrieval-only --rewrite off --guardrails off --reranker current --concurrency 1 --limit 10`  
**Evaluation Mode**: `retrieval-only` | **Judge**: `none` | **Guardrails**: `off`  
**Query Rewrite**: `off` | **Reranker**: `current`  

## 1. Retrieval Performance Summary

| Metric | Value | Numerator / Denominator | Notes |
| :--- | ---: | :---: | :--- |
| Scored Coverage | 0.0% | 0/10 | Cases with verified gold labels |
| No Candidate Rate | 0.0% | 0/10 | Empty candidate set |
| Retrieval Error Rate | 0.0% | 0/10 | Hybrid/FTS errors |
| Reranker Error Rate | 0.0% | 0/10 | Reranker API errors |
| Document Recall @ 1 | 0.0000 | - | Primary legal document hit |
| Document Recall @ 3 | 0.0000 | - | Top 3 document candidates |
| Document Recall @ 5 | 0.0000 | - | Top 5 document candidates |
| Document Recall @ 10 | 0.0000 | - | Top 10 document candidates |
| Document Recall @ 24 | 0.0000 | - | Pinecone max top_k limit |
| Article Recall @ 1 | 0.0000 | - | Top 1 article candidate |
| Article Recall @ 3 | 0.0000 | - | Top 3 article candidates |
| Article Recall @ 6 | 0.0000 | - | Top 6 article candidates |
| Clause Recall @ 1 | 0.0000 | - | Top 1 clause candidate |
| Clause Recall @ 3 | 0.0000 | - | Top 3 clause candidates |
| Clause Recall @ 6 | 0.0000 | - | Top 6 clause candidates |
| Article MRR | 0.0000 | - | Mean Reciprocal Rank |
| nDCG @ 10 | 0.0000 | - | Normalized DCG |
| Exact Citation Hit Rate | 0.0% | - | Article level citation hit |
| Multi-Hop All-Coverage | 0.0% | - | All required evidence hits |
| Multi-Hop Partial-Coverage | 0.0% | - | At least one required hit |

## 3. Stage-Level Latency Breakdown

| Stage / Operation | P50 (s) | P95 (s) | Mean (s) | Min (s) | Max (s) |
| :--- | ---: | ---: | ---: | ---: | ---: |
| `t_candidate` | 0.0024s | 0.0054s | 0.0030s | 0.0017s | 0.0055s |
| `t_hybrid` | 0.8001s | 1.6402s | 0.9554s | 0.7897s | 2.1241s |
| `t_lexical` | 0.6240s | 1.3761s | 0.7311s | 0.3738s | 1.5552s |
| `t_rerank` | 1.8662s | 2.6230s | 2.0274s | 1.7310s | 3.0253s |
| `t_resolve_chunk` | 0.1288s | 0.4495s | 0.1991s | 0.0491s | 0.5167s |
| `t_retrieval` | 2.9368s | 5.1350s | 3.3307s | 2.6815s | 6.5810s |
| `t_rewrite` | 0.0000s | 0.0000s | 0.0000s | 0.0000s | 0.0000s |
| `t_total` | 2.9368s | 6.9501s | 3.6607s | 2.6815s | 9.8811s |

## 4. Stage-Level Candidate Survival & Retention

| Retrieval Stage | Survival Rate | Avg Candidates per Query |
| :--- | ---: | ---: |
| `pinecone_hits` | 100.0% | 24.00 |
| `lexical_hits` | 100.0% | 12.00 |
| `merged_document_ids` | 0.0% | 0.00 |
| `resolved_document_ids` | 0.0% | 0.00 |
| `locally_selected_chunks` | 0.0% | 0.00 |
| `reranker_input_chunks` | 100.0% | 0.00 |
| `reranker_output_chunks` | 100.0% | 0.00 |
| `final_evidence_chunks` | 100.0% | 0.00 |

## 5. Case-by-Case Execution Details

| Case ID | Group | Status | Latency | Article Recall | Token F1 | Refusal Category |
| :---: | :--- | :--- | ---: | ---: | ---: | :--- |
| `case_001` | factoid | ok | 9.88s | - | - | `-` |
| `case_002` | unanswerable | ok | 2.75s | - | - | `-` |
| `case_003` | multi-hop | ok | 3.30s | - | - | `-` |
| `case_004` | unanswerable | ok | 2.68s | - | - | `-` |
| `case_005` | factoid | ok | 3.37s | - | - | `-` |
| `case_006` | multi-hop | ok | 2.78s | - | - | `-` |
| `case_007` | factoid | ok | 2.77s | - | - | `-` |
| `case_008` | unanswerable | ok | 3.09s | - | - | `-` |
| `case_009` | factoid | ok | 2.69s | - | - | `-` |
| `case_010` | multi-hop | ok | 3.29s | - | - | `-` |
