# Vercel public gateway

Vercel chỉ làm cổng HTTPS mỏng. FastAPI, MongoDB và hai SQLite corpus phải chạy ở một backend luôn online có persistent disk. Không upload corpus local lên Vercel và không đưa corpus vào MongoDB.

## Triển khai

1. Build `Dockerfile` trên Render, Railway, Fly.io hoặc VPS có persistent volume.
2. Gắn volume vào `/data` và đặt `content_store.sqlite3`, `legal_fts.sqlite3` tại đó. Có thể đổi đường dẫn bằng biến môi trường.
3. Cấu hình toàn bộ secret ở backend, đặc biệt `MONGO_URL`, provider keys, `WEB_SESSION_SECRET`, `ADMIN_USERNAME` và `ADMIN_PASSWORD`.
4. Kiểm tra `GET /readyz` trả HTTP 200 trước khi mở public.
5. Import repository vào Vercel và đặt `BACKEND_ORIGIN=https://<backend-cua-ban>` trong Project Environment Variables.
6. Deploy Vercel. `vercel.json` chuyển mọi request qua function `api/proxy.py`, nên cookie ẩn danh, HTML và static assets vẫn cùng origin đối với trình duyệt.

## Ranh giới vận hành

- `PUBLIC_RAGAS_ENABLED=false` là mặc định. Chỉ bật khi backend đã có judge provider và ngân sách phù hợp.
- Quota Ragas trong process phù hợp demo một instance. Nếu scale nhiều instance, cần quota store dùng chung như Redis trước khi tăng traffic.
- NeMo do từng người dùng bật cho từng câu hỏi; mặc định tắt.
- Vercel proxy có timeout nền tảng. Backend vẫn phải giới hạn thời gian xử lý và rate limit.
- Không commit secret, service-account JSON, corpus hoặc file `.env`.
- Cấu hình này là gói sẵn sàng triển khai; repository không tuyên bố đã deploy nếu chưa có URL và kiểm tra live.
