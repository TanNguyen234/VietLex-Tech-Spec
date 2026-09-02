# VietLex Retrieval Recovery and Production Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `vietlex-lean-superpowers` for execution. Use subagent-driven development only when the user explicitly authorizes delegation; otherwise execute sequentially in the current worktree.

**Goal:** Recover reliable legal retrieval, evaluate Pinecone v1, Qdrant v2, and Vertex/Qdrant v3 without backend ambiguity, and prepare a secure deployment path without changing the pinned production backend until evidence gates pass.

**Architecture:** Keep Pinecone `vietlex-legal-rag-v1` plus local SQLite/Zstandard as the production default. Extract the existing v3 query helper into a typed evaluation service, bind every evaluation run to an explicit backend and immutable candidate pool, then add v3 only as an opt-in shadow lane after it passes a broadened deterministic benchmark. Treat Supabase full-document storage and any production cutover as separate, explicitly authorized phases.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic Settings, Qdrant Cloud, Vertex AI `gemini-embedding-2` (1024d), Pinecone, SQLite/Zstandard/FTS5, pytest, Ruff, optional offline Ragas.

## Global Constraints

- Current code and tests override historical plans. Re-read `AGENTS.md`, `docs/PROJECT_CONTEXT.md`, `docs/AGENT_WORKFLOW.md`, `docs/CURRENT_ARCHITECTURE.md`, and `app/config.py` before execution.
- Preserve the current dirty worktree. Never stage `data/` or generated evaluation runs wholesale.
- Do not recreate collections, ingest more vectors, upload full documents, call paid/live providers, commit, push, merge, or change `.env` without explicit authorization for that action.
- Pinecone v1 remains production. Qdrant v2 remains opt-in inference/staging. Vertex/Qdrant v3 remains isolated until the shadow and cutover gates below pass.
- Default tests and evaluation make zero Ragas calls. Deterministic retrieval gates run before answer generation or Ragas.
- A source or configuration edit invalidates later evidence. Generate durable benchmark artifacts only after the source/configuration diff is stable and reviewed.
- Every dirty-tree run must record `git_dirty=true` and a Git diff SHA-256. Never promote a run whose backend, candidate pool, provider/model, or selection hashes are missing.
- Human adjudicators alone may promote legal evidence labels.
- Each task below follows RED → one root-cause change → focused GREEN. Run the broad suite once, at the end.

---

## Audit Baseline to Preserve

- Production durable vectors: Pinecone `vietlex-legal-rag-v1`, namespace `legal-documents-v1`, 518,255 document records.
- Full text: local `data/huggingface/content_store.sqlite3` with Zstandard content; FTS is verified for title/document-number lookup, not article/body search.
- Qdrant v2: `vietlex-legal-rag-v2-pilot-384`, 134,334 structural points over 827 documents, opt-in parallel runtime.
- Qdrant v3: `vietlex-legal-rag-v3-vertex-1024`, 51,801 points selected from 5,000 documents, isolated from production.
- The weak final answer run used Pinecone v1 with smaller candidate limits, not the v2 backend used by the older stronger run. In `case_017`, the gold document disappeared before reranking; changing only the reranker cannot recover it.
- The verified retrieval slice has 53 evidence labels concentrated in two documents. The v3 raw-RRF result is promising on that narrow slice, but it is not representative production evidence.
- Local broad verification before this plan: `874 passed, 2 skipped`; `ruff check .` passed. These results describe the dirty tree only and are not durable benchmark evidence.

---

### Task 1: Protect repository hygiene and benchmark provenance

**Files:**
- Modify: `.gitignore`
- Modify: `app/evaluation/run_manifest.py`
- Modify: `app/evaluation/schemas.py`
- Create: `scripts/check_repository_artifacts.py`
- Create: `tests/evaluation/test_artifact_policy.py`
- Modify: `.github/workflows/ci-cd.yml`

**Step 1: Write the failing tests**

Add tests proving that:

