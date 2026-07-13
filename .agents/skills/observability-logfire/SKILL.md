---
name: observability-logfire
description: Hướng dẫn tích hợp Pydantic Logfire để giám sát, ghi log và theo dõi các span độ trễ (latency tracking) trong FastAPI và services của dự án Vietlex Legal RAG.
---

# Observability with Pydantic Logfire Skill

Kỹ năng này đảm bảo mọi hoạt động của API và RAG Pipeline được giám sát và lưu vết (tracing) đầy đủ về độ trễ, exception và dữ liệu payload.

## 1. Khởi tạo Logfire toàn cục
Khởi tạo Logfire trong `app/main.py` ngay khi FastAPI app được tạo:
```python
import logfire

logfire.configure()
logfire.instrument_fastapi(app)
```

## 2. Theo dõi các hàm cốt lõi (Services)
- Sử dụng decorator `@logfire.instrument` trên các hàm trong thư mục `app/services/` (ví dụ: `run_advanced_rag`, `check_semantic_cache`, `run_llm_as_judge`).
- Việc này tự động sinh các trace span phân tầng, giúp xác định nút thắt cổ chai về hiệu năng (bottleneck).

```python
import logfire

@logfire.instrument("Chạy luồng truy xuất nâng cao cho truy vấn: {user_query}")
async def run_advanced_rag(user_query: str):
    # Logic code...
    pass
```

## 3. Log thông tin phụ thuộc và Trace ID
- Mỗi request sẽ có một `trace_id` độc bản dạng UUID.
- Ghi log (Log logs/warnings) kèm theo `trace_id` này để dễ dàng phân tích log đa kênh khi có sự cố.
- Sử dụng logfire context variables để truyền trace id tự động qua các background task.
