# Findings verified on production

These priorities describe observed user impact, not severity of a hypothetical exploit. The deployed commit was not identified, so local source references are diagnostic candidates rather than proof of the deployed implementation. Evidence IDs refer to `evidence/OBSERVATIONS.md` and case IDs to `CASES.md`.

## F01 · P3 · Saved-PDF coverage wording obscures unread pages

- **User/feature:** researcher checking how much of an official PDF has actually been read; C03, E01.
- **Reproduce:** in the audit workspace read pages 1–5, 46–50 and 55–56 of the 94-page PDF; reopen `#sources`.
- **Expected:** the 82 unrequested pages should be described explicitly as *not yet read*, distinct from pages read but containing no extractable text.
- **Actual:** `PDF · 12/94 trang có chữ` followed by `Chưa có chữ ở 82 trang trong các bản đọc đang lưu.` This is technically scoped to the retained reads, but can make a reader infer that extraction failed on 82 pages. The detailed analysis page clarifies it is not a conclusion about the original PDF; the library card does not.
- **Frequency/scope:** 1/1 observed 94-page source library card; PDF original was not shown to lack those pages.
- **Diagnostic code:** `app/services/retained_source_analysis.py:97` defines `missing_pages` as all PDF page numbers absent from saved reads; `app/templates/workspace_source_library.html:22` renders that set as pages with no text. This matches the observed wording, but deployment SHA is unknown.
- **Smallest fix:** display `12 trang đã đọc có chữ; 82 trang chưa đọc` and separately count attempted pages with empty extraction/OCR failures. Do not change source-data semantics merely to change the label.
- **Acceptance:** on a 94-page file after reading 12 distinct pages, library explicitly shows 82 unread; when one attempted page extracts no text, it appears in a separate count. No page is declared missing from the original without evidence.
- **Workaround:** use the detailed retained-source analysis disclosure, which states the pages absent from the saved read are not necessarily absent from the original.

## F02 · P2 · Pinning from the workspace reader leaves a stale evidence count

- **User/feature:** researcher pinning a source quote; C04, E03.
- **Reproduce:** on the workspace source reader embedded under the same workspace URL, enter an exact quote from Điều 119 and click pin. Repeat with a second exact excerpt. Watch the visible evidence list/count, then reload the page.
- **Expected:** success should immediately display the new evidence or navigate to a refreshed state.
- **Actual:** on 2/2 same-page pin attempts the count/list stayed stale; both new pins appeared after manual reload. A third pin from the separate saved-source page returned to the workspace and was visible immediately. There is no observed data loss.
- **Frequency/scope:** 2/2 embedded same-page pins; 0/1 separate-page pin. Only one workspace tested.
- **Diagnostic code:** `app/static/js/research-workspace.js:357` calls `location.assign('/workspaces/' + workspaceId + '#sources')` after successful POST. When already at this URL/hash, that assignment need not reload. The route's exact deployed source is unverified.
- **Smallest fix:** after successful pin, refresh the evidence component/count from a real response or force a documented full navigation/reload; show confirmation only when persisted.
- **Acceptance:** pinning twice from the same workspace page updates the count immediately on each attempt and both quotes remain after reload; failed pin leaves no false success.
- **Workaround:** reload `#sources` after pinning.

## F03 · P1 · Generated reports repeatedly fail structured-output validation

