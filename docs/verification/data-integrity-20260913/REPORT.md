# Data integrity — 13/09/2026

Runtime `d80abc2` sửa hai lỗi có bằng chứng:

1. Rename, pin, unpin, save analysis, full review batch và remove document thiếu expiry predicate tại atomic write. Route có thể đọc hồ sơ còn hạn nhưng công việc hoàn tất sau khi hết hạn. MongoDB thật trước sửa chấp nhận cả **6/6** ghi trên bản ghi đã hết hạn; sau sửa **6/6 bị từ chối**, trong khi **6/6 ghi hợp lệ vẫn thành công**. Bản ghi hết hạn vẫn tồn tại khi probe kết thúc, nên kết quả không do TTL xóa trước. Giữ `red.json` và `green.json`.
2. Official evidence ID trước đây chỉ phụ thuộc URL + quote, nên hai phiên bản PDF dùng cùng URL và cùng đoạn không thể ghim riêng. ID mới gồm URL, hash toàn PDF (HTML dùng hash text) và exact quote. Hai nhóm trang cùng PDF vẫn dùng cùng ID; khác hash PDF cho ID khác. Không đổi ID hoặc dữ liệu đã lưu, không promotion hiệu lực. Đây là test hàm thuần, chưa có hai phiên bản lịch sử thực cùng URL để nghiệm thu live.

## Kiểm thử

- RED thuần: `tests/test_official_evidence_identity.py` import helper chưa có thất bại; sau sửa pass.
- Mongo thật: `.venv/Scripts/python.exe tmp/data-integrity-20260913/mongo_probe.py tmp/data-integrity-20260913/green.json`: **12/12 đạt**, không mock database, không gọi model. Probe chỉ tạo UUID test riêng với TTL; không sửa hay xóa hồ sơ người dùng. File script kèm yêu cầu output path mới; không ghi đè báo cáo này khi tái chạy.
- Focused reader/routes/full-review: **41 passed**. Hai assertion owner/atomic cũ không tính expiry làm lượt full đầu fail: **2 failed, 1282 passed**. Cập nhật assertions kiểm tra timestamp expiry và giữ nguyên các điều kiện owner/size/atomic.
- Full cuối: **1284 passed, 30 warnings**, 223.33 giây, exit 0; `full-final.log`/`full-final-process.json` giữ command và output. Suite provider-free có doubles của unit tests hiện có; không dùng nó làm bằng chứng database/provider thật.
- Review diff phát hiện đọc file bằng encoding mặc định Windows làm hỏng ba nhãn metadata tiếng Việt; đã phục hồi chính xác từ Git UTF-8 trước kiểm thử cuối. Diff cuối chỉ thêm helper, không đổi nhãn parser.

```powershell
.venv/Scripts/python.exe -m pytest tests --ignore=tests/integration --ignore=tests/visual -q -p no:cacheprovider --basetemp=tmp/data-integrity-20260913/pytest-final --junitxml=tmp/data-integrity-20260913/full-final.xml
```

## Chưa đạt toàn bộ report

Probe Supabase thật với hai cụm “Điều 25. Thời gian thử việc” và “bảo vệ dữ liệu cá nhân” trả HTTP 500, mã PostgreSQL 57014, statement timeout (~3–5 giây). Truy vấn “thử việc” limit 1 trả 200 không chứng minh scan body ổn định. OpenAPI hiện không có RPC; schema code chỉ có index số hiệu/hash. Khóa REST có sẵn nhưng máy chưa có kết nối quản trị SQL. Không bật một nhãn full-text dựa trên scan lỗi.

Đường sửa cần index phù hợp và readback/latency benchmark trước bật: [PostgreSQL pg_trgm hỗ trợ LIKE/ILIKE](https://www.postgresql.org/docs/17/pgtrgm.html), [Supabase full-text với GIN](https://supabase.com/docs/guides/database/full-text-search). Chưa thực thi schema mới, chưa mở rộng corpus hoặc chứng nhận hiệu lực. Logfire token 401 và 30 deprecation warnings chưa sửa; không đánh dấu project zero-error.

## Triển khai và kiểm tra tiếp nối

`d80abc2` đã push và triển khai (`dpl_58oYg3vXLYW4tTNFSxmuyUWvwLx8`). Bản OCR tiếp theo `f1a1b2d` giữ nguyên các sửa đổi integrity; production kiểm tra ID nguồn khớp hợp đồng mới, ghim 200, ghim trùng 409 và reader 200/no-store. Xem [bằng chứng OCR và production](../ocr-output-20260913/REPORT.md). Hai phiên bản PDF lịch sử khác nhau tại cùng URL vẫn chưa có live fixture để nghiệm thu.

## Publication boundary

Raw response, model output, logs and diagnostic runners referenced above are retained locally; they are not published in this commit. The manifest records their hashes for local verification. Published evidence is limited to this curated report, aggregate results where present and public-source references. Production workspace identifiers and cookie values are excluded. This restricts public reproducibility; it does not turn summaries into raw evidence.
