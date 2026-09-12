# VietLex — trạng thái chức năng

Cập nhật ngày 2026-09-12; production hiện tại 93ec75d đã triển khai sau sửa runtime, UX và packaging Evaluation Lab. Đây là nguồn trạng thái chức năng hiện tại; tài liệu review có ngày là lịch sử. Primary workflow: người nghiên cứu pháp lý/compliance tìm văn bản → tổ chức căn cứ → rà soát tài liệu → xử lý findings → xuất báo cáo.

“Có” nghĩa là có implementation, không đồng nghĩa production verified. Bản af8c9f5 đã triển khai và có 71 request live: xem [báo cáo ngày 12/09](docs/verification/live-api-af8c9f5-20260912/LIVE_REPORT.md). Bảng dưới ghi trạng thái kiểm chứng của đợt 11/09 trước triển khai; không thay thế kết quả live mới. Bản sửa a1d3986 đã triển khai: xem [kết quả sau sửa](docs/verification/product-fixes-20260912.md); chưa nghiệm thu pháp lý. Test bên dưới là điểm kiểm tra trong repository, không phải chứng nhận đúng luật. Corpus bên thứ ba và giới hạn 14.962 document ID của v3 không thay đổi.

| Chức năng | Trạng thái / UI / API | Test đối chiếu | Production verified trong đợt này | Giới hạn |
|---|---|---|---|---|
| Hiệu lực / sửa đổi / as-of | Có sự kiện reviewer trong hồ sơ; thêm amended và partially_effective | `tests/services/test_legal_effect.py`, `tests/test_legal_effect_routes.py` | NOT RUN | Không phải registry toàn corpus; không tự xác nhận nguồn, không chứng nhận lịch sử đầy đủ; unknown khi thiếu sự kiện |
| Search số hiệu/tiêu đề + filters | Có UI/API loại văn bản, cơ quan, ngày ban hành, sort ngày; lọc trước LIMIT | `tests/services/test_legal_browser.py`, `tests/test_legal_routes.py` | NOT RUN | Tối đa 20 kết quả UI; chưa body full-text, article search toàn corpus, highlight match hay sort semantic relevance |
| Document-scoped Q&A | Có từ reader; không gọi corpus retrieval hoặc semantic cache; rỗng thì từ chối | `tests/services/test_document_scope.py`, `tests/test_public_web_routes.py` | NOT RUN | Lexical trong văn bản, tối đa 3 chunks/720 context tokens; không phải full-document review; chưa một selector chung đủ 4 scope |
| Reader actions | Ask, copy text/citation/permalink, pin nguyên điều khoản + note | `tests/test_legal_routes.py` | NOT RUN | Pin tối đa 4.000 ký tự, không cắt ngầm; chưa highlight cá nhân/compare phiên bản luật/related provisions |
| Workspace | 7 mục Tổng quan/Nguồn/Tài liệu/Phân tích/Rà soát/Báo cáo/Hoạt động | `tests/test_workspace_routes.py`, `tests/product_forms.test.cjs` | NOT RUN | Cần JavaScript để thu gọn các panel; lựa chọn nguồn giữ trong DOM; giới hạn retention hiện có |
| Phân tích nguồn / nghĩa vụ / so sánh | Có, theo evidence được chọn | `tests/test_workspace_routes.py` | NOT RUN | Cần provider; không tự mở rộng căn cứ |
| Upload / OCR | Có PDF/DOCX/TXT, OCR tùy chọn | `tests/services/test_workspace_ocr.py`, `tests/test_workspace_routes.py` | NOT RUN | OCR tối đa 5 trang; provider-dependent, không phải lưu trữ hồ sơ lớn |
| Full review / findings | Có review theo lô và trạng thái open/accepted/dismissed/resolved, ghi chú, nội dung sửa, version CAS | `tests/test_full_document_review_routes.py`, `tests/test_finding_management.py` | NOT RUN | Quyết định giữ riêng finding gốc; tối đa 20 sự kiện/finding; chưa tự đối chiếu resolved qua tài liệu v2 |
| Redline | Có diff xác định giữa hai bản text | `tests/services/test_document_redline.py`, `tests/test_document_redline_routes.py` | NOT RUN | Không phải Word Track Changes; không suy ra tính hợp pháp của sửa đổi |
| Timeline / claim verification | Có trong công cụ theo context | `tests/test_legal_timeline_routes.py`, `tests/test_claim_verification_routes.py` | NOT RUN | Selected evidence; quote khớp không tự chứng minh diễn giải đúng |
| Báo cáo editable / version / export | Có editor Markdown, lưu bản mới, MD/DOCX, in/lưu PDF qua browser | `tests/test_report_deliverables.py`, `tests/test_research_report_routes.py` | NOT RUN | DOCX cơ bản, URL dạng text; PDF không có renderer server; 50 analysis gần nhất; bản sửa luôn unverified; chưa mọi citation link tới đúng khoản |
| Official portal discovery | Có WebForms GET/POST cổng Chính phủ, lỗi theo bước | `tests/services/test_official_web_search.py`, `tests/services/test_deep_research.py` | NOT RUN | Metadata/snippet discovery; adapter ID không phải model AI |
| Federated official discovery | Có adapter Brave + portal, dedupe URL, allowlist, partial-error; mặc định tắt | `tests/services/test_federated_official_search.py` | NOT RUN | Cần `OFFICIAL_BRAVE_SEARCH_ENABLED` và `BRAVE_SEARCH_API_KEY`; chưa multi-domain full-page evidence extraction/ranking benchmark |
| Trusted URL reader | Có đọc và ghim trích đoạn server lưu | `tests/services/test_trusted_source_reader.py`, `tests/test_trusted_source_routes.py` | NOT RUN | Allowlist fetch riêng, tối đa 3 URL HTML; không tương đương discovery-domain coverage |
| Model comparison / technical UI | API model comparison chỉ admin; UI theo role; safety checkbox đã bỏ | `tests/test_model_comparison_routes.py`, `tests/test_public_templates.py` | NOT RUN | Model experiment vẫn trong workspace admin, chưa chuyển thành trang lab riêng; chính sách guardrail do config quyết định |
| Admin corpus | Có hàng đợi thiếu ngày ban hành/URL, phân trang 50 metadata | `tests/test_product_quality.py`, `tests/services/test_legal_browser.py` | NOT RUN | Read-only; chưa lifecycle registry, sửa metadata, ingestion jobs, reindex/rollback, counters healthy toàn corpus |
| Feedback triage → regression draft | Có category, assignee, state, history, CAS và JSON draft admin-only | `tests/test_product_quality.py` | NOT RUN | Assignee là nhãn giao việc; expected answer để trống, cần người adjudicate; không tự thêm Golden case hoặc chạy regression gate |

