# Nghiệm thu workflow thực tế — 2026-09-12

## Kết quả và phạm vi

Đợt này hoàn thiện việc sử dụng căn cứ đã tìm được ngoài corpus: mở lại bản đọc, xem phạm vi trang đã trích xuất, chọn/giữ căn cứ, ghi chú cần đối chiếu, xem findings và sửa/xuất báo cáo. Không thay đổi index, model, ranking hoặc hiệu lực pháp luật. Không tuyên bố đã hoàn tất mọi P0 trong report gốc hay hệ thống không thể còn lỗi.

- Thư viện nhóm theo URL và hash PDF, không gộp hai phiên bản khác hash. Trang có text được đếm một lần; trang trắng không tính. Đây là độ phủ trích xuất, không phải xác suất đúng luật.
- GET bản đọc đã lưu kiểm tra chủ sở hữu và TTL, không gọi reader/provider. Thư viện dựa trên 50 analysis còn giữ, không phải kho lưu trữ vĩnh viễn.
- Đối chiếu `to_check/text_checked/follow_up` lưu riêng quote gốc, tối đa 10 sự kiện. Ghi đè từ revision cũ trả 409. `text_checked` không xác nhận hiệu lực.
- Bộ lọc không bỏ lựa chọn ẩn; ID lựa chọn giữ qua tải lại trong sessionStorage. Không lưu quote vào browser storage.
- Report preview escape HTML, chỉ link citation ID thuộc snapshot; hỗ trợ heading/list/bold cơ bản. Lưu tạo phiên bản mới; MD/DOCX/print dùng phiên bản đã lưu. Findings có bộ lọc và nguồn snapshot để đối chiếu.

## Bằng chứng tách biệt

| Loại | Kết quả | Giới hạn |
|---|---|---|
| Python provider-free | 1283 passed, 30 warnings, 425.41 giây (lần cuối sau sửa CSS) | Loại integration và visual; doubles chỉ thuộc tests, không chứng minh live model |
| JavaScript | 5 passed | Product form tests; không thay thế Chrome |
| Chrome + local API + MongoDB thật | Giữ lựa chọn qua reload; lưu review; stale write 409; mở nguồn và đưa đoạn bôi chọn vào form | Không gọi OCR/model mới khi mở bản đọc |
| Báo cáo thật | Lưu phiên bản mới, giữ 3 nguồn; MD/DOCX trả 200; DOCX có word/document.xml | Không chạy Microsoft Word; không phải Track Changes |
| PDF Chrome | Kiểm tra text trích từ PDF, nội dung báo cáo không lẫn form sửa | Browser print, không phải PDF API server |
| Mobile 390 × 844 / desktop 1440 × 1050 | Các view trong JSON không tràn ngang, không pageerror | Chỉ các đường dẫn/thao tác được ghi; không chứng minh mọi tương tác admin |

Kịch bản thực chạy: `browser_check.py`, `delivery_check.py`; kết quả JSON đi kèm. Chúng dùng Chrome thật, không intercept network hoặc thay DOM để dựng kết quả. Thao tác Range chỉ chọn 150 ký tự có thật trong bản đọc. Hai script ghi vào thư mục chứa script: **sao chép sang thư mục tmp mới trước khi tái chạy**, không ghi đè bộ bằng chứng này. Session/workspace nằm trong file ignored, không được công bố; người chạy lại cần phiên hợp lệ và hồ sơ test thật tương đương.

Server local chạy app thật với `SERVERLESS_ONLINE_ONLY=true`, truststore cho CA hệ thống và DNS-over-HTTPS để khắc phục resolver máy host. Không đổi `.env`, không giả lập MongoDB. Lượt này cập nhật review trên hồ sơ thử nguồn công khai và tạo phiên bản báo cáo thử; không thay dữ liệu corpus. Những response có cookie và ảnh trang quản trị/tài khoản được giữ ngoài Git.

API thật cũng kiểm tra truy cập ẩn danh: GET bản đọc trả **404**, không chứa dữ liệu đã lưu (`anonymous-reader.json`). `spacing-result.json` đo vị trí DOM thật sau sửa CSS: hai nhãn không chồng nhau trên 390 px.

Deliverable thực từ nguồn luật công khai: [Markdown](report-export.md), [DOCX](report-export.docx), [PDF in qua Chrome](report-print.pdf). Các file giữ nhãn chưa xác minh hiệu lực; không phải ví dụ được dựng lại.

