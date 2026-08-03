# AGENTS.md — Mandatory Rules for AI Coding Agents

This file is the primary instruction source for every coding agent working in `VietLex-Tech-Spec`.

## 1. Current project objective

VietLex is a Vietnamese legal RAG system over a pinned third-party corpus of 518,255 documents. The current priority is not adding more features. The priority is making retrieval and evaluation measurable, reproducible, and technically honest.

Current quality status:

- the architecture is production-oriented but the latest benchmark is a failed baseline;
- answerable accuracy and retrieval quality are not yet acceptable;
- Ragas is too expensive and unstable to remain the default evaluator;
- deterministic retrieval-first evaluation must be established before changing embeddings, rerankers, generation models, or ingestion.

Never describe the system as production-ready unless a reproducible benchmark demonstrates it.

## 2. Current architecture — source of truth

The implementation in `app/config.py` and current production code overrides older plans and archived documentation.

### Persistent storage

- Pinecone index: `vietlex-legal-rag-v1`
- Pinecone namespace: `legal-documents-v1`
- One durable Pinecone record per legal document
- Full document content: local SQLite/Zstandard content store
- Qdrant is inference/staging only; it is not the durable corpus store

### Dense retrieval

- Model: `intfloat/multilingual-e5-small`
- Dimension: 384
- Dense query inference: Qdrant Cloud staging
- Persistent vectors: Pinecone

### Sparse retrieval

- Current implementation: local `FastSparseEncoder`
- Maximum non-zero terms: 64
- Do not call this implementation full BM25 unless corpus-level IDF is actually present

### Lexical retrieval

- Current SQLite FTS supports exact normalized document-number lookup and title search
- It does not currently provide full article/body search
- Do not claim article-level FTS is active until a verified index has been built

### Runtime retrieval

- Original query is used for sparse and exact-reference retrieval
- Rewritten query may be used for dense retrieval
- Pinecone hybrid retrieval and local FTS run concurrently
- Full text is resolved locally, then chunked by legal structure
- Current chunk limit: 220 approximate whitespace tokens
- Current overlap: 24 tokens for oversized structural units
- Rerank input limits, candidate limits, and document resolution limits are governed by evaluation profiles and runtime settings
- Current final evidence: up to 3 chunks within 720 context tokens

Configuration declarations in `app/config.py` do not prove runtime usage until verified by code execution. Any evaluation run executed from a dirty working tree must be recorded with `git_dirty=true` and a Git diff SHA-256 hash.

### Reranking

- Current primary: Qdrant `answerdotai/answerai-colbert-small-v1`
- Current fallback: Pinecone `bge-reranker-v2-m3`
- This order is not considered proven optimal for Vietnamese legal text
- Any provider switch requires an A/B benchmark on identical reranker inputs

### Generation and guardrails

- Generation uses the configured remote provider chain
- NeMo input and output guardrails are external-LLM-dependent and may timeout or produce false positives
- Guardrails must support `off`, `shadow`, and `enforce` evaluation modes
- A technical guardrail error must never be classified as a hallucination block

## 3. Evaluation policy

### Default evaluator

Deterministic code-based evaluation is the default.

Ragas must be optional and disabled unless explicitly requested. The default test or evaluation command must perform zero LLM judge calls.

### Required separation

Evaluation must separate:

1. online execution: retrieval, optional generation, optional guardrails;
2. offline deterministic metrics;
3. optional Ragas or other LLM judge audit.

Never hold the online pipeline semaphore while running Ragas, report generation, checkpoint writes, or offline metrics.

### Required deterministic retrieval metrics

At minimum:

- Document Recall@K
- Article Recall@K
- Clause Recall@K
- MRR
- nDCG@K
- exact legal-reference hit
- multi-hop all-required-evidence coverage
- partial-hop coverage
- candidate survival at every retrieval stage
- no-candidate rate
- retrieval technical-error rate
- reranker technical-error rate

Metrics must report numerator, denominator, coverage, skipped cases, and skip reasons.

### Required deterministic answer metrics

At minimum:

- normalized exact match
- token precision/recall/F1
- character F1
- ROUGE-L and CHRF as secondary metrics only
- expected number/date/entity precision and recall
- legal citation precision, recall, and coverage
- invalid-citation rate
- refusal precision and recall
- mixed factual-claim plus refusal rate

