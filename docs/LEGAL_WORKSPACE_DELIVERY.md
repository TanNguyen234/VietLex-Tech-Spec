# VietLex — bàn giao hồ sơ nghiên cứu và UX người dùng

Ngày: 2026-09-05. Phân loại: runtime/product, trình bày evaluation chỉ đọc, tài liệu và kiểm thử. Không ingestion/migration.

Yêu cầu mới nhất được ưu tiên: sản phẩm dành cho người dùng cuối; gom sửa trước, kiểm thử đúng phần bị ảnh hưởng, không chạy full suite. Báo cáo này là bằng chứng bàn giao, không phải chứng nhận production-ready.

## 1. Kiến trúc

Giữ FastAPI/Jinja và tài sản CSS/JavaScript cục bộ. Thêm lớp hồ sơ nghiên cứu, trình bày liên kết nhận định–bằng chứng, phân tích có cấu trúc và trang chất lượng đọc artifact. Phân tích bằng chứng gọi qua biên direct_llm hiện có, không lồng vào đường truy xuất chat.

**Không thay đổi hành vi truy xuất/đánh giá Vertex/Qdrant v3 đã có**: dense 1024d, sparse, phối hợp RRF+DBSF, giới hạn 3 chunks/720 context tokens và lựa chọn legacy vẫn giữ nguyên. Artifact lịch sử không được coi là kiểm chứng cho tính năng phân tích mới. Không thay đổi provider, model, ingestion hay chỉ mục.

## 2. Mô hình dữ liệu

- Collection research_workspaces: chủ sở hữu đăng nhập hoặc client ẩn danh, tiêu đề/mô tả, thời điểm tạo/cập nhật/hết hạn, bằng chứng ghim và lịch sử phân tích.
- Ghim từ lượt tương tác thuộc đúng chủ sở hữu; lưu nguồn hội thoại, mã nguồn, trích đoạn, dẫn chiếu và ghi chú. Giới hạn 100 bằng chứng; giữ tối đa 50 phân tích.
- Kết quả phân tích lưu snapshot bằng chứng để không mất dấu nguồn sau khi bỏ ghim. Thời hạn theo DATA_RETENTION_DAYS; không quảng cáo là lưu trữ pháp lý vĩnh viễn.
- Đăng nhập nhận lại dữ liệu ẩn danh đúng client. Export/xóa lịch sử/xóa tài khoản bao gồm hồ sơ.
- Log tương tác thêm retrieval_trace có whitelist; bản ghi cũ hiển thị trạng thái không có số liệu thay vì suy đoán.

## 3. Endpoint

- GET/POST /workspaces; GET/POST/DELETE /workspaces/{workspace_id}.
- GET /api/workspaces; POST /workspaces/{workspace_id}/evidence; DELETE /workspaces/{workspace_id}/evidence/{evidence_id}.
- POST /workspaces/{workspace_id}/analyses/selected, /compare, /obligations.
- GET /api/interactions/{trace_id}/retrieval; GET /evaluation-lab.
- GET /account chọn /login hoặc /settings theo phiên. Thu hồi phiên hiện tại trở về /account để không rơi vào trang 401.
- Các endpoint quản trị hiện có được đưa vào bộ lọc giao diện; không thêm quyền quản trị mới.

CSRF, xác thực, ràng buộc chủ sở hữu và rate limit vẫn áp dụng. Phân tích chỉ chấp nhận ID bằng chứng của hồ sơ; phạm vi quá lớn bị từ chối rõ ràng, không cắt ngầm hay tìm thêm nguồn.

## 4. Luồng UX và rà soát user/admin

