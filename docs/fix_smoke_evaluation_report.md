# SYSTEM EVALUATION REPORT - VIETLEX LEGAL RAG

**Evaluation Timestamp**: `2026-08-02 20:02:03`  
**Number of Test Queries**: `2` across Factoid, Multi-hop and Unanswerable groups  
**Semantic cache enabled**: `False`  
**Dataset warning**: third-party research data; not an official source of current Vietnamese law.

## Metrics

| Metric | Value |
| :--- | ---: |
| Average end-to-end latency | 15.10s |
| Average queue latency | 2.48s |
| Average online pipeline latency | 12.62s |
| Average Ragas latency | 0.00s |
| Evaluation failures | 1/2 |
| Cache hits | 0/2 |
| Legal input pass rate | 100.0% |
| Answerable accuracy | 0.0% (0/2) |
| Grounded generation rate | 0.0% (0/2) |
| Service completion rate | 50.0% |
| Unanswerable accuracy | 0.0% (0/0) |
| Refusal precision | 0.0% |
| Refusal recall | 0.0% |
| Gold context hit rate | 50.0% (1/2) |
| Gold context recall | 0.25 |
| Retrieval MRR | 0.17 |
| Output blocked | 0/2 |
| Ragas Faithfulness | - |
| Ragas Answer Accuracy | - |
| Ragas Context Precision | - |
| Ragas Context Recall | - |

> Cache hits and honest refusals are not assigned artificial Ragas scores. Metric averages include scored generations only.

> Answerable accuracy requires Ragas answer accuracy >= 0.50; technical failures remain in denominators. Reference-less cases are excluded from direct retrieval metrics.

## Scenarios

| ID | Group | Query | Status | Latency | Faithfulness | Accuracy | Precision | Recall |
| :-: | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| 1 | Factoid | Theo Luật Bảo vệ môi trường, Giấy phép môi trường được định nghĩa như thế nào? | Input Guardrail Error | 5.01s | - | - | - | - |
| 2 | Multi-hop | Sự khác biệt cơ bản về tính chất áp dụng giữa quy chuẩn kỹ thuật môi trường và tiêu chuẩn môi trường là gì? | Honest Refusal | 25.18s | - | - | - | - |
