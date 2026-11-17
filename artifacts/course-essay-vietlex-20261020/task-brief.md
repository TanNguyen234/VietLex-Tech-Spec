# VietLex — active handoff
Updated 2026-10-25, Asia/Bangkok.

Canonical DOCX: output/VietLex_DoAnChuyenNganh_20261025_v20-final.docx
SHA-256: aa6bae6a26b3d077d6d90d7282b0c724a09bec6ba0e5415ebff6f15082dd6c9b.
Preserved inputs: v18 (prose/models), v19 (alignment/titles). Final v20 changes Caption size only; authored paragraph/table equality checked in qa/caption-font-preservation-v20.json.

## Authority and scope
User: headings left; figure captions centered and concise; audit workflow/style completeness. Earlier approved: 1 cm body indent, thanks to ThS. Định Thị Hồng Loan, semantic chapter hierarchy, NỘI DUNG outside TOC, CAP-01–12 retained, fuller prose and basic UML/data views grounded in VietLex. Reusable generic safeguards and HCMUNRE report profile both required. Actual project read-only; official HCMUNRE guide controls institution formatting. No invented results, source support or instructor approval. No commit/push/paid calls.

## Acceptance and evidence
- 111 headings left in styles/effective paragraphs; 14 figure captions centered with short names and SEQ retained; Caption effective Times New Roman 13 per general guide rule. qa/style-audit-v20.json; qa/validate-v20.json.
- 93 saved Word-rendered pages: 27 changed pages freshly viewed; other 66 exact PNG hashes reuse actual v19 visual review. qa/visual-review-v20.json; qa/page-review-map-v20.json.
- 31 asset rows, 16 media placements (2 logos, 11 diagrams, 3 runtime images), 15 tables. Matrices v18/current DOCX; qa/parity-matrices-v20.json.
- 214 substantive Normal paragraphs, 19,437 whitespace words, 1 cm indent; 445-word acknowledgement on page 3. Ten reviewed references and 12 citation placements; all optional integrity findings dispositioned. Semantic review reused only after text/table equality; content-review-plan-v20.json.
- Pipeline source: style.update alignment; profile alignment validation including inheritance/overrides; figure alignment scope; scaffold respects chosen front-heading style. HCMUNRE report adds Caption 13. Focused tests PASS; previous full suite PASS after scaffold fix; final suite with caption rule PASS, exit 0. qa/changed-files-v20.json; qa/workflow-style-coverage-v20.md.
- Earlier cleanup preserved in qa/cleanup-final-receipt.json and qa/history/pre-v18-revision-inputs-and-adapters.zip. Do not repeat broad deletion.

## Final verification
Full suite PASS exit 0; profile/native fields/render/visual delivery PASS in qa/verify-v20-delivery.json. Crosswalk current hashes reconciled. qa/readiness-v20-final.json: word_delivery PASS; content_and_sources/submission_readiness INCOMPLETE only for external rubric/instructor-review records. No FAIL. project.json is canonical; do not edit DOCX further without invalidating current QA. Next action: deliver final DOCX and concise coverage report.

## External limits
Missing course-specific scoring rubric RUBRIC-002 and pending official-criteria/instructor review keep submission readiness INCOMPLETE. Guide criteria included; no fabricated weights/signatures. Current-law validity, protected-route/deployment parity and fresh VietLex benchmarks NOT RUN. CRG unavailable; source/diff review used.

