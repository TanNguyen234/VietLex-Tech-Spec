---
name: observability-logfire
description: Hướng dẫn tích hợp Pydantic Logfire để giám sát, ghi logs và theo dõi các trace span, độ trễ (latency tracking) trong FastAPI và các services của dự án Vietlex Legal RAG. Kích hoạt khi cần cài đặt logfire, đặt các decorators `@logfire.instrument` cho service, truyền context variables (trace_id) giữa các tác vụ nền, hoặc gỡ lỗi bottlenecks hiệu năng.
---

# Observability with Pydantic Logfire Skill

Kỹ năng này hướng dẫn cách cấu hình, sử dụng và tích hợp **Pydantic Logfire** để giám sát toàn diện hoạt động của API và RAG Pipeline. Việc này cho phép theo dõi vết (tracing), ghi log lỗi (exception logging), đo lường độ trễ (latency) và kiểm soát payload truyền qua các tầng nghiệp vụ của Vietlex Legal RAG.

---

## 1. Khởi tạo Logfire toàn cục (Global Initialization)

Logfire cần được cấu hình ngay khi ứng dụng khởi chạy và thực hiện bọc (instrument) ứng dụng FastAPI để tự động ghi nhận dữ liệu telemetry của mọi HTTP Request/Response.

```python
# app/main.py
from fastapi import FastAPI
import logfire

# Khởi tạo Logfire
logfire.configure()

app = FastAPI()

# Tự động instrument ứng dụng FastAPI để đo đạc thời gian request, status codes, v.v.
logfire.instrument_fastapi(app)
```

---

## 2. Giám sát các hàm dịch vụ cốt lõi (Services Instrumentation)

### Tại sao cần thiết?
Một luồng xử lý RAG nâng cao đi qua rất nhiều bước trung gian: Kiểm tra Semantic Cache -> Phân tách từ tiếng Việt -> Dense Search -> Sparse Search -> Reciprocal Rank Fusion -> Cohere Rerank -> LLM Generation. Việc đặt decorator `@logfire.instrument` trên từng hàm dịch vụ giúp tự động xây dựng cây Trace Spans phân tầng trực quan trên Dashboard của Logfire, giúp phát hiện ngay lập tức bước nào gây ra nút thắt cổ chai về mặt thời gian (latency bottleneck).

### Cách sử dụng decorator:
Sử dụng decorator `@logfire.instrument` trên các hàm xử lý chính thuộc `app/services/`.

```python
# app/services/rag_pipeline.py
import logfire

@logfire.instrument("Kiểm tra bộ nhớ đệm ngữ nghĩa cho query: {user_query}")
async def check_semantic_cache(user_query: str) -> dict | None:
    # Logic kiểm tra cache với cosine similarity
    ...

@logfire.instrument("Thực hiện Hybrid Search Dense & Sparse cho query: {query}")
async def run_hybrid_search(query: str) -> list:
    # Logic tìm kiếm
    ...

@logfire.instrument("Chạy luồng RAG hoàn chỉnh cho query: {user_query}")
async def run_advanced_rag(user_query: str) -> str:
    # Hàm tổng hợp gọi tuần tự các bước trên
    cache_hit = await check_semantic_cache(user_query)
    if cache_hit:
        return cache_hit["response"]
        
    retrieved_docs = await run_hybrid_search(user_query)
    # ... logic sinh câu trả lời ...
```

---

## 3. Truyền Trace ID & Log nâng cao (Context Variables)

### Tại sao cần thiết?
Mỗi yêu cầu từ người dùng cần được gán một `trace_id` độc bản. Khi có lỗi phát sinh trong một tác vụ chạy ngầm (Background Task) như Ragas Evaluator, nếu không có `trace_id` liên kết, chúng ta không thể biết lỗi đó thuộc về câu hỏi nào của người dùng.

### Kỹ thuật truyền ngữ cảnh (Context Propagation):
Sử dụng context variables của Logfire hoặc truyền tường minh `trace_id` trong log tags/attributes để nhóm các bản ghi log lại với nhau.

```python
# app/services/evaluator.py
import logfire

class RagasEvaluator:
    def run_llm_as_judge(self, query: str, context: list, response: str, trace_id: str):
        # Thiết lập context/tags để tất cả logs trong hàm này đều mang trace_id
        with logfire.span("Chạy đánh giá chất lượng", trace_id=trace_id) as span:
            # Thực hiện đánh giá
            # ...
            
            # Ghi log thành công
            logfire.info(
                "Đã chấm điểm câu trả lời",
                trace_id=trace_id,
                faithfulness=0.98,
                relevance=0.95
            )
```
- **Lưu ý bảo mật**: Không bao giờ log trực tiếp các thông tin nhạy cảm của hệ thống như `QDRANT_API_KEY`, `LITELLM_MASTER_KEY` hay mật khẩu của database vào Logfire.
