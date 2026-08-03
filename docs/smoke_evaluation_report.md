# SYSTEM EVALUATION REPORT - VIETLEX LEGAL RAG

**Evaluation Timestamp**: `2026-08-02 19:52:32`  
**Number of Test Queries**: `6` across Factoid, Multi-hop and Unanswerable groups  
**Semantic cache enabled**: `False`  
**Dataset warning**: third-party research data; not an official source of current Vietnamese law.

## Metrics

| Metric | Value |
| :--- | ---: |
| Average end-to-end latency | 87.94s |
| Average queue latency | 61.54s |
| Average online pipeline latency | 24.99s |
| Average Ragas latency | 1.41s |
| Evaluation failures | 3/6 |
| Cache hits | 0/6 |
| Legal input pass rate | 100.0% |
| Answerable accuracy | 0.0% (0/4) |
| Grounded generation rate | 50.0% (2/4) |
| Service completion rate | 83.3% |
| Unanswerable accuracy | 50.0% (1/2) |
| Refusal precision | 33.3% |
| Refusal recall | 50.0% |
| Gold context hit rate | 33.3% (2/6) |
| Gold context recall | 0.25 |
| Retrieval MRR | 0.33 |
| Output blocked | 0/6 |
| Ragas Faithfulness | - |
| Ragas Answer Accuracy | - |
| Ragas Context Precision | - |
| Ragas Context Recall | - |

> Cache hits and honest refusals are not assigned artificial Ragas scores. Metric averages include scored generations only.

> Answerable accuracy requires Ragas answer accuracy >= 0.50; technical failures remain in denominators. Reference-less cases are excluded from direct retrieval metrics.

## Scenarios

| ID | Group | Query | Status | Latency | Faithfulness | Accuracy | Precision | Recall |
| :-: | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| 1 | Factoid | Theo Luật Bảo vệ môi trường, Giấy phép môi trường được định nghĩa như thế nào? | Honest Refusal | 24.53s | - | - | - | - |
| 2 | Multi-hop | Sự khác biệt cơ bản về tính chất áp dụng giữa quy chuẩn kỹ thuật môi trường và tiêu chuẩn môi trường là gì? | Eval Failed | 51.13s | - | - | - | - |
| 3 | Unanswerable | Mức phạt đối với tổ chức, cá nhân không có Giấy phép môi trường khi nhập khẩu phế liệu từ nước ngoài là bao nhiêu? | Output Guardrail Error | 67.87s | - | - | - | - |
| 4 | Factoid | Cụm từ "doanh nghiệp nhà nước" trong Luật Ngân sách nhà nước số 83/2015/QH13 được thay thế bằng cụm từ nào theo quy định tại văn bản này? | Honest Refusal | 80.66s | - | - | - | - |
| 5 | Multi-hop | Khi chi nhánh của doanh nghiệp chấm dứt hoạt động, doanh nghiệp đó có những trách nhiệm gì liên quan đến nợ và người lao động của chi nhánh? | Eval Failed | 145.10s | - | - | - | - |
| 6 | Unanswerable | Mức xử phạt hành chính cụ thể đối với hành vi không báo cáo về việc tuân thủ quy định của Luật Doanh nghiệp theo yêu cầu của Cơ quan đăng ký kinh doanh là bao nhiêu? | Honest Refusal | 158.35s | - | - | - | - |