- **User/feature:** researcher generating a memo from two selected legal excerpts; C07, E04.
- **Reproduce:** select evidence IDs `35c31ef1c69d8741bee69c11` and `c2f8681a721716f0378cd277`, then ask Reports for an audit memo on filing place/deadline/effect for 80 workers at 24/09/2026.
- **Expected:** a grounded draft citing only the selected IDs, or a useful recovery path after a clear model-output validation failure.
- **Actual:** validator reported the model used an ID outside the selected set; the draft body was empty and status `Chưa thể xác minh kết quả phân tích`. Two selected source snapshots were retained. The validator's refusal to present an invalid memo as verified is correct.
- **Frequency/scope:** direct audit case 1/1 failed. Read-only admin requests for 24/09/2026 showed 7/7 retained structured-report requests with `research_report_invalid_structured_response`, including this audit case and six earlier requests using one or two selected records. This is evidence of recurring production failure for that day's retained attempts, not a rate for all users or dates. E08.
- **Measured cost:** the audit's failed report consumed 1,260 input + 794 output = 2,054 provider-reported tokens and yielded no usable memo body. Admin notes that this total omits embedding/reranker and unreported usage.
- **Cause:** this audit model output violated the selected-ID contract. The six other errors share the generic invalid-structured status; their specific validation reasons were not inspected. Whether prompt wording, decoding, model behavior or deployment version caused the cluster remains unverified. `app/services/research_report.py` contains the local report validator, but cannot establish production causality without the deployment SHA or sanitized server trace.
- **Smallest fix:** investigate sanitized validation telemetry for this case, then constrain/repair ID selection from the allowed set without inventing quotations. Preserve the current guard. Offer a visible retry with the same selected evidence and explain what happened.
- **Acceptance:** several fresh memo prompts over different selected evidence sets produce only allowed IDs and usable, clearly unverified drafts; deliberately invalid IDs remain blocked. Measure success rate and input/output tokens per attempt.
- **Workaround:** manually edit an unverified draft with checked citations, as C08 demonstrated.

## F04 · P2 · Generic admin code checks misclassify a successful structured review

- **User/feature:** operator diagnosing review quality and token spending; C11/C13, E05/E08.
- **Reproduce:** open admin detail for review trace `34c092e5-cef5-48a2-829d-b7c283b0202a`, then open the corresponding saved findings page.
- **Expected:** the admin status and code checks should describe the structured review contract: batch completion, five scheduled/reviewed clauses, three findings, and two linked selected legal excerpts. If the generic chat checks do not apply, label them N/A.
- **Actual:** status is `full_document_review_ok` and saved findings show 3/3, but the admin `Kiểm tra code` table says `Request hoàn tất: fail · full_document_review_ok`, `Có context: fail · 0`, `Có trích dẫn: fail · 0`. Admin's generic interaction row saved 0/0 context/citations even though the structured result linked evidence separately.
- **Frequency/scope:** 1/1 audited full-review batch. This finding is about operational interpretation, not a failure of the actual three review findings.
- **Diagnostic source:** local `app/services/evaluator.py` and `app/templates/admin_details.html` implement generic code checks; production deployment match unverified.
- **Smallest fix:** branch deterministic admin checks by request kind, using structured review fields for review/report tasks, and render generic chat context/citation checks as N/A where inapplicable.
- **Acceptance:** opening this kind of successful batch no longer displays a generic `Request hoàn tất: fail`; saved review coverage and evidence-link counts are shown or explicitly unavailable. Actual failed structured results still display failure.
- **Workaround:** inspect the saved findings page and provider status directly; do not rely on the generic code-check row for structured review.

## F05 · P2 · Retained-source LLM usage is absent from the central admin request list

- **User/feature:** operator budgeting AI input for long saved sources; C06/C13, E02/E08.
- **Reproduce:** submit the audit's retained-source analysis of Điều 120; inspect the resulting analysis page, then filter `/admin/requests` to 24/09/2026.
- **Expected:** a paid LLM operation should have traceable provider-reported input/output counts in the same usage view, with clear coverage if usage was unavailable.
- **Actual:** retained-source analysis returned an AI answer, but the ten retained admin request rows for the day contained no corresponding source-analysis interaction. The analysis page shows 10/37 passages but no provider token count. Other audited LLM tasks have admin usage details.
- **Frequency/scope:** 1/1 retained-source call compared with the day's 10 admin rows. No statement about whether the provider itself returned usage for this call.
- **Diagnostic source:** local `app/api/retained_source_routes.py:24,77` captures `current_provider_calls()` into the workspace analysis record but does not save a central interaction. Deployment SHA unverified.
- **Smallest fix:** record a sanitized central interaction for this task with analysis ID, selection method/count, input/output usage coverage, status and latency; retain per-workspace provider-call record without duplicating billing totals.
- **Acceptance:** after one relevant-mode and one full-mode call, each appears in admin requests with selection counts and provider usage or explicit N/A. Aggregate totals reconcile with detail rows and disclose exclusions.
- **Workaround:** the analysis page exposes selected/available passage counts, but those counts cannot be converted reliably into provider tokens or cost.