1. operational checkpoints/logs under `data/` are rejected from a proposed Git change set;
2. a single report payload over the configured limit and a run directory over the aggregate limit fail with exact paths and sizes;
3. a manifest can record report-file SHA-256 values and source-state provenance without embedding secrets;
4. `.env`, service-account JSON, publishable/service-role credentials, and raw authorization headers are rejected by a bounded tracked-file scan.

Use a stdlib-only interface:

```python
def audit_repository_artifacts(
    root: Path,
    *,
    files: Sequence[Path],
    max_file_bytes: int = 20_000_000,
    max_run_bytes: int = 50_000_000,
) -> list[ArtifactViolation]:
    return collect_size_and_secret_violations(
        root,
        files=files,
        max_file_bytes=max_file_bytes,
        max_run_bytes=max_run_bytes,
    )
```

Run:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/evaluation/test_artifact_policy.py -q
```

Expected: FAIL because the policy module and manifest file-hash field do not exist.

**Step 2: Implement the smallest policy**

- Ignore operational data/checkpoints explicitly; do not blanket-ignore intended source fixtures.
- Scan only Git-tracked/staged paths supplied to the script; never recursively hash the 7+ GB local corpus by default.
- Permit compact `manifest.json`, `configuration.json`, `summary.json`, and `report.md`; require large raw results to be compressed or stored outside Git with SHA-256 and byte count in the manifest.
- Add `artifact_files: list[{path, sha256, bytes, storage}]` to `EvaluationRunManifest` with backward-compatible defaults.
- Change CI lint from the `app/` subset to `ruff check .`, then run the artifact/secret guard before pytest.

**Step 3: Focused verification**

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/evaluation/test_artifact_policy.py tests/evaluation/test_provenance.py -q
.\.venv\Scripts\python.exe -m ruff check scripts/check_repository_artifacts.py app/evaluation/run_manifest.py app/evaluation/schemas.py tests/evaluation/test_artifact_policy.py
```

Expected: PASS. Do not delete or overwrite the current 50+ MB raw result files; report them for a separately authorized cleanup decision.

---

### Task 2: Extract a typed Vertex/Qdrant v3 retrieval adapter

**Files:**
- Create: `app/services/vertex_qdrant_retrieval.py`
- Modify: `app/ingestion/vertex_qdrant_migration.py`
- Modify: `app/services/clients.py`
- Create: `tests/services/test_vertex_qdrant_retrieval.py`
- Modify: `tests/ingestion/test_vertex_qdrant_migration.py`

**Step 1: Freeze the service contract**

The adapter must return the existing `RetrievalOutcome`; it must not introduce a second result schema. It owns query-time embedding, sparse query encoding, Qdrant RRF, payload validation, conversion to `EvidenceChunk`, stage trace, latency, and typed technical errors.

```python
class VertexQdrantRetriever:
    async def retrieve_detailed(
        self,
        dense_query: str,
        *,
        sparse_query: str,
        limit: int,
    ) -> RetrievalOutcome:
        return await retrieve_vertex_qdrant_evidence(
            dense_query,
            sparse_query=sparse_query,
            limit=limit,
            dependencies=self.dependencies,
        )
```

Required payload keys are `document_id`, `document_number`, `title`, `source_url`, `heading_path`, `citation`, `body`, `token_count`, `dataset_revision`, `chunk_sha256`, `embedding_provider`, `embedding_model`, `embedding_dimension`, and `migration_schema`.

**Step 2: Write focused RED tests**

Cover:

- original query feeds sparse retrieval while the optionally rewritten query feeds dense retrieval;
- query uses named `dense` and `sparse` vectors and Qdrant RRF;
- payload converts to `EvidenceChunk` without re-chunking local full documents;
- wrong model/dimension/schema or missing provenance fails closed as `retrieval_error`;
- no candidates reports `no_candidate`;
- provider and Qdrant failures remain typed and observable;
- stage trace preserves raw candidate IDs and scores without vectors.