| Khu vực | Kết quả rà soát và xử lý |
| --- | --- |
| Hỏi đáp/lịch sử | Giữ hỏi, thử lại, sao chép, feedback, mở nguồn; thêm lưu bằng chứng và liên kết nhận định. Nhãn tiếng Việt, không diễn giải liên kết thành độ đúng pháp luật. |
| Tra cứu/toàn văn | Giữ tìm số hiệu/tiêu đề và đọc nguyên văn. Nút hỏi về văn bản nói rõ chỉ điền sẵn câu hỏi, không hứa giới hạn truy xuất. |
| Hồ sơ | Tạo, đổi tên/mô tả, xóa, ghim/bỏ ghim, ghi chú khi ghim, mở hội thoại nguồn; empty state dẫn tới hành động thực. |
| Phân tích | Chọn bằng chứng, hai nhóm A/B, bảng so sánh và nghĩa vụ/quyền; lịch sử tải lại, bộ lọc, liên kết nguồn. Chặn gửi trùng, thông báo thiếu bằng chứng/lỗi, không reload để che mất kết quả. |
| Tài khoản | Điều hướng hợp lệ cả khi chưa đăng nhập; đăng ký/đăng nhập/khôi phục giữ form có CSRF; xác nhận trước xóa dữ liệu và sửa luồng tự thu hồi phiên. |
| Quản trị | Bộ lọc nhật ký/tài khoản, mở chi tiết lượt, thu hồi phiên/vô hiệu hóa có xác nhận; ẩn tự vô hiệu hóa. Bảo vệ admin cuối cùng vẫn ở máy chủ. |
| Tính trung thực | Guardrail chưa ghi nhận không còn hiển thị “bị chặn”. Bỏ bảng điểm Balanced-50 cũ khỏi dashboard, dẫn tới artifact hiện hành. Cấu hình provider không đồng nghĩa provider đang hoạt động. |
| Điều hướng/trợ giúp | Điều hướng chung, theme, quyền riêng tư và điều khoản; thông tin kỹ thuật nằm ở mục phụ/chi tiết. Admin không tải script chat và không khởi tạo các request chat không cần thiết. |

Rà soát chức năng là đối chiếu mã nguồn, hợp đồng và kiểm thử provider-free; không có tuyên bố rằng mọi thao tác đã được thử trên hệ thống production.

## 5. Tệp thay đổi và coverage review

Checkpoint OCR trước khi tạo báo cáo: 78 tệp, 70 reviewable, 8 excluded.
Đã review 50/70 tệp reviewable (71.43% toàn working tree); 20 JSON artifact có sẵn của người dùng được bỏ qua có chủ đích, không thuộc nhiệm vụ. 4 tệp tài liệu nhiệm vụ được đọc riêng vì OCR loại Markdown. 4 report.md có sẵn cũng không thuộc nhiệm vụ. Không có finding blocking còn mở trong phạm vi đã review.

Mỗi dòng dưới đây là một mục reviewed ở checkpoint (đường dẫn tương đối repository):

```text
modified: .dockerignore
modified: .vercelignore
modified: Dockerfile
modified: app/account_database.py
modified: app/api/account_routes.py
modified: app/api/routes.py
modified: app/database.py
modified: app/main.py
modified: app/static/css/vietlex-enhancements.css
modified: app/static/js/vietlex.js
modified: app/templates/account_form.html
modified: app/templates/admin.html
modified: app/templates/admin_details.html
modified: app/templates/admin_users.html
modified: app/templates/chat_history_messages.html
modified: app/templates/chat_message.html
modified: app/templates/index.html
modified: app/templates/legal_document.html
modified: app/templates/legal_search.html
modified: app/templates/privacy.html
modified: app/templates/settings.html
modified: app/templates/terms.html
modified: tests/test_account_database.py
modified: tests/test_admin_dashboard.py
modified: tests/test_api_routes.py
modified: tests/test_database.py
modified: tests/test_deployment_contract.py
modified: tests/test_public_templates.py
modified: vercel.json
added: app/api/evaluation_lab_routes.py
added: app/api/workspace_routes.py
added: app/research_database.py
added: app/services/evaluation_lab.py
added: app/services/research_analysis.py
added: app/services/research_presenter.py
added: app/static/js/product.js
added: app/static/js/research-workspace.js
added: app/templates/evaluation_lab.html
added: app/templates/product_nav.html
added: app/templates/research_workspace.html
added: app/templates/research_workspaces.html
added: tests/product_forms.test.cjs
added: tests/services/test_evaluation_lab.py
added: tests/services/test_research_analysis.py
added: tests/services/test_research_presenter.py
added: tests/test_evaluation_lab_routes.py
added: tests/test_product_navigation.py
added: tests/test_research_database.py
added: tests/test_retrieval_inspector_routes.py
added: tests/test_workspace_routes.py
modified, documentation reviewed: README.md
modified, documentation reviewed: docs/CURRENT_ARCHITECTURE.md
modified, documentation reviewed: docs/DOCUMENTATION_INDEX.md
added, documentation reviewed: docs/superpowers/plans/2026-09-04-legal-intelligence-workspace.md
```

