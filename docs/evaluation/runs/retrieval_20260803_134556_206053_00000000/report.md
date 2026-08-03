# VIETLEX EVALUATION REPORT — retrieval_20260803_134556_206053_00000000

**Run ID**: `retrieval_20260803_134556_206053_00000000`  
**Profile**: `custom`  
**UTC Timestamp**: `2026-08-03T13:45:57.152758+00:00`  
**Git Commit SHA**: `8bd5423da0daca16532a8c4820b7640fd48fac82`  
**Git Dirty Status**: `True` (Diff SHA256: `clean`)  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `84c93a522c1bc8eac7179aa808f70b59466fe9a55a4a9f98ddae07797c9662c7`  
**Sidecar SHA-256**: `N/A`  
**Configuration Fingerprint**: `ed4a5e49db5b31d60d271c08f6d8ae2947ff1a29a7d2b71b8d5d7c7cc01fef24`  
**Execution Command**: `run_retrieval_eval.py --profile separated_no_intent --verified-only --concurrency 2`  
**Evaluation Mode**: `retrieval-only` | **Judge**: `none` | **Guardrails**: `off`  
**Query Rewrite**: `off` | **Reranker**: `current`  

## 1. System Reliability & Execution Status

| Status Metric | Count / Value | Numerator / Denominator | Notes |
| :--- | ---: | :---: | :--- |
| Scored Gold Coverage | 100.0% | 12/12 | Cases with verified gold labels |
| No Candidate Rate | 0.0% | 0/12 | Empty candidate set |
| Retrieval Error Rate | 0.0% | 0/12 | Hybrid/FTS technical errors |
| Reranker Error Rate | 0.0% | 0/12 | Reranker API errors |

## 2. Retrieval Quality Summary (Scored Cases)

| Retrieval Metric | Value | Notes |
| :--- | ---: | :--- |
| Document Recall @ 1 | 0.0833 | Primary document candidate hit |
| Document Recall @ 3 | 0.0833 | Top 3 document candidates |
| Document Recall @ 5 | 0.0833 | Top 5 document candidates |
| Document Recall @ 10 | 0.0833 | Top 10 document candidates |
| Document Recall @ 24 | 0.0833 | Max document candidate pool |
| Article Recall @ 1 | 0.0833 | Top 1 article candidate |
| Article Recall @ 3 | 0.0833 | Top 3 article candidates |
| Article Recall @ 6 | 0.0833 | Top 6 article candidates |
| Clause Recall @ 1 | 0.0833 | Top 1 clause candidate |
| Clause Recall @ 3 | 0.0833 | Top 3 clause candidates |
| Clause Recall @ 6 | 0.0833 | Top 6 clause candidates |
| Article MRR | 0.0833 | Mean Reciprocal Rank |
| nDCG @ 10 | 0.0833 | Normalized DCG |
| Exact Reference Hit Rate | 8.3% | Exact citation match |
| Multi-Hop All-Coverage | 8.3% | All required evidence hits |
| Multi-Hop Partial-Coverage | 8.3% | At least one required hit |

## 4. Stage-Level Latency Breakdown

| Stage / Operation | P50 (s) | P95 (s) | Mean (s) | Min (s) | Max (s) |
| :--- | ---: | ---: | ---: | ---: | ---: |
| `t_candidate` | 0.0206s | 0.0480s | 0.0246s | 0.0100s | 0.0488s |
| `t_hybrid` | 0.9026s | 2.6908s | 1.3121s | 0.8190s | 3.0762s |
| `t_lexical` | 2.3161s | 4.2051s | 2.3913s | 1.0806s | 4.7685s |
| `t_rerank` | 2.8190s | 3.7290s | 2.9256s | 2.2148s | 3.7308s |
| `t_resolve_chunk` | 0.2019s | 1.4119s | 0.5263s | 0.1051s | 1.6462s |
| `t_retrieval` | 5.9031s | 11.8614s | 6.6357s | 4.0328s | 17.9470s |
| `t_rewrite` | 0.0000s | 0.0000s | 0.0000s | 0.0000s | 0.0000s |
| `t_total` | 5.9031s | 16.2519s | 7.4488s | 4.0328s | 27.7038s |

## 5. Stage-Level Candidate Survival & Retention

| Retrieval Stage | Query Active Rate | Avg Candidates per Query |
| :--- | ---: | ---: |
| `pinecone_hits` | 100.0% | 24.00 |
| `fts_hits` | 100.0% | 12.00 |
| `merged_document_candidates` | 100.0% | 0.00 |
| `resolved_document_candidates` | 100.0% | 0.00 |
| `structural_chunks_generated` | 100.0% | 0.00 |
| `locally_selected_chunks` | 100.0% | 0.00 |
| `reranker_input_chunks` | 100.0% | 0.00 |
| `reranker_output_chunks` | 100.0% | 0.00 |
| `final_evidence_chunks` | 100.0% | 0.00 |

## 6. Case-by-Case Execution Details

| Case ID | Group | Status | Latency | Article Recall | Token F1 | Refusal Category |
| :---: | :--- | :--- | ---: | ---: | ---: | :--- |
| `case_051` | factoid | ok | 6.81s | 0.00 | N/A | `-` |
| `case_016` | multi-hop | ok | 27.70s | 0.00 | N/A | `-` |
| `case_103` | factoid | ok | 5.86s | 0.00 | N/A | `-` |
| `case_120` | multi-hop | ok | 5.94s | 0.00 | N/A | `-` |
| `case_173` | multi-hop | ok | 4.03s | 0.00 | N/A | `-` |
| `case_185` | factoid | ok | 6.25s | 0.00 | N/A | `-` |
| `case_231` | factoid | ok | 6.88s | 0.00 | N/A | `-` |
| `case_246` | multi-hop | ok | 6.53s | 0.00 | N/A | `-` |
| `case_259` | factoid | ok | 5.26s | 0.00 | N/A | `-` |
| `case_267` | factoid | ok | 4.31s | 0.00 | N/A | `-` |
| `case_349` | factoid | ok | 4.85s | 1.00 | N/A | `-` |
| `case_356` | multi-hop | ok | 4.95s | 0.00 | N/A | `-` |
