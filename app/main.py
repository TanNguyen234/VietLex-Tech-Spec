import logfire
from dotenv import load_dotenv
# Load environment variables from .env before logfire configuration
load_dotenv()

from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import secrets

from app.config import get_settings

# Configure Logfire
logfire.configure()

settings = get_settings()

app = FastAPI(title="VietLex Advanced Legal RAG")

from app.database import init_db

@app.on_event("startup")
async def startup_event():
    await init_db()

# Instrument FastAPI with Logfire
logfire.instrument_fastapi(app)

# Rate Limiting (Slowapi)
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS Middleware
origins = [str(settings.FRONTEND_URL)] if settings.FRONTEND_URL else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="app/templates")

# CSRF helper function
def get_csrf_token(request: Request) -> str:
    session_csrf = request.session.get("csrf_token") if hasattr(request, "session") else None
    # For this boilerplate, using cookies if session middleware isn't active
    cookie_csrf = request.cookies.get("csrf_token")
    return session_csrf or cookie_csrf or ""

# Include router
from app.api.routes import router as api_router
app.include_router(api_router)

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    # CSRF generation
    token = secrets.token_hex(32)
    response = templates.TemplateResponse(request, "index.html", {"csrf_token": token})
    # Save token in cookie for validation
    response.set_cookie(key="csrf_token", value=token, httponly=True, samesite="strict")
    return response
