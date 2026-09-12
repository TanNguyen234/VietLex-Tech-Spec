# CURRENT_ARCHITECTURE.md — Technical Source of Truth

> Current product capability status: [FEATURE_STATUS](../FEATURE_STATUS.md). Dated updates below describe their own change sets, not an exhaustive current feature inventory. Product reliability commit af8c9f5 was deployed and live tested on 2026-09-12; Runtime fixes a1d3986 were deployed and retested the same day; see FEATURE_STATUS for evidence and remaining limits.

## Admin and temporary originals update (2026-09-09)

Admin now has dedicated Overview, Requests, Usage, Accounts, Providers, Evaluation,
System and Audit pages, a shared responsive shell, page-specific database reads,
bounded account/audit pagination and preserved RBAC/CSRF/no-store. Request details
show a guardrail technical failure rather than safe boolean defaults.

New successful PDF/DOCX/TXT uploads retain original BSON binary with their extracted
metadata inside the same Mongo workspace. The existing atomic 12,000,000-byte
workspace budget includes originals; maximum 20 documents. Owner-scoped original
downloads force attachment/no-store/nosniff. Normal reads exclude binary; reads and
new document saves reject expired workspaces before the Mongo TTL sweep. Existing
document/workspace/account deletion removes embedded originals in the same write;
no new collection, migration, credentials, or external storage service is needed.
Prior uploads cannot regain original bytes. Existing serverless upload/body limits
still apply. This does not implement OCR or large-object storage.

See [verification](verification/admin-storage-20260909/README.md) for exact local
checks and deployment status. Provider-free tests and synthetic layout previews
are not live Mongo/provider or legal-quality acceptance.


## Approved workspace feature expansion (2026-09-08)

The owner subsequently approved deployment and implementation of the dated unfinished-feature backlog. The prior backlog remains a historical review, not the current approval state.

- Workspace tools add explicit model claim assessment with exact server-source quotes, structured reports followed by claim assessment, deterministic document redlines and explicit-date timelines. These outputs do not certify legal correctness or current legal effect.
- Legal-effect records require owner scope plus an administrator's explicit review, an exact official-source quote, applicable date, document references and whole-document/partial scope. Unknown or conflicting histories remain unknown.
- Public HTML reading is limited to vanban.chinhphu.vn and baochinhphu.vn, three URLs per request, no redirects or login bypass, bounded bodies/text and explicit failures/truncation. Only exact stored excerpts can be pinned. This is not unrestricted general-web search or PDF extraction.
- Full-document review is an explicit plan and one user-run batch per request. It respects existing context limits and reports oversized/skipped clauses. Successful batch storage atomically preserves bounded document-level progress for the latest three input fingerprints, independently of the 50-entry analysis history. Document deletion removes that progress and dependent private analyses.
- Model comparison uses two configured direct-provider aliases, identical bounded input, separate observed usage/error records and no implicit cross-provider fallback. Missing reported model identity remains unobserved/partial. Text equality is not an accuracy ranking.
- Account settings show advisory daily attempt quota and UTC reset, with owner-only projected reads and unavailable states. Admin admission counters are explicitly process-local since startup, not global WAF/Slowapi totals. Actual provider billing reconciliation remains unavailable.
- OCR/large-object storage and full-corpus expansion are not implemented by this slice. Live model benchmarks, authenticated production workflow tests and edge WAF verification still require operational evidence; no production-readiness promotion follows from these implementations.

## Reviewer demo packaging (2026-09-08)

- Vercel entrypoint and Docker default to REVIEWER_DEMO_MODE=true (explicit environment override possible). Anonymous mutations are denied before body parsing; active verified accounts use existing owner/admin-scoped functions.
- Shared Mongo demo_usage records enforce atomic personal/global minute/day attempt caps. AI/research defaults: 3/minute, 20/day/account and 100/day globally. Ordinary writes: 15/minute, 100/day/account and 1000/day globally. Auth: 5/minute and 15/day/peer IP, 200/day globally. Each category has global 60/minute cap. Protective logout/session-revocation/privacy deletion paths skip shared work quota.
- Admission fails closed on auth/quota errors; it bounds body receive time and per-instance mutation concurrency. Peer-IP Slowapi keys cannot be reset by rotating the anonymous cookie. Edge WAF is still required and has NOT been verified in the packaging session.
- Runtime dependencies are hash-locked for Python 3.12; Docker uses the same runtime set as Vercel and a non-root user. Installed-package template/static paths are absolute. Wheel alone does not include external immutable evaluation artifacts; the companion source bundle does.
- Validation and unapproved feature backlog are in docs/REVIEWER_GUIDE.md and docs/UNFINISHED_FEATURES_REVIEW_20260908.md. That packaging release itself introduced no new product workflow; the subsequently approved expansion is described above.

