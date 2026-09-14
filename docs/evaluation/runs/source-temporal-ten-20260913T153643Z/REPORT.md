# 10 câu ngoài corpus — phân tích trích đoạn theo thời điểm

Đã gọi service thật với Vertex Gemini 3.5 Flash cho 10 câu từ bộ nguồn ngoài corpus trước đó, bổ sung ngày áp dụng 13/09/2026. Không mock. **10/10 provider success, 10/10 response chỉ dùng ID đã chọn, 10/10 insufficient_evidence.** Năm văn bản có ngày hiệu lực tương lai theo metadata: cả 5 câu trả lời nêu ngày đó chưa đến. Đây không phải điểm đúng/đủ pháp lý.

## Phạm vi chính xác

Các URL đã được discovery ở lượt trước. Lượt này không search web lại, không chạy HTTP endpoint production, không đánh giá retrieval toàn corpus. Gọi đúng generate_selected_evidence_answer trên hai trích đoạn OCR thật mỗi văn bản: phần đầu trang 1 và một đoạn quanh lần xuất hiện đầu của “hiệu lực” (hoặc trang cuối). Mọi input, prompt, output, thời gian và provenance đều nằm trong JSON raw giữ cục bộ; bản công bố có hash và đánh giá tổng hợp. Giới hạn ngữ cảnh ứng dụng giữ nguyên; không đưa toàn bộ 178 trang vào model.

Heuristic chọn đoạn này có giới hạn rõ: “hiệu lực chứng thư” hay “còn hiệu lực” không nhất thiết là điều khoản hiệu lực văn bản. Do vậy kết quả không đại diện cho một người đã chọn đầy đủ căn cứ; cũng không chứng minh model không thể trả lời nếu được cấp đúng phần còn thiếu. Không đưa heuristic này vào production.

| Chủ đề | Trang có trích đoạn | Nội dung thực tế và phần thiếu |
| --- | --- | --- |
| aviation | 1, 4 | Nêu 01/01/2027 và chuyển tiếp sang Quyết định 2007/QĐ-TTg; thiếu nội dung quyết định đó và phương pháp phân bổ. |
| health | 1, 5 | Nêu ngày hiệu lực 09/09/2026 và ngày thực hiện mức phụ cấp 01/01/2026; thiếu mức hưởng/cách tính/đối tượng chi tiết. |
| procurement | 1, 14 | Nêu ngày metadata và một số sửa đổi; thiếu toàn bộ thay đổi, điều khoản hiệu lực, chuyển tiếp. |
| resources_tax | 1, 3 | Nêu hiệu lực 09/09/2026, kỳ thuế 2026; thiếu nội dung sửa đổi ở trang 2. |
| credit | 1, 4 | Nêu chưa đến ngày 01/11/2026; thiếu các khoản sửa đổi của Thông tư 15/2023/TT-NHNN. |
| maritime | 1, 2 | Nêu chưa đến ngày 01/11/2026; thiếu điều kiện hoạt động cụ thể. |
| agriculture | 1, 7 | Nêu chưa đến ngày 20/10/2026, một số loại bảo hiểm/thủ tục; thiếu toàn bộ sửa đổi và chuyển tiếp. |
| imports | 1, 10 | Nêu ngày do metadata công bố, thiếu điều kiện tại Điều 5/8 và điều khoản hiệu lực gốc. |
| reserves | 1, 28 | Nêu ngày metadata 04/09/2026; excerpt cắt ngay câu hiệu lực và thiếu phần quy trình quản lý. |
| electricity | 1, 18 | Nêu chưa đến ngày 20/10/2026; thiếu các chính sách hỗ trợ chi tiết. |

## Kết luận về sản phẩm

Bản sửa bảo toàn metadata giúp câu trả lời sử dụng ngày đã có thay vì báo mất thông tin. Tuy nhiên, đọc được PDF và tìm đúng URL chưa hoàn tất nghiên cứu. Cần tìm đúng điều khoản trong các bản đọc, giữ điều kiện/ngoại lệ/chuyển tiếp, rồi kiểm tra văn bản được dẫn tiếp. Trường hợp hàng không chỉ rõ cần đọc thêm Quyết định 2007/QĐ-TTg để trả lời cho thời điểm trước 2027.

Không chấm đạt trọn vẹn 10 câu. Chưa kiểm tra từng claim đối với toàn bộ văn bản gốc và hệ thống văn bản áp dụng tại ngày hỏi. Chỉ số valid_selected_ids không phải citation precision về nội dung. Token/chi phí không được harness này ghi nhận; không suy ra từ số câu hay gán bằng 0.

Manifest giữ Git SHA, git_dirty=true, diff SHA-256 và hash source/config tại lúc chạy. Source metadata đang uncommitted lúc chạy; không quảng bá đây là clean-commit benchmark. Các câu hỏi/nguồn là công khai; không đưa cookie hoặc dữ liệu người dùng vào artifact.

## Publication boundary

Raw response, model output, logs and diagnostic runners referenced above are retained locally; they are not published in this commit. The manifest records their hashes for local verification. Published evidence is limited to this curated report, aggregate results where present and public-source references. Production workspace identifiers and cookie values are excluded. This restricts public reproducibility; it does not turn summaries into raw evidence.
