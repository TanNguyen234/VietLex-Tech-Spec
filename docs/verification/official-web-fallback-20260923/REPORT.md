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

## Continuation: ordinary question and long scanned source

The initial five deterministic searches for a natural import-machinery question repeated a broad phrase and missed `56/2026/TT-BKHCN` (14 official results). A direct official search for `dây chuyền công nghệ đã qua sử dụng` returned that document. Commit `0f0816f` retains this distinctive subject phrase as the final verification query, including when the UI's optional model keyword planner supplies broad alternatives. The model planner still supplies the other queries and never supplies legal evidence itself. The source-reading fix in `2962501` also keeps relevant Article 5 conditions within the bounded answer instead of treating a heading as the whole article.

On the production domain, the UI-equivalent `suggest_keywords=true` plan found `56/2026/TT-BKHCN` among 18 official results, without a document number in the question. The selected [Government Portal record](https://vanban.chinhphu.vn/?pageid=27160&docid=219429) identified a 39-page PDF. Ordinary extraction yielded only 61 characters in the first five pages, so the probe explicitly retried those pages with OCR: `vertex_ocr`, 11,635 characters. The saved-source relevant-excerpt route returned HTTP 303 then a readable answer page with excerpt-scope, time-marker and citation sections; a 240-character Article 5 quote was pinned from the exact OCR text. These checks establish operational flow only: they do not certify OCR accuracy, citation sufficiency, legal effect or answer correctness.

The same production workspace could not create a new research report: `POST /analyses/report` returned HTTP 429 `demo_daily_quota`; a later retry returned the same typed error. Current-case MD/DOCX export is therefore **NOT RUN**. Earlier report/export tests in this file remain historical evidence for that separate path. A new plan request after the new deployment also received the daily quota response, so the deployed deterministic query cannot be independently re-probed today. Vercel displayed commit `0f0816f` as **Ready**, **Latest**, **Production**, with `vietlex-legal-rag.vercel.app` assigned at deployment `3ZBrPwLY55QVVYQYwUumFgc5aJ7y`.

| Gate | Exact command / observation | Result |
| --- | --- | --- |
| RED for model keyword loss | `.venv/Scripts/python.exe -m pytest -q tests/services/test_official_query_planner.py::test_model_keywords_keep_distinctive_subject_verification` | Expected assertion failure before fix |
| Focused GREEN | `.venv/Scripts/python.exe -m pytest -q tests/services/test_official_query_planner.py tests/services/test_deep_research.py` | 22 passed |
| Report/export focused gate | `.venv/Scripts/python.exe -m pytest -q tests/test_research_report_routes.py tests/test_report_deliverables.py` | 9 passed, 2 warnings; test path only, not a live report for this case |
| Stable diff | `git diff --cached --check` | passed before commit |
| Broad provider-free suite | `.venv/Scripts/python.exe -m pytest -x -q --basetemp tmp/continuation-20260922/pytest-temp-query-final2/cases --junitxml=tmp/continuation-20260922/query-final2.xml` with TEMP/TMP on D | **NOT PASSED**: `MemoryError` while collecting `google.genai` in `tests/evaluation/test_runtime_contracts.py`; C had ~234 MB free and free physical memory ~700 MB. No reliable new full-suite result. |
| Production workflow | `.venv/Scripts/python.exe tmp/continuation-20260922/probe_imports_workflow.py` | Correct document found, OCR/read/answer/pin passed; report 429 daily quota |
| Production report retry | `.venv/Scripts/python.exe tmp/continuation-20260922/resume_imports_report.py` | 429 `demo_daily_quota`; export **NOT RUN** |

The live probe scripts and request summaries are in ignored `tmp/continuation-20260922/` and include private session state; they are intentionally not committed. The report preserves only bounded observations. No additional corpus upload, migration, vector rebuild, registry promotion or paid plan change was performed in this continuation.

## Follow-up on 2026-09-24

With the daily demo budget reset, the original report request proceeded but failed the claim verifier: HTTP 502, `invalid_structured_response`, `ClaimVerificationValidationError`, `invalid_evidence_quote`. It did **not** pass as a checked report. The server preserved a draft with that status. Read-only checks opened its editor (HTTP 200), exported Markdown (2,327 bytes), and exported a valid DOCX ZIP (2,369 bytes). Both exports retained the official source URL. A new report attempt from two longer, exact Article 5 excerpts was also rejected with `invalid_evidence_reference`. These typed failures protect against fabricated quotes/IDs; they mean model-verified report generation for this case remains unproven. The drafts can be edited and exported with the unverified status.

The first saved-source answer called pages 6–39 “bị khuyết” even though those pages simply had not been read. Commit `30800d5` removes the `missing_pages` list from the model input while retaining `readable_pages` and the PDF page count, and tells the model to describe any relevant unreviewed pages as **chưa đọc**. The UI continues to display precise coverage and states that unread pages do not prove an incomplete PDF. A focused RED test reproduced the misleading input before the change; after it, 24 retained-source service/route tests passed. The stable full provider-free suite then completed: **1,395 passed, 4 skipped, 31 warnings in 495.27 s**.

Vercel deployment `8ytLs4NXuFrL7QdgTnimgzunZBia` showed commit `30800d5` **Ready / Latest / Production** on `vietlex-legal-rag.vercel.app`. Reanalysis of the **same saved OCR source**, with the same natural question and `scope=relevant`, returned an answer page with status `ok`, 10/18 selected passages and five server-owned citation blocks. The answer no longer called unread pages missing; the page still explains that only 5/39 pages have text in the saved read. The model described the portal's reported start date as having taken effect by the user's date. This is a date comparison from one source, not an audit of amendments or legal effect; no human legal adjudication was performed.

| Gate | Exact command / observation | Result |
| --- | --- | --- |
| Focused RED | `.venv/Scripts/python.exe -m pytest -q tests/services/test_retained_source_analysis.py::test_partial_read_prompt_describes_coverage_without_missing_page_claim` | failed before fix because `missing_pages` reached the model |
| Focused GREEN | `.venv/Scripts/python.exe -m pytest -q tests/services/test_retained_source_analysis.py tests/test_retained_source_routes.py` | 24 passed, 2 warnings |
| Full provider-free suite | `.venv/Scripts/python.exe -m pytest -q --basetemp D:/Download/ProfessionalLegalRAG/tmp/continuation-20260922/pytest-temp-final-20260924/cases --junitxml=tmp/continuation-20260922/full-final-20260924.xml` with TEMP/TMP on D and `PYTHONDONTWRITEBYTECODE=1` | 1,395 passed, 4 skipped, 31 warnings, 495.27 s |
| Production saved-source reanalysis | `.venv/Scripts/python.exe tmp/continuation-20260922/recheck_imports_answer.py` | HTTP 303 then 200; `ok`, 10/18 passages, five citations, no false missing-page statement |
| Production deterministic plan | `.venv/Scripts/python.exe tmp/continuation-20260922/probe_deployed_plan.py` | HTTP 200; fifth query was `dây chuyền công nghệ đã qua sử dụng` |
| Production draft/export readback | `.venv/Scripts/python.exe tmp/continuation-20260922/inspect_imports_saved_reports.py` | editor 200, Markdown and valid DOCX with official URL; draft status `invalid_structured_response` |
| Production two-excerpt report | `.venv/Scripts/python.exe tmp/continuation-20260922/complete_imports_report.py` | two exact quotes pinned; report rejected HTTP 502 `invalid_evidence_reference` |

There was no new corpus ingestion, Supabase upgrade, vector migration or registry evidence promotion in this follow-up. The live model responses and the scoped test set do not establish accuracy across arbitrary Vietnamese legal questions; human review and a representative benchmark remain necessary before any production-readiness claim.