Run:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/services/test_vertex_qdrant_retrieval.py -q
```

Expected: FAIL because the adapter does not exist.

**Step 3: Implement and keep ingestion compatibility**

- Move query responsibility out of `app/ingestion/vertex_qdrant_migration.py`.
- Keep `query_vertex_records()` as a thin deprecated wrapper only while existing migration callers/tests still import it; it must delegate to the same low-level query function.
- Reuse `FastSparseEncoder`, the existing Vertex provider factory, and Qdrant client factory. Do not add a new dependency.
- Do not wire this adapter into `retrieve_configured_legal_evidence()` yet.

**Step 4: Focused GREEN**

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/services/test_vertex_qdrant_retrieval.py tests/ingestion/test_vertex_qdrant_migration.py -q
.\.venv\Scripts\python.exe -m ruff check app/services/vertex_qdrant_retrieval.py app/ingestion/vertex_qdrant_migration.py tests/services/test_vertex_qdrant_retrieval.py
```

Expected: PASS with no live provider calls.

---

### Task 3: Make evaluation backend identity explicit and fail closed

**Files:**
- Modify: `run_retrieval_eval.py`
- Modify: `run_answer_eval.py`
- Modify: `app/evaluation/run_manifest.py`
- Modify: `app/evaluation/capacities.py`
- Create: `app/evaluation/retrieval_backends.py`
- Modify: `tests/evaluation/test_default_entrypoints.py`
- Modify: `tests/evaluation/test_runtime_contracts.py`
- Modify: `tests/evaluation/test_capacities.py`
- Create: `tests/evaluation/test_retrieval_backend_binding.py`

**Step 1: Write RED tests for the CLI and manifest**

Add a required explicit choice for live evaluation:

```text
--backend production | pinecone-v1 | qdrant-v2-parallel | vertex-qdrant-v3
```

Contract:

- `production` resolves the configured runtime and records the effective backend.
- Named experimental backends call their adapter directly; they do not mutate global settings or production routing.
- `--preflight` may inspect all backends provider-free.
- The manifest records `requested_backend`, `effective_backend`, collection/index identity, vector model/dimension, capacities, and fallback lanes.
- Execution stops before a provider call if requested/effective backend identity is inconsistent.
- `--run-id` never determines backend behavior.

Run:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/evaluation/test_retrieval_backend_binding.py tests/evaluation/test_default_entrypoints.py tests/evaluation/test_runtime_contracts.py tests/evaluation/test_capacities.py -q
```

Expected: FAIL on missing CLI/backend binding.

**Step 2: Implement one resolver**

```python
async def retrieve_for_evaluation(
    backend: RetrievalBackend,
    *,
    dense_query: str,
    sparse_query: str,
    profile: EvaluationProfile,
) -> RetrievalOutcome:
    adapter = resolve_evaluation_backend(backend)
    return await adapter.retrieve_detailed(
        dense_query,
        sparse_query=sparse_query,
        profile=profile,
    )
```

- `pinecone-v1` calls `get_legal_retriever().retrieve_detailed()`.
- `qdrant-v2-parallel` calls the existing configured parallel path with an explicit v2 contract, without silently depending on an unrelated shell environment variable.
- `vertex-qdrant-v3` calls `VertexQdrantRetriever`.
- `production` calls `retrieve_configured_legal_evidence()` and records its resolved backend.
- Build capacities from the selected backend rather than only `STRUCTURAL_BACKEND_ENABLED`.

**Step 3: Focused GREEN**

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/evaluation/test_retrieval_backend_binding.py tests/evaluation/test_default_entrypoints.py tests/evaluation/test_runtime_contracts.py tests/evaluation/test_capacities.py -q
```

Expected: PASS; default/preflight paths make zero provider calls.

---

### Task 4: Implement a valid identical-input ranking A/B

**Files:**
- Create: `app/evaluation/candidate_pool.py`
- Modify: `app/services/remote_reranker.py`
- Modify: `run_retrieval_eval.py`
- Modify: `app/evaluation/reporting.py`
- Create: `tests/evaluation/test_candidate_pool.py`
- Create: `tests/evaluation/test_identical_input_reranker.py`

**Step 1: Define the comparison unit**

