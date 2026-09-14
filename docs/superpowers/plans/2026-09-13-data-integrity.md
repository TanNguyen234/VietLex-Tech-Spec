# Data integrity implementation plan

**Goal:** Reject writes after workspace expiry and distinguish official-source versions without changing raw quotes or legal status.
**Architecture:** Add expiry predicates to atomic Mongo writes; derive new official evidence IDs from URL, document/content digest and exact quote. Existing evidence remains readable; no migration or deletion.
**Authority:** User authorizes fixes, real provider/database tests, commits, push and deployment. No index deletion, full ingestion, credential change or human evidence promotion.

- [x] RED: run real Mongo integration probe against uniquely named test workspaces; active writes must succeed and expired writes must fail for rename, pin, unpin, analysis, full-review batch and document removal. Probe writes only its own UUID objects and leaves TTL cleanup; no mocks.
- [x] Add `expires_at > now` to each atomic write in app/research_database.py. Preserve owner, size, array and revision conditions. Explicit workspace deletion stays allowed for privacy cleanup.
- [x] RED pure test for version-sensitive evidence ID in tests/test_official_evidence_identity.py; same PDF and quote across page windows deduplicates, changed PDF or quote does not.
- [x] Add identity helper in app/services/trusted_source_reader.py and call it in app/api/trusted_source_routes.py. Preserve old stored IDs and metadata.
- [x] Review all changed error paths; focused gates then full suite. Run live probe again and store outputs only after stable source. Commit/push/deploy after verification.

## Remaining corpus blocker confirmed by live reads
Supabase body scans returned HTTP 500 / PostgreSQL 57014 statement timeout for two legal phrases. Existing schema has document-number and content-hash indexes only. Service-role REST access is configured; no SQL management connector is available. Do not advertise scalable full-text from a LIMIT scan; an additive indexed search schema and execution permission/connection must be established and measured separately. This plan does not mark that P0 complete.
