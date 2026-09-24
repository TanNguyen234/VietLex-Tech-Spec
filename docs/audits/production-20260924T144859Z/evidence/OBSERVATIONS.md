# Production observations

These are transcriptions of visible production UI states observed in the real Codex in-app browser during this audit. Browser screenshots were rendered in the tool session for visual inspection; the browser interface did not provide a supported path to save image bytes locally. This file is a text evidence artifact, not a fabricated screenshot or network trace. No cookies, credentials, raw private content or provider payloads are included.

## E01 — Official source and saved pages

- URL: `https://vietlex-legal-rag.vercel.app/workspaces/deb03296-8210-4a31-b06f-8f737926b968#sources`.
- Official PDF reached through source discovery: `https://congbaocdn.chinhphu.vn/CongBaoCP/VanBan/2019/11/30232/29070-1-2019993-99445-2019-qh14.pdf`.
- UI after three reading sessions: `PDF · 12/94 trang có chữ`; `Chưa có chữ ở 82 trang trong các bản đọc đang lưu.` The 82 pages were unrequested/unread, not demonstrated blank in the original PDF.
- Evidence `35c31ef1c69d8741bee69c11`, PDF page 49: Điều 119(1)-(2), 10+ workers register at provincial labor authority and file within 10 days of issuing rules.
- Evidence `c2f8681a721716f0378cd277`, PDF page 50: Điều 121, internal rules take effect 15 days after competent authority receives a complete filing.
- The official portal metadata labels number 45/2019/QH14 as `Nghị quyết ... bộ luật Lao động`; the PDF cover itself says `BỘ LUẬT LAO ĐỘNG`. This metadata discrepancy originates at the official portal or its search metadata; product displayed it unchanged.

## E02 — Source passage selection

- URL: `https://vietlex-legal-rag.vercel.app/workspaces/deb03296-8210-4a31-b06f-8f737926b968/source-analysis/20a71cb2-f2ea-45f9-98ea-7f43b33623fb`.
- Question: `Trong Bộ luật Lao động 2019, Điều 120 liệt kê hồ sơ đăng ký nội quy lao động gồm những tài liệu nào? Chỉ dùng các trang đã đọc và nêu rõ nếu Điều 120 chưa nằm trong phạm vi.`
- UI: `25673 ký tự trong bản đọc đã lưu · 12/94 trang có chữ`; `Đã đưa 10/37 đoạn liên quan vào bước trả lời`.
- Answer listed four dossier documents from Điều 120. Visible citations point to two selected passages on PDF page 50; their text contains the heading and items 1–4 across an excerpt boundary. The screen says the draft is unverified and that lexical selection may miss exceptions.
- This validates displayed selection and citation text, not actual provider token count or full wire payload.

## E03 — Pinned-evidence refresh

- URL: workspace Sources page above.
- On two attempts, pinning from a reader embedded on the same workspace page kept the visible counter unchanged until browser reload. After reload the pins existed, so persistence worked. Pinning from a separate saved-source page returned to the workspace with the updated counter immediately.
- Diagnostic local source: `app/static/js/research-workspace.js:357` assigns the same workspace URL plus `#sources` after a successful pin. Production deployment code version remains unverified.

## E04 — Report and exports

- First generated draft: `https://vietlex-legal-rag.vercel.app/workspaces/deb03296-8210-4a31-b06f-8f737926b968/reports/4f38ba3f-53c8-4ad7-997f-904dff5efc80`.
- UI: `Chưa thể xác minh kết quả phân tích` because the model cited an evidence ID outside the selected set. Draft body empty, two selected source snapshots present. This guard correctly prevented promotion; generation did not yield a usable memo in this one attempt.
- Manually edited and saved audit draft: `https://vietlex-legal-rag.vercel.app/workspaces/deb03296-8210-4a31-b06f-8f737926b968/reports/8f8a274b-8128-4d36-858e-632636a96b36`. UI labels it unverified after editing, preserves link to prior version and selected-source links.
- Markdown and DOCX controls each emitted a browser download event. File bytes and final file content were not inspected; export content is unverified.

## E05 — Document upload and full review

