# VietLex Legal Intelligence Workspace Implementation Plan

> Initial implementation plan; execution details and deviations are recorded below and in the completion report. The checklist records planned gates, not a claim that every proposed test was executed unchanged.

**Goal:** Evolve VietLex's existing chat, evidence, legal-browser, and evaluation surfaces into an owner-scoped evidence-centric legal research workspace without changing the verified retrieval/evaluation contracts.

**Architecture:** Keep the FastAPI/Jinja/vanilla-JavaScript monolith and current anonymous/authenticated owner model. Add one `research_workspaces` MongoDB collection with bounded embedded evidence, notes, and typed analysis records; expose recorded retrieval telemetry and immutable evaluation artifacts through read-only presenters. AI analysis calls use only server-resolved selected evidence and validate JSON with Pydantic before persistence.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, Motor/MongoDB, Pydantic v2, vanilla CSS/JavaScript, pytest.

## Global Constraints

- Do not change Vertex embeddings, Qdrant v3 retrieval, the RRF/DBSF blend, evidence ranking, context budgets, answer prompt, semantic-cache identity, golden labels, or deterministic metric contracts.
- Reuse authenticated `user_id` ownership and signed anonymous `client_id`; never accept an owner identity from the browser.
- All mutations require existing CSRF validation and bounded inputs; all object and evidence identifiers are server-validated.
- Default tests are provider-free. Structured analysis provider calls occur only after an explicit user action and are replaced by test doubles in route tests.
- Evaluation Lab reads current immutable artifacts; it never launches a benchmark, edits an artifact, or promotes evidence.
- Existing untracked evaluation runs are user-owned and remain untouched.

---

## Current-state feature map

| Capability | Current implementation | Reuse decision |
| :--- | :--- | :--- |
| Chat and progress | `/chat`, SSE/polling progress, retry/copy/feedback in `app/api/routes.py` and `app/static/js/vietlex.js` | Preserve and add workspace/evidence actions at presentation seams only. |
| Identity and ownership | Signed anonymous client cookie plus opaque authenticated sessions; session and interaction queries select `user_id` or `client_id` | Apply the same owner query to workspaces and every nested evidence/analysis mutation. |
| Evidence | `EvidenceView` parses citation, document ID, title, safe URL, and excerpt without changing grounding context | Persist the original context plus these derived display fields; pin only from an owned trace. |
| Legal corpus browser | `/search` and `/documents/{document_id}` use Supabase online or local SQLite/Zstandard | Upgrade the existing document template with a research sidecar; do not create another viewer. |
| Runtime diagnostics | Interaction logs persist status, latency, provider/model, provider usage, context count, cache, guardrail and technical-error state | Add a bounded sanitized retrieval trace containing only runtime-recorded values and candidate counts. |
| Evaluation | Deterministic per-answer evaluation and immutable Golden-50 answer/retrieval artifacts already exist | Add a public-safe artifact reader and Evaluation Lab; do not duplicate scores in templates. |
| Structured analysis | Direct provider boundary exists, but no validated compare/obligation output contract | Add Pydantic schemas and fail-closed parsers around explicit selected-evidence calls. |

## Data contracts

`research_workspaces` stores `_id`, `workspace_id`, `title`, `description`, `client_id`, optional `user_id`, `created_at`, `updated_at`, `expires_at`, `evidence`, and `analyses`. Evidence records store `evidence_id`, `trace_id`, source `session_id`, `evidence_index`, `introduced_by_claim` (a bounded source-answer excerpt), `original`, parsed citation metadata, bounded note, and timestamps. Analysis records store `analysis_id`, `kind`, `status`, selected `evidence_ids`, evidence snapshots, validated `result` or a bounded typed error, provider/model observations, and timestamps.

`ClaimSupportView` exposes citation-anchor signals: `directly_supported` for matching article/clause anchors, `partially_supported` for document-only links, and `unresolved` for missing/ambiguous links. Merely having retrieved evidence does not imply support. It is explicitly not a legal-correctness, entailment, or confidence score.

`PublicRetrievalTrace` contains query, rewritten query when recorded, request/cache status, effective backend and collection when recorded, ranking mode when recorded, candidate counts derived from recorded stage lists, final evidence count, numeric latencies, sanitized typed errors, guardrail/provider observations, and context budget from current configuration.

Typed AI results are `SelectedEvidenceResult`, `ComparisonResult(findings: list[ComparisonFinding])` and `ObligationMatrixResult(rows: list[ObligationRow])`. References must resolve to selected workspace evidence IDs, with group-specific A/B checks. Support/modality fields are strict literals. Selection is capped at ten records within the current 720-token context budget; oversize inputs fail before a provider call.

## Task 1: Workspace persistence and ownership

