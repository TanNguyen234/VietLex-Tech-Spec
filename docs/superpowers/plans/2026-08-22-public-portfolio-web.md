# VietLex Public Portfolio Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a secure, modern, publicly demoable VietLex web application without changing the evaluated RAG pipeline.

**Architecture:** Keep FastAPI/Jinja/HTMX as the origin application, scope anonymous data with a signed client cookie, isolate optional evaluation from `/chat`, and host corpus-dependent FastAPI on persistent storage. Serve the UI through local static assets and make Vercel an optional frontend/proxy target.

**Tech Stack:** Python 3, FastAPI, Jinja2, HTMX-compatible HTML, Motor/MongoDB, SlowAPI, vanilla CSS/JavaScript, pytest.

**Spec:** `docs/superpowers/specs/2026-08-22-public-portfolio-web-design.md`

## Global Constraints

- Do not modify retrieval, embeddings, chunking, reranking, generation, provider fallback, corpus/index, semantic-cache behavior, golden data, or the offline Ragas contract.
- `/chat` must never execute or enqueue Ragas.
- Public NeMo and Ragas choices default to off.
- No provider call, migration, deployment, credential change, commit, push, or evidence promotion is authorized.
- Preserve the dirty worktree and touch only explicit web/runtime-test/documentation paths.

---

### Task 1: Security, identity, and configuration foundation

