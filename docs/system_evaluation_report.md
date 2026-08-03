# SYSTEM EVALUATION REPORT - VIETLEX LEGAL RAG

**Evaluation Timestamp**: `2026-08-02 15:44:19`  
**Number of Test Queries**: `30` across Factoid, Multi-hop and Unanswerable groups  
**Semantic cache enabled**: `False`  
**Dataset warning**: third-party research data; not an official source of current Vietnamese law.

## Metrics

| Metric | Value |
| :--- | ---: |
| Average end-to-end latency | 160.77s |
| Average queue latency | 139.59s |
| Average online pipeline latency | 21.05s |
| Average Ragas latency | 0.14s |
| Evaluation failures | 6/30 |
| Cache hits | 0/30 |
| Legal input pass rate | 87.5% |
| Answerable accuracy | 0.0% (0/24) |
| Grounded generation rate | 8.3% (2/24) |
| Service completion rate | 86.7% |
| Unanswerable accuracy | 83.3% (5/6) |
| Refusal precision | 33.3% |
| Refusal recall | 83.3% |
| Gold context hit rate | 30.0% (9/30) |
| Gold context recall | 0.25 |
| Retrieval MRR | 0.25 |
| Output blocked | 6/30 |
| Ragas Faithfulness | - |
| Ragas Answer Accuracy | - |
| Ragas Context Precision | - |
| Ragas Context Recall | - |

> Cache hits and honest refusals are not assigned artificial Ragas scores. Metric averages include scored generations only.

> Answerable accuracy requires Ragas answer accuracy >= 0.50; technical failures remain in denominators. Reference-less cases are excluded from direct retrieval metrics.

## Scenarios