- URL: workspace Documents/Review pages and saved findings `https://vietlex-legal-rag.vercel.app/workspaces/deb03296-8210-4a31-b06f-8f737926b968/findings/34c092e5-cef5-48a2-829d-b7c283b0202a`.
- Test-only ASCII-heading TXT, SHA-256 `ED3A895FCD5F82502BC533394F96C3F2F8CD1765001A237267928737DBDBAEAB`, uploaded; UI showed 1063 bytes, 1 extracted part. It used `Dieu` without Vietnamese accents.
- Test-only Unicode-heading TXT, SHA-256 `C41F7E752F12F96F0816A0B32BF9CD8B802E366F688E0FF0ACA5BFC28A1869C7`, uploaded; UI showed 1409 bytes, 5 parts: preamble and Điều 1–4. Extracted Điều 2, 3, 4 match the original test document.
- Full-review plan displayed `0/5`, one `batch-1 (5 điều khoản)`, `0 chưa thể xếp lô`. After one actual batch, UI displayed `5/5` and three findings. Two cite selected Điều 119 and 121 excerpts for the deliberately wrong 20-day and immediate-effect clauses. The third says no selected direct legal evidence for the invented dossier claim, with `Cần kiểm chứng`.
- After reload, saved findings link appeared. Saved findings page showed 3/3 findings and each status `Chưa xử lý`. Current amendment status remains unverified; no finding was marked legally final.

## E06 — Document-scoped chat and mobile

- Mobile viewport: 390×844. Search `45/2019/QH14` returned one corpus document `333670` labeled Bộ luật Lao động 2019. Reader `/documents/333670?as_of=2026-09-24` had 237 structural sections. TOC jump to `#section-29` showed Điều 26, minimum probation pay 85% of the job salary.
- `Hỏi trong văn bản` opened a document-scoped chat. User asked whether 70% for a shop sales probationary hire meets the minimum, and what information is missing to compute a concrete amount. Answer said 70% is below 85%, base salary missing; on-screen legal evidence drawer showed Điều 26. One of five displayed claims had a direct evidence link; other claims were marked `Chưa xác định liên kết bằng chứng`.
- After reload, session list still included chat `81d1b713-33e9-47bf-bcfc-1f99c0d541d2` and opening it restored question and answer.
- At 1366×768 desktop and 390×844 mobile on report/reader pages, observed `scrollWidth <= innerWidth`; no horizontal overflow in those sampled pages. This does not certify all UI views.

## E07 — Selected-evidence analysis

- With exactly evidence IDs `35c31ef1c69d8741bee69c11` and `c2f8681a721716f0378cd277` selected, Analysis showed `Phạm vi bằng chứng: 2 mục` after tab navigation and return from chat.
- Checklist question about an 80-worker employer yielded 10-day filing and 15-day post-complete-receipt effect with the matching IDs, and explicitly said current amendment/repeal/transition status was insufficient. The answer was labeled `Không đủ bằng chứng`, appropriately for a question asking about September 2026 current effect.

## E08 — Admin request telemetry and measured provider tokens

- Read-only admin dashboard `https://vietlex-legal-rag.vercel.app/admin` showed 53 retained requests, 53,342 measured tokens and usage coverage `34/36` LLM calls at the time viewed. These are global retained figures, not audit-only totals and not a bill.
- `https://vietlex-legal-rag.vercel.app/admin/details/7cc317f4-491f-4a46-8772-941a08cf8904`: document-scoped Điều 26 chat, one Vertex `gemini-3.5-flash` call, provider-reported input 423, output 236, total 659; one saved context with 332 body characters/about 50 whitespace words. Backend `document_lexical_v1`; legal effect `UNKNOWN`.
- `https://vietlex-legal-rag.vercel.app/admin/details/34c092e5-cef5-48a2-829d-b7c283b0202a`: successful five-clause review batch, one Vertex call, input 1,668, output 670, total 2,338 provider tokens. Admin generic code evaluation simultaneously showed `Request hoàn tất: fail · full_document_review_ok`, `Có context: fail · 0`, `Có trích dẫn: fail · 0` despite saved findings page having three findings and two linked legal excerpts. Its admin interaction record stored zero generic contexts/citations; the structured review result persisted separately.
- `https://vietlex-legal-rag.vercel.app/admin/details/4f38ba3f-53c8-4ad7-997f-904dff5efc80`: failed report, one Vertex call, input 1,260, output 794, total 2,054 provider tokens; status `research_report_invalid_structured_response`. The tokens were consumed although the draft body was unusable.
- `https://vietlex-legal-rag.vercel.app/admin/requests?start_date=2026-09-24&end_date=2026-09-24&skip=0`: ten retained requests for that UTC day. Seven were structured report attempts (one audit case and six earlier requests) and all seven had `research_report_invalid_structured_response`; the other three were the review batch, scoped chat and official discovery/keyword planning. The six earlier requests were not independent audit test cases, and their full prompts were not inspected.
- The retained-source analysis C06 did not appear as an interaction in this admin request list. Local `app/api/retained_source_routes.py` captures provider calls into its workspace analysis record but does not call the shared interaction logger. Thus admin totals are incomplete for that workflow; no provider token count for C06 was visible in the audited UI.

