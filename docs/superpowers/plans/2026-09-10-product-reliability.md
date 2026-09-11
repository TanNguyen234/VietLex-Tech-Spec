# Product reliability implementation plan

**Goal:** Connect discovery, evidence, review and deliverables without overstating legal authority.
**Architecture:** Extend the existing owner-scoped workflows and deterministic services. Preserve corpus contracts and existing uncommitted redesign.
**Tech stack:** FastAPI, Jinja, MongoDB, SQLite/Supabase, pytest.

## Constraints and review decisions

- Runtime and documentation work; provider-free verification. No commit, push, migration, ingestion, credential edits or evidence promotion.
- A schema is not verified legal data. Existing `legal_effect.py` already records human-reviewed dated events; extend it rather than create a second authority store.
- Full corpus body search needs an indexed backend contract and operational acceptance; do not advertise title search or a bounded candidate scan as full-text search.
- Multiple search adapters do not prove deeper research. Preserve explicit provider coverage, technical failures and source provenance.
- Keep existing modified files; Git initially contains redesign and observability changes.
- CRG tools unavailable; source and bounded searches are authority.

## Execution order

1. Legal effect: tests first for whole-document effectiveness followed by partial repeal/amendment and duplicate source identifiers. Extend deterministic status handling; preserve unknown and historical dates. Review service, route consumers and focused tests.
2. Scope: trace chat/cache/history/retrieval before implementing document and selected-source restrictions. Empty evidence must never expand scope.
3. Search/reader: trace both local and online contracts; add supported filters, precise capability labels and direct provision actions without unapproved index migration.
4. Workspace: integrate existing redesign with task-based navigation, contextual actions and developer/admin separation.
5. Review/report: extend persisted owner-scoped findings and versioned deliverables, preserving source snapshots and atomic storage budgets.
6. Admin/feedback: reuse audit and account authorization; expose factual inventory and triage, never fabricate healthy counts or run reindex automatically.
7. Official discovery: separate discovery-domain coverage from fetch allowlists; bounded connectors need captured parser fixtures and explicit partial/error states.
8. Documentation: consolidate current capability status; mark historical reviews as dated snapshots. Record exact verification commands, pre-existing dirty state and NOT RUN live checks.

Each runtime step uses focused RED → minimal change → focused GREEN → stable diff review. Run broader provider-free tests after the final stable source state. No production-readiness claim follows from unit tests.
