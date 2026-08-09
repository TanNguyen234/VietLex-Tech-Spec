# VietLex P2 Retrieval Profile Comparison

**Status:** `COMPLETED`  
**Decision:** `NO_WINNER_ZERO_RECALL`  
**Recommended profile:** `none`  
**Run Git SHA:** `aa3208c850d8b8f8782bab98ca925228202dfff8`  
**Run source-state SHA-256:** `4c4a9c600ee59271052b746944bf5273ad6e64ae36b2332c45afa624a6b8b91d`  
**Dataset SHA-256:** `d6e125030e8dda700667ba00f25162fac76472a9bfa2d087f54e2b5bc73a1fee`  
**Gold sidecar SHA-256:** `6044c084fd0cfd7b696b7e927ae2df26130e090aa64cf1a3b39a0784c1d8a9bf`  
**Selected cases:** `40`  
**Selected-case-set SHA-256:** `02b147618710247b69406c62c37ee1733412cf99c803a3b818cfc0040e78cfd6`  

## Quality and reliability

| Profile | Doc R@1 | Doc R@3 | Doc R@24 | Article R@3 | Clause R@3 | Doc MRR | nDCG@10 | Initial source misses | Statuses | Technical errors |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- | :--- |
| `legacy` | 0.0000 (0.0000/53.0000) | 0.0000 (0.0000/53.0000) | 0.0000 (0.0000/53.0000) | 0.0000 (0.0000/30.0000) | 0.0000 (0.0000/14.0000) | 0.0000 (0.0000/40.0000) | 0.0000 (0.0000/48.2021) | 53 | {'ok': 40} | {} |
| `separated_intent` | 0.0000 (0.0000/53.0000) | 0.0000 (0.0000/53.0000) | 0.0000 (0.0000/53.0000) | 0.0000 (0.0000/30.0000) | 0.0000 (0.0000/14.0000) | 0.0000 (0.0000/40.0000) | 0.0000 (0.0000/48.2021) | 53 | {'ok': 40} | {} |
| `separated_no_intent` | 0.0000 (0.0000/53.0000) | 0.0000 (0.0000/53.0000) | 0.0000 (0.0000/53.0000) | 0.0000 (0.0000/30.0000) | 0.0000 (0.0000/14.0000) | 0.0000 (0.0000/40.0000) | 0.0000 (0.0000/48.2021) | 53 | {'ok': 40} | {} |

## Coverage and secondary deterministic metrics

| Profile | Coverage | Exact reference | Multi-hop all | Multi-hop partial | No-candidate rate | Retrieval error rate | Reranker error rate | Scored / skipped | Skip reasons |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: | :--- |
| `legacy` | 1.0000 (40.0000/40.0000) | 0.0000 (0.0000/40.0000) | 0.0000 (0.0000/40.0000) | 0.0000 (0.0000/53.0000) | 0.0000 (0.0000/40.0000) | 0.0000 (0.0000/40.0000) | 0.0000 (0.0000/40.0000) | 40 / 0 | {} |
| `separated_intent` | 1.0000 (40.0000/40.0000) | 0.0000 (0.0000/40.0000) | 0.0000 (0.0000/40.0000) | 0.0000 (0.0000/53.0000) | 0.0000 (0.0000/40.0000) | 0.0000 (0.0000/40.0000) | 0.0000 (0.0000/40.0000) | 40 / 0 | {} |
| `separated_no_intent` | 1.0000 (40.0000/40.0000) | 0.0000 (0.0000/40.0000) | 0.0000 (0.0000/40.0000) | 0.0000 (0.0000/53.0000) | 0.0000 (0.0000/40.0000) | 0.0000 (0.0000/40.0000) | 0.0000 (0.0000/40.0000) | 40 / 0 | {} |

## Latency

| Profile | Total mean (s) | Total p50 (s) | Total p95 (s) |
| :--- | ---: | ---: | ---: |
| `legacy` | 5.9857 | 4.1813 | 13.9039 |
| `separated_intent` | 6.4889 | 4.1044 | 15.5088 |
| `separated_no_intent` | 6.9185 | 4.7377 | 14.1178 |

## Stage evidence losses

### `legacy`

- First-loss counts: `{'source_retrieval_metrics': 53}`.
- Reranker contribution: `not_measurable_no_verified_gold_at_reranker_input`; input matches `{'document': 0, 'article': 0, 'clause': 0}`, output matches `{'document': 0, 'article': 0, 'clause': 0}`.

### `separated_intent`

- First-loss counts: `{'source_retrieval_metrics': 53}`.
- Reranker contribution: `not_measurable_no_verified_gold_at_reranker_input`; input matches `{'document': 0, 'article': 0, 'clause': 0}`, output matches `{'document': 0, 'article': 0, 'clause': 0}`.

### `separated_no_intent`

- First-loss counts: `{'source_retrieval_metrics': 53}`.
- Reranker contribution: `not_measurable_no_verified_gold_at_reranker_input`; input matches `{'document': 0, 'article': 0, 'clause': 0}`, output matches `{'document': 0, 'article': 0, 'clause': 0}`.

## Limitations

- Configured provider identifiers do not prove which fallback served a request because runtime provider diagnostics are not persisted in RetrievalCaseResult.
- The benchmark covers 40 curated all-required-verified cases from the 420-case evaluation dataset, not an independent sample of all 518,255 corpus documents.

