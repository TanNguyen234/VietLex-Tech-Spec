# VietLex — gói sửa lỗi giao diện và tính năng tra cứu (2026-11-15)

Trạng thái: đã sửa trong cây làm việc, CHƯA commit, CHƯA push.

Log pytest hợp lệ: `pytest-full-after-feature-pack-clean.log` (một tiến trình duy nhất). File `pytest-full-after-feature-pack.log` KHÔNG dùng: hai tiến trình pytest đã ghi chung file nên nội dung hỏng; đã dừng cả hai.

## Lỗi giao diện đã sửa

| ID | Triệu chứng (đã tái hiện trên 127.0.0.1:8101) | Nguyên nhân | Sửa |
|---|---|---|---|
| UI-1 | Khách mở `/settings` hoặc `/admin` trên trình duyệt thấy JSON thô `{"detail":"Authentication required."}` (401) | `require_user` / `require_admin` raise 401 cho mọi client | `app/main.py` `_browser_auth_redirect`: 401 + GET + `Sec-Fetch-Dest: document` → 303 `/login`. fetch/API vẫn nhận JSON 401 |
| UI-2 | Mở `/sessions` trực tiếp thấy đoạn HTML thanh bên không có layout | Route trả fragment cho thanh bên | `app/api/routes.py` `list_sessions`: `Sec-Fetch-Dest: document` → 303 `/` |
| UI-3 | Lớp nền bằng chứng (`#drawer-backdrop`) chặn nút "+ Mới" khi drawer mở; bấm nền không đóng | Thiếu `data-action` cho nền | `app/templates/index.html`: thêm `data-action="close-drawer"` (dùng handler `close-drawer` có sẵn trong `vietlex.js`) |
| UI-4 | Script inline bị CSP chặn (`script-src 'self'`) | Viết JS inline trong template | JS chuyển sang `app/static/js/legal-search.js`; không còn `onclick` |

## Tính năng mới

| ID | Tính năng | File chính |
|---|---|---|
| F-1 | Lọc theo lĩnh vực (chuỗi con, không phân biệt hoa thường) trên `/search`, áp dụng khi tìm theo số hiệu/tiêu đề | `app/services/legal_browser.py` (`SearchFilters.sector`, `LegalSearchResult.legal_sectors`), `app/api/legal_routes.py` (lọc sau khi có kết quả), `app/templates/legal_search.html` |
| F-2 | Ghi chú tuổi văn bản dưới mỗi kết quả: luôn nói "chưa xác minh hiệu lực"; cũ hơn 10 năm có cảnh báo đối chiếu | `app/services/source_currency.py` `currency_note` |
| F-3 | Nút "Sao chép trích dẫn": tên văn bản, số hiệu, cơ quan, ngày ban hành, nguồn | `app/services/source_currency.py` `format_citation`; `legal-search.js` |
| F-4 | "Tìm gần đây" (8 mục, localStorage trên máy người dùng, không lưu server) | `legal-search.js` |

Giới hạn đã biết: lọc lĩnh vực chạy sau khi backend trả kết quả nên một trang có thể ít hơn 20 mục; không áp dụng cho tìm theo nội dung (`scope=body`). Không có nguồn trạng thái hiệu lực đã xác minh trong corpus, nên VietLex không khẳng định hiệu lực.

## Kiểm thử

- Test mới: `tests/services/test_vietlex_feature_pack.py` (10 test), `tests/test_vietlex_browser_navigation.py` (4 test).
- Sửa thêm sau bước kiểm tra: `currency_note` đọc được năm từ ngày không ISO (ví dụ `20/11/2019`). Ngày có nhưng không đọc được năm ghi "Ngày ban hành không đọc được", không còn ghi nhầm "Chưa có ngày ban hành". Test: `test_currency_note_reads_year_from_non_iso_date_and_flags_unreadable_date`.
- Focused sau sửa: 44 passed (`test_vietlex_feature_pack.py`, `test_vietlex_browser_navigation.py`, `test_legal_routes.py`, `test_body_search.py`).
- Full suite (một tiến trình, `pytest tests -q -rfE`, 573 s, log `pytest-full-after-feature-pack-clean.log`): **8 failed, 2259 passed, 6 skipped**.
  - Cả 8 test fail đều xảy ra trên HEAD sạch (copy `git archive HEAD` app/tests ở thư mục tạm, cùng venv, cùng thông báo lỗi, không kèm `.env`). Không do gói VietLex; không có test mới nào fail.
  - `tests/evaluation/test_provenance.py::test_provider_catalog_preserves_current_fallback_orders`: catalog model nhà cung cấp lệch kỳ vọng (ví dụ Gemini 2.5 vs 2.0).
  - `tests/test_api_routes.py::test_chat_mandatory_guards_bypass_unchecked_cache_and_measure_real_latency`: đã biết.
  - `tests/test_guardrail_route_state.py::test_legacy_shadow_request_is_enforced_without_cache[rejected-output]` và `[error-output]`: mock bị await ngoài kỳ vọng.
  - `tests/test_rag_pipeline.py` (4 test): `RetrievalPipelineError: Legal retrieval failed` hoặc evidence rỗng.
- Trình duyệt (Playwright headed, `127.0.0.1:8101`, server khởi động lại sau sửa):
  - UI-3 (2026-11-15): hỏi "Thời gian thử việc tối đa là bao lâu?" → bấm nguồn "45/2019/QH14, Điều 25" → drawer `open`, `aria-hidden=false`, nền `hidden=false` phủ toàn màn hình, `data-action=close-drawer`. Bấm nền → drawer `aria-hidden=true`, `inert=true`, nền `hidden=true`, focus trả về một nút. Sau đó bấm "+ Mới" chạy bình thường. Console error: 0.
  - Từ phiên trước: lọc lĩnh vực đúng (1 kết quả), ghi chú tuổi hiển thị, sao chép trả "Đã sao chép", tìm gần đây lưu và hiển thị, `/settings` → `/login`, `/sessions` → `/`.
- Đã biết nhưng KHÔNG thuộc phạm vi thay đổi: `tests/test_api_routes.py::test_chat_mandatory_guards_bypass_unchecked_cache_and_measure_real_latency` FAIL trên HEAD sạch (đã kiểm bằng git worktree tạm, đã xóa). Không do gói này.

## Lỗi còn mở (chưa sửa)

- Câu trả lời fallback của guard hiển thị hai lần (Q13, Q20).
- `/documents/333670` trả trang 560 KB (hiệu năng).
- Câu trả lời thường bị guard chặn hoặc không có căn cứ hiện hành (xem `rubric-results.md`): vấn đề corpus/retrieval, không sửa bằng UI.
- Thân câu trả lời (câu hỏi thử việc, 2026-11-15) có cảnh báo nguồn lặp lại hai lần và trích lại đoạn gốc "Đoạn mở đầu không đánh số": lỗi định dạng/prompt, chưa sửa.
- Môi trường: ổ C: còn khoảng 0,88 GB trống (trên tổng 97 GB). Một lần `git worktree add` vào thư mục tạm trên C: lỗi `No space left on device`. Cần dọn dung lượng trước khi ghi file lớn hoặc chạy test/worktree.