## E09 — Workspace isolation, quote rejection and saved-page search

- Created test workspace B `https://vietlex-legal-rag.vercel.app/workspaces/e7076484-04a6-4afb-8160-b217e41fad7f`, titled `[AUDIT 2026-09-24] Hồ sơ B kiểm tra cách ly`. Its overview showed 0 evidence, 0 documents and 0 reports. The list still showed workspace A with 3 evidence; reopening A showed its three pins and two uploaded documents. This tests UI-visible isolation between two workspaces under the same signed-in account, not cross-account access control.
- In A's saved-source reader, entered fabricated text `ĐIỀU KIỂM THỬ BỊA: Công ty được nộp nội quy sau 99 ngày.` and clicked `Ghim trích đoạn`. UI changed the button to `Chưa ghim được; kiểm tra trích đoạn rồi thử lại`; returning to workspace still showed 3/3 pins. No fabricated evidence was saved.
- In A's source library, searched within saved pages for `Hồ sơ đăng ký nội quy lao động` without an AI call. UI returned 2 matching pages among 12 saved readable pages (PDF pages 49 and 50) with matching text and a link back to the original saved reader. Search is expressly limited to saved pages and up to 20 displayed matches.

## E10 — Empty internal search

- On the 390×844 mobile viewport, searched `999999/2099/QH99` at `https://vietlex-legal-rag.vercel.app/search?q=999999%2F2099%2FQH99&as_of=2026-09-24&legal_type=&authority=&issued_from=&issued_to=&sort=default`.
- UI showed no matching number/title and stated `Không có kết quả trong phạm vi nội bộ không có nghĩa là không có quy định`, with a link to continue in a research workspace. This avoids claiming the legal rule does not exist. Filter controls were visible but not exercised; pagination was not tested.

## E11 — Displayed legal type cannot be reused as an exact filter

- On the same 390×844 mobile viewport, unfiltered `45/2019/QH14` returned one card: `LUẬT`, `Bộ luật Lao động 2019`, `45/2019/QH14 · Quốc hội · 2019-11-20`.
- Submitting `q=45/2019/QH14&legal_type=Bộ luật&authority=Quốc hội` returned no result. This alone is not a defect because the card's actual displayed type was `LUẬT`, despite its title and the form's `Bộ luật` placeholder.
- Resetting and submitting `q=45/2019/QH14&authority=Quốc hội` retained the card. Entering its displayed type `LUẬT` as `legal_type` then returned no result; changing only that field to `Luật` restored the same card. UI labels the field `Loại văn bản (tên chính xác)`.
- The exact production URLs for the decisive pair were `https://vietlex-legal-rag.vercel.app/search?q=45%2F2019%2FQH14&as_of=2026-09-24&legal_type=LU%E1%BA%ACT&authority=Qu%E1%BB%91c+h%E1%BB%99i&issued_from=&issued_to=&sort=default` (empty) and the same URL with `legal_type=Lu%E1%BA%ADt` (one card). Local diagnostic source `app/services/legal_browser.py:157-160,341-344` applies exact field equality; `app/templates/legal_search.html:4` uses the `.eyebrow` class and `app/static/css/vietlex.css` applies uppercase visual styling. Deployment SHA is unknown; the production behavior itself establishes the mismatch.