## Production foundation state

### Local research/admin presentation update (2026-09-05)

- `/admin/evaluations` requires the existing administrator dependency. It selects local answer/retrieval runs with a manifest and results file, confines selection to the run root, and returns `Cache-Control: no-store`. The public `/evaluation-lab` remains pinned to its existing answer run.
- Evaluation presentation includes stored quality gate, case status counts, deterministic/optional judge groups, all recorded recall cutoffs, stage recall, latency means, provenance and case evidence/error drilldown. Values are macro means over recorded finite case values; unavailable observations retain coverage and skip reasons. It does not revalidate provenance hashes or certify legal correctness.
- The dashboard projects at most 100 cases and rejects individual JSON artifacts larger than 32 MiB. Truncation is explicit, and its summaries must not be interpreted as whole-run statistics. An absent stored gate is unknown, not passed. Reading artifacts never invokes a provider or starts evaluation.
- The homepage launches existing search, evidence workspace, comparison and obligation-table workflows. Be Vietnam Pro is self-hosted under its OFL license; light is the default and dark remains selectable. Document outlines add anchors while preserving and HTML-escaping the original text.
- Workspace upload and selected-clause contract review are implemented with the limits below. Verified legal-effect relationships remain unimplemented. Official-web discovery does not make article-level legal conclusions.

| Area | Classification | Current contract |
| :--- | :--- | :--- |
| Registration, verification, login, recovery, export/deletion | IMPLEMENTED | First-party MongoDB accounts; public registration always creates `role=user`, `status=active`. |
| Account lifecycle and sessions | IMPLEMENTED | Opaque cookies, SHA-256 token hashes, TTL, last-used metadata, per-session/other-session revocation, password-reset revocation, and immediate disabled-account rejection. Missing legacy fields resolve to `user` and `active`. |
| Administrator identity and user operations | IMPLEMENTED | Normal `/admin` access requires an active authenticated account with `role=admin`. Disable/enable and session revocation are bounded, CSRF-protected, and audited. Role changes are CLI-only and cannot remove the last active administrator. |
| Admin interaction filtering | PARTIALLY IMPLEMENTED | Bounded search plus request-status, provider, and cache filters use persisted fields. Date-range and explicit fallback/guardrail filters remain future work. Detail views redact known secrets and common PII and bound displayed text/context. |
| Provider/system operations view | PARTIALLY IMPLEMENTED | Configuration presence, passive recent events, cooldowns, readiness, and retrieval topology are visible without active paid probes. Process-local provider telemetry is best effort across replicas. |
| Static HTTP Basic administrator | LEGACY | Available only when `LEGACY_ADMIN_BASIC_ENABLED=true`; off by default and deprecated. It is not stored in MongoDB. |
| Logfire | IMPLEMENTED | Configured once before FastAPI instrumentation with service/environment attributes and `if-token-present`; test mode always sets export off. Headers, prompts, and response bodies are not opted into capture. |
| Answer generation routing | PARTIALLY IMPLEMENTED | The existing direct-LLM boundary now declares answer, guardrail, evaluation, and future structured-analysis policies. Vertex remains answer/guardrail primary, configured direct APIs remain fallbacks, and provider/model/status/latency/token metadata is retained. Evaluator implementations remain separate callers under the declared evaluation policy. |
| OmniGate | SHOULD NOT BE CHANGED | Optional evaluator fallback only; it is not the production answer or guardrail primary. |
| Retrieval, rank fusion, evidence budget, semantic-cache fingerprint, Golden-50 | SHOULD NOT BE CHANGED | Unmodified by the production-foundation work. |

Administrator bootstrap is deliberately non-public:

