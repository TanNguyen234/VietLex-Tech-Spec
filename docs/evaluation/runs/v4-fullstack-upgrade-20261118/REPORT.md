# VietLex V4 Full-Stack Upgrade — Live Evaluation Report (`v4-fullstack-upgrade-20261118`)

## 1. Tổng quan kết quả thực nghiệm trực tiếp (Live Production Stack)
- **Git SHA / Dirty Proof:** `431003ace17e15c7b7bf3443b1d78c261840dc2b` (`git_dirty=True`, `git_diff_sha256=5d911d93a3add9e2…`)
- **Kho dữ liệu pháp luật đám mây (1:1:1 Parity):** `6541` văn bản quy phạm · `224999` đoạn cấu trúc Qdrant V3 · Qdrant Disk `2.366 GiB / 4.00 GiB` · RAM `274.22 MiB / 1024 MiB`
- **Kết quả Rubric 31 câu hỏi pháp luật thực tế (`POST /chat/stream`):** **30/31 PASS** (so với baseline ngày 2026-11-17: **13/31 PASS**)
- **Độ trễ phản hồi (Streaming TTFT trung vị):** `13663.8 ms` · Tổng thời gian trung vị `36.001 s`
- **Kiểm chứng định tuyến đa Provider (Dev/Test/Admin) vs Giới hạn Quota Public (`APP_ENV=production`):** `PASS=True` (`Gemini`, `Groq`, `OpenRouter`, `Vertex`, `Tavily` hoạt động đầy đủ; khách ẩn danh `401`, user thường chạm ngưỡng `429` và khóa `auto`)
- **Kiểm chứng E2E Hồ sơ Luật sư (Workspace):** `PASS=True` (Trích xuất DOCX `<w:numPr>` + `<w:tbl>`, Redline từng từ `<del>`/`<ins>`, rà soát theo lô có căn cứ luật, xuất báo cáo `.docx` khổ A4 chuẩn Nghị định 30/2020/NĐ-CP)

## 2. Đối chiếu chi tiết 31 câu hỏi pháp luật (Baseline Vòng 7 vs VietLex V4)

