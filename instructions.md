# Hướng dẫn phát triển và thiết lập VietLex Legal RAG

## Thiết lập

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Chỉ cấu hình credential trong `.env`. `app/config.py` là nguồn duy nhất đọc
Pinecone, Qdrant inference, embedding/reranking, OmniGate, MongoDB và Logfire
secrets.

## Cấu trúc chính

```text
app/
├── main.py
├── config.py
├── api/
├── ingestion/
│   ├── dataset_snapshot.py
│   ├── legal_text.py
│   ├── sparse_encoder.py
│   ├── content_store.py
│   ├── checkpoint.py
│   ├── pinecone_store.py
│   ├── qdrant_inference.py
│   └── hf_pipeline.py
├── services/
│   ├── clients.py
│   ├── retrieval.py
│   ├── rag_pipeline.py
│   ├── semantic_cache.py
│   ├── guardrails.py
│   └── evaluator.py
└── templates/
```

## Chuẩn bị corpus

Corpus được khóa tại revision
`4d4e10b201544e8a4c49a1d3fa496595a7d486d0` và phải có đúng 518.255 metadata
IDs/content IDs được join theo `id`.

```powershell
python -m app.ingestion.hf_pipeline download
python -m app.ingestion.hf_pipeline prepare
python -m app.ingestion.hf_pipeline smoke
```

Sau khi tất cả gate đạt:

```powershell
python -m app.ingestion.hf_pipeline full --delete-existing --yes
python -m app.ingestion.hf_pipeline verify
```

Không sửa checkpoint thủ công. Khi gián đoạn, chạy lại chính lệnh `full`; point
ID là UUIDv5 deterministic và completed batches được bỏ qua.

## Request flow

1. CSRF, rate limit và PII redaction.
2. Semantic cache revision-aware, similarity tối thiểu 0,96.
3. Input guardrail.
4. Query rewrite.
5. Tạo query embedding bằng Qdrant staging rồi chạy một Pinecone hybrid query.
6. Resolve full candidate documents từ local content store.
7. Dynamic legal/fallback chunking và lexical top 64.
8. BGE-reranker-v2-M3 lấy top 3 evidence.
9. Grounded answer, output guardrail, log/evaluation/cache.

## Quy tắc nguồn dữ liệu

Dataset là nguồn nghiên cứu bên thứ ba, không phải cơ sở dữ liệu chính thức và
không chứng minh văn bản còn hiệu lực. Không được biến việc có mặt trong dataset
thành kết luận pháp lý. Answer phải dẫn số văn bản/Điều/Khoản/URL khi có, nêu rõ
bất định và yêu cầu kiểm tra nguồn chính thức hiện hành hoặc người có chuyên môn.
Kết quả không phải tư vấn pháp lý.

## Kiểm tra trước bàn giao

```powershell
python -m pytest -q
python -m compileall -q app scripts tests
git diff --check
```

Chi tiết recovery, quota và reconciliation nằm trong
`docs/huggingface-ingestion-runbook.md`.
