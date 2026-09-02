# Repository Documentation Refresh Implementation Record

> Completed 2026-09-01 in the current workspace. The checklist records the
> implemented scope; no commit, push, live-provider call, or remote mutation was
> part of this documentation pass.

**Goal:** Make every document that presents current VietLex behavior agree with the deployed Vertex/Qdrant v3 online-only SSR contract and the 2026-09-01 Golden-50 evidence, while preserving historical artifacts as history.

**Architecture:** Current operational truth remains code/tests, `app/config.py`, `docs/PROJECT_CONTEXT.md`, `docs/CURRENT_ARCHITECTURE.md`, and current runbooks. Root legacy specifications and dated evaluation/UX reports receive explicit historical banners rather than rewritten historical claims. A new documentation index records which files are canonical, operational, evidence-bearing, or historical.

**Tech Stack:** Markdown, FastAPI/Jinja deployment documentation, immutable JSON/Markdown evaluation artifacts, PowerShell link/reference validation.

## Global Constraints

- Do not modify immutable directories under `docs/evaluation/runs/`.
- Do not turn the 4,969-document Qdrant v3 slice into a 518,255-document coverage claim.
- Deterministic metrics remain primary; Ragas is opt-in, model-judged, and not independent legal review.
- Preserve the dirty working tree and do not commit, push, migrate, ingest, delete, or call live providers.
- Dated plans, specs, and reports retain their original observations; only add clear historical/superseded labels where needed.

---

### Task 1: Documentation authority map

**Files:**
- Create: `docs/DOCUMENTATION_INDEX.md`
- Modify: `GEMINI.md`

**Interfaces:**
- Consumes: the source precedence in `AGENTS.md` and current runtime contracts in `app/config.py`.
- Produces: a single routing page that tells readers which documents are current and which are historical.

- [x] **Step 1: Classify repository documentation**

List canonical architecture/context, current runbooks, current evaluation status, immutable evidence, and historical plans/reports. State that filenames such as `plan.md` or dated reports do not override code/tests.

- [x] **Step 2: Correct agent-tool guidance**

Make `GEMINI.md` defer to `AGENTS.md`; describe CRG as preferred when available, not guaranteed or auto-updating evidence.

- [x] **Step 3: Validate local links**

Run: a read-only PowerShell Markdown-link scan from repository root.

Expected: every new relative link resolves or is an intentional placeholder inside a historical command example.

### Task 2: Current architecture and operations

**Files:**
- Modify: `architecture/architecture.md`
- Modify: `instructions.md`
- Modify: `docs/PRODUCTION_OPERATIONS.md`
- Modify: `docs/runbooks/DEPLOYMENT.md`
- Modify: `deploy/vercel-proxy/README.md`
- Modify: `docs/evaluation/golden50-v3/README.md`

**Interfaces:**
- Consumes: `app/server.py`, `vercel.json`, `.vercelignore`, `app/services/readiness.py`, and the runtime selector in `app/config.py`.
- Produces: accurate setup, Vercel SSR, persistent-host, readiness, and Golden-50 execution instructions.

- [x] **Step 1: Replace the duplicate stale architecture page**

Turn `architecture/architecture.md` into a concise compatibility entry that links to `docs/CURRENT_ARCHITECTURE.md` and summarizes both current runtime contracts.

- [x] **Step 2: Refresh developer setup and request flow**

Update `instructions.md` for the default Vertex/Qdrant v3 path, the legacy/free Pinecone path, online-only SSR, and the destructive ingestion boundary.

- [x] **Step 3: Correct deployment and operations topology**

Document Vercel as the active direct FastAPI/Jinja SSR host, mark local search/document pages unavailable in online-only mode, and retain the persistent Docker alternative without calling it the only production topology.

- [x] **Step 4: Pin the reproducible Golden-50 commands**

Add `SERVERLESS_ONLINE_ONLY=true`, the exact denominator contract, immutable run-directory rule, and current comparison/report links without embedding secrets.

### Task 3: Current evidence and portfolio claims

**Files:**
- Modify: `README.md`
- Modify: `README.en.md`
- Modify: `docs/evaluation/CURRENT_STATUS.md`
- Modify: `docs/evaluation/PORTFOLIO_EVIDENCE.md`
- Modify: `docs/PROJECT_CONTEXT.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`

**Interfaces:**
- Consumes: the 2026-09-01 retrieval and answer manifests/reports plus final provider-free suite output.
- Produces: current headline metrics with explicit deterministic/Ragas boundaries and deployed-URL status.

- [x] **Step 1: Update headline results**

Replace the 2026-08-27 Golden-50 and 915-test headline with the 2026-09-01 result: retrieval gate passed, 917 passed/2 skipped, deterministic answer metrics remained weak, and Vercel SSR smoke passed.

- [x] **Step 2: Add current status before historical log**

Place a dated current snapshot at the top of `docs/evaluation/CURRENT_STATUS.md`; label the retained earlier P0/P1/P2 and structural-pilot narrative as historical.

- [x] **Step 3: Refresh portfolio evidence conservatively**

Update hashes, immutable paths, denominators, observed generator/judge identity, and the caveat that generator and Ragas judge both used Vertex `gemini-3.5-flash`.

- [x] **Step 4: Keep architecture boundaries aligned**

Record the latest bounded benchmark and direct Vercel deployment without changing the pinned corpus/index architecture.

### Task 4: Historical-document labeling and final verification

**Files:**
- Modify: `plan.md`
- Modify: `nemo_guardrails_features.md`
- Modify: `docs/ux_ui_evaluation_report.md`
- Modify: `docs/system_evaluation_report.md`
- Modify: `docs/smoke_evaluation_report.md`
- Modify: `docs/fix_smoke_evaluation_report.md`

**Interfaces:**
- Consumes: the documentation authority map from Task 1.
- Produces: unambiguous historical status without altering old measurements.

- [x] **Step 1: Add historical banners**

State each document's original date/purpose and link to the current source of truth. Do not rewrite dated metrics or retrospective observations.

- [x] **Step 2: Scan stale current claims**

Run: `rg -n "Cohere|text-embedding-004|Pinecone remains the production backend|Vercel is only the public proxy"` over non-historical current documents.

Expected: zero stale current claims; matches may remain only below explicit historical banners or in immutable history.

- [x] **Step 3: Run focused documentation contracts**

Run: `.\.venv\Scripts\python.exe -B -m pytest -q tests/test_deployment_contract.py tests/test_readiness.py`

Expected: all focused tests pass.

- [x] **Step 4: Review the stable documentation diff**

Run: `git -c safe.directory=D:/Download/ProfessionalLegalRAG diff --check` and inspect only the documentation paths in this plan.

Expected: no whitespace errors introduced by this refresh; unrelated pre-existing dirty files remain untouched.

- [x] **Step 5: Report boundaries**

List modified files, exact checks, Git dirty status, historical files intentionally unchanged, and remote effects `NONE`. Commit and push remain `NOT RUN`.

## Self-Review

- Spec coverage: covers current architecture, setup, deployment, evaluation, portfolio claims, and misleading legacy documents across the repository.
- Placeholder scan: angle-bracket placeholders occur only where the runbook intentionally demonstrates user-supplied IDs/domains; implementation steps contain no unresolved design decisions.
- Type consistency: no source interfaces change; all runtime names match `app/config.py` and deployed entry point `app/server.py`.
