# Nghiệm thu nguồn ngoài corpus — 12/09/2026

## Kết quả thực chạy

Tìm đúng URL văn bản neo **13/13**: bộ 10 câu ban đầu **10/10**, thêm 3 câu tự nhiên giữ riêng **3/3**. Trong 10 câu ban đầu, nhóm câu tự nhiên tăng từ **0/5 lên 5/5**; nhóm có số hiệu giữ **5/5**. Đây là kiểm tra discovery theo URL chính xác, không phải tỷ lệ trả lời đúng luật.

Đọc được hai trang đầu **12/13 ở lần đầu**. Hàng hải gặp `source_transport_error`; thử lại riêng thành công, nên **13/13 có nội dung sau retry**. Giữ nguyên `maritime.json` lỗi và `maritime-retry.json` thành công. Không gộp retry để che tỷ lệ lỗi lần đầu.

| Chủ đề | Tìm đúng neo | Đọc lần đầu | Phạm vi trang đọc / tổng |
|---|---|---|---|
| Hàng không | Có | Có | 2/4 |
| Phụ cấp y tế | Có | Có | 2/6 |
| Đấu thầu | Có | Có | 2/23 |
| Thuế tài nguyên | Có | Có | 2/3 |
| Tín dụng | Có | Có | 2/4 |
| Hàng hải | Có | Lỗi mạng; retry có | 2/17 sau retry |
| Bảo hiểm nông nghiệp | Có | Có | 2/24 |
| Nhập khẩu | Có | Có | 2/39 |
| Dự trữ | Có | Có | 2/40 |
| Điện lực | Có | Có | 2/18 |
| Chữ ký điện tử — holdout | Có | Có | 2/57 |
| Tài nguyên viễn thông — holdout | Có | Có | 2/98 |
| Phân loại phim — holdout | Có | Có | 2/24 |

`cases.json` lưu nguyên câu hỏi và neo chấm. Neo chỉ dùng chấm kết quả, không đưa vào planner của câu tự nhiên. Model được quan sát: `google_vertex_ai / gemini-3.5-flash`; tìm kiếm vẫn qua cổng Chính phủ. Mỗi JSON giữ kế hoạch, từng bước, nguồn, thời điểm, hash PDF và hash nội dung/OCR.

Mười văn bản ban đầu đã được kiểm tra vắng trong local SQLite, Supabase và toàn bộ 141.798 điểm Qdrant: [bằng chứng gốc](../../../verification/online-discovery-20260912/REPORT.md). Kiểm kê vắng trong corpus cho ba holdout: **NOT RUN**. Không suy rộng rằng mọi dữ liệu thiếu đều được tìm thấy.

## Workflow API thật

API local chạy source mới, MongoDB thật và Vertex thật; không mock, không đổi `.env`, không bỏ CSRF/auth. DNS máy không phân giải MongoDB SRV; launcher kiểm thử dùng DNS HTTPS `1.1.1.1`, trust store hệ thống. Các lần khởi động thất bại được ghi trong nhật ký local. Không gọi đây là nghiệm thu workflow trên production.

Tạo hồ sơ công khai thử nghiệm → đề xuất từ khóa → tìm cổng → OCR hai trang Nghị định 349/2026/NĐ-CP → ghim 2.200 ký tự nguyên văn kết quả đọc → hỏi chỉ trên căn cứ đó → đọc lại hồ sơ. Các endpoint hoàn tất thành công. Kết quả `status=ok`, `evidence_scope=1`, phân biệt **03 ngày làm việc** với **10 ngày**, đúng hai con số trong đoạn nguồn đã chọn. Các response công khai được lưu trong thư mục `api/`.

**Lỗi còn quan sát được:** OCR ghi “thu thập báo cáo” ở một chỗ mà lượt OCR khác ghi “thu thập báo giá”. Chưa chấm OCR theo ảnh gốc toàn bộ văn bản; không tuyên bố OCR chính xác tuyệt đối. Hai neo ngày trả lời được kiểm tra theo đoạn đã đọc; không chứng nhận hiệu lực hiện hành. Độ đúng/đủ pháp lý của câu trả lời cho cả 13 câu rộng: **NOT RUN**. Không dùng title hit, số trang hoặc HTTP 200 thay cho đánh giá đó.

## Sửa nguyên nhân

- Câu tự nhiên được chuyển thành năm cụm từ tiêu đề có thể chỉnh sửa. Model không được tự đưa số hiệu nhớ/đoán; lỗi planner có fallback hiển thị rõ. Khi tắt tính năng, không gọi model.
- Theo tệp PDF đính kèm đã allowlist, không lấy trang danh mục làm điều khoản. Giới hạn 20 MB, 200 trang/tệp, tối đa 5 trang/lượt, 20.000 ký tự/lượt; có đọc tiếp và thử một trang khi quá giới hạn.
- Tách trang loại tham chiếu annotations khỏi **bản OCR**, giữ PDF gốc và hash. Trước sửa, bản “hai trang” đấu thầu vẫn hơn 11 MB; bản tách nội dung khoảng 934 KB. Không xác minh chữ ký số.
- PDF có metadata trùng được thử parser tolerant và công khai cờ khôi phục. Không tự xác nhận hiệu lực; ngày nguồn ghi được giữ riêng với trạng thái `unverified`.
- Chat có đường chuyển câu hỏi sang hồ sơ tìm nguồn. Kết quả có nút đọc bản gốc, OCR, đọc tiếp và ghim trích đoạn chính xác; backend kiểm tra quote trong nội dung đã lưu, theo chủ sở hữu hồ sơ.