```powershell
python scripts/manage_admin.py grant admin@example.com
python scripts/manage_admin.py revoke admin@example.com
```

The account must already exist. Grants/revocations create a bounded audit record;
demotion revokes the account's active sessions. Never expose this command through
a browser route.

## Architectural Topology

```text
USE_LEGACY_FREE_PIPELINE=false (default)
        +--> Vertex gemini-embedding-2, 1024d
        +--> Qdrant v3, dense + sparse IDF + 50/50 RRF-DBSF rank blend
        +--> up to 3 structural points / 720 context tokens

USE_LEGACY_FREE_PIPELINE=true
        +--> Qdrant E5 query inference, 384d
        +--> Pinecone v1 dense+sparse + local SQLite FTS
        +--> local full-text resolution/chunking + ColBERT/BGE rerank
        +--> up to 3 chunks / 720 context tokens
        +--> Google Cloud/Vertex blocked before client construction
```

## Legacy/free runtime stages (`USE_LEGACY_FREE_PIPELINE=true`)

1. **User Query**: Original query used for sparse and exact reference search.
2. **Query Rewrite**: Default OFF; an explicit evaluation run may opt in to a short LLM rewrite. The original query always remains sufficient for production retrieval.
3. **Hybrid Search & Document Resolution**:
   - Pinecone hybrid search (up to `RETRIEVAL_DOCUMENT_LIMIT`).
   - SQLite FTS lookup (up to `LEGAL_FTS_RESULT_LIMIT`).
   - A remote dense failure with usable FTS evidence is `partial_retrieval_error`, not a silent success: answer/retrieval scoring continues and the technical-error counter increments.
   - Merged & balanced document selection (up to `RESOLVED_DOCUMENT_LIMIT`).
4. **Local Structural Chunking & Selection**:
   - Documents resolved from local content store.
   - Structural unit chunking (220 tokens max, 24 overlap).
   - Local chunk selection per document (up to `LOCAL_CHUNKS_PER_DOCUMENT`).
5. **Reranker Candidate Bounding**:
   - Bounded total candidate chunks (up to `RERANK_INPUT_LIMIT`).
6. **Reranking**:
   - Primary: Qdrant ColBERT (`answerdotai/answerai-colbert-small-v1`).
   - Fallback: Pinecone (`bge-reranker-v2-m3`).
7. **Final Context Selection**:
   - Top reranked evidence chunks (up to `FINAL_EVIDENCE_LIMIT` within `LLM_CONTEXT_MAX_TOKENS`).
8. **Answer Generation**:
   - Vertex is deliberately disabled. Configured secondary providers are attempted in order: OpenRouter, Gemini Direct API, NVIDIA NIM, and Groq, followed by the existing secondary-model pass.
   - Current secondary model IDs remain pinned by `app/evaluation/provider_catalog.py`: OpenRouter `meta-llama/llama-3.3-70b-instruct`; Gemini API `gemini-2.0-flash` then `gemini-1.5-flash`; NVIDIA `meta/llama-3.3-70b-instruct`; Groq `llama-3.3-70b-versatile` then `llama3-8b-8192`.
   - Runtime evidence records the actual provider/model, `fallback_used`, and the Vertex `primary_error_kind`. NeMo guardrails use the same Vertex-primary adapter and legacy direct-API fallbacks. OmniGate remains evaluator infrastructure rather than an answer or guardrail primary.

## Phase G0 Google Cloud model boundary

- `app/services/vertex_ai.py` owns ADC discovery, reusable `google-genai` client creation, timeouts/retries, error mapping, generation, and embedding calls.
- `gemini-embedding-2` supports isolated probes and the separate Vertex–Qdrant migration collection at 1024 dimensions. It is never used to query the existing E5 Pinecone index or the v2 384d collection.
- `run_vertex_g0_probe.py` performs isolated live checks and writes immutable artifacts without credential material or vector writes.
- Ragas is never enqueued by `/chat`; opt-in offline audits use Vertex AI first only when `USE_LEGACY_FREE_PIPELINE=false`. Free mode removes Vertex from the judge chain.
- The input-rail prompt explicitly permits lawful legal questions about public authorities, policy, office, and jurisdiction; ambiguous inputs default to allow while clear jailbreak/off-topic/harm requests remain blocked.
- Pinecone `vietlex-legal-rag-v1`, Qdrant staging, SQLite FTS, and the content store remain available; the boolean selector now chooses v3 or the legacy/free topology explicitly.

