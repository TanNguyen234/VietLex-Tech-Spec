# Báo cáo live API — 12/09/2026

Bản triển khai: af8c9f5bd2770b192f410453f36680f4395a7d71. Production: https://vietlex-legal-rag.vercel.app. Đây là báo cáo tiến độ, chưa phải xác nhận toàn bộ chức năng đạt.

Đã ghi nhận 71 HTTP request thật. Không dùng mock. Không sửa source/config production trong lượt kiểm tra này.

## Kết quả chức năng

| Chức năng | Kết quả thực tế |
|---|---|
| Login | 303, phiên đăng nhập thật; truy cập admin 200 |
| Search ngày | Khoảng 2019 có văn bản 333670; khoảng 2020 loại văn bản; ngày sai 422 |
| Workspace / pin | Tạo, sửa, đọc lại đủ ba nguồn Điều 24–26 |
| Scoped chat | Hai lần 500; chưa có nguyên nhân log |
| Chat toàn corpus | 200 nhưng truy xuất nguồn 1963/2005, bỏ lỡ Điều 25; không đạt câu hỏi test |
| Selected evidence / obligations / compare | 502 invalid_structured_response; không đạt |
| Upload TXT | Upload ba điều thành công, tải lại khớp byte; đầu vào quá lớn trước đó bị 422 |
| OCR | 200, Gemini 3.5 Flash đọc đúng nội dung Điều 26 với thay đổi xuống dòng; đầu vào là PDF raster dựng từ nguyên văn corpus, không phải scan chính thức |
| Selected/full review | 200 status ok; nội dung có nhận định hiện hành chưa được căn cứ hiệu lực hỗ trợ |
| Finding | Lưu ghi chú, đọc lại đúng; revision cũ bị 409 |
| Claim verification | 200 status ok; chưa phải kiểm chứng pháp lý độc lập |
| Timeline | 200; không có ngày trong ba nguồn, trả 0 events và unverified |
| Redline | 200 với hai trích đoạn thật; không phải hai phiên bản hợp đồng |
| Report | Generate ok; lưu phiên bản; MD và DOCX có ghi chú; DOCX giải nén và đọc XML được |
| Official research | HTTP 200 nhưng status failed: 4 no_results, 1 ReadTimeout |
| Trusted URL | HTTP 200 đọc trang danh mục cổng Chính phủ; chưa chứng minh trích căn cứ cụ thể |
| Admin | Corpus, feedback, evaluations, system, providers, usage trả 200; chưa audit mọi nội dung |
| Feedback loop | Downvote trên lượt chat lỗi retrieval, triage investigating, xuất regression draft 200 |
| Evaluation | Chạy deterministic endpoint trên lượt chat thật, HTTP 200; không chạy Ragas |

## Phần còn lại

Model comparison, legal-effect promotion, PDF print UI, DOCX upload, các nhánh lỗi/quyền truy cập đầy đủ, thao tác quản trị tài khoản và sửa các lỗi phát hiện chưa hoàn tất. Không tạo dữ liệu hiệu lực giả. Không xóa tài khoản hay dữ liệu có sẵn. Chưa thể kết luận sản phẩm đạt yêu cầu toàn diện.

## Giới hạn và tác động

Đã tạo hồ sơ test fddc8168-4194-43f9-919b-e75d6465a963, nguồn ghim, tài liệu công khai, analyses, phiên bản report và feedback của lượt test trên tài khoản được cung cấp. Không thay đổi cấu hình quota/credentials production. Tổng chi phí provider chưa xác định; HTTP count không bằng số provider calls.

Đọc log Vercel bổ sung bị automatic approval review từ chối do hết hạn mức Codex; không thử bypass. Chưa sửa lỗi scoped chat hay structured output, chưa redeploy bản sửa.

## Evidence

requests.jsonl giữ method/path/time/status/latency/hash; observations.jsonl ghi nhận kiểm tra nội dung. Response artifacts có thể chứa dữ liệu quản trị: giữ cục bộ, chưa commit/push. Cookie được che; credentials/cookies nằm trong tmp gitignored. SHA response là trước khi che cookie. INTERIM_REPORT.md là ảnh chụp trước đăng nhập, được thay thế về trạng thái bởi báo cáo này.