**Files:**
- Create: `app/research_database.py`
- Modify: `app/database.py`
- Test: `tests/test_research_database.py`

**Interfaces:**
- Produces: `create_workspace`, `list_workspaces`, `get_workspace`, `update_workspace`, `delete_workspace`, `pin_workspace_evidence`, `unpin_workspace_evidence`, and `save_workspace_analysis`.

- [ ] Write fake-collection tests proving authenticated and anonymous owner filters, bounded listing, unique evidence IDs, update timestamps, and delete isolation.
- [ ] Run `python -m pytest tests/test_research_database.py -q` and require the missing-module RED failure.
- [ ] Implement one collection and indexes on owner/update time plus TTL; use atomic owner-filtered MongoDB operations.
- [ ] Re-run the focused test to GREEN.

## Task 2: Deterministic evidence, claim, and retrieval presenters

**Files:**
- Create: `app/services/research_presenter.py`
- Modify: `app/database.py`
- Modify: `app/api/routes.py`
- Test: `tests/services/test_research_presenter.py`
- Modify: `tests/test_api_routes.py`

**Interfaces:**
- Produces: `build_claim_support(answer, contexts)`, `sanitize_retrieval_trace(latency, contexts, settings)`, and `build_public_retrieval_trace(interaction)`.
- Extends: `log_interaction(..., retrieval_trace=None)`.

- [ ] Write tests for exact-anchor support, partial/unresolved states, bounded claim count, dataclass stage-count extraction, secret/error removal, missing-trace behavior, and owner-scoped inspector access.
- [ ] Run the focused presenter/route tests and observe RED.
- [ ] Implement pure presenters and persist only their bounded JSON-safe output on completed chat requests.
- [ ] Add `GET /api/interactions/{trace_id}/retrieval`; return 404 for absent owner records and an explicit `unavailable` state for legacy records.
- [ ] Re-run the focused tests to GREEN.

## Task 3: Workspace routes and evidence pinning

**Files:**
- Create: `app/api/workspace_routes.py`
- Modify: `app/main.py`
- Create: `app/templates/research_workspaces.html`
- Create: `app/templates/research_workspace.html`
- Create: `app/static/js/research-workspace.js`
- Test: `tests/test_workspace_routes.py`

**Interfaces:**
- Produces: `GET/POST /workspaces`, `GET/POST/DELETE /workspaces/{workspace_id}`, `POST /workspaces/{workspace_id}/evidence`, and `DELETE /workspaces/{workspace_id}/evidence/{evidence_id}`.

- [ ] Write route tests for create/list/read/rename/delete, anonymous/authenticated isolation, CSRF, invalid IDs, owned-trace evidence pinning, invalid evidence indices, and unpin ownership.
- [ ] Run `python -m pytest tests/test_workspace_routes.py -q` and observe RED.
- [ ] Implement server-rendered list/detail pages and bounded mutations; resolve evidence only from `get_owned_interaction` and ignore all browser-supplied citation/excerpt fields.
- [ ] Re-run workspace tests to GREEN.

## Task 4: Selected-evidence analysis and typed legal intelligence

**Files:**
- Create: `app/services/research_analysis.py`
- Modify: `app/api/workspace_routes.py`
- Modify: `app/templates/research_workspace.html`
- Test: `tests/services/test_research_analysis.py`
- Modify: `tests/test_workspace_routes.py`

**Interfaces:**
- Produces: `ComparisonResult`, `ObligationMatrixResult`, `parse_comparison`, `parse_obligation_matrix`, and explicit selected-evidence provider functions.
- Produces routes: `POST /workspaces/{workspace_id}/analyses/selected`, `/compare`, and `/obligations`.

- [ ] Write schema tests that reject unknown evidence IDs, malformed JSON, unsupported support states, and modality coercion; test selected analysis never invokes global retrieval.
- [ ] Run focused tests and observe RED.
- [ ] Build provider prompts from only server-resolved evidence, cap evidence count/text, call the existing structured-analysis provider policy, validate raw JSON with Pydantic, and persist success/degraded records.
- [ ] Return `422 insufficient_evidence` for empty/too-small selections and `502 invalid_structured_response` for validation failure without displaying malformed output as verified.
- [ ] Re-run focused tests to GREEN.

## Task 5: Evaluation Lab from immutable artifacts

**Files:**
- Create: `app/services/evaluation_lab.py`
- Create: `app/api/evaluation_lab_routes.py`
- Create: `app/templates/evaluation_lab.html`
- Modify: `app/main.py`
- Test: `tests/services/test_evaluation_lab.py`
- Test: `tests/test_evaluation_lab_routes.py`

**Interfaces:**
- Produces: `load_evaluation_lab(answer_run_path, case_id=None)` and `GET /evaluation-lab`. Retrieval results already embedded in the canonical answer artifact are used; no unverified cross-run join is introduced.

