# Online full-text continuation

Goal: connect the verified PostgreSQL body-search contract to runtime and prepare a bounded, explicit importer. No vector changes, automatic legal-status promotion, destructive migration or local fallback.

- [x] Runtime: opt-in RPC adapter using the public read-only key; coverage and filters, safe highlights, typed failures, disabled by default until remote acceptance.
- [x] Ingestion: build a new batch from hash-verified source documents, preserve reader offsets, refuse overwrite, explicit document limit, publish only after SQL validation. No implicit migration or automatic full-corpus import.
- [x] Focused RED/GREEN for RPC payload/errors and import offsets/hash/bounds; actual PostgreSQL contract remains independent proof.
- [ ] Review, full suite, real-provider checks where accessible, commit/push with explicit deployment evidence.

External state: user authorized synchronizing the new Logfire key to Vercel production; update succeeded. Supabase URL had NXDOMAIN from two resolvers. No SQL/admin connection currently configured. Continue independent implementation; do not invent remote acceptance.
