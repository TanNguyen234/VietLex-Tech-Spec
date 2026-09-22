# Tra cứu số hiệu và đường tiếp tục khi kho dữ liệu lỗi — 22/09/2026

Runtime `dcc3d3a`. Phạm vi: metadata search/reader và UI phục hồi; không thay đổi corpus, vector, nguồn đã ghim hoặc trạng thái hiệu lực.

## Lỗi và sửa

Trên corpus v3 local, `68/2026/TT-BXD` không có số hiệu khớp nhưng trước sửa trả 20 văn bản khác vì FTS tiếp tục tìm các token rời của số hiệu trong tiêu đề. Sau sửa, query chứa số hiệu đầy đủ chỉ tra `document_number` chuẩn hóa. Cả SQLite FTS, SQLite có filters và Supabase adapter đặt điều kiện số hiệu trước `LIMIT`; không lọc một trang candidate đã cắt. Query không chứa số hiệu vẫn dùng tìm tiêu đề như cũ. Không có kết quả trả HTTP 200, cho người dùng tự chuyển nguyên câu hỏi sang hồ sơ. Lỗi backend trả HTML 503/no-store với retry và đường tiếp tục; không tự gọi AI hay đổi retrieval backend.

## Kiểm chứng

- TDD: ba test mới ban đầu **3 failed** trên FTS, SQLite filtered và Supabase query; sau sửa **3 passed**. Nhóm `test_legal_fts.py`, `test_legal_browser.py`, `test_legal_routes.py`: **37 passed, 2 warnings**. Test dùng fixture/MockTransport; không phải online Supabase.
- Corpus v3 local thật: `68/2026/TT-BXD` → `[]`, `45/2019/QH14` → ID `333670`, filter `sort=newest` với số hiệu thiếu → `[]`.
- Chrome local, mobile 390×844: số hiệu thiếu trả 200/0 kết quả, link hiển thị, không tràn ngang, query giữ nguyên trong trường hồ sơ; không submit AI. [Kết quả JSON](local-empty-search.json) và [ảnh thật](local-empty-search-mobile.png). Server chạy `APP_ENV=test`, `SERVERLESS_ONLINE_ONLY=false`, `--lifespan off`; query đọc SQLite thật và trang hồ sơ đọc Mongo thật. Lượt đầu search đã hiển thị đúng 0 kết quả nhưng trang hồ sơ 500 vì DNS MongoDB của host; lượt sau dùng DNS over HTTPS trong process kiểm tra và toàn script đạt. Lượt thất bại không được tính passed.
- Outage Chrome local, desktop 1440×1050 và mobile 390×844: metadata search, body search, reader đều HTML 503/no-store; query đi vào hồ sơ, không tràn ngang, không page errors. [JSON](local-outage.json), [desktop](local-outage-desktop.png), [mobile](local-outage-mobile.png). Server chạy `APP_ENV=test`, `SERVERLESS_ONLINE_ONLY=true`, `--lifespan off`; request Supabase thất bại thật, không mock backend.
- Sau push `dcc3d3a` lên `origin/main`, domain canonical production trả HTML 503/no-store mới cho số hiệu `68/2026/TT-BXD` ([HTTP JSON](production-exact-number.json)). Chrome production kiểm tra ba URL metadata/body/reader đều 503/no-store; nút chuyển query sang hồ sơ hoạt động, desktop/mobile không tràn ngang, không page errors. [JSON](production-outage.json), [desktop](production-outage-desktop.png), [mobile](production-outage-mobile.png). Đây là **outage recovery hoạt động**, không phải search online thành công.
- Ruff các file đổi: **PASS**. Full provider-free suite sau review source: **1.378 passed, 4 skipped, 31 warnings**, 333,62 giây. JUnit local: `tmp/continuation-20260922/full.xml`. Skipped không phải passed. Chưa có benchmark pháp lý mới.
- Artifact gate: **PASS**. Ruff quét mọi file trong `app tests` báo 11 lỗi style ở `tests/visual/redesign_preview.py` chưa tracked và không thuộc thay đổi này; Ruff trên toàn bộ Python tracked: **PASS**. Không sửa file visual ngoài phạm vi để làm đẹp gate.

## Online và giới hạn

Supabase project ref `jtldmpnghdzitvkbvald` vẫn là blocker từ 21/09: DNS đã được đối chiếu hai resolver và REST ConnectError trong bằng chứng trước; không lặp truy vấn chỉ để tăng số lần đo. Trang quản trị trong phiên này chuyển sang đăng nhập; không có Management API token, nên chưa xác định project paused, deleted hay URL sai. Cần chủ project đăng nhập Supabase Dashboard để xác nhận trạng thái và khôi phục đúng project/URL, sau đó mới chạy search/reader và import/RPC online. Không đổi hostname theo suy đoán, không chạy migration hoặc full ingestion. Vercel CLI ban đầu `fetch failed` do Node TLS; sau khi dùng system CA, CLI cho biết chưa đăng nhập. [GitHub commit status](vercel-commit-status.json) của `dcc3d3a` có context `Vercel=success` và trỏ tới [deployment](https://vercel.com/foxys-projects-5fe642e0/vietlex-legal-rag/3uWTDheqwG3DunUyJbrgKyG3tZrW); domain canonical trả giao diện mới. Cờ **Ready trong Vercel Dashboard chưa được quan sát trực tiếp** vì thiếu phiên đăng nhập, nên không gán deployment ID riêng khi chưa có build log.

HTTP 503 có UX tiếp tục không chứng minh search online hoạt động. Việc query rỗng trên corpus local 4.969 văn bản không chứng minh văn bản không tồn tại ở nguồn chính thức hoặc trong toàn 518.255 văn bản. Không có review pháp lý tự động cho câu trả lời.

## Lệnh đã chạy

```powershell
.venv\Scripts\python.exe -m pytest -q tests/ingestion/test_legal_fts.py::test_full_document_number_never_falls_back_to_title_terms tests/services/test_legal_browser.py::test_local_full_number_filters_before_limit tests/services/test_legal_browser.py::test_supabase_full_number_uses_number_only_before_limit
.venv\Scripts\python.exe -m pytest -q tests/ingestion/test_legal_fts.py tests/services/test_legal_browser.py tests/test_legal_routes.py
.venv\Scripts\python.exe -m ruff check app/ingestion/legal_fts.py app/services/legal_browser.py app/api/legal_routes.py tests/ingestion/test_legal_fts.py tests/services/test_legal_browser.py tests/test_legal_routes.py
.venv\Scripts\python.exe -m pytest -q --junitxml=tmp/continuation-20260922/full.xml
.venv\Scripts\python.exe tmp/continuation-20260921/empty_search_browser.py
.venv\Scripts\python.exe tmp/continuation-20260921/outage_browser.py
.venv\Scripts\python.exe tmp/continuation-20260921/outage_browser.py https://vietlex-legal-rag.vercel.app
.venv\Scripts\python.exe scripts/check_repository_artifacts.py
.venv\Scripts\python.exe -m ruff check app tests
$paths = @(git -c safe.directory=D:/Download/ProfessionalLegalRAG ls-files -- '*.py'); .venv\Scripts\python.exe -m ruff check @paths
git -c safe.directory=D:/Download/ProfessionalLegalRAG push origin main
```

Browser scripts cần server 8781/8782 có `/healthz` 200 trước khi chạy. `--lifespan off` được dùng để tách startup Mongo/network khỏi kiểm tra HTTP/UI, không phải kiểm chứng readiness đầy đủ.
