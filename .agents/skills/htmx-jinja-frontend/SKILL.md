---
name: htmx-jinja-frontend
description: Hướng dẫn cấu hình Jinja2 Templates, giao tiếp không đồng bộ qua HTMX và tối ưu hóa CSS bằng TailwindCSS cho giao diện ứng dụng Vietlex Legal RAG. Sử dụng skill này khi người dùng yêu cầu chỉnh sửa UI/UX, tạo trang chat, thiết kế layouts, tích hợp HTMX attributes (hx-post, hx-target, hx-swap, hx-indicator) hoặc tạo các components Jinja2 partial.
---

# HTMX & Jinja2 Frontend Skill

Kỹ năng này hướng dẫn thiết kế và xây dựng giao diện tương tác mượt mà, phản hồi nhanh (reactive UI) cho ứng dụng Vietlex Legal RAG mà không cần sử dụng các Single Page Application (SPA) framework phức tạp (như React, Vue). Thay vào đó, chúng ta kết hợp **Jinja2 Templates** ở phía backend, **HTMX** để giao tiếp không đồng bộ và **TailwindCSS** để tùy biến kiểu dáng (styling).

---

## 1. Cơ chế hoạt động của HTMX (Server-Driven UI)

### Tại sao lại chọn HTMX + Jinja2?
Thay vì gửi JSON qua API rồi viết Javascript ở client để parse và render HTML, HTMX thay đổi quy trình:
1. Client gửi yêu cầu AJAX (POST/GET) thông qua các thuộc tính HTML trực tiếp.
2. Server nhận yêu cầu, xử lý và dùng Jinja2 để render một **Khối HTML Partial** (ví dụ: chỉ render thẻ tin nhắn mới, không render lại toàn bộ trang).
3. Server trả về chuỗi HTML đó, HTMX tự động hoán đổi (swap) nội dung vào đúng phần tử chỉ định trong DOM.

**Lợi ích**: Code logic tập trung hoàn toàn ở Backend, không có trạng thái phức tạp ở Frontend, giảm thiểu tối đa dung lượng Javascript cần tải.

---

## 2. Giao diện trang chủ (`index.html`)

Trang chủ chứa cấu trúc bao quát, thanh điều hướng, khung hiển thị lịch sử chat và form gửi câu hỏi. Form này gửi request đến `/chat` thông qua HTMX.

```html
<!-- app/templates/index.html -->
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vietlex Legal RAG - Trợ lý Pháp luật Việt Nam</title>
    <!-- Nhúng Tailwind CSS qua CDN (hoặc file tĩnh tùy cấu hình) -->
    <script src="https://cdn.tailwindcss.com"></script>
    <!-- Nhúng HTMX -->
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
</head>
<body class="bg-slate-900 text-slate-100 min-h-screen flex flex-col">

    <!-- Header -->
    <header class="border-b border-slate-800 p-4 bg-slate-950/50 backdrop-blur-md sticky top-0 z-10">
        <h1 class="text-xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 to-teal-200">
            Vietlex Legal RAG
        </h1>
    </header>

    <!-- Chat Container -->
    <main class="flex-1 max-w-4xl w-full mx-auto p-4 flex flex-col justify-between overflow-hidden">
        
        <!-- Khung lịch sử chat -->
        <div id="chat-history" class="flex-1 overflow-y-auto space-y-4 pr-2">
            <!-- Tin nhắn chào mừng mặc định -->
            <div class="flex justify-start">
                <div class="bg-slate-800 text-slate-200 rounded-lg p-3 max-w-[80%] border border-slate-700">
                    Xin chào! Tôi là trợ lý pháp luật Vietlex. Hãy nhập câu hỏi pháp lý của bạn ở dưới.
                </div>
            </div>
        </div>

        <!-- Chỉ báo loading (HTMX Indicator) -->
        <div id="chat-loading" class="htmx-indicator flex items-center justify-start space-x-2 py-2 text-slate-400 text-sm">
            <div class="animate-bounce h-2 w-2 bg-emerald-400 rounded-full"></div>
            <div class="animate-bounce h-2 w-2 bg-emerald-400 rounded-full [animation-delay:0.2s]"></div>
            <div class="animate-bounce h-2 w-2 bg-emerald-400 rounded-full [animation-delay:0.4s]"></div>
            <span>Vietlex đang tra cứu luật và phân tích...</span>
        </div>

        <!-- Form nhập tin nhắn -->
        <form hx-post="/chat" 
              hx-target="#chat-history" 
              hx-swap="beforeend" 
              hx-indicator="#chat-loading"
              hx-on::after-request="this.reset(); document.getElementById('chat-history').scrollTop = document.getElementById('chat-history').scrollHeight"
              class="mt-4 flex gap-2">
            <!-- Đóng gói CSRF Token bảo mật -->
            <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
            <input type="text" 
                   name="message" 
                   required 
                   placeholder="Hỏi về luật doanh nghiệp, dân sự, lao động..." 
                   class="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-4 py-3 text-slate-100 focus:outline-none focus:border-emerald-500 transition">
            <button type="submit" 
                    class="bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-600 hover:to-teal-600 px-6 py-3 rounded-lg font-semibold text-slate-900 transition">
                Gửi
            </button>
        </form>
    </main>

</body>
</html>
```

---

## 3. Khối HTML Partial (`chat_message.html`)

Đây là template Jinja2 mini dùng để render một tin nhắn mới. Khi gọi `POST /chat`, backend chỉ render file này và trả về. HTMX sẽ chèn nó vào cuối vùng `#chat-history`.

```html
<!-- app/templates/chat_message.html -->

<!-- Tin nhắn của User -->
{% if role == 'user' %}
<div class="flex justify-end">
    <div class="bg-emerald-600/25 border border-emerald-500/30 text-emerald-100 rounded-lg p-3 max-w-[80%] shadow-md">
        {{ content }}
    </div>
</div>
{% endif %}

<!-- Phản hồi từ Trợ lý (Bot) -->
{% if role == 'bot' %}
<div class="flex justify-start flex-col space-y-1">
    <div class="bg-slate-800 text-slate-200 rounded-lg p-4 max-w-[80%] border border-slate-700 shadow-md">
        <!-- Nội dung luật trả về -->
        <div class="prose prose-invert text-sm leading-relaxed">
            {{ content | safe }}
        </div>
        
        <!-- Section metadata & feedback -->
        <div class="mt-3 pt-2 border-t border-slate-700/50 flex items-center justify-between text-xs text-slate-400">
            <span>Trace ID: <code class="text-emerald-400">{{ trace_id }}</code></span>
            
            <!-- Nút gửi phản hồi Thumbs up/down qua HTMX -->
            <div class="flex items-center space-x-2">
                <button hx-post="/api/feedback" 
                        hx-vals='{"trace_id": "{{ trace_id }}", "rating": "up"}'
                        hx-swap="outerHTML"
                        class="hover:text-emerald-400 p-1 transition"
                        title="Hữu ích">
                    👍
                </button>
                <button hx-post="/api/feedback" 
                        hx-vals='{"trace_id": "{{ trace_id }}", "rating": "down"}'
                        hx-swap="outerHTML"
                        class="hover:text-red-400 p-1 transition"
                        title="Không hữu ích">
                    👎
                </button>
            </div>
        </div>
    </div>
</div>
{% endif %}
```
