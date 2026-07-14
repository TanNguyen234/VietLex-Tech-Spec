---
name: guardrails-and-evals
description: Hướng dẫn cấu hình NVIDIA NeMo Guardrails để kiểm duyệt tính an toàn của Input/Output và thiết lập Ragas LLM-as-a-judge chạy không đồng bộ dưới dạng Background Task để đánh giá chất lượng câu trả lời cho dự án Vietlex Legal RAG. Kích hoạt khi cần cài đặt hệ thống kiểm duyệt prompt, lọc câu hỏi độc hại/lạc đề, kiểm tra ảo giác của câu trả lời, hoặc thiết lập các chỉ số đánh giá RAG (Faithfulness, Relevance, Recall).
---

# NeMo Guardrails & Ragas Evaluation Skill

Kỹ năng này hướng dẫn thiết lập hệ thống kiểm duyệt và tự động đánh giá chất lượng câu trả lời (LLM-as-a-judge) cho dự án Vietlex Legal RAG nhằm đảm bảo tính an toàn, bảo mật thông tin và đo lường liên tục hiệu năng của hệ thống.

---

## 1. Kiểm duyệt An toàn với NVIDIA NeMo Guardrails

### Tại sao cần thiết?
Hệ thống RAG pháp luật dễ bị khai thác thông qua các hình thức Prompt Injection (tấn công đưa mã độc/chỉ thị độc hại), câu hỏi xúc phạm, hoặc người dùng cố tình hỏi các chủ đề nhạy cảm ngoài phạm vi pháp luật Việt Nam. Kiểm duyệt đầu ra giúp ngăn chặn ảo giác (hallucination) - trường hợp LLM sinh ra thông tin pháp luật sai lệch hoặc bịa đặt.

### Cấu hình thư mục `guardrails_config/`:

*   **`config.yml`**: Định nghĩa cấu trúc các luồng kiểm duyệt (flows).
    ```yaml
    models:
      - type: main
        engine: openai
        model: legal-core-model

    rails:
      # Định nghĩa các chốt chặn
      input:
        flows:
          - check jailbreak
          - filter off-topic questions
      output:
        flows:
          - check hallucination
    ```

*   **`prompts.yml`**: Tinh chỉnh prompt để phân loại nội dung chính xác.
    *   *Input Check*: Huấn luyện mô hình nhận diện xem câu hỏi có thuộc phạm vi pháp luật Việt Nam không. Nếu không, kích hoạt fallback từ chối trả lời một cách lịch sự.
    *   *Output Check*: Thực hiện kiểm tra chéo (N-shot / Self-Consistency) xem câu trả lời của mô hình có được hỗ trợ 100% bởi các điều luật được truy xuất từ Qdrant hay không.

---

## 2. Đánh giá chất lượng tự động với Ragas (LLM-as-a-judge)

### Tại sao chạy không đồng bộ (Asynchronous Background Task)?
Quá trình chấm điểm bằng Ragas yêu cầu gọi thêm các API LLM độc lập để đánh giá tính trung thực và sự liên quan. Nếu chạy đồng bộ trong luồng phản hồi chính, thời gian chờ của người dùng (latency) sẽ tăng gấp 2 - 3 lần. Việc sử dụng `BackgroundTasks` của FastAPI giúp trả về giao diện cho người dùng ngay lập tức, trong khi tiến trình chấm điểm diễn ra ngầm.

### Các chỉ số chấm điểm cốt lõi:
1. **Faithfulness (Độ trung thực)**: Đo lường xem câu trả lời được sinh ra có hoàn toàn dựa trên ngữ cảnh được cung cấp không (ngăn chặn ảo giác).
2. **Answer Relevance (Độ liên quan)**: Đo lường mức độ phản hồi trực tiếp của câu trả lời đối với câu hỏi của người dùng (tránh trả lời lan man, lạc đề).
3. **Context Recall (Độ đầy đủ)**: Đo lường xem các điều luật được Qdrant truy xuất có chứa đầy đủ thông tin để trả lời câu hỏi hay không.

### Mẫu triển khai code:

```python
# app/services/evaluator.py
import logfire
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevance, context_recall
from datasets import Dataset

class RagasEvaluator:
    def __init__(self, llm_client):
        self.llm = llm_client

    @logfire.instrument("Chạy đánh giá chất lượng Ragas cho trace_id: {trace_id}")
    def run_llm_as_judge(self, query: str, context: list[str], response: str, trace_id: str):
        try:
            # Ragas yêu cầu cấu trúc dataset dạng bảng
            data = {
                "question": [query],
                "contexts": [context],
                "answer": [response]
            }
            dataset = Dataset.from_dict(data)
            
            # Thực hiện đánh giá bằng LLM-as-a-judge
            result = evaluate(
                dataset=dataset,
                metrics=[faithfulness, answer_relevance, context_recall],
                llm=self.llm
            )
            
            # Ghi nhận kết quả đánh giá cùng trace_id để phân tích
            scores = {
                "faithfulness": result["faithfulness"],
                "answer_relevance": result["answer_relevance"],
                "context_recall": result["context_recall"]
            }
            
            logfire.info(
                "Đánh giá Ragas hoàn thành",
                trace_id=trace_id,
                metrics=scores
            )
            
            # TODO: Lưu scores vào Database để hiển thị lên Dashboard giám sát hiệu năng
            
        except Exception as e:
            logfire.error("Lỗi khi chạy Ragas evaluator", error=str(e), trace_id=trace_id)
```

```python
# app/api/routes.py
from fastapi import APIRouter, BackgroundTasks, Depends
from app.services.evaluator import RagasEvaluator
# ... các imports khác ...

@router.post("/chat")
async def chat(
    message: str,
    background_tasks: BackgroundTasks,
    evaluator: Annotated[RagasEvaluator, Depends(get_evaluator)]
):
    # 1. Chạy Input Guardrails
    # 2. Advanced Retrieval & Generation
    # 3. Chạy Output Guardrails
    
    # 4. Kích hoạt đánh giá ngầm và lưu vết
    trace_id = "uuid-generated-for-request"
    background_tasks.add_task(
        evaluator.run_llm_as_judge,
        user_query=message,
        context=retrieved_chunks,
        bot_response=final_response,
        trace_id=trace_id
    )
    
    return {"response": final_response, "trace_id": trace_id}
```
