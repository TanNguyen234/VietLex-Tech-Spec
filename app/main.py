import secrets
from dotenv import load_dotenv
import logfire
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.database import init_db
from app.api.routes import router as api_router
from app.services.clients import close_clients
from app.services.retrieval import reset_retriever
from app.services.semantic_cache import ensure_semantic_cache_collection
from app.services.guardrails import warm_guardrails
from app.services.web_security import AnonymousClientMiddleware
from app.rate_limit import limiter

# Load environment variables from .env before logfire/settings initialization
load_dotenv()

settings = get_settings()

app = FastAPI(title="VietLex Advanced Legal RAG")

app.add_middleware(
    AnonymousClientMiddleware,
    secret=settings.WEB_SESSION_SECRET or secrets.token_urlsafe(32),
    cookie_name=settings.ANONYMOUS_COOKIE_NAME,
    max_age=settings.ANONYMOUS_COOKIE_MAX_AGE_SECONDS,
)

@app.on_event("startup")
async def startup_event():
    logfire.configure()
    await init_db()
    await ensure_semantic_cache_collection()
    await warm_guardrails()

@app.on_event("shutdown")
async def shutdown_event():
    await close_clients()
    reset_retriever()

# Instrument FastAPI with Logfire
logfire.instrument_fastapi(app)

# Rate Limiting (Slowapi)
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
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# CSRF helper function
def get_csrf_token(request: Request) -> str:
    session_csrf = request.session.get("csrf_token") if hasattr(request, "session") else None
    cookie_csrf = request.cookies.get("csrf_token")
    return session_csrf or cookie_csrf or ""

# Include router
app.include_router(api_router)

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    # CSRF generation
    token = secrets.token_hex(32)
    response = templates.TemplateResponse(request, "index.html", {"csrf_token": token})
    # Save token in cookie for validation
    response.set_cookie(key="csrf_token", value=token, httponly=True, samesite="strict")
    return response