## Run artifacts

### `legacy`

- Run ID: `p2-legacy-aa3208c`.
- Command: `run_retrieval_eval.py --dataset app/data/namsyntax_legal_qa_420_curated_v1.json --sidecar docs/evaluation/adjudication/promotions/gold-adjudication-promotion-curated-v4_20260809_151015_227377/labels_v2.json --profile legacy --rewrite off --reranker current --concurrency 1 --verified-only --gold-policy all-required-verified --require-clean-git --run-id p2-legacy-aa3208c`.
- Artifact SHA-256: `{'manifest.json': '23fb71035bf3d448bba6f307f7e6618945181cfb9c8b312c0fb983e412a4dc39', 'configuration.json': 'f1521d181312c5d12037491bd729c0ed1234b80a1a45dcc6392e73bac193f0e7', 'evaluation_case_set.json': '0b23dc546dab301a3eed8ec648550565c8281559b28b2732a3042cd33181c1e8', 'retrieval_results.json': 'd8235d7e78baa57477d822139da6331ba6a8a8c401a87c7f3f613ae833b8a47f', 'report.md': 'db0496e47e91cbde2914c226b4e4b63ea34dafee474fd1967c9d29356fe0952c'}`.
- Configured providers: `{'dense': {'provider': 'qdrant-cloud-staging', 'model': 'intfloat/multilingual-e5-small'}, 'reranker_primary': {'provider': 'qdrant', 'model': 'answerdotai/answerai-colbert-small-v1'}, 'reranker_fallback': {'provider': 'pinecone', 'model': 'bge-reranker-v2-m3'}, 'generation': {'mode': 'not_applicable', 'candidates': []}, 'judge': {'mode': 'none', 'candidates': []}}`.

### `separated_intent`

- Run ID: `p2-separated-intent-aa3208c`.
- Command: `run_retrieval_eval.py --dataset app/data/namsyntax_legal_qa_420_curated_v1.json --sidecar docs/evaluation/adjudication/promotions/gold-adjudication-promotion-curated-v4_20260809_151015_227377/labels_v2.json --profile separated_intent --rewrite off --reranker current --concurrency 1 --verified-only --gold-policy all-required-verified --require-clean-git --run-id p2-separated-intent-aa3208c`.
- Artifact SHA-256: `{'manifest.json': '5ee114e70e2f1034ba62875ad3d6a8d036f43538fcb6895d1a8e1f99a8d402ef', 'configuration.json': 'e5c0c7c63a8a95cd8207a0cc58a8ebd976c159f203df50ab56388855a0f1c32a', 'evaluation_case_set.json': '0b23dc546dab301a3eed8ec648550565c8281559b28b2732a3042cd33181c1e8', 'retrieval_results.json': '4ce348f3cfff9e173f8516d616ec3dba438042f6c3721eb4781a629b1053e137', 'report.md': '9c4183c6168467f1496124d4b679f23ee1f2739b2f4e4341060d332ef66ae76a'}`.
- Configured providers: `{'dense': {'provider': 'qdrant-cloud-staging', 'model': 'intfloat/multilingual-e5-small'}, 'reranker_primary': {'provider': 'qdrant', 'model': 'answerdotai/answerai-colbert-small-v1'}, 'reranker_fallback': {'provider': 'pinecone', 'model': 'bge-reranker-v2-m3'}, 'generation': {'mode': 'not_applicable', 'candidates': []}, 'judge': {'mode': 'none', 'candidates': []}}`.

### `separated_no_intent`

- Run ID: `p2-separated-no-intent-aa3208c`.
- Command: `run_retrieval_eval.py --dataset app/data/namsyntax_legal_qa_420_curated_v1.json --sidecar docs/evaluation/adjudication/promotions/gold-adjudication-promotion-curated-v4_20260809_151015_227377/labels_v2.json --profile separated_no_intent --rewrite off --reranker current --concurrency 1 --verified-only --gold-policy all-required-verified --require-clean-git --run-id p2-separated-no-intent-aa3208c`.
- Artifact SHA-256: `{'manifest.json': 'f536770ae3a35f4cd3c5ee6447b93755c129d8e450fc1d5c2e5fec17faf74634', 'configuration.json': 'b2c5ad4d67bb7a9cda5c51f99f126f4ac627d6cf0b81d76ed6576c831c231f37', 'evaluation_case_set.json': '0b23dc546dab301a3eed8ec648550565c8281559b28b2732a3042cd33181c1e8', 'retrieval_results.json': '94fc61993bbf366773463ca0268e9fb36bf1a14a13794c70223d95be3755a4f6', 'report.md': 'fbfe44febaf7c5f602194ee8d544bafab0fb8e5e66b47c2aacb87b27bf3b53be'}`.
- Configured providers: `{'dense': {'provider': 'qdrant-cloud-staging', 'model': 'intfloat/multilingual-e5-small'}, 'reranker_primary': {'provider': 'qdrant', 'model': 'answerdotai/answerai-colbert-small-v1'}, 'reranker_fallback': {'provider': 'pinecone', 'model': 'bge-reranker-v2-m3'}, 'generation': {'mode': 'not_applicable', 'candidates': []}, 'judge': {'mode': 'none', 'candidates': []}}`.

