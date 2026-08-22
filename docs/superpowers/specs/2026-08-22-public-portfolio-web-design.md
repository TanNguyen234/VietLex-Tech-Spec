# VietLex Public Portfolio Web Design

## Goal

Turn the existing FastAPI/Jinja/HTMX application into a credible public portfolio demo for recruiters and Vietnamese users while preserving the currently evaluated RAG pipeline exactly.

## Authority and freeze contract

Allowed changes are limited to the web/API/controller layer, MongoDB session and evaluation records, templates, static assets, deployment configuration, tests, and current documentation. The following are frozen: retrieval topology, embeddings, sparse retrieval, structural chunking, Pinecone/Qdrant/SQLite corpus contracts, rerankers, context budgets, generation prompts/models/fallbacks, NeMo implementation, semantic-cache behavior, golden datasets, and the offline Ragas metric contract. No corpus migration, provider call, credential change, deployment, commit, or push is part of this implementation.

The web layer may decide whether to invoke the existing NeMo checks for a request. The default public-chat choice is off; an anonymous user can opt in per session. `/chat` never invokes Ragas. Public Ragas evaluation is a separate, explicit, rate-limited action over an already persisted trace.

## Audience and product scope

The primary audience is a recruiter reviewing an intern/fresher portfolio and a Vietnamese user performing general legal lookup. The product is not a law-firm case-management system, multi-tenant SaaS, official legal database, or legal-advice service. There are no user accounts, billing, document uploads, or agent workflows.

## Architecture

The existing FastAPI application remains the origin application. A signed anonymous client cookie scopes chat sessions so public users cannot list or mutate one another's history. MongoDB continues to hold sessions, interactions, feedback, and public-evaluation state; the corpus remains on the backend persistent disk. The UI remains server-rendered Jinja plus HTMX and small local JavaScript/CSS assets.

For an online demo, the FastAPI origin runs in a container/VM service with persistent storage. Vercel is an optional public frontend/proxy deployment target and must not contain the 7.14 GB local data directory. This preserves the corpus and RAG topology while making the demo reachable from a browser.

## Backend components

### Request identity and security

- Issue a signed, HttpOnly, SameSite=Lax anonymous-client cookie from the index route.
- Scope session CRUD, history, export, feedback, code evaluation, and Ragas evaluation to that client identifier.
- Protect every `/admin` route with HTTP Basic credentials supplied only through environment settings. Missing credentials keep admin unavailable rather than public.
- Preserve CSRF validation for mutations.
- Apply endpoint-specific IP limits and an additional anonymous-client quota to chat and public Ragas actions.
- Validate message, title, search, and export inputs with explicit length limits.

### Chat orchestration

Refactor the 659-line route only at presentation/persistence seams. The call order and behavior of guardrails, cache, `run_advanced_rag`, output guardrails, logging, and cache persistence remain unchanged when NeMo is enabled. When disabled, input/output checks are skipped observably and logged as disabled; retrieval and generation remain identical.

### Session capabilities

- Existing create/list/read/rename/delete operations become owner-scoped.
- Session list supports a bounded title search.
- Export returns a UTF-8 Markdown download containing the conversation, timestamps, trace IDs, and source excerpts.
- Retry resubmits the original user question as a new trace in the same session; it never reuses or edits the prior answer.

### Evidence presentation

Parse the already formatted evidence strings into presentation-only fields: citation, document number, title, source URL, and excerpt. Parsing must retain the original context verbatim and never alter the text passed to the LLM. Source URLs are allowlisted to HTTP/HTTPS before becoming links.

### Public evaluation

Code evaluation is deterministic, provider-free, and available for every owned trace. It reports observable properties only: request status, latency, cache status, context and citation counts, parsed-citation coverage, refusal/no-evidence state, provider/model observation, and technical-error presence. It must not label an answer legally correct.

Public Ragas is off by default at deployment and off by default in the UI. When the deployment owner enables it and the user explicitly requests it, a separate endpoint evaluates a persisted answer/context once, caches the result by trace, and returns the existing proxy metrics. Missing reference data is displayed as not applicable; no score is fabricated. The endpoint has per-trace idempotency, client/IP quotas, one concurrent public judge call, and a global daily budget. Metric explanations state prerequisites and limitations.

### Operational endpoints

- `/healthz` proves the process can respond and has no provider dependency.
- `/readyz` reports configured/readable local stores and MongoDB readiness without exposing secrets or calling paid providers.
- The UI status badge reads readiness rather than claiming unconditional health.

## Frontend and UI/UX

The visual direction is a restrained legal-research workspace: deep navy/ink surfaces, warm brass accent, readable neutral body text, and limited motion. The desktop layout uses a session rail, central conversation, and collapsible evidence/evaluation drawer. Mobile uses a session sheet and full-width evidence drawer.

Required interactions:

- searchable session history; create, rename, delete, and Markdown export;
- multiline composer with send state, NeMo toggle, clear error/retry state, and persistent legal disclaimer;
- structured source cards with citation, title, document number, excerpt, source link, and copy action;
- copy answer, copy citation, retry, and visible feedback state;
- per-answer evaluation panel for code evaluation and explicitly requested Ragas;
- light/dark theme stored locally;
- keyboard-visible focus, semantic labels, ARIA live status, touch-visible actions, and `prefers-reduced-motion` support;
- accurate architecture copy that does not claim OpenAI embeddings, Qdrant-only evidence, or LiteLLM as the sole provider.

Application JavaScript and CSS are served locally from `/static`. Third-party runtime libraries must be vendored or replaced by small local equivalents; the deployed app must not depend on Tailwind CDN, Google Fonts, unpkg, or jsDelivr to render and operate.

## Admin

The protected admin workspace retains stats, logs, search, and details. It adds readiness, request-status distribution, technical-error visibility, Ragas execution/coverage, and a read-only portfolio-evidence summary from existing immutable evaluation reports. It never starts an offline benchmark or promotes evidence.

## Error handling

Public errors use stable Vietnamese messages and appropriate HTTP status codes. Technical details are logged in sanitized form and visible only in protected admin views. Missing MongoDB, local stores, Ragas credentials, or judge quota produce explicit unavailable states; they never silently become a passing result. HTMX requests receive renderable partial errors, while JSON operational endpoints receive structured status objects.

## Verification

Focused tests cover anonymous ownership, admin authentication, CSRF, rate limits, health/readiness, session search/export, deterministic evaluation, Ragas opt-in/idempotency/unavailable states, NeMo off/on routing, evidence parsing, and template accessibility copy. Existing chat-route behavior tests remain passing. After diff review is clean, run the full provider-free test suite once. Live RAG/Ragas evaluation and deployment are `NOT RUN` unless separately authorized.

## Success criteria

- No public user can access another anonymous user's sessions or traces.
- Admin is inaccessible without configured credentials.
- The default chat path makes zero NeMo and Ragas calls; opting into NeMo does not change retrieval/generation configuration.
- `/chat` makes zero Ragas calls in every mode.
- Public code evaluation is deterministic and honest about what it cannot prove.
- Public Ragas is explicit, cached, bounded, and unavailable rather than unsafe when disabled.
- All required chat, session, evidence, feedback, admin, health, responsive, accessibility, local-asset, and technical-copy improvements are present.
- The RAG freeze is demonstrated by an unchanged diff for frozen source/config fields and passing existing pipeline tests.