For each case, persist one bounded pre-rerank v3 RRF pool containing candidate ID, document/article/clause identity, text SHA-256, score, rank, backend contract, and pool SHA-256. Never persist vectors or credentials.

```python
class CandidatePool(BaseModel):
    case_id: str
    backend_contract_sha256: str
    candidates: list[CandidateChunk]
    candidate_ids_sha256: str
    candidate_payload_sha256: str
```

Ranking modes:

```text
raw-rrf | qdrant-colbert
```

Both modes must consume the same `CandidatePool`. Do not compare against a Pinecone/v2 run with different candidates or capacities.

**Step 2: Write RED tests**

- reordered/changed candidate IDs invalidate the A/B pair;
- changed candidate text hash invalidates the pair;
- Qdrant ColBERT receives exactly the raw pool, bounded once;
- a reranker technical failure is counted and leaves the raw-RRF result available, not silently labelled reranked;
- report includes per-case wins/losses/ties and aggregate document/article/clause metrics plus latency/error rates.

Run:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/evaluation/test_candidate_pool.py tests/evaluation/test_identical_input_reranker.py -q
```

Expected: FAIL because immutable candidate pools are not implemented.

**Step 3: Implement and verify provider-free fixtures**

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/evaluation/test_candidate_pool.py tests/evaluation/test_identical_input_reranker.py tests/services/test_remote_reranker.py -q
```

Expected: PASS using fakes only.

**Step 4: Live A/B gate — explicit authorization required**

After source/config is stable, run the same verified cases through one retrieval pass and two ranking modes. Persist the raw pool before reranking. The exact command must include backend, case selection, capacities, run ID, and clean/dirty provenance; record it verbatim in the manifest.

Promotion rule: keep raw RRF if ColBERT reduces any required document/article/clause recall gate or materially increases technical-error rate. Latency alone cannot compensate for lower legal recall. This gate selects ranking only; it does not authorize production routing.

---

### Task 5: Broaden and audit the golden retrieval set before Ragas

**Files:**
- Create: `scripts/audit_gold_distribution.py`
- Modify: `app/evaluation/gold_sidecar.py`
- Modify: `app/evaluation/preflight.py`
- Create: `tests/evaluation/test_gold_distribution.py`
- Create after human review: a new versioned sidecar under `docs/evaluation/datasets/`
- Create after human review: a matching immutable audit summary under `docs/evaluation/datasets/`

**Step 1: Write provider-free RED tests**

The audit must report numerator, denominator, coverage, skipped cases, and reasons for:

- verified cases and evidence items;
- distinct document IDs/numbers;
- distinct legal types;
- document/article/clause label counts;
- answerable/unanswerable and question-type distribution;
- concentration: maximum evidence share in one document and top-N documents.

Preflight must warn or fail under an explicit representative gate when evidence is concentrated in too few documents. It must not auto-promote labels found by lexical matching.

Run:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/evaluation/test_gold_distribution.py tests/evaluation/test_gold_adjudication.py -q
```

Expected: FAIL on the missing distribution contract.

**Step 2: Implement the audit and adjudication queue**

- Generate a queue of unresolved evidence anchors and local source candidates.
- Store source hashes and citations, not credentials or unrelated private content.
- Require human review for every `verified` transition.
- Version the dataset/sidecar and bind both SHA-256 values in `current_evaluation.json` only after review.

**Step 3: Proposed representative acceptance gate**

Before a production claim, require at least 50 fully verified cases spanning at least 25 distinct legal documents and 8 legal types, with document-, article-, and clause-level examples. Record this as a proposed project gate and have a human reviewer approve or revise it before using it as policy.

Retrieval must meet the existing pinned gates at the configured K: document recall 1.00, article recall at least 0.95, clause recall at least 0.90, multi-hop all-required coverage at least 0.95, no-candidate rate 0, and technical-error rate 0. Also report tighter top-3 diagnostics; do not replace the pinned gate with top-3 only.

**Step 4: Focused GREEN**

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/evaluation/test_gold_distribution.py tests/evaluation/test_gold_adjudication.py tests/evaluation/test_preflight.py -q
```

Expected: PASS without provider calls.

