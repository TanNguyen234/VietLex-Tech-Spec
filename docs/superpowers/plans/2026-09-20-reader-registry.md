# Reader/search registry integration plan

Goal: show published reviewed legal events at an explicit as-of date directly in reader/search, with clear unknown vs unavailable states.
Architecture: one bounded Mongo query per page (up to 20 numbers, 200 records); project with existing registry_view. No legal publication, status inference, reindex or provider calls. Registry timeout must preserve document/search content with a typed visible degraded state. No status filter over incomplete corpus metadata.
Authority: existing request to finish legal reliability and UX. Runtime: legal_routes, legal_registry_database, shared labels, reader/search templates. Preserve source text, ownership and citation scope.

- [x] RED: dates affect published events; unknown and registry failure differ; invalid date stops lookup; search uses one batch; batch overflow never truncates into a false conclusion.
- [x] Implement bounded batch and explicit date UI; full history remains linked to /legal-status, no private reviewer data exposed.
- [x] Review stable diff; focused and broader suite; actual local corpus+Mongo+Chrome read-only checks. Production metadata remains blocked by Supabase NXDOMAIN, do not claim those paths live verified.
- [ ] Update status/evidence, split commit/push and verify deployment reachable. Human publication remains NOT RUN.
