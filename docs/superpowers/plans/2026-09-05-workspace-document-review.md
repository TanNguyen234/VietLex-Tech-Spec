# Workspace document and contract review implementation plan

## Frozen contract

- Classification: runtime/product workflow.
- Scope: upload bounded PDF, DOCX, or UTF-8 TXT files into an owner-scoped research workspace; extract text without retaining raw file bytes; expose deterministic clause/page records; review only explicitly selected clauses against explicitly selected legal evidence.
- Storage: at most 20 documents per workspace, 10 MB input each, 250,000 extracted characters, 100 clause/page records, inherited workspace TTL. Store filename, media type, SHA-256, size, extraction metadata and bounded text segments.
- Security: existing CSRF/owner checks, extension plus magic validation, DOCX archive entry/uncompressed-size caps, encrypted/oversized PDF rejection, sanitized filename, no macro execution, no external fetch, and no raw file persistence.
- Analysis: contract review uses the existing structured-analysis provider boundary and request-local telemetry. Contract text is untrusted data. Every finding must cite a selected clause; legal conclusions require selected legal evidence or remain `needs_verification`.
- Failure states: unsupported type, malformed/encrypted document, empty text, size/structure limit, invalid clause/evidence IDs, provider failure, invalid structured response, and workspace conflict remain explicit.

## Focused RED

- [x] Parser accepts bounded TXT/DOCX/PDF contracts and rejects malformed, encrypted, unsupported, oversized, or empty inputs.
- [x] Workspace persistence is owner-scoped, bounded, duplicate-safe, and can pin a server-resolved document clause as evidence.
- [x] Upload, clause-pin and review routes preserve CSRF/ownership and never trust browser-supplied clause text.
- [x] Structured contract findings validate selected clause/evidence IDs and downgrade unsupported legal claims.
- [x] Workspace UI renders document inventory, clause selection, provenance and a review table.

## Stable verification

- [x] Focused tests.
- [x] Stable-diff independent review.
- [x] Ruff, JavaScript syntax and full provider-free suite once.
- [x] Durable verification report after source/config stabilization.

Verification: `docs/verification/workspace-document-review-20260906/report.md`. Full execution required one Git-ownership environment retry; see exact results.