## F06 · P2 · The displayed legal type does not round-trip through the exact filter

- **User/feature:** person narrowing a known law by the type shown on its search card; C18, E11.
- **Reproduce:** search `45/2019/QH14` on production and note the card type `LUẬT` and authority `Quốc hội`. In the filter, enter `Quốc hội` as authority and `LUẬT` as type, then apply. Change only the type to `Luật` and apply again.
- **Expected:** copying the displayed type into a field labeled `Loại văn bản (tên chính xác)` should keep the known record, or the UI should expose the exact canonical value required.
- **Actual:** authority alone retained the record. `LUẬT` returned the empty state; `Luật` restored the same record. A user can incorrectly conclude that the record is absent after adding a seemingly exact filter.
- **Frequency/scope:** one known record, one decisive uppercase/title-case pair on mobile. Other legal types and sorting were not tested.
- **Diagnostic source:** local `app/templates/legal_search.html:4` shows `result.legal_type` in `.eyebrow`; local `app/static/css/vietlex.css` applies `text-transform:uppercase` to `.eyebrow`; local `app/services/legal_browser.py:157-160,341-344` uses exact field equality. This is a plausible mechanism, not proof of deployed source identity.
- **Smallest fix:** render the canonical type alongside its display styling or offer a controlled type selector whose submitted value is the canonical type. Preserve strict filtering semantics if required, while allowing users to copy the visible label successfully.
- **Acceptance:** `45/2019/QH14` remains visible when a user selects or copies the type shown on its card and applies the `Quốc hội` filter; the selected filter value survives reload. Test at least one more type and both backed search stores.
- **Workaround:** enter `Luật` instead of the visually uppercased `LUẬT` for this record.

## Investigations and limits, not verified product defects

- **Token/cost risk:** source code implements bounded selected evidence and query-based `relevant_source_passages`, and C06 showed 10/37 selected passages on production. The retained-source route defaults to `full` if no scope is submitted (`app/api/retained_source_routes.py:31`), while the observed source-library form explicitly submits `relevant` first. Full mode can include up to 120,000 characters/24,000 whitespace words. No actual provider token counts were available, so no cost saving percentage or leak is claimed.
- **Reference-sensitive retrieval:** local `_relevance_terms` in `app/services/retained_source_analysis.py` strips digits. C06 succeeded on a descriptive Điều 120 question, but an article-number-only question could rank poorly; this requires a focused corpus test before a defect claim. Improve with generic parsed references (document number, article, clause, point), adjacent context and exception preservation, rather than hard-coded legal topics.
- **Review amplification:** local full-document review uses approximate whitespace-token budgets and repeats the selected legal evidence for each batch (`app/services/full_document_review.py`). C11 had only one batch; total token/cost behavior on long documents was not measured.
- **Search metadata conflict:** official Công báo portal text labels 45/2019/QH14 as `Nghị quyết ... bộ luật Lao động`, while the official PDF cover says `BỘ LUẬT LAO ĐỘNG`. VietLex source-discovery card inherited the portal label, while its internal record used the correct title. This is an upstream metadata discrepancy. A product warning could help when parsed PDF cover disagrees with search metadata; root responsibility remains unverified.
- **Exports:** Markdown and DOCX download events were observed but bytes inaccessible through the browser tool. File-content correctness is unverified, not failed.
- **Current legal effect:** 2019 PDF text and initial effective date do not establish whether the provisions were amended, repealed or subject to transition by 24/09/2026. No present-day legal advice conclusion is drawn.
