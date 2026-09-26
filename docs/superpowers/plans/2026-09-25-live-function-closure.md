# VietLex Live Function Closure Implementation Plan

> **For agentic workers:** Execute inline in the current task. Check each task against production evidence; no subagent or new worktree is required.

**Goal:** Resolve reproducible defects from the 99-row production inventory, execute safe missing live cases, and keep unmet deployment/data contracts explicit.

**Architecture:** The inventory is the acceptance ledger. Each code change starts with one failing focused test and is limited to its shared root cause. Production UI checks use synthetic data and separate observed behavior from route existence. Remote corpus migrations and legal evidence publication remain separate contracts.

**Tech Stack:** Python 3.12, FastAPI/Jinja, MongoDB, Supabase/Postgres, Qdrant, Vercel, pytest, in-app browser.

## Global Constraints

- Preserve the pinned Pinecone and Vertex/Qdrant retrieval contracts in `AGENTS.md`.
- Preserve authentication, CSRF, rate limits and owner scope.
- Do not promote legal effect or evaluation quality without verified evidence.
- Do not delete indexes, run full ingestion, change `.env`, commit or push on the strength of this plan alone.
- Local Mongo DNS failure is an environment observation, not a proven application defect.

---

### Task 1: Freeze and reconcile the acceptance ledger

**Files:** Read `docs/audits/production-full-function-20260925/MATRIX.csv`; create a new dated follow-up report after verification.

**Interfaces:** Consumes the 99 inventory IDs; produces per-ID live outcome, evidence link, date, and reason for every remaining blocked or untested case.

- [x] Read current code, tests, architecture and the prior live audit. Graph tool unavailable; use directed `rg` and source checks.
- [x] Separate `FAIL` in deployed behavior from missing dataset, missing provider authorization, missing test account, and test-client limits.
- [x] Use synthetic data and read-only UI checks first; avoid repeated provider calls when a prior live case already verifies the same contract.
- [x] Recount the matrix only after a visible outcome; do not turn `NOT_TESTED` into `PASS` from unit tests or a loaded page.

### Task 2: Exercise identity and owner boundaries

**Files:** Inspect `app/api/account_routes.py`, `app/account_database.py`, `app/api/dependencies.py`, `tests/test_account_routes.py`; no source change unless a reproducible defect appears.

**Interfaces:** Registration produces an unverified `user`; email verification produces a verified `user`; login produces an owner-scoped auth session. Admin navigation must reject a normal user.

- [x] Inspect production registration form and its terms. A synthetic account was provisioned through the account helper because no controlled mailbox was available; this did not test registration or email verification.
- [x] Verify login, owner scope, admin denial, quota display, export and admin session invalidation as separate observed states. Signup, email confirmation, quota exhaustion and self-service session paths remain open.
- [x] Record the missing controlled mailbox in the report and keep the registration row unproven. Verification was not disabled in the product.

### Task 3: Fix ASCII legal headings in uploaded documents

**Files:** Modify `app/services/workspace_documents.py`; test `tests/services/test_workspace_documents.py`.

**Interfaces:** `_split_sections(text, document_id=...) -> list[WorkspaceClause]` must split Vietnamese `Điều 1` and common ASCII `Dieu 1` headings; ordinary prose must stay in its current clause.

- [x] Add one focused test with `Dieu 1. ...` and `Dieu 2. ...`, plus prose using `dieu` and `điều`, expecting two clauses without a false split.
- [x] Run `.venv\Scripts\python.exe -m pytest -q tests/services/test_workspace_documents.py -k ascii` and capture the intended RED.
- [x] Extend the existing `_HEADING` expression minimally; preserve all upload limits and content validation.
- [x] Run the focused file and review the diff and error paths.

### Task 4: Diagnose document-scoped citation and report reliability

**Files:** Read `app/services/document_scope.py`, `app/services/research_report.py`, `app/services/research_presenter.py`, related tests; modify only after a deterministic failure is reproduced.

