# VietLex — Vietnamese Legal RAG

<div align="center">

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Corpus](https://img.shields.io/badge/Corpus-518%2C255%20documents-2E8B57)](https://huggingface.co/datasets/vohuutridung/vietnamese-legal-documents)
[![Dense embedding](https://img.shields.io/badge/Embedding-E5--small%20384d-F59E0B)](https://huggingface.co/intfloat/multilingual-e5-small)
[![Backend](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)

**Evidence-grounded Vietnamese Legal RAG over 518,255 documents using hybrid retrieval, reranking, and Vertex AI.**

Ngôn ngữ: **Tiếng Việt** | [English](README.en.md)

</div>

VietLex là dự án portfolio AI/ML xây dựng hệ thống hỏi đáp pháp luật Việt Nam có dẫn chứng. Hệ thống kết hợp dense retrieval và sparse retrieval trên Pinecone với tra cứu số hiệu/tiêu đề bằng SQLite FTS5, sau đó resolve nội dung cục bộ, chunk theo cấu trúc pháp lý, rerank và sinh câu trả lời grounded bằng Vertex AI Gemini.

> [!WARNING]
> Corpus là dataset nghiên cứu của bên thứ ba [`vohuutridung/vietnamese-legal-documents`](https://huggingface.co/datasets/vohuutridung/vietnamese-legal-documents), không phải cơ sở dữ liệu pháp luật chính thức và không tự xác nhận hiệu lực hiện hành. Kết quả chỉ nhằm mục đích tham khảo thông tin, không phải tư vấn pháp lý; luôn đối chiếu với nguồn chính thức cập nhật.

## Kết quả nổi bật

| Bằng chứng portfolio | Kết quả đã lưu trong artifact |
| :--- | :--- |
| Balanced-50 answer evaluation | Faithfulness **0,9158** · Answer Accuracy **0,8950** · Context Precision **0,8757** · Context Recall **0,9333** |
| Hoàn tất pipeline | **50/50** generation `STOP` · **50/50** NeMo input/output safe · **0** lỗi kỹ thuật trong run |
| Verified retrieval subset | **40** case có toàn bộ required evidence đã xác minh · Document Recall@3 macro **0,9250**, micro **50/53** |
| Automated verification | Suite provider-free phân tầng; live-provider tests là opt-in |

Balanced-50 gồm 40 case có fully verified required retrieval evidence và 10 deterministic reference-only case. Các metric trên là bằng chứng cho một lát cắt đánh giá có giới hạn, không chứng minh độ chính xác pháp lý trên toàn corpus hoặc production readiness. Xem [`PORTFOLIO_EVIDENCE.md`](docs/evaluation/PORTFOLIO_EVIDENCE.md) để biết provenance và evidence boundary đầy đủ.

## Demo

![Giao diện hỏi đáp pháp luật của VietLex](docs/images/chat_flow.png)

Repository cung cấp giao diện chat FastAPI/Jinja2 thật; ảnh trên là screenshot đã lưu trong repository, không phải mockup hay tuyên bố về một deployment công khai.

## Năng lực cốt lõi

- **Hybrid retrieval toàn corpus:** một Pinecone dense+sparse query chạy song song với SQLite FTS5 exact document-number/title search.
- **Dense inference:** `intfloat/multilingual-e5-small`, 384 chiều, qua Qdrant Cloud inference staging; persistent vectors nằm trong Pinecone.
- **Sparse retrieval:** `FastSparseEncoder` cục bộ, tối đa 64 nonzero terms; không được mô tả là full BM25 vì không có corpus-level IDF.
- **Evidence resolution:** full text nằm trong SQLite/Zstandard và chỉ được chunk sau khi document được resolve.
- **Legal-aware chunking:** Chương → Mục → Điều → Khoản, 220 approximate whitespace tokens với overlap 24 cho đơn vị quá dài.
- **Remote reranking:** Qdrant ColBERT là primary; Pinecone `bge-reranker-v2-m3` là fallback kỹ thuật.
- **Grounded generation:** Vertex AI `gemini-3.5-flash` qua ADC, với citations và typed provider diagnostics.
- **Evaluation:** deterministic retrieval/answer metrics là mặc định; Ragas/LLM judge chỉ chạy opt-in offline.
- **Web backend:** FastAPI, Jinja2/HTMX, MongoDB cho session/log/feedback, rate limiting và guardrail modes `off`/`shadow`/`enforce`.
- **Tài khoản:** đăng ký/đăng nhập, Gmail verification/reset, lịch sử theo chủ sở hữu, export và xóa dữ liệu.
- **Tra cứu văn bản:** tìm theo số hiệu/tiêu đề và xem toàn văn từ SQLite cục bộ, kèm cảnh báo chưa xác minh hiệu lực.

## Kiến trúc

```mermaid
flowchart LR
    Corpus["Pinned corpus: 518,255 documents"] --> Store["SQLite + Zstandard full text"]
    Store --> DenseText["Metadata + outline + representative body"]
    Store --> Sparse["FastSparseEncoder · max 64 terms"]
    DenseText --> Stage["Qdrant inference staging · E5-small 384d"]
    Stage --> Pinecone["Pinecone · one record/document"]
    Sparse --> Pinecone

    Query["Original query"] --> Embed["Qdrant dense query inference"]
    Query --> SparseQ["Original sparse query"]
    Query --> FTS["SQLite FTS5 · number/title"]
    Embed --> Hybrid["Pinecone hybrid search"]
    SparseQ --> Hybrid
    Hybrid --> Merge["Merge + exact deduplication"]
    FTS --> Merge
    Merge --> Resolve["Resolve full text"]
    Resolve --> Chunk["Structural local chunks"]
    Chunk --> Bound["Max 24 reranker inputs · up to 4 chunks/document"]
    Bound --> Rerank["Qdrant ColBERT · Pinecone BGE fallback"]
    Rerank --> FullEvidence["Full-corpus evidence lane"]
    FullEvidence --> Combine["Exact dedupe + bounded rank interleave"]
    Combine --> Evidence["Up to 3 evidence chunks · 720 context tokens"]
    Evidence --> Answer["Vertex AI Gemini answer"]

    Query -. opt-in .-> Structural["Qdrant structural pilot · 827 documents"]
    Structural -. parallel retrieval + rerank .-> Combine
    Store -. migration dry-run / pilot .-> VertexLane["Vertex AI gemini-embedding-2 · 1024d"]
    VertexLane -. isolated hybrid/RRF .-> QdrantV3["Qdrant v3 migration collection"]
```

Runtime mặc định giữ `STRUCTURAL_BACKEND_ENABLED=false`. Khi structural pilot được bật, lane Qdrant structural 827 văn bản chạy **song song** với lane Pinecone-v1 + FTS toàn corpus; nó không thay thế hoặc mở rộng structural coverage lên 518.255 văn bản.

Cross-lane Pinecone BGE final rerank đã được triển khai và đánh giá trên identical inputs nhưng vẫn giữ `CROSS_LANE_FINAL_RERANK_ENABLED=false`: bằng chứng không đủ để phê duyệt cutover. Không chạy lại A/B trong lần closure này.

## Tech stack

| Lớp | Công nghệ |
| :--- | :--- |
| API & UI | Python 3.10+, FastAPI, Uvicorn, Jinja2, HTMX |
| Durable vector retrieval | Pinecone Serverless, index `vietlex-legal-rag-v1`, namespace `legal-documents-v1` |
| Dense inference & reranking | Qdrant Cloud, multilingual E5-small 384d, AnswerAI ColBERT-small-v1 |
| Lexical & content store | SQLite FTS5, SQLite/Zstandard, local `FastSparseEncoder` |
| Generation | Google Vertex AI `gemini-3.5-flash` qua Application Default Credentials |
| Runtime data | MongoDB cho session, interaction log, feedback và admin data; không lưu corpus pháp luật |
| Evaluation & safety | Pytest, deterministic metrics, optional Ragas, NeMo Guardrails |
| Delivery | Docker, GitHub Actions, Vercel thin gateway + persistent-disk FastAPI origin |

## Đánh giá

### Bằng chứng portfolio đã xác minh

| Tập đánh giá | Generation `STOP` | NeMo safe | Ragas coverage | Faithfulness | Answer accuracy | Context precision | Context recall | Technical errors |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Representative-10, `all-required-verified` | 10/10 | 10/10 | 10/10 | 0,9857 | 0,9750 | 0,9400 | 1,0000 | 0 |
| Balanced-50, 26 factoid + 24 multi-hop | 50/50 | 50/50 | 50/50 | 0,9158 | 0,8950 | 0,8757 | 0,9333 | 0 |

Nguồn bất biến:

- [`Balanced-50 report`](docs/evaluation/runs/answer-balanced50-v2-live-20260822/report.md)
- [`Representative-10 report`](docs/evaluation/runs/answer-representative10-v6-live-20260822/report.md)
- [`Portfolio evidence`](docs/evaluation/PORTFOLIO_EVIDENCE.md)
- [`Current evaluation status`](docs/evaluation/CURRENT_STATUS.md)

Metric deterministic trong code là mặc định. Retrieval metrics bao gồm Document/Article/Clause Recall@K, MRR, nDCG, exact-reference hit, multi-hop coverage, stage survival, no-candidate rate và technical-error rates. Answer metrics bao gồm exact match, token/character F1, ROUGE-L/CHRF, number/date/entity, citation và refusal metrics. Mọi aggregate lưu numerator, denominator, coverage, skipped cases và skip reasons.

## Chạy dự án từ một máy mới

### 1. Yêu cầu và tài nguyên

- Python 3.10+ và Git.
- MongoDB local hoặc MongoDB Atlas.
- Ít nhất khoảng **8 GiB disk trống** để download snapshot, build file tạm và giữ local stores. Trên bản build hiện tại, `content_store.sqlite3` khoảng 3,08 GiB và `legal_fts.sqlite3` khoảng 0,21 GiB.
- Pinecone, Qdrant Cloud và Google Cloud ADC nếu muốn chạy chat RAG thật giống môi trường tác giả. Chỉ đọc/search văn bản cục bộ không tạo vector mới.

> [!IMPORTANT]
> Git không chứa corpus vì kích thước lớn và `data/huggingface/` được ignore. Clone repository xong **chưa đủ** để chạy retrieval. Phải dựng local stores theo bước 3 và kết nối đúng Pinecone index nếu muốn chat trên toàn bộ 518.255 văn bản.

### 2. Cài Python và cấu hình

```powershell
git clone https://github.com/TanNguyen234/VietLex-Tech-Spec.git
Set-Location VietLex-Tech-Spec
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Điền `.env` theo nhu cầu:

| Chức năng | Biến bắt buộc |
| :--- | :--- |
| Web/session | `MONGO_URL`, `WEB_SESSION_SECRET` (bắt buộc ổn định và ≥32 ký tự ở production) |
| Full-corpus retrieval/cache | `PINECONE_API_KEY`, index `vietlex-legal-rag-v1`, namespace `legal-documents-v1` |
| Dense inference/rerank | `QDRANT_URL`, `QDRANT_API_KEY` |
| Sinh câu trả lời | `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT` |
| Xác minh email | `ACCOUNT_EMAIL_ENABLED=true`, `EMAIL_USER`, Gmail App Password trong `EMAIL_PASS`, `EMAIL_FROM`, `PUBLIC_BASE_URL` |

Các biến và giá trị mặc định đầy đủ nằm trong [`.env.example`](.env.example). Không commit `.env`, JSON service account, cookie hoặc token. Ở production, `FRONTEND_URL` và `PUBLIC_BASE_URL` phải là HTTPS thật.

### 3. Dựng dữ liệu cục bộ

Pipeline tải đúng revision đã pin, hỗ trợ resume HTTP Range, kiểm tra kích thước/SHA-256, rồi stream Parquet thành SQLite/Zstandard:

```powershell
python -m app.ingestion.hf_pipeline download
python -m app.ingestion.hf_pipeline prepare
python -u -m app.ingestion.legal_fts build --batch-size 256
python -m app.ingestion.hf_pipeline smoke
```

Sau bước này cần có:

```text
data/huggingface/content_store.sqlite3   # 518.255 metadata + full-text documents
data/huggingface/legal_fts.sqlite3       # number/title search index
```

`smoke` phải báo `snapshot_verified=true`, `content_store_verified=true` và `joined_count=518255`. FTS chỉ tìm số hiệu/tiêu đề; không được mô tả là full-body/article search.

> [!CAUTION]
> `download` dùng Internet và có thể tải vài GiB. Không copy hai file SQLite đang mở giữa các máy; dùng snapshot/backup đã kiểm tra integrity theo [`docs/PRODUCTION_OPERATIONS.md`](docs/PRODUCTION_OPERATIONS.md).

### 4. Kết nối vector store

Runtime mặc định dùng Pinecone v1 có **518.255 record, một record/văn bản**. Con số **134.334** là số structural chunk của pilot 827 văn bản và không phải kích thước corpus production.

- Nếu bạn được cấp quyền vào index hiện có: chỉ cấu hình đúng key/index/namespace trong `.env`; không ingestion lại.
- Nếu dùng tài khoản Pinecone mới: phải tự dựng index bằng runbook. Lệnh full có thể xóa/recreate remote index, tốn quota/chi phí và không thuộc quickstart thông thường.
- Structural Pinecone thay thế hiện mới có 21.696/134.334 record vì hosted-inference quota; không bật `STRUCTURAL_BACKEND_ENABLED` để thay thế lane v1.

Lane migration Vertex–Qdrant mới là **isolated pilot**, không tham gia runtime mặc định. Nó dùng `gemini-embedding-2` 1.024 chiều, dense cosine và sparse IDF trong collection `vietlex-legal-rag-v3-vertex-1024`. Dữ liệu được lấy cân bằng giữa nhiều loại văn bản, chunk theo Điều/Khoản và giới hạn số chunk trên mỗi văn bản để không làm tràn cluster. Lệnh mặc định chỉ lập kế hoạch cục bộ:

```powershell
# Provider-free dry-run: không tạo collection, không gọi Vertex, không upload.
python run_vertex_qdrant_migration.py --max-documents 12 --max-points 24

# Pilot live có checkpoint; chỉ chạy khi đã duyệt chi phí/quota và remote write.
python run_vertex_qdrant_migration.py --max-documents 12 --max-points 24 `
  --allow-create --allow-remote-write

# Chạy lại bỏ qua các point đã được Qdrant ACK; có thể probe hybrid/RRF.
python run_vertex_qdrant_migration.py --max-documents 12 --max-points 24 `
  --allow-remote-write --probe-query "thời gian thử việc"
```

Tăng `--max-documents` và `--max-points` theo từng đợt; checkpoint mặc định ở `data/huggingface/vertex_qdrant_checkpoint.sqlite3`. Không bật lane này thay Pinecone trước khi có benchmark A/B trên identical inputs và đủ coverage. `gemini-embedding-2` hỗ trợ tối đa 3.072 chiều, nhưng 1.024 được chọn để tăng chất lượng so với 384d mà vẫn giữ ngân sách storage khả thi; xem [Google Cloud model card](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/embedding-2) và [Qdrant hybrid vectors](https://qdrant.tech/documentation/manage-data/vectors/).

Chi tiết và điều kiện resume: [`docs/huggingface-ingestion-runbook.md`](docs/huggingface-ingestion-runbook.md).

### 5. Chạy ứng dụng


```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Mở <http://localhost:8000>. Các endpoint kiểm tra là `GET /healthz` và `GET /readyz`; `/readyz` chỉ xanh khi các dependency được cấu hình thực sự sẵn sàng.

### 6. Kiểm thử vừa đủ

Không cần chạy toàn bộ evaluation suite sau mỗi sửa UI. Dùng tầng nhỏ nhất chứng minh thay đổi:

```powershell
# Smoke web/account/legal hằng ngày
python -m pytest -q tests/test_account_routes.py tests/test_legal_routes.py tests/test_public_web_routes.py tests/test_web_security.py

# Lint mã chạy
python -m ruff check app

# Full provider-free suite: chỉ trước release/merge hoặc khi đổi retrieval/evaluation
python -m pytest -q
```

Các live tests được đánh dấu `live` và không chạy mặc định. Không xóa test evaluation chỉ để giảm số lượng: chúng là bằng chứng tái lập metric. Khi sửa một module, ưu tiên `pytest <file>::<test>` rồi chạy gate rộng đúng một lần khi source đã ổn định.

Kiểm tra packaging/tĩnh bổ sung:

```powershell
python -m compileall -q app tests
git diff --check
```

### Deployment topology

- **Vercel public gateway:** `vercel.json` và `api/proxy.py` proxy HTML/API/static; gateway dùng polling 1 giây vì serverless proxy buffer response.
- **FastAPI origin:** chạy `Dockerfile` trên host có persistent `/data` disk cho `content_store.sqlite3` và `legal_fts.sqlite3`.
- Direct FastAPI clients dùng SSE progress; repository không tuyên bố end-to-end SSE qua Vercel hoặc một live production URL chưa được kiểm chứng.

Xem [`deploy/vercel-proxy/README.md`](deploy/vercel-proxy/README.md).

## Advanced evaluation và adjudication

### Provider-free gold adjudication

`run_gold_adjudication.py` tạo immutable human-review artifacts trong repository mà không gọi provider, Ragas, generation, guardrail, corpus/index hoặc vector writes.

```powershell
python -u run_gold_adjudication.py queue --dataset app/data/namsyntax_legal_qa_420.json --sidecar docs/evaluation/gold_labels/namsyntax_legal_qa_420_labels_v2.json --content-store data/huggingface/content_store.sqlite3 --fts data/huggingface/legal_fts.sqlite3 --target-cases 40 --candidate-limit 12
python -u run_gold_adjudication.py preview --dataset app/data/namsyntax_legal_qa_420.json --sidecar docs/evaluation/gold_labels/namsyntax_legal_qa_420_labels_v2.json --queue docs/evaluation/adjudication/queues/<run-id>/queue.json --decisions <decisions.json>
python -u run_gold_adjudication.py promote --dataset app/data/namsyntax_legal_qa_420.json --sidecar docs/evaluation/gold_labels/namsyntax_legal_qa_420_labels_v2.json --queue docs/evaluation/adjudication/queues/<run-id>/queue.json --decisions <decisions.json> --preview docs/evaluation/adjudication/previews/<run-id>/preview.json --approve-preview-sha256 <approved-preview-sha256>
```

Promotion không sửa source sidecar. Nó rebuild preview, yêu cầu đúng approved preview SHA-256 và ghi một `labels_v2.json` mới; coverage không đủ vẫn giữ `BLOCKED_INSUFFICIENT_VERIFIED_CASES`.

### Deterministic evaluation

```powershell
python -u run_retrieval_eval.py --preflight-all-profiles --verified-only --gold-policy all-required-verified --rewrite off --reranker current
python -u run_retrieval_eval.py --profile separated_intent --verified-only --gold-policy all-required-verified --rewrite off --reranker current
python -u run_answer_eval.py --profile separated_intent --verified-only --judge none --guardrails off
```

Ragas chỉ được bật rõ ràng cho offline audit có ngân sách; route `/chat` không enqueue Ragas. Các live-provider test/evaluation không thuộc default suite và có thể phát sinh quota hoặc chi phí.

### Corpus operations dành cho operator

Full ingestion có thể xóa/recreate remote index và chỉ chạy khi đã có quyền migration/reingestion rõ ràng, quota phù hợp và backup/checkpoint:

```powershell
python -u -m app.ingestion.hf_pipeline full --delete-existing --yes
```

`verify` sau ingestion đọc trạng thái Pinecone từ xa; nó không phải provider-free. Các bước local `download`, `prepare`, `smoke` và FTS build đã được mô tả trong quickstart phía trên.

## Giới hạn đã công bố

- Corpus của bên thứ ba không bảo đảm hiệu lực pháp luật hiện hành hoặc độc lập kiểm chứng toàn bộ dữ liệu.
- Structural pilot chỉ phủ 827 văn bản luật chính, không phải toàn bộ 518.255 văn bản.
- Kết quả evaluation là bounded slice; không chứng minh whole-corpus legal accuracy hoặc production readiness.
- Vercel gateway dùng polling; progress registry vẫn process-local.
- Cross-lane final rerank vẫn được chủ ý tắt theo quyết định `KEEP_DISABLED`.

## Tài liệu

- [`docs/PROJECT_CONTEXT.md`](docs/PROJECT_CONTEXT.md) — source-of-truth context
- [`docs/CURRENT_ARCHITECTURE.md`](docs/CURRENT_ARCHITECTURE.md) — runtime architecture
- [`docs/AGENT_WORKFLOW.md`](docs/AGENT_WORKFLOW.md) — engineering/evidence workflow
- [`docs/evaluation/PORTFOLIO_EVIDENCE.md`](docs/evaluation/PORTFOLIO_EVIDENCE.md) — recruiter-safe evidence
- [`docs/huggingface-ingestion-runbook.md`](docs/huggingface-ingestion-runbook.md) — ingestion operations