| ID | Group | Query | Status | Latency | Faithfulness | Accuracy | Precision | Recall |
| :-: | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| 1 | Factoid | Theo Luật Bảo vệ môi trường, Giấy phép môi trường được định nghĩa như thế nào? | Honest Refusal | 80.20s | - | - | - | - |
| 2 | Multi-hop | Sự khác biệt cơ bản về tính chất áp dụng giữa quy chuẩn kỹ thuật môi trường và tiêu chuẩn môi trường là gì? | Blocked Input | 12.90s | - | - | - | - |
| 3 | Unanswerable | Mức phạt đối với tổ chức, cá nhân không có Giấy phép môi trường khi nhập khẩu phế liệu từ nước ngoài là bao nhiêu? | Honest Refusal | 37.96s | - | - | - | - |
| 4 | Factoid | Chuyên gia có bằng thạc sĩ cần có bao nhiêu năm kinh nghiệm công tác để trở thành thành viên hội đồng thẩm định báo cáo đánh giá tác động môi trường? | Honest Refusal | 48.63s | - | - | - | - |
| 5 | Multi-hop | Đối với dự án đầu tư nằm trên địa bàn từ 02 đơn vị hành chính cấp tỉnh trở lên, cơ quan nào có thẩm quyền thẩm định báo cáo đánh giá tác động môi trường và thời hạn ra quyết định phê duyệt là bao lâu kể từ khi nhận được báo cáo đã chỉnh sửa? | Honest Refusal | 50.38s | - | - | - | - |
| 6 | Unanswerable | Theo quy định tại Điều 67, mức tiền ký quỹ bảo vệ môi trường cụ thể mà tổ chức khai thác khoáng sản phải nộp là bao nhiêu? | Honest Refusal | 65.95s | - | - | - | - |
| 7 | Factoid | Loại công nghệ nào được ưu tiên lựa chọn trong xử lý chất thải y tế lây nhiễm? | Blocked Output | 58.54s | - | - | - | - |
| 8 | Multi-hop | Các hộ gia đình sản xuất trong làng nghề thuộc ngành, nghề không khuyến khích phát triển có những trách nhiệm gì về bảo vệ môi trường? | Honest Refusal | 93.20s | - | - | - | - |
| 9 | Unanswerable | Thời hạn cụ thể để Ủy ban nhân dân cấp huyện phải hoàn thành việc thu thập dữ liệu xác định thiệt hại theo đề nghị của cấp xã là bao nhiêu ngày? | Honest Refusal | 74.19s | - | - | - | - |
| 10 | Factoid | Hệ thống thu gom, xử lý nước thải tại các khu dân cư tập trung mới phải được thiết kế như thế nào so với hệ thống thoát nước mưa? | Blocked Output | 115.84s | - | - | - | - |
| 11 | Multi-hop | Các nội dung chính của hoạt động bảo vệ tầng ô-dôn là gì và cơ quan nào chịu trách nhiệm chủ trì trình Thủ tướng Chính phủ ban hành Kế hoạch quốc gia quản lý các chất làm suy giảm tầng ô-dôn? | Eval Failed | 117.17s | - | - | - | - |
| 12 | Unanswerable | Mức xử phạt tiền cụ thể là bao nhiêu đối với doanh nghiệp không thực hiện đăng ký thay đổi nội dung Giấy chứng nhận đăng ký hoạt động chi nhánh trong thời hạn 10 ngày? | Blocked Input | 120.86s | - | - | - | - |
| 13 | Factoid | Ai là người chịu trách nhiệm thu nhận và tổng hợp thông tin về môi trường quốc gia? | Honest Refusal | 130.11s | - | - | - | - |
| 14 | Multi-hop | Khi có từ 02 tổ chức, cá nhân trở lên gây thiệt hại về môi trường, trách nhiệm bồi thường và chi trả chi phí được xác định dựa trên những yếu tố nào, và ai sẽ quyết định nếu không xác định được tỷ lệ trách nhiệm? | Blocked Output | 143.31s | - | - | - | - |
| 15 | Unanswerable | Mức phí môi giới tối đa khi bán cổ phần cho người môi giới được quy định là bao nhiêu phần trăm? | Honest Refusal | 147.85s | - | - | - | - |
| 16 | Factoid | Vốn tự nhiên bao gồm những loại tài nguyên và dịch vụ nào theo quy định? | Honest Refusal | 163.21s | - | - | - | - |
| 17 | Multi-hop | Theo văn bản, những đối tượng nào được xác định là người quản lý doanh nghiệp? | Honest Refusal | 160.29s | - | - | - | - |
| 18 | Unanswerable | Mức xử phạt hành chính cụ thể đối với hành vi không báo cáo về việc tuân thủ quy định của Luật Doanh nghiệp theo yêu cầu của Cơ quan đăng ký kinh doanh là bao nhiêu? | Honest Refusal | 180.68s | - | - | - | - |
| 19 | Factoid | Trong trường hợp Nhà nước trưng mua hoặc trưng dụng tài sản của doanh nghiệp, việc thanh toán và bồi thường được quy định như thế nào? | retrieval_error | 195.71s | - | - | - | - |
| 20 | Multi-hop | Để thay đổi loại tài sản góp vốn so với cam kết ban đầu, thành viên công ty trách nhiệm hữu hạn hai thành viên trở lên cần điều kiện gì và phải hoàn thành việc góp vốn trong thời gian bao lâu? | retrieval_error | 204.56s | - | - | - | - |
| 21 | Factoid | Trường hợp thành viên công ty là cá nhân bị Tòa án tuyên bố mất tích thì quyền và nghĩa vụ của họ được thực hiện như thế nào? | retrieval_error | 218.72s | - | - | - | - |
| 22 | Multi-hop | Trong trường hợp chủ sở hữu không góp đủ vốn điều lệ theo cam kết, thời hạn để đăng ký thay đổi vốn là bao lâu và họ phải chịu trách nhiệm gì đối với các nghĩa vụ tài chính trước đó? | retrieval_error | 233.13s | - | - | - | - |
| 23 | Factoid | Cơ quan nào có thẩm quyền quyết định và chi trả tiền lương, thù lao cũng như các lợi ích khác cho Kiểm soát viên? | Blocked Input | 223.72s | - | - | - | - |
| 24 | Multi-hop | Để yêu cầu triệu tập họp Đại hội đồng cổ đông, nhóm cổ đông sở hữu 5% cổ phần phổ thông cần thực hiện yêu cầu bằng hình thức nào và phải đính kèm thêm những tài liệu gì? | Eval Failed | 269.83s | - | - | - | - |
| 25 | Factoid | Đại hội đồng cổ đông thường niên phải được tổ chức trong thời hạn bao lâu kể từ ngày kết thúc năm tài chính? | Honest Refusal | 250.22s | - | - | - | - |
| 26 | Multi-hop | Khi chủ tọa tạm dừng họp trái quy định và Đại hội đồng cổ đông bầu người thay thế để thông qua nghị quyết về việc tổ chức lại công ty, thì nghị quyết này cần đạt tỷ lệ phiếu tán thành tối thiểu là bao nhiêu để được thông qua? | Blocked Output | 264.59s | - | - | - | - |
| 27 | Factoid | Sau khi kết thúc việc kiểm tra theo yêu cầu của cổ đông, Ban kiểm soát phải báo cáo kết quả trong thời hạn bao lâu và báo cáo cho những đối tượng nào? | Blocked Output | 277.02s | - | - | - | - |
| 28 | Multi-hop | Để có quyền tự mình khởi kiện thành viên Hội đồng quản trị do vi phạm trách nhiệm người quản lý, cổ đông hoặc nhóm cổ đông cần đáp ứng điều kiện gì về tỷ lệ sở hữu cổ phần? | Honest Refusal | 286.87s | - | - | - | - |
| 29 | Factoid | Cụm từ "doanh nghiệp nhà nước" trong Luật Ngân sách nhà nước số 83/2015/QH13 được thay thế bằng cụm từ nào theo quy định tại văn bản này? | Honest Refusal | 288.72s | - | - | - | - |
| 30 | Multi-hop | Khi chi nhánh của doanh nghiệp chấm dứt hoạt động, doanh nghiệp đó có những trách nhiệm gì liên quan đến nợ và người lao động của chi nhánh? | Blocked Output | 308.86s | - | - | - | - |