## Lệnh

```powershell
.venv/Scripts/python.exe -m pytest tests --ignore=tests/integration --ignore=tests/visual -q -p no:cacheprovider --basetemp=tmp/workflow-usability-20260912/pytest-final --junitxml=tmp/workflow-usability-20260912/full-final.xml
node --test tests/product_forms.test.cjs
node --check app/static/js/research-workspace.js
node --check app/static/js/workflow-controls.js
.venv/Scripts/python.exe tmp/workflow-usability-20260912/browser_check.py
.venv/Scripts/python.exe tmp/workflow-usability-20260912/delivery_check.py
git -c safe.directory=D:/Download/ProfessionalLegalRAG diff --check -- app tests
```

`manifest.json` ghi Git SHA trước commit, dirty proof và SHA-256 từng file runtime/test thay đổi (kể cả file mới). `full-final.log` và `full-final-process.json` giữ output/exit code của lần cuối; `full.log`/`full-process.json` giữ lượt trước sửa khoảng cách, không chỉ số test viết tay. Sau commit, release receipt ghi SHA nguồn và triển khai riêng.

## Lỗi phát hiện và đã sửa

- Template bản đọc serialize datetime vào JSON gây lỗi; chỉ truyền các field JSON cần thiết, có regression test với datetime thật.
- CSS `display:grid` làm phần tử có `hidden` vẫn hiện: thêm quy tắc ẩn rõ ràng, Chrome xác nhận bộ lọc hoạt động.
- CSP không cho string `wait_for_function` của harness: chuyển harness sang locator assertion, không nới CSP của app.
- Form report đang sửa có thể chặn chuyển trang sau khi lưu: đánh dấu save thành công trước redirect; Chrome đã tạo phiên bản thật.

## Giới hạn còn tồn tại

- OCR nguồn 349/2026 có cụm “báo cáo/báo giá” cần đối chiếu PDF gốc; UI giữ nguyên quote và ghi chú, không sửa ngầm. Hiệu lực vẫn unverified.
- Discovery 13/13 neo của đợt trước không chứng minh trả lời đầy đủ 13 câu rộng. Không chạy lại benchmark model/discovery trong đợt UI này; xem [kết quả thật trước đó](../../evaluation/runs/official-online-20260912T140633Z/REPORT.md).
- Logfire export trả 401 vì token hiện tại; chưa sửa credentials. Không coi lỗi giám sát này là chặn nội dung hay kết luận pháp lý.
- Production có quota tài khoản; không bypass để tạo kết quả. Provider-free tests và local live API không có nghĩa mọi model endpoint production đã được gọi lại.
- Full-text/article index toàn corpus, registry hiệu lực toàn corpus, ingestion/rollback admin và đối chiếu findings qua v2 vẫn là việc còn lại ở [FEATURE_STATUS](../../../FEATURE_STATUS.md). Không chạy migration hay chứng nhận nguồn tự động để làm bảng trông đầy đủ.
- 30 deprecation warnings vẫn tồn tại; không gọi kết quả này là zero-warning hoặc zero-bug.

## Git và triển khai

Runtime gồm `0889251` (workflow và regression tests) và `6011dc3` (khoảng cách UI). Tài liệu/ảnh/bằng chứng được commit riêng. File cấu hình agent, artifacts cũ, build và thay đổi không thuộc task được giữ ngoài các commit. Không đưa cookie hoặc credentials vào Git. Kết quả promote và smoke được ghi trong `release.json` / `production-result.json`.

Production sau promote: **8/8 GET trả 200**, trong đó hồ sơ có thư viện nguồn, bản đọc có payload lưu và report có preview; ba trang riêng tư trả `Cache-Control: no-store`. **3/3 static asset khớp byte gói deploy**, đồng thời nội dung khớp Git blob sau chuẩn hóa CRLF. Smoke không gọi AI và không mutation; không thay cho benchmark câu trả lời.

Lần đối chiếu hash đầu thất bại vì Git archive trên Windows xuất CRLF trong khi Git blob lưu LF. Đã giữ `production-initial-byte-check.json`, kiểm tra trực tiếp số byte và so cả ba file với gói archive thực: khớp hoàn toàn. Không sửa runtime để làm test pass. `production-result.json` ghi riêng hash byte phục vụ và hash Git blob.
