# PHÂN TÍCH VÀ ĐÁNH GIÁ CÁC TÍNH NĂNG CỦA NVIDIA NEMO GUARDRAILS

Tài liệu này tổng hợp toàn bộ các tính năng bảo mật và kiểm duyệt mà thư viện **NVIDIA NeMo Guardrails** cung cấp (dựa trên tài liệu chính thức từ NVIDIA), kèm theo đánh giá chi tiết về khả năng áp dụng và mức độ cần thiết đối với dự án **Vietlex Legal RAG** (Trợ lý Pháp luật Việt Nam).

---

## 1. Tổng quan về NeMo Guardrails

NVIDIA NeMo Guardrails là một bộ công cụ mã nguồn mở giúp các nhà phát triển dễ dàng xây dựng các rào chắn bảo mật cho các ứng dụng dựa trên mô hình ngôn ngữ lớn (LLM). Nó cho phép kiểm soát đầu vào (input), luồng hội thoại (dialogue), và đầu ra (output) của LLM thông qua ngôn ngữ cấu hình Colang và các file định cấu hình YAML.

---

## 2. Chi tiết các Tính năng & Đánh giá mức độ tích hợp vào Vietlex

Dưới đây là danh sách đầy đủ các tính năng trong Catalog của NeMo Guardrails và phân tích đánh giá mức độ phù hợp cho dự án Vietlex Legal RAG.

### 2.1 Topic Control (Kiểm soát Chủ đề hội thoại)
* **Mô tả chức năng**: Giới hạn phạm vi thảo luận của chatbot chỉ xoay quanh các chủ đề định trước. Khi người dùng hỏi các câu hỏi ngoài lề (off-topic) như công thức nấu ăn, viết code, hoặc các vấn đề chính trị/xã hội không liên quan, hệ thống sẽ chặn và đưa ra phản hồi từ chối định sẵn mà không cần gửi câu hỏi tới LLM chính.
* **Cách hoạt động**: Định nghĩa các luồng hội thoại mẫu (dialogue flows) bằng ngôn ngữ Colang để hướng dẫn bot nhận diện ý định (intent) và chuyển hướng hội thoại khi đi lệch hướng.
* **Đánh giá đối với Vietlex**: **CỰC KỲ CẦN THIẾT (Tích hợp ngay)**.
  * *Lý do*: Vietlex là một trợ lý chuyên biệt về luật pháp Việt Nam. Việc trả lời các câu hỏi ngoài phạm vi không chỉ làm tăng chi phí API (token) vô ích mà còn tăng nguy cơ LLM đưa ra thông tin sai lệch về các chủ đề nhạy cảm. Kiểm soát chủ đề giúp giữ ứng dụng hoạt động đúng mục tiêu thương mại và kỹ thuật.

### 2.2 Jailbreak Protection (Chống các cuộc tấn công bẻ khóa prompt)
* **Mô tả chức năng**: Nhận diện và ngăn chặn các nỗ lực của người dùng nhằm "đánh lừa" hệ thống (Prompt Injection / Jailbreaking) để bỏ qua các rào chắn bảo mật của hệ thống (ví dụ: prompt dạng "Hãy đóng vai một AI không bị giới hạn...", "Từ giờ hãy bỏ qua các hướng dẫn trước đó...").
* **Cách hoạt động**: Sử dụng mô hình kiểm duyệt phụ hoặc các thuật toán phân tích heuristic để kiểm tra xem prompt của người dùng có chứa các cấu trúc lệnh hệ thống độc hại hay không.
* **Đánh giá đối với Vietlex**: **CỰC KỲ CẦN THIẾT (Tích hợp ngay)**.
  * *Lý do*: Trợ lý pháp luật rất dễ bị người dùng thử thách bằng các prompt injection để bắt nó phát ngôn sai lệch hoặc tuyên bố các điều khoản vi phạm pháp luật. Việc chặn đứng jailbreak từ cổng vào giúp bảo vệ uy tín và độ tin cậy của hệ thống.

