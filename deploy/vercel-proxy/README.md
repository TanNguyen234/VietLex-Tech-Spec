# Vercel online-only SSR

The directory name is retained for compatibility with older links. Vercel is
no longer only a proxy: it runs the FastAPI/Jinja application directly through
`app/server.py`.

Vercel chạy trực tiếp ứng dụng FastAPI/Jinja SSR qua `app/server.py`. Chế độ
`SERVERLESS_ONLINE_ONLY=true` dùng Qdrant v3, Vertex AI và MongoDB
online; không đóng gói hoặc đọc SQLite corpus từ máy local.

## Cấu hình production

- `APP_ENV=production`
- `SERVERLESS_ONLINE_ONLY=true`
- `USE_LEGACY_FREE_PIPELINE=false`
- `FRONTEND_URL=https://<domain-vercel>`
- `PUBLIC_BASE_URL=https://<domain-vercel>`
- `WEB_SESSION_SECRET=<ít nhất 32 ký tự>`
- `MONGO_URL`, `QDRANT_URL`, `QDRANT_API_KEY`
- `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`
- `GOOGLE_SERVICE_ACCOUNT_JSON` chứa JSON service account đầy đủ

Pinecone credentials chỉ cần nếu chủ động cấu hình contract legacy/free hoặc
fallback liên quan; chúng không phải dependency retrieval của v3 online-only.

Không upload `.env`, service-account file, `data/`, tests, reports hoặc corpus.
`/healthz` chỉ chứng minh process phục vụ HTTP; `/readyz` kiểm tra MongoDB và
cấu hình retrieval online mà không phát sinh provider call trả phí.

Các trang `/search` và `/documents/{id}` dùng Supabase trong online-only, trên slice 14.962 văn bản đã audit. Chat lấy evidence trực tiếp từ Qdrant v3 payload.

Bản reviewer dùng `requirements-demo.lock`, demo admission và quota Mongo chia sẻ giữa instance. Xem `docs/REVIEWER_GUIDE.md` để cấu hình, quyền truy cập và các gate WAF/online chưa xác minh.

Production alias đã kiểm tra ngày 2026-09-01:
<https://vietlex-legal-rag.vercel.app>. Health/readiness/chat smoke không phải
bằng chứng production-readiness; xem `docs/evaluation/CURRENT_STATUS.md` để biết
benchmark và giới hạn hiện tại.
