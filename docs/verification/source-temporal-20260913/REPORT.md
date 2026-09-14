# Metadata nguồn và kiểm chứng theo thời điểm

Đối chiếu kết quả ngày 14/09/2026. Hai commit đã push: `59de08f` giữ metadata nguồn; `168ef58` bỏ import retrieval khỏi CLI help. Bản `168ef58` đã Vercel READY và promote thành công: `dpl_3ixYGDVEPdi9c4uUL3SVEpGgfVVA`.

## Thay đổi và nguyên nhân

Ngày hiệu lực nguồn công bố đã có trong bản đọc/ghim nhưng bị bỏ khỏi prompt. Ngày ban hành cũng bị mất tại bước ghim. Đã giữ ngày ban hành qua pin/snapshot và truyền whitelist source_url, retrieved_at, issued_date, reported_effective_from, legal_effect_status vào prompt phân tích, báo cáo, nghĩa vụ, so sánh và rà soát. Metadata là dữ liệu chưa chứng nhận, tính vào ngân sách ngữ cảnh; không chuyển thành hiệu lực đã xác minh.

A/B cùng câu hỏi và cùng trích đoạn hàng không: trước sửa model báo thiếu ngày hiệu lực; sau sửa nêu được 01/01/2027 và phần chưa xác minh. Baseline đã từ chối kết luận khi thiếu căn cứ, không có bằng chứng hallucination trong cặp thử này. Thay đổi sửa mất thông tin, không phải chứng nhận đúng luật. Các JSON raw lưu cục bộ giữ nguyên input, prompt và output; manifest công bố hash.

## Production thật

- GET hồ sơ 200; POST ghim 200; POST phân tích nguồn đã chọn 200.
- Snapshot giữ issued_date=10-09-2026, reported_effective_from=01-01-2027, legal_effect_status=unverified.
- Provider google_vertex_ai / gemini-3.5-flash, provider_status=success, câu trả lời insufficient_evidence; nêu ngày hiệu lực tương lai so với câu hỏi 13/09/2026 và giới hạn chuyển tiếp/sửa đổi/bãi bỏ.
- Dùng phiên và CSRF thật, không mock hay tắt quota. Đã thêm một trích đoạn công khai và một analysis vào hồ sơ test hiện có. Raw response giữ cục bộ, hash request nằm trong manifest; không đưa cookie vào report.

## Kiểm thử và lỗi giữ lại

RED metadata và pin mất issued_date đã quan sát. 45 focused pass trước lượt rộng đầu. Lượt rộng đầu: 1 failed / 1289 passed / 30 warnings, 638.01 giây; test CLI --help timeout 15 giây. Chạy riêng đạt 7.52 giây. Source audit phát hiện import run_retrieval_eval chỉ để lấy DEFAULT_DATASET_PATH, kéo theo app.config. RED mới chứng minh help import cấu hình; sửa đọc cùng canonical current_evaluation.json bằng stdlib, giữ nguyên timeout/dataset.

Focused sau sửa CLI: **66 passed, 1 warning**. Review diff và Ruff pass. Full cuối: **1290 passed, 30 warnings, 354.58 giây**, exit 0. Full command nằm trong full-temporal-final-process.json. Integration/visual bị loại khỏi suite; unit doubles không phải bằng chứng provider thật. Không giấu lượt fail trước.

## Đánh giá 10 câu và giới hạn còn lại

[Xem 10 câu gọi model thật](../../evaluation/runs/source-temporal-ten-20260913T153643Z/REPORT.md): hai trích đoạn mỗi văn bản; 10/10 provider success và 10/10 insufficient_evidence. Năm trường hợp có ngày hiệu lực tương lai đều được nêu đúng theo dữ liệu đã cấp. Đây không phải fresh web search hoặc audit pháp lý toàn diện.

VBPL search endpoint đã thử qua web tool và HTTP trực tiếp, đều 403; chưa thêm provider giả. Corpus full-text vẫn thiếu index SQL; các probe body đã timeout 57014. Không sửa credentials/Logfire 401, không tạo registry hiệu lực giả, không đổi index hay provider. Không đánh dấu project zero-error.

Files runtime: app/services/research_analysis.py, app/api/trusted_source_routes.py, app/api/workspace_routes.py. CLI: run_eval_suite.py. Tests: tests/test_source_temporal_context.py, tests/services/test_research_analysis.py, tests/test_run_eval_suite.py. Manifest dùng hash Git blob cho source, hash byte thật cho artifact.

## Publication boundary

Raw response, model output, logs and diagnostic runners referenced above are retained locally; they are not published in this commit. The manifest records their hashes for local verification. Published evidence is limited to this curated report, aggregate results where present and public-source references. Production workspace identifiers and cookie values are excluded. This restricts public reproducibility; it does not turn summaries into raw evidence.
