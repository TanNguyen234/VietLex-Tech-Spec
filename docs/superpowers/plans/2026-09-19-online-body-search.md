# Online full-text continuation

Goal: connect the verified PostgreSQL body-search contract to runtime and prepare a bounded, explicit importer. No vector changes, automatic legal-status promotion, destructive migration or local fallback.

- [x] Runtime: opt-in RPC adapter using the public read-only key; coverage and filters, safe highlights, typed failures, disabled by default until remote acceptance.
- [x] Ingestion: build a new batch from hash-verified source documents, preserve reader offsets, refuse overwrite, explicit document limit, publish only after SQL validation. No implicit migration or automatic full-corpus import.
- [x] Focused RED/GREEN for RPC payload/errors and import offsets/hash/bounds; actual PostgreSQL contract remains independent proof.
- [ ] Review, full suite, real-provider checks where accessible, commit/push with explicit deployment evidence.

External state: user authorized synchronizing the new Logfire key to Vercel production; update succeeded. Supabase URL had NXDOMAIN from two resolvers. No SQL/admin connection currently configured. Continue independent implementation; do not invent remote acceptance.

## 23 September rollout and capacity correction

User explicitly authorized SQL migration, online body import and completion with full permissions. Dashboard now provides SQL access. The original migration succeeded; only 2,573 evenly sampled passages were staged, with no active batch. The exact online set is 14,962 documents, all source hashes match the local full store; prepared bundle has 257,254 passages. Current database is about 162 MB after sample; the sample alone uses 12.4 MB. Dashboard confirms Free plan / 500 MB database limit.

Scope freeze: preserve phrase search, RLS, source-hash checks, reader offsets, explicit publication and response schema. Investigate compact passage storage using the already stored full text before bulk import. No plan upgrade is authorized. Files if needed: additive SQL migration, importer RPC path, focused SQL/Python tests; no vector/provider changes. RED: compact upload must validate source slices, retain phrase/anchor results, hide unpublished data and avoid duplicate body storage. Measure actual sample storage before choosing the final schema. Review failure paths and stable diff, run focused SQL/ingestion gates then full suite once, then write durable rollout evidence and enable production only after complete remote acceptance.

## 23 September user stop and actual remote state

The user stopped adding corpus data and redirected work to grounded official-web answers when internal data is limited. The upload already running completed before cancellation: 101,573 passage rows now exist in batch `288c184e-9761-4d2d-9298-f9b91966070a`, status building. No active batch exists and production body search is disabled. The online document count remains 14,962. Database size measured 316,705,939 bytes (Free plan). The `20260923_legal_body_expression_index.sql` migration was applied; `20260923_legal_body_active_lookup.sql` remains local and unapplied. No ingestion process remains. Do not resume or publish the partial batch under the current instruction.
