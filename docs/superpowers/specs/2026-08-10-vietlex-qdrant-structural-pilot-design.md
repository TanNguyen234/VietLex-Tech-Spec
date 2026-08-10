# VietLex Qdrant Structural Pilot Design

**Date:** 2026-08-10

**Phase:** P3 — evidence-driven retrieval repair

**Status:** Architecture approved by the user on 2026-08-10; written specification pending final review.

**Supersedes:** `2026-08-09-vietlex-pinecone-hosted-structural-index-design.md` and the unexecuted Pinecone-only Tasks 2-6 in `2026-08-09-vietlex-structural-pilot.md`.

## Decision

Build the v2 primary-legislation pilot as a new Qdrant collection using Qdrant Cloud Inference for both dense embeddings and corpus-level BM25. The preferred dense candidate is `Qwen/Qwen3-Embedding-0.6B` at 1024 dimensions. It is not accepted merely because it is larger than 384 dimensions: an exact live model-contract probe and a benchmark over real in-scope verified gold evidence must pass before bulk reindexing.

The pilot remains opt-in. Pinecone v1 stays active and unchanged until a reproducible full-corpus pilot benchmark authorizes a separate cutover plan. This design creates code and guarded commands for the user to run; it does not authorize this implementation session to create, populate, switch, delete, or rebuild a remote collection or index.

## Evidence and corrected assumptions

### Retrieval failure

The current Pinecone v1 index contains one 384-dimensional vector per full legal document. The 40-case verified P2 baseline has zero Document Recall@24, and a read-only top-1000 investigation found the required document for only 11 of 40 queries. When found, ranks ranged from 25 to 901. Structural evidence that never enters source retrieval cannot be repaired by a later reranker, top-k adjustment, or local re-chunking step.

### Exact local pilot capacity

Provider-free enumeration of the pinned content store on 2026-08-10 produced:

| Measurement | Value |
|---|---:|
| Primary-legislation documents | 827 |
| Hiến pháp | 4 |
| Luật | 595 |
| Pháp lệnh | 228 |
| Structural records at 420/48 | 134,334 |
| Approximate chunk tokens | 10,876,502 |
| UTF-8 body bytes | 65,712,409 |
| Estimated metadata JSON bytes | 99,454,336 |
| Raw 1024-dimension float32 bytes | 550,232,064 (0.512 GiB) |
| Dense + body + metadata before index overhead | 0.666 GiB |

This replaces the earlier 108,630-record lower bound. The earlier value came from a truncated sparse-preparation statistic and was not a capacity estimate.

### Nullable source provenance

Document `72273` (`30/2001/QH10`) is a valid in-scope law with a pinned content hash but has an empty `issuing_authority` in the source corpus. It is the only selected document missing a currently required structural metadata field. The v2 record contract therefore uses `issuing_authority: str | None`. It preserves missing provenance as `null`; it does not drop the law and does not infer an authority from its number, title, or content.

### Current remote state

A read-only Pinecone probe confirmed that `vietlex-legal-rag-v1` is Ready, serverless OnDemand in AWS `us-east-1`, dimension 384, dot-product, and contains 518,255 vectors in `legal-documents-v1`.

The 2026-08-10 Qdrant probe timed out before `get_collection` returned. It performed no model inference and no write. Qdrant model availability, collection capacity, and live cluster health are therefore preflight requirements, not established facts.

## Options considered

### 1. Qdrant Cloud Inference and Qdrant durable pilot

**Chosen, conditional on preflight.** Structural text is sent once to Qdrant. Qdrant produces and stores a named 1024-dimensional dense vector and a named `qdrant/bm25` sparse vector in the same point. This eliminates the staging upsert/retrieve hop and the second upload to Pinecone.

Qdrant documents a free-cluster shape of 1 GB RAM, 0.5 vCPU, and 4 GB disk, with an indicative capacity around one million 768-dimensional vectors. The enumerated 134,334-record pilot is plausibly within that disk envelope, but body, payload indexes, sparse postings, HNSW, WAL, segments, existing collections, and safety headroom must be measured before creation. No capacity decision may use raw dense bytes alone.

