# Find provisions in retained official sources

Proposed next runtime/UX scope after temporal metadata delivery: exact phrase search across the current workspace's retained official source readings. This addresses a concrete workflow gap seen in the ten-question run: availability of full PDFs does not select the relevant provisions. It does not replace the blocked corpus-wide full-text index or claim semantic search.

Contract: current owner/expiry checks; no provider or web calls; search only last 50 retained analyses, up to 3 sources each; latest reading per URL/PDF version/page; do not merge PDF versions. Case-insensitive phrase matching with whitespace tolerance; no invented snippets. Return original text around match with safely escaped highlight, source version/page and link to saved reader. State coverage and result cap explicitly. Search query length bounded. Empty query does not claim no results. Zero results means no match in retained readings, not absence of law.

UI: search form inside Sources library; server-rendered results usable without JS. Each result opens saved reading and may pin an exact retained quote through existing CSRF-protected endpoint. Keep full-corpus search label unchanged. No source metadata promotion.

Gates: pure RED tests for phrase/same-page dedup/version separation/empty/retention; route ownership and no-store; template escaping; actual saved public PDF search and pin through live local or production API; browser desktop/mobile check using real data. Do not claim production validation from fixture tests. Freeze implementation scope before editing.

Status: plan only; implementation NOT STARTED.
