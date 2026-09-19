# Công báo: nghiệm thu tìm nguồn và đọc PDF — 19/09/2026

Runtime `533547f` đã push và deploy. Vercel build log xác nhận đúng SHA; production canonical trả giao diện hai nguồn và API mới.

## Thay đổi

Tìm trực tiếp trên Cổng văn bản Chính phủ và Công báo; Brave vẫn opt-in. Adapter dùng endpoint công khai được trang Công báo gọi, HTTPS xác minh, tối đa 2 MB/phản hồi, không theo redirect. Kết quả Công báo mở trang chi tiết rồi đọc PDF trên đúng CDN đã allowlist. Metadata thiếu toàn văn không được coi là evidence. Federation giữ lỗi từng nguồn và danh tính provider cả khi tất cả nguồn lỗi.

## Kết quả thực chạy

- Full provider-free suite: **1.310 passed, 4 skipped, 30 warnings**, 331,98 giây. Bốn bài live opt-in RAG/reranker/report/Vertex không chạy trong suite này.
- 10 truy vấn HTTP thật: thử việc, dữ liệu cá nhân, đấu thầu, thuế tài nguyên, hàng không, dự trữ quốc gia, điện lực, bảo hiểm y tế, nhập khẩu, tín dụng. Cả 10 có kết quả; đây là query ngắn, không phải 10 câu trả lời pháp lý hoặc chứng minh ngoài corpus.
- Kế hoạch thật về Luật 91/2025/QH15: 5 bước có lần lượt 5/2/1/3/5 kết quả. Production HTTP 200 trong 35,063 giây, provider `chinhphu_and_congbao`; `complete` nghĩa các bước có kết quả, không có nghĩa nghiên cứu đầy đủ.
- Production đọc trang đầu PDF Luật 91/2025/QH15: HTTP 200 trong 8,265 giây, `pdf_text`, `readable`, **1.727 ký tự**; không OCR, không generation. Nội dung có tên luật và Điều 1.
- Chrome thật local và production ở 1440×1050/390×844: không tràn ngang, không pageerror. [Ảnh production mobile](discovery-mobile.png).

## Phản biện và việc chưa đạt

Thêm nguồn thật giải quyết một phần phụ thuộc vào một website, nhưng không chứng minh coverage. Với “thử việc”, hai kết quả đầu là quy trình kiểm định và đóng tàu; Bộ luật Lao động đứng thứ ba. “Tín dụng” cũng có kết quả đầu về tiền sử dụng đất. Không coi 10/10 có kết quả là 10/10 đúng đủ. Cần đánh giá xếp hạng theo câu hỏi cụ thể và toàn văn.

Ngày hiệu lực API Công báo có thể null; không tự xác nhận luật hiện hành. Chỉ đọc một trang PDF trong nghiệm thu này. Chưa kiểm chứng toàn bộ attachment, mọi chủ đề, toàn bộ corpus hoặc pháp lý từng kết luận. Full-text nội bộ và registry hiệu lực toàn corpus vẫn chưa hoàn tất. Logfire vẫn bị 401 token không hợp lệ; không sửa credentials trong thay đổi này.

## Lệnh và bằng chứng

- `.venv\Scripts\python.exe -m pytest tests/services/test_congbao_search.py -q`: RED 5 lỗi thiếu adapter trước implementation; GREEN sau sửa.
- Focused search/reader/routes: 67 passed; hai kiểm tra bổ sung default wiring/SSRF cũng đạt trước full suite.
- `.venv\Scripts\python.exe -m pytest -q --junitxml=tmp/congbao-probe-20260919/full.xml`
- `.venv\Scripts\python.exe -m ruff check` trên 7 file Python thay đổi: passed; `git diff --check`: passed.
- `live_adapter.py`, `live_federation.py`, `production.py`, `browser.py`, `production_browser.py` trong thư mục raw local: HTTP/browser thật, không thay thế bằng test doubles.

[Summary](summary.json) và [manifest](manifest.json) lưu aggregate/hash. Raw response, cookie, workspace ID và log riêng không xuất bản. Unit tests có test doubles để thử nhánh lỗi; không được dùng làm chứng cứ live.

## So sánh thêm trên 10 câu gốc, cùng query

[Aggregate](identical-ten-summary.json): giữ nguyên kế hoạch query đã lưu ngày 12/09, không dùng URL/đáp án để tạo query. Mỗi cổng chạy 5 query/câu, 10 câu; không generation/OCR. Cổng Chính phủ tìm đúng URL mốc **10/10**; Công báo tìm đúng số hiệu mốc **0/10**. Cả hai có thể trả tài liệu cùng chủ đề; có kết quả không đồng nghĩa tìm đúng quy định mới. Bộ này có bằng chứng vắng văn bản mốc trong SQLite/Supabase/Qdrant ngày 12/09, **không quét lại corpus ngày 19/09**. Không suy ra Công báo không chứa văn bản chỉ từ search miss.

Vì vậy giữ cả hai nguồn, không thay portal hoặc tuyên bố khắc phục hoàn toàn thiếu dữ liệu. Kết quả cũng chưa chấm câu trả lời pháp lý. Script thật: `.venv\Scripts\python.exe tmp/congbao-probe-20260919/compare_ten.py`; raw local, hash trong aggregate. Discovery service không thay đổi trong lượt so sánh; cuối lượt chỉ sửa JS/template giải thích trạng thái.

## Sửa UX tiếp theo

Chrome production trước sửa phát hiện badge `results_found` lộ mã kỹ thuật. Đổi trạng thái sang tiếng Việt, phân biệt không tìm thấy với lỗi nguồn và giải thích nguồn trùng đã hiển thị trước. Cập nhật hướng dẫn đọc Công báo. Chrome local với dữ liệu Mongo thật sau sửa: desktop/mobile không tràn ngang/pageerror, badge tiếng Việt. `node --check`, 5 Node form tests và 24 route tests passed. Đây là kiểm chứng bổ sung UI, không ghi lại full suite 1.310 tests thành bằng chứng sau thay đổi JS/template.