### 2. Qdrant inference followed by Pinecone storage

Rejected as the default. The current Qdrant API pattern embeds by writing to a staging collection and retrieving vectors. Repeating that for 134,334 records before uploading to Pinecone adds network transfer, remote writes, checkpoints, and failure boundaries. It is slower and operationally more complex than letting Qdrant store the vectors it generated.

### 3. Pinecone-hosted embeddings and Pinecone storage

Retained only as an explicit fallback plan if the Qdrant candidate fails availability, quality, or capacity gates. The Pinecone smoke showed strong candidate-set quality for `llama-text-embed-v2` at 1024 dimensions, but Pinecone integrated-text upserts are limited to 96 records per request and Starter storage is capped at 2 GB across serverless indexes. The current v1 raw dense vectors alone occupy about 0.741 GiB before metadata and index overhead, so coexistence with v2 cannot be assumed safe without account-plan and storage evidence.

### 4. `mxbai/embed-large-v1` as the Qdrant dense model

Rejected as the preferred Vietnamese model. It has 1024 dimensions but is described as English-focused, has a 512-token model limit, and requires a fixed retrieval-query prompt. Dimension alone is not evidence of Vietnamese legal retrieval quality.

## Dense model contract

The preferred candidate is `Qwen/Qwen3-Embedding-0.6B` because its primary model documentation declares:

- more than 100 supported languages;
- a 32K context window;
- output dimensions from 32 through 1024;
- instruction-aware retrieval behavior.

The exact Qdrant model identifier, 1024-dimensional output, model options, token usage, and availability on the configured cluster must be obtained from a live probe against the newly created empty pilot collection. Qdrant performs Cloud Inference through collection query/upsert operations rather than the standalone embedding call used in the earlier Pinecone design. Code must not silently rename the model, choose another dimension, strip the query instruction, truncate text, or fall back to a local model.

The query instruction is a versioned configuration value written in every manifest. Passage text is embedded without the query instruction. Query and passage representation must use the same model revision and dimension.

## Corpus and structural record contract

The pilot scope is deterministic and gold-agnostic:

- legal type exactly `Hiến pháp`, `Luật`, or `Pháp lệnh`;
- dataset repository `vohuutridung/vietnamese-legal-documents`;
- pinned revision `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`;
- all 827 selected document IDs in ascending order.

Each point contains:

- a deterministic record ID derived from repository, revision, document ID, chunk order, and chunk SHA-256;
- structural body text, at most 420 approximate whitespace tokens with 48-token overlap only for oversized structural units;
- document ID, document number, title, source URL, legal type, nullable issuing authority, and issuance date;
- article, clause, heading path, citation, token count;
- dataset revision, document content SHA-256, and chunk SHA-256;
- named dense and BM25 vectors produced inside Qdrant.

The implementation streams bounded document batches. It must not materialize all records merely to count or upload them. Record identity is idempotent across retries and resume runs.

## Qdrant collection contract

The proposed target is a new collection named `vietlex-legal-rag-v2-pilot`. It never reuses `vietlex-embedding-staging`, `vietlex-rerank-staging`, or any v1 storage target.

Collection vector schema:

- `dense`: 1024 dimensions, cosine, stored on disk;
- `bm25`: sparse vector with IDF modifier when supported by the live Qdrant version;
- HNSW disabled with `m=0` during bulk upload, then enabled with `m=16` during an explicit finalize phase;
- payload indexes created before upload for fields used by runtime filters and provenance checks.

The initial collection uses the shard count justified by live cluster capacity. Free single-node clusters start with one shard and one upload worker. More shards or workers are allowed only when cluster telemetry supports them.

No implementation command recreates or deletes an existing collection. If the target already exists with any schema or manifest mismatch, creation fails closed.

## Retrieval flow