---

### Task 6: Gate answer generation and Ragas behind retrieval quality

**Files:**
- Modify: `run_answer_eval.py`
- Modify: `app/evaluation/answer_runner.py`
- Modify: `app/evaluation/ragas_adapter.py`
- Modify: `app/evaluation/reporting.py`
- Create: `tests/evaluation/test_retrieval_quality_gate.py`
- Modify: `tests/evaluation/test_answer_runner.py`

**Step 1: Write RED tests**

- `run_answer_eval.py` refuses to start generation/Ragas when the bound retrieval artifact misses a required gate, has incomplete coverage, or has a different dataset/backend/candidate-pool hash.
- `judge_mode=none` is the default and makes zero judge calls.
- `judge_mode=ragas` runs only after online retrieval/generation semaphores are released.
- deterministic metrics remain complete when Ragas is unavailable or quota-limited;
- Ragas errors are reported as skipped/technical errors, never converted to zero quality scores or successful completion.

Run:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/evaluation/test_retrieval_quality_gate.py tests/evaluation/test_answer_runner.py tests/evaluation/test_ragas_adapter.py -q
```

Expected: FAIL because answer evaluation currently does not require a bound passing retrieval artifact.

**Step 2: Implement the gate**

Add:

```text
--retrieval-run <immutable run directory>
--judge none | ragas
```

Validate dataset SHA, sidecar SHA, selected-case SHA, backend contract, and candidate-pool SHA before the first generation call. Keep deterministic answer metrics primary: normalized exact match, token precision/recall/F1, character F1, ROUGE-L/CHRF, number/date/entity precision/recall, citation precision/recall/coverage, invalid citations, refusal precision/recall, and mixed claim-plus-refusal.

**Step 3: Focused GREEN**

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/evaluation/test_retrieval_quality_gate.py tests/evaluation/test_answer_runner.py tests/evaluation/test_ragas_adapter.py -q
```

Expected: PASS with zero live calls.

**Step 4: Live answer/Ragas run — explicit authorization required**

Run deterministic answer evaluation first on the passing retrieval artifact. Run one optional Ragas audit afterward, with provider/model IDs, quota failures, coverage, skipped cases, and latency persisted. Never state that Ragas proves legal correctness; it is a secondary LLM-judge audit.

---

### Task 7: Add v3 shadow mode without changing answers

**Files:**
- Modify: `app/config.py`
- Modify: `app/services/rag_pipeline.py`
- Modify: `app/services/semantic_cache.py`
- Modify: `app/services/readiness.py`
- Modify: `tests/services/test_rag_pipeline.py`
- Modify: `tests/services/test_semantic_cache.py`
- Create: `tests/services/test_vertex_qdrant_shadow.py`
- Modify: `tests/test_config.py`

**Step 1: Define the minimal configuration**

Add a separate experiment flag, default false:

```python
VERTEX_QDRANT_SHADOW_ENABLED: bool = False
```

Do not reuse `STRUCTURAL_BACKEND_ENABLED` and do not repoint `STRUCTURAL_COLLECTION_NAME`. Shadow mode runs v3 after/beside the production retrieval lane, records bounded ID/hash/latency diagnostics, and never changes evidence passed to generation.

**Step 2: Write RED tests**

- default false makes zero v3 calls;
- shadow result cannot alter production evidence/order/status/cache payload;
- shadow timeout/failure is observable but cannot fail a successful production request;
- diagnostics contain no raw query, full text, credentials, or vectors;
- semantic-cache identity includes whether shadow diagnostics are enabled only if it changes persisted diagnostics; answer cache correctness remains bound to the production retrieval contract.

Run:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/services/test_vertex_qdrant_shadow.py tests/services/test_rag_pipeline.py tests/services/test_semantic_cache.py tests/test_config.py -q
```

Expected: FAIL on missing shadow configuration.

**Step 3: Implement and verify**

Use a bounded timeout and do not hold answer generation open beyond the approved shadow latency budget. Expose provider health in a separate admin diagnostic; normal readiness must not make a paid provider call on every probe.

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/services/test_vertex_qdrant_shadow.py tests/services/test_rag_pipeline.py tests/services/test_semantic_cache.py tests/test_config.py -q
```