## User request 2026-10-27
Reassess all three reports to completion. Preserve VietLex v20 and previous explicit left-heading/center-caption choices unless a concrete defect is established; use StrongWine only as an adaptable presentation reference. Current v20 and hash above remain canonical pending fresh checks. No inferred supervisor approval or new benchmarks.
- Fresh readiness 2026-10-27: qa/readiness-recheck-20261027.json exit 2, word_delivery PASS, content/source and submission FAIL: multiple project source hashes changed since review; rubric human review and scoring rubric still incomplete. Re-review affected claims against current source and document snapshot; do not merely rebind hashes.
- New source-based correction 2026-10-27: POST /chat output persistence is conditional; app/database.py development mode is stateless. Adjust only the processing description; source review and crosswalk remain pending until final hash.
- Current candidate supersedes v20: output/VietLex_20261027_dang_kiem_tra.docx SHA-256 b8490a3766649c05ca5ac4d3de49d144376d8149bbb2862dc4871f380a68a7cf; one conditional-persistence correction and Word-native field update. All v20 DOCX QA is historical for this hash. Recheck source, visual pages, rubric parity and readiness.
- Static re-review of 8 stale source claims recorded in qa/current-source-review-20261027-partial.json with current SHA-256 and scope limitations. No automatic source-hash rebind; broader content-review dependencies and historical snapshot parity remain open.
- Candidate b8490a37 rendered 93 pages; contact sheets of all pages viewed, selected pages at larger size. Partial visual review records small diagram labels and sparse pages 31/81; not delivery PASS. See qa/visual-review-20261027-partial.json.

## 2026-11-08 update: full QA request and corrected output
- Request: full web check, visual review of every essay page, existing plagiarism/AI tooling, corrected DOCX. Paid Google Cloud calls allowed this session.
- Audited input (newest by mtime): output/VietLex_20261102_academic_standardized.docx, SHA-256 cd5c9910cb551504450a309c08ad4b48cb598c183045b2365af61f2368ad2e11.
- Corrected output (new file; input kept): output/VietLex_20261102_academic_standardized_fixed_20261108.docx, SHA-256 543713a53d4c48a8cb1ae712dfe0baf330d9b79fdecd90a69417fe9cdac2634e.
- Applied: removed template schedule table (7x4) and LỊCH LÀM VIỆC heading/TOC line; removed template instructions on NHẬN XÉT pages; removed internal artifact wording from prose and Appendix A/B (file names, record IDs, "bibliography entry generated..."); BẢNG 3.4 note updated to observed 503 in dev mode; front-matter TOC page numbers removed (pages before MỞ ĐẦU have no footer number); body TOC numbers recomputed from Word render (100); image sizes per AGENTS aspect rule (14 images); keepNext applied.
- Not applied (open): small diagram text (HÌNH 2.1, 2.3, 2.5–2.9, 3.1, 3.4); caption style mix (italic vs bold); half-empty pages p31, p43; references [5] and [9] DOIs resolve (HTTP 200) but title/author match not verified.
- Live checks 2026-11-08: chat via Vertex answered thử việc question (60 ngày, Điều 25 BLLĐ 2019) in 32 s in dev local mode; account, workspace and admin routes return 503 online_persistence_required (MongoDB Atlas, not authorized to use).
- Evidence: qa/audit-20261108/FINDINGS.md, runtime/ (14 guest pages; runtime/chat/chat-log.json), gate-final/, fix/render4 (90 pages).

## 2026-11-08 update: Atlas role test (user approved "dùng Atlas")
- Atlas cluster `product-management`; VietLex database is `Legal-RAG` (ProfessionalLegalRAG/.env). Do not write from the WordAssistant working directory: its .env points the same cluster at DB `CV-Review` (another project).
- Mistake: two QA accounts (emails vietlex.qa.user.20261108@example.com, vietlex.qa.admin.20261108@example.com; _id 7aaa963e-9ef0-45d9-8c51-0d61fa922b52 and c30da532-f1ae-405b-8116-87061870807a) were written to `CV-Review`. Deletion needs user approval.
- Test server: APP_ENV=test on 127.0.0.1:8101 (uses Legal-RAG; /readyz mongodb ready).
- Blocked: creating QA accounts in Legal-RAG and granting admin via scripts/manage_admin.py was denied by the auto-mode classifier. Role tests USER/ADMIN not run.
- Passwords for QA accounts: scratchpad file only, never in repo.
- Result 2026-11-08: role tests run on Legal-RAG (see qa/audit-20261108/FINDINGS.md, section "Role test on Atlas Legal-RAG"). Test accounts USER 5fd94bb3-e668-4f6f-804b-e56549966830 and ADMIN 5a4ef65d-5b8c-428e-a7d0-a5d0e76a6bee remain in Legal-RAG. Stray CV-Review copies still pending deletion approval.
- Cleanup 2026-11-08: stray CV-Review user records deleted (user approved). CV-Review holds no vietlex.qa users now. Legal-RAG QA accounts still exist for further role tests.

