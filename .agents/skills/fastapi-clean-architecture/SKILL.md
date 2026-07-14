---
name: fastapi-clean-architecture
description: Hướng dẫn chi tiết thiết lập API FastAPI tuân thủ Clean Architecture, Slowapi Rate Limiting và CSRF Protection cho dự án Vietlex Legal RAG. Kích hoạt bất kỳ khi nào người dùng yêu cầu cấu hình API, viết routes/endpoints mới, thiết lập dependencies, xử lý CORS/CSRF middleware, cài đặt giới hạn rate limit (Slowapi), hoặc tổ chức mã nguồn theo mô hình Kiến trúc Sạch.
---

# FastAPI Clean Architecture Skill

Kỹ năng này hướng dẫn cách thiết lập, phát triển và cấu trúc ứng dụng FastAPI tuân thủ mô hình **Clean Architecture**, tích hợp bảo mật chống tấn công CSRF và giới hạn tần suất yêu cầu (Rate Limiting) bằng Slowapi để bảo vệ hệ thống Vietlex Legal RAG.

---

## 1. Cấu trúc Dự án (Clean Architecture Compliance)

Việc phân lớp mã nguồn giúp tách biệt rõ ràng giữa logic nghiệp vụ (business logic), cách trình diễn (presentation layer/API endpoints) và dữ liệu/hạ tầng (ingestion/database). Khi thêm mới endpoint hoặc logic, hãy luôn tuân thủ cấu trúc sau:

```
app/
├── main.py                # Điểm khởi chạy FastAPI, cấu hình Middlewares, Rate Limiter toàn cục và Logfire
├── config.py              # Định nghĩa cấu hình hệ thống bằng Pydantic BaseSettings (load từ file .env)
├── api/                   # Presentation Layer (API endpoints & Routing)
│   ├── dependencies.py    # Các dependency dùng chung (Auth, CSRF, Database connections) được inject vào router
│   └── routes.py          # Định nghĩa endpoints, nhận request payload, kiểm thử CSRF, chuyển tiếp cho service
├── services/              # Core Business Logic Layer
│   # RAG pipeline, Semantic Cache, Guardrails, Evaluator độc lập với API framework
├── ingestion/             # Data Ingestion Layer
│   # Parser văn bản luật và indexer tải dữ liệu lên Qdrant Vector DB
└── templates/             # UI Templates (Jinja2 & HTMX)
    # Các partial/HTML components dùng cho giao diện tương tác
```

---

## 2. Giới hạn Tần suất (Slowapi Rate Limiting)

### Tại sao cần thiết?
Hệ thống RAG thực hiện các tác vụ tốn tài nguyên (Dense/Sparse retrieval, Rerank, sinh văn bản bằng LLM). Việc không giới hạn tần suất yêu cầu có thể dẫn tới cạn kiệt tài nguyên (VRAM/API quota) hoặc bị tấn công từ chối dịch vụ (DoS).

### Cấu hình và Quy tắc:
1. **Mức giới hạn**: Giới hạn endpoint `POST /chat` tối đa là **5 requests/phút trên mỗi địa chỉ IP**.
2. **HTMX Integration**: Do giao diện sử dụng HTMX để tải HTML không đồng bộ, khi vượt hạn ngạch, API cần trả về một khối HTML partial thân thiện chứa thông tin lỗi thay vì trả về JSON lỗi tiêu chuẩn, giúp giao diện không bị vỡ.

```python
# app/main.py
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Khởi tạo limiter
limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter

# Custom handler trả về HTML partial cho HTMX khi bị Rate Limit
def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded):
    # Kiểm tra xem request có phải từ HTMX hay không thông qua header
    if request.headers.get("HX-Request"):
        return HTMLResponse(
            content="<div class='error-message text-red-500 font-semibold p-4 bg-red-50 border border-red-200 rounded-lg'>"
                    "Bạn đã gửi quá nhiều câu hỏi. Vui lòng chờ 1 phút trước khi thử lại."
                    "</div>",
            status_code=429
        )
    return _rate_limit_exceeded_handler(request, exc)

app.add_exception_handler(RateLimitExceeded, custom_rate_limit_handler)
```

---

## 3. Bảo vệ chống CSRF (CSRF Protection)

### Tại sao cần thiết?
Để bảo vệ phiên làm việc của người dùng khi cookie được gửi tự động cùng request. Mọi request làm thay đổi trạng thái (như `POST /chat`) phải được xác thực token CSRF hợp lệ được sinh ra khi truy cập giao diện chính.

### Cấu hình sinh và kiểm tra Token:
1. Khi người dùng truy cập `GET /`, sinh một token CSRF bảo mật ngẫu nhiên, lưu vào cookie phiên và truyền vào template Jinja2.
2. Với `POST /chat`, validate token gửi lên từ form hoặc header trùng khớp với token trong cookie.

```python
# app/api/dependencies.py
import secrets
from fastapi import Request, HTTPException, Cookie, Form
from typing import Annotated

def generate_csrf_token() -> str:
    return secrets.token_hex(32)

def verify_csrf_token(
    request: Request,
    csrf_token_cookie: Annotated[str | None, Cookie(alias="csrf_token")] = None,
    csrf_token_form: Annotated[str | None, Form(alias="csrf_token")] = None
):
    # Lấy token từ header nếu form không có (hỗ trợ các request AJAX/HTMX nâng cao)
    token_from_header = request.headers.get("X-CSRF-Token")
    submitted_token = csrf_token_form or token_from_header

    if not csrf_token_cookie or not submitted_token or csrf_token_cookie != submitted_token:
        raise HTTPException(
            status_code=403,
            detail="CSRF token validation failed. Yêu cầu của bạn bị từ chối bảo mật."
        )
    return submitted_token
```

```python
# app/api/routes.py
from fastapi import APIRouter, Depends, Form
from typing import Annotated
from app.api.dependencies import verify_csrf_token

router = APIRouter()

@router.post("/chat")
async def chat(
    message: Annotated[str, Form()],
    csrf_token: Annotated[str, Depends(verify_csrf_token)] # Validate CSRF trước khi xử lý
):
    # Tiếp tục xử lý logic chat
    return {"status": "success"}
```

---

## 4. Tiêu chuẩn Mã nguồn & Dependencies Injection

- **Annotated Syntax**: Luôn sử dụng kiểu dữ liệu `Annotated` của Python 3.9+ kết hợp với `Depends` để khai báo dependency. Việc này cải thiện khả năng đọc mã nguồn và hỗ trợ đắc lực cho việc kiểm thử tự động (Unit Test).
  ```python
  # Khuyến khích:
  async def get_chat_history(db: Annotated[DatabaseSession, Depends(get_db_session)]):
      ...
  ```
- **Pydantic v2**: Định nghĩa tất cả cấu hình và schemas dữ liệu bằng Pydantic v2 (import trực tiếp từ `pydantic` hoặc `pydantic_settings`). Tránh sử dụng các cú pháp Pydantic v1 cũ (`Config` class lồng thay vì `model_config`, `dict()` thay vì `model_dump()`).
