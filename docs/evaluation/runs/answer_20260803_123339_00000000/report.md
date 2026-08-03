# VIETLEX EVALUATION REPORT — answer_20260803_123339_00000000

**Run ID**: `answer_20260803_123339_00000000`  
**UTC Timestamp**: `2026-08-03T12:33:39.820578+00:00`  
**Git Commit SHA**: `ff8d478ad011622544dab5892f13ac16b81fed91`  
**Dataset Revision**: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`  
**Dataset SHA-256**: `84c93a522c1bc8eac7179aa808f70b59466fe9a55a4a9f98ddae07797c9662c7`  
**Configuration Fingerprint**: `f4f5e4c90916950207387a2297063fa0c59c26d2f45ebf4193bb528fd5c06760`  
**Execution Command**: `run_answer_eval.py --mode answer --rewrite off --guardrails off --reranker current --concurrency 1 --limit 5 --judge none`  
**Evaluation Mode**: `answer` | **Judge**: `none` | **Guardrails**: `off`  
**Query Rewrite**: `off` | **Reranker**: `current`  

## 1. Retrieval Performance Summary

| Metric | Value | Numerator / Denominator | Notes |
| :--- | ---: | :---: | :--- |
| Scored Coverage | 0.0% | 0/5 | Cases with verified gold labels |
| No Candidate Rate | 0.0% | 0/5 | Empty candidate set |
| Retrieval Error Rate | 0.0% | 0/5 | Hybrid/FTS errors |
| Reranker Error Rate | 0.0% | 0/5 | Reranker API errors |
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

## 2. Generation & Answer Accuracy Summary

| Metric | Value | Notes |
| :--- | ---: | :--- |
| Answerable Accuracy | 33.3% | Token F1 >= 0.50 |
| Unanswerable Accuracy | 100.0% | Honest refusal classification |
| Refusal Precision | 0.0% | Correct refusals / Total refusals |
| Refusal Recall | 100.0% | Correct refusals / Unanswerable cases |
| Token F1 | 0.2449 | Unigram token F1 |
| Character F1 | 0.2612 | 3-gram character F1 |
| ROUGE-L | 0.2034 | Word LCS F1 |
| CHRF | 0.3249 | Character n-gram F-score |
| Citation Precision | 1.0000 | Valid citations / Total generated |
| Invalid Citation Rate | 0.0% | Hallucinated citations |

## 3. Stage-Level Latency Breakdown

| Stage / Operation | P50 (s) | P95 (s) | Mean (s) | Min (s) | Max (s) |
| :--- | ---: | ---: | ---: | ---: | ---: |
| `t_candidate` | 0.0102s | 0.0121s | 0.0102s | 0.0069s | 0.0121s |
| `t_hybrid` | 1.1268s | 2.2202s | 1.3804s | 1.0015s | 2.4837s |
| `t_input_guardrail` | 0.0000s | 0.0000s | 0.0000s | 0.0000s | 0.0000s |
| `t_lexical` | 0.8361s | 0.9841s | 0.6938s | 0.3214s | 1.0153s |
| `t_llm` | 1.9790s | 41.2972s | 16.2496s | 1.6170s | 43.5690s |
| `t_output_guardrail` | 0.0000s | 0.0000s | 0.0000s | 0.0000s | 0.0000s |
| `t_rerank` | 2.5258s | 5.2882s | 3.1397s | 1.8763s | 5.6894s |
| `t_resolve_chunk` | 0.4721s | 1.0128s | 0.5553s | 0.1799s | 1.0524s |
| `t_retrieval` | 4.1130s | 11.2504s | 5.9174s | 3.7430s | 12.8030s |
| `t_rewrite` | 1.6530s | 2.8184s | 1.9600s | 1.2480s | 2.8790s |
| `t_total` | 8.1619s | 49.0472s | 24.1280s | 7.1667s | 49.3352s |

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
| `case_001` | factoid | ok | 47.90s | - | 0.27 | `normal_answer` |
| `case_002` | unanswerable | ok | 8.16s | - | 0.11 | `pure_refusal` |
| `case_003` | multi-hop | ok | 49.34s | - | 0.19 | `normal_answer` |
| `case_004` | unanswerable | ok | 8.08s | - | 0.13 | `pure_refusal` |
| `case_005` | factoid | ok | 7.17s | - | 0.51 | `normal_answer` |
