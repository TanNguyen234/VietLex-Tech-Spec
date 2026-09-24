# VietLex — hậu kiểm sửa lỗi production, 24/09/2026

## Phạm vi và bản triển khai

Báo cáo này nối tiếp [kiểm toán ban đầu](../../audits/production-20260924T144859Z/REPORT.md) và các [phát hiện F01–F06](../../audits/production-20260924T144859Z/FINDINGS.md). Mã runtime cuối cùng là commit `5104921097be71b86bfe40aa99afbf74819ad2cc` trên `main`. Vercel deployment `388QGaYkXrvKKHUXTTocXWCo9QvB` được kiểm tra qua giao diện, có trạng thái **Ready / Latest / Production** và gắn `vietlex-legal-rag.vercel.app`. Các lượt kiểm tra trình duyệt bên dưới được thực hiện sau khi deployment này sẵn sàng, trên hồ sơ thử kiểm toán `deb03296-8210-4a31-b06f-8f737926b968` với [PDF Công báo chính thức](https://congbaocdn.chinhphu.vn/CongBaoCP/VanBan/2019/11/30232/29070-1-2019993-99445-2019-qh14.pdf).

| Mục | Thay đổi và bằng chứng sau triển khai | Giới hạn |
| --- | --- | --- |
| F01 — trang PDF | Thư viện nguồn phân biệt 12/94 trang đã đọc có chữ, 82 trang chưa đọc, 0 trang đã đọc nhưng chưa có chữ. | Chỉ một PDF 94 trang; không chứng nhận OCR toàn văn. |
| F02 — ghim trích đoạn | Hai lần ghim liên tiếp ngay trong hồ sơ làm số căn cứ đổi 3→4→5; tải lại vẫn có cả hai câu trích. | Một hồ sơ, hai trích đoạn Điều 1 và Điều 2. |
| F03 — báo cáo từ căn cứ | Dùng lại hai evidence ID `35c31ef1c69d8741bee69c11`, `c2f8681a721716f0378cd277`; bản lưu `6bc3014b-b2fc-4820-8dec-5ecfa1611696` đạt `research_report_ok`, có hai provider calls, tổng 3.021 input + 1.542 output = **4.563** token được báo cáo. Mã dùng alias ngắn trong prompt và vẫn từ chối ID/trích dẫn ngoài tập đã chọn. | Một lượt thành công không chứng minh tỉ lệ ổn định; bản lỗi ban đầu tốn 2.054 token và không tạo được bản dùng được. Không coi kết luận luật hiện hành là đã xác minh. |
| F04 — kiểm tra admin | Chi tiết request review `34c092e5-cef5-48a2-829d-b7c283b0202a` không còn đánh dấu fail vì thiếu context/citation dạng chat; trường đếm findings cũ thiếu dữ liệu hiện “Chưa ghi nhận”. | Dữ liệu cũ thiếu số đếm không được suy diễn thành 0 hoặc 3. |
| F05 — token nguồn đã lưu | Phân tích `relevant` `60446906-f0fd-4731-8697-f2b21468204d` hiện trong admin với `retained_source_ok`, 10/37 đoạn từ 25.673 ký tự đã lưu, 3.550 input + 260 output = **3.810** provider tokens. Phân tích `full` `b64f7a66-5e94-4a2d-9069-ad5ca6f1885a` hiện với 15/15 đoạn từ 10.663 ký tự, 5.218 input + 267 output = **5.485** tokens. Cả hai hiển thị đầy đủ usage của 1/1 provider call được ghi nhận. | Hai câu hỏi và phạm vi nguồn khác nhau; **không** dùng chênh lệch 1.675 token làm tỉ lệ tiết kiệm. Chưa có A/B cùng đầu vào hoặc đối soát hóa đơn nhà cung cấp. |
| F06 — lọc loại | Kiểm tra lại luật `45/2019/QH14` và một thông tư với loại/nhà ban hành tương ứng; nhãn hiển thị khớp giá trị bộ lọc chính xác. | Chưa quét mọi loại và mọi backend. |
| Quota admin | Production `/settings` của admin ghi rõ quota demo theo ngày UTC không áp dụng. Mã bỏ qua giới hạn AI và write **theo ngày** cho admin có vai trò hiệu lực; xác thực, giới hạn theo phút, dung lượng và quota nhà cung cấp vẫn còn. | Đường OCR bổ sung được kiểm tra bằng unit test, **NOT RUN live**; hành vi tài khoản thường trên production **NOT RUN live** trong hậu kiểm này. |
| Cảnh báo báo cáo nguồn | Hai trang kết quả `retained_source_ok` ở trên sau deployment `5104921` không còn câu “Báo cáo chưa vượt qua bước kiểm chứng.”; cả hai vẫn có trích dẫn và cảnh báo OCR/đối chiếu bản gốc. | Kiểm tra chứng thực câu trích nguyên văn không chứng minh diễn giải pháp lý đúng. |

## Token và độ liên quan

Bản runtime giới hạn đoạn đưa vào model theo câu hỏi và tham chiếu Điều chung, giữ đoạn liền kề khi cần; không chứa danh sách tên luật/chủ đề/câu trả lời cố định. Admin lưu số token provider báo cáo, số đoạn chọn và trạng thái, không lưu nguyên văn riêng tư trong log dùng để tính chi phí. Đây là kiểm soát ngữ cảnh có thật và hai số đo usage thật. **Chưa chứng minh mức giảm chi phí**: cần chạy cùng bộ câu hỏi, cùng bản đọc, cùng model và cùng thời điểm trên `relevant`/`full`; so sánh Recall@K, căn cứ đủ điều kiện/ngoại lệ, trích dẫn hợp lệ, phần bỏ sót, lỗi kỹ thuật và input/output token. Đầu vào ngắn hơn không tự chứng minh câu trả lời đúng. Tavily chỉ có thể là nguồn khám phá URL tùy chọn; hậu kiểm này không dùng Tavily và không có A/B cho nó.

Ở câu hỏi Điều 2 trong `full`, model ghi “trang 1 và trang 2” trong lời văn trong khi hai trích dẫn được hiển thị đều neo trang 1; đây là phát biểu vị trí chưa được dẫn chứng đủ, dù bốn nhóm đối tượng xuất hiện trong trích đoạn. Bản đọc còn lộ `readable_pages: [1, 2, 3, 4, 5]` như dữ liệu thô trong câu trả lời. Hai điểm này cần đưa vào tập đánh giá câu trả lời/citation trước khi quảng bá độ tin cậy; chưa có cơ sở đề xuất bỏ chức năng. Không có chức năng nào bị xóa.

## Kiểm thử và thay đổi

- Sửa quota: test RED tập trung có 5 failed, 20 passed; sau sửa 28 passed. `python -m pytest -q` dùng Python ngoài `.venv` lỗi ở collection vì thiếu `pypdf` và import `tests.services`; không được tính là kết quả suite.
- Sau quota: `.venv\Scripts\python.exe -m pytest -q` → **1.413 passed, 4 skipped, 31 warnings**, 218,90 giây. Commit `a565b8cd816371ad71845c20f5918d52d38657f9`; deployment production đã Ready trước lượt hậu kiểm.
- Sửa cảnh báo: `.venv\Scripts\python.exe -m pytest -q tests/test_retained_source_routes.py::test_saved_answer_renders_safe_text_and_links_to_server_quote` → 1 failed đúng cảnh báo sai (RED); `.venv\Scripts\python.exe -m pytest -q tests/test_retained_source_routes.py` → 8 passed; `.venv\Scripts\python.exe -m pytest -q` sau review diff → **1.413 passed, 4 skipped, 31 warnings**, 404,94 giây. `git diff --cached --check` sạch. Commit `5104921097be71b86bfe40aa99afbf74819ad2cc` đã push lên `main` và xác nhận production Ready.
- Kiểm tra production là các thao tác giao diện trình duyệt có tài khoản admin và nguồn công khai; đây là live-provider runs riêng, **không** phải unit/integration suite. Không chạy full corpus ingestion, migration, xóa dữ liệu/chỉ mục, thay credentials, hoặc benchmark toàn tập.

Tệp runtime/test ở đợt quota: `app/services/reviewer_demo.py`, `app/api/workspace_routes.py`, `app/api/account_routes.py`, `app/templates/account_quota.html`, `app/templates/demo_notice.html`, `tests/services/test_reviewer_demo.py`, `tests/test_workspace_routes.py`, `tests/test_account_routes.py`. Đợt cảnh báo: `app/api/retained_source_routes.py`, `tests/test_retained_source_routes.py`. Đợt F01–F06 và hậu kiểm legacy nằm trong các commit `6a467a83bbd0b6bcb37af18e936eb891228e3096` và `bdc8663b1502b32ab6514733c0a4460072e101e3`.

## Việc còn mở

Chưa có benchmark tái lập đủ tài liệu/điều/khoản và độ đúng pháp lý, chưa xác minh toàn corpus v3, chưa đọc được bytes của export trong đợt kiểm toán, chưa đo tỉ lệ thành công báo cáo qua nhiều lượt, và chưa có A/B cùng đầu vào cho tiết kiệm token. Những việc này cần bằng chứng mới; không được suy từ các ca thành công ở đây thành “production-ready”. Nếu một chức năng không đạt sau phép thử có tiêu chí rõ, sẽ trình kết quả và đề xuất phương án trước khi bỏ; hiện không đề xuất xóa chức năng nào.

Cây Git trước khi thêm báo cáo đã có `.codex/config.toml` sửa sẵn và nhiều tệp chưa theo dõi không thuộc đợt này; chúng không được stage hay xóa. Báo cáo này là tài liệu hậu kiểm, không thay đổi mã runtime sau suite ở trên.