| # | Mã | Nhóm | Baseline (17/11) | VietLex V4 | TTFT (ms) | Tổng (s) | Nguồn | Ghi chú kiểm chứng |
|---|---|---|---|---|---:|---:|---:|---|
| 1 | `L01` | lao động | PASS | **PASS** | 13663.8 | 16.359 | 15 | BLLĐ 2019 Điều 25 K2 (60 ngày) |
| 2 | `L02` | lao động | PASS | **PASS** | 39099.9 | 43.396 | 26 | BLLĐ 2019 Điều 35 K1a (45 ngày) |
| 3 | `L03` | lao động | FAIL | **PASS** | 6509.1 | 10.704 | 29 | BLLĐ 2019 Điều 40 nghĩa vụ bồi thường khi đơn phương trái luật |
| 4 | `T01` | thực tập | FAIL | **PASS** | 8512.6 | 15.578 | 17 | Phân biệt thực tập/dấu hiệu HĐLĐ theo Điều 13 BLLĐ 2019 |
| 5 | `T02` | thực tập | FAIL | **PASS** | 19800.8 | 30.552 | 14 | Điều kiện đóng BHXH bắt buộc & nghỉ phép |
| 6 | `T03` | thực tập | FAIL | **PASS** | 12267.6 | 17.778 | 30 | Mức lương tối thiểu vùng NĐ 293/2025/NĐ-CP / NĐ 74/2024 |
| 7 | `B01` | bảo hiểm xã hội | FAIL | **PASS** | 6441.3 | 9.877 | 23 | Luật BHXH 2024 Điều 64 (15 năm đóng BHXH) |
| 8 | `B02` | bảo hiểm xã hội | PASS | **FAIL** | — | 40.597 | 0 | HTTP 503: Luồng phản hồi bị gián đoạn giữa chừng. Vui lòng thử lại. |
| 9 | `D01` | vay và hợp đồng | PASS | **PASS** | 49628.4 | 78.537 | 16 | BLDS 2015 Điều 119/463/466 & BLTTDS chứng cứ dữ liệu điện tử |
| 10 | `D02` | vay và hợp đồng | PASS | **PASS** | 9921.8 | 12.414 | 9 | BLDS 2015 Điều 429 (3 năm) |
| 11 | `D03` | vay và hợp đồng | PASS | **PASS** | 5678.1 | 35.564 | 22 | BLDS 2015 Điều 119 giao dịch bằng lời nói |
| 12 | `R01` | đất đai và công chứng | FAIL | **PASS** | 58469.3 | 61.224 | 23 | Công chứng hợp đồng chuyển nhượng QSDĐ (Luật Đất đai 2024 Điều 27) |
| 13 | `R02` | đất đai và công chứng | FAIL | **PASS** | 6089.3 | 36.001 | 25 | Luật Đất đai 2024 Điều 138 cấp sổ đỏ mua giấy tay |
| 14 | `R03` | đất đai và công chứng | FAIL | **PASS** | 60434.9 | 65.053 | 23 | BLDS 2015 Điều 129 K2 công nhận hiệu lực khi thực hiện 2/3 nghĩa vụ |
| 15 | `H01` | hôn nhân và gia đình | FAIL | **PASS** | 46407.8 | 50.647 | 17 | Luật HNGĐ 2014 Điều 81 K3 con dưới 36 tháng tuổi giao cho mẹ |
| 16 | `H02` | hôn nhân và gia đình | PASS | **PASS** | 75937.4 | 79.277 | 9 | Luật HNGĐ 2014 Điều 8 K1 tuổi kết hôn |
| 17 | `G01` | giao thông | FAIL | **PASS** | 6153.3 | 10.482 | 28 | NĐ 168/2024/NĐ-CP phạt nồng độ cồn xe máy & tạm giữ xe |
| 18 | `G02` | giao thông | FAIL | **PASS** | 5059.4 | 37.398 | 16 | NĐ 168/2024/NĐ-CP vượt đèn đỏ ô tô (18–20 triệu) |
| 19 | `E01` | doanh nghiệp | PASS | **PASS** | 4884.6 | 6.939 | 9 | Luật Doanh nghiệp 2020 vốn điều lệ TNHH MTV |
| 20 | `E02` | doanh nghiệp | PASS | **PASS** | 8113.4 | 13.226 | 16 | Trách nhiệm hữu hạn cổ đông/chủ sở hữu & nghĩa vụ trả lương |
| 21 | `X01` | thuế | FAIL | **PASS** | 39815.8 | 42.529 | 17 | Mức tính tiền chậm nộp thuế 0,03%/ngày |
| 22 | `X02` | thuế | PASS | **PASS** | 42259.7 | 54.058 | 19 | Ngưỡng giảm trừ gia cảnh TNCN (NQ 110/2025/UBTVQH15) |
| 23 | `P01` | tố tụng và hành động | FAIL | **PASS** | 44834.5 | 54.787 | 18 | Tranh chấp đòi nợ dân sự & thủ tục hòa giải |
| 24 | `F02` | tố tụng và hành động | PASS | **PASS** | 38593.5 | 42.374 | 22 | Quyền nộp đơn khởi kiện sau hòa giải không thành |
| 25 | `P02` | tố tụng và hành động | FAIL | **PASS** | 38971.0 | 43.214 | 23 | BLTTDS 2015 Điều 189 hồ sơ khởi kiện dân sự |
| 26 | `P03` | tố tụng và hành động | FAIL | **PASS** | 41797.1 | 47.08 | 22 | BLLĐ 2019 Điều 188 hòa giải tranh chấp lao động cá nhân |
| 27 | `O01` | ngoài phạm vi và bịa đặt | PASS | **PASS** | 48650.0 | 53.96 | 8 | Từ chối trung thực văn bản giả định Luật Bảo vệ thú cưng 2026 |
| 28 | `O02` | ngoài phạm vi và bịa đặt | FAIL | **PASS** | 7625.0 | 11.487 | 7 | Đạt các tiêu chí C1–C6 |
| 29 | `O03` | ngoài phạm vi và bịa đặt | PASS | **PASS** | — | 1.768 | 0 | Chặn đúng câu hỏi tư vấn đầu tư ngoài phạm vi pháp luật |
| 30 | `O04` | ngoài phạm vi và bịa đặt | FAIL | **PASS** | 5994.9 | 10.0 | 17 | Phân biệt sa thải đúng pháp luật vs sa thải trái pháp luật (Điều 41/125 BLLĐ) |
| 31 | `F01` | ngoài phạm vi và bịa đặt | FAIL | **PASS** | 6630.5 | 23.232 | 27 | Bồi thường khi sa thải trái pháp luật theo Điều 41 BLLĐ 2019 |
