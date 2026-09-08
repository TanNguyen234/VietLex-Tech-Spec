# VietLex reviewer demo

Bản demo phục vụ đánh giá năng lực kỹ thuật, không phải tư vấn pháp lý hay chứng nhận production-ready. Danh sách chức năng còn thiếu: [chờ duyệt](UNFINISHED_FEATURES_REVIEW_20260908.md).

## Tour online 10–15 phút

Domain hiện có: https://vietlex-legal-rag.vercel.app . Kiểm tra có dòng **Demo reviewer** trước khi thử thao tác ghi; push Git thành công không tự chứng minh deployment thành công.

1. Chưa đăng nhập: xem giới thiệu, `/search` với số hiệu/tiêu đề, mở toàn văn, xem `/evaluation-lab` và các case/provenance. Dữ liệu online là slice 14.962 văn bản đã audit, không phải toàn corpus.
2. Đăng ký email riêng, xác minh và đăng nhập (SMTP phải được operator cấu hình). Không dùng chung tài khoản admin. Không dùng thông tin hợp đồng thật trong demo.
3. Hỏi một câu thuộc bộ ví dụ/corpus, mở evidence và retrieval inspector. Kiểm tra nguồn và trạng thái thiếu dữ liệu, không coi lời AI là kết luận pháp lý.
4. Tạo hồ sơ, ghim evidence từ interaction của mình, thêm ghi chú; thử phân tích evidence đã chọn, bảng nghĩa vụ hoặc so sánh. Ngân sách context nhỏ: giảm số evidence nếu thấy `evidence_scope_too_large`.
5. Tạo kế hoạch web, sửa truy vấn rồi bấm chạy rõ ràng. Kết quả hiện chỉ là metadata từ cổng Chính phủ; rỗng/lỗi không được hiểu là không có quy định.
6. Upload `docs/reviewer/sample-contract.txt`, chọn điều khoản và căn cứ luật rồi review. Mẫu là hư cấu; không dùng finding này làm tư vấn. Không có OCR.
7. Export dữ liệu từ tài khoản; kiểm tra chỉ có dữ liệu của mình. Đăng xuất/thu hồi phiên/xóa dữ liệu của chính mình khi cần. Không xóa dữ liệu của người khác hoặc tạo tải phá hoại.
8. Chủ dự án có thể tự mở admin để kiểm tra trace, context, trạng thái đánh giá và token coverage. Reviewer thông thường không được quyền admin.

Đây là checklist thao tác cho reviewer, không phải tuyên bố mọi bước đã chạy online trong phiên đóng gói. Kết quả đã chạy nằm trong báo cáo verification và bản ghi online riêng.

## Chính sách demo

- Khách chưa login: chỉ đọc/tra cứu; mutation bị chặn trước body/provider.
- Login yêu cầu tài khoản active và email đã xác minh; chức năng sản phẩm đã có giữ nguyên quyền owner/admin.
- AI/research: 3 lượt/phút và 20 lượt/ngày UTC/tài khoản; tối đa 100 lượt/ngày toàn demo. Bao gồm chat, phân tích, contract review, research run và yêu cầu evaluation. Đây là số lần thử, không phải token hay USD.
- Ghi thông thường: 15/phút, 100/ngày/tài khoản; toàn demo 1000/ngày. Đăng xuất, thu hồi phiên và xóa dữ liệu/tài khoản không bị quota chung này khóa.
- Auth (login/register/reset/verify): 5/phút, 15/ngày theo peer IP, 200/ngày toàn demo. Mỗi nhóm còn cap toàn cục 60/phút. Người dùng chung mạng có thể chia sẻ giới hạn auth.
- Mongo giữ counter nguyên tử theo người dùng/IP được hash và cửa sổ UTC, dùng chung giữa instance. Không refund lượt lỗi; nếu bước quota sau từ chối thì lượt giữ ở bước trước vẫn tính. Không đọc được auth/quota: 503, không gọi provider.
- Nhận body tối đa 15 giây, 2 mutation đang xử lý/instance; body thường 64 KiB, multipart dưới 4.000.000 byte. Chọn file dưới 3,7 MB để chừa multipart overhead. Parser còn memory/deadline riêng.
- Quota không phải đảm bảo chống bot/DDoS hoặc trần tiền. Read traffic và IP thật sau proxy phải được kiểm soát ở edge. Không tin header IP do client tự gửi.

## Chạy bản đã đóng gói

Python 3.12, trong thư mục project:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install --require-hashes -r requirements-demo.lock
.venv/Scripts/python -m pip install . --no-deps
# Tạo cấu hình riêng từ .env.example; không commit .env hoặc service-account JSON.
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Vercel dùng `app/server.py`; entrypoint bật demo mặc định. Docker cũng bật mặc định và chạy non-root. `REVIEWER_DEMO_MODE=false` là override có chủ đích của operator, không dùng cho public demo. Khi chạy `app.main` trực tiếp, đặt `REVIEWER_DEMO_MODE=true` như `.env.example`.

Docker (chưa chạy build trong phiên này):

```sh
docker build -t vietlex-reviewer .
docker run --rm -p 8000:8000 --env-file .env vietlex-reviewer
```

Online-only cần `SERVERLESS_ONLINE_ONLY=true`, `USE_LEGACY_FREE_PIPELINE=false`, MongoDB, Qdrant v3, Vertex và Supabase; cấu hình server-only như runbook. Persistent topology dùng volume corpus đúng contract; không trộn hai chế độ. Không có dữ liệu/secret thật trong gói. Wheel có templates/static nhưng immutable Evaluation Lab artifacts đi kèm source bundle, nên chạy từ thư mục project khi cần lab.

## Gate vận hành trước khi mở rộng reviewer

1. Bật/kiểm tra Vercel Bot Protection và WAF rate rules cho auth/chat/workspace mutations; thử browser hợp lệ để tránh chặn reviewer. Kiểm tra giới hạn tính năng theo plan, không tự mua gói.
2. Đặt cảnh báo/ngân sách chi phí ở nền tảng và provider; quota request không đo được chi phí từng lượt.
3. Kiểm tra IP thực sau proxy bằng evidence đã khử PII; chỉ trust proxy do operator kiểm soát.
4. Kiểm tra Mongo TTL index của `demo_usage`, phân quyền credentials tối thiểu, backup và retention. Không dùng khóa quản trị vector cho reviewer.
5. Kiểm tra root có notice, `/healthz`, `/readyz`, admin deny, anonymous chat deny; sau đó reviewer có tài khoản thật kiểm tra flow và quota với ngân sách được duyệt.
6. Nếu bị abuse, đóng traffic/mutation ở WAF hoặc tạm dừng deployment; không tắt chế độ demo để vượt lỗi quota. Không xóa/reingest index để xử lý sự cố demo.

Nguồn nền tảng: [Vercel Functions limits](https://vercel.com/docs/functions/limitations), [Vercel Firewall](https://vercel.com/docs/vercel-firewall). Vercel có giới hạn body 4,5 MB; giới hạn app được đặt thấp hơn. Trạng thái WAF thực tế chưa được xác minh.