1. Normalize the user query without rewriting legal references away.
2. Add the versioned Qwen retrieval instruction for the dense query only.
3. Run dense and BM25 prefetches against the structural collection.
4. Fuse candidates using deterministic reciprocal-rank fusion while retaining source rank, score, and technical errors.
5. Merge exact document-number matches as a deterministic lane.
6. Deduplicate on structural record ID and cap per-document candidates.
7. Rerank a bounded merged set with the existing remote reranker.
8. Return structural chunks directly; do not resolve and re-chunk full documents again.

Dense, BM25, exact-reference, fusion, and reranker failures remain separately observable. A provider failure cannot be converted into an empty successful retrieval.

## Reindex command phases

The user-operated CLI exposes independent phases:

1. `audit`: enumerate the local scope and validate content and chunk contracts; zero provider calls.
2. `plan`: write an immutable capacity, model, scope, and command manifest; zero writes.
3. `create`: create the exact empty collection after validating the plan hash and an explicit remote-write authorization.
4. `probe-model`: idempotently upsert the real in-scope structural gold subset, verify the model/schema/usage contract, and benchmark that subset before bulk upload.
5. `upload`: only after `PASS_MODEL_PROBE`, stream all remaining idempotent batches with checkpointed committed record IDs.
6. `finalize`: enable HNSW and wait for optimizer health without changing record content.
7. `verify`: compare remote count, collection schema, deterministic sample hashes, and provider usage with the plan.
8. `benchmark`: run deterministic retrieval evaluation and write an immutable run directory.

There is no `delete`, `recreate`, automatic `cutover`, or implicit cleanup command in this plan.

The probe records use their final deterministic record IDs and are a genuine subset of the planned collection, not synthetic provider responses. A later bulk upload safely overwrites identical IDs with identical content. If the probe fails, the command writes a failure artifact and leaves the small collection unchanged for audit; it does not delete or repurpose it.

## Throughput design

Maximum useful speed is defined as the highest sustained throughput that preserves exact accounting and does not cause repeated throttling or incomplete batches.

- use the Qdrant gRPC path for upload when the live endpoint supports it;
- begin at 64 records per batch and adapt within a tested 64-256 range;
- start at one worker per shard and increase only while latency, timeout, CPU, and 429 evidence remain healthy;
- keep vectors on disk from collection creation instead of converting segments during ingestion;
- create known payload indexes before data upload;
- disable HNSW construction during upload and build it once after the final committed batch;
- use bounded exponential backoff only for typed transient failures;
- reduce concurrency on repeated transient failures instead of retrying every worker at full speed;
- persist checkpoints atomically after acknowledged batches;
- on resume, verify source, plan, collection, model, and record hashes before continuing;
- record elapsed time, records/second, tokens/second, retry count, provider usage, and final optimizer time.

Sparse BM25 indexing cannot be deferred in the same way as dense HNSW, so its throughput cost must remain visible in the report.

## Capacity and quota gates

Before `create`:

- Qdrant endpoint and configured credentials are reachable;
- target collection does not exist;
- live disk, RAM, vCPU, shard count, and existing collection usage are recorded from reachable telemetry or bound by an explicit capacity configuration when the service does not expose those values;
- projected total storage includes dense vectors, body, metadata, sparse index, HNSW, WAL/segments, and at least 25% safety headroom;
- predicted usage fits the live cluster rather than a generic plan description.

Before `upload`:

- Cloud Inference has succeeded on the exact target collection;
- the exact dense and sparse model identifiers and options are accepted;
- retrieved probe vectors have the declared 1024-dimensional shape;
- provider inference usage is present in responses;
- the immutable probe artifact records `PASS_MODEL_PROBE` on the declared verified denominator.

If the Qdrant cluster cannot meet the capacity gate, the command returns `BLOCKED_CAPACITY`. It does not delete old collections or automatically switch to Pinecone.

## Quality gates

The model probe and benchmark use only verified golden cases whose evidence resolves to the pinned knowledge corpus and declared primary-legislation scope. Reports include the exact dataset and sidecar SHA-256, included case IDs, numerator, denominator, coverage, skipped cases, and skip reasons. No synthetic decision or invented evidence may enter the acceptance denominator.

