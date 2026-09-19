# Internal full-text implementation plan

**Goal:** searchable body passages with exact reader anchors, filters, escaped highlighting and explicit index coverage.

**Architecture:** an additive SQLite FTS5 sidecar for persistent/local mode, built from hash-checked ContentStore documents into a new file. Existing title index and all vector contracts remain untouched. Online-only production must not silently fall back to a bundled local subset. Production PostgreSQL migration is a subsequent separately verified deployment; do not advertise remote full-text before it exists.

**Authority:** user authorized remaining fixes, tests, commits/push/deploy. No deletion/rebuild of existing stores or vector collections. A new bounded local index can be tested without modifying those stores.

- [x] RED: content-only match, Vietnamese accent handling, filter before limit, exact anchor/text retention, safe snippet escaping, missing index error.
- [x] Implement shared reader section parser without changing section IDs; sidecar build to exclusive new path with atomic ready metadata, body search and coverage.
- [x] Add explicit search mode only when local index is ready, explain indexed count/time and query scope; online body mode returns a clear unavailable state.
- [x] Run focused tests, inspect stable diff, run appropriate broader gates and actual corpus/browser checks.
- [ ] Production: schema and PostgreSQL contract test prepared; remote importer/runtime integration and SQL application remain pending actual database access.

No generated snippets, no fabricated legal-effect data, no new AI models. Token verification: configured Logfire token accepted by US /v1/info on this turn; production secret propagation has not been established.