## Phản biện report và quyết định

- Đồng ý ưu tiên source reliability và workflow hơn thêm model. Tuy nhiên các field `effective_from/effective_to` không tạo ra dữ liệu đáng tin: phải có nguồn, người kiểm chứng, phạm vi và thời điểm. Không gán ngày ban hành thành ngày hiệu lực.
- “Amended” và “partially effective” không đồng nghĩa repealed. Bản sửa phân biệt chúng trong lịch sử reviewer; một sự kiện sửa đổi riêng lẻ chưa chứng minh văn bản còn hiệu lực.
- Full-text search cần index trên body/article và benchmark với truy vấn thật. Quét vài candidate rồi gọi là full-text toàn corpus sẽ lặp lại chính UX contract sai mà report phê bình. Đợt này chưa thực thi migration/ingestion; đây vẫn là P0 còn thiếu.
- Nhiều search provider mở rộng discovery nhưng không đảm bảo coverage, toàn văn hay hiệu lực. Brave opt-in giữ whitelist và partial failures; không đổi tên snippet thành evidence đã xác minh. Protocol tham chiếu: [Brave Web Search API](https://api-dashboard.search.brave.com/api-reference/web/search/get).
- Findings và bản report sửa tay phải giữ provenance, tránh biến thao tác “resolved” hoặc “save” thành chứng nhận đúng luật. Regression draft cũng cần đáp án do người xác lập.
- Model comparison chỉ nên là thí nghiệm quản trị. An toàn không phải checkbox để end-user tắt policy; cache cũng không được bỏ qua policy của server.

## Việc còn lại để hoàn tất report

1. Corpus lifecycle registry có provenance/review, quan hệ version/amendment và as-of dùng được trong search/chat; nhập dữ liệu chỉ sau quy trình kiểm chứng.
2. Chỉ mục body/article riêng, highlight và relevance/date pagination; kế hoạch build/readback/rollback và benchmark cùng bộ query trên local/online trước khi bật.
3. Findings đối chiếu v2 có clause identity ổn định, evidence link trong board/export; DOCX citation hyperlink và PDF server nếu yêu cầu xuất tự động.
4. Admin ingestion/index job state, chỉnh metadata có audit, role editor/reviewer, cost budget và feedback adjudication/regression gate.
5. Nghiệm thu live hai tài khoản, OCR, provider search, report export trong Word/browser và chất lượng pháp lý. Không coi test double hoặc preview synthetic là bằng chứng live.

## Phát hiện live ngày 12/09/2026

- Evaluation Lab có lỗi HTTP 200 nhưng thiếu artifact trên a1d3986. Commit 93ec75d sửa quy tắc ignore thư mục và đường dẫn; production đã hiển thị run canonical. Không coi HTTP 200 đơn thuần là kiểm chứng chức năng.

- Scoped chat af8c9f5 trả 500 vì nhánh lexical phụ thuộc PyVi, không có trong gói online. Bản a1d3986 dùng fast_terms cho riêng scope; production trả 200 và đúng neo Điều 25 Khoản 2 trong câu thử.
- Selected analysis, comparison, obligations bị JSON cắt vì MAX_TOKENS. Bản a1d3986 dùng MINIMAL thinking, ngân sách mặc định 4096 và giữ trạng thái truncated_output; cả ba endpoint production đã trả 200 status ok sau sửa.
- Corpus có document ID không đồng nghĩa có mọi điều khoản: truy xuất trực tiếp 16 record đã lập chỉ mục của document 333670 không có Điều 25. Candidate pool của câu hỏi thử việc cũng không chứa văn bản này. Chưa thay đổi index hay ranking.
- Official research vẫn có no_results/timeout sau sửa query; chưa đạt. Logfire xuất trace bị 401 là lỗi giám sát riêng, chưa sửa credentials.
- Review đã bổ sung chỉ dẫn rõ nguồn chưa xác minh hiệu lực; prompt không phải bằng chứng bảo đảm mọi kết luận pháp lý đúng.