## Vertex–Qdrant v3 primary lane

`run_vertex_qdrant_migration.py` prepares deterministic structural records from a balanced set of legal document types, bounds very long documents with evenly spaced structural coverage, embeds them with Vertex AI `gemini-embedding-2` at 1024 dimensions, and stores named dense plus sparse-IDF vectors in `vietlex-legal-rag-v3-vertex-1024`. The default invocation is provider-free and write-free. Creation and upload require explicit flags, and a SQLite acknowledgement ledger makes later batches resumable.

The v3 lane exposes typed hybrid runtime and evaluation adapters. With `USE_LEGACY_FREE_PIPELINE=false`, `production` uses v3 as its primary retrieval path; initialization/provider failures are typed and do not silently fall back to Pinecone. After expansion, raw RRF missed one required document at top 3 because sparse-only distractors outranked the correct dense hit. Production therefore uses an equal reciprocal-rank blend of the Qdrant RRF and DBSF result lists; the 2026-09-03 Golden-50 run passed every retrieval gate. Qdrant ColBERT remains rejected because the live comparison reduced verified article/clause recall. The audited remote collection has 141,798 points over exactly 14,962 unique document IDs. Chat evidence comes directly from each Qdrant point payload (`body`); it does not fetch full text from Supabase. In serverless online-only mode, Supabase `public.legal_documents` supplies title/number search and full-document pages for the same 14,962-document set through a publishable-key, read-only RLS policy. The packaged local v3 bundle is older and must not be presented as matching the expanded online set. This remains a narrow slice of the 518,255-document corpus, not whole-corpus production-readiness evidence. Set the boolean to `true` to restore Pinecone v1 and disable all Google Cloud calls.

## Evidence-centric research workspace

### Personal documents and contract review (2026-09-06)

- Uploads accept PDF, DOCX and UTF-8 TXT, with a 10 MB input cap, 250,000 extracted characters and 100 sections. PDF pages retain page numbers; scanned PDFs without text require OCR outside this workflow.
- A short-lived subprocess imposes a 256 MiB memory ceiling (Windows Job Object / POSIX resource limit) and a 15-second deadline. Failure to establish isolation fails closed. Upload buffering is limited to two concurrent requests per process, six per client IP per minute and a 30-second body deadline.
- Documents remain embedded in the owner-scoped workspace, sharing its TTL. An atomic BSON-size guard limits document, evidence and analysis growth to 12 MB; the workspace can reject additional records before its 20-document count limit. No raw upload bytes are persisted.
- Contract review uses only selected server-resolved clauses and selected legal evidence; uploaded personal-document evidence cannot become legal authority. `evidence_linked` records a reference, not semantic verification. Missing law links are `needs_verification`.
- Admin review telemetry stores status, counts, hashes and provider calls without copying private clauses, filenames or generated findings into evaluation logs. Removing a document removes its pinned evidence and document-specific review analyses.

### Official web research slice (2026-09-05)

- An owner-scoped workspace can create a deterministic five-step plan and lets the user edit every query before the explicit run action.
- The run reads the public search form at `vanban.chinhphu.vn`, preserves its Web Forms state, and submits five bounded searches under a dedicated `2/minute` client limit and a process-wide concurrency limit of two. It does not call an LLM or consume model tokens.
- Results retain only HTTPS links on the exact government-domain allowlist. Stored support text is limited to official result metadata (document number, issue date, and abstract/title); it is not represented as article-level legal analysis or verified legal-effect status.
- Each run stores per-step query, status and sources in the existing owner-scoped workspace. It attempts a request-level admin trace first and records `admin_trace_status=unavailable` in the workspace analysis if that write fails. Portal/contract failures remain explicit `provider_error`; empty steps remain `no_results` and make the overall run partial or failed.
- Portal transactions are recorded as external HTTP calls, including reported request count and latency. They are excluded from the LLM-call ledger and token denominator.
- Google Search Grounding is deliberately not used for this persisted workflow because its Search Suggestion display and Grounded Result storage terms do not match the workspace retention contract.

