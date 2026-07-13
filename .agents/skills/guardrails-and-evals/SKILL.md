---
name: guardrails-and-evals
description: Hướng dẫn cấu hình NVIDIA NeMo Guardrails kiểm duyệt Input/Output và thiết lập Ragas LLM-as-a-judge dưới dạng Background Task để đánh giá chất lượng câu trả lời.
---

# NeMo Guardrails & Ragas Evaluation Skill

Kỹ năng này chịu trách nhiệm thiết lập các chốt chặn an toàn (Guardrails) để lọc các truy vấn độc hại/lạc đề và giám sát chất lượng nội dung sinh ra của mô hình thông qua đánh giá tự động (Ragas).

## 1. Cấu hình NeMo Guardrails
- Đặt cấu hình tại thư mục `guardrails_config/`:
  - `config.yml`: Định nghĩa các rails bảo mật (Input rails, Output rails).
  - `prompts.yml`: Prompts tùy chỉnh dùng cho mô hình phân loại nội dung.
- **Input Guardrails Check**: Lọc các câu hỏi mang tính tấn công (injection), xúc phạm hoặc lạc đề khỏi phạm vi pháp luật Việt Nam.
- **Output Guardrails Check**: Kiểm tra chéo xem câu trả lời được sinh ra có bám sát ngữ cảnh (context) đã cung cấp hay bị ảo giác (hallucination). Nếu phát hiện ảo giác, trả về tin nhắn fallback an toàn.

## 2. Ragas Evaluation (LLM-as-a-judge)
- Để tránh ảnh hưởng đến thời gian phản hồi (latency) của người dùng, luồng đánh giá phải chạy không đồng bộ dưới dạng **FastAPI Background Task**.
- Sử dụng framework Ragas để tính toán các chỉ số:
  - **Faithfulness**: Độ trung thực của câu trả lời so với ngữ cảnh.
  - **Answer Relevance**: Mức độ liên quan của câu trả lời đối với câu hỏi gốc.
  - **Context Recall**: Mức độ đầy đủ của thông tin truy xuất được.
- Kết quả đánh giá và điểm số (metrics score) phải được lưu trữ cùng với `trace_id` để phục vụ audit/dashboard sau này.

```python
# Ví dụ cấu hình background task trong routes.py
from fastapi import BackgroundTasks

@router.post("/chat")
async def chat(message: str, background_tasks: BackgroundTasks):
    # Luồng xử lý chính...
    background_tasks.add_task(
        evaluator.run_llm_as_judge,
        user_query,
        context,
        bot_response,
        trace_id
    )
```
