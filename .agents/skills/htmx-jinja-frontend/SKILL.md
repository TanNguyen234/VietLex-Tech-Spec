---
name: htmx-jinja-frontend
description: Hướng dẫn cấu hình Jinja2 Templates, giao tiếp không đồng bộ qua HTMX và tối ưu hóa CSS bằng TailwindCSS cho giao diện ứng dụng Vietlex Legal RAG.
---

# HTMX & Jinja2 Frontend Skill

Kỹ năng này hướng dẫn AI Agent thiết lập giao diện người dùng nhẹ, tương tác mượt mà không cần dùng các framework SPA phức tạp như React/Vue, nhờ sự kết hợp của Jinja2, HTMX và TailwindCSS.

## 1. Cơ chế Hoạt động của HTMX
- HTMX cho phép gửi yêu cầu AJAX trực tiếp từ các thuộc tính HTML.
- Khi người dùng gửi tin nhắn (submit form), HTMX gửi yêu cầu `POST /chat` lên FastAPI.
- FastAPI không trả về JSON mà render trực tiếp template Jinja2 partial (`chat_message.html`) và trả về chuỗi HTML.
- HTMX nhận chuỗi HTML này và chèn/thay thế vào vùng hiển thị chat (ví dụ: `hx-swap="beforeend"`).

## 2. Giao diện Chính (index.html)
- Chứa cấu trúc HTML cơ bản, tích hợp TailwindCSS qua CDN (hoặc build tĩnh).
- Chứa CSRF Meta tag hoặc input hidden để HTMX tự động thu thập token bảo mật gửi lên server.

```html
<!-- Form chat ví dụ trong index.html -->
<form hx-post="/chat" 
      hx-target="#chat-history" 
      hx-swap="beforeend" 
      hx-on::after-request="this.reset()">
    <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
    <input type="text" name="message" placeholder="Nhập câu hỏi pháp lý..." required>
    <button type="submit">Gửi</button>
</form>
```

## 3. Template Partial (chat_message.html)
- Chỉ chứa cấu trúc HTML của riêng tin nhắn mới sinh ra (tin nhắn của người dùng hoặc phản hồi từ bot).
- Sử dụng các lớp CSS của Tailwind để tạo hiệu ứng bubble chat (màu sắc, bo góc, căn lề trái/phải tương ứng).
- Có thể đính kèm thông tin `trace_id` hoặc nút phản hồi (thumbs up/down) liên kết với `/api/feedback`.
