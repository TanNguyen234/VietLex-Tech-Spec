# Bản review lịch sử ngày 2026-09-08

> Tài liệu lịch sử, không dùng để xác định chức năng hiện tại hoặc quyền triển khai. Một số mục dưới đây đã được triển khai sau review. Nguồn trạng thái duy nhất: [FEATURE_STATUS](../FEATURE_STATUS.md). Yêu cầu cải tiến hiện tại của chủ dự án thay thế phạm vi đóng gói cũ; ranh giới commit/provider/migration trong AGENTS.md vẫn áp dụng.

Ngày rà soát: 2026-09-08. Căn cứ: code/tests hiện tại, config và CURRENT_ARCHITECTURE; không dùng nhận xét marketing làm bằng chứng runtime. **Không triển khai các mục F01–F10 trước khi chủ dự án duyệt phạm vi cụ thể.** Đợt hiện tại chỉ đóng gói và bảo vệ các chức năng đã có.

## Đã có, không cần làm lại

Hỏi đáp có evidence; tra cứu số hiệu/tiêu đề và toàn văn online qua Supabase; hồ sơ theo owner; ghim nguồn/ghi chú; phân tích nguồn đã chọn, so sánh và bảng nghĩa vụ; kế hoạch nghiên cứu 5 bước và tìm metadata tại cổng Chính phủ; upload PDF/DOCX/TXT và rà soát điều khoản được chọn; tài khoản/email verification/reset, export/xóa dữ liệu cá nhân; admin request/context/telemetry/đánh giá và Evaluation Lab đọc artifact.

Đây là các implementation đã có. Full suite provider-free đạt 1084 passed, 2 skipped; không đồng nghĩa mọi luồng đã được nghiệm thu end-to-end trên production.

## Danh sách xin duyệt

