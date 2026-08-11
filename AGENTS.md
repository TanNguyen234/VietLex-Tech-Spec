# AGENTS.md — VietLex mandatory rules

These rules apply to every coding agent in this repository. Current code and tests override historical plans.

## Objective and status

VietLex is a Vietnamese legal RAG system over a pinned third-party corpus of 518,255 documents. The priority is measurable, reproducible, technically honest retrieval and evaluation—not feature growth. The latest benchmark is a failed baseline; never call the system production-ready without a reproducible benchmark.

Use this source order: current code/tests → `app/config.py` → `docs/PROJECT_CONTEXT.md` → `docs/CURRENT_ARCHITECTURE.md` → current runbooks → historical plans. Report conflicts and update the current source of truth; do not revive superseded Qdrant-durable, Cohere, Gemini-embedding, or mandatory-Ragas designs.

## Pinned architecture

- Durable corpus: Pinecone `vietlex-legal-rag-v1`, namespace `legal-documents-v1`, one record per document; full text is local SQLite/Zstandard.
- Qdrant is inference/staging only unless a separately approved migration changes that contract.
- Dense model: `intfloat/multilingual-e5-small`, dimension 384; query inference uses Qdrant Cloud staging and persistent vectors use Pinecone.
- Sparse retrieval is local `FastSparseEncoder`, max 64 nonzero terms. Do not call it full BM25 without corpus-level IDF.
- SQLite FTS supports normalized document-number lookup and title search, not verified article/body search.
- Original query feeds sparse/exact retrieval; rewritten query may feed dense retrieval. Pinecone hybrid and local FTS run concurrently.
- Resolved documents are structurally chunked at 220 approximate whitespace tokens with overlap 24; final evidence is up to 3 chunks / 720 context tokens.
- Primary reranker is Qdrant `answerdotai/answerai-colbert-small-v1`; fallback is Pinecone `bge-reranker-v2-m3`. Provider changes require an A/B benchmark on identical inputs.
- Guardrails must support `off`, `shadow`, and `enforce`; technical guardrail failures are never hallucination blocks.
- A config declaration is not runtime proof. Dirty-tree evaluation manifests require `git_dirty=true` and the Git diff SHA-256.

## Change workflow

Before editing, inspect this file, `docs/PROJECT_CONTEXT.md`, `docs/AGENT_WORKFLOW.md`, `docs/CURRENT_ARCHITECTURE.md`, `app/config.py`, affected implementation/tests, and classify the change as runtime, evaluation, ingestion, or documentation.

For behavior changes:

1. Freeze scope, contract, authority, failure case, focused test, and review target.
2. Write/update tests first; observe the intended RED failure.
3. Make one root-cause change; run only invalidated focused gates while findings remain.
4. Review the stable diff and important error paths. Source-validate graph findings.
5. Run the broader/full suite once after review is clean. Any source/config change invalidates later proof and requires rerunning affected gates.
6. Generate durable benchmark/report artifacts only after source/config are stable.

Before final reporting, list changed files and exact commands; distinguish unit, integration, and live-provider runs; mark unexecuted work `NOT RUN`; report failures/limits, Git state, and remote effects. Creating files or compiling is not proof a live pipeline succeeded.

Git worktrees default to OFF. Use one only when the current task explicitly requests isolation.

## Evaluation contract

- Deterministic code-based evaluation is the default. Ragas/LLM judges are opt-in and must make zero calls in default tests/evaluation.
- Keep online retrieval/generation/guardrails separate from offline deterministic metrics and optional judge audits. Never hold the online semaphore during offline metrics, reporting, checkpoints, or Ragas.
- Retrieval metrics must cover document/article/clause Recall@K, MRR, nDCG@K, exact-reference hit, multi-hop full/partial coverage, stage survival, no-candidate rate, and retrieval/reranker technical-error rates.
- Answer metrics must cover normalized exact match; token precision/recall/F1; character F1; secondary ROUGE-L/CHRF; expected number/date/entity precision/recall; citation precision/recall/coverage; invalid citations; refusal precision/recall; and mixed claim-plus-refusal rate.
- Every metric reports numerator, denominator, coverage, skipped cases, and skip reasons. Lexical similarity does not prove legal correctness or faithfulness.
- Each run writes an immutable unique `docs/evaluation/runs/<run-id>/` directory with manifest, configuration, raw results, and report. The manifest records run ID/time, Git SHA/dirty proof, dataset revision/SHA-256, configuration fingerprint, command, provider/model IDs, and metric version.

## Authority and destructive boundaries

Do not infer authority for materially different mutations. These require explicit authorization for the exact class of action in the current task:

- delete/recreate Pinecone indexes or Qdrant collections;
- run full-corpus ingestion or rebuild/migrate persistent vectors;
- delete local content stores, checkpoints, or FTS indexes;
- overwrite user-owned reports/checkpoints;
- commit, push, merge, or open a pull request;
- change production credentials or `.env`;
- invoke paid/live providers when the task is provider-free.

Treat `--delete-existing`, `--yes`, index/collection deletion, and full ingestion as destructive. Commit/local-merge permission never implies push, provider calls, migration, deletion, or evidence promotion.

Changing E5 query/passage prefixes, dense model/dimension, Pinecone metric, sparse document representation, persistent filter metadata, or one-vector-per-document topology normally requires a migration plan and explicit reingestion authorization. Never change only one side of an ingested contract.

## Evidence, security, and privacy

- Production code uses real implementations; doubles belong only in tests.
- Never fabricate benchmark outputs, provider responses, ingestion reports, logs, or screenshots.
- Load secrets through `app/config.py`; never hardcode or log keys or raw private content when a hash/citation is sufficient.
- Preserve CSRF, CORS, authentication, and rate limits. Provider/database failures must remain typed and observable, not silently swallowed.
- Human-only legal evidence promotion remains human-only unless the current task explicitly establishes a verified automated contract.

## Repository exploration

If CRG is available, call minimal context first and use directed graph queries for architecture, impact, and tests. CRG is optional: do not block on it. Its Git-based change review can omit untracked files and a stale graph can omit new source; compare against `git status`, then inspect uncovered files with `rg` and bounded source reads. Every important CRG conclusion must be checked against source.
