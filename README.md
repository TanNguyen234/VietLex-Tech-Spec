# VietLex — Vietnamese Legal RAG

<div align="center">

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Corpus](https://img.shields.io/badge/Corpus-518%2C255%20documents-2E8B57)](https://huggingface.co/datasets/vohuutridung/vietnamese-legal-documents)
[![Dense embedding](https://img.shields.io/badge/V3%20Embedding-gemini--embedding--2%201024d-F59E0B)](https://cloud.google.com/vertex-ai/generative-ai/docs/embeddings/get-text-embeddings)
[![Backend](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)

**Vietnamese Legal RAG với v3 Vertex/Qdrant mặc định và đường Pinecone toàn corpus không dùng Google Cloud được chọn tường minh.**

Ngôn ngữ: **Tiếng Việt** | [English](README.en.md)

</div>

VietLex là dự án portfolio AI/ML xây dựng hệ thống hỏi đáp pháp luật Việt Nam có dẫn chứng. Runtime có hai contract được chọn bằng một boolean: v3 dùng Vertex/Qdrant structural retrieval theo mặc định; legacy/free dùng Pinecone + SQLite FTS và chặn hoàn toàn Google Cloud trước khi tạo client.

> [!WARNING]
> Corpus là dataset nghiên cứu của bên thứ ba [`vohuutridung/vietnamese-legal-documents`](https://huggingface.co/datasets/vohuutridung/vietnamese-legal-documents), không phải cơ sở dữ liệu pháp luật chính thức và không tự xác nhận hiệu lực hiện hành. Kết quả chỉ nhằm mục đích tham khảo thông tin, không phải tư vấn pháp lý; luôn đối chiếu với nguồn chính thức cập nhật.

## Kết quả nổi bật

| Bằng chứng portfolio | Kết quả đã lưu trong artifact |
| :--- | :--- |
| Golden-50 answer evaluation v3 raw-RRF, 2026-09-02 | Deterministic exact match **0,0000** · Token F1 **0,2304** · Citation precision **0,9470** |
| Ragas opt-in, secondary evidence | Faithfulness **0,8887** · Answer Accuracy **0,9184** · Context Precision **0,8878** · Context Recall **0,9354** trên 49/50 case |
| Hoàn tất pipeline | **50/50** generation `STOP` · **50/50** NeMo input/output safe · **49/50** Ragas, 1 lỗi judge có kiểu |
| Verified retrieval subset | **40** case có toàn bộ required evidence đã xác minh · Document Recall@3 **1,0000**, micro **53/53** |
| Dữ liệu v3 đã kiểm kê | **51.801** point remote · **4.969** document ID duy nhất · local full-doc/FTS bundle cùng tập |
| Automated verification | **921 passed, 2 skipped**; live-provider tests vẫn là opt-in |
| Public SSR smoke | Vercel FastAPI/Jinja tại <https://vietlex-legal-rag.vercel.app>: SSR và readiness sẵn sàng; tìm kiếm Supabase và trang toàn văn đã được kiểm tra trực tiếp |

Golden-50 v3 được tách từ Balanced-50, gồm 40 case có fully verified required retrieval evidence và 10 deterministic reference-only case. Các metric trên là bằng chứng cho một lát cắt đánh giá có giới hạn, không chứng minh độ chính xác pháp lý trên toàn corpus hoặc production readiness. Xem [`PORTFOLIO_EVIDENCE.md`](docs/evaluation/PORTFOLIO_EVIDENCE.md) để biết provenance và evidence boundary đầy đủ.

## Demo

### Hỏi đáp có dẫn nguồn

![Giao diện hỏi đáp pháp luật mới nhất của VietLex](docs/images/vietlex_web_latest.png)

### Tra cứu văn bản trong local corpus

![Giao diện tra cứu Bộ luật Lao động 2019](docs/images/vietlex_legal_search_latest.png)

Hai ảnh được chụp ngày **2026-08-26** từ web FastAPI/Jinja2 chạy thật với local corpus và MongoDB online; đây không phải mockup. Deployment công khai online-only hiện ở <https://vietlex-legal-rag.vercel.app>; trang tìm kiếm và toàn văn dùng tập Supabase 4.969 văn bản tương ứng v3.

## Năng lực cốt lõi

- **V3 hybrid retrieval mặc định:** Qdrant dense 1024d + sparse IDF hợp nhất bằng raw RRF trên **51.801** structural point.
- **Evidence v3:** chat đọc trực tiếp trường `body` trong Qdrant payload; không gọi Supabase để resolve full text.
- **Full-document v3:** Supabase phục vụ trang toàn văn và tìm số hiệu/tiêu đề trên Vercel; SQLite/Zstandard + FTS5 giữ cùng **4.969** văn bản cho persistent/local và sparse-length calibration.
- **Reranking:** v3 giữ raw RRF; Qdrant ColBERT không được bật vì A/B identical-input làm giảm verified recall.
- **Grounded generation:** Vertex AI `gemini-3.5-flash` qua ADC, với citations và typed provider diagnostics.
- **Evaluation:** deterministic retrieval/answer metrics là mặc định; Ragas/LLM judge chỉ chạy opt-in offline.
- **Web backend:** FastAPI, Jinja2/HTMX, MongoDB cho session/log/feedback, rate limiting và guardrail modes `off`/`shadow`/`enforce`.
- **Tài khoản:** đăng ký/đăng nhập, Gmail verification/reset, lịch sử theo chủ sở hữu, export và xóa dữ liệu.
- **Tra cứu văn bản:** tìm theo số hiệu/tiêu đề và xem toàn văn từ Supabase ở online-only hoặc SQLite ở persistent/local, kèm cảnh báo chưa xác minh hiệu lực.

## Kiến trúc

```mermaid
flowchart TB
    User["Browser"] --> Web["Vercel FastAPI · Jinja2/HTMX SSR"]
    Web --> Mongo["MongoDB online<br/>accounts · sessions · logs · feedback"]
    Web --> Supabase["Supabase online<br/>4,969 full documents · title/number search"]

    subgraph Ingest["Pinned ingestion contract"]
        Corpus["Hugging Face snapshot<br/>518,255 documents"] --> Store["SQLite + Zstandard<br/>518,255 full texts · 3.08 GiB"]
        Store --> FTSBuild["SQLite FTS5<br/>number + title · 0.21 GiB"]
        Store --> DocRepresentation["Metadata + outline + representative body"]
        DocRepresentation --> E5Ingest["Qdrant Cloud Inference<br/>E5-small · 384d"]
        Store --> SparseIngest["Local FastSparseEncoder<br/>max 64 nonzero terms"]
        E5Ingest --> PCV1["Pinecone v1<br/>518,255 document records"]
        SparseIngest --> PCV1
    end

    Web --> Selector{"USE_LEGACY_FREE_PIPELINE"}
    subgraph Runtime["Legacy/free · true"]
        Selector -- "true" --> Query["Original query"]
        Query --> Rewrite["Direct-API query rewrite nếu cấu hình"]
        Rewrite --> DenseQ["Qdrant E5 query inference · 384d"]
        Query --> SparseQ["Local sparse query"]
        Query --> FTS["SQLite FTS5 exact/title"]
        DenseQ --> Hybrid["Pinecone dense+sparse hybrid"]
        SparseQ --> Hybrid
        Hybrid --> Merge["Merge + exact-location scoring"]
        FTS --> Merge
        Merge --> Resolve["Resolve full text from SQLite"]
        Resolve --> Chunk["Chương → Mục → Điều → Khoản<br/>220 tokens · overlap 24"]
        Chunk --> Rerank["Qdrant ColBERT<br/>Pinecone BGE fallback"]
        Rerank --> Evidence["≤3 chunks · ≤720 context tokens"]
        Evidence --> Generate["Direct-API generation<br/>Vertex bị chặn"]
        Generate --> Web
    end

    subgraph Optional["V3 mặc định và pilot cũ"]
        Query -. "STRUCTURAL_BACKEND_ENABLED" .-> QV2["Qdrant v2 structural pilot<br/>827 documents · 134,334 points · 384d + BM25"]
        QV2 -. "parallel evidence" .-> Rerank
        Store -. "resumable migration" .-> Embed2["Vertex gemini-embedding-2<br/>1024d"]
        Embed2 -.-> QV3["Qdrant v3 primary<br/>51,801 points · 4,969 documents"]
        Selector -- "false (mặc định)" --> QV3
        QV3 --> Evidence
        QV3 -. "explicit evaluation" .-> Audit["Deterministic retrieval benchmark"]
    end
```

`USE_LEGACY_FREE_PIPELINE=false` là mặc định và chọn Qdrant v3. Đặt `true` sẽ chọn đúng Pinecone-v1 + FTS và chặn Vertex cho retrieval, rewrite, generation, guardrails, migration helper và judge selection. `STRUCTURAL_BACKEND_ENABLED` chỉ còn ý nghĩa với contract cũ tương thích; boolean `true` luôn thắng và không chạy Qdrant v2.

### Pipeline cũ khác v3 ở đâu?

| Mặt so sánh | Legacy/free (`true`) | V3 mặc định (`false`) |
| :--- | :--- | :--- |
| Coverage | 518.255 văn bản | 51.801 point từ đúng 4.969 document ID đã audit |
| Vector store | Pinecone `vietlex-legal-rag-v1/legal-documents-v1` | Qdrant `vietlex-legal-rag-v3-vertex-1024` |
| Đơn vị index | 1 vector đại diện/văn bản | Structural chunk; tối đa 16 chunk phân bố đều/văn bản khi migration |
| Dense embedding | E5-small 384d qua Qdrant inference | `gemini-embedding-2` 1024d qua Vertex |
| Sparse | `FastSparseEncoder`, tối đa 64 term; không phải full BM25 | Sparse IDF theo point trong Qdrant |
| Truy xuất | Pinecone hybrid chạy song song SQLite FTS số hiệu/tiêu đề | Qdrant dense+sparse fusion bằng RRF |
| Full text/chunk runtime | Resolve SQLite/Zstandard rồi chunk 220/24 | Dùng structural text đã lưu trong payload; migration chunk 320/32 |
| Rerank | Qdrant ColBERT; Pinecone BGE fallback | Raw RRF; ColBERT không được chọn vì A/B identical-input kém hơn |
| Evidence cuối | Tối đa 3 chunk / 720 token | Tối đa 3 point / 720 token |
| Khi lỗi backend | Có thể còn evidence từ FTS và báo partial error | Fail closed có typed error; không âm thầm nhảy sang Pinecone |
| Google Cloud | Bị chặn trước khi tạo Vertex client; generation dùng direct-API fallback đã cấu hình | Vertex dùng cho query embedding và generation/guardrails mặc định |
| Điểm mạnh/yếu | Coverage rộng nhưng vector cấp document có thể bỏ sót Điều/Khoản sâu | Granularity tốt hơn trên vùng đã migrate nhưng không trả lời được ngoài lát cắt |
| Semantic cache/eval | Cache fingerprint và manifest ghi Pinecone + Google Cloud off | Cache fingerprint và manifest ghi v3 + Google Cloud on |

Chế độ legacy/free có nghĩa là **không gọi Google Cloud**, không có nghĩa mọi provider còn lại đều miễn phí hoặc không có quota. Nếu không có ít nhất một key direct API còn hoạt động, retrieval vẫn chạy nhưng generation có thể thất bại có kiểu.

Cross-lane Pinecone BGE final rerank đã được triển khai và đánh giá trên identical inputs nhưng vẫn giữ `CROSS_LANE_FINAL_RERANK_ENABLED=false`: bằng chứng không đủ để phê duyệt cutover. Không chạy lại A/B trong lần closure này.

## Trạng thái dữ liệu và giới hạn hiện tại

Số liệu dưới đây được đọc lại ngày **2026-08-27** bằng API chỉ-đọc của Pinecone/Qdrant và SQLite ở chế độ read-only.

| Kho dữ liệu | Vai trò thực tế | Số lượng quan sát được | Trạng thái / giới hạn |
| :--- | :--- | ---: | :--- |
| SQLite/Zstandard `content_store.sqlite3` | Nguồn full text cục bộ | **518.255** văn bản | 3.309.723.648 byte ≈ **3,08 GiB**; đầy đủ theo revision pin |
| SQLite FTS5 `legal_fts.sqlite3` | Tìm số hiệu và tiêu đề | **518.255** văn bản | 223.526.912 byte ≈ **0,21 GiB**; không tìm full body/Điều/Khoản |
| Pinecone `vietlex-legal-rag-v1/legal-documents-v1` | Full-corpus legacy/free | **518.255** vector 384d | Một vector/văn bản; index ready, dot-product |
| Pinecone `semantic-cache-v1` | Cache câu hỏi đã trả lời | **9** vector | Cùng index v1; chỉ nhận cache hit ở ngưỡng nghiêm ngặt |
| Pinecone `llama-text-embed-v2-index/national-primary-v2` | Thử nghiệm structural cũ, không phải runtime mặc định | **21.696** vector 1024d | Bị dừng trước mục tiêu 134.334 vì hosted-inference quota |
| Qdrant `vietlex-embedding-staging` | E5 inference staging | **2.049** point 384d | Collection kỹ thuật, không phải corpus durable |
| Qdrant `vietlex-rerank-staging` | ColBERT transient staging | **0** point thường trú | Point tạm được dọn sau rerank |
| Qdrant `vietlex-legal-rag-v2-pilot-384` | Structural pilot opt-in | **134.334** point từ **827** văn bản | Dense 384d + sparse BM25/IDF; collection green nhưng coverage hẹp |
| Qdrant `vietlex-legal-rag-v3-vertex-1024` | Runtime mặc định khi boolean `false` | **51.801** point trên đúng **4.969** document ID đã audit | Dense 1024d + sparse IDF; collection green nhưng coverage hẹp |
| MongoDB online | Tài khoản, phiên, interaction, feedback | Dữ liệu vận hành thay đổi theo người dùng | Không chứa corpus hoặc vector pháp luật |

### Usage limit nào đang áp dụng?

API database cho biết schema và số vector/point, nhưng **không trả về phần trăm quota tháng của tài khoản**. Con số RU/WU, token đã dùng và dung lượng cluster thực tế phải xem trong Pinecone/Qdrant/Google Cloud Console; README không suy đoán chúng.

- Nếu Pinecone đang ở **Starter**, giới hạn công khai hiện tại là 2 GiB storage toàn organization, 5 serverless index, 1.000.000 read units/tháng, 2.000.000 write units/tháng, 5.000.000 embedding tokens/model/tháng và 100 query/giây/namespace. Xem [Pinecone database limits](https://docs.pinecone.io/reference/api/database-limits).
- Nếu Qdrant đang ở **Free Tier**, cluster có 1 GiB RAM, 0,5 vCPU và 4 GiB disk, một node, không có HA. Selected free inference models có thể miễn phí; usage/model cụ thể chỉ hiện trong tab Inference. Xem [Qdrant pricing](https://qdrant.tech/pricing/) và [Cloud Inference](https://qdrant.tech/documentation/cloud/inference/).
- `gemini-embedding-2` nhận tối đa 8.192 input token và xuất tối đa 3.072 chiều; VietLex chọn 1.024 chiều. Quota Vertex thực tế phụ thuộc project/region và phải kiểm tra trong Google Cloud Console. Xem [model card](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/embedding-2).
- Application tự giới hạn chat ở **6 request/phút/client**; public evaluation 6/phút. Ragas public mặc định tắt; nếu bật thì tối đa 3 lượt/client/ngày và 20 lượt toàn hệ thống/ngày.

### Vấn đề retrieval hiện tại

1. Pinecone v1 bao phủ đủ 518.255 văn bản nhưng chỉ có **một vector đại diện cho mỗi văn bản**. Một Điều/Khoản nằm sâu trong full text có thể không xuất hiện trong representation dùng để embedding.
2. SQLite FTS5 giúp bắt số hiệu và tiêu đề, nhưng không phải article/body search. Các câu hỏi diễn đạt tự nhiên không nêu số hiệu vẫn phụ thuộc vào document-level semantic recall.
3. Qdrant v2 có structural chunk tốt hơn nhưng chỉ phủ 827 văn bản. Bật nó không tự biến coverage thành toàn corpus.
4. Qdrant v3 đã vượt mốc 50.000 point nhưng mới lấy từ 5.000/518.255 văn bản. Nó nay là runtime mặc định, nên có thể cải thiện câu hỏi thuộc vùng đã migrate; câu hỏi ngoài vùng đó vẫn có thể không có candidate. Canary 40 case cho thấy raw RRF tốt, còn Qdrant ColBERT làm giảm recall; coverage đại diện vẫn là bottleneck.

## Migration sắp tới và mốc hết Google Cloud Trial

Mục tiêu của migration v3 là tìm ở cấp **đoạn pháp lý/Điều/Khoản**, dùng `gemini-embedding-2` 1.024 chiều + sparse IDF + RRF, thay vì phụ thuộc hoàn toàn vào một vector đại diện cho cả văn bản. Điều này có khả năng cải thiện câu hỏi tự nhiên, nhưng chỉ khi chunk liên quan thật sự đã được upload và A/B benchmark chứng minh stage survival/Recall@K tốt hơn.

| Giai đoạn | Phạm vi | Quy mô quan sát / dự kiến | Trạng thái qua cổng |
| :--- | :--- | ---: | :--- |
| G0 — hoàn tất | Kế hoạch chọn 5.000 văn bản + golden anchors | **50.000/50.000** record kế hoạch đã ACK; remote audit: **51.801** point / **4.969** document ID | Upload/resume/collection green; runtime mặc định đã route sang v3 bằng boolean |
| G1 — quality gate | 40 case / 53 evidence đã xác minh, nhưng chỉ thuộc 2 văn bản | Raw RRF all-required@3 **39/40**; Qdrant ColBERT **33/40** | Raw RRF qua canary hẹp; ColBERT bị loại; chưa đủ coverage để cutover |
| G2 — targeted expansion | 20.000 văn bản được ưu tiên từ query logs/gold set | tối đa **320.000 point** | Capacity preflight; dense float32 thô đã ≈1,22 GiB, chưa gồm sparse/payload/HNSW |
| Full theoretical cap | 518.255 văn bản | tối đa **8.292.080 point** | Dense float32 thô ≈31,6 GiB; **không khả thi** trên Qdrant Free 4 GiB |

> [!CAUTION]
> Code hiện tại lấy tối đa 16 chunk phân bố đều trên mỗi văn bản để giữ chi phí hữu hạn. Cách này có thể vẫn bỏ sót một Điều cụ thể, nên không được quảng bá là đã giải quyết hoàn toàn lỗi chat. Trước G2 cần chọn một trong hai contract: lưu đầy đủ Điều/Khoản cho tập văn bản ưu tiên, hoặc giữ Pinecone làm document router rồi chunk/rerank full text cục bộ theo request.

Theo thông tin vận hành hiện tại, Google Cloud Trial còn khoảng **3 tháng** (mốc chính xác phải xác nhận ở Cloud Billing). Kế hoạch an toàn:

1. **Tháng 1:** chạy G1 có checkpoint, đo Recall/MRR/nDCG và kiểm kê token/chi phí thật; chưa cutover.
2. **Tháng 2:** quyết định giữ Vertex có billing hay chuyển sang embedding tự host/open-weight. Nếu đổi model, phải tạo collection mới và re-embed; không được query vector Vertex bằng model khác.
3. **Tháng 3:** chỉ chạy G2 sau capacity gate; đóng băng manifest/model/dimension, hoàn tất benchmark và chuẩn bị fallback trước ngày trial hết.

Nếu trial tự đóng mà không nâng cấp billing, Google cho biết billing project sẽ bị vô hiệu hóa, tài nguyên bị dừng và bước vào grace period 30 ngày. Vector đã ghi trong Qdrant/Pinecone không tự mất vì nằm ở provider khác, nhưng VietLex sẽ không thể gọi Vertex để rewrite/generate hoặc tạo/query embedding v3. Khi đó answer generation chỉ còn hoạt động nếu ít nhất một fallback OpenRouter/Gemini Direct/NVIDIA/Groq vẫn có key và quota. Xem [Google Cloud Free Trial lifecycle](https://docs.cloud.google.com/free/docs/free-cloud-features).

Khuyến nghị thực tế: **không full-migrate hàng triệu point chỉ để tận dụng credit trial**. Hoàn tất G1, đo chất lượng và chi phí, sau đó hoặc bật billing có budget alert cho Vertex, hoặc chọn embedding tự host trước khi G2 để tránh phải re-embed lần hai.

## Đánh giá

### 1. Bảng chỉ số toàn diện Golden-50 v3 (Deterministic + Ragas + Latency + Safety)

Đánh giá thực thi trên tập **Golden-50 v3** đã tách sẵn (26 câu hỏi Factoid + 24 câu hỏi Multi-hop) với Qdrant v3 raw-RRF, cấu hình `separated_intent`, `guardrails=enforce`, và Vertex AI `gemini-3.5-flash`. Retrieval metric chấm được 40 case đã xác minh; 10 case còn lại được ghi rõ `no_verified_gold_label`:

| Nhóm chỉ số | Tên chỉ số | Giá trị đạt được | Mẫu số / Mẫu kiểm thử | Ghi chú kỹ thuật |
| :--- | :--- | ---: | :---: | :--- |
| **Độ tin cậy & An toàn** | **Generation Finish** | **100,0%** | 50/50 | 100% phản hồi kết thúc trạng thái `STOP` sạch sẽ |
| | **NeMo Input Guardrail Safe** | **100,0%** | 50/50 | 0 vi phạm prompt injection / off-topic |
| | **NeMo Output Guardrail Safe** | **100,0%** | 50/50 | 0 output bị rail chặn; không đồng nghĩa đã chứng minh không ảo giác |
| | **Retrieval Technical Error Rate** | **0,0%** | 0/50 | Không có lỗi retrieval/reranker |
| | **No-Candidate Rate** | **0,0%** | 0/50 | Mọi câu hỏi đều truy xuất được ngữ cảnh hợp lệ |
| **Chất lượng Truy xuất (40/50 case có verified gold; 10 skip)** | **Document Recall @ 3** | **100,0%** | 53/53 | Văn bản chứa căn cứ nằm trong Top 3 |
| | **Document Recall @ 24** | **100,0%** | 53/53 | Toàn bộ văn bản căn cứ được tìm thấy ở Top 24 |
| | **Article Recall @ 3** | **100,0%** | 30/30 | Tỷ lệ trúng chính xác Điều luật cụ thể |
| | **Clause Recall @ 3** | **92,86%** | 13/14 | Tỷ lệ trúng chính xác Khoản luật cụ thể |
| | **Document MRR** | **0,9875** | 39,5/40 | Mean Reciprocal Rank cấp văn bản |
| | **Article MRR** | **0,9259** | 25/27 | Mean Reciprocal Rank cấp Điều luật |
| | **Clause MRR** | **0,7949** | 10,33/13 | Mean Reciprocal Rank cấp Khoản luật |
| | **nDCG @ 10** | **0,9275 macro / 0,9084 micro** | 43,6867/48,0918 | Normalized Discounted Cumulative Gain |
| | **Exact Reference Hit** | **100,0%** | 40/40 | Trúng dẫn chiếu pháp lý đã xác minh |
| | **Multi-hop All-Required** | **97,50%** | 39/40 | Thu hồi đủ 100% căn cứ trong câu hỏi đa bước |
| **Câu trả lời deterministic (50/50)** | **Exact match / Token F1 / Character F1** | **0,0000 / 0,2304 / 0,2226** | 50/50 | Lexical overlap thấp; không được diễn giải thành đúng/sai pháp lý |
| | **Citation precision / invalid rate** | **0,9470 / 0,0530** | 50/50 | Citation recall/coverage chỉ applicable ở 1/50 case |
| **Ragas opt-in (49/50, 1 judge error)** | **Faithfulness (Tính trung thực)** | **0,8887** | 49/50 | Judge và generator cùng model identity; không phải review pháp lý độc lập |
| | **Answer Accuracy (Độ chuẩn xác)** | **0,9184** | 49/50 | Mức độ trùng khớp ngữ nghĩa với ground truth |
| | **Context Precision (Độ chuẩn ngữ cảnh)** | **0,8878** | 49/50 | Mức độ tập trung của tài liệu được trích dẫn |
| | **Context Recall (Độ phủ ngữ cảnh)** | **0,9354** | 49/50 | Độ bao phủ thông tin cần thiết để giải đáp |
| **Thời gian Phản hồi (50/50)** | **t_input_guardrail** | **1,1212 s** | P50 (P95: 1,3067s) | Kiểm duyệt an toàn đầu vào |
| | **t_retrieval** | **0,8146 s** | P50 (P95: 1,1693s) | Có một cold start 13,5977 s |
| | **t_output_guardrail** | **1,1379 s** | P50 (P95: 1,3983s) | Kiểm duyệt an toàn đầu ra |
| | **t_total (End-to-End)** | **5,2812 s** | P50 (P95: 6,4429s) | Generation/guardrail trên evidence đã persist |

### 2. Đánh giá So sánh Reranker lần cuối (Qdrant ColBERT vs Pinecone BGE vs Raw RRF)

Thử nghiệm đối đầu trực tiếp trên cùng một tập 40 ca kiểm thử đã xác minh (`all-required-verified`):

| Thuật toán / Provider | Doc Recall @3 | Article Recall @3 | Clause Recall @3 | All-Required Coverage | Độ trễ P50 | Đánh giá kỹ thuật |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Raw RRF (Qdrant dense + sparse)** | **100,0%** (53/53) | **100,0%** (30/30) | **92,86%** (13/14) | **97,50%** (39/40) | **2,65 s** | **Tốt nhất trong canary**: giữ được Điều/Khoản |
| **Qdrant v2 comparator lịch sử** | **94,34%** (50/53) | **90,00%** (27/30) | **85,71%** (12/14) | **85,00%** (34/40) | **8,92 s** | Cùng case ID nhưng là run lịch sử, không phải A/B đồng thời |
| **Qdrant ColBERT (`answerai-colbert`)** | **100,0%** (53/53) | **90,00%** (27/30) | **78,57%** (11/14) | **87,50%** (35/40) | **2,97 s** | **Không đạt gate** trên chính candidate pool raw-RRF |
| **Pinecone BGE (`bge-reranker-v2-m3`)** | NOT SCORED | NOT SCORED | NOT SCORED | NOT SCORED | 15,00 s timeout | Monthly rerank limit 500 đã hết; không biến lỗi kỹ thuật thành điểm chất lượng |

**Kết luận**: Raw hybrid RRF của v3 là ứng viên tốt nhất trong canary hẹp. Qdrant ColBERT không nên bật bắt buộc vì tăng latency và loại nhầm Điều/Khoản; Pinecone BGE chưa có điểm A/B hợp lệ trong run này.

### 3. Final audit Balanced-50 với `qdrant-only` — không đạt cutover

Run lịch sử ngày 2026-08-27 thực thi đủ 50/50 câu với Qdrant ColBERT, guardrails enforce, deterministic metrics và Ragas. Nó dùng Pinecone-v1 + SQLite FTS và **không chạy v3**, nên không được dùng làm số liệu hiện tại của v3.

| Chỉ số | Kết quả |
| :--- | ---: |
| Generation / guardrails / Ragas coverage | **50/50**; 0 technical error |
| Verified Document Recall@3 | **0/53** |
| Ragas Faithfulness | **0,7467** |
| Ragas Answer Accuracy | **0,1500** |
| Ragas Context Precision / Recall | **0,1600 / 0,1567** |
| Deterministic token F1 / char F1 | **0,1585 / 0,1801** |
| End-to-end latency P50 / P95 | **10,65 s / 14,09 s** |

Kết quả lịch sử này loại phương án ép ColBERT vào pipeline. V3 raw-RRF hiện là runtime mặc định và tốt hơn trong audit mới, nhưng 40 case có verified retrieval gold vẫn là lát cắt hẹp nên chưa chứng minh production readiness toàn corpus.

### 4. Nguồn Bằng chứng Bất biến (Artifacts)
- [`Golden-50 v3 answer + NeMo + Ragas, 2026-09-02`](docs/evaluation/runs/answer-v3-golden50-production-20260902/report.md)
- [`Golden-50 v3 retrieval, 2026-09-02`](docs/evaluation/runs/retrieval-v3-golden50-production-20260902/report.md)
- [`Golden-50 dataset và nhãn đã tách`](docs/evaluation/golden50-v3/README.md)
- [`Balanced-50 v3 raw-RRF answer + Ragas`](docs/evaluation/runs/answer-v3-raw-balanced50-20260827-final2/report.md)
- [`Balanced-50 v3 raw-RRF retrieval gate`](docs/evaluation/runs/retrieval-v3-raw-balanced50-20260827-final/report.md)
- [`Identical-pool Qdrant ColBERT A/B`](docs/evaluation/runs/retrieval-v3-colbert-identical40-20260827-final2/report.md)
- [`Balanced-50 report`](docs/evaluation/runs/answer-balanced50-v2-live-20260822/report.md)
- [`Balanced-50 Qdrant-only final audit`](docs/evaluation/runs/answer-balanced50-qdrant-only-final-20260827/report.md)
- [`Representative-10 report`](docs/evaluation/runs/answer-representative10-v6-live-20260822/report.md)
- [`Vertex/Qdrant v3 Canary report`](docs/evaluation/runs/retrieval-vertex-v3-goldenfull-verified40-20260826/report.md)
- [`Vertex/Qdrant v3 50k migration report`](docs/evaluation/runs/vertex-qdrant-v3-50k-20260827/report.md)
- [`Portfolio evidence`](docs/evaluation/PORTFOLIO_EVIDENCE.md)
- [`Current evaluation status`](docs/evaluation/CURRENT_STATUS.md)

---

## Supabase cho legal browser online-only

V3 chat vẫn lấy evidence trực tiếp từ Qdrant payload. Riêng Vercel online-only dùng Supabase `public.legal_documents` cho `/search` và `/documents/{id}`; persistent/local tiếp tục đọc [`data/v3`](data/v3/README.md).

Trạng thái xác minh 2026-09-02: bảng, index và RLS đã tồn tại; đúng **4.969** văn bản trùng bộ ID v3 đã được upload. Publishable key chỉ có quyền `SELECT`; không có anonymous write policy. Ba mẫu `content_sha256` và tổng số dòng đã đối chiếu với nguồn local.

### 1. Cấu hình biến môi trường (`.env`)
```env
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_KEY
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVER_SIDE_SERVICE_ROLE_KEY
```

### 2. Tạo bảng trên Supabase SQL Editor
Chạy lệnh sau để lấy câu lệnh SQL DDL chuẩn hóa:
```powershell
python run_supabase_full_doc_upload.py --print-schema
```
Sao chép và thực thi trong **Supabase SQL Editor**:
```sql
create table if not exists public.legal_documents (
  document_id bigint primary key,
  document_number text not null,
  title text not null,
  source_url text not null,
  legal_type text not null,
  legal_sectors text not null,
  issuing_authority text not null,
  issuance_date text,
  content text not null,
  content_sha256 text not null,
  content_store_key text not null,
  quality_flags jsonb not null default '[]'::jsonb,
  dataset_revision text not null,
  uploaded_at timestamptz not null default now()
);
create index if not exists legal_documents_document_number_idx on public.legal_documents (document_number);
create index if not exists legal_documents_content_sha256_idx on public.legal_documents (content_sha256);
alter table public.legal_documents enable row level security;
```

`SUPABASE_SERVICE_ROLE_KEY` chỉ được đặt ở backend/CLI, không đưa vào Vercel client hoặc biến `NEXT_PUBLIC_*`. Uploader chủ động từ chối publishable key.

### 3. Kiểm tra kết nối & upload có chủ đích
```powershell
# Kiểm tra kết nối và bảng
python run_supabase_full_doc_upload.py --check-connection

# Ví dụ upload đúng tập v3 hiện tại với streaming batch và checkpoint resumable
python run_supabase_full_doc_upload.py --max-documents 4969 --batch-size 50 --allow-remote-write
```

## Tech stack

| Lớp | Công nghệ |
| :--- | :--- |
| API & UI | Python 3.12 (runtime package), FastAPI, Uvicorn, Jinja2, HTMX |
| Vector retrieval mặc định | Qdrant v3, Vertex dense 1024d + sparse IDF + raw RRF |
| Full-doc v3 | Supabase online-only; SQLite/Zstandard + FTS5 cho persistent/local, cùng đúng 4.969 văn bản đã audit |
| Legacy/free | Pinecone toàn corpus + Qdrant E5 384d/ColBERT staging |
| Generation | Google Vertex AI `gemini-3.5-flash` qua Application Default Credentials |
| Runtime data | Supabase cho legal browser; MongoDB cho session, interaction log, feedback và admin data |
| Evaluation & safety | Pytest, deterministic metrics, optional Ragas, NeMo Guardrails |
| Delivery | Docker hoặc Vercel FastAPI SSR online-only, GitHub Actions |


### Bằng chứng portfolio đã xác minh

| Tập đánh giá | Generation `STOP` | NeMo safe | Ragas coverage | Faithfulness | Answer accuracy | Context precision | Context recall | Technical errors |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Representative-10, `all-required-verified` | 10/10 | 10/10 | 10/10 | 0,9857 | 0,9750 | 0,9400 | 1,0000 | 0 |
| Golden-50 v3 raw-RRF, 26 factoid + 24 multi-hop | 50/50 | 50/50 | 49/50 | 0,8887 | 0,9184 | 0,8878 | 0,9354 | 1 judge error |

Nguồn bất biến:

- [`Golden-50 v3 current report`](docs/evaluation/runs/answer-v3-golden50-production-20260902/report.md)
- [`Representative-10 report`](docs/evaluation/runs/answer-representative10-v6-live-20260822/report.md)
- [`Portfolio evidence`](docs/evaluation/PORTFOLIO_EVIDENCE.md)
- [`Current evaluation status`](docs/evaluation/CURRENT_STATUS.md)

Metric deterministic trong code là mặc định. Retrieval metrics bao gồm Document/Article/Clause Recall@K, MRR, nDCG, exact-reference hit, multi-hop coverage, stage survival, no-candidate rate và technical-error rates. Answer metrics bao gồm exact match, token/character F1, ROUGE-L/CHRF, number/date/entity, citation và refusal metrics. Mọi aggregate lưu numerator, denominator, coverage, skipped cases và skip reasons.

## Chạy dự án từ một máy mới

### 1. Yêu cầu và tài nguyên

- Python 3.12 và Git. CI vẫn giữ một lane tương thích dependency trên Python 3.10, nhưng package runtime trong `pyproject.toml` yêu cầu `>=3.12,<3.13`.
- MongoDB local hoặc MongoDB Atlas; Supabase cho tra cứu toàn văn ở online-only.
- Qdrant Cloud và Google Cloud ADC để chạy v3 live. Pinecone chỉ cần cho đường legacy/free.
- Bundle v3 đã có trong repository (khoảng 41,3 MB). Chỉ cần khoảng **8 GiB disk trống** nếu tự dựng full corpus 518.255 văn bản; build hiện tại khoảng 3,08 GiB content + 0,21 GiB FTS, chưa tính file tải và file tạm.

> [!IMPORTANT]
> Repository chứa sẵn [`data/v3`](data/v3/README.md) cho đúng 4.969 văn bản thuộc collection v3, nên clone xong không cần dựng full local corpus để chạy v3. `data/huggingface/` vẫn bị ignore; chỉ cần dựng full store theo bước 3 nếu muốn đường toàn corpus 518.255 văn bản.

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
| Chọn pipeline | `USE_LEGACY_FREE_PIPELINE=false` cho v3; `true` cho Pinecone cũ và không gọi Google Cloud |
| Web/session | `MONGO_URL`, `WEB_SESSION_SECRET` (bắt buộc ổn định và ≥32 ký tự ở production) |
| Full-corpus retrieval/cache | `PINECONE_API_KEY`, index `vietlex-legal-rag-v1`, namespace `legal-documents-v1` |
| Dense inference/rerank | `QDRANT_URL`, `QDRANT_API_KEY` |
| V3 + Vertex generation | `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT` (không cần khi boolean là `true`) |
| Generation không Google Cloud | Ít nhất một trong `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `NVIDIA_API_KEY`, `GROQ_API_KEY` |
| Xác minh email | `ACCOUNT_EMAIL_ENABLED=true`, `EMAIL_USER`, Gmail App Password trong `EMAIL_PASS`, `EMAIL_FROM`, `PUBLIC_BASE_URL` |

Các biến và giá trị mặc định đầy đủ nằm trong [`.env.example`](.env.example). Không commit `.env`, JSON service account, cookie hoặc token. Ở production, `FRONTEND_URL` và `PUBLIC_BASE_URL` phải là HTTPS thật.

### 3. Dữ liệu cục bộ

V3 mặc định dùng ngay [`data/v3/content_store.sqlite3`](data/v3/README.md) và `legal_fts.sqlite3`; không cần chạy ingestion. Các lệnh dưới đây chỉ dành cho đường full corpus 518.255 văn bản:

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

Runtime mặc định dùng Qdrant v3 có **51.801 point** trên đúng **4.969 document ID** theo audit remote. Pinecone v1 có **518.255 record, một record/văn bản** và được chọn khi `USE_LEGACY_FREE_PIPELINE=true`. Con số **134.334** là số structural chunk của pilot v2 827 văn bản và không phải kích thước corpus production.

- Nếu bạn được cấp quyền vào index hiện có: chỉ cấu hình đúng key/index/namespace trong `.env`; không ingestion lại.
- Nếu dùng tài khoản Pinecone mới: phải tự dựng index bằng runbook. Lệnh full có thể xóa/recreate remote index, tốn quota/chi phí và không thuộc quickstart thông thường.
- Index Pinecone thử nghiệm riêng `llama-text-embed-v2-index` có 21.696 vector và không được hai runtime contract đọc. `STRUCTURAL_BACKEND_ENABLED` chỉ thuộc selector tương thích cũ, không điều khiển index Pinecone thử nghiệm này.

Lane Vertex–Qdrant v3 là runtime mặc định nhưng vẫn chỉ là **bounded migration slice**, không phải full corpus. Nó dùng `gemini-embedding-2` 1.024 chiều, dense cosine và sparse IDF trong collection `vietlex-legal-rag-v3-vertex-1024`. Dữ liệu được lấy cân bằng giữa nhiều loại văn bản, chunk theo Điều/Khoản và giới hạn số chunk trên mỗi văn bản để không làm tràn cluster. Lệnh migration mặc định chỉ lập kế hoạch cục bộ:

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

Tăng `--max-documents` và `--max-points` theo từng đợt; checkpoint mặc định ở `data/huggingface/vertex_qdrant_checkpoint.sqlite3`. Không bật lane này thay Pinecone trước khi có benchmark A/B trên identical inputs, đủ coverage và capacity gate theo bảng migration phía trên. `gemini-embedding-2` hỗ trợ tối đa 3.072 chiều, nhưng 1.024 được chọn để cân bằng chất lượng và storage; xem [Google Cloud model card](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/embedding-2) và [Qdrant hybrid vectors](https://qdrant.tech/documentation/manage-data/vectors/).

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

- **Vercel online-only SSR:** `app/server.py` chạy FastAPI/Jinja trực tiếp; Qdrant v3 cung cấp chat evidence, Supabase cung cấp legal-browser documents và local corpus bị loại khỏi bundle.
- **Persistent alternative:** `Dockerfile` vẫn hỗ trợ host có `/data` cho `content_store.sqlite3` và `legal_fts.sqlite3` khi `SERVERLESS_ONLINE_ONLY=false`.
- FastAPI trực tiếp dùng SSE; deployment live chỉ được tuyên bố sau kiểm tra HTTP và benchmark có manifest.

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
- V3 mặc định chỉ phủ đúng 4.969 document ID đã audit; pilot v2 riêng biệt phủ 827 văn bản luật chính. Không đường nào trong hai đường này đại diện toàn bộ 518.255 văn bản.
- Kết quả evaluation là bounded slice; không chứng minh whole-corpus legal accuracy hoặc production readiness.
- Vercel FastAPI SSR dùng progress registry process-local; nhiều replica cần shared event backend hoặc sticky routing.
- Cross-lane final rerank vẫn được chủ ý tắt theo quyết định `KEEP_DISABLED`.

## Tài liệu

- [`docs/PROJECT_CONTEXT.md`](docs/PROJECT_CONTEXT.md) — source-of-truth context
- [`docs/CURRENT_ARCHITECTURE.md`](docs/CURRENT_ARCHITECTURE.md) — runtime architecture
- [`docs/AGENT_WORKFLOW.md`](docs/AGENT_WORKFLOW.md) — engineering/evidence workflow
- [`docs/evaluation/PORTFOLIO_EVIDENCE.md`](docs/evaluation/PORTFOLIO_EVIDENCE.md) — recruiter-safe evidence
- [`docs/huggingface-ingestion-runbook.md`](docs/huggingface-ingestion-runbook.md) — ingestion operations
