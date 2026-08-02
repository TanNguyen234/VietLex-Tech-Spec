# Vietnamese Legal Documents Full-Corpus RAG Design

> **Implementation amendment (2026-07-30):** Dense and sparse ingestion use
> Qdrant Cloud Inference `intfloat/multilingual-e5-small` (384 dimensions) and
> `qdrant/bm25`. This supersedes the BGE-M3/1024 and local sparse ingestion
> details below. The final 16 × 128 concurrent configuration measured about
> 46.58 documents/second without failures; batch 512 was rejected after
> repeated inference 500s. BGE-reranker-v2-M3 remains unchanged.

Date: 2026-07-29
Status: Approved in conversation; crawler-removal prerequisite completed
Project: VietLex Legal RAG

## 1. Objective

Replace every crawler-related code path, test, script, document, and data artifact with a reproducible ingestion pipeline for the external Hugging Face dataset `vohuutridung/vietnamese-legal-documents`.

The pipeline must:

- download the complete dataset into the project without creating a second Hugging Face Arrow cache;
- preserve dataset provenance, revision, file sizes, and SHA-256 checksums;
- ingest all 518,255 documents into a new Qdrant knowledge-base collection;
- fit the knowledge-base index within the user's approximately 4 GB Qdrant capacity;
- retain the configured BGE-M3 dense embedding service and BGE-reranker-v2-M3 service;
- improve ingestion throughput through bounded asynchronous batching, server-side dense/BM25 inference, checkpointing, and Qdrant bulk upload;
- provide reliable citations and explicit quality limitations without representing the third-party corpus as authoritative legal advice;
- remove hardcoded credentials and load all secrets through `app/config.py`.

## 2. Verified Inputs and Constraints

### Dataset

- Repository: `https://huggingface.co/datasets/vohuutridung/vietnamese-legal-documents`
- Pinned revision observed on 2026-07-29: `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`
- License declared by the publisher: CC BY 4.0
- Documents: 518,255
- Metadata config: one Parquet shard, approximately 82 MB compressed
- Content config: eleven Parquet shards, approximately 3.51 GB compressed
- Total remote storage reported by Hugging Face: 3,590,886,390 bytes
- Materialized content size reported by the dataset server: 10,685,379,581 bytes
- Join key: integer `id`
- Content format: normalized plain/Markdown-like Vietnamese text without residual HTML in the inspected sample

The metadata and content configs have separate physical orderings. They must be joined by `id`; row position must never be treated as the join key.

Sample inspection showed a highly skewed document-length distribution. Some documents expose `Chương`, `Mục`, and `Điều` structure, while many administrative documents do not. Runtime chunking therefore needs a legal-structure path and a deterministic paragraph/token fallback.

### Existing services

- Dense embedding service: BGE-M3, 1024 dimensions
- Reranking service: BGE-reranker-v2-M3
- Qdrant client installed during discovery: 1.18.0
- Existing Qdrant collections observed:
  - `test_inference_collection`
  - `vietlex_knowledge_base`
  - `vietlex_laws_crawler_kb`
  - `vietlex_semantic_cache`
- Qdrant capacity communicated by the user: approximately 4 GB
- Local free space observed before cleanup/download: approximately 12.8 GB on drive D

### Capacity consequence

Article-level indexing of the full corpus cannot fit into 4 GB. Two million 1024-dimensional float32 vectors alone require approximately 7.6 GiB before HNSW, sparse vectors, payload, or segment overhead.

The approved design therefore indexes exactly one Qdrant point per source document and performs fine-grained legal chunking only after retrieving candidate documents. This preserves full corpus coverage while keeping the remote vector index bounded.

## 3. Selected Architecture

### 3.1 Remote Qdrant document index

Create a new collection named `vietlex_legal_documents_v1`.

Each of the 518,255 documents becomes one deterministic point:

- Point ID: UUIDv5 derived from dataset repository, pinned revision, and source `id`
- Named dense vector: `dense`
  - BGE-M3
  - 1024 dimensions
  - cosine distance
  - Qdrant `FLOAT16` storage
  - vector data stored on disk
- Named sparse vector: `bm25`
  - real BM25-compatible sparse representation
  - Vietnamese text segmented consistently for documents and queries
  - IDF modifier enabled in Qdrant
  - sparse index stored on disk when supported by the server
- Minimal payload:
  - `document_id`
  - `document_number`
  - `title`
  - `legal_type`
  - `legal_sectors`
  - `issuing_authority`
  - normalized `issuance_date`
  - `source_url`
  - `dataset_repository`
  - `dataset_revision`
  - `content_sha256`
  - `content_store_key`
  - `quality_flags`

Full document content is deliberately excluded from Qdrant payloads because it would consume most or all of the 4 GB capacity before vector indexes were built.

The dense retrieval representation is bounded and deterministic:

1. document number, title, type, sectors, authority, and date;
2. the leading substantive text;
3. a structural outline composed from detected `Chương`, `Mục`, and `Điều` headings throughout the document;
4. truncation to the configured BGE-M3 token budget.

The sparse representation uses the same metadata and structural outline with a stricter token limit to bound sparse-index growth.

### 3.2 Local compressed content store

Raw pinned Parquet files remain under:

`data/huggingface/vohuutridung__vietnamese-legal-documents/<revision>/`

A local SQLite content store is built beside them. Every content value is compressed independently with Zstandard so a retrieved document can be decompressed without reading an entire 100–400 MB Parquet row group.

The store contains:

- source document ID as primary key;
- compressed UTF-8 content;
- uncompressed byte length;
- SHA-256 content hash;
- source shard and source row position for audit;
- build metadata and schema version.

MongoDB is not added to the knowledge retrieval path. It remains available for conversations, feedback, evaluation, and administrative logs. Moving the corpus into MongoDB would create another remote capacity and consistency dependency without improving the legal accuracy of the source material.

### 3.3 Runtime two-stage retrieval

The request path is:

1. Rewrite the user query when the existing query-rewrite policy requires it.
2. Generate one BGE-M3 query vector.
3. Generate one BM25-compatible sparse query vector.
4. Run dense and sparse prefetches in one Qdrant hybrid query and fuse them with Qdrant RRF.
5. Retrieve a bounded candidate set of source documents.
6. Load candidate full texts from the local compressed content store.
7. Split candidate texts:
   - legal path: `Chương` → `Mục` → `Điều` → `Khoản`;
   - fallback path: normalized paragraphs with token-bounded windows and small overlap;
   - preserve heading ancestry and article/clause citations in every chunk.
8. Apply a cheap lexical prefilter so the remote cross-encoder never receives an unbounded number of chunks.
9. Rerank the bounded chunk set with BGE-reranker-v2-M3.
10. Send the top three evidence chunks to the answer model with source metadata and URLs.

Qdrant and HTTP clients are application-scoped reusable clients. The request path must not construct and close a new client for every dense or sparse search.

## 4. Ingestion Design and Throughput

### 4.1 Download

The downloader:

- resolves only the approved pinned revision;
- downloads the dataset card, one metadata Parquet shard, and eleven content Parquet shards directly into the project;
- uses `.part` files, HTTP range resume, timeouts, retries with jitter, and atomic rename after validation;
- verifies remote expected size and computes SHA-256 locally;
- writes a machine-readable manifest containing repository, revision, URL, size, checksum, completion timestamp, and tool version;
- does not use `load_dataset()` in materialized mode and does not populate a second global Arrow cache.

### 4.2 Streaming preparation

Preparation is a bounded pipeline:

- stream Parquet record batches with PyArrow;
- build an ID-keyed metadata lookup from the approximately 82 MB metadata shard;
- validate uniqueness and missing joins;
- normalize metadata and content;
- build the Zstandard SQLite content store in large transactions;
- derive dense retrieval text and sparse retrieval text;
- write durable batch records to a checkpoint database.

The process never holds the full content corpus or all embeddings in memory.

### 4.3 Embedding and sparse encoding

Dense embedding uses a shared `httpx.AsyncClient` and configurable bounded concurrency. Batches are limited by both document count and total input size to prevent a few very long documents from causing timeouts.

Defaults are selected by a benchmark rather than hardcoded as universal values:

- start with 8 concurrent embedding requests;
- start with up to 32 documents per request;
- cap aggregate characters/tokens per request;
- reduce concurrency on repeated 429/5xx/timeout responses;
- retry transient failures with exponential backoff and jitter;
- fail permanently invalid rows into an audit table without silently inventing vectors.

Sparse encoding uses Qdrant Cloud Inference model `qdrant/bm25`. Documents and
queries use the same server-side model and IDF-enabled named sparse vector.

### 4.4 Qdrant upload

Before the destructive remote operation, local download, validation, content-store construction, unit tests, and a real embedding smoke test must pass.

Then:

1. delete all four existing collections explicitly authorized by the user;
2. create `vietlex_legal_documents_v1`;
3. create required payload indexes before building HNSW;
4. use two shards when accepted by the target cluster;
5. disable or defer HNSW indexing during the initial load;
6. stream deterministic points through `upload_points` with bounded batches, parallelism, retries, and idempotent IDs;
7. checkpoint every completed upload batch;
8. restore production optimizer/HNSW settings after upload;
9. wait for optimizer completion;
10. verify point count, random payload/hash samples, dense search, sparse search, hybrid search, and local content resolution.

The process runs a measured 1,000-document and 10,000-document benchmark before continuing automatically to the full corpus. These are not substitutes for the full run; they tune batch and concurrency values and catch capacity or service-limit failures early.

Speed acceptance is:

- no serial per-document network calls;
- at least three times the throughput of the repository's existing batch-8/serial-upsert path on the same 10,000-document benchmark, unless the embedding service itself enforces a lower rate limit;
- bounded memory;
- resumability without regenerating or re-uploading completed batches;
- an ingestion report with wall time, documents/second, retry counts, rejected rows, and final Qdrant count.

## 5. Reliability and Data Quality

The dataset is a third-party research compilation sourced from `thuvienphapluat.vn`. It is not an official state database and does not provide sufficient metadata to establish current legal effect for every document.

Reliability measures:

- pin and display the exact dataset revision;
- verify all downloaded files by size and SHA-256;
- preserve source URL and document number in retrieval results;
- detect missing metadata, duplicate IDs, duplicate content hashes, invalid dates, empty content, encoding damage, and abnormal lengths;
- store quality flags with every indexed point;
- never infer that a document is in force merely because it exists in the dataset;
- make the answer prompt disclose uncertainty when effectiveness/status cannot be verified;
- keep the semantic cache threshold at 0.96 and include corpus revision in cache identity so stale answers do not survive a corpus replacement;
- provide prominent README and UI/API disclaimers that results are informational and must be checked against official/current sources or qualified counsel.

The database choice does not make a source authoritative. Provenance, revision control, validation, citations, and status-aware answer behavior are the relevant controls.

## 6. Security

- Remove the hardcoded embedding-service key currently present in `app/config.py`.
- Load Qdrant, embedding service, reranker, OmniGate, MongoDB, and Logfire credentials only through Pydantic settings and environment variables.
- Never write secret values to manifests, checkpoints, logs, tests, README, or command output.
- Continue sending the required Bearer authorization header to embedding/rerank and OmniGate services.
- Keep production ingestion connected to real services; test doubles are limited to automated tests and are not available as production fallbacks.

## 7. Crawler Removal Scope