Báo cáo này là tệp bàn giao bổ sung sau checkpoint. Review dùng OCR Delegation Mode để chọn tệp/quy tắc; Codex kiểm tra mã nguồn và diff, không có LLM endpoint phụ. CRG không khả dụng nên dùng rg và Git.

## 6. Kiểm thử bổ sung

Các test mới phủ research_database, workspace routes, retrieval inspector, evaluation lab routes/services, schema/phạm vi phân tích, trình bày nhận định. Mở rộng test account/database/API/deployment/templates.

test_product_navigation.py kiểm tra điều hướng khách/đã đăng nhập, thu hồi phiên, trạng thái guardrail chưa ghi nhận, escaping và ẩn tự vô hiệu hóa.
product_forms.test.cjs dùng node:test với DOM/fetch giả lập, không mạng: storage bị tắt, hủy xác nhận, lọc GET, CSRF/gửi trùng/lỗi 429, chuyển trang.

## 7. Lệnh xác minh chính xác

PowerShell; PYTHONDONTWRITEBYTECODE=1. Không dùng --run-live.

Vòng chọn lọc ban đầu:

```powershell
python -m pytest tests/test_account_database.py tests/test_account_routes.py tests/test_admin_dashboard.py tests/test_admin_operations.py tests/test_product_navigation.py tests/test_workspace_routes.py tests/test_research_database.py tests/test_retrieval_inspector_routes.py tests/test_evaluation_lab_routes.py tests/services/test_research_analysis.py tests/services/test_research_presenter.py tests/services/test_evaluation_lab.py tests/test_public_templates.py tests/test_api_routes.py tests/test_database.py tests/test_legal_routes.py tests/test_deployment_contract.py -q -p no:cacheprovider
```

Sau sửa lỗi, chỉ chạy lại 7 tệp liên quan. Đã kiểm tra thư mục basetemp chưa tồn tại, không tái sử dụng/xóa thư mục tạm của người dùng:

```powershell
$taskTemp = 'C:/Users/VI TINH THANH AN/.codex/visualizations/2026/09/04/01a06d02-a6b5-7342-9eb7-11a2fc0aee1c/pytest-product-20260905-a'
if (Test-Path -LiteralPath $taskTemp) { throw 'Refusing to reuse an existing pytest base directory' }
python -m pytest tests/test_account_routes.py tests/test_product_navigation.py tests/test_workspace_routes.py tests/test_public_templates.py tests/test_admin_dashboard.py tests/services/test_evaluation_lab.py tests/test_api_routes.py -q -p no:cacheprovider --basetemp="$taskTemp"
node --test tests/product_forms.test.cjs
node --check app/static/js/product.js
node --check app/static/js/research-workspace.js
node --check app/static/js/vietlex.js
python -m ruff check app tests --no-cache
python -m ruff check app/api/account_routes.py tests/test_product_navigation.py tests/test_workspace_routes.py --no-cache
git -c safe.directory=D:/Download/ProfessionalLegalRAG -c core.whitespace=cr-at-eol diff --check
git -c safe.directory=D:/Download/ProfessionalLegalRAG rev-parse HEAD
```

OCR dùng safe.directory chỉ trong tiến trình, không ghi Git global config:

```powershell
$env:GIT_CONFIG_COUNT='1'
$env:GIT_CONFIG_KEY_0='safe.directory'
$env:GIT_CONFIG_VALUE_0='D:/Download/ProfessionalLegalRAG'
ocr delegate preview --format json
ocr delegate rule --format json <các đường dẫn reviewed tại mục 5>
ocr delegate rule --format json tests/product_forms.test.cjs
```

Danh sách đối số ở lệnh rule thứ hai là toàn bộ 49 tệp nhiệm vụ tại checkpoint trước khi thêm product_forms.test.cjs; tệp này được lấy rule riêng. Bản rule gồm correctness/security/async/resource/error handling và XSS.

## 8. Kết quả