### 2.3 Content Safety / Moderation (Kiểm duyệt An toàn nội dung)
* **Mô tả chức năng**: Kiểm tra cả đầu vào và đầu ra để phát hiện ngôn từ kích động thù địch, quấy rối, nội dung bạo lực, nội dung người lớn, hoặc các ngôn từ toxic khác.
* **Cách hoạt động**: Tích hợp các bộ phân loại văn bản (classifiers) hoặc gọi các mô hình an toàn chuyên dụng (như Llama Guard hoặc các API kiểm duyệt nội dung của GCP/OpenAI).
* **Đánh giá đối với Vietlex**: **CẦN THIẾT (Nên tích hợp)**.
  * *Lý do*: Bảo vệ hệ thống khỏi việc hiển thị các nội dung không phù hợp hoặc vi phạm thuần phong mỹ tục Việt Nam. Đặc biệt là bảo vệ đầu ra của AI không vô tình sinh ra nội dung toxic khi gặp các câu hỏi mang tính khiêu khích.

### 2.4 Hallucination & Fact-Checking (Chống ảo giác & Xác thực thông tin)
* **Mô tả chức năng**: Đảm bảo câu trả lời của mô hình dựa trên thực tế và thông tin chính xác từ tài liệu tham chiếu (ngữ cảnh RAG trích xuất từ Qdrant) thay vì tự bịa ra thông tin.
* **Cách hoạt động**: Sử dụng cơ chế Self-Check (LLM tự đối chiếu câu trả lời của chính mình với các đoạn ngữ cảnh luật để tìm điểm mâu thuẫn) hoặc các mô hình tính điểm tương đồng ngữ nghĩa (như AlignScore).
* **Đánh giá đối với Vietlex**: **CỰC KỲ QUAN TRỌNG (Bắt buộc phải có)**.
  * *Lý do*: Trong lĩnh vực pháp luật, ảo giác (hallucination) là điều tối kỵ. Việc AI tự chế ra một điều luật không tồn tại hoặc trích dẫn sai số hiệu nghị định có thể gây ra hậu quả pháp lý nghiêm trọng cho người dùng. Tính năng này giúp đảm bảo độ tin cậy của câu trả lời.

### 2.5 PII Detection & Redaction (Nhận diện & Lọc thông tin cá nhân)
* **Mô tả chức năng**: Tự động phát hiện và che giấu (redact) hoặc lọc bỏ các thông tin nhận dạng cá nhân nhạy cảm (Personally Identifiable Information) như: Số CCCD, số điện thoại, địa chỉ email, số tài khoản ngân hàng, thông tin thẻ tín dụng.
* **Cách hoạt động**: Sử dụng các thư viện nhận diện thực thể có tên (NER) như Microsoft Presidio chạy offline hoặc tích hợp API bên thứ ba để lọc text trước khi gửi đến LLM và trước khi trả về cho user.
* **Đánh giá đối với Vietlex**: **RẤT CẦN THIẾT (Nên tích hợp sớm)**.
  * *Lý do*: Để tuân thủ Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân tại Việt Nam. Người dùng khi hỏi về tình huống pháp lý có xu hướng đưa cả tên tuổi, số điện thoại hoặc địa chỉ thật vào câu hỏi. Hệ thống cần ẩn các thông tin này để bảo vệ quyền riêng tư trước khi chuyển tiếp dữ liệu đến LLM Gateway.