Delete crawler-specific production modules, crawler entry points, crawler tests, raw/processed crawler datasets, crawl manifests, crawl logs, live-site debugging scripts, crawler-specific plans/specifications, and crawler-derived documentation.

Replace the existing legacy dataset indexers with one Hugging Face ingestion implementation under `app/ingestion/`.

Before deletion, produce a path-level audit list. Preserve unrelated user work and unrelated evaluation artifacts. Existing dirty-worktree items are removed only when they are demonstrably crawler-related or derived from crawler output.

No git commit, push, migration, or unrelated external mutation is included without explicit user authorization.

## 8. Error Handling and Recovery

- Download: resume partial files and reject checksum/size mismatch.
- Dataset validation: stop before Qdrant deletion on missing shards, duplicate IDs, join failure, or insufficient local disk.
- Content store: use transactional batches and integrity checks.
- Embedding: retry transient failures; record permanent failures with source IDs and error categories.
- Qdrant upload: deterministic IDs and completed-batch checkpoints make retries idempotent.
- Capacity: stop cleanly on storage/quota errors and retain local prepared artifacts/checkpoints.
- Final optimizer: poll with bounded intervals and emit progress; do not claim completion until collection status and point count are verified.
- Runtime retrieval: fail closed with a no-evidence response when Qdrant, local content resolution, or reranking cannot provide sufficient grounded context.

## 9. Test and Verification Strategy

Tests are written before behavior changes.

Unit tests cover:

- dataset revision/path resolution;
- metadata/content joins by ID rather than position;
- legal-structure and fallback chunking;
- deterministic point IDs;
- retrieval-text token bounds;
- content compression/decompression and hash verification;
- sparse document/query preprocessing parity;
- adaptive batching;
- checkpoint resume behavior;
- payload construction and quality flags;
- collection configuration;
- hybrid result mapping and local dynamic chunk reranking;
- corpus-revision-aware semantic cache behavior;
- credential defaults contain no secrets.

Integration verification covers:

- pinned download of a small real range/shard fixture;
- real embedding dimension equals 1024;
- real reranker response contract;
- real Qdrant create/upload/query/delete against a temporary test collection;
- 1,000- and 10,000-document ingestion benchmarks;
- full point-count reconciliation at 518,255;
- random end-to-end legal queries with source URL, document number, and article-level evidence.

Final review uses code-review-graph change detection, affected flows, and test coverage analysis before repository-wide tests are run.

## 10. Operational Sequence

1. Approve this written spec and authorize its commit if a commit is desired.
2. Remove crawler-related repository content using the reviewed deletion list.
3. Produce the implementation plan using the writing-plans workflow.
4. Add failing tests.
5. Implement dataset download, validation, content store, and audit report.
6. Implement capacity-bounded collection creation and resumable ingestion.
7. Update runtime hybrid retrieval and semantic cache dimensions/revisioning.
8. Update README and supporting architecture/setup documentation.
9. Run local tests and real-service smoke/benchmark checks.
10. Delete the four authorized Qdrant collections.
11. Create the new collection and run the complete ingestion.
12. Verify final count, optimizer state, retrieval behavior, disk constraints, and generated audit artifacts.

## 11. Sources Consulted

- Dataset card and repository API: `https://huggingface.co/datasets/vohuutridung/vietnamese-legal-documents`
- BGE-M3 model card: `https://huggingface.co/BAAI/bge-m3`
- BGE-reranker-v2-M3 model card: `https://huggingface.co/BAAI/bge-reranker-v2-m3`
- Qdrant bulk upload: `https://qdrant.tech/documentation/database-tutorials/bulk-upload/`
- Qdrant hybrid queries: `https://qdrant.tech/documentation/search/hybrid-queries/`
- Qdrant full-text/BM25 search: `https://qdrant.tech/documentation/search/text-search/full-text-search/`
- Qdrant optimizer configuration: `https://qdrant.tech/documentation/operations/optimizer/`
