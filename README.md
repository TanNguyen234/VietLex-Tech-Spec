# VietLex Advanced Legal RAG - Trợ lý Pháp luật Việt Nam

Hệ thống RAG nâng cao truy vấn văn bản luật Việt Nam (phân tách Chương -> Mục -> Điều) được xây dựng theo kiến trúc sạch (Clean Architecture) sử dụng FastAPI, Qdrant Cloud, NeMo Guardrails, Logfire, Ragas, MongoDB và giao diện Web SSR hiện đại (HTMX + TailwindCSS + Phosphor Icons).

---

## 🚀 Các Tính Năng Cốt Lõi

1. **Bộ Nhớ Đệm Ngữ Nghĩa (Semantic Cache)**:
   * Thực hiện tìm kiếm vector trên Qdrant với embedding `text-embedding-004`.
   * Trả kết quả tức thời khi độ tương đồng đạt ngưỡng tin cậy >= 0.96, giúp tối ưu chi phí API và giảm độ trễ phản hồi xuống mức mili-giây.

2. **Quy Trình Tìm Kiếm & Sinh Văn Bản Nâng Cao (Advanced Retrieval)**:
   * **Truy vấn viết lại (Query Rewrite)**: LLM tự động tối ưu hóa và chuyển đổi ngôn từ của người dùng sang ngôn ngữ pháp lý chính thống.
   * **Tìm kiếm hỗn hợp (Hybrid Search)**: Kết hợp tìm kiếm Dense (mô hình embedding Google) và Sparse (BM25 phân tách từ bằng thư viện tiếng Việt `PyVi`) trên Qdrant.
   * **Hợp nhất RRF (Reciprocal Rank Fusion)**: Gom nhóm và tính điểm kết quả từ hai kênh tìm kiếm.
   * **Reranker**: Cohere `rerank-multilingual-v3.0` thực hiện sắp xếp lại, chọn ra Top 3 ngữ cảnh chính xác nhất để làm prompt context.
   * **Generator**: Sử dụng model `legal-core-model` (Meta Llama 3.3 70B Instruct trên cổng OmniGate) để sinh câu trả lời chuẩn xác.

3. **Cơ Chế Bảo Mật & Kiểm Duyệt Tích Hợp (NeMo Guardrails)**:
   * **Topic Control**: Phát hiện và chặn câu hỏi ngoài lề (off-topic) như viết code, nấu ăn, tán gẫu để giữ bot luôn đúng vai trò trợ lý pháp lý.
   * **Jailbreak Protection**: Chống bẻ khóa prompt (Prompt Injection) ở đầu vào.
   * **Content Safety**: Kiểm duyệt từ ngữ toxic, thù địch hoặc bất hợp pháp ở cả đầu vào và đầu ra.
   * **Hallucination Check**: Đối chiếu câu trả lời của mô hình với tài liệu luật gốc để phát hiện và ngăn chặn ảo giác (AI tự bịa luật).
   * **PII Redaction (Ẩn thông tin cá nhân)**: Tự động phát hiện và che giấu SĐT, Email, số CCCD/CMND bằng tiếng Việt để bảo mật quyền riêng tư theo Nghị định 13/2023/NĐ-CP.

4. **Quản Lý Lịch Sử & Đánh Giá Chất Lượng (Admin Dashboard)**:
   * Lưu trữ toàn bộ tương tác người dùng, ngữ cảnh luật đã dùng, safety checks, và feedback người dùng vào cơ sở dữ liệu MongoDB Atlas.
   * Chạy ngầm đánh giá Ragas LLM-as-a-judge (đo lường Faithfulness và Answer Relevance) sau mỗi lượt chat.
   * Cung cấp giao diện quản trị Admin hiển thị biểu đồ KPI và chi tiết log hội thoại trực quan bằng HTMX.

---

## 📁 Cấu Trúc Dự Án (Clean Architecture)

