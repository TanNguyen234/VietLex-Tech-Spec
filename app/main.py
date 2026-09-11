import secrets
import asyncio
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.paths import APP_ROOT
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import get_settings, validate_production_settings
from app.database import init_db
from app.api.routes import router as api_router
from app.api.account_routes import router as account_router
from app.api.legal_routes import router as legal_router
from app.api.finding_routes import router as finding_router
from app.api.product_quality_routes import router as product_quality_router
from app.api.workspace_routes import router as workspace_router
from app.api.legal_timeline_routes import router as timeline_router
from app.api.claim_verification_routes import router as claim_router
from app.api.document_redline_routes import router as redline_router
from app.api.research_report_routes import router as research_report_router
from app.api.trusted_source_routes import router as source_router
from app.api.model_comparison_routes import router as model_comparison_router
from app.api.full_document_review_routes import router as full_review_router
from app.api.legal_effect_routes import router as legal_effect_router
from app.api.evaluation_lab_routes import router as evaluation_lab_router
from app.api.dependencies import optional_user
from app.services.web_security import (
    AnonymousClientMiddleware,
    resolve_web_session_secret,
)
from app.services.http_security import (
    SecurityHeadersMiddleware,
    WorkspaceUploadBodyLimitMiddleware,
)
from app.services.workspace_documents import MAX_UPLOAD_BYTES
from app.rate_limit import limiter
from app.services.observability import configure_observability
from app.services.reviewer_demo import ReviewerDemoMiddleware

# Load environment variables from .env before settings/observability initialization.
load_dotenv()

settings = get_settings()
validate_production_settings(settings)
configure_observability(settings)

app = FastAPI(title="VietLex Advanced Legal RAG")

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    WorkspaceUploadBodyLimitMiddleware,
    max_bytes=MAX_UPLOAD_BYTES + 256_000,
)

app.add_middleware(
    AnonymousClientMiddleware,
    secret=resolve_web_session_secret(settings),
    cookie_name=settings.ANONYMOUS_COOKIE_NAME,
    max_age=settings.ANONYMOUS_COOKIE_MAX_AGE_SECONDS,
)

@app.on_event("startup")
async def startup_event():
    from app.services.semantic_cache import ensure_semantic_cache_collection

    await init_db()
    await ensure_semantic_cache_collection()
    if settings.PUBLIC_NEMO_DEFAULT_ENABLED and not settings.SERVERLESS_ONLINE_ONLY:
        from app.services.guardrails import warm_guardrails

        await warm_guardrails()

@app.on_event("shutdown")
async def shutdown_event():
    from app.services.clients import close_clients
    from app.services.retrieval import reset_retriever

    await close_clients()
    reset_retriever()

# Tests skip Logfire entirely so inherited credentials can never emit telemetry or
# start its credential-validation thread. Other environments are configured above.
if settings.APP_ENV != "test":
    import logfire

    logfire.instrument_fastapi(app, capture_headers=False)

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

app.add_middleware(ReviewerDemoMiddleware, settings=settings)
app.state.reviewer_demo_mode = settings.REVIEWER_DEMO_MODE
app.state.demo_ai_daily_limit = settings.DEMO_AI_DAILY_LIMIT

templates = Jinja2Templates(directory=APP_ROOT / "templates")
app.mount("/static", StaticFiles(directory=APP_ROOT / "static"), name="static")

# CSRF helper function
def get_csrf_token(request: Request) -> str:
    session_csrf = request.session.get("csrf_token") if hasattr(request, "session") else None
    cookie_csrf = request.cookies.get("csrf_token")
    return session_csrf or cookie_csrf or ""

# Include router
app.include_router(api_router)
app.include_router(account_router)
app.include_router(legal_router)
app.include_router(finding_router)
app.include_router(product_quality_router)
app.include_router(workspace_router)
app.include_router(timeline_router)
app.include_router(claim_router)
app.include_router(redline_router)
app.include_router(research_report_router)
app.include_router(source_router)
app.include_router(model_comparison_router)
app.include_router(full_review_router)
app.include_router(legal_effect_router)
app.include_router(evaluation_lab_router)

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request, current_user=Depends(optional_user), document_id: int | None = Query(None, ge=0)):
    scoped_document = None
    if document_id is not None:
        from app.api.legal_routes import _get_browser
        from app.services.legal_browser import LegalBrowserBackendError
        try:
            scoped_document = await asyncio.to_thread(_get_browser().get_document, document_id)
        except LegalBrowserBackendError:
            raise HTTPException(503, "Không đọc được văn bản đã chọn.") from None
        if scoped_document is None:
            raise HTTPException(404, "Không tìm thấy văn bản đã chọn.")
    # CSRF generation
    token = secrets.token_hex(32)
    progress_transport = (
        "polling"
        if request.query_params.get("gateway") == "vercel"
        else "sse"
    )
    response = templates.TemplateResponse(
        request,
        "index.html",
        {
            "csrf_token": token,
            "progress_transport": progress_transport,
            "current_user": current_user,
            "prefill_question": request.query_params.get("question", "")[:2_000],
            "scoped_document": scoped_document,
        },
    )
    # Save token in cookie for validation
    response.set_cookie(
        key="csrf_token",
        value=token,
        httponly=True,
        secure=settings.APP_ENV == "production" or request.url.scheme == "https",
        samesite="strict",
    )
    return response
