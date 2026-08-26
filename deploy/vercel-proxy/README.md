# Vercel public gateway

Vercel chỉ làm cổng HTTPS mỏng. FastAPI, MongoDB và hai SQLite corpus phải chạy ở một backend luôn online có persistent disk. Không upload corpus local lên Vercel và không đưa corpus vào MongoDB.

## Triển khai

1. Build `Dockerfile` trên Render, Railway, Fly.io hoặc VPS có persistent volume.
2. Gắn volume vào `/data` và đặt `content_store.sqlite3`, `legal_fts.sqlite3` tại đó. Có thể đổi đường dẫn bằng biến môi trường.
3. Cấu hình toàn bộ secret ở backend, đặc biệt `MONGO_URL`, provider keys, `WEB_SESSION_SECRET`, `ADMIN_USERNAME` và `ADMIN_PASSWORD`. Đặt `APP_ENV=production`, `FRONTEND_URL=https://<domain-vercel>` và `PUBLIC_BASE_URL=https://<domain-vercel>`; nếu bật email thì thêm `ACCOUNT_EMAIL_ENABLED=true`, `EMAIL_USER`, `EMAIL_PASS`, `EMAIL_FROM`.
4. Kiểm tra `GET /readyz` trả HTTP 200 trước khi mở public.
5. Import repository vào Vercel và đặt `BACKEND_ORIGIN=https://<backend-cua-ban>` trong Project Environment Variables.
6. Deploy Vercel. `vercel.json` chuyển mọi request qua function `api/proxy.py`, nên cookie ẩn danh, HTML và static assets vẫn cùng origin đối với trình duyệt.

Vercel project không cần Install Command hay Build Command. `.vercelignore` dùng allowlist chỉ đưa `api/` và `vercel.json` lên deployment, vì proxy chỉ dùng Python standard library; không đưa `requirements.txt`, `app/`, tests, corpus hoặc model dependencies vào function bundle. Function timeout được đặt 60 giây và origin timeout 55 giây.

Kiểm tra sau deploy:

```text
GET https://<domain-vercel>/healthz  -> 200
GET https://<domain-vercel>/readyz   -> 200, MongoDB/content_store/legal_fts ready
GET https://<domain-vercel>/          -> HTML có data-progress-transport="polling"
```

## Ranh giới vận hành

- `PUBLIC_RAGAS_ENABLED=false` là mặc định. Chỉ bật khi backend đã có judge provider và ngân sách phù hợp.
- Quota Ragas trong process phù hợp demo một instance. Nếu scale nhiều instance, cần quota store dùng chung như Redis trước khi tăng traffic.
- NeMo do từng người dùng bật cho từng câu hỏi; mặc định tắt.
- Vercel proxy có timeout nền tảng. Backend vẫn phải giới hạn thời gian xử lý và rate limit.
- Vercel Python proxy buffer upstream responses, nên gateway đánh dấu request bằng `gateway=vercel` và UI dùng polling progress 1 giây. Chỉ client truy cập FastAPI trực tiếp mới dùng SSE.
- Không commit secret, service-account JSON, corpus hoặc file `.env`.
- Cấu hình này là gói sẵn sàng triển khai; repository không tuyên bố đã deploy nếu chưa có URL và kiểm tra live.
