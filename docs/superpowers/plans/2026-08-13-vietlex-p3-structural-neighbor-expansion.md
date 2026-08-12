# P3 experiment: bounded legal-structure neighbor expansion

## Entry evidence

The cap-8, exact-input reranker comparison selected Pinecone BGE for the next experiment, but the reranker cannot recover evidence absent from its input. Three required items remain missing at reranker input:

- `case_323`: document `427301`, `Điều 124`, required article; absent from dense/BM25 top 48. BM25 top 96 finds it only at rank 79, after the fused bound.
- `case_371`: document `427301`, `Điều 164`, clause `3`; absent from dense/BM25 top 96, while multiple chunks from the same article and clause `2` are retrieved.
- `case_397`: document `427301`, `Điều 197`, clause `1`; dense rank 13 but fused/input bounding removes it. A neighboring `Điều 196` requirement is fused rank 1.

Increasing both source top-k values from 48 to 96 did not recover these items into fused candidates and worsened some RRF positions. That family is rejected without a full benchmark.

## Frozen experiment

Change exactly one candidate-generation behavior: after normal RRF, fetch a bounded set of structural neighbors for already retrieved document/article locators, then fuse/dedupe them before the cap-8 candidate bound. Keep E5/BM25 models, vectors, source top-k 48, RRF k 60, reranker input 24, Pinecone BGE, return limit 6, final limit 3, context 720, and all persistent data unchanged.

Neighbor definition must be deterministic and legal-structure based:

- same document and same article sibling clauses;
- immediately preceding/current/following article numbers for numeric `Điều N` locators;
- no cross-document expansion;
- a strict per-query remote-read limit and deduplication by immutable record ID;
- malformed locator/payload/read failures become typed observable technical errors.

## TDD and review gates

1. RED: retrieved `Điều 123` can expand to `Điều 124`; retrieved `Điều 164` clause `2` can expand to sibling clause `3`; unrelated documents/articles cannot enter.
2. RED: remote read overflow, malformed payload, revision mismatch, and provider failure are fail-closed and typed.
3. GREEN with the smallest transport/read interface; no upsert/delete/reindex path.
4. Source-review transport filters, bounds, trace observability, provider-call accounting, and production-route isolation.
5. Focused suite, then full suite once.
6. Run one immutable Pinecone-BGE benchmark and accept only if reranker-input all-required coverage and required-level recall improve with zero new technical errors. Production cutover remains a separate decision.

## Authority boundary

Allowed experiment effects are bounded Qdrant reads/inference and Pinecone reranker calls. Forbidden: collection writes/deletes/recreation, reindexing, Pinecone corpus mutation, local-store/FTS mutation, generation, Ragas, evidence promotion, credentials, and production routing changes.
