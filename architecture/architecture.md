# CURRENT_ARCHITECTURE.md — Current VietLex Architecture

Status: current implementation reference  
Historical plans under `docs/superpowers/` may conflict with this file.

## Storage

```text
Pinned Hugging Face snapshot
        |
        v
Local content store (SQLite + compressed full text)
        |
        +--> Dense document representation
        |       |
        |       v
        |   Qdrant Cloud inference (E5-small, 384d)
        |       |
        |       v
        +--> Pinecone durable dense+sparse record
        |
        +--> Local title/exact-number FTS
```

Pinecone is the durable vector store. Qdrant is not a durable copy of the 518,255-document corpus.

## Runtime retrieval

```text
Original query
   |
   +--> exact document number + title FTS
   |
   +--> sparse encoding -------------------------+
   |                                             |
   +--> original query (default) -> Qdrant E5 ---+--> Pinecone hybrid top 24
   |    optional evaluation rewrite only         |
                                                  |
FTS IDs ------------------------------------------+
                                                  v
                                      balanced document selection
                                                  |
                                                  v
                                     resolve local full documents
                                                  |
                                                  v
                                chapter/section/article/clause chunking
                                                  |
                                                  v
                                      local lexical chunk selection
                                                  |
                                                  v
                               remote reranker, currently up to 12 chunks
                                                  |
                                                  v
                                    top 3, context <= 720 tokens
                                                  |
                                                  v
                                Vertex AI answer generation
                                  gemini-3.5-flash via ADC
                                                  |
                                   typed technical failure only
                                                  v
                   OpenRouter -> Gemini Direct API -> NVIDIA -> Groq
                              secondary answer models
```

`gemini-embedding-2` is isolated behind the Vertex provider for G0 probes at
384/768/1024 dimensions. It cannot feed the production E5 index, and the probe
has no Pinecone/Qdrant write dependency. Vertex generation failures are typed
and may activate the existing direct-API models as secondary answer providers.
The observed provider/model and primary failure kind remain in runtime metadata.
NeMo guardrails use the same Vertex-primary adapter and legacy direct-API fallbacks.
OmniGate remains an evaluator dependency, not an answer or guardrail primary.

## Current implementation cautions

- `RETRIEVAL_DOCUMENT_LIMIT` and `RERANK_CANDIDATE_LIMIT` represent different concepts and must not be conflated.
- Dense-provider failure plus usable FTS evidence is observable as `partial_retrieval_error`; it remains quality-scoreable but counts as a retrieval technical error.
- Only a limited number of chunks currently survive per document before reranking.
- FTS is not article-body FTS.
- Current sparse encoding is not full BM25 with corpus-level IDF.
- The current primary reranker is an implementation choice, not a proven Vietnamese-domain winner.
- E5 ingestion/query contract changes require coordinated migration.
- Technical provider errors must never be treated as valid no-evidence refusals.

## Evaluation architecture target

```text
Stage A: online execution
query -> retrieval -> Vertex generation -> persist raw result -> release online semaphore

Stage B: deterministic offline evaluation
persisted result -> retrieval metrics -> answer metrics -> latency metrics -> report

Stage C: optional offline judge audit
sampled persisted result -> optional Ragas/Vertex judge -> separate audit artifact
```

`/chat` performs zero Ragas calls. Default evaluation also performs zero judge
LLM calls.

## Sources of truth

1. code and tests;
2. `app/config.py`;
3. this file;
4. `docs/PROJECT_CONTEXT.md`;
5. current runbooks;
6. historical plans/specs.

Any conflict must be reported explicitly.