```text
vietlex-rag/
├── app/
│   ├── main.py                # Khởi chạy FastAPI, cấu hình Middleware & Logfire
│   ├── config.py              # Quản lý cấu hình biến môi trường qua Pydantic Settings
│   ├── database.py            # Kết nối & truy vấn MongoDB Atlas bất đồng bộ
│   ├── api/
│   │   ├── routes.py          # Routing chính cho chat UI, feedback & Admin API
│   │   └── dependencies.py    # Verify CSRF Token cho HTMX requests
│   ├── services/
│   │   ├── rag_pipeline.py    # Quy trình tìm kiếm nâng cao (Rewrite, Hybrid, RRF, Rerank)
│   │   ├── semantic_cache.py  # Tìm kiếm & lưu trữ bộ nhớ đệm ngữ nghĩa trên Qdrant
│   │   ├── guardrails.py      # Bộ lọc an toàn Input/Output & Ẩn thông tin cá nhân (PII)
│   │   └── evaluator.py       # Tác vụ chạy nền đánh giá chất lượng Ragas
│   ├── ingestion/
│   │   ├── parser.py          # Phân tách tài liệu pháp luật (Chương -> Mục -> Điều)
│   │   └── indexer.py         # PyVi Tokenizer & Import dữ liệu lên Qdrant Cloud
│   └── templates/
│       ├── index.html         # Giao diện khung Chat người dùng
│       ├── chat_message.html  # Khối tin nhắn HTMX động
│       ├── admin.html         # Khung giao diện Admin Dashboard
│       ├── admin_stats.html   # Các card số liệu KPI thống kê
│       ├── admin_logs.html    # Bảng nhật ký hội thoại có thanh tìm kiếm live
│       └── admin_details.html # Modal chi tiết log tương tác & Ragas score
├── requirements.txt
├── .env                       # File cấu hình môi trường bảo mật
└── README.md
```

---

## 🛠️ Hướng Dẫn Cài Đặt & Khởi Chạy

### 1. Cấu hình biến môi trường
Tạo file `.env` ở thư mục gốc của dự án với các thông số sau:
```env
# Server
HOST=0.0.0.0
PORT=8000
FRONTEND_URL=http://localhost:8000

# Qdrant Database
QDRANT_URL=https://your-qdrant-endpoint.gcp.cloud.qdrant.io
QDRANT_API_KEY=your_qdrant_api_key

# Cohere API Key
COHERE_API_KEY=your_cohere_api_key

# LLM Gateway (OmniGate)
OMNIGATE_BASE_URL=https://llmgateway.onrender.com
LITELLM_MASTER_KEY=your_litellm_master_key

# MongoDB
MONGO_URL=mongodb+srv://your-mongodb-atlas-uri/Legal-RAG

# Logfire (Tùy chọn)
LOGFIRE_TOKEN=your_logfire_token
```

### 2. Thiết lập Môi trường ảo Python
```powershell
# Khởi tạo venv
python -m venv .venv

# Kích hoạt venv
.venv\Scripts\Activate.ps1

# Nâng cấp pip và cài đặt dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Nạp dữ liệu văn bản luật (Ingestion)
Chuẩn bị tệp văn bản luật trong thư mục và chạy script indexer để đẩy dữ liệu lên Qdrant:
```powershell
.venv\Scripts\python -m app.ingestion.qdrant_indexer
```

### 4. Khởi chạy Web Server (SSR)
Chạy server FastAPI cục bộ:
```powershell
.venv\Scripts\python -m uvicorn app.main:app --port 8000 --host 127.0.0.1
```
* Giao diện Chat: `http://localhost:8000`
* Trang quản trị Admin: `http://localhost:8000/admin`

---

## 🧪 Quy trình Kiểm thử (Verification & Testing)

Để kiểm tra toàn bộ luồng chức năng tự động (không mock), hãy chạy bộ test có sẵn:
```powershell
.venv\Scripts\pytest
```

Hoặc bạn có thể thực hiện kiểm thử thủ công qua trình duyệt:
1. **Kiểm tra Chat**: Gửi câu hỏi pháp luật (ví dụ: "Thủ tục thành lập công ty TNHH?") tại trang chủ và đợi câu trả lời từ RAG.
2. **Kiểm tra Cache**: Gửi lại chính xác câu hỏi đó, phản hồi sẽ trả về ngay lập tức với nhãn "Cache".
3. **Kiểm tra Guardrails**: Gửi câu hỏi lạc đề (ví dụ: "Làm thế nào để luộc trứng?") hoặc chửi bậy, hệ thống sẽ chặn và hiển thị câu thông báo từ chối tương ứng.
4. **Kiểm tra PII**: Nhập câu hỏi chứa số điện thoại hoặc email (ví dụ: "Tôi tên Nam, sđt là 0912345678, cần tư vấn ly hôn..."). Hệ thống sẽ tự động che đi thông tin nhạy cảm thành `[SĐT_ĐÃ_ẨN]` trước khi lưu database/gửi tới LLM.
5. **Kiểm tra Admin**: Truy cập `/admin`, tìm kiếm câu hỏi vừa nhập, nhấp nút **Chi tiết** để xem thông số kiểm duyệt, các contexts luật trích xuất và điểm đánh giá Ragas.