The public FastAPI/Jinja application now includes additive research-product
surfaces without changing retrieval or evaluation behavior:

- `/workspaces` stores owner-scoped research cases in one MongoDB
  `research_workspaces` collection. Authenticated ownership uses `user_id`;
  anonymous ownership requires the existing signed `client_id` and no assigned
  `user_id`. Evidence, per-evidence notes, and bounded analysis records are
  embedded in each workspace document. Evidence retains its source trace and
  session ID; existing chat sessions are not migrated.
- Evidence can be pinned only by resolving a context index from an interaction
  already owned by the requester. Citation, excerpt, document ID, and source URL
  are derived server-side; browser-supplied evidence content is not accepted.
- Selected-evidence analysis bypasses global retrieval and sends only the
  server-resolved selected evidence to the existing direct generation boundary.
  Missing/foreign selections fail as `insufficient_evidence`. A maximum of ten
  evidence records must fit the existing `LLM_CONTEXT_MAX_TOKENS` whitespace-token
  budget (720 by default), including their reference headers. Oversized selections
  return `422 evidence_scope_too_large`; no selected record is silently dropped.
  AI calls use a process-local semaphore of two and retain direct-provider timeouts.
- Compare and obligation-matrix operations validate provider JSON with strict
  Pydantic schemas. Invalid provider output is persisted and returned as
  `invalid_structured_response`; malformed output is never presented as a
  verified legal analysis. Selected answers also use a typed JSON schema with an
  explicit `insufficient_evidence` state. Provider failures have a distinct
  degraded/provider-error state. Saved analyses retain evidence snapshots so
  provenance survives an unpin operation.
- Interaction records may include a bounded `retrieval_trace` containing only
  recorded backend/collection/ranking labels, numeric latency, stage candidate
  counts, final evidence count, cache state, and context budget. Old records
  remain valid and render `trace_not_recorded`.
- Claim support is a deterministic citation-anchor coverage view. Its states do
  not estimate confidence, semantic entailment, legal correctness, or current
  legal effect. Exact article/clause anchors link to recorded citations; a
  document-only anchor is partial; absent or ambiguous links are unresolved.
  At most twelve sentence-like claims are projected without another model call.
- `/evaluation-lab` reads the current immutable Golden-50 answer artifact and
  exposes bounded deterministic, Ragas, case, and provenance projections. Page
  loads make no provider call and never mutate or promote evaluation evidence.
  Macro means expose their sum/count, coverage, skipped count and recorded skip
  reasons. Per-case retrieval metrics retain original numerators/denominators.
  Vercel and Docker bundle only `manifest.json` and `answer_results.json` from
  `answer-v3-golden50-expanded14962-rrf-dbsf-20260903`, using the original artifacts.

Research workspaces inherit `DATA_RETENTION_DAYS` through a MongoDB TTL index.
Expiry is fixed at workspace creation; edits do not extend it. Each workspace
holds at most 100 pinned records and the newest 50 analyses. Account sign-in
claims anonymous workspaces; export includes a public-field projection; history
and account deletion remove owned workspaces. The settings label includes this
scope. They are research convenience records, not permanent legal archives.

The document reader keeps full text and metadata with a responsive research
sidecar. Its question shortcut pre-fills normal chat; it does not claim to scope
global retrieval to that document. Strict scope is available through selected
workspace evidence. Direct structural-section pinning/text-selection menus and
temporal revision comparison are deferred; current Compare operates on evidence
groups with explicit A/B provenance.

Vertex/Qdrant v3 embeddings, dense+sparse retrieval, RRF+DBSF rank blending,
structural evidence selection, original chat generation prompts/models, context budgets, and
evaluation metric implementations are unchanged by this product layer.

## Verification & Provenance

- Configuration declarations in `app/config.py` do not prove runtime usage until verified by code execution.
- Evaluation runs from dirty working trees are marked with `git_dirty=true` and `git_diff_sha256`.
- The 2026-09-02 Vercel deployment at
  <https://vietlex-legal-rag.vercel.app> loaded the SSR root, reported ready,
  returned Supabase-backed search results, and rendered a full legal document.
  Direct `/healthz` navigation was blocked by the browser client during this
  smoke and is not claimed as observed evidence.