Do not claim that lexical similarity proves legal correctness or faithfulness.

### Immutable run artifacts

Every evaluation run must write to a unique directory:

`docs/evaluation/runs/<run-id>/`

Each run must contain its own manifest, configuration, raw results, and report. Never overwrite another run.

The manifest must include run ID, UTC timestamp, Git commit SHA, dataset revision, evaluation dataset SHA-256, configuration fingerprint, command, provider/model identifiers, and metric version.

## 4. Mandatory change workflow

Before editing:

1. inspect this file;
2. inspect `docs/PROJECT_CONTEXT.md`;
3. inspect `docs/AGENT_WORKFLOW.md`;
4. inspect `docs/CURRENT_ARCHITECTURE.md`;
5. inspect `app/config.py` and the actual implementation involved;
6. inspect affected tests;
7. identify whether the task changes runtime behavior, evaluation only, ingestion, or documentation.

During implementation:

1. write or update tests first for behavior changes;
2. make one logically isolated change at a time;
3. run focused tests after each change;
4. run the broader relevant suite before declaring completion;
5. preserve exact errors and real command output;
6. never replace missing evidence with invented evidence.

Before final reporting:

1. list files changed;
2. list exact commands executed;
3. distinguish unit tests, integration tests, and live provider calls;
4. report `NOT RUN` for anything not actually executed;
5. report remaining failures and limitations;
6. confirm whether any remote data was modified.

## 5. Destructive-operation policy

The following operations are forbidden unless the user explicitly authorizes that exact operation in the current task:

- delete or recreate the Pinecone index;
- run full corpus ingestion;
- rebuild or migrate all persistent vectors;
- delete or recreate Qdrant collections;
- delete local content stores, checkpoints, or FTS indexes;
- overwrite user-owned evaluation reports/checkpoints;
- commit, push, merge, or open a pull request;
- change production credentials or `.env`.

Commands containing `--delete-existing`, `--yes`, index deletion, collection deletion, or full ingestion must be treated as destructive.

## 6. No mock and no fabricated completion

- Production code must use real implementations.
- Test doubles are allowed only in tests.
- Do not create fake benchmark outputs, fake provider responses, fake ingestion reports, or fabricated screenshots/logs.
- Creating files is not proof that a pipeline ran.
- A task is not complete merely because code compiles.
- Never state that a live benchmark, ingestion, training, or deployment succeeded unless the command actually completed and evidence was saved.

## 7. Reingestion boundary

Do not change only one side of an already-ingested embedding contract.

Changes that usually require explicit reingestion include:

- adding or changing E5 `query:` or `passage:` prefixes;
- changing dense model or dimension;
- changing Pinecone metric;
- changing sparse document representation;
- changing persistent metadata required for filtering;
- changing one-document-per-vector into hierarchical vectors.

For these tasks, prepare a migration plan and benchmark justification. Do not execute the migration without explicit authorization.

## 8. Security and privacy

- Load all secrets through `app/config.py`.
- Never hardcode or log API keys.
- Never store raw private user content in audit logs when a hash or citation is sufficient.
- Preserve CSRF, CORS, authentication, and rate-limit protections when modifying API routes.
- Do not silently swallow database or provider failures.
- Technical errors must have typed status and observable diagnostics.

## 9. Documentation lifecycle

Use this precedence order:

1. current code and tests;
2. `app/config.py`;
3. `docs/PROJECT_CONTEXT.md`;
4. `docs/CURRENT_ARCHITECTURE.md`;
5. current runbooks;
6. implementation plans and historical design files.

Older plans under `docs/superpowers/` may be superseded. Do not implement an old Qdrant-durable, Cohere, Gemini embedding, or mandatory background-Ragas architecture merely because it appears in an older document.

When documentation conflicts with code, report the conflict and update the current source of truth. Do not silently select the older document.

## 10. Repository exploration

If code-review-graph MCP tools are available, use them first for architecture, impact radius, affected flows, and test relationships. Fall back to normal repository search and file reading when graph coverage is incomplete or unavailable.

Do not block the task solely because a preferred MCP tool is unavailable.