| ID | Chức năng | Hiện có và phần chưa hoàn thiện | Điều kiện hoàn tất nếu được duyệt |
|---|---|---|---|
| F01 | Kiểm chứng claim/citation theo ngữ nghĩa | `research_presenter.py` dùng `citation_anchor_only`; có quote/anchor/link nhưng chưa chứng minh nguồn ủng hộ nội dung claim hay phát hiện mâu thuẫn pháp lý. | Bộ ca có nhãn support/contradiction/insufficient, span nguồn chính xác, coverage/skip reason; không gọi điểm lexical là đúng pháp luật. |
| F02 | Hiệu lực và độ mới pháp luật | Trạng thái hiệu lực còn UNKNOWN/chưa xác minh; chưa có chuỗi sửa đổi, thay thế, bãi bỏ và phiên bản áp dụng tại thời điểm hỏi. | Nguồn chính thức, ngày hiệu lực/kiểm tra và quan hệ văn bản có provenance; unknown khi không đủ dữ liệu. |
| F03 | Nghiên cứu nhiều nguồn | Lane web mới tìm metadata ở `vanban.chinhphu.vn`; chưa tích hợp đầy đủ trusted legal sources/general web, đọc toàn văn web và chống trùng/xung đột giữa các lane. | Duyệt từng nguồn, điều khoản sử dụng/lưu trữ, ngân sách gọi dịch vụ và bộ test nguồn không có kết quả/lỗi/không hỗ trợ claim. |
| F04 | Deep Research hoàn chỉnh | Có kế hoạch 5 bước sửa được và kết quả từng bước; chưa phải quy trình tự tổng hợp báo cáo pháp lý toàn diện rồi verify từng khẳng định. | Báo cáo có issue/analysis/exceptions/checklist/sources, liên kết nguồn từng claim, trạng thái bước và xử lý thiếu evidence. |
| F05 | OCR và xử lý hồ sơ lớn | Có text PDF/DOCX/TXT; không OCR scan. Hiện giới hạn 20 tài liệu, 100 phần, 250k ký tự/file, budget BSON 12 MB có thể chặn sớm hơn. | OCR và lưu trữ lớn phải có thiết kế riêng, giới hạn tài nguyên/retention/privacy, benchmark trích xuất. Không tự mở rộng trong đợt đóng gói. |
| F06 | Review toàn hợp đồng / redline | Review hiện chỉ các điều khoản và căn cứ được chọn; tối đa 10 điều khoản, ngân sách context hiện có. `evidence_linked` không phải kết luận đúng luật. Chưa có redline hai bản hợp đồng hoặc rà soát toàn hồ sơ hàng loạt. | Duyệt taxonomy finding, matching phiên bản, provenance, khả năng chỉ rõ bỏ sót và corpus kiểm thử. |
| F07 | Legal timeline | Chưa có workflow dựng timeline sự kiện/hạn nghĩa vụ và dẫn nguồn từng mốc. | Duyệt định nghĩa sự kiện, ngày chưa chắc chắn, múi giờ và đối chiếu nguồn; không tự suy ra thời hạn pháp lý thiếu căn cứ. |
| F08 | So sánh nhiều model | So sánh evidence hiện có không phải chạy cùng câu hỏi qua nhiều model. | Duyệt provider, ngân sách, inputs giống nhau và cách hiển thị disagreement; phải xin phép live/paid benchmark. |
| F09 | Admin accounting/vận hành sâu | Có token input/output/thinking/total và coverage theo request/tác vụ/model. Chưa có billing thực đối soát, toàn bộ embedding/reranker/upstream retry usage, giao diện quota còn lại hay dashboard các lần bị chặn tại admission. | Chỉ dùng usage/cost thực đo hoặc estimate được gắn nhãn; chuẩn hóa số đếm và quyền xem; không gán usage mất cho model cuối. |
| F10 | Chất lượng/corpus và kiểm thử rộng | Online v3 đã audit 14.962 văn bản, không phải 518.255 văn bản. Golden-50 có phạm vi hẹp; retrieval tốt trên subset không chứng minh câu trả lời đúng luật hay sẵn sàng production. | Duyệt dataset/A-B và ngân sách; ingestion/migration/deletion vector cần quyền riêng cho đúng thao tác. |

Nguồn code chính: `app/services/research_presenter.py`, `research_analysis.py`, `deep_research.py`, `official_web_search.py`, `workspace_documents.py`, `admin_observability.py`; `app/account_database.py`; `docs/CURRENT_ARCHITECTURE.md`.

## Các việc vận hành cần xác minh trước khi mời reviewer rộng rãi

Các mục dưới thuộc đóng gói/bảo vệ demo, không phải mở rộng F01–F10:

- **WAF/bot protection/rate rules tại Vercel: CHƯA XÁC MINH.** Dashboard browser không truy cập được trong phiên này. Không có bằng chứng rule đã bật; quota ứng dụng không thay thế chống DDoS/chi phí request ở edge.
- **Rollout bản code mới: cần kiểm tra sau push.** Smoke trước thay đổi: `/`, `/healthz`, `/readyz`, `/evaluation-lab` đều HTTP 200; đó chưa phải bằng chứng admission mới đã chạy online.
- **Đăng ký → email xác minh → login bằng tài khoản reviewer thật: NOT RUN.** Phụ thuộc cấu hình SMTP hiện có. Không chia sẻ tài khoản admin cho reviewer.
- **Chat/upload/research bằng tài khoản thật và quota Mongo đa instance: NOT RUN online.** Các test dùng double ở ranh giới DB/provider; không tự chạy provider trả phí.
- **Docker build/runtime, restore backup, tải lớn và pentest: NOT RUN.** Docker CLI không có trong môi trường hiện tại. Wheel/ASGI được kiểm tra trong môi trường runtime sạch riêng.

Có thể duyệt từng ID Fxx kèm phạm vi/ngân sách. Mặc định toàn bộ F01–F10 vẫn CHỜ DUYỆT.