Các runner thực thi: login_live.py, workflow_authenticated.py, phase2.py đến phase7.py, official_live.py, deliverables_live.py, chat_live.py, feedback_live.py, ocr_live.py trong tmp/live-api-af8c9f5. Lệnh: `.venv/Scripts/python.exe -X utf8 tmp/live-api-af8c9f5/<runner>.py`.

## Nhật ký request

| Nhãn | HTTP | Giây |
|---|---:|---:|
| home | 200 | 14.725 |
| health | 200 | 0.591 |
| readiness | 200 | 0.539 |
| search | 200 | 3.476 |
| workspaces | 200 | 0.546 |
| evaluation_lab | 200 | 0.376 |
| deployed_product_js | 200 | 0.328 |
| reader | 200 | 1.921 |
| workspace_create | 401 | 1.256 |
| search_date_match_public | 200 | 2.125 |
| search_date_exclude_public | 200 | 1.11 |
| search_invalid_date_public | 422 | 0.347 |
| document_missing_public | 404 | 0.508 |
| scoped_page_public | 200 | 1.132 |
| admin_anonymous_public | 401 | 0.346 |
| account_anonymous_public | 303 | 0.332 |
| login_public | 200 | 0.33 |
| login_session_start_1 | 200 | 16.116 |
| login_authenticated_1 | 303 | 2.501 |
| workspace_create_authenticated_1 | 303 | 3.601 |
| workspace_readback | 200 | 1.195 |
| pin_24 | 200 | 4.175 |
| pin_25 | 200 | 3.63 |
| pin_26 | 200 | 3.553 |
| evidence_readback | 200 | 1.143 |
| workspace_update | 303 | 2.753 |
| workspace_options | 200 | 1.532 |
| search_filters | 200 | 2.07 |
| session_create | 200 | 2.564 |
| scoped_chat_page | 200 | 1.801 |
| document_scoped_chat | 500 | 3.28 |
| upload_public_law_txt | 422 | 5.347 |
| admin_role_probe | 200 | 3.325 |
| analysis_selected_live | 502 | 9.98 |
| upload_public_three_articles_txt | 200 | 4.545 |
| original_download_three_articles | 200 | 1.383 |
| obligations_live | 502 | 9.11 |
| comparison_live | 502 | 10.336 |
| full_review_plan_live | 200 | 4.083 |
| official_research_plan_live | 200 | 2.936 |
| admin_corpus_live | 200 | 1.721 |
| admin_feedback_live | 200 | 1.174 |
| admin_evaluations_live | 200 | 0.997 |
| admin_system_live | 200 | 1.167 |
| admin_providers_live | 200 | 0.962 |
| admin_usage_live | 200 | 1.208 |
| timeline_live | 200 | 3.097 |
| selected_clause_review_live | 200 | 11.382 |
| full_review_live | 200 | 11.432 |
| claims_live | 200 | 5.716 |
| official_research_run_live | 200 | 47.422 |
| report_live | 200 | 25.317 |
| finding_board_live | 200 | 2.053 |
| finding_note_update_live | 303 | 3.197 |
| finding_stale_revision_live | 409 | 2.949 |
| finding_readback_live | 200 | 1.369 |
| report_editor_live | 200 | 1.391 |
| report_save_version_live | 303 | 3.288 |
| report_export_md_live | 200 | 1.38 |
| report_export_docx_live | 200 | 1.403 |
| full_review_coverage_readback | 200 | 2.885 |
| corpus_chat_live | 200 | 8.318 |
| upload_single_article_redline | 200 | 5.015 |
| redline_public_excerpts_live | 200 | 3.267 |
| trusted_official_portal_live | 200 | 6.171 |
| chat_feedback_live | 200 | 3.042 |
| feedback_triage_live | 303 | 2.958 |
| feedback_regression_draft_live | 200 | 1.205 |
| evaluation_actual_chat_live | 200 | 2.674 |
| scoped_chat_retry_live | 500 | 4.135 |
| ocr_public_article_live | 200 | 8.524 |