Expected: PASS with fakes only.

**Step 4: Cutover decision — separate authorization**

Only propose `vertex-qdrant-v3` as primary after representative deterministic retrieval, answer metrics, latency, quota, and shadow disagreement reports pass. Prefer the winning v3 ranking mode from Task 4; do not require ColBERT if raw RRF is more accurate. Keep Pinecone v1 as a typed fallback during any separately approved canary. A permanent vector-store change requires a migration plan and explicit reingestion/cutover authorization.

---

### Task 8: Secure the Supabase full-document export lane

**Files:**
- Modify: `app/config.py`
- Modify: `app/ingestion/supabase_full_doc.py`
- Modify: `run_supabase_full_doc_upload.py`
- Modify: `tests/ingestion/test_supabase_full_doc_upload.py`
- Create: `docs/runbooks/SUPABASE_FULL_DOCUMENT_EXPORT.md`

**Step 1: Replace the credential contract with RED tests**

Server-side writes require:

```text
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
```

The uploader must reject `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` for writes. Tests must prove the key is never logged, serialized into checkpoints, or included in reports.

Run:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/ingestion/test_supabase_full_doc_upload.py tests/test_config.py -q
```

Expected: FAIL because current code accepts the publishable-key settings.

**Step 2: Implement secure schema and resumable verification**

- Generate schema SQL with RLS enabled and no anonymous write policy.
- Use the service role only in the explicit backend upload process.
- Bind checkpoint identity to corpus revision, selected document-ID SHA, table/schema version, content hash algorithm, and target URL host; never bind/store the secret.
- Acknowledge a batch only after the REST/database response confirms the upsert.
- Add provider-free dry-run, bounded batches, retry classification, final row count, missing-ID detection, and deterministic content-hash sampling.
- Initially keep local SQLite as runtime source of truth. Do not switch retrieval resolution to Supabase in the upload task.

**Step 3: Focused GREEN**

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/ingestion/test_supabase_full_doc_upload.py tests/test_config.py -q
.\.venv\Scripts\python.exe -m ruff check app/ingestion/supabase_full_doc.py run_supabase_full_doc_upload.py tests/ingestion/test_supabase_full_doc_upload.py
```

Expected: PASS without network calls.

**Step 4: Live upload — explicit authorization and credential required**

Create the table/RLS through an authorized Supabase admin channel, then upload the approved 50,000-document selection. A publishable key alone is insufficient. Record attempted/uploaded/skipped/failed counts, remote row count, selected-ID SHA, sample content hashes, latency, and quota/storage usage. Never claim completion from a checkpoint count without remote verification.

---

### Task 9: Make deployment topology and health claims honest

**Files:**
- Modify: `app/services/readiness.py`
- Modify: `tests/services/test_readiness.py`
- Modify: `api/proxy.py`
- Modify: `vercel.json`
- Modify: `Dockerfile`
- Modify: `README.md`
- Modify: `README.en.md`
- Create: `docs/runbooks/DEPLOYMENT.md`

**Step 1: Write RED deployment/readiness tests**

- Vercel remains a thin proxy and fails clearly when `BACKEND_ORIGIN` is absent/invalid.
- Backend readiness reports local content store, FTS, Mongo, configured production backend identity, and whether required credentials are configured.
- Provider connectivity is a separate cached/admin diagnostic, not an unbounded live call on every health probe.
- Production startup fails closed if its required local data mount or approved remote full-text adapter is absent.
- README never implies that Vercel stores the 3+ GB SQLite corpus or runs persistent RAG workers.

Run:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/services/test_readiness.py tests/test_vercel_proxy.py tests/test_production_startup.py -q
```

Expected: FAIL on the new backend/data-source readiness assertions.

**Step 2: Implement deployment contract**

- Document Vercel → persistent FastAPI origin → Pinecone/Qdrant plus mounted SQLite, or later verified Supabase adapter.
- Keep secrets server-side at the persistent origin.
- Document required environment variables by component and explicitly mark optional/live-provider variables.
- Document data acquisition/build commands and expected file/count/hash checks so a new operator can reproduce the local setup.

**Step 3: Focused GREEN**

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/services/test_readiness.py tests/test_vercel_proxy.py tests/test_production_startup.py -q
```