Before remote reindexing, the candidate model must pass a passage-ranking smoke on all eligible verified in-scope gold evidence. The initial reference floor is the prior Pinecone `llama-text-embed-v2` 1024 candidate smoke: Recall@1 0.975, Recall@3 1.000, and MRR 0.9833 on its 40-case set. If denominators differ, both results must be recomputed on the identical eligible set before comparison.

After upload, the full structural retrieval benchmark must report non-zero Document, Article, and Clause Recall; candidate survival per stage; exact-reference hits; MRR; nDCG; technical-error rates; latency; and provider usage. A model-smoke pass cannot authorize cutover by itself.

Acceptance states are:

- `PASS_MODEL_PROBE`: exact contract and candidate ranking meet the declared floor;
- `PASS_PILOT`: immutable full-corpus run materially improves P2 without provenance drift or technical errors;
- `FAIL_QUALITY`: valid execution below the quality floor;
- `BLOCKED_TECHNICAL`: model, provider, network, schema, or artifact failure;
- `BLOCKED_CAPACITY`: live storage or compute headroom is insufficient;
- `BLOCKED_SCOPE`: required verified evidence is outside the declared corpus.

## Testing and verification

- TDD unit tests for nullable provenance, deterministic IDs, streaming enumeration, model options, query instruction, exact vector schema, adaptive batching, retries, checkpoint resume, and remote-write gates.
- Fake clients only at external provider boundaries; production code contains no fake or local embedding fallback.
- Contract tests assert exact outgoing `Document` model/options and collection schema.
- Provider-free tests cover RRF, error separation, scope filtering, artifact hashing, and dry-run commands.
- A live probe is a separate user-run command and records actual provider calls. It is never part of default pytest.
- Focused and affected suites run after each task; Ruff, compileall, `git diff --check`, CRG change review, and one full pytest run are required before implementation completion.
- Every live operation not executed is reported as `NOT RUN`.

## Cutover and deletion boundary

This design does not change the default production backend. A separate cutover plan requires an immutable `PASS_PILOT`, runtime latency evidence, capacity after HNSW completion, rollback steps, and an exact user-authorized target.

Pinecone v1 deletion, Qdrant staging cleanup, collection recreation, full 518,255-document ingestion, and expansion beyond primary legislation remain forbidden unless separately and exactly authorized. Reindex code must never treat a general execute flag as permission to delete data.

## Known limitations

- The verified gold set is concentrated in a small number of laws and cannot prove regulatory-document coverage.
- Qdrant availability and the exact Qwen model identifier on the configured cluster are not yet verified because the read-only endpoint timed out.
- The 0.666 GiB estimate excludes sparse postings, HNSW, payload-index, WAL, segment, and allocator overhead.
- A Qdrant free cluster is suitable for a pilot, not evidence of production availability or SLA.
- BM25 quality depends on Qdrant's corpus-level tokenizer and IDF behavior; Vietnamese legal-reference performance must be measured rather than assumed.
- The runtime remains v1 until a later cutover, so completing local code or even reindexing a pilot does not make VietLex production-ready.

## Primary references

- Qdrant Cloud cluster capacity: <https://qdrant.tech/documentation/cloud/create-cluster/>
- Qdrant Cloud Inference and billing boundary: <https://qdrant.tech/documentation/cloud/inference/>
- Qdrant bulk upload guidance: <https://qdrant.tech/documentation/database-tutorials/bulk-upload/>
- Qdrant HNSW bulk-index optimization: <https://qdrant.tech/articles/indexing-optimization/>
- Qdrant use of Qwen3 embeddings in Cloud Inference experiments: <https://qdrant.tech/articles/relevance-feedback/>
- Qwen3 Embedding 0.6B model contract: <https://huggingface.co/Qwen/Qwen3-Embedding-0.6B>
- Pinecone database, storage, batch, and throughput limits: <https://docs.pinecone.io/reference/api/database-limits>
- Pinecone high-throughput ingestion guidance: <https://docs.pinecone.io/guides/optimize/increase-throughput>
