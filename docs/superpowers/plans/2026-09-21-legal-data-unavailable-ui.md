# Legal data outage recovery UI plan

Goal: a real corpus outage returns an honest HTML 503 with a useful next action, not a JSON dead end or fabricated results.
Contract: keep 503/no-store and distinguish missing body index from corpus backend failure. Preserve the escaped search query in retry and an explicit /workspaces?question= link. Users choose official-source research; never auto-run providers or silently cross-fallback retrieval contracts. Reader failures must not invent a document title/source URL.
Authority: user requested fixing missing internal data and flexible complete UX, including commit/push/deploy and real tests.
Files: app/api/legal_routes.py; new legal_data_unavailable.html; tests/test_legal_routes.py and existing body-search error test; documentation.

- [x] RED: HTML 503/no-store, original query safely preserved, explicit workspace action, no registry/provider calls on backend failure; reader error readable; missing index offers metadata search.
- [x] Reuse research_workspaces initial_question and existing styles/nav; do not alter successful response or ingestion contract.
- [x] Review stable diff and focused tests; Chrome local desktop/mobile verified against a real backend outage. Production check after deploy is recorded separately from local verification.
- [x] Documentation and separate code/evidence commits; verify production outage recovery after push.
- [ ] Restore/connect original Supabase project before online FTS can be published. This requires project-owner Dashboard access; production search success remains unverified.

Reviewed scope addition: successful internal search with zero matches must also offer the explicit query-to-workspace action, while retaining HTTP 200 and the no-match explanation. This is distinct from backend failure (503); no auto-discovery or provider call. Add focused RED and a real local out-of-corpus-number check.

22/09: `68/2026/TT-BXD` exposed title-token fallback returning unrelated documents. Focused RED covered SQLite FTS, SQLite filtered search and Supabase request construction. Local corpus/Chrome now yields 0 results with the preserved workspace query; see `docs/verification/legal-search-recovery-20260922/REPORT.md`.