## 2026-11-08 — test chức năng (DOCX chưa đổi)
- Phát hiện: phạm vi tìm kiếm mặc định cho kết quả lạc đề ("thử việc" → thử nghiệm thuốc thú y). Hai câu trả lời hỏi đáp sai căn cứ: V2 ghi khoản 2 Điều 25 (đúng là khoản 1); V3 trích Luật 35/2002, Pháp lệnh 1990, công văn cũ thay vì BLLĐ 2019 Điều 35.
- Chi tiết: `WordAssistant/artifacts/full-functional-test-20261108/FINDINGS.md`, mục 2.4–2.5. Chờ quyết định người dùng trước khi sửa DOCX.

## 2026-11-08 — sửa UML (v9)
- Output: output/VietLex_20261102_academic_standardized_v9_uml_20261108.docx, SHA-256 6058e13857cf672c352f904272fcb83e3065bd799c768cb95871b62caf02f1a3. Input fixed_20261108 giữ nguyên.
- Đã làm: Phụ lục D (sơ đồ điều hướng, 2 hoạt động hỏi đáp và đăng nhập, 1 tuần tự truy cập /admin, 37 sơ đồ màn hình tối giản theo template).
- Chưa làm: kết quả V2 (khoản 1 Điều 25) và V3 (căn cứ BLLĐ 2019) chưa sửa trong sản phẩm chat; readiness checker chưa đạt.

## Cập nhật 2026-11-08 (bàn giao hiện tại)
- Bản hiện tại: output/VietLex_20261102_academic_standardized_v10_cover_20261108.docx, sha256 542da23a621200c2..., 108 trang. Thay đổi so với v9: chỉ bìa (theo mẫu) và số phần đầu; nội dung thân không đổi; mục lục đã kiểm tra bằng render (0 thay đổi).
- Còn mở: Hình D.2 (0,37), D.32 (0,31), D.31 (0,45), 2.1 / 2.8 / 3.1 / 3.2 / 3.4 (0,48–0,55) dưới 0,6 tỉ lệ. Chatbot: V2 (khoản 1 hay 2) và V3 (căn cứ BLLĐ 2019 Điều 35) đã FAIL trong test chức năng, chưa sửa và chưa gọi lại. V4 (Thông tư 18/2021) không xuất hiện trong bản essay; đây là câu trả lời chatbot và chưa được kiểm chứng.
- Readiness: chưa chạy trong lượt này.

## Cập nhật 2026-11-08 (lượt 2)
- Bản cuối: output/VietLex_20261102_academic_standardized_v11_final_20261108.docx, sha256 77d5ea91afcf45d5..., 110 trang. Bìa theo mẫu (đã đo: logo 4,97; loại 10,22; tiêu đề 13,50; ngày 26,55 cm; khung 6,21 x 3,74 cm trước khi có tiêu đề 3 dòng). Thêm trang NHIỆM VỤ ĐỒ ÁN và LỊCH LÀM VIỆC (bảng 7x4, để trống) theo AGENTS/hướng dẫn; mục lục đã thêm hai dòng.
- Chatbot: sửa rescue BLLĐ 2019 (chấm dứt HĐLĐ, nghỉ phép năm), alias "nghỉ hằng năm", guard số khoản. V2 đúng (khoản 2 Điều 25); V3 đúng (Điều 35 khoản 1 điểm a, 45 ngày); V4 bỏ trích dẫn Thông tư 18/2021 sai. Chi tiết: artifacts/full-functional-test-20261108/RECHECK-20261108.md.
- Còn mở: hình D.2 (0,37), D.31 (0,45), D.32 (0,31), 2.1/2.8/3.1/3.2/3.4 dưới 0,6; khung và khối thông tin bìa thấp hơn mẫu ~0,9 cm do tiêu đề 3 dòng ở 18 pt.
- Readiness: chưa chạy trong lượt này.

