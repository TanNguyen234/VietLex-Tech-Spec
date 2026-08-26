# VietLex Production Web Product Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a minimal single-instance account-enabled VietLex web product with legal browsing, privacy controls, hardened HTTP behavior, and stable provider-free verification.

**Architecture:** Keep the existing FastAPI/Jinja/MongoDB monolith. Add small account, email, and legal-browsing modules; reuse the signed anonymous identity, local FTS/content store, CSRF, rate limiter, and current templates. External providers are injected or lazy so default tests make zero network calls.

**Tech Stack:** Python 3.10+, FastAPI, Jinja2, Motor/MongoDB, SQLite FTS5, `hashlib.scrypt`, `smtplib`, existing CSS/JavaScript, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-08-25-vietlex-production-web-product-design.md`

## Global Constraints

- Preserve Pinecone v1 as the durable corpus and Qdrant as inference/staging only.
- Do not change model, dimension, vector topology, ingestion contract, or production cutover.
- Do not run live SMTP, Mongo, Pinecone, Qdrant, Vertex, Ragas, or guardrail calls in default verification.
- Do not add OAuth, MFA, Redis, queues, bookmarks, notifications, frontend frameworks, or auth/email SDKs.
- Keep anonymous chat working and retain `client_id` provenance after account history claiming.
- Never log or commit SMTP credentials or raw account tokens.
- Do not commit, push, migrate remote data, or upload vectors without separate explicit authorization.

---

### Task 1: Local SMTP configuration and stable runtime imports

**Files:**
- Modify: `.env`
- Modify: `.env.example`
- Modify: `app/config.py`
- Modify: `app/main.py`
- Modify: `app/api/routes.py`
- Modify: `Dockerfile`
- Modify: `app/evaluation/decision_package.py`
- Test: `tests/test_config.py`
- Test: `tests/test_deployment_contract.py`
- Test: `tests/test_public_web_routes.py`

**Interfaces:**
- Produces settings `ACCOUNT_EMAIL_ENABLED`, `EMAIL_USER`, `EMAIL_PASS`, `EMAIL_FROM`, `SMTP_HOST`, `SMTP_PORT`, `PUBLIC_BASE_URL`, `AUTH_COOKIE_NAME`, and `AUTH_SESSION_DAYS`.
- Produces a web runtime whose import does not eagerly load NeMo/Transformers/Torch.

- [ ] Write tests that production email mode rejects missing SMTP fields, Docker includes `guardrails_config/`, and importing `app.main` avoids the guardrail module until startup requires it.
- [ ] Run only the new config/deployment tests and observe the intended failures.
- [ ] Add the minimal settings, local ignored credential values, five Ruff import removals, lazy runtime imports, conditional guardrail warm-up, and Docker copy.
- [ ] Run the focused tests and fatal Ruff command.

### Task 2: Password, account-token, and email primitives

**Files:**
- Create: `app/services/accounts.py`
- Create: `app/services/email_delivery.py`
- Test: `tests/services/test_accounts.py`
- Test: `tests/services/test_email_delivery.py`

**Interfaces:**
- Produces `normalize_email(str) -> str`, `hash_password(str) -> str`, `verify_password(str, str) -> bool`, `new_token() -> str`, and `token_sha256(str) -> str`.
- Produces `SmtpEmailSender.send_verification(email, token)` and `send_password_reset(email, token)` with STARTTLS and no credential/token logging.

- [ ] Write focused tests for normalization, scrypt verification/rejection, malformed envelopes, token hashing, generic public URLs, and SMTP STARTTLS/login/send behavior using a fake SMTP factory.
- [ ] Run the new tests and observe failures caused by missing modules.
- [ ] Implement only the tested primitives and injected SMTP sender.
- [ ] Run the focused tests to green.

### Task 3: MongoDB account persistence and history ownership

**Files:**
- Create: `app/account_database.py`
- Modify: `app/database.py`
- Test: `tests/test_account_database.py`
- Modify: `tests/test_database_sessions.py`

**Interfaces:**
- Produces user create/lookup/verify, auth-session create/resolve/revoke, account-token issue/consume, history claim, account export, history deletion, and account deletion functions.
- Extends session/interaction functions with optional `user_id` while preserving existing `client_id` calls.

- [ ] Write fake-collection tests for unique normalized email, TTL indexes, hash-only tokens, single-use token consumption, owner queries, anonymous history claim, JSON export shape, and deletion cascade.
- [ ] Run only account/session database tests and observe failures.
- [ ] Implement four account collections and the smallest compatible ownership query: authenticated rows use `user_id`; anonymous rows continue using `client_id`.
- [ ] Run account/session database tests to green.

### Task 4: Account dependencies, routes, and templates

**Files:**
- Modify: `app/api/dependencies.py`
- Create: `app/api/account_routes.py`
- Modify: `app/main.py`
- Create: `app/templates/account_form.html`
- Create: `app/templates/settings.html`
- Modify: `app/templates/index.html`
- Test: `tests/test_account_routes.py`
- Modify: `tests/test_public_templates.py`

**Interfaces:**
- Produces routes `/register`, `/login`, `/logout`, `/verify-email`, `/forgot-password`, `/reset-password`, `/settings`, `/account/export`, `/account/history`, and `/account` deletion.
- Produces `optional_user(request)` and `require_user(request)` dependencies backed by the opaque auth cookie.

- [ ] Write route tests for generic registration/recovery responses, unverified login refusal, successful cookie login/logout, token verification/reset, CSRF on destructive operations, history claiming, export, and deletion.
- [ ] Run account route/template tests and observe failures.
- [ ] Implement minimal server-rendered forms and routes with generic error messages and secure cookies.
- [ ] Run account route/template tests to green.

### Task 5: Authenticated ownership in existing chat/session flows

**Files:**
- Modify: `app/api/routes.py`
- Modify: `app/database.py`
- Test: `tests/test_api_routes.py`
- Test: `tests/test_database_sessions.py`
- Test: `tests/test_conversation_export.py`

**Interfaces:**
- Existing chat, feedback, evaluation, list/open/rename/delete/export session flows select `user_id` when authenticated and otherwise use `client_id`.

- [ ] Add focused tests that two authenticated users cannot access each other's sessions/interactions and anonymous behavior remains unchanged.
- [ ] Run the focused ownership tests and observe failures.
- [ ] Thread the resolved user ID through the existing functions without restructuring the chat pipeline.
- [ ] Run focused ownership/export tests to green.

### Task 6: Legal search, document detail, and evidence links

**Files:**
- Create: `app/services/legal_browser.py`
- Create: `app/api/legal_routes.py`
- Create: `app/templates/legal_search.html`
- Create: `app/templates/legal_document.html`
- Modify: `app/services/evidence_presenter.py`
- Modify: `app/templates/chat_message.html`
- Modify: `app/templates/chat_history_messages.html`
- Modify: `app/templates/index.html`
- Modify: `app/static/css/vietlex-enhancements.css`
- Test: `tests/services/test_legal_browser.py`
- Test: `tests/test_legal_routes.py`
- Modify: `tests/services/test_evidence_presenter.py`

**Interfaces:**
- Produces `LegalBrowser.search(query, limit)` returning metadata-only results and `get_document(document_id)` returning one verified content-store document or `None`.
- Extends `EvidenceView` with optional `document_id` only when the context exposes an exact numeric identity.

- [ ] Write tests for blank query, document-number/title search, result cap, missing/corrupt stores, document 404, safe source links, validity warning, and escaped evidence rendering.
- [ ] Run legal browser/route/evidence tests and observe failures.
- [ ] Reuse `LegalFtsIndex.search`, `ContentStore.get_metadata_many`, and `ContentStore.get_many`; add no new index.
- [ ] Implement server-rendered search/detail pages and structured evidence links.
- [ ] Run focused tests to green.

### Task 7: Privacy pages and HTTP production hardening

**Files:**
- Create: `app/templates/privacy.html`
- Create: `app/templates/terms.html`
- Create: `app/services/http_security.py`
- Modify: `app/main.py`
- Modify: `app/config.py`
- Modify: `app/templates/index.html`
- Test: `tests/test_web_security.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_public_web_routes.py`

**Interfaces:**
- Produces response security middleware and production configuration validation.
- Produces public `/privacy` and `/terms` pages.

- [ ] Write tests for CSP, HSTS-on-HTTPS, nosniff, referrer, permissions, frame protection, strict production frontend URL, stable session secret, and public legal pages.
- [ ] Run focused security/config tests and observe failures.
- [ ] Implement one middleware and minimal static pages; preserve existing CSRF/CORS/rate-limit behavior.
- [ ] Run focused tests to green.

### Task 8: Stable diff review and provider-free verification

**Files:**
- Review all paths reported by `git status --short`.
- Modify only files implicated by confirmed findings.

**Interfaces:**
- Produces a review-clean, provider-free verified source state.

- [ ] Run `git diff --check` and fatal Ruff on `app/`.
- [ ] Run affected account, security, browsing, session, deployment, and template tests once.
- [ ] Inspect authentication, token, deletion, source-link, startup, and error paths against the spec.
- [ ] Apply only confirmed fixes with a focused RED test, then rerun only invalidated focused gates.
- [ ] Run `python -m pytest -q` once after the source/configuration is stable.
- [ ] Run Docker/config smoke checks if Docker is available; otherwise report `NOT RUN`.

### Task 9: Provider-free vector growth audit

**Files:**
- Read current checkpoints, manifests, configuration, and vector-status scripts only.
- Create no durable evaluation artifact until source/configuration is stable.

**Interfaces:**
- Produces an exact recommendation naming backend, index/collection, namespace, current count, missing count, bounded batch, quota evidence, command, and remote effects.

- [ ] Run only provider-free audit/preflight commands identified by current source and runbooks.
- [ ] Compare checkpoint counts with current architecture and Git state.
- [ ] Stop before any client construction, upload, create, delete, migration, or benchmark call.
- [ ] Request exact remote authorization if a safe bounded upload is available.

## Integration boundary

No commits are part of this plan because current authority does not grant commit, push, merge, deployment, live email, or vector writes.
