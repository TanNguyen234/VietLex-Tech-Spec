# Filtered official web discovery implementation plan

**Goal:** Answer natural-language legal questions from relevant sections of official web documents when the limited internal corpus lacks evidence, without adding corpus data.

**Architecture:** Preserve Supabase search and Qdrant retrieval contracts. Their existing workspace links carry the original question to explicit official discovery, bounded source reading and retained-source answers. Repair deterministic fallback keywords when the question contains an as-of date; filter unrelated title matches only when a strong topical match exists; select bounded diverse passages from a read original and compare issuance/effective dates. Document-reference filtering remains a special case; snippets remain discovery metadata.

**Scope/authority:** Runtime discovery and tests, research documentation, bounded live verification. User stopped ingestion on 2026-09-23; no further import, publication, vector writes or plan upgrade. The interrupted import completed 101,573 staged passages; its batch remains unpublished and body search disabled.

## Research basis

- LangGraph CRAG checks retrieved-document relevance and branches to rewritten web search: https://github.com/langchain-ai/langgraph/blob/main/examples/rag/langgraph_crag.ipynb . Its example concatenates web results; VietLex must retain individually attributable originals instead.
- GPT Researcher supports domain restrictions and combines local/web context, with optional source curation: https://docs.gptr.dev/docs/gpt-researcher/context/filtering-by-domain and https://github.com/assafelovic/gpt-researcher/blob/master/gpt_researcher/skills/researcher.py . Reuse the pattern, not an additional framework.
- Inspected 2026-09-23. These are reference implementations, not legal-accuracy evidence.

## Frozen implementation contract

- Files: `app/services/federated_official_search.py`, `app/services/deep_research.py`, `app/services/retained_source_analysis.py`, `app/api/retained_source_routes.py`, `app/static/js/research-workspace.js`, the two saved-source templates and focused tests.
- Failure observed live: exact 68/2026/TT-BXD returned one matching portal record plus three unrelated Gazette records. The natural-language aviation question with "Xét tại ngày 13/09/2026" generated fallback keyword "xét tại ngày 13/09/2026", returning unrelated 09/2026 documents.
- Extract complete references with token boundaries and normalized case/spacing. If query has references, keep only records whose number/title/snippet contains at least one requested complete reference. Keep related amendments mentioning that number. Never accept suffix or substring collisions.
- Validate official origins before combining; deduplicate URL fragments; rank direct number matches ahead of contextual mentions; filter before aggregate truncation. Preserve typed partial-provider failures and actual request counts.
- Lexical title overlap is a bounded discovery filter, not a calibrated relevance or legal-correctness score.
- If a strong topical title match exists, hide low-overlap discovery results; weaker result sets remain visible for manual review. Select up to ten source passages with diverse query-term coverage; retain metadata provenance and exact page citations. The existing full-source option remains available.
- Parse the explicit as-of date and portal-reported issuance/effective dates separately; communicate temporal uncertainty and never infer later repeal from the initial effective date.
- No automatic web calls from empty search/chat, no model migration or new dependency. Existing explicit workspace action is the integration boundary.
- After an explicit source read, the screen offers an inline question action using the saved source, rather than requiring a separate hunt through the source library.

## Gates

- [x] RED: focused fixtures with wrong numbers, spoofed hosts, duplicate fragments, related amendments, date-tainted keyword fallback, noisy topical titles, passage selection and temporal status.
- [x] GREEN: bounded filters and passage selection; focused tests passed.
- [x] Review stable diff/error paths; final full provider-free suite: 1,389 passed, 4 skipped.
- [x] Local live: natural question, official discovery/read and bounded answer; production follow-up remains.
- [x] Durable report in `docs/verification/official-web-fallback-20260923/REPORT.md`.

## Deferred by evidence

General questions without document numbers need measured query coverage and source selection before adopting an LLM relevance grader. Retrieval scores from Supabase, Qdrant and web are not interchangeable confidence scores. An official domain alone does not establish relevance, completeness or legal effect. Date checks must distinguish issuance, effective date and the user's as-of date; missing evidence must remain explicit.