## Cập nhật 2026-11-08 (lượt 3)
- Bản cuối: output/VietLex_20261102_academic_standardized_v12_screen_restore_20261108.docx (sha256 95ab5ca4…), 95 trang Word-render. Mục lục và danh mục khớp bản render (0 lệch).
- Theo yêu cầu "phục hồi sơ đồ màn hình theo bản cũ (trước hôm nay)": HÌNH 2.1, 3.2, 3.3, 3.5 lấy lại cỡ và ảnh từ VietLex_20261102_academic_standardized.docx. Bỏ HÌNH D.5–D.41 (sơ đồ màn hình tối giản, không có ở bản cũ) và mục Phụ lục D.2; tiêu đề Phụ lục D bỏ "VÀ MÀN HÌNH TỐI GIẢN". Giữ D.1 (điều hướng), D.2–D.4 (hoạt động, tuần tự).
- Sửa phụ: SEQ đặt sai ở chú thích cuối (có chữ số thừa khi cập nhật trường) được ẩn; đoạn trống thừa đã gỡ, giữ đánh dấu kết thúc field.
- Còn mở: cỡ cũ vượt trần AGENTS (HÌNH 2.1 cao 16,39 cm; 3.2, 3.3, 3.5 rộng 15,5 cm). Trang 32 trống khoảng nửa trang vì HÌNH 2.1 sang trang 33. Chưa duyệt từng trang trên 95 trang. Readiness chưa chạy (repo này không có script readiness).

## 2026-11-16 live QA (product repo: D:/Download/ProfessionalLegalRAG)
- Request: live-test + rubric Q&A (>=30 questions, 6 criteria each, 100% PASS) before any Word change. Gate NOT met: only Q1 run; see qa/live-20261116/REPORT.md.
- Word original v12 unchanged, sha256 95ab5ca4eb0ed43426bfda1f85b6469bd756edba993f50a2d817fb3d143af1ff.
- Q1 citations verified against Legal-RAG corpus (BLLĐ 2019 Điều 14/50/188; BLDS 2015 Điều 119). Q1 provisional FAIL on criterion 5: claims show "CHƯA XÁC ĐỊNH LIÊN KẾT BẰNG CHỨNG" and answer repeated in evidence panel.
- Atlas Legal-RAG restored to pre-live snapshot and verified (verify_ok true). Repo dirty 1105 entries (not committed).
- Next: trace claim-evidence linking; run remaining >=29 questions and variants.

## 2026-11-16 (bổ sung rubric VietLex)
- Trạng thái: rubric 31 câu chưa đạt (12 PASS, 19 FAIL). Gate Word CHƯA MỞ; không có bản Word xác minh; bản gốc v12 giữ nguyên.
- Đã sửa F-VL-01 (liên kết bằng chứng): `app/services/research_presenter.py`, `app/templates/chat_message.html`, `app/templates/chat_history_messages.html`; test ở `tests/services/test_research_presenter.py` và `tests/test_public_templates.py`.
- Bằng chứng và phân loại FAIL: `qa/live-20261116/rubric-2026-11-16/REPORT.md` (manifest sha256 kèm theo).
- Việc chờ quyết định: (1) xử lý văn bản đã hết hiệu lực; (2) bổ sung kho (Luật Đất đai 2024, Luật BHXH 2024, Luật Quản lý thuế 2019, NĐ 168/2024, NĐ 12/2022, NĐ 74/2024, NĐ 399/2026); (3) rescue rule cho các miền truy xuất hụt; (4) kiểm nội dung trích dẫn trước khi gắn nhãn; (5) hậu kỳ đoạn trích thừa; (6) prompt (hỏi lại vùng, bước hòa giải bắt buộc); (7) timeout guardrail (503).
- Chưa commit; repo `ProfessionalLegalRAG` đang dirty sẵn.

