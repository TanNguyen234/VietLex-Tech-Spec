# VietLex Evaluation Current Status

**Status (2026-08-09):** P2 retrieval baseline `COMPLETED`; quality result `NO_WINNER_ZERO_RECALL`; production readiness **NOT DEMONSTRATED**.

- Production readiness: **NOT DEMONSTRATED**.
- Historical 2026-08-03 retrieval runs remain invalid for decisions.
- Deterministic evaluation is primary; Ragas remains opt-in and is disabled for P2.
- No ingestion, corpus/index mutation, generation, or guardrail evaluation is part of P2.

## Promoted verified-gold checkpoint

The user approved exact preview SHA-256 `89138b35c77998c03d797d92c6e9d9a31070abc02bf4becb1a0fb26dbea5387c`. Promotion completed without overwriting the source sidecar.

- Dataset: `app/data/namsyntax_legal_qa_420_curated_v1.json`.
- Dataset SHA-256: `d6e125030e8dda700667ba00f25162fac76472a9bfa2d087f54e2b5bc73a1fee`.
- Source sidecar: `docs/evaluation/gold_labels/namsyntax_legal_qa_420_labels_v4.json`.
- Source-sidecar file SHA-256: `7629cec30a5afcd31d1517d142341a053ebe665691093c2742288f0a61433d5c`.
- Promoted sidecar: `docs/evaluation/adjudication/promotions/gold-adjudication-promotion-curated-v4_20260809_151015_227377/labels_v2.json`.
- Promoted-sidecar file SHA-256: `6044c084fd0cfd7b696b7e927ae2df26130e090aa64cf1a3b39a0784c1d8a9bf`.
- Promoted canonical sidecar payload SHA-256: `a04cc60c535ded71ea33f3b9b3b6105342b205f5e9f52e6636424ce8388a5089`.
- Promotion summary SHA-256: `25288a79c29f6b4b6534453f3239a49ad742a1f72c4351c4bb961bf837ba55db`.
- Queue SHA-256: `aac86e7921c319da7a82262a04df7df60745e7778aae262940c81791de606435`.
- Decisions SHA-256: `35959b6a89852b717458be5c3694e8899768df7b8f50731535c023fb25741b0b`.
- Counts after reload: 420 cases, 484 evidence items, 53 verified evidence items, 40 cases satisfying `all-required-verified`.
- Selected-case-set SHA-256: `02b147618710247b69406c62c37ee1733412cf99c803a3b818cfc0040e78cfd6`.
- Persisted reviewer identity: `conversation-user`; raw adjudication notes: absent.
- Provider calls during curation/adjudication/promotion: 0.
- Remote data, local corpus, Pinecone, Qdrant, content store, and FTS modified: no.

The earlier curated-v1 queue is retained immutably and explicitly marked superseded. It is not eligible for promotion or P2.

## P2 completed baseline

P2 compared these profiles on the exact same 40 selected cases and source state:

1. `legacy`
2. `separated_no_intent`
3. `separated_intent`

Pinned runtime flags were `rewrite=off`, `reranker=current`, `concurrency=1`, `verified-only=true`, and `gold-policy=all-required-verified`.

- Live source Git SHA: `aa3208c850d8b8f8782bab98ca925228202dfff8`; `git_dirty=false`.
- Live source-state SHA-256: `4c4a9c600ee59271052b746944bf5273ad6e64ae36b2332c45afa624a6b8b91d`.
- Selected-case-set SHA-256: `02b147618710247b69406c62c37ee1733412cf99c803a3b818cfc0040e78cfd6`.
- Preflight: `docs/evaluation/preflight/p2-ready-20260809-aa3208c/`; batch `OK`; provider calls 0; 40 cases; all three profiles shared the exact provenance above.
- Successful run IDs: `p2-legacy-aa3208c`, `p2-separated-no-intent-aa3208c`, `p2-separated-intent-aa3208c`.
- Comparison: `docs/evaluation/comparisons/p2-aa3208c/`.
- Comparison JSON SHA-256: `e6b45624c25095e2110de61f92b92fe2b0b93d1eaca4b6960feaaa4745495a7a`.
- Comparison report SHA-256: `4b4a11e8b1358214a0801351e8aecea669aee41deb3a814f35a5b2cd3300dc17`.
- Comparison was generated from clean Git SHA `944d3c996bddcd395d539e62dab4e8ba4bbb33c6`.