- Vòng đầu: **102 passed, 2 failed, 5 errors, 5 warnings / 123.61s**. Hai failure là nhãn hồ sơ/bằng chứng chưa đồng bộ. Năm setup error là WinError 5 với thư mục pytest tạm của tài khoản khác.
- Vòng chạy lại chọn lọc: **54 passed / 67.71s**. Bao gồm tất cả failure/error trên và test mới cho thu hồi phiên. Tổng 110 ca Python được bao phủ qua các lần chạy có chọn lọc, không phải một lần full-suite.
- JavaScript: **5 passed, 0 failed / 411.7ms**; ba script kiểm tra cú pháp thành công.
- Ruff: thành công; diff --check với nhận diện CRLF của Windows: thành công. Lệnh thử với core.autocrlf=false trước đó báo whitespace giả do CRLF; không đổi dòng toàn repository để che cảnh báo.
- Có 5 cảnh báo datetime.utcnow() hiện hữu trong database.py; chưa mở rộng phạm vi để refactor.
- Unit/route/integration cục bộ dùng doubles và socket guard; không chạy live provider.
- Full suite: **NOT RUN** theo yêu cầu mới nhất. Lần thử full-suite trước chỉ đạo này đã bị dừng, không có kết quả full-suite hợp lệ.
- Build/deploy/container runtime: **NOT RUN**; test hợp đồng đóng gói artifact đã qua, không tương đương deploy thành công.
- Browser hậu chỉnh sửa: **NOT VERIFIED** do webview attach timeout. Quan sát browser cô lập ở giai đoạn trước không được nâng thành chứng cứ cho UI cuối cùng. Không tạo screenshot giả.

## 9. Giới hạn, Git và tác động ngoài

HEAD: 645a7309a4a932cd82531ee06a76e90584060b10; working tree dirty, chưa commit/push. Bốn thư mục evaluation/runs/retrieval-v3-* có sẵn được giữ nguyên; không sửa artifact/checkpoint người dùng.

Không deploy, không gọi provider trả phí/live, không migration/reingestion, không thay credentials/.env, không xóa dữ liệu người dùng. Các HTTP server thử nghiệm loopback của nhiệm vụ đã dừng.

Chất lượng câu trả lời pháp luật và phân tích mới chưa được benchmark live; baseline của dự án không được tự nâng thành đạt. Qdrant v3 không được mô tả là có toàn bộ corpus. Liên kết nhận định chỉ là neo dẫn chiếu, không phải semantic entailment. Phân tích có giới hạn 10 bằng chứng, giới hạn context hiện hành và semaphore process-local hai request; đây không phải quota phân tán.

Artifact lab chỉ đọc lần đánh giá đã ghim; N/A không đổi thành 0. Không suy đoán expected evidence không có trong artifact. Email thật/MongoDB thật/end-to-end production chưa chạy.

## 10. Chủ động hoãn

- Ghim trực tiếp đoạn bôi đen từ toàn văn và notebook tổng quát: chưa có hợp đồng neo cấu trúc đủ chắc; hiện ghim bằng chứng truy xuất, ghi chú lúc ghim.
- Phân tích tự giới hạn toàn văn từ nút hỏi: hoãn; nút chỉ prefill, còn luồng selected-only đã có ràng buộc riêng.
- So sánh nhiều experiment: chưa có join artifact tương thích được xác minh; không ghép số liệu suy đoán.
- Tự xác nhận hiệu lực pháp luật hoặc promotion bằng chứng: giữ human-only.
- Kiểm chứng live và phát hành: cần quyền và một đợt xác minh vận hành riêng.

### Bài học tái sử dụng (bản nháp redacted)

Giữ nguyên đường truy xuất khi thêm năng lực nghiên cứu; ràng buộc ID và snapshot nguồn ở máy chủ. UI an toàn phải phân biệt “chưa ghi nhận” với “không an toàn”, và điều hướng sau thu hồi phiên phải xử lý mất xác thực. Kiểm thử biểu mẫu bằng node:test bắt được gửi trùng/CSRF mà không cần provider.

Không ghi vào D:/Download/Codex-Self-Reflection vì ngoài writable roots hiện tại; bài học được giữ ở đây thay vì ghi ngoài quyền. Skills ảnh hưởng thực tế: VietLex Lean/Ponytail giới hạn phạm vi và vòng kiểm thử; frontend-design/HTMX-Jinja cho luồng tiếng Việt; FastAPI Clean Architecture cho boundary; OCR Delegation Mode cho review. Chi tiết kế hoạch triển khai nằm trong docs/superpowers/plans/2026-09-04-legal-intelligence-workspace.md.