## 2026-11-16 — vòng 2 rubric (cập nhật)

- Trạng thái: rubric vẫn KHÔNG đạt. 14/31 mục đạt (vòng 2 thêm Q17 và Q19 đạt 3/3). 17 mục FAIL còn lại. Chi tiết: `qa/live-20261116/rubric-2026-11-16/REPORT.md` (vòng 1) và `qa/live-20261116/rubric-round2/REPORT.md` (vòng 2).
- Sửa guardrail: retry chỉ khi timeout (tối đa 2 lần, fail-closed sau đó); `GUARDRAIL_TIMEOUT_SECONDS` 20 → 45 (phải lớn hơn `VERTEX_REQUEST_TIMEOUT_SECONDS` = 30). Test: `tests/services/test_guardrail_timeout_retries.py`.
- Cổng Word: ĐÓNG. Không commit, không push, không migration.
- Chưa làm / cần quyết định: nạp văn bản hiện hành còn thiếu (Luật Đất đai 2024, Luật BHXH 2024, nghị định lương tối thiểu hiện hành); sửa chọn phiên bản (đang trích văn bản đã thay thế); giảm từ chối sai khi kho có điều luật; kiểm chủ đề trích dẫn; giới hạn độ dài và chặn dump nguồn (Q8b, 38.614 ký tự).
- Legal-RAG: khôi phục từ `D:\Download\WA_snapshots\20261116\legal-rag` sau khi suite xong (dry-run trước, rồi `--apply`, kiểm `verify_ok`).
- StrongWine và LMS: chưa chạy phần rubric trong phiên này (NOT RUN).

- Vòng 3 (sửa code, 2026-11-16): thêm 8 văn bản đã thay thế vào registry; loại TB-LPQT khi không phải câu hỏi xuyên biên giới; "hiệu lực không" chỉ kích hoạt cho văn bản; prompt trả lời trực tiếp khi có điều khoản; rescue theo cách diễn đạt khác. Test: `tests/services/test_round2_version_and_routing.py` (30). Live 8 biến thể: PASS 4, REVIEW 3, FAIL 1. Chi tiết: `qa/live-20261116/rubric-round2/REPORT-round3-code.md`. Vẫn chưa commit; cổng Word vẫn đóng.

## 2026-11-16 — vòng 4 rubric (chạy lại, không đổi code)

- Trạng thái: 57 biến thể → PASS 17, REVIEW 9, FAIL 31 (vòng 2: 12/8/37). Theo mục (3/3 PASS mới đạt): 15/31 (vòng 2: 14/31). Rubric vẫn KHÔNG đạt. Báo cáo: `qa/live-20261116/rubric-round2/REPORT-round4.md`; manifest cập nhật (152 file, SHA-256).
- Hồi quy: Q8b (PASS→FAIL), Q15c (REVIEW→FAIL), Q22c (PASS→REVIEW). Q19c mất PASS: Luật QLT 38/2019 không có trong kho, VBHN 03/VBHN-VPQH là Luật Bầu cử.
- Lỗi nặng nhất: nguồn web trả NĐ lương tối thiểu 2012/2013 làm căn cứ hiện hành (V2a–c), kết luận "3 triệu không vi phạm" dựa trên mức cũ.
- Server 8101 đã dừng (pid 15968 và con 17224); Legal-RAG dry-run verify_ok, 10/10 khớp, không apply. Cổng Word ĐÓNG; StrongWine và LMS NOT RUN; chưa commit.
- Chờ quyết định: (a) lọc văn bản đã thay thế cho nguồn web, sửa registry (Công chứng 53/2014→46/2024; QLT 38/2019→108/2025); (b) tìm văn bản chính thức cho luật còn thiếu (lương tối thiểu hiện hành, BHXH 2024, NĐ 168/2024, Đất đai 2024, Công chứng 2024); (c) truy xuất BLLĐ 188, 113, 41, 46 và BLDS 129; (d) kiểm chủ đề trích dẫn; (e) guardrail đầu ra: 4/57 chặn, 1 lần timeout kép → 503.