Expected: PASS without deploying.

---

### Task 10: Stable-diff review, broad verification, authorized live evidence, and handoff

**Files:**
- Review all files changed by Tasks 1–9
- Create only after stable source/config: `docs/evaluation/runs/<unique-run-id>/` containing the manifest, configuration, summary, report, and declared raw-result artifacts
- Update only after verified evidence: `docs/evaluation/current_evaluation.json`, `README.md`, `README.en.md`, `docs/PROJECT_CONTEXT.md`, `docs/CURRENT_ARCHITECTURE.md`

**Step 1: Review stable source/config diff**

```powershell
git status --short
git diff --check
git diff -- . ':(exclude)docs/evaluation/runs'
rg -n "TODO|FIXME|NEXT_PUBLIC_SUPABASE|vertex-qdrant-v3|requested_backend|effective_backend" app tests scripts run_*.py docs
```

If available, run Open Code Review delegation once after the diff is stable; verify every important finding against source and `git status`. Do not treat review as test evidence.

**Step 2: Run the broad provider-free suite once**

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -B -m pytest -q
.\.venv\Scripts\python.exe scripts/check_repository_artifacts.py
git diff --check
```

Record exact outputs. If source/config changes afterward, rerun affected gates and then the broad suite again.

**Step 3: Run authorized live gates in this order**

1. v3 raw-RRF retrieval on the broadened verified set;
2. Qdrant ColBERT over the identical persisted candidate pools;
3. choose the better ranking mode by pinned retrieval gates, errors, and latency;
4. deterministic answer evaluation bound to the passing retrieval run;
5. optional Ragas audit;
6. shadow runtime canary;
7. separately authorized Supabase upload and verification.

Stop at the first failed prerequisite. Do not spend answer/judge quota when retrieval is below gate.

**Step 4: Publish an honest final matrix**

The final README table must report, for each tested backend/ranking mode:

- corpus/document/point coverage and maximum/current capacity where provider evidence is available;
- dataset/sidecar/selection/backend/candidate-pool hashes;
- document/article/clause Recall@K, MRR, nDCG, exact-reference hit, multi-hop full/partial coverage, stage survival, no-candidate rate, retrieval/reranker technical-error rates;
- deterministic answer metrics with numerator/denominator/coverage/skips;
- optional Ragas metrics with provider/model, coverage/skips/errors;
- p50/p95 latency and request/quota usage;
- Git SHA/dirty proof and exact command;
- status: failed baseline, experiment, shadow candidate, or production default.

Do not label the project production-ready unless a reproducible representative run passes and deployment data/provider health is verified.

**Step 5: Git actions require fresh explicit approval**

Before any commit, show exact changed files and verification evidence. Stage only reviewed source/tests/docs; exclude local corpus, checkpoints, credentials, and oversized raw artifacts. Commit, push, merge, migration, and provider calls remain independent approvals.

---

## Recommended Execution Order and Stop Conditions

1. Execute Tasks 1–3 provider-free.
2. Execute Task 4 with fakes; request live-call authorization for its A/B only after stable review.
3. Execute Task 5 and obtain human adjudication. Stop if the representative gate remains unmet.
4. Execute Task 6 only after retrieval passes.
5. Execute Task 7 as shadow only. Stop before primary cutover and request a separate decision.
6. Execute Task 8 only after a server-side Supabase credential and table/RLS authority are available.
7. Execute Tasks 9–10 and publish evidence only after all relevant source/config is stable.

The shortest credible path is therefore: explicit backend identity → typed v3 adapter → identical-input retrieval A/B → broadened human-verified gold → deterministic answer evaluation → optional Ragas → shadow canary. More vectors, a new database, or a stronger judge cannot repair a candidate-generation failure by themselves.
