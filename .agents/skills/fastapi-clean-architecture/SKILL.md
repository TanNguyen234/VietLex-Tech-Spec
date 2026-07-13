---
name: fastapi-clean-architecture
description: Hướng dẫn thiết lập API FastAPI tuân thủ cấu trúc Clean Architecture, Slowapi Rate Limiting và CSRF Protection cho dự án Vietlex Legal RAG.
---

# FastAPI Clean Architecture Skill

Kỹ năng này giúp AI Agent thiết lập và phát triển các thành phần trong ứng dụng FastAPI tuân thủ cấu trúc Clean Architecture, cấu hình các lớp bảo mật bảo vệ ứng dụng khỏi các lỗi rate limiting và CSRF.

## 1. Cấu trúc Dự án (Clean Architecture)
Khi thêm mới endpoint hoặc service, bắt buộc tuân theo sơ đồ phân lớp:
- `app/config.py`: Load cấu hình từ `.env` bằng `pydantic-settings`.
- `app/api/dependencies.py`: Chứa các dependency được inject vào router (ví dụ: Auth, RateLimiter).
- `app/api/routes.py`: Định nghĩa các endpoints, đón nhận đầu vào, thực hiện kiểm tra CSRF và chuyển tiếp cho service.
- `app/services/`: Nơi xử lý logic nghiệp vụ chính.

## 2. Slowapi Rate Limiting
- Cấu hình Slowapi Limiter toàn cục trong `app/main.py`.
- Giới hạn endpoint `POST /chat` là **5 requests/phút trên mỗi IP**.
- Sử dụng callback xử lý lỗi để trả về thông điệp HTML thân thiện với HTMX (thay vì JSON thông thường) khi vượt hạn ngạch.

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

## 3. CSRF Protection Middleware
- Sử dụng thư viện bảo mật hoặc tự định nghĩa middleware để sinh token CSRF an toàn (secure token) khi người dùng truy cập `GET /`.
- Token này được chèn vào cookie hoặc HTML meta/form.
- Đối với `POST /chat`, middleware hoặc dependency injection bắt buộc phải thực hiện xác thực token gửi lên từ form (`csrf_token`).

```python
import secrets
from fastapi import Request, HTTPException

def generate_csrf_token() -> str:
    return secrets.token_hex(32)

def validate_csrf_token(request: Request, csrf_token: str):
    session_token = request.cookies.get("csrf_token")
    if not session_token or session_token != csrf_token:
        raise HTTPException(status_code=403, detail="CSRF token validation failed")
```

## 4. Quy định Triển khai Code
- Sử dụng `Annotated` của Python 3.9+ cho tất cả các Dependency Injections trong FastAPI.
- Tất cả các Pydantic Model phải tuân thủ chuẩn Pydantic v2.