## Kiểm thử và phiên bản

- RED đã quan sát cho planner, PDF/metadata/OCR, route và chuyển câu hỏi; riêng feature-disabled test thất bại trước sửa rồi qua.
- `.venv/Scripts/python.exe -m pytest tests/services/test_official_query_planner.py tests/services/test_official_document_reader.py tests/test_trusted_source_routes.py tests/test_workspace_routes.py tests/test_public_templates.py -q -p no:cacheprovider`: **48 passed**.
- `.venv/Scripts/python.exe -m pytest tests --ignore=tests/integration --ignore=tests/visual -q -p no:cacheprovider --basetemp=tmp/online-evidence-20260912/full --junitxml=tmp/online-evidence-20260912/full.xml`: **1278 passed, 30 warnings**, 524,22 giây. Đây là suite provider-free, gồm test doubles; không phải live benchmark.
- Sau sửa cuối CSS/hướng dẫn PDF: `.venv/Scripts/python.exe -m pytest tests/test_public_templates.py tests/test_workspace_routes.py -q -p no:cacheprovider`: **34 passed**. Backend không thay đổi.
- `node --check app/static/js/research-workspace.js`; `node --test tests/product_forms.test.cjs`: **5 passed**. Ruff trên các file Python thay đổi: passed.
- Live: `.venv/Scripts/python.exe tmp/online-evidence-20260912/run_acceptance.py`, `api_workflow.py`, `final_checks.py`. Script thực chạy lưu kèm; không dùng test doubles.
- Commits: `a1d7e10` backend/tests; `f221672` workflow/UI; `e977ddb` sửa UI qua ảnh thật. Đã push origin/main. `manifest.json` ghi trạng thái đầu lượt live khi source chưa commit; `source_hashes` giữ từng file Python. CSS/template sửa sau đó không thay đổi service đang đánh giá. Hash artifact xuất bản dùng LF trong `publication.json`.

Production smoke bản `f221672`: health/readiness/JS trả 200 và có reader mới; xem `production-smoke.json`. Workflow có ghi dữ liệu trên production mới: **NOT RUN** (quota tài khoản demo đã hết ở lượt trước). Logfire token 401 còn tồn tại; không thay credentials khi chưa có quyền cho lớp thay đổi đó.

Bản cuối `e977ddb` được deploy và promote bằng Vercel CLI 59.14.0, deployment `dpl_CxC1ZogUPSBpQBcLt8CEw3zJnvUJ`. Kiểm tra CSS thực phục vụ lưu ở `production-final.json`. Các lệnh remote: `git push origin main`; `vercel deploy --prod --skip-domain --yes --scope foxys-projects-5fe642e0`; `vercel promote dpl_CxC1ZogUPSBpQBcLt8CEw3zJnvUJ --yes --scope foxys-projects-5fe642e0`. Bundle lấy từ Git archive của commit runtime, không lấy toàn working tree. Không migration, không reingestion, không đổi credentials.

Các file runtime/tests thay đổi (`git diff --name-only 31c95b8..e977ddb`):

```text
app/api/trusted_source_routes.py
app/api/workspace_routes.py
app/services/deep_research.py
app/services/official_document_reader.py
app/services/official_query_planner.py
app/services/reviewer_demo.py
app/services/trusted_source_reader.py
app/static/css/vietlex-enhancements.css
app/static/js/research-workspace.js
app/templates/chat_message.html
app/templates/research_tools.html
app/templates/research_workspace.html
app/templates/research_workspaces.html
tests/services/test_official_document_reader.py
tests/services/test_official_query_planner.py
tests/test_public_templates.py
tests/test_trusted_source_routes.py
tests/test_workspace_routes.py
```

Tài liệu bổ sung: README, FEATURE_STATUS, kế hoạch, ảnh UI thực và thư mục run này. Các thay đổi có sẵn ngoài phạm vi trong `.agents`, `.codex`, build và artifact cũ được giữ nguyên, không stage.

## Phản biện report và việc hữu ích tiếp theo

Thêm field hiệu lực hoặc thêm nhà cung cấp search không tự tạo độ tin cậy. Bản này chứng minh có thể lấy căn cứ ngoài chỉ mục mà không thay topology hay tự chứng nhận luật. Nó chưa giải quyết recall toàn web: provider mặc định vẫn chỉ tìm một cổng; Brave đa nguồn chưa được bật/nghiệm thu. Không quảng bá thành tìm toàn bộ pháp luật Việt Nam.

Ưu tiên tiếp theo là **bảng thiếu căn cứ trong hồ sơ**: từng câu hỏi cần điều khoản nào, đã đọc trang nào, còn phụ lục nào, ai xác minh. Đo bằng tỷ lệ câu hỏi có trích đoạn được reviewer chấp nhận, không bằng số nguồn.

Tiếp đến là **đối chiếu OCR cạnh ảnh trang** và trạng thái “đã kiểm tra bản gốc” do người dùng xác nhận; giữ cả bản OCR ban đầu, sửa của reviewer và provenance. Lỗi “báo cáo/báo giá” là ca hồi quy thực tế để nghiệm thu chức năng này.

Cuối cùng là **tìm trong nguồn ngoài corpus đã ghim** theo Điều/Khoản, kèm coverage của toàn PDF và phụ lục. Nó giảm bước copy/paste mà không cần mở thêm model. Chỉ tự động trả lời câu hỏi rộng khi có đủ căn cứ và lịch sử sửa đổi đã kiểm chứng; còn thiếu thì trình bày khoảng trống cụ thể.
