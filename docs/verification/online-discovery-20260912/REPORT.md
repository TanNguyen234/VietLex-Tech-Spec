# Kiểm tra thực tế tìm kiếm online — 12/09/2026

**Chưa đạt yêu cầu trả lời đúng và đủ khi người dùng không có dữ liệu sẵn.** Đây là kiểm tra discovery của service thật gọi Cổng văn bản Chính phủ, không phải benchmark trả lời pháp lý và không phải request qua API production. Không dùng mock hoặc kết quả web search khác để thay kết quả sản phẩm.

## Phương pháp và giới hạn

- 10 chủ đề, mỗi câu chạy 5 bước bằng `build_research_plan` và `run_deep_research`, version `official-web-v2`. Script tái chạy đi kèm; cần cấu hình thật.
- Chọn neo văn bản từ bảng kết quả thực tế của cổng Chính phủ. Mỗi số hiệu đã được kiểm tra không có trong SQLite local và Supabase. Bộ ứng viên 2025 bị loại vì thực tế có trong Supabase.
- **Đã quét hết Qdrant v3 bằng unfiltered scroll** sau khi bộ lọc document_id gặp lỗi thiếu payload index: 141.798 point, 142 trang, không point nào thiếu document_number; cả 10 số hiệu đều có 0 match. Xem `qdrant-absence-scan.json` cùng thời gian và SHA luồng đọc. Không đổi index hoặc đọc vector.
- “Ngoài database” nghĩa là các văn bản neo mới không có trong SQLite, Supabase và Qdrant v3 đang phục vụ hệ thống. Không có nghĩa kho không chứa luật cũ cùng chủ đề. Pinecone legacy không được quét; đó không phải backend runtime v3 của lượt thử.
- 5 câu có số hiệu, 5 câu diễn đạt tự nhiên. Đây là bộ kiểm tra có chủ đích, không đại diện phân bố mọi truy vấn thực tế.
- Chấm tìm thấy bằng URL khớp neo, loại trùng URL giữa các bước. Neo là văn bản liên quan đã biết, không phải danh sách đầy đủ mọi luật cần trả lời.
- Ngày ban hành và tiêu đề là metadata từ cổng; chưa xác minh hiệu lực, nội dung điều khoản hoặc tính đầy đủ bằng chuyên gia pháp lý.

## Kết quả

| Chủ đề | Câu hỏi thực chạy | Neo kiểm tra | URL duy nhất | Khớp neo | Bước lỗi provider |
| --- | --- | --- | ---: | --- | ---: |
| Hàng không | Chi phí trực tiếp và gián tiếp khi khai thác tài sản hạ tầng hàng không do Nhà nước đầu tư được phân bổ thế nào theo quy định tháng 9/2026? | [68/2026/TT-BXD](https://vanban.chinhphu.vn/?pageid=27160&docid=219442) | 0 | Không | 0/5 |
| Y tế | Nhân viên y tế được hưởng phụ cấp ưu đãi nghề như thế nào theo quy định mới tháng 9/2026? | [350/2026/NĐ-CP](https://vanban.chinhphu.vn/?pageid=27160&docid=219438) | 0 | Không | 0/5 |
| Đấu thầu | Quy định lựa chọn nhà thầu được sửa đổi ra sao trong tháng 9/2026? | [349/2026/NĐ-CP](https://vanban.chinhphu.vn/?pageid=27160&docid=219431) | 0 | Không | 0/5 |
| Thuế tài nguyên | Hướng dẫn thuế tài nguyên thay đổi thế nào theo Thông tư 135/2026/TT-BTC? | [135/2026/TT-BTC](https://vanban.chinhphu.vn/?pageid=27160&docid=219437) | 1 | Có | 0/5 |
| Tín dụng | Hoạt động thông tin tín dụng có thay đổi gì theo Thông tư 46/2026/TT-NHNN? | [46/2026/TT-NHNN](https://vanban.chinhphu.vn/?pageid=27160&docid=219435) | 1 | Có | 0/5 |
| Hàng hải | Cơ sở đào tạo và tổ chức cung ứng thuyền viên phải đáp ứng điều kiện gì theo Nghị định 348/2026/NĐ-CP? | [348/2026/NĐ-CP](https://vanban.chinhphu.vn/?pageid=27160&docid=219424) | 1 | Có | 0/5 |
| Bảo hiểm nông nghiệp | Bảo hiểm nông nghiệp được sửa đổi những nội dung gì theo Nghị định 346/2026/NĐ-CP? | [346/2026/NĐ-CP](https://vanban.chinhphu.vn/?pageid=27160&docid=219420) | 1 | Có | 0/5 |
| Nhập khẩu | Nhập khẩu dây chuyền công nghệ đã qua sử dụng phải đáp ứng điều kiện gì theo quy định mới tháng 9/2026? | [56/2026/TT-BKHCN](https://vanban.chinhphu.vn/?pageid=27160&docid=219429) | 0 | Không | 0/5 |
| Dự trữ quốc gia | Quản lý và sử dụng hàng dự trữ quốc gia theo Nghị định 345/2026/NĐ-CP được quy định thế nào? | [345/2026/NĐ-CP](https://vanban.chinhphu.vn/?pageid=27160&docid=219380) | 1 | Có | 0/5 |
| Điện lực | Quy định mới tháng 9/2026 hỗ trợ ứng dụng khoa học công nghệ và chế tạo trong lĩnh vực điện lực như thế nào? | [344/2026/NĐ-CP](https://vanban.chinhphu.vn/?pageid=27160&docid=219377) | 0 | Không | 0/5 |

**Discovery: 5/10 câu tìm thấy neo (50%).** Nhóm có số hiệu: 5/5. Nhóm câu hỏi tự nhiên: 0/5. Nguồn tìm được chỉ chứng minh văn bản liên quan xuất hiện trong kết quả; không chứng minh trả lời đúng luật. Các response `partial` không được tính là hoàn tất nghiên cứu.

**Độ đúng và đủ của câu trả lời: NOT EVALUATED.** Service này trả metadata/snippet, không tạo bản trả lời có toàn văn điều khoản. Không có cơ sở gán accuracy, faithfulness hay legal completeness cho 10 câu. Không tìm thấy nguồn là thất bại discovery, không phải kết luận không tồn tại quy định.

## Nguyên nhân và hành động

1. Query planner giữ số hiệu tốt hơn sau sửa lỗi, nhưng câu tự nhiên vẫn lấy cuối câu, dễ giữ mốc thời gian thay cho đối tượng pháp lý. Cần xây bộ tạo từ khóa và kiểm tra A/B trên cùng câu, không hardcode đáp án bộ này.
2. Năm truy vấn trên một cổng không tương đương nghiên cứu đa nguồn. Gắn nhãn đúng phạm vi cổng; phân biệt không có kết quả với lỗi mạng.
3. Cần bước đọc toàn văn/PDF, trích Điều/Khoản, xác định phạm vi và điểm còn thiếu trước khi cho người dùng xuất kết luận. Không dùng title/snippet để chứng nhận hiệu lực.
4. Khi thiếu căn cứ, đưa người dùng tới sửa từ khóa, tìm văn bản theo số hiệu hoặc bổ sung nguồn; không mở rộng phạm vi âm thầm.

Các JSON đi kèm giữ nguyên kết quả service, query, trạng thái từng bước, kiểm tra hai kho tra cứu và lần quét Qdrant bổ sung. Chúng chỉ chứa câu hỏi thử nghiệm và nguồn công khai.