- The 2026-09-03 bound Golden-50 RRF+DBSF retrieval gate passed, while
  deterministic answer exact match/token F1 remained `0.0000 / 0.2305`;
  deployment success therefore does
  not authorize a production-readiness claim.
- Current immutable evidence lives under
  `docs/evaluation/runs/*-golden50-expanded14962-rrf-dbsf-20260903/`. Both
  manifests honestly record the tested dirty source state and its diff hash.
- Production-foundation work does not alter Vertex embeddings, Qdrant v3
  retrieval, the RRF/DBSF blend, structural evidence selection, or evaluation
  metric contracts. Historical retrieval evidence therefore remains descriptive
  of the same retrieval configuration. Provider cooldown enforcement is stricter;
  historical answer runs do not validate requests that would now skip a cooled
  fallback provider.

## Opt-in structural v2 parallel path

When `STRUCTURAL_BACKEND_ENABLED=true`, the explicitly gated Qdrant structural pilot and `get_legal_retriever()` (Pinecone v1 + local FTS) execute concurrently. Neither lane can prevent the other from searching. Fusion removes only exact normalized chunk duplicates using document identity plus normalized content SHA-256; distinct windows within the same Điều/Khoản remain candidates. `CROSS_LANE_FINAL_RERANK_ENABLED=true` optionally passes the combined pool through one Pinecone BGE final rerank before the shared evidence/token budget; it remains off by default until the required identical-input A/B authorizes cutover. If the optional final reranker fails, the system falls back to bounded exact-deduplicated rank interleave and reports `partial_retrieval_error`. A successful final rerank that rejects every candidate keeps the standard `no_candidate` status and records reason `no_candidate_after_final_rerank` with pre/post candidate counts.

```text
Pinned local primary-legislation scope (827 documents)
        |
        v
134,334 immutable structural records (420 max tokens / 48 overlap)
        |
        +--> Qdrant Cloud Inference dense: multilingual-e5-small, 384d
        +--> Qdrant corpus-level sparse: qdrant/bm25 with IDF
        |
        v
Opt-in collection vietlex-legal-rag-v2-pilot-384
        |
        +--> concurrent dense / BM25 / exact-reference lanes
        +--> deterministic RRF and per-document cap
        +--> Pinecone bge-reranker-v2-m3 by default
        +--> direct structural evidence (no second local re-chunk)
        +--> bounded merge with the concurrent Pinecone-v1 + FTS lane
```

A failure in one lane with usable evidence from the other remains observable as `partial_retrieval_error`. If both lanes fail, the pipeline fails closed. Structural coverage remains 827 documents and is not represented as full-corpus coverage.

## Grounded semantic cache

Semantic cache identity binds corpus revision and a pipeline fingerprint covering retrieval/embedding/reranker/answer-model, `ANSWER_PROMPT_VERSION`, and evidence-budget configuration. Prompt or grounding-policy changes must bump this explicit version. Only grounded `ok` responses are written. Evidence contexts are serialized with a SHA-256 and restored on a cache hit; legacy or tampered entries fail open to fresh retrieval.

## Public runtime lifecycle

- `APP_ENV=production` requires a stable `WEB_SESSION_SECRET`; production startup never silently rotates anonymous identities.
- New MongoDB session and interaction records carry `expires_at` and are governed by TTL indexes using `DATA_RETENTION_DAYS` (30 days by default). Explicit session deletion removes both the session and its owned interaction logs.
- `SERVERLESS_ONLINE_ONLY=true` runs FastAPI/Jinja SSR directly as one Vercel Python Function. It excludes local SQLite corpus files, uses Vertex/Qdrant v3 payloads as chat evidence, and uses Supabase for `/search` and `/documents/{id}`; readiness requires both `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`. The pinned sparse-length value is `979.1241640033913`, copied from the audited v3 data bundle. Direct FastAPI responses use SSE. Progress state remains bounded and process-local, so multi-replica deployment still requires sticky routing or a shared event backend.
- The persistent-container topology remains available with `SERVERLESS_ONLINE_ONLY=false`; in that mode readiness and legal-browser pages still require the matching local content store and FTS index.

Each inference document is contract-versioned as `vietlex-structural-document-v2` and contains the corpus title, document number, legal type, structural path, citation, and unchanged chunk body. Its SHA-256 is persisted separately from the body/chunk hash and participates in checkpoint identity.

