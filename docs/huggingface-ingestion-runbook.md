# Pinecone Full-Corpus Ingestion Runbook

## Phạm vi

Pipeline nạp 518.255 văn bản từ snapshot
`vohuutridung/vietnamese-legal-documents@4d4e10b201544e8a4c49a1d3fa496595a7d486d0`
vào Pinecone index `vietlex-legal-rag-v1`, namespace `legal-documents-v1`.

Dataset là nguồn nghiên cứu bên thứ ba, không phải nguồn pháp luật chính thức,
không xác nhận hiệu lực hiện hành và không thay thế tư vấn pháp lý.

## Điều kiện

1. Python 3.10+ và dependencies đã được cài.
2. `.env` có `PIPECONE_API` hoặc `PINECONE_API_KEY`.
3. `.env` có URL/key của cluster Qdrant Cloud đang ở trạng thái Ready.
4. Snapshot và content store nằm trên ổ D; không chạy hai full process chung
   checkpoint.
5. Pinecone organization còn đủ storage và write units. Starter có giới hạn
   2 GB cho toàn organization, không chỉ riêng index này.

## Vai trò từng dịch vụ

- Qdrant Cloud: sinh E5-small và rerank ColBERT qua các collection staging nhỏ.
- Pinecone: persistent dense+sparse vectors và semantic-cache namespace.
- SQLite/Zstandard: full legal text và provenance.
- Pinecone Inference: BGE-reranker-v2-M3 fallback khi Qdrant tạm lỗi.

Staging dùng ID cố định, vector on-disk, `m=0` và `indexing_threshold=0`; mỗi
window ghi đè các ID cũ rồi chuyển vectors sang Pinecone.

## Chuẩn bị dữ liệu

Chỉ chạy nếu local artifacts chưa có hoặc cần dựng lại:

```powershell
python -m app.ingestion.hf_pipeline download
python -m app.ingestion.hf_pipeline prepare
```

Download hỗ trợ HTTP Range và kiểm tra SHA-256. Prepare stream Parquet bằng
PyArrow, join metadata/content theo integer ID và ghi SQLite/Zstandard bằng
atomic replace. Gate thành công yêu cầu đúng 518.255 metadata, content và joined
documents, không missing ID hoặc empty-content blocker.

## Full reset và ingestion

```powershell
python -u -m app.ingestion.hf_pipeline full --delete-existing --yes
```

Ở một run mới, hai flag xác nhận các side effect sau:

- xóa/recreate Pinecone index `vietlex-legal-rag-v1`;
- reset collection Qdrant staging nhỏ, không lưu corpus ở Qdrant.

Ingestion dùng batch 128, concurrency 16. Mỗi Pinecone record gồm:

- dense vector 384 chiều từ `intfloat/multilingual-e5-small`;
- lexical sparse vector tối đa 64 non-zero values;
- deterministic UUIDv5;
- document ID, content-store key, revision và SHA-256;
- không có full content, title hoặc source text.

Representation-v2 dùng một dense input ngắn theo thứ tự metadata, outline rồi
nội dung đại diện (tối đa 420 whitespace tokens/2.400 ký tự). Sparse input được
tạo độc lập từ metadata, outline và full text tối đa 2.048 terms; không còn tái
sử dụng dense text đã rút gọn. Vẫn chỉ có một vector record/document.

Nếu namespace đã ingestion hoàn tất bằng representation trước đó, runtime mới
vẫn tương thích. Chỉ rebuild khi chủ động muốn áp dụng representation-v2 và đã
chấp nhận xóa index/checkpoint tương ứng; không cần rebuild cho chunking,
candidate selection, reranking hay context budget vì các bước đó chạy ở query
time.

Pinecone SDK v9 dùng native gRPC/HTTP2 cho upsert. Pipeline retry hữu hạn với
exponential backoff khi gặp 429/timeout/503. Mỗi batch chỉ được đánh dấu complete
sau Pinecone success.

## Resume

Nếu process hoặc mạng bị ngắt, chạy lại đúng lệnh full. Không xóa:

- `data/huggingface/content_store.sqlite3`;
- `data/huggingface/pinecone_ingestion_state.sqlite3`;
- snapshot Parquet.

Checkpoint dùng batch IDs ổn định từ 0 đến 4048. Nếu batch size thay đổi hoặc
Pinecone index biến mất trong khi checkpoint có completed batches, pipeline
abort thay vì bỏ qua dữ liệu từ xa.

## Quota/capacity

- Pinecone batch cố định dưới giới hạn 2 MB/1.000 vector.
- Namespace upsert giới hạn 50 MB/s và 100 requests/s; cấu hình 16×128 nằm dưới
  các giới hạn request thiết kế, nhưng vẫn retry khi server throttle.
- Không dùng Pinecone hosted embedding nên không tiêu embedding-token quota.
- Pinecone hosted reranker chỉ là fallback; circuit breaker tránh lặp lại
  Qdrant timeout nhưng vẫn phải theo dõi inference quota của Pinecone.
- Nếu nhận `QUOTA_EXCEEDED`, không xóa checkpoint/local store; giải phóng index
  Pinecone khác hoặc nâng plan rồi chạy lại.

## Xác minh

Sau full-run:

```powershell
python -m app.ingestion.hf_pipeline verify
```

Verify dùng một stats call và một fetch 20 IDs để kiểm tra:

- remote namespace có đúng 518.255 vectors;
- dimension là 384 và index ready;
- sample document IDs/hash khớp SQLite local;
- snapshot vẫn đúng revision và SHA-256.

Report cuối nằm tại
`data/huggingface/pinecone_ingestion_report.json`.

## Runtime retrieval mặc định

- dense query: câu hỏi đã rewrite; sparse query: nguyên văn câu hỏi người dùng;
- Pinecone hybrid và SQLite FTS5 chạy song song rồi merge document IDs;
- retrieve 24 document, chunk theo Điều/Khoản ở mức tối đa 220 tokens;
- chọn tối đa 12 rerank candidates, tối đa 2 candidates/document;
- Qdrant ColBERT là chính, Pinecone BGE là fallback, trả tối đa 6 kết quả;
- local policy lấy tối đa 3 evidence trong tổng context 720 whitespace tokens;
- output model tối đa 640 tokens;
- `RERANK_MIN_SCORE=0.05` là cấu hình deployment, cần hiệu chỉnh bằng bộ câu hỏi
  có nhãn trước khi nâng threshold vì score normalization phụ thuộc service.

FTS5 là index runtime độc lập, không cần reingest Pinecone:

```powershell
python -u -m app.ingestion.legal_fts build --batch-size 256
```

Index chỉ lưu metadata exact-number và title FTS5 `contentless` có BM25; không
lập chỉ mục hay giải nén body lần thứ hai. Mỗi batch được commit riêng; nếu tiến
trình bị ngắt, file `.building` được giữ và cùng câu lệnh sẽ resume từ document
cuối đã hoàn thành. Lệnh tự compact schema body cũ sang schema title-only bằng
file sibling và chỉ replace sau khi count/integrity hợp lệ. Chỉ file tạm sai
schema hoặc khác `DATASET_REVISION` mới bị tạo lại.

## Nguồn kỹ thuật

- Pinecone database/operation/model quotas:
  <https://docs.pinecone.io/reference/api/database-limits>
- Pinecone hybrid dense+sparse search:
  <https://docs.pinecone.io/guides/search/hybrid-search>
- Pinecone Python SDK gRPC performance:
  <https://sdk.pinecone.io/python/guides/grpc.html>
- Qdrant Cloud Inference:
  <https://qdrant.tech/documentation/cloud/inference/>