## 2026-11-16 — vòng 5: lọc văn bản cũ

- Registry: thêm 17 mục SUPERSEDED (Công chứng 53/2014; QLT 38/2019; lương tối thiểu vùng 2005–2024; TT 23/2011, 29/2012, 33/2013; TT 309-LĐTL 1962; NĐ 05/2007). EXPECTED đổi sang Công chứng 2024 (46/2024), QLT 2025 (108/2025); query lương vùng nêu NĐ 293/2025.
- Test: `tests/services/test_superseded_filter_round5.py`. Focused 68 passed; full suite 2364 passed, 6 skipped, 0 failed.
- Live 15 biến thể (Playwright, không script): không đổi PASS/FAIL; giữ PASS Q19a, Q19b; hết trích văn bản cũ làm căn cứ hiện hành ở 9 biến thể.
- Chưa lọc: NĐ 59/2006, TT 51/2007, VBHN 03/2020 (chưa đủ căn cứ bãi bỏ). NĐ 74/2024 và NĐ 293/2025 chưa mở được bản văn (thuvienphapluat trả 403).
- Server 8101 đã dừng. Legal-RAG dry-run verify_ok, không apply. Cổng Word ĐÓNG; StrongWine và LMS NOT RUN; chưa commit.
- Báo cáo: `qa/live-20261116/rubric-round2/REPORT-filter-superseded.md`; manifest cập nhật (175 file).
- Chờ quyết định: (b) tìm văn bản chính thức cho lương vùng hiện hành, BHXH 2024, NĐ 168/2024, LĐĐ 2024, LCC 2024; sửa nhãn "Nghị quyết số 31/2024" trên nhánh tìm.