- [ ] Write temporary-artifact tests for manifest provenance, deterministic/Ragas labels, bounded case projection, missing files, malformed JSON, incompatible run IDs, and absent metrics.
- [ ] Run focused tests and observe RED.
- [ ] Read manifests/results without mutation; project only public-safe bounded fields and preserve numerator/denominator/coverage/skip reasons where present.
- [ ] Render overview, limitations, provenance, and a query-selected 50-case explorer; expose comparisons only when compatible artifacts are available.
- [ ] Re-run focused tests to GREEN.

## Task 6: Evidence-centric chat and document-reader UX

**Files:**
- Modify: `app/templates/index.html`
- Modify: `app/templates/chat_message.html`
- Modify: `app/templates/chat_history_messages.html`
- Modify: `app/templates/legal_document.html`
- Modify: `app/static/js/vietlex.js`
- Modify: `app/static/css/vietlex.css`
- Modify: `app/static/css/vietlex-enhancements.css`
- Modify: `tests/test_public_templates.py`

**Interfaces:**
- Consumes: claim support, retrieval inspector, and workspace endpoints.
- Produces: Workspace/Corpus/Intelligence navigation, evidence pin controls, exact evidence opening, claim-support summary, retrieval inspector, dense evidence board, document research sidecar, responsive fallback, focus visibility, and reduced-motion behavior.

- [ ] Add template assertions for every visible control and honest evidence/evaluation copy; ensure navigation entries have implemented targets.
- [ ] Run template tests and observe RED.
- [ ] Implement a restrained editorial workstation using existing CSS variables and local assets; use dialogs/drawers only for state that benefits from focused inspection.
- [ ] Re-run template and route tests to GREEN.

## Task 7: Current documentation and stable verification

**Files:**
- Modify: `README.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/DOCUMENTATION_INDEX.md`
- Review: all changed source, tests, and untracked paths reported by Git.

**Interfaces:**
- Produces: current product/data/retention documentation and a review-clean provider-free diff.

- [ ] Document the embedded workspace model, owner boundary, selected-evidence enforcement, structured-analysis failure states, Evaluation Lab artifact provenance, and unchanged retrieval contract.
- [ ] Run `git diff --check` and fatal Ruff on changed Python files.
- [ ] Inspect ownership, CSRF, object-ID, output escaping, URL safety, provider-failure, and legacy-record error paths.
- [ ] Run all invalidated focused tests after review fixes.
- [ ] Run `python -m pytest -q` once on stable source; provider/live integration tests remain `NOT RUN` unless explicitly authorized.
- [ ] Report exact commands/results, changed files, Git state, remote effects, limitations/deferred browser text-selection behavior, and whether Vertex/Qdrant v3 retrieval/evaluation changed.

## Compatibility and risk register

- Existing sessions are not migrated; pinned evidence references source sessions and remains additive.
- Existing interaction records without `retrieval_trace` render an explicit unavailable inspector state.
- Workspace TTL follows `DATA_RETENTION_DAYS`; pinned evidence is research convenience, not permanent legal archiving.
- MongoDB documents are bounded to prevent unbounded embedded-array growth; evidence and analysis limits fail explicitly.
- Claim support is deterministic citation-anchor coverage, not semantic entailment or legal correctness.
- Structured provider output may fail validation; the original evidence and chat remain available and the failure is persisted as degraded state.
- Large evaluation artifacts are read-only and case projections are bounded; no page load invokes a provider.

## Execution notes (2026-09-05)

- Latest user instruction supersedes the original RED/full-suite checklist for the final product polish: batch implementation first, then affected tests only. The checklist above is historical planning, not execution evidence. No full suite is required for this delivery; exact selected runs and limits are in the delivery report.

- Completed all eight product slices with provider-free service/route/schema/template tests. Focused regressions also cover account claiming/export/deletion, anonymous access after account assignment, CSRF on direct workspace entry, strict selection boundaries, A/B provenance, malformed output, and artifact packaging.
- Deployment configuration now includes exactly the two canonical Evaluation Lab JSON artifacts; no artifact was rewritten and no deployment was performed.
- Claim mapping remains a bounded deterministic presentation view, not a separately generated claim model. General notebook editing and direct document text-selection pinning are deferred. Notes are currently attached while pinning evidence; source conversations are linked from pinned records.
- Comparison and matrix filters work on freshly returned and persisted results. Original snapshots remain available when source evidence is unpinned. Requests are disabled while an analysis is pending; process-local concurrency is two.
- The document shortcut pre-fills ordinary chat. Strict selected-only analysis is explicitly a separate workspace path.
- Final validation, review coverage, Git state, exact commands and remaining verification limits are recorded in `docs/LEGAL_WORKSPACE_DELIVERY.md`.
