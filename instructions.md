# Hướng dẫn phát triển VietLex

Updated: 2026-09-01. Xem
[`docs/DOCUMENTATION_INDEX.md`](docs/DOCUMENTATION_INDEX.md) để chọn đúng tài
liệu hiện hành.

## Thiết lập persistent/local

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Chỉ cấu hình credential trong `.env` hoặc secret storage của nền tảng.
`app/config.py` là nguồn cấu hình runtime; không hardcode hoặc ghi secrets vào
log, manifest hay tài liệu.

## Hai runtime contract

- `USE_LEGACY_FREE_PIPELINE=false` là mặc định: Vertex
  `gemini-embedding-2` 1024d truy vấn Qdrant v3 bằng dense+sparse IDF/raw RRF;
  generation dùng Vertex `gemini-3.5-flash` primary.
- `USE_LEGACY_FREE_PIPELINE=true`: dùng Pinecone v1 + local SQLite FTS,
  Qdrant E5-small/ColBERT và chặn Google Cloud trước khi tạo client. “Free” chỉ
  có nghĩa không gọi Google Cloud; direct-API fallback vẫn có quota/chi phí.

Không có silent fallback từ Qdrant v3 sang Pinecone v1.

## Deployment

- Vercel: `SERVERLESS_ONLINE_ONLY=true`, entry point `app/server.py`, FastAPI/
  Jinja SSR trực tiếp. Chat đọc evidence từ Qdrant payload; không đóng gói local
  corpus. `/search` và `/documents/{id}` không thuộc contract này.
- Persistent host/Docker: `SERVERLESS_ONLINE_ONLY=false`; readiness yêu cầu
  content store và FTS phù hợp với runtime được chọn.

Runbook: [`docs/runbooks/DEPLOYMENT.md`](docs/runbooks/DEPLOYMENT.md).

## Corpus và destructive boundary

Corpus được khóa tại revision
`4d4e10b201544e8a4c49a1d3fa496595a7d486d0`, tổng cộng 518.255 document IDs.
Qdrant v3 hiện chỉ có 51.801 point của đúng 4.969 document IDs; không gọi đó là
full corpus.

Các pha provider-free:

```powershell
python -m app.ingestion.hf_pipeline download
python -m app.ingestion.hf_pipeline prepare
python -m app.ingestion.hf_pipeline smoke
python -m app.ingestion.hf_pipeline verify
```

`full --delete-existing --yes`, remote upload, collection/index creation và
reingestion là destructive/live operations, chỉ chạy khi có quyền rõ ràng cho
đúng thao tác. Không sửa checkpoint thủ công.

## Request flow mặc định v3

1. CSRF, rate limit, ownership và PII redaction.
2. Grounded semantic-cache lookup theo corpus/pipeline fingerprint.
3. Optional input guardrail theo mode `off`, `shadow` hoặc `enforce`.
4. Original query vào sparse/exact lane; rewrite mặc định tắt.
5. Vertex dense query + Qdrant v3 dense/sparse-IDF fusion bằng raw RRF.
6. Tối đa 3 payload evidence point trong 720 context tokens.
7. Grounded answer, optional output guardrail, typed diagnostics và persistence.

Online `/chat` không tự chạy Ragas. Deterministic metrics là mặc định; Ragas
chỉ là offline opt-in judge.

## Kiểm tra trước bàn giao

```powershell
python -m pytest -q
python -m compileall -q app tests
python -m ruff check app
git diff --check
```

Live-provider evaluation không thuộc default tests. Golden-50 reproducible
commands nằm tại
[`docs/evaluation/golden50-v3/README.md`](docs/evaluation/golden50-v3/README.md).
