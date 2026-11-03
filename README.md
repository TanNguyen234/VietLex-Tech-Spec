# VietLex

VietLex là ứng dụng nghiên cứu pháp luật Việt Nam có truy nguồn. Hệ thống hỗ trợ tra cứu văn bản, đọc tài liệu chính thức, giữ trích đoạn, hội thoại theo hồ sơ và xuất kết quả nghiên cứu.

[Ứng dụng](https://vietlex-legal-rag.vercel.app) · [English](README.en.md) · [Báo cáo phát hành](docs/tasks/production-readiness-20261103/REPORT.md)

## Trạng thái phát hành

Bản triển khai ngày 03/11/2026 đã được kiểm chứng kỹ thuật bằng kiểm thử tự động và các luồng HTTP thực. Đây là công cụ hỗ trợ nghiên cứu; kết quả không phải ý kiến pháp lý được chứng nhận.

**Production readiness toàn diện chưa được chứng minh.** Bộ Golden50 có phạm vi hẹp; Ragas dùng cùng model family với mô hình sinh; hồ sơ L04 mới được review nguồn bằng AI, chưa có phê duyệt pháp lý độc lập. Các giới hạn này được giữ rõ thay vì chuyển thành trạng thái đạt.

## Kết quả đánh giá

Golden50 được chạy qua service production với Vertex/Qdrant thực. Bước chấm deterministic 3.3 và Ragas dùng lại đúng 50 câu trả lời cùng ngữ cảnh đã lưu; không sinh lại câu trả lời để chọn điểm tốt hơn. Tám ca HTTP trên tên miền chính được kiểm tra riêng.

| Hạng mục | Kết quả | Phạm vi |
| --- | ---: | --- |
| Kiểm thử Python | 2.240 passed | 6 ca live được loại khỏi vòng provider-free |
| Kiểm thử Node | 22 passed | Luồng frontend, session và hủy tác vụ |
| HTTP frozen / phân quyền | 8/8; ADMIN/USER đạt | Guardrails, replay/export, MongoDB, đọc PDF |
| Guardrails Golden50 | Input 50/50; output 50/50 | Luôn enforce ở public chat local và online |
| Document / Article / Clause Recall@3 | 53/53; 29/30; 13/14 | 40 ca có gold; 10 ca thiếu gold được skip |
| Multi-hop full coverage | 38/40 | Gate retrieval hiện có đạt |
| Exact match / token F1 | 0,0000 / 0,2323 | 50 ca; không đồng nghĩa đúng/sai pháp lý |
| Citation precision / invalid rate | 0,9679 / 0,0321 | Metric 3.3; 49 ca có căn cứ chấm |
| Ragas faithfulness | 0,8333 | 49/50 ca; 1 ca không có prompt context |
| Ragas answer accuracy | 0,9000 | 50/50 ca |
| Ragas context precision / recall | 0,8708 / 0,9490 | 49/50 ca |
| Lỗi kỹ thuật Ragas | 0 | 754 lời gọi structured judge được ghi nhận |
| Tổng thời gian Golden50 P50 / P95 | 56,95 / 62,65 giây | Service benchmark, không phải load test HTTP |

Ragas là audit bổ sung, không xác nhận hiệu lực pháp luật. Có 17/49 ca có faithfulness dưới 0,8 theo judge. Nhãn số/ngày/thực thể chưa có trong bộ này nên những metric tương ứng là N/A; citation recall chỉ có gold ở 1/50 ca. Không gán điểm đạt cho chiều thiếu nhãn.

Xem [full deterministic metric](docs/evaluation/runs/crg-golden50-20261103-3ee9f610/FULL_METRICS.md), [Ragas raw summary](docs/evaluation/runs/ragas-golden50-20261103-256a0838/summary.json), [kết quả từng ca](docs/evaluation/runs/ragas-golden50-20261103-256a0838/results.json) và [biên bản kiểm chứng](docs/evaluation/runs/crg-golden50-20261103-3ee9f610/REPORT.md).

## Phạm vi dữ liệu và kiến trúc

Corpus ghim gồm 518.255 hồ sơ từ [dataset bên thứ ba](https://huggingface.co/datasets/vohuutridung/vietnamese-legal-documents), revision `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`. Không đồng nhất tổng corpus với dữ liệu online. Audit ngày 27/10/2026 ghi nhận 14.982 document ID và 142.063 điểm Qdrant V3; lượt phát hành này không kiểm kê lại toàn bộ remote corpus.

| Tuyến | Hợp đồng |
| --- | --- |
| `USE_LEGACY_FREE_PIPELINE=false` | Vertex `gemini-embedding-2` 1024 chiều, Qdrant V3, sparse IDF và blend RRF+DBSF |
| `USE_LEGACY_FREE_PIPELINE=true` | E5-small 384 chiều, Pinecone V1, SQLite/Zstandard; chặn Google/Vertex trước khi tạo client |
| API và giao diện | FastAPI, Jinja/HTMX, hội thoại và hồ sơ nghiên cứu theo chủ sở hữu |
| Nguồn chính thức ngoài corpus | Đọc theo yêu cầu, giữ URL/hash/phạm vi trang; không tự nâng thành luật đã xác minh |
| An toàn | CSRF, CORS, authentication, rate limits; lỗi guardrail kỹ thuật được tách khỏi semantic rejection |

Hai tuyến retrieval không tự cross-fallback. Guardrails của public chat luôn enforce; tham số legacy `off`, `shadow` hoặc `false` không tắt được kiểm tra. Timeout quyết định mặc định là 20 giây; lỗi kỹ thuật được trả có kiểu, không được biến thành kết luận an toàn.

## Hồ sơ L04

[Review nguồn L04](docs/legal/L04-AI-SOURCE-REVIEW-20261103.md) đối chiếu nghĩa vụ cấp phép, thẩm quyền, sửa đổi 2025–2026 và chuyển tiếp cho mốc 29/10/2026. Kết luận nguồn có điều kiện: không được suy miễn giấy phép chỉ vì không có nước thải/khí thải khi nhập khẩu phế liệu; phải kiểm tra các ngoại lệ riêng và đúng chủ thể cấp phép.

Review được thực hiện bằng AI theo chỉ định của người dùng. Không có chữ ký chuyên gia bị tạo giả, không đổi gold labels và không công bố hồ sơ thành human-approved. Runtime tiếp tục từ chối chứng nhận hiệu lực hiện hành khi chuỗi căn cứ chưa đủ.

## Chạy local

Cần Python 3.12. Các bước sau không tải corpus và không tạo hay migrate index:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-demo.lock
python -m pip install . --no-deps
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload --port 8000
```

Mở `http://127.0.0.1:8000`. Chat đầy đủ cần cấu hình provider và nguồn dữ liệu tương ứng; mở được giao diện không đồng nghĩa các phụ thuộc đã sẵn sàng. Không đưa `.env`, credentials hoặc corpus local vào Git.

## Kiểm thử và đánh giá

```powershell
python -m pytest -m "not live" -q
node --test tests/*.test.cjs
```

Đánh giá deterministic mặc định không gọi Ragas. Lệnh live dưới đây có thể phát sinh chi phí provider; dùng run ID mới:

```powershell
python run_answer_eval.py --dataset docs/evaluation/golden50-v3/cases.json --sidecar docs/evaluation/golden50-v3/labels.json --backend production --ranking rrf-dbsf --profile separated_intent --rewrite off --guardrails enforce --reranker current --concurrency 2 --gold-policy none --judge none --run-id YOUR_UNIQUE_RUN_ID
```

Audit Ragas được chạy tách riêng trên câu trả lời đã lưu. Script gốc, phiên bản thư viện, source/input hashes, kết quả và ledger nằm trong [run Ragas](docs/evaluation/runs/ragas-golden50-20261103-256a0838/manifest.json). Model judge được yêu cầu là `gemini-3.5-flash`; adapter hiện không cung cấp token usage hoặc response model version, nên các trường đó được ghi UNKNOWN.

Không chạy ingestion toàn corpus, thay model/dimension bền vững hoặc xóa/rebuild index như một bước cài đặt. Những thao tác đó cần kế hoạch và quyền riêng.

## Sử dụng kết quả

Mở từng nguồn, đối chiếu Điều/Khoản và ngày áp dụng trước khi sử dụng. Không có kết quả không chứng minh một quy định không tồn tại. VietLex không phải cơ sở dữ liệu pháp luật chính thức; người sử dụng chịu trách nhiệm kiểm chứng và xin ý kiến chuyên môn khi cần.