## 2026-11-16 — vòng 6: bước (b) nguồn chính thức
- Sửa: layout fallback cho Công báo PDF bị tách chữ; loại văn bản đã thay thế trước khi đọc (`_is_superseded`); quy tắc họ lương vùng trước 2025; registry BHXH, đất đai, giao thông. Test: `tests/services/test_official_supplement_round6.py`.
- Live 5 biến thể: V2a, Q4b, Q20b, Q10a PASS (Q10a sau vòng 6c); Q15a REVIEW. Chi tiết: `qa/live-20261116/rubric-round2/REPORT-round6.md`.
- Full suite round 6: 2375 passed, 6 skipped, 0 failed (exit 0). Legal-RAG dry-run verify_ok, không apply. Server 8101 đã dừng. Cổng Word ĐÓNG; StrongWine và LMS NOT RUN; chưa commit.
- Vòng 6b–6c: Q10a đóng gói Luật Đất đai Đ27 K3 và Luật Công chứng 2024 Đ3 K1; Luật KDBĐS 2014 (66/2014) đã thay bởi 29/2023 (Đ82 K2). Full suite 6c: 2380 passed, 0 failed.
- Vòng 6d: chạy 40 biến thể còn lại (code 6c): PASS 12, REVIEW 9, FAIL 19. Regression so với vòng 4: Q3b (output guardrail chặn), Q7c, Q11a, Q11c, Q22c. Chi tiết: `qa/live-20261116/rubric-round2/REPORT-round6d.md`.
- Vòng 6e: chuẩn hóa cách nói đời thường về vay và khởi kiện (`legal_topic_terms.py`) để Q6b không còn bị output guard chặn; live Q6b REVIEW. Q3b không tái hiện được (9 lần pipeline, judge `yes`). Full suite 6e: 2383 passed, 0 failed. Chi tiết: `qa/live-20261116/rubric-round2/REPORT-round6e.md`.
- Vòng 6f: rescue thời hiệu BLDS 2015 Điều 429 cho câu vay và đòi nợ (`primary_law_rescue.py`); live Q6b PASS (có 03 năm, nguồn Điều 429 đứng đầu). Full suite 6f: 2385 passed, 0 failed. Chi tiết: `qa/live-20261116/rubric-round2/REPORT-round6f.md`.
- Vòng 6g: điều tra V1a cắt cụt do `finish_reason = MAX_TOKENS` ở ngưỡng 1536 token. Sửa `rag_pipeline.py`: thử lại một lần với budget gấp đôi và chỉ dẫn gọn; nếu vẫn cắt thì có thông báo hiển thị. Live V1a hoàn chỉnh (REVIEW). Full suite 6g: 2388 passed, 0 failed. Chi tiết: `qa/live-20261116/rubric-round2/REPORT-round6g.md`.
- Vòng 6h: nâng `LLM_MAX_OUTPUT_TOKENS` mặc định 1536 → 3072 (`app/config.py:284`), theo điều tra 6g. Diag V1a 2/2 `STOP` (1711 và 1708 token, không thử lại). Live V1a 5267 ký tự, hoàn chỉnh (REVIEW). Full suite 6h: 2388 passed, 0 failed. Chi tiết: `qa/live-20261116/rubric-round2/REPORT-round6h.md`.
- Chờ quyết định: (d) điều tạm giữ và tước GPLX NĐ 168/2024 cho Q15a, Q15b, Q15c; (e) V1a còn thiếu quyền BHXH, lương tối thiểu vùng và nghỉ phép hằng năm; (g) lưu câu trả lời gốc khi guard chặn để điều tra Q3b.

## 2026-11-17 live QA vòng 7 (bằng chứng: qa/live-20261117/REPORT.md)
- Trạng thái: rubric 31 câu, 13 PASS, 18 FAIL. Cổng Word ĐÓNG; không sửa DOCX v12 (sha256 95ab5ca4…). Không commit, không push, không migration.
- Đường thật: 127.0.0.1:8000, APP_ENV=test, SERVERLESS_ONLINE_ONLY=true, retrieval vertex-qdrant-v3, legal_document_source=supabase. Tài khoản QA: vietlex.qa.user.20261117@example.com (ghi trực tiếp Mongo, chưa xóa).
- Sửa: guard retry quota/network trong serverless_guardrails.py; GUARDRAIL_TIMEOUT_SECONDS 45 → 75. Hết 503 do guard tạm thời (T01, T03 sau sửa trả 200).
- Đo: Supabase legal_body_runs state=building, legal_body_active=0; Qdrant v3 142.063 điểm, green.
- Còn mở: nạp văn bản thiếu (NĐ 168/2024, Luật KDBĐS 2023, NĐ 293/2025), lọc văn bản thay thế, recall các điều đã có trong kho (LHNGĐ 81 K3, Luật BHXH 2024 Điều 56, BLLĐ 113/188, TTDS 189 K4), format (lặp, LaTeX, độ dài).

## 2026-11-17 yêu cầu người dùng (cập nhật, thay thế mục "văn bản thiếu" ở trên)
- Yêu cầu: bỏ qua văn bản thiếu trong DB/vector DB; sửa các lỗi khác; làm Word theo plan checklist; không hỏi.
- Đã sửa: rescue topics và rules (hôn nhân nuôi con dưới 36 tháng, BHXH lương hưu và đối tượng, hồ sơ khởi kiện, mua bán đất công chứng, lương tối thiểu, sa thải), planner (thực tập, sa thải, hòa giải có ngữ cảnh lao động), LaTeX cleanup trong câu trả lời, chặn trích dẫn số hiệu không có trong ngữ cảnh truy xuất, retry guard tạm thời.
- Trạng thái: vòng 8 H01 đạt; các câu còn lại chưa đạt đủ 6/6. Cổng 100% chưa đạt. Chưa commit.
- Word v13 (2026-11-17): output/VietLex_20261102_academic_standardized_v13_fields_20261117.docx. Render 95 trang PASS; visual review chưa duyệt; verify format FAIL do lỗi có sẵn (logo 5.56×3.25 cm, header/footer GVHD/SVTH không khớp bìa, thứ tự phần đầu).