### 2.6 Agentic Security & Tool Calling Control (Bảo mật Tác tử & Giám sát gọi Tool)
* **Mô tả chức năng**: Thiết lập ranh giới bảo mật cho các AI Agent có khả năng tự động đưa ra quyết định gọi các API hoặc công cụ ngoài (Function Calling). Nó kiểm tra xem tham số truyền vào công cụ có hợp lệ và an toàn không, ngăn chặn các cuộc tấn công tiêm nhiễm mã độc qua tham số gọi hàm.
* **Cách hoạt động**: Định nghĩa cấu trúc schema nghiêm ngặt cho từng tool trong Colang và chặn cuộc gọi nếu phát hiện tham số bất thường.
* **Đánh giá đối với Vietlex**: **CHƯA CẦN THIẾT (Có thể xem xét sau)**.
  * *Lý do*: Hiện tại Vietlex hoạt động theo mô hình luồng RAG tĩnh cố định (FastAPI gọi Qdrant và Cohere trực tiếp, sau đó đưa kết quả vào LLM). Chúng ta không cho phép mô hình tự quyết định gọi công cụ ngoài một cách tự do (không dùng kiến trúc ReAct/Agent tự trị gọi hàm). Do đó, nguy cơ tấn công qua tool calling hiện bằng không.

### 2.7 Third-Party Security APIs Integration (Tích hợp API bảo mật bên thứ ba)
* **Mô tả chức năng**: Kết nối nhanh với các giải pháp bảo mật chuyên dụng như ActiveFence, Cisco AI Defense, Cleanlab, GCP Text Moderation, Llama Guard, Patronus Lynx để thực hiện kiểm duyệt.
* **Cách hoạt động**: Cấu hình các API key và endpoint trong file config YAML của Guardrails để hệ thống tự động gọi kiểm tra song song hoặc tuần tự.
* **Đánh giá đối với Vietlex**: **CÂN NHẮC (Không ưu tiên)**.
  * *Lý do*: Các dịch vụ này thường yêu cầu trả phí theo lượng sử dụng và làm tăng đáng kể thời gian phản hồi (latency) của hệ thống do phải gọi nhiều API bên ngoài. Đối với tiếng Việt, các mô hình toàn cầu này cũng hoạt động kém chính xác hơn so với việc cấu hình rào chắn bằng Colang/LLM prompts tối ưu nội bộ.

---

## 3. Bản đồ Đề xuất Triển khai (Roadmap & Recommendations)

Để đạt hiệu quả tối ưu cho Vietlex Legal RAG, chúng ta nên chia việc tích hợp NeMo Guardrails thành các giai đoạn dựa trên mức độ ưu tiên và chi phí tài nguyên:

| Tính năng | Mức độ ưu tiên | Trạng thái hiện tại | Giải pháp đề xuất |
| :--- | :---: | :--- | :--- |
| **Topic Control** | Cao | Đang chạy bản demo qua prompt | Chuyển hẳn sang cấu hình Colang Flow kết hợp embeddings để phát hiện câu hỏi ngoài lề nhanh chóng mà không cần gọi LLM sinh văn bản, giúp giảm latency. |
| **Jailbreak Protection** | Cao | Tích hợp trong Input Guardrails | Sử dụng mô hình kiểm duyệt nhẹ (hoặc self-check prompt tối ưu tiếng Việt) để quét nhanh câu hỏi ở đầu vào. |
| **Hallucination Check** | Cao | Tích hợp trong Output Guardrails | Triển khai cơ chế đối chiếu tự động (NLI - Natural Language Inference) giữa câu trả lời và context luật trích xuất. Trả về câu từ chối chuẩn nếu phát hiện AI tự bịa luật. |
| **PII Detection** | Trung bình | Chưa tích hợp | Tích hợp thư viện Python `presidio-analyzer` (miễn phí, chạy offline) để quét và ẩn số điện thoại, email, CCCD trước khi chuyển dữ liệu đi. |
| **Content Safety** | Trung bình | Tích hợp chung trong Guardrails | Sử dụng bộ lọc từ khóa cấm kết hợp kiểm duyệt bằng LLM prompt. |
| **Agentic Security** | Thấp | Không áp dụng | Bỏ qua để tiết kiệm tài nguyên hệ thống do ứng dụng không sử dụng kiến trúc gọi Tool tự do. |
