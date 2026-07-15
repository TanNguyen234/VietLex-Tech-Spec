from fastapi import Request, HTTPException, Form, status

# Dependency for CSRF token validation in form POST
async def verify_csrf(request: Request, csrf_token: str = Form(...)):
    cookie_token = request.cookies.get("csrf_token")
    if not cookie_token or cookie_token != csrf_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token validation failed. Request blocked."
        )
    return csrf_token