## 2026-11-17 — yêu cầu v16 (đã trả lời grill Q1–Q8; còn lại làm theo ý bạn)
- Đầu vào giữ nguyên: output/VietLex_20261102_academic_standardized_v13_fields_20261117.docx. Đầu ra mới là file riêng, không ghi đè.
- Hình = mỗi trang hoặc popup của web VietLex là một hình, ảnh thật chụp từ app đang chạy (APP_ENV=test, Supabase/Qdrant/Mongo thật), chụp bằng click từ trang chủ/đăng nhập, không che dữ liệu.
- Sơ đồ phân rã màn hình và sơ đồ luồng chính cho VietLex; chia nhiều ảnh nếu nhiều trang.
- UML: class/ERD OO 1 sơ đồ; use case, sequence, activity, state mỗi loại 3 sơ đồ nếu áp dụng; loại không áp dụng ghi lý do.
- Bảng: toàn bộ kiểu đen, không nền xanh ở hàng đầu.
- Lịch làm việc: 15 tuần, bắt đầu 01/08/2026; ghi là kế hoạch dự kiến.
- Khung: chỉ trang bìa; khoảng cách tới chữ đều 4 cạnh; không sát mép giấy bên trái.
- Logo bìa 4,5 cm (sai lệch có chủ đích so với profile 3,59 cm; ghi rõ). Bỏ ảnh web 5,56×3,25 cm trên bìa.
- Ảnh tuân quy tắc tỷ lệ AGENTS. Lời văn theo wordassistant skill và signs-of-ai-writing; NOT RUN/BLOCKED khi chưa làm.
- Hoàn thiện: Word COM field update, render PDF, PNG 150 DPI, xem từng trang; check_course_essay_readiness.py; báo cáo ba gate riêng.

## 2026-11-17 — lượt sửa LỊCH (theo yêu cầu người dùng)
- LỊCH LÀM VIỆC: kế hoạch dự kiến 15 tuần (01/08/2026–13/11/2026). Bản v13 có bảng sáu dòng trống và đoạn "khung dự kiến" đặt trước tiêu đề; đã thay bằng bảng đầy đủ. Nguồn: docs/evaluation/CURRENT_STATUS.md (P0–P3) và docs/PROJECT_CONTEXT.md. Bản v16: output/VietLex_20261102_v16_lich_20261117.docx.
- Đối chiếu Git (chỉ nội bộ): nhánh hiện tại feat/vietlex-ui-features-20261115; 332 commit trong 01/08–13/11 (cộng 2 commit ngày 02/09 trên origin/copilot); trước 01/08: 43 commit (13/07–26/07); sau 13/11: 4 commit ngày 16/11. Tuần 12–13 không có commit.
- Còn mở: số liệu Golden-50 và Ragas trong kế hoạch chỉ là kế hoạch; cần tệp bằng chứng trước khi báo cáo số.
- Kết quả lượt LỊCH (17/11): bản giao output/VietLex_20261102_v16_lich_final_20261117.docx, Word render 96 trang (qa/v16-20261117/render-final/). LỊCH trang 8–9, TÓM TẮT trang 10, không trang trắng.
- Còn mở: mục lục phần đầu (NHIỆM VỤ … LỊCH LÀM VIỆC) trong bản render không hiện số trang; cần kiểm trước khi giao. Readiness FAIL (project.json còn trỏ bản v12).