### Deterministic result

All three profiles produced the same failed retrieval quality:

- Status: 40/40 `ok`; scored 40; skipped 0; coverage 40/40.
- Document Recall@1, @3, @5, @10, and @24: `0/53` (`micro=0`, `macro=0`).
- Article Recall@3: `0/30`; 27 scored cases, 13 skipped because no applicable article gold.
- Clause Recall@3: `0/14`; 13 scored cases, 27 skipped because no applicable clause gold.
- Document MRR: `0/40`; nDCG@10 numerator `0`, denominator `48.20209`.
- Exact legal-reference hit: `0/40`.
- Multi-hop all-required coverage: `0/40`; partial coverage: `0/53`.
- No-candidate rate: `0/40`; retrieval technical-error rate: `0/40`; reranker technical-error rate: `0/40`.
- First loss: all 53 verified evidence items were absent at `source_retrieval_metrics`; document IDs `427301` and `431147` appeared in zero Pinecone, FTS, merged, resolved, structural, local-selection, reranker-input/output, or final traces.
- Reranker contribution is not measurable because zero verified gold reached the reranker input.
- Recommendation: none. Changing local intent scoring or larger post-source capacities cannot recover documents absent from both initial retrieval sources.

Total-latency summaries:

| Profile | Mean (s) | P50 (s) | P95 (s) | Max (s) |
| :--- | ---: | ---: | ---: | ---: |
| `legacy` | 5.9857 | 4.1813 | 13.9039 | 18.0353 |
| `separated_no_intent` | 6.9185 | 4.7377 | 14.1178 | 31.5816 |
| `separated_intent` | 6.4889 | 4.1044 | 15.5088 | 19.6317 |

Configured provider identifiers are provenance only. The current `RetrievalCaseResult` does not persist which reranker fallback actually served each request. The production Qdrant inference/rerank clients may use ephemeral staging points; no corpus ingestion, durable Pinecone index/namespace change, Qdrant collection recreation, local store/FTS mutation, generation, Ragas, guardrail evaluation, migration, or deployment was executed.

The verified subset is 40 curated cases from the 420-case evaluation dataset, not 40 cases independently sampled from all 518,255 corpus documents. The 53 promoted evidence items point to two pinned corpus documents, so the result diagnoses retrieval for this verified legal slice, not whole-corpus accuracy.

## Execution and verification evidence

- Promotion artifact reload and hash validation: passed.
- Relevant post-promotion suite: `195 passed in 23.70s`.
- Full post-promotion suite: `375 passed, 1 skipped in 59.93s`.
- Runner audit-summary TDD: RED reproduced two intended failures plus the missing-path failure; GREEN `19 passed in 5.78s`.
- Runtime adapter failure was reproduced from the first attempted live run: `AttributeError: 'EvidenceChunk' object has no attribute 'score'`. TDD regression passed after removing the invalid field read; relevant suite `199 passed in 20.11s`.
- Failed immutable run: `docs/evaluation/runs/p2-legacy-d9f76f1/failure.json`; completed cases 0; manifest/results/report were not written.
- Comparison TDD: 3 focused tests passed; comparison plus metrics/reporting/provenance suite: `27 passed in 8.17s`.
- Final focused regression/comparison gate: `4 passed in 5.16s`.
- Final relevant evaluation gate: `202 passed in 20.49s`.
- Final full suite: `382 passed, 1 skipped in 46.85s`; the skip is the existing opt-in live integration test.
- Fatal Ruff checks over `app`, both changed entrypoints, and affected evaluation tests: passed. Compileall and working/staged `git diff --check`: passed.
- A broader Ruff invocation over all legacy tests was also attempted and failed on pre-existing unused imports outside the P2 change scope; those unrelated tests were not mechanically rewritten.
- Real promoted-sidecar selection validation: 420 total cases, 40 selected, 484 evidence items, no implicit audit summary.
- Live retrieval execution: 120 successful case executions plus one aborted first-case attempt; exact provider call count was not instrumented.
- Remote durable corpus/index data modified: no. Ephemeral Qdrant inference/rerank staging may have been created and cleaned by the configured clients.

Execution plan: `docs/superpowers/plans/2026-08-09-vietlex-p2-retrieval-baseline.md`.
