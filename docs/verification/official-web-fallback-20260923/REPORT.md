# Official web discovery and bounded answer verification — 2026-09-23

## Scope and source references

The user stopped further corpus ingestion and kept Supabase Free. This change improves the existing explicit workspace path from a missing internal result to official-site discovery, source reading, relevant-excerpt answer and as-of-date display. Supabase and Qdrant retrieval contracts were not changed.

Reference implementations reviewed:

- LangGraph Corrective RAG: retrieved-context relevance check followed by a web branch: <https://github.com/langchain-ai/langgraph/blob/main/examples/rag/langgraph_crag.ipynb>.
- GPT Researcher: domain-restricted web search and optional source curation: <https://docs.gptr.dev/docs/gpt-researcher/context/filtering-by-domain> and <https://github.com/assafelovic/gpt-researcher/blob/master/gpt_researcher/skills/researcher.py>.

VietLex retains its own official-domain allowlist, bounded government portal/Gazette adapters and source reader. Search snippets are discovery metadata. A legal answer is generated from the saved original text and carries exact server-owned page excerpts; filtering never certifies legal effect or faithfulness.

## Observed failure and correction

- Online exact-number search for `68/2026/TT-BXD` returned the matching Government Portal record together with three unrelated Gazette numbers. Federated discovery now checks full document-number boundaries, official URL hosts, duplicates and related mentions before the aggregate limit.
- A natural aviation-cost question ending `Xét tại ngày 13/09/2026` caused the fallback planner to search `xét tại ngày 13/09/2026`. That returned unrelated `09/2026` documents. The corrected fallback searches the issue phrase `chi phí trực tiếp`; a live local discovery placed the matching `68/2026/TT-BXD` first. The query also works when the as-of date leads the question.
- For natural questions, a strong topical title match suppresses weak title matches. When no strong match exists, results remain available for manual review. This lexical filter can miss a relevant document whose official title uses different terms.
- The answer option sends at most 10 selected passages from one saved source version, including relevant article continuations across a page boundary and portal-reported date metadata. Selected passages are restored to original reading order before generation. The full saved-source option remains available for broader review. On the 4-page aviation PDF, selection was 10/13 passages.
- At 2026-09-13 the source metadata says issued 2026-09-10 and effective from 2027-01-01. The UI reports that it was issued but not yet effective at the requested date. Later amendment/repeal history is not established by this comparison.

Government source in the live case: <https://vanban.chinhphu.vn/?pageid=27160&docid=219442>. The reader reported 4/4 readable OCR pages and source hash `316352ed8a263d22b45e0653abc4d40dbb5a9b39ee3b1d6aaf2e847577add9e7`. OCR and interpretation still require checking against the original PDF. The final bounded local live answer was `ok`, cited metadata and pages 1, 3–4, covered both indirect and common costs, and did not claim missing article text. It is one operational example, not a legal-accuracy benchmark. The model may put IDs in a separate citations list instead of after every individual claim.

## Verification

| Gate | Command or method | Result |
| --- | --- | --- |
| Focused RED/GREEN | `.venv/Scripts/python.exe -m pytest tests/services/test_deep_research.py tests/services/test_federated_official_search.py tests/services/test_official_query_planner.py tests/services/test_retained_source_analysis.py tests/test_retained_source_routes.py -q` | 45 passed after observed failures |
| JavaScript syntax | `node --check app/static/js/research-workspace.js` | pass |
| Diff whitespace | `git diff --check` | pass |
| Full provider-free suite after final source change | `.venv/Scripts/python.exe -m pytest -q --junitxml=tmp/continuation-20260922/official-web-final-full.xml` | 1,389 passed, 4 skipped, 31 warnings, 324.88 s |
| SQL contract | `node tests/sql/body_search_contract.mjs tmp/body-search-20260919/pg tmp/body-search-20260919/real-sql-fixture.json` | PGlite passed; real local doc 333670 hit with section-27 |
| SQL batch | `node tests/sql/body_search_batch.mjs tmp/body-search-20260919/pg tmp/continuation-20260919/real-body-batch` | 10 local real documents, 97 passages, 41 header hits; unpublished hidden and offsets checked |
| Local live official discovery | `tmp/continuation-20260922/probe_natural_web.py` (failed model keyword proposal, old fallback) and bounded direct-plan rerun | Original query found unrelated numbers; corrected first query found `68/2026/TT-BXD` first |
| Local live relevant answer | `.venv/Scripts/python.exe tmp/continuation-20260922/probe_local_relevant_answer.py` | `ok`; 10/13 passages, reported temporal state, 5 server-owned cited excerpts |
| Production, first deployment `eb6ade3` | `.venv/Scripts/python.exe tmp/continuation-20260922/probe_postdeploy_web.py` | Natural query: correct source found; two result occurrences, no unrelated document numbers; `partial` because some other step queries had no results. Saved answer HTTP 200 with bounded-excerpt and as-of indicators, 5 citations, no provider error or missing-document claim. |
| Production browser, first deployment | `.venv/Scripts/python.exe tmp/continuation-20260922/probe_postdeploy_browser.py` | Reader and answer HTTP 200; inline relevant form; 5 citations; zero JS page errors; no horizontal overflow at 1440 px/390 px. |
| Production after final reading-order change, `3f8d81f` | `.venv/Scripts/python.exe tmp/continuation-20260922/probe_postdeploy_web.py` | Vercel deployment `4gbiav5vhduAoT5nWc5KJKCS1omF` Ready. Natural query found `68/2026/TT-BXD`, 2 source occurrences, no other document numbers (`partial` because other step queries had no results). Saved answer HTTP 200; 10/13 excerpts, 5 citations, as-of status; described direct, indirect and common costs, issued/effective dates; no missing-document claim or provider error. |
| Production browser after final change | `.venv/Scripts/python.exe tmp/continuation-20260922/probe_postdeploy_browser.py` | Reader and answer HTTP 200; inline relevant form; 5 citations; zero JS page errors; no horizontal overflow at 1440 px/390 px. |

## Remote ingestion state at user stop

No more corpus data was uploaded after the stop instruction. A previously running chunk had just completed: 101,573 body passages staged in unpublished batch `288c184e-9761-4d2d-9298-f9b91966070a`; zero active batches; production body search flag off. Online `legal_documents` remained 14,962. The Supabase database measured 316,705,939 bytes on Free. `20260923_legal_body_expression_index.sql` had been applied; `20260923_legal_body_active_lookup.sql` was tested locally and remains unapplied remotely. No upload process remains. The partial batch is not a production search index.
