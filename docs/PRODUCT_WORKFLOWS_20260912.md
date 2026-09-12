# VietLex: chức năng hữu ích và khoảng trống workflow

## Cập nhật sau sửa ngày 12/09

Query planner và PDF reader đã có [13 neo discovery thực đạt sau sửa](evaluation/runs/official-online-20260912T140633Z/REPORT.md); kết quả 5/10 bên dưới là baseline lịch sử, không phải trạng thái mới nhất. [Nghiệm thu workflow tiếp theo](verification/workflow-usability-20260912/REPORT.md) bổ sung mở lại bản đọc, đối chiếu riêng quote gốc, giữ lựa chọn và báo cáo có preview. Các mục còn là đề xuất phải đọc cùng [FEATURE_STATUS](../FEATURE_STATUS.md); chưa hoàn tất full-text hay registry hiệu lực toàn corpus.

## Kết luận từ baseline trước sửa

Vấn đề không đơn thuần là user có ít nút. User chưa được dẫn từ một vấn đề chưa rõ đến một đầu ra có thể sử dụng. Thêm công cụ phân tích sẽ không giải quyết việc không tìm được nguồn ban đầu. Trong [10 câu thử online](verification/online-discovery-20260912/REPORT.md), 5 câu biết số hiệu tìm được nguồn; 5 câu diễn đạt tự nhiên không tìm được nguồn. Đây là ưu tiên cao hơn thêm model.

Bản review ban đầu đúng về feature sprawl và giới hạn dữ liệu, nhưng cần điều chỉnh ba điểm:

1. Có trường `status` không đồng nghĩa biết hiệu lực. Dữ liệu chưa xác minh phải ở trạng thái unknown, kèm lịch sử xác nhận, nguồn và ngày đối chiếu. Không suy từ ngày ban hành ra hiệu lực.
2. Full-text search cần một index nội dung có coverage được kiểm kê. Không đổi nhãn ô tìm title thành “toàn văn” khi backend chưa đáp ứng. Document có trong kho không có nghĩa mọi Điều/Khoản có trong index retrieval: probe văn bản 333670 tìm thấy 16 chunk đã index nhưng không có Điều 25 trong tập probe.
3. Search API đa nguồn chỉ mở rộng discovery. Đúng và đủ còn cần đọc tài liệu, xác định ngoại lệ, thời điểm áp dụng và kiểm tra bằng chứng. Không chấm đạt từ whitelist domain hoặc HTTP 200.

## Người dùng và đầu ra chính

Primary persona: người nghiên cứu pháp lý, compliance và legal operations. Họ cần lưu được câu hỏi, tình tiết, ngày áp dụng, căn cứ và việc tiếp theo. Homepage nên cho chọn công việc: tìm quy định, kiểm tra nghĩa vụ, rà soát tài liệu, soạn bản ghi nhớ. Mỗi lựa chọn mở một luồng có trạng thái và đầu ra cụ thể; không đưa toàn bộ công cụ lên một trang.

## 1. Hồ sơ câu hỏi có hướng dẫn — P0

**Luồng:** mô tả vấn đề → bổ sung tình tiết còn thiếu → chọn ngày áp dụng → tìm nguồn → lưu hồ sơ.

Ví dụ người dùng hỏi về thử việc: thu thập vị trí, trình độ công việc và ngày cần áp dụng. Những dữ kiện này được lưu như dữ liệu user cung cấp, không được model tự điền. Cho phép bỏ qua với nhãn “chưa rõ”; câu trả lời phải giữ giới hạn tương ứng.

Đối tượng lưu: câu hỏi gốc, facts có người nhập và thời gian, câu hỏi làm rõ, as_of, source_scope, trạng thái thiếu căn cứ. Không bắt người dùng biết số hiệu mới bắt đầu được.

**Nghiệm thu:** quay lại hồ sơ vẫn giữ tình tiết; sửa ngày áp dụng đánh dấu kết luận cũ cần rà soát; không tự chọn đáp án làm rõ; không tự mở rộng scope. Đo tỷ lệ hồ sơ tạo được ít nhất một căn cứ đã đọc trên tổng hồ sơ bắt đầu, không dùng số lượt chat thay cho hoàn thành công việc.

## 2. Tìm nguồn khi corpus thiếu — P0

**Luồng:** câu hỏi tự nhiên → xem từ khóa đề xuất → search nguồn chính thức → đọc toàn văn → chọn Điều/Khoản → đưa vào hồ sơ.

Tách trạng thái “không tìm thấy”, “cổng nguồn lỗi”, “tìm thấy metadata nhưng chưa đọc được nội dung”. Cho sửa từ khóa trực tiếp và hiển thị cổng đã thực sự tìm. Không hiển thị sáu domain như sáu nguồn đã được search nếu chỉ gọi một provider.

Ưu tiên sửa query planner theo đối tượng và hành vi pháp lý, bảo toàn cụm từ và bỏ phần hỏi/thời gian dư thừa. A/B cùng bộ câu hỏi và thêm bộ holdout trước khi thay mặc định. Chỉ dùng model tạo từ khóa nếu có đầu ra có cấu trúc, giới hạn chi phí, giữ câu gốc và kiểm tra không thêm tình tiết. Không hardcode 10 câu benchmark.

