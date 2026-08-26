# VietLex Production Web Product Design

## Goal

Turn the existing anonymous legal-chat portfolio into a minimal single-instance production-like web product without changing the pinned retrieval architecture or claiming verified legal validity.

## Scope

### Runtime stability first

- Remove the five fatal Ruff unused imports.
- Stop public web imports from eagerly loading NeMo, Transformers, and Torch when the relevant feature is unused.
- Make guardrail warm-up conditional on its deployment setting.
- Package `guardrails_config/` in the Docker image and preserve the existing persistent `/data` corpus boundary.
- Keep startup failures typed and observable for dependencies that are actually enabled.

### Account and identity

- Add email/password registration, login, logout, email verification, forgot-password, reset-password, and account settings.
- Normalize email addresses and enforce a unique MongoDB index.
- Hash passwords with Python `hashlib.scrypt` using a per-password random salt.
- Use opaque random authentication tokens. Store only token SHA-256 values in MongoDB with TTL expiry; send the raw token only in an HttpOnly, SameSite=Lax cookie.
- Retain anonymous `client_id` ownership. On successful login, attach the current anonymous sessions and interactions to the authenticated `user_id` without deleting `client_id` provenance.
- Avoid user-enumeration responses for registration and password recovery.

### Email delivery

- Use standard-library SMTP through Gmail with `EMAIL_USER`, `EMAIL_PASS`, `EMAIL_FROM`, `SMTP_HOST`, `SMTP_PORT`, and `PUBLIC_BASE_URL` settings.
- Default `SMTP_HOST=smtp.gmail.com` and `SMTP_PORT=587`; require STARTTLS.
- Never log credentials or raw verification/reset tokens.
- Unit tests use an injected fake sender and make zero network calls.
- Production startup fails closed when account email flows are enabled but required SMTP settings are absent.

### Legal browsing

- Add `/search` using only the verified existing SQLite FTS contract: document number and title search.
- Add `/documents/{document_id}` backed by the local content store, with metadata, full text, source link, and an explicit unverified-validity warning.
- Do not claim article/body search, current legal effect, amendments, repeals, or replacement relationships.
- Render evidence as structured cards with safe clickable HTTP(S) links and a document-detail link when the document identity is available.

### Privacy and account lifecycle

- Add `/privacy`, `/terms`, and `/settings`.
- Export the authenticated user's account, sessions, and interactions as JSON.
- Delete authenticated conversation history independently from deleting the account.
- Account deletion revokes auth sessions and deletes the user, verification/reset tokens, owned chat sessions, and owned interaction logs.

### HTTP hardening

- Add Content-Security-Policy, Strict-Transport-Security on HTTPS, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, and frame protection.
- Require an explicit non-local `FRONTEND_URL`, stable `WEB_SESSION_SECRET`, and secure auth-cookie configuration in production.
- Preserve current CSRF checks, anonymous ownership, admin authentication, rate limits, and retention TTLs.

### Dependency and operations hygiene

- Keep the existing monolith and current dependencies; do not add an auth framework, frontend framework, Redis, queue, or email SDK.
- Split runtime/dev/evaluation requirements only if this can be done without changing runtime resolution behavior; otherwise retain one file and add a reproducible constraint lock.
- Add concise backup/restore and deployment smoke instructions.

## Explicitly excluded

- OAuth, MFA, organizations, subscriptions, bookmarks, notifications, native mobile apps, microservices, Kubernetes, Celery, GraphQL, full-body FTS, and automatic legal-validity inference.
- Multi-instance shared state. A single FastAPI instance remains the supported production-like topology.
- Provider calls from default tests.

## Data model

MongoDB adds four focused collections:

- `users`: `_id`, normalized email, password hash envelope, verification state, timestamps, and `schema_version`.
- `auth_sessions`: token hash, user ID, created time, and TTL expiry.
- `account_tokens`: hashed email-verification/password-reset token, purpose, user ID, and TTL expiry.
- Existing `chat_sessions` and `evaluation_logs`: optional `user_id` plus retained anonymous `client_id`.

No migration rewrites all historical documents. Existing anonymous rows remain valid and are claimed only by an authenticated owner with the matching signed client cookie.

## Error handling and security boundaries

- Invalid/expired/reused tokens return a generic failure and never reveal token state details.
- Login and recovery return generic credential/recovery messages.
- Email delivery failure leaves the account unverified and returns a retryable typed error without exposing provider details.
- Destructive account operations require a valid authenticated session plus CSRF.
- Source URLs remain limited to safe HTTP(S) URLs.

## Verification strategy

1. Establish focused RED tests for each behavior group.
2. Make the smallest root-cause implementation change and run only affected tests.
3. Review the stable diff and important security/error paths.
4. Run fatal Ruff, focused integration tests, Docker/config checks, and the full provider-free suite once after source/configuration is stable.
5. Live SMTP, Mongo, Pinecone, Qdrant, Vertex, deployment, and browser smoke checks remain `NOT RUN` until separately authorized and configured.

## Vector database follow-up

Vector growth starts only after the product diff is stable and all provider-free gates pass. First run provider-free audit/preflight to identify the exact backend, current count, missing document set, quota, checkpoint, and proposed bounded batch. Any remote upload must name the index/collection, namespace, maximum document/record count, and command before execution. No delete, recreate, full-corpus rebuild, model/dimension change, or production cutover is implied by this design.

## Success criteria

- Anonymous chat remains functional.
- A verified user can authenticate across browsers and see claimed account history.
- Verification/reset email flows are secure and testable without live calls.
- Search and document detail work against the pinned local stores without overstating coverage or validity.
- Privacy export/deletion and account deletion are owner-scoped and CSRF-protected.
- Fatal Ruff and the full provider-free suite pass; container configuration includes every startup resource.
- No secret is committed or printed, and no remote provider/index is mutated by default verification.