The pre-upload model probe is corpus-discriminative rather than relevant-only: 1,748 real verified rows, 825 deterministic real hard negatives (one per non-gold primary-law document), and 64 stratified title canaries. Default probe execution uses Qdrant Cloud Inference only; Pinecone reference inference is not constructed. Absolute pass gates are gold Document Recall@10 `1.0`, gold structural Recall@10 at least `0.95`, and canary Document Recall@10 at least `0.90`.

The final pilot benchmark requires fused Document Recall@24 `1.0`, applicable Article Recall@24 at least `0.95`, applicable Clause Recall@24 at least `0.90`, all-required coverage at least `0.95`, and zero no-candidate/retrieval/reranker error rates. It reports reranker input/output deltas on identical cases; it does not infer reranker quality when verified evidence is absent from its input.

Remote ingestion is ordered and artifact-bound: `create -> probe-model -> upload -> finalize -> verify -> benchmark`. Runtime/evaluation reads do not create indexes or mutate payload schemas. Raw structural traces use only `dense_hits`, `bm25_hits`, `exact_hits`, `fused_hits`, `reranker_input`, `reranker_output`, and `final_hits`; legacy metric-v3 names exist only in a declared offline adapter. The evaluator records the effective structural collection, limits, reranker mode, and Pinecone fallback in its configuration fingerprint.
# Administrative request observability

2026-09-08 update: structured workspace reports include bounded validation and
generation diagnostics; report and claim verification each use a finite 4,096
output-token budget. Structured Vertex calls request `application/json` while
keeping strict downstream schemas. New known structured failures populate admin
technical-error fields; no historical backfill was performed. See the
[functional verification matrix](verification/feature-live-20260908/README.md).
Semantic model assessment is available in workspace workflows; the structural
admin checks described below still do not establish legal correctness.

The authenticated `/admin` workspace projects persisted `evaluation_logs` without invoking retrieval or evaluation providers. Its filters apply to both request summaries and log rows. Administrators can inspect bounded, redacted request/answer content, stored context, retrieval stages, provider/model calls, provider-reported token counts, latency, guardrail state, feedback and stored Ragas proxy results. A bounded CSV export records an administrative audit event.

Token totals include only LLM responses that reported usage. They exclude embedding and reranker usage, provider attempts without usage, and monetary cost. Input, output, thinking and provider-reported total tokens have independent coverage denominators; thinking tokens are not added to provider totals. New chat calls and opt-in Ragas judge calls append to the per-request ledger. Missing and malformed legacy telemetry remains `N/A`, and capture overflow is explicit.

Context inspection performs structural citation-anchor and exact-quote membership checks only. Semantic claim support remains `NOT_EVALUATED`, and legal-effect status remains `UNKNOWN` unless a future authoritative contract records it. The dashboard never presents these deterministic checks or Ragas proxy scores as proof of legal correctness.

## Serverless OCR and guardrail update — 2026-09-09

On `SERVERLESS_ONLINE_ONLY=true`, opt-in chat self-checks use the versioned NeMo prompts through the current Vertex primary, one request per check, without retry/fallback or NeMo import. Container NeMo and offline off/shadow/enforce behavior remain unchanged. Complete yes/no decisions may include the exact prompt label; technical failures remain distinct from semantic blocks. The legacy free switch still prevents Vertex client creation.

Workspace uploads have explicit opt-in inline-PDF OCR (maximum 5 pages, 3,700,000 bytes, 60 seconds, 8,192 output tokens, one Vertex request). Strict JSON/page coverage rejects partial output. Machine text retains page/hash/model provenance and is visibly unverified. Original bytes and text share the existing owner-scoped Mongo record and retention. Reviewer demo OCR reserves the AI budget; ordinary text extraction makes zero generation calls. No external worker, Files API, new storage collection or migration is required.

The Groq primary is `qwen/qwen3.8-27b` after an identical-input two-case synthetic operational A/B (old alias HTTP 404, new alias 2/2 exact JSON). This is not evidence of legal-answer quality. NVIDIA original/candidate failed live and were not replaced; the old Groq secondary is also unverified/unavailable in the catalog. No retrieval model, embeddings, reranking or corpus changes.