**Files:**
- Modify: `app/config.py`
- Modify: `app/main.py`
- Modify: `app/api/dependencies.py`
- Create: `app/services/web_security.py`
- Test: `tests/test_web_security.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `get_client_id(request: Request) -> str`, `issue_client_cookie(response, client_id)`, `require_admin(request)`, bounded rate-limit keys, and web-only settings.

- [ ] Write focused failing tests for signed anonymous identity, unavailable/admin Basic authentication, default-off public NeMo/Ragas, and bounded settings.
- [ ] Run `python -m pytest tests/test_web_security.py tests/test_config.py -q` and confirm the focused failures.
- [ ] Implement the minimal security/configuration helpers and middleware wiring without reading or logging secrets.
- [ ] Re-run the focused tests until green.

### Task 2: Owner-scoped sessions, search, export, and trace access

**Files:**
- Modify: `app/database.py`
- Create: `app/services/conversation_export.py`
- Test: `tests/test_database_sessions.py`
- Test: `tests/test_conversation_export.py`

**Interfaces:**
- Consumes: anonymous `client_id` from Task 1.
- Produces: owner-scoped CRUD/query functions, `get_owned_interaction(trace_id, client_id)`, and `render_conversation_markdown(session, messages) -> str`.

- [ ] Write failing unit tests proving cross-owner reads/mutations fail, search is bounded, and export is deterministic UTF-8 Markdown.
- [ ] Run `python -m pytest tests/test_database_sessions.py tests/test_conversation_export.py -q` and confirm RED.
- [ ] Add owner fields and filters while preserving existing interaction fields and admin queries.
- [ ] Implement the export renderer and make the focused tests pass.

### Task 3: Evidence and deterministic public-evaluation models

**Files:**
- Create: `app/services/evidence_presenter.py`
- Create: `app/services/public_evaluation.py`
- Test: `tests/services/test_evidence_presenter.py`
- Test: `tests/services/test_public_evaluation.py`

**Interfaces:**
- Produces: `present_context(text: str) -> EvidenceView` and `build_code_evaluation(interaction: Mapping[str, Any]) -> dict[str, Any]`.

- [ ] Write failing tests for citation/title/document-number/URL parsing, unsafe URL suppression, verbatim context preservation, metric applicability, and non-claims of legal correctness.
- [ ] Run `python -m pytest tests/services/test_evidence_presenter.py tests/services/test_public_evaluation.py -q` and confirm RED.
- [ ] Implement pure presentation/evaluation functions with no provider or database construction.
- [ ] Re-run the focused tests until green.

### Task 4: Web routes, health, readiness, rate limits, and optional evaluation

**Files:**
- Create: `app/api/chat_routes.py`
- Create: `app/api/session_routes.py`
- Create: `app/api/evaluation_routes.py`
- Create: `app/api/admin_routes.py`
- Modify: `app/api/routes.py`
- Modify: `app/main.py`
- Modify: `app/services/evaluator.py`
- Test: `tests/test_api_routes.py`
- Create: `tests/test_public_web_routes.py`

**Interfaces:**
- Consumes: Tasks 1-3 helpers.
- Produces: `/healthz`, `/readyz`, owner-scoped session/export/feedback routes, `/api/evaluation/{trace_id}`, and protected `/admin` routes.

- [ ] Add focused failing route tests for every new boundary, default zero NeMo/Ragas calls, explicit NeMo opt-in, Ragas separation/idempotency/unavailable response, and endpoint quotas.
- [ ] Run `python -m pytest tests/test_api_routes.py tests/test_public_web_routes.py -q` and confirm RED without provider calls.
- [ ] Extract route modules at controller seams, preserving the existing chat pipeline order when NeMo is enabled.
- [ ] Implement health/readiness, ownership, export, retry, feedback, code evaluation, and guarded Ragas invocation.
- [ ] Re-run the focused route tests until green.

### Task 5: Local frontend assets and modern public UI

**Files:**
- Create: `app/static/css/vietlex.css`
- Create: `app/static/js/vietlex.js`
- Create: `app/templates/components/evaluation_panel.html`
- Create: `app/templates/components/error_message.html`
- Modify: `app/templates/index.html`
- Modify: `app/templates/chat_message.html`
- Modify: `app/templates/chat_history_messages.html`
- Modify: `app/templates/sidebar_sessions.html`
- Test: `tests/test_public_templates.py`

**Interfaces:**
- Consumes: structured evidence and route response fields from Tasks 3-4.
- Produces: responsive chat workspace, local assets, copy/retry/export/search/theme/feedback/evaluation interactions, and accessible status messaging.

- [ ] Write failing template tests for zero third-party runtime CDN links, semantic labels, visible touch actions, reduced-motion support, accurate provider copy, and required controls.
- [ ] Run `python -m pytest tests/test_public_templates.py -q` and confirm RED.
- [ ] Implement the local CSS/JavaScript and update templates without adding a frontend framework or build tool.
- [ ] Re-run template and public-route tests until green.

### Task 6: Protected admin and evidence dashboard

**Files:**
- Create: `app/services/portfolio_evidence.py`
- Modify: `app/templates/admin.html`
- Modify: `app/templates/admin_stats.html`
- Modify: `app/templates/admin_logs.html`
- Modify: `app/templates/admin_details.html`
- Test: `tests/test_admin_dashboard.py`

**Interfaces:**
- Produces: read-only summary loader for immutable representative-10/balanced-50 reports and improved protected dashboard views.

- [ ] Write failing tests for auth coverage, readiness/status cards, technical errors, Ragas coverage, and honest immutable evidence labels.
- [ ] Run `python -m pytest tests/test_admin_dashboard.py -q` and confirm RED.
- [ ] Implement a fail-closed, read-only evidence loader and accessible admin templates.
- [ ] Re-run focused admin tests until green.

### Task 7: Online-demo packaging and documentation

**Files:**
- Create: `vercel.json`
- Create: `deploy/vercel-proxy/README.md`
- Modify: `Dockerfile`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `README.en.md`
- Test: `tests/test_deployment_contract.py`

**Interfaces:**
- Produces: container origin with persistent-data contract and optional Vercel proxy/frontend configuration.

- [ ] Write failing tests that exclude `data/` from Vercel packaging, require a backend origin, document persistent paths, and keep secrets environment-only.
- [ ] Run `python -m pytest tests/test_deployment_contract.py -q` and confirm RED.
- [ ] Add minimal deployment files and exact online-demo documentation without claiming a deployment occurred.
- [ ] Re-run deployment tests until green.

### Task 8: Stable diff review and verification

**Files:**
- Review: all explicitly changed files from Tasks 1-7
- Verify: `tests/`

**Interfaces:**
- Produces: review-clean diff and current provider-free verification evidence.

- [ ] Compare `git status --short` with the authority ledger and inspect the complete changed diff, including untracked files.
- [ ] Verify frozen RAG source/config values did not change; source-validate error, ownership, auth, quota, and unavailable paths.
- [ ] Run all invalidated focused test files once after review fixes.
- [ ] Run `python -m pytest -q` once on the stable source and record exact pass/fail/skip counts.
- [ ] Report changed files, exact commands, `NOT RUN` provider/deployment work, dirty Git state, and no remote effects.