**Nghiệm thu:** công khai URL duy nhất tìm được, số trang đã đọc thành công, trích đoạn và vị trí. Với câu không đủ căn cứ, trả danh sách thiếu và bước tiếp theo. Chấm riêng discovery hit, nguồn đúng chủ đề, evidence coverage và câu trả lời được chứng minh; mỗi chỉ số có mẫu số và skip reason.

## 3. Checklist nghĩa vụ có người xử lý — P1

**Luồng:** chọn nguồn → tạo bảng nghĩa vụ → user xác nhận → giao người phụ trách/hạn → đánh dấu hoàn tất kèm tài liệu.

Mở rộng obligation matrix hiện có bằng trạng thái, người phụ trách, hạn do user xác nhận, bằng chứng hoàn tất. Mỗi dòng dẫn về đoạn luật và điều kiện áp dụng. Không tự biến thời hạn model đoán thành lịch pháp lý chính thức.

**Nghiệm thu:** thay nguồn đánh dấu các dòng liên quan cần rà soát; lịch sử lưu ai sửa; export giữ citation và trạng thái; không gửi thông báo ra bên ngoài nếu chưa được cấu hình/cho phép. Giá trị là quản lý công việc sau nghiên cứu, không phải thêm một câu trả lời dài.

## 4. Rà soát tài liệu qua nhiều phiên bản — P1

**Luồng:** upload → review → user quyết định finding → upload bản sửa → đối chiếu → xác nhận resolved → xuất báo cáo.

Giữ finding như object độc lập với response model: nguồn clause, issue, recommendation, basis, status, reviewer note và revision. Không đánh resolved chỉ vì đoạn chữ thay đổi. So sánh phải hiển thị finding cũ, thay đổi tương ứng và bằng chứng để reviewer quyết định.

**Nghiệm thu:** concurrent edit có conflict; finding dismissed không mất lịch sử; upload bản mới không xóa bản cũ; export phản ánh đúng trạng thái mới nhất. Với tài liệu là trích luật, không mặc định gọi mọi đoạn là điều khoản hợp đồng.

## 5. Bản ghi nhớ có thể bàn giao — P1

**Luồng:** chọn kết quả đã kiểm tra → chỉnh Issue/Facts/Analysis/Risks/Recommendations → lưu version → xuất DOCX/Markdown.

Thêm danh sách điểm chưa xác minh và nguồn cần đối chiếu ngay trong đầu ra. Khi sửa nguồn hoặc findings, báo report version nào đang cũ. Không tự ghi đè bản user đã chỉnh bằng một lần generate khác. PDF cần kiểm tra phân trang, font tiếng Việt và citation thật trước khi đưa vào danh sách export đã nghiệm thu.

**Nghiệm thu:** file tải xuống mở được, giữ tiếng Việt và citation; version cũ đọc được; nội dung chỉnh sửa xuất đúng. Đo tỷ lệ hồ sơ tạo deliverable được user lưu, không đo số lần model generate.

## 6. Admin xử lý dữ liệu và feedback — P0/P1

Ưu tiên queue có hành động hơn dashboard nhiều biểu đồ: thiếu nguồn chính thức, chưa kiểm tra hiệu lực, lỗi parse, thiếu chunk, citation sai, retrieval không tìm thấy. Mỗi item có bằng chứng, assignee, trạng thái, root cause và đường dẫn tới lần kiểm tra lại.

Feedback có thể tạo regression draft; người duyệt phải xác nhận expected evidence trước khi trở thành golden case. Không coi dislike tự động là hallucination. Reindex/rollback phải là job được cấp quyền riêng, có trước/sau và checkpoint; không gắn nút “sửa” thực chất xóa index.

**Nghiệm thu:** một feedback lỗi retrieval đi được tới case tái hiện, bản sửa và kết quả regression. Coverage corpus phải nói rõ document hay chunk, tại thời điểm nào và kiểm kê từ đâu.

## UX chỉ số: quy tắc hiển thị

Mỗi chỉ số cần tên dễ hiểu, cách tính, mẫu số, thời gian đo, dữ liệu thiếu và giới hạn diễn giải. N/A là thiếu dữ liệu, không phải 0. Token không đồng nghĩa tiền; request không đồng nghĩa người dùng; citation hợp lệ không chứng minh nguồn còn hiệu lực; AI judge không phải chuyên gia pháp lý.

Đã bổ sung hướng dẫn mở rộng tại admin overview, usage/quality và Evaluation Lab; phần đánh giá chat dùng nhãn tiếng Việt và giải thích giới hạn. Bước tiếp theo là đặt mô tả sát từng metric có ngữ cảnh riêng, đặc biệt coverage và khoảng thời gian. Không dùng tooltip chỉ hover vì người dùng bàn phím/điện thoại cũng cần đọc được.

## Thứ tự triển khai và điều kiện dừng

1. Giữ runtime ổn định, scope đúng và lỗi có thể quan sát.
2. Sửa tìm kiếm câu tự nhiên, sau đó đọc được căn cứ online. Chưa đạt bước này thì không quảng bá “Deep Research hoàn chỉnh”.
3. Nối hồ sơ → checklist/findings → deliverable; tận dụng state và version hiện có.
4. Đưa kết quả lỗi thật vào admin queue và regression có người duyệt.

Tài liệu này là phân tích và tiêu chí đề xuất, **không phải danh sách tính năng đã triển khai**. Trạng thái hiện tại chỉ theo [FEATURE_STATUS](../FEATURE_STATUS.md); bằng chứng live có phạm vi nêu rõ trong từng report.