**Interfaces:** Claims must map to retrieved source sections; selected evidence IDs must remain validated. A report validation failure must remain visible and must not produce an apparently verified draft.

- [ ] Reproduce the prior one-of-five direct citation mapping case and the report ID validation failure in a focused local test or a new synthetic live case.
- [ ] Write a failing test for a root-cause defect, implement the smallest fix, and rerun only affected tests.
- [ ] Do not relax evidence-ID validation to increase report success rate.

### Task 5: Exercise exports, admin filters and safe file paths

**Files:** Inspect `app/api/research_report_routes.py`, `app/api/routes.py`, `app/api/account_routes.py`, relevant tests; no source change unless downloaded bytes or typed errors are wrong.

**Interfaces:** Exports must match saved version, MIME and citation links; admin request filters must preserve exact scope.

- [ ] Download synthetic report Markdown/DOCX and inspect actual bytes if the browser exposes them; otherwise record the client limitation.
- [ ] Inspect account/session/admin CSV exports without echoing private content in artifacts.
- [ ] Test read-only admin views and filters; do not mutate real feedback or publish legal events.

### Task 6: Separate remote data prerequisites from code fixes

**Files:** Read `migrations/20260919_legal_body_search.sql`, `app/ingestion/body_remote.py`, `app/services/remote_body_search.py`, `docs/verification/supabase-resumed-20260922/REPORT.md`.

**Interfaces:** `SUPABASE_BODY_SEARCH_ENABLED=true` may follow only a verified remote migration, active batch and query/citation acceptance; an unavailable body index remains explicit 503.

- [x] Inspect migration and import plan, source hashes and publication rollback before remote mutation.
- [x] Determine that the current task does not name the exact Supabase migration/import class; prepare the reviewed sequence in the closure report without executing it.
- [x] Keep current-law status unknown until a human reviewer has verified and published an official-source event.

### Task 7: Stable review and reporting

**Files:** Modified source/tests plus a new dated report; do not overwrite prior audits.

**Interfaces:** The report states exact commands, Git state, remote effects, live/unit/integration separation and remaining blockers.

- [x] Review the stable diff and source-validate changes. CRG was unavailable; used `git diff`, `rg` and focused source reads.
- [x] Run `.venv\Scripts\python.exe -m pytest -q` after source was stable: 1,416 passed, 4 skipped. A later source/config change invalidates this result.
- [x] Update the acceptance matrix only with live outcomes, recalculate percentages mechanically, and list S08 as a proposed removal for user approval without deleting it.

### Task 8: Owner steering on body index and retrieval

The owner subsequently chose to rely on the full documents already in Supabase and the vectors already in Qdrant, rather than add more passages. They then explicitly asked to fix S08 end to end and only propose removing it if a fix cannot meet the acceptance bar. The proposed compact passage-index design is superseded. Do not upload, publish, or delete the 101,573 unpublished staging rows under the earlier migration authorization; deletion was not approved.

- [x] Verify current remote batch, active coverage, and Free-size risk using read-only SQL.
- [x] Source-check whether Qdrant candidates are hydrated from Supabase in the production answer path.
- [ ] Measure retrieval/citation gaps on a fixed question set before changing the retrieval contract.
- [x] Present S08 decision; owner chose to fix it.
- [x] Prototype full-document expression-index search on the existing `legal_documents.content`, with source section anchors, phrase/diacritic correctness, filtered ordering, RLS and bounded pagination. Sample source/vector sizes measured; actual production GIN size remains unmeasured.
- [x] Make the new RPC and read-only adapter pass focused SQL/API tests (10 PGlite, 40 Python); full suite after stable source: 1,419 passed, 4 skipped.
- [ ] Measure projected and actual index size before any persistent production migration; preflight Free headroom and active production schema.
- [ ] Apply only an explicitly authorized, capacity-safe production migration and verify RPC/UI live. Do not remove staging without separate approval.
