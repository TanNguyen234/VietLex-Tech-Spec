from app.services.reviewer_demo import demo_admission_snapshot
import asyncio
import json
import time
import uuid
import secrets
import csv
import io
from datetime import date
from functools import partial
from typing import Dict
import logfire

from fastapi import APIRouter, Request, Depends, Form, BackgroundTasks, HTTPException, Query

from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.templating import Jinja2Templates
from app.paths import APP_ROOT

from app.evaluation.online_metrics import build_online_metrics, sanitize_error_message
from app.api.dependencies import (
    optional_user,
    require_admin,
    verify_csrf,
    verify_csrf_header,
)
from app.config import get_settings
from app.services.public_evaluation import (
    DailyRagasQuota,
    build_code_evaluation,
    ragas_metric_catalog,
)
from app.services.conversation_export import render_conversation_markdown
from app.services.readiness import build_readiness
from app.rate_limit import limiter
from app.services.evidence_presenter import present_context
from app.services.provider_runtime import provider_status_snapshot, capture_provider_usage
from app.services.admin_observability import present_interaction, AdminDataUnavailable
from app.services.direct_llm import provider_cooldown_snapshot
from app.services.chat_progress import chat_progress
from app.services.research_presenter import (
    build_claim_support,
    build_public_retrieval_trace,
    sanitize_retrieval_trace,
)

from app.services.pii import redact_pii
from app.services.runtime_errors import (
    GUARDRAIL_UNAVAILABLE_MESSAGE,
    GuardrailUnavailableError,
    RetrievalPipelineError,
)
from app.database import (
    log_interaction, update_feedback, get_admin_logs, get_admin_stats, get_interaction,
    create_session, get_sessions, get_session_messages, delete_session, rename_session,
    get_owned_interaction, get_admin_audit_logs,
    get_admin_inventory,
)
from app.account_database import (
    get_user_by_id,
    list_users,
    revoke_all_auth_sessions,
    set_user_status,
    write_admin_audit,
)

router = APIRouter()
templates = Jinja2Templates(directory=APP_ROOT / "templates")
settings = get_settings()
_public_ragas_quota = DailyRagasQuota(
    client_limit=settings.PUBLIC_RAGAS_CLIENT_DAILY_LIMIT,
    global_limit=settings.PUBLIC_RAGAS_GLOBAL_DAILY_LIMIT,
)
_public_ragas_semaphore = asyncio.Semaphore(1)


def _sanitize_admin_interaction(log: dict) -> dict:
    return present_interaction(log)


def admin_filters(
    search: str = Query('', max_length=100), request_status: str = Query('', max_length=50),
    provider: str = Query('', max_length=100), model: str = Query('', max_length=200),
    cache_hit: str = Query('', pattern='^(|true|false)$'), ragas_status: str = Query('', max_length=50),
    feedback: str = Query('', pattern='^(|up|down)$'), start_date: str = Query('', max_length=10),
    end_date: str = Query('', max_length=10),
    user_id: str = Query('', max_length=100), session_id: str = Query('', max_length=100),
):
    try:
        start_date = date.fromisoformat(start_date) if start_date else None
        end_date = date.fromisoformat(end_date) if end_date else None
    except ValueError:
        raise HTTPException(422, 'Ngày phải có định dạng YYYY-MM-DD.') from None
    if start_date and end_date and start_date > end_date:
        raise HTTPException(422, 'Ngày bắt đầu phải trước hoặc bằng ngày kết thúc.')
    if end_date == date.max:
        raise HTTPException(422, 'Ngày kết thúc vượt phạm vi hỗ trợ.')
    return dict(search_query=search, request_status=request_status, provider=provider, model=model,
                cache_hit=None if not cache_hit else cache_hit == 'true', ragas_status=ragas_status, feedback=feedback,
                start_date=start_date, end_date=end_date, user_id=user_id, session_id=session_id)


def admin_page_links(request: Request, skip: int, limit: int, size: int) -> dict:
    return {
        'previous_url': str(request.url.include_query_params(skip=max(0, skip-limit), limit=limit)) if skip else None,
        'next_url': str(request.url.include_query_params(skip=skip+limit, limit=limit)) if size == limit else None,
        'export_url': '/admin/export.csv?' + str(request.url.query),
    }


async def _load_admin_logs(**kwargs):
    try:
        return await get_admin_logs(**kwargs)
    except AdminDataUnavailable:
        raise HTTPException(503, 'Không đọc được nhật ký. Vui lòng thử lại.', headers={'Cache-Control': 'no-store'}) from None


async def check_input_guardrails(message: str):
    try:
        if settings.SERVERLESS_ONLINE_ONLY:
            from app.services.serverless_guardrails import check_input_guardrails as implementation
        else:
            from app.services.guardrails import check_input_guardrails as implementation
    except ImportError:
        raise GuardrailUnavailableError("input", "dependency_unavailable") from None

    return await implementation(message)


async def check_output_guardrails(response: str, contexts: list[str], query: str):
    try:
        if settings.SERVERLESS_ONLINE_ONLY:
            from app.services.serverless_guardrails import check_output_guardrails as implementation
        else:
            from app.services.guardrails import check_output_guardrails as implementation
    except ImportError:
        raise GuardrailUnavailableError("output", "dependency_unavailable") from None

    return await implementation(response, contexts, query)


async def check_semantic_cache(message: str):
    from app.services.semantic_cache import check_semantic_cache as implementation

    return await implementation(message)


async def save_to_semantic_cache(*args, **kwargs):
    from app.services.semantic_cache import save_to_semantic_cache as implementation

    return await implementation(*args, **kwargs)


async def run_advanced_rag(message: str, **kwargs):
    from app.services.rag_pipeline import run_advanced_rag as implementation

    return await implementation(message, **kwargs)


async def run_llm_as_judge(*args, **kwargs):
    from app.services.evaluator import run_llm_as_judge as implementation

    return await implementation(*args, **kwargs)


async def _owned_interaction(trace_id: str, client_id: str, user_id: str | None):
    if user_id:
        return await get_owned_interaction(trace_id, client_id, user_id=user_id)
    return await get_owned_interaction(trace_id, client_id)


async def _optional_input_guardrail(
    message: str, enabled: bool
) -> tuple[bool, str, float]:
    if not enabled:
        return True, "", 0.0
    started = time.perf_counter()
    safe, rejection = await check_input_guardrails(message)
    return safe, rejection, round(time.perf_counter() - started, 4)


async def _optional_output_guardrail(
    response: str, contexts: list[str], query: str, enabled: bool
) -> tuple[bool, str, float]:
    if not enabled:
        return True, "", 0.0
    started = time.perf_counter()
    safe, fallback = await check_output_guardrails(response, contexts, query)
    return safe, fallback, round(time.perf_counter() - started, 4)


@router.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "vietlex"}


@router.get("/readyz")
async def readyz():
    async def mongo_ping() -> bool:
        from app.database import get_db

        result = await get_db().command("ping")
        return result.get("ok") == 1.0

    snapshot = await build_readiness(settings, mongo_ping)
    status_code = 200 if snapshot["status"] == "ready" else 503
    return JSONResponse(snapshot, status_code=status_code)


@router.get("/api/progress/{request_id}")
@limiter.limit(settings.PUBLIC_PROGRESS_RATE_LIMIT)
async def chat_progress_status(request: Request, request_id: str):
    snapshot = chat_progress.get(
        request_id, getattr(request.state, "client_id", "legacy")
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Progress not found")
    return snapshot


@router.get("/api/interactions/{trace_id}/retrieval")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def retrieval_inspector(
    request: Request, trace_id: str, current_user=Depends(optional_user)
):
    if len(trace_id) > 100:
        raise HTTPException(status_code=422, detail="Invalid trace ID")
    client_id = getattr(request.state, "client_id", "legacy")
    user_id = str(current_user["_id"]) if current_user else None
    interaction = await _owned_interaction(trace_id, client_id, user_id)
    if interaction is None or (user_id is None and interaction.get("user_id")):
        raise HTTPException(status_code=404, detail="Interaction not found")
    return build_public_retrieval_trace(interaction)


@router.get("/api/progress/{request_id}/stream")
async def chat_progress_stream(request: Request, request_id: str):
    client_id = getattr(request.state, "client_id", "legacy")

    async def events():
        last_payload = None
        for _ in range(300):
            if await request.is_disconnected():
                return
            snapshot = chat_progress.get(request_id, client_id)
            if snapshot is not None:
                payload = json.dumps(snapshot, ensure_ascii=False)
                if payload != last_payload:
                    yield f"data: {payload}\n\n"
                    last_payload = payload
                if snapshot.get("complete"):
                    return
            await asyncio.sleep(0.4)
        yield 'event: timeout\ndata: {"complete":true,"status":"timeout"}\n\n'

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@router.post("/chat", response_class=HTMLResponse)
@limiter.limit(settings.CHAT_RATE_LIMIT)
@capture_provider_usage
async def chat(
    request: Request,
    background_tasks: BackgroundTasks,
    message: str = Form(...),
    csrf_token: str = Form(...),
    session_id: str = Form(None),
    nemo_enabled: bool = Form(False),
    document_id: int | None = Form(None, ge=0),
    request_id: str = Form(""),
    csrf_valid: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    request_started = time.perf_counter()
    # A legacy client may request stricter checks, never disable server policy.
    nemo_enabled = settings.PUBLIC_NEMO_DEFAULT_ENABLED or nemo_enabled
    message = redact_pii(message)
    trace_id = str(uuid.uuid4())
    client_id = getattr(request.state, "client_id", "legacy")
    user_id = str(current_user["_id"]) if current_user else None
    scoped_outcome = None
    if document_id is not None:
        from app.api.legal_routes import _get_browser
        from app.services.document_scope import document_evidence
        from app.services.legal_browser import LegalBrowserBackendError

        try:
            document = await asyncio.to_thread(_get_browser().get_document, document_id)
        except LegalBrowserBackendError:
            raise HTTPException(503, "Không đọc được văn bản đã chọn.") from None
        if document is None:
            raise HTTPException(404, "Không tìm thấy văn bản đã chọn.")
        scoped_outcome = await asyncio.to_thread(document_evidence, message, document)
    persist_interaction = partial(
        log_interaction, client_id=client_id, user_id=user_id,
        request_metadata={'method': 'POST', 'path': '/chat', 'nemo_requested': nemo_enabled,
                          'guardrail_engine': 'direct_self_check' if settings.SERVERLESS_ONLINE_ONLY else 'nemo',
                          'scope': 'document' if document_id is not None else 'corpus', 'document_id': document_id},
    )
    if request_id:
        chat_progress.start(request_id, client_id, nemo_enabled=nemo_enabled)
    is_new_session = False
    
    if not session_id or session_id == "default":
        session_id = str(uuid.uuid4())
        words = message.split()
        title = " ".join(words[:5]) + ("..." if len(words) > 5 else "")
        await create_session(
            session_id, title, client_id=client_id, user_id=user_id
        )
        is_new_session = True
        
    with logfire.span("Xử lý Chat Request", trace_id=trace_id, query_length=len(message)) as span:
        t_cache = 0.0

        # Step 2: Apply NeMo Guardrails (Input Check)
        if request_id:
            chat_progress.advance(
                request_id,
                client_id,
                "input_guardrail",
                "Đang kiểm tra NeMo input" if nemo_enabled else "NeMo input đang tắt",
            )
        try:
            input_safe, rejection_message, t_guardrails_input = (
                await _optional_input_guardrail(message, nemo_enabled)
            )
        except GuardrailUnavailableError as error:
            t_guardrails_input = round(time.perf_counter() - request_started, 4)
            t_total = round(time.perf_counter() - request_started, 4)
            tech_error = {
                "stage": "guardrails_input",
                "error_type": error.__class__.__name__,
                "message": sanitize_error_message(error),
            }
            logfire.error(
                "Input guardrail unavailable",
                error=str(error),
                trace_id=trace_id,
            )
            latency_record = {
                "t_total": t_total,
                "t_cache": t_cache,
                "t_guardrails_input": t_guardrails_input,
            }
            metrics = build_online_metrics(
                trace_id=trace_id,
                request_status="technical_error",
                latency=latency_record,
                context_used=[],
                bot_response=GUARDRAIL_UNAVAILABLE_MESSAGE,
                cached=False,
                technical_error=tech_error,
                ragas_mode="off",
                ragas_sample_rate=0.0,
            )
            await persist_interaction(
                trace_id=trace_id,
                user_query=message,
                bot_response=GUARDRAIL_UNAVAILABLE_MESSAGE,
                contexts=[],
                cached=False,
                session_id=session_id,
                request_status="technical_error",
                technical_error=tech_error,
                latency=metrics.latency,
                observed_provider=metrics.observed_provider,
                observed_model=metrics.observed_model,
                provider_usage=metrics.provider_usage,
                ragas_mode=metrics.ragas_mode,
                ragas_status=metrics.ragas_status,
                ragas_selected=False,
                ragas_executed=False,
                citation_count=0,
                context_count=0,
                no_evidence=False,
            )
            if request_id:
                chat_progress.complete(request_id, client_id, status="technical_error")
            return templates.TemplateResponse(
                request,
                "chat_message.html",
                {
                    "user_msg": message,
                    "bot_msg": GUARDRAIL_UNAVAILABLE_MESSAGE,
                    "trace_id": trace_id,
                    "session_id": session_id,
                },
                status_code=503,
            )
        if not input_safe:
            span.set_attribute("guardrails_blocked_input", True)
            t_total = round(time.perf_counter() - request_started, 4)
            latency_record = {
                "t_total": t_total,
                "t_cache": t_cache,
                "t_guardrails_input": t_guardrails_input,
            }
            metrics = build_online_metrics(
                trace_id=trace_id,
                request_status="blocked_input",
                latency=latency_record,
                context_used=[],
                bot_response=rejection_message,
                cached=False,
                input_safe=False,
                rejection_reason="Jailbreak or off-topic input blocked by guardrails",
                ragas_mode="off",
                ragas_sample_rate=0.0,
            )
            # Log blocked input interaction
            await persist_interaction(
                trace_id=trace_id,
                user_query=message,
                bot_response=rejection_message,
                contexts=[],
                cached=False,
                input_safe=False,
                rejection_reason="Jailbreak or off-topic input blocked by guardrails",
                session_id=session_id,
                request_status="blocked_input",
                latency=metrics.latency,
                observed_provider=metrics.observed_provider,
                observed_model=metrics.observed_model,
                provider_usage=metrics.provider_usage,
                ragas_mode=metrics.ragas_mode,
                ragas_status=metrics.ragas_status,
                ragas_selected=metrics.ragas_selected,
                ragas_executed=metrics.ragas_executed,
                citation_count=metrics.citation_count,
                context_count=metrics.context_count,
                no_evidence=metrics.no_evidence,
                refusal_category=metrics.refusal_category,
            )
            response = templates.TemplateResponse(
                request,
                "chat_message.html",
                {"user_msg": message, "bot_msg": rejection_message, "trace_id": trace_id, "session_id": session_id}
            )
            if is_new_session:
                response.headers["HX-Trigger"] = "load-sessions"
            if request_id:
                chat_progress.complete(request_id, client_id, status="blocked_input")
            return response

        # Step 3: Check Semantic Cache only after the input is approved.
        if request_id:
            chat_progress.advance(
                request_id, client_id, "semantic_cache", "Đang kiểm tra semantic cache"
            )
        cache_started = time.perf_counter()
        cached_response = None if scoped_outcome is not None or nemo_enabled else await check_semantic_cache(message)
        t_cache = round(time.perf_counter() - cache_started, 4)

        if cached_response:
            cached_contexts = cached_response.contexts
            cached_text = cached_response.response
            span.set_attribute("cache_hit", True)
            t_total = round(time.perf_counter() - request_started, 4)
            latency_record = {
                "t_total": t_total,
                "t_cache": t_cache,
                "t_guardrails_input": t_guardrails_input,
            }
            metrics = build_online_metrics(
                trace_id=trace_id,
                request_status="cache_hit",
                latency=latency_record,
                context_used=cached_contexts,
                bot_response=cached_text,
                cached=True,
                input_safe=True,
                ragas_mode="off",
                ragas_sample_rate=0.0,
            )
            await persist_interaction(
                trace_id=trace_id,
                user_query=message,
                bot_response=cached_text,
                contexts=cached_contexts,
                cached=True,
                input_safe=True,
                session_id=session_id,
                request_status="cache_hit",
                latency=metrics.latency,
                observed_provider=metrics.observed_provider,
                observed_model=metrics.observed_model,
                provider_usage=metrics.provider_usage,
                ragas_mode=metrics.ragas_mode,
                ragas_status=metrics.ragas_status,
                ragas_selected=metrics.ragas_selected,
                ragas_executed=metrics.ragas_executed,
                citation_count=metrics.citation_count,
                context_count=metrics.context_count,
                no_evidence=metrics.no_evidence,
                refusal_category=metrics.refusal_category,
                retrieval_trace=sanitize_retrieval_trace(
                    {"retrieval_status": "cache_hit"},
                    cached_contexts,
                    settings,
                    query=message,
                    cached=True,
                ),
            )
            response = templates.TemplateResponse(
                request,
                "chat_message.html",
                {
                    "user_msg": message,
                    "bot_msg": cached_text,
                    "trace_id": trace_id,
                    "cached": True,
                    "session_id": session_id,
                    "contexts": cached_contexts,
                    "evidence_views": [
                        present_context(item) for item in cached_contexts
                    ],
                    "claim_support": build_claim_support(cached_text, cached_contexts),
                },
            )
            if is_new_session:
                response.headers["HX-Trigger"] = "load-sessions"
            if request_id:
                chat_progress.complete(request_id, client_id, status="cache_hit")
            return response

        span.set_attribute("cache_hit", False)

        # Step 4: Run Advanced Retrieval Pipeline (RAG)
        if request_id:
            chat_progress.advance(
                request_id,
                client_id,
                "retrieval_generation",
                "Đang retrieval, rerank và tạo câu trả lời",
            )
        try:
            bot_response, context_used, latency_info = await run_advanced_rag(
                message, **({"scoped_outcome": scoped_outcome} if scoped_outcome is not None else {})
            )
        except RetrievalPipelineError as error:
            t_total = round(time.perf_counter() - request_started, 4)
            tech_error = {
                "stage": getattr(error, "status", "retrieval_error"),
                "error_type": error.__class__.__name__,
                "message": sanitize_error_message(error),
            }
            error_response = "Hệ thống tra cứu văn bản pháp luật gặp sự cố kỹ thuật. Vui lòng thử lại sau."
            logfire.error("Retrieval pipeline failed", error=str(error), trace_id=trace_id)
            err_latency: Dict[str, float] = {
                "t_total": t_total,
                "t_cache": t_cache,
                "t_guardrails_input": t_guardrails_input,
            }
            if error.latency:
                for k, v in error.latency.items():
                    if isinstance(v, (int, float)):
                        err_latency[k] = float(v)
            err_latency["t_total"] = t_total

            err_provider_usage = error.latency.get("provider_usage") if isinstance(error.latency, dict) else None
            err_observed_prov = error.latency.get("observed_provider") if isinstance(error.latency, dict) else None
            err_observed_mod = error.latency.get("observed_model") if isinstance(error.latency, dict) else None

            metrics = build_online_metrics(
                trace_id=trace_id,
                request_status="technical_error",
                latency=err_latency,
                context_used=[],
                bot_response=error_response,
                cached=False,
                technical_error=tech_error,
                observed_provider=err_observed_prov,
                observed_model=err_observed_mod,
                provider_usage=err_provider_usage,
                ragas_mode="off",
                ragas_sample_rate=0.0,
            )
            await persist_interaction(
                trace_id=trace_id,
                user_query=message,
                bot_response=error_response,
                contexts=[],
                cached=False,
                session_id=session_id,
                request_status="technical_error",
                technical_error=tech_error,
                latency=metrics.latency,
                observed_provider=metrics.observed_provider,
                observed_model=metrics.observed_model,
                provider_usage=metrics.provider_usage,
                ragas_mode=metrics.ragas_mode,
                ragas_status=metrics.ragas_status,
                ragas_selected=False,
                ragas_executed=False,
                citation_count=0,
                context_count=0,
                no_evidence=False,
            )
            if request_id:
                chat_progress.complete(request_id, client_id, status="technical_error")
            return templates.TemplateResponse(
                request,
                "chat_message.html",
                {
                    "user_msg": message,
                    "bot_msg": error_response,
                    "trace_id": trace_id,
                    "session_id": session_id,
                },
                status_code=500,
            )

        # Early check: Handle Answer Generation Technical Failures BEFORE Output Guardrail
        generation_status = latency_info.get("generation_status", "success") if isinstance(latency_info, dict) else "success"
        if generation_status not in ("success", "no_contexts"):
            t_total = round(time.perf_counter() - request_started, 4)
            tech_error = {
                "stage": "answer_generation",
                "error_type": generation_status,
                "message": sanitize_error_message(bot_response),
            }
            err_latency: Dict[str, float] = {
                "t_total": t_total,
                "t_cache": t_cache,
                "t_guardrails_input": t_guardrails_input,
                "t_guardrails_output": 0.0,
            }
            if isinstance(latency_info, dict):
                for k, v in latency_info.items():
                    if isinstance(v, (int, float)):
                        err_latency[k] = float(v)
            err_latency["t_total"] = t_total

            err_observed_prov = latency_info.get("observed_provider") if isinstance(latency_info, dict) else None
            err_observed_mod = latency_info.get("observed_model") if isinstance(latency_info, dict) else None
            err_provider_usage = latency_info.get("provider_usage") if isinstance(latency_info, dict) else None

            metrics = build_online_metrics(
                trace_id=trace_id,
                request_status="technical_error",
                latency=err_latency,
                context_used=context_used,
                bot_response=bot_response,
                cached=False,
                input_safe=True,
                output_safe=True,
                technical_error=tech_error,
                observed_provider=err_observed_prov,
                observed_model=err_observed_mod,
                provider_usage=err_provider_usage,
                ragas_mode="off",
                ragas_sample_rate=0.0,
            )
            await persist_interaction(
                trace_id=trace_id,
                user_query=message,
                bot_response=bot_response,
                contexts=context_used,
                cached=False,
                session_id=session_id,
                request_status="technical_error",
                technical_error=tech_error,
                latency=metrics.latency,
                observed_provider=metrics.observed_provider,
                observed_model=metrics.observed_model,
                provider_usage=metrics.provider_usage,
                ragas_mode=metrics.ragas_mode,
                ragas_status=metrics.ragas_status,
                ragas_selected=False,
                ragas_executed=False,
                citation_count=metrics.citation_count,
                context_count=len(context_used),
                no_evidence=False,
            )
            response = templates.TemplateResponse(
                request,
                "chat_message.html",
                {
                    "user_msg": message,
                    "bot_msg": bot_response,
                    "trace_id": trace_id,
                    "session_id": session_id,
                    "contexts": context_used,
                    "evidence_views": [present_context(item) for item in context_used],
                },
            )
            if is_new_session:
                response.headers["HX-Trigger"] = "load-sessions"
            if request_id:
                chat_progress.complete(request_id, client_id, status="technical_error")
            return response

        # Step 5: Apply NeMo Guardrails (Output Check)
        if request_id:
            chat_progress.advance(
                request_id,
                client_id,
                "output_guardrail",
                "Đang kiểm tra NeMo output" if nemo_enabled else "NeMo output đang tắt",
            )
        try:
            output_safe, fallback_response, t_guardrails_output = (
                await _optional_output_guardrail(
                    bot_response,
                    context_used,
                    message,
                    nemo_enabled,
                )
            )
        except GuardrailUnavailableError as error:
            t_guardrails_output = round(time.perf_counter() - request_started, 4)
            t_total = round(time.perf_counter() - request_started, 4)
            tech_error = {
                "stage": "guardrails_output",
                "error_type": error.__class__.__name__,
                "message": sanitize_error_message(error),
            }
            logfire.error(
                "Output guardrail unavailable",
                error=str(error),
                trace_id=trace_id,
            )
            err_latency = {
                "t_total": t_total,
                "t_cache": t_cache,
                "t_guardrails_input": t_guardrails_input,
                "t_guardrails_output": t_guardrails_output,
            }
            if isinstance(latency_info, dict):
                for k, v in latency_info.items():
                    if isinstance(v, (int, float)):
                        err_latency[k] = float(v)
            err_latency["t_total"] = t_total

            out_provider_usage = latency_info.get("provider_usage") if isinstance(latency_info, dict) else None
            out_observed_prov = latency_info.get("observed_provider") if isinstance(latency_info, dict) else None
            out_observed_mod = latency_info.get("observed_model") if isinstance(latency_info, dict) else None

            metrics = build_online_metrics(
                trace_id=trace_id,
                request_status="technical_error",
                latency=err_latency,
                context_used=context_used,
                bot_response=GUARDRAIL_UNAVAILABLE_MESSAGE,
                cached=False,
                technical_error=tech_error,
                observed_provider=out_observed_prov,
                observed_model=out_observed_mod,
                provider_usage=out_provider_usage,
                ragas_mode="off",
                ragas_sample_rate=0.0,
            )
            await persist_interaction(
                trace_id=trace_id,
                user_query=message,
                bot_response=GUARDRAIL_UNAVAILABLE_MESSAGE,
                contexts=context_used,
                cached=False,
                session_id=session_id,
                request_status="technical_error",
                technical_error=tech_error,
                latency=metrics.latency,
                observed_provider=metrics.observed_provider,
                observed_model=metrics.observed_model,
                provider_usage=metrics.provider_usage,
                ragas_mode=metrics.ragas_mode,
                ragas_status=metrics.ragas_status,
                ragas_selected=False,
                ragas_executed=False,
                citation_count=0,
                context_count=len(context_used),
                no_evidence=False,
            )
            if request_id:
                chat_progress.complete(request_id, client_id, status="technical_error")
            return templates.TemplateResponse(
                request,
                "chat_message.html",
                {
                    "user_msg": message,
                    "bot_msg": GUARDRAIL_UNAVAILABLE_MESSAGE,
                    "trace_id": trace_id,
                    "session_id": session_id,
                },
                status_code=503,
            )

        final_response = bot_response if output_safe else fallback_response
        final_response = redact_pii(final_response)
        rejection_reason = None if output_safe else "Hallucination or unsafe output detected"
        
        # Build online operational metrics
        if not context_used:
            req_status = "no_evidence"
        elif not output_safe:
            req_status = "blocked_output"
        else:
            req_status = "ok"

        t_total = round(time.perf_counter() - request_started, 4)
        full_latency: Dict[str, float] = {
            "t_total": t_total,
            "t_cache": t_cache,
            "t_guardrails_input": t_guardrails_input,
            "t_guardrails_output": t_guardrails_output,
        }
        if isinstance(latency_info, dict):
            for k, v in latency_info.items():
                if isinstance(v, (int, float)):
                    full_latency[k] = float(v)
        full_latency["t_total"] = t_total

        observed_prov = latency_info.get("observed_provider") if isinstance(latency_info, dict) else None
        observed_mod = latency_info.get("observed_model") if isinstance(latency_info, dict) else None
        provider_use = latency_info.get("provider_usage") if isinstance(latency_info, dict) else None

        metrics = build_online_metrics(
            trace_id=trace_id,
            request_status=req_status,
            latency=full_latency,
            context_used=context_used,
            bot_response=final_response,
            cached=False,
            input_safe=True,
            output_safe=output_safe,
            rejection_reason=rejection_reason,
            ragas_mode="off",
            ragas_sample_rate=0.0,
            observed_provider=observed_prov,
            observed_model=observed_mod,
            provider_usage=provider_use,
        )

        # Save log to database
        await persist_interaction(
            trace_id=trace_id,
            user_query=message,
            bot_response=final_response,
            contexts=context_used,
            cached=False,
            input_safe=True,
            output_safe=output_safe,
            rejection_reason=rejection_reason,
            session_id=session_id,
            request_status=req_status,
            latency=metrics.latency,
            observed_provider=metrics.observed_provider,
            observed_model=metrics.observed_model,
            provider_usage=metrics.provider_usage,
            ragas_mode=metrics.ragas_mode,
            ragas_status=metrics.ragas_status,
            ragas_selected=metrics.ragas_selected,
            ragas_executed=metrics.ragas_executed,
            citation_count=metrics.citation_count,
            context_count=metrics.context_count,
            no_evidence=metrics.no_evidence,
            refusal_category=metrics.refusal_category,
            retrieval_trace=sanitize_retrieval_trace(
                latency_info,
                context_used,
                settings,
                query=message,
                cached=False,
            ),
        )
        
        # Cache only grounded, output-approved answers and preserve their evidence.
        if req_status == "ok" and context_used and scoped_outcome is None:
            background_tasks.add_task(
                save_to_semantic_cache,
                message,
                final_response,
                context_used,
            )
        
        # Ragas is an opt-in offline audit and is never enqueued by /chat.
        # Step 8: Return HTML partial response
        response = templates.TemplateResponse(
            request,
            "chat_message.html",
            {"user_msg": message, "bot_msg": final_response, "trace_id": trace_id, "session_id": session_id, "contexts": context_used, "evidence_views": [present_context(item) for item in context_used], "claim_support": build_claim_support(final_response, context_used)}
        )
        if is_new_session:
            response.headers["HX-Trigger"] = "load-sessions"
        if request_id:
            chat_progress.complete(request_id, client_id, status=req_status)
        return response




@router.post("/api/feedback")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def feedback(
    request: Request,
    trace_id: str = Form(...),
    rating: str = Form(...),
    csrf_token: str = Form(...),
    csrf_valid: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    if rating not in {"up", "down"}:
        raise HTTPException(status_code=422, detail="Invalid feedback rating")
    with logfire.span("Xử lý Feedback", trace_id=trace_id, rating=rating):
        updated = await update_feedback(
            trace_id,
            rating,
            client_id=getattr(request.state, "client_id", "legacy"),
            user_id=(str(current_user["_id"]) if current_user else None),
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Interaction not found")
        return {"status": "success", "message": "Thank you for your feedback!"}


@router.post("/api/evaluation/{trace_id}")
@limiter.limit(settings.PUBLIC_EVALUATION_RATE_LIMIT)
async def public_evaluation(
    request: Request,
    trace_id: str,
    run_ragas: bool = Form(False),
    csrf_token: str = Form(...),
    csrf_valid: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    client_id = getattr(request.state, "client_id", "legacy")
    user_id = str(current_user["_id"]) if current_user else None
    interaction = await _owned_interaction(trace_id, client_id, user_id)
    if interaction is None:
        raise HTTPException(status_code=404, detail="Interaction not found")

    payload = {
        "code_evaluation": build_code_evaluation(interaction),
        "ragas_metrics": ragas_metric_catalog(has_reference=False),
        "ragas": {"status": "not_requested"},
    }
    if not run_ragas:
        return payload
    if not getattr(settings, "PUBLIC_RAGAS_ENABLED", False):
        payload["ragas"] = {"status": "disabled"}
        return JSONResponse(payload, status_code=503)

    metrics = interaction.get("metrics") or {}
    if metrics.get("ragas_executed"):
        payload["ragas"] = {
            "status": metrics.get("ragas_status") or "cached",
            "cached": True,
            "faithfulness": metrics.get("ragas_proxy_faithfulness"),
            "answer_relevance": metrics.get("ragas_proxy_answer_relevance"),
        }
        if metrics.get("ragas_error"):
            payload["ragas"]["error"] = metrics["ragas_error"]
        return payload

    if not interaction.get("contexts"):
        payload["ragas"] = {"status": "skipped_no_context"}
        return JSONResponse(payload, status_code=422)

    if not _public_ragas_quota.reserve(client_id):
        payload["ragas"] = {"status": "quota_exceeded"}
        return JSONResponse(payload, status_code=429)

    async with _public_ragas_semaphore:
        await run_llm_as_judge(
            interaction.get("user_query") or "",
            list(interaction.get("contexts") or []),
            interaction.get("bot_response") or "",
            trace_id,
            force=True,
        )
    refreshed = await _owned_interaction(trace_id, client_id, user_id) or interaction
    refreshed_metrics = refreshed.get("metrics") or {}
    payload["ragas"] = {
        "status": refreshed_metrics.get("ragas_status") or "unavailable",
        "cached": False,
        "faithfulness": refreshed_metrics.get("ragas_proxy_faithfulness"),
        "answer_relevance": refreshed_metrics.get("ragas_proxy_answer_relevance"),
    }
    if refreshed_metrics.get("ragas_error"):
        payload["ragas"]["error"] = refreshed_metrics["ragas_error"]
    return payload

@router.get("/sessions", response_class=HTMLResponse)
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def list_sessions(
    request: Request,
    search: str = "",
    current_user=Depends(optional_user),
):
    client_id = getattr(request.state, "client_id", "legacy")
    sessions = await get_sessions(
        client_id,
        search_query=search.strip()[:100],
        user_id=(str(current_user["_id"]) if current_user else None),
    )
    return templates.TemplateResponse(
        request,
        "sidebar_sessions.html",
        {"sessions": sessions}
    )

@router.post("/sessions", response_class=HTMLResponse)
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def new_session(
    request: Request,
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    session_id = str(uuid.uuid4())
    client_id = getattr(request.state, "client_id", "legacy")
    await create_session(
        session_id,
        "Hội thoại mới",
        client_id=client_id,
        user_id=(str(current_user["_id"]) if current_user else None),
    )
    response = HTMLResponse(
        content=(
            '<article class="message-card assistant-message">'
            '<div class="message-role">VietLex</div>'
            '<div class="answer-body"><p>Hội thoại mới đã sẵn sàng. '
            'Bạn có thể đặt câu hỏi pháp luật bằng tiếng Việt.</p></div>'
            '</article>'
            f'<input type="hidden" name="session_id" value="{session_id}" '
            'id="session-id-input">'
        )
    )
    response.headers["HX-Trigger"] = "load-sessions"
    return response

@router.get("/sessions/{session_id}", response_class=HTMLResponse)
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def get_session_history(
    request: Request,
    session_id: str,
    current_user=Depends(optional_user),
):
    client_id = getattr(request.state, "client_id", "legacy")
    raw_messages = await get_session_messages(
        session_id,
        client_id,
        user_id=(str(current_user["_id"]) if current_user else None),
    )
    messages = [
        {
            **message,
            "evidence_views": [
                present_context(item) for item in (message.get("contexts") or [])
            ],
            "claim_support": build_claim_support(
                message.get("bot_response") or "", message.get("contexts") or []
            ),
        }
        for message in raw_messages
    ]
    return templates.TemplateResponse(
        request,
        "chat_history_messages.html",
        {"messages": messages, "session_id": session_id}
    )

@router.delete("/sessions/{session_id}")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def remove_session(
    request: Request,
    session_id: str,
    _csrf: str = Depends(verify_csrf_header),
    current_user=Depends(optional_user),
):
    await delete_session(
        session_id,
        getattr(request.state, "client_id", "legacy"),
        user_id=(str(current_user["_id"]) if current_user else None),
    )
    response = HTMLResponse(content="")
    response.headers["HX-Trigger"] = "load-sessions"
    return response

@router.post("/sessions/{session_id}/rename", response_class=HTMLResponse)
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def rename_sess(
    request: Request,
    session_id: str,
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    new_title = request.headers.get("HX-Prompt")
    if new_title:
        await rename_session(
            session_id,
            new_title.strip()[:120],
            getattr(request.state, "client_id", "legacy"),
            user_id=(str(current_user["_id"]) if current_user else None),
        )
    sessions = await get_sessions(
        getattr(request.state, "client_id", "legacy"),
        user_id=(str(current_user["_id"]) if current_user else None),
    )
    return templates.TemplateResponse(
        request,
        "sidebar_sessions.html",
        {"sessions": sessions}
    )


@router.get("/sessions/{session_id}/export")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def export_session(
    request: Request,
    session_id: str,
    current_user=Depends(optional_user),
):
    client_id = getattr(request.state, "client_id", "legacy")
    user_id = str(current_user["_id"]) if current_user else None
    sessions = await get_sessions(client_id, user_id=user_id)
    session = next((item for item in sessions if item.get("session_id") == session_id), None)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = await get_session_messages(
        session_id, client_id, user_id=user_id
    )
    body = render_conversation_markdown(session, messages)
    return Response(
        body.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="vietlex-{session_id}.md"'
        },
    )

def _admin_response(request, template, section, title, context=None, *, status_code=200):
    csrf_token = request.cookies.get("csrf_token") or secrets.token_hex(32)
    response = templates.TemplateResponse(
        request, template,
        {"admin_section": section, "page_title": title, "csrf_token": csrf_token,
         "settings": settings, **(context or {})},
        status_code=status_code, headers={"Cache-Control": "no-store"},
    )
    if not request.cookies.get("csrf_token"):
        response.set_cookie("csrf_token", csrf_token, httponly=True,
                            secure=settings.APP_ENV == "production" or request.url.scheme == "https",
                            samesite="strict")
    return response


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(
    request: Request, filters: dict = Depends(admin_filters),
    skip: int = Query(0, ge=0, le=100000), limit: int = Query(25, ge=1, le=100),
    _admin: dict = Depends(require_admin),
):
    stats, logs, inventory = await asyncio.gather(
        get_admin_stats(filters=filters), _load_admin_logs(limit=6, skip=0, **filters),
        get_admin_inventory(),
    )
    return _admin_response(request, "admin.html", "overview", "Tổng quan vận hành", {
        "stats": stats, "inventory": inventory,
        "logs": [_sanitize_admin_interaction(log) for log in logs],
        "filters": filters, "filter_action": "/admin", "limit": limit,
        "export_url": "/admin/export.csv?" + str(request.url.query),
    }, status_code=503 if stats.get("status") == "unavailable" else 200)


@router.get("/admin/requests", response_class=HTMLResponse)
async def admin_requests_page(
    request: Request, filters: dict = Depends(admin_filters),
    skip: int = Query(0, ge=0, le=100000), limit: int = Query(25, ge=1, le=100),
    _admin: dict = Depends(require_admin),
):
    logs = await _load_admin_logs(limit=limit, skip=skip, **filters)
    return _admin_response(request, "admin_requests_page.html", "requests", "Nhật ký requests", {
        "logs": [_sanitize_admin_interaction(log) for log in logs],
        "filters": filters, "filter_action": "/admin/requests", "skip": skip, "limit": limit,
        **admin_page_links(request, skip, limit, len(logs)),
    })


@router.get("/admin/usage", response_class=HTMLResponse)
async def admin_usage_page(request: Request, filters: dict = Depends(admin_filters),
                           _admin: dict = Depends(require_admin)):
    stats = await get_admin_stats(filters=filters)
    return _admin_response(request, "admin_usage_page.html", "usage", "Usage và chất lượng", {
        "stats": stats, "filters": filters, "filter_action": "/admin/usage", "limit": 25,
        "export_url": "/admin/export.csv?" + str(request.url.query),
    }, status_code=503 if stats.get("status") == "unavailable" else 200)


@router.get("/admin/providers", response_class=HTMLResponse)
async def admin_providers_page(request: Request, _admin: dict = Depends(require_admin)):
    return _admin_response(request, "admin_providers_page.html", "providers", "Nhà cung cấp AI", {
        "provider_status": provider_status_snapshot(settings, provider_cooldown_snapshot()),
    })


@router.get("/admin/system", response_class=HTMLResponse)
async def admin_system_page(request: Request, _admin: dict = Depends(require_admin)):
    async def mongo_ping():
        from app.database import get_db
        return (await get_db().command("ping")).get("ok") == 1.0

    system_status = await build_readiness(settings, mongo_ping)
    return _admin_response(request, "admin_system_page.html", "system", "Hệ thống và giới hạn", {
        "system_status": system_status, "demo_admission": demo_admission_snapshot(),
    })


@router.get("/admin/stats", response_class=HTMLResponse)
async def admin_stats_partial(request: Request, filters: dict = Depends(admin_filters), _admin: str = Depends(require_admin)):
    stats = await get_admin_stats(filters=filters)
    return templates.TemplateResponse(
        request,
        "admin_stats.html",
        {"stats": stats}, headers={"Cache-Control": "no-store"},
        status_code=503 if stats.get('status') == 'unavailable' else 200,
    )

@router.get("/admin/logs", response_class=HTMLResponse)
async def admin_logs_partial(
    request: Request,
    skip: int = Query(0, ge=0, le=100000),
    limit: int = Query(25, ge=1, le=100),
    filters: dict = Depends(admin_filters),
    _admin: dict = Depends(require_admin),
):
    logs = await _load_admin_logs(
        limit=limit,
        skip=skip,
        **filters,
    )
    logs = [_sanitize_admin_interaction(log) for log in logs]
    return templates.TemplateResponse(
        request,
        "admin_logs.html",
        {"logs": logs, "skip": skip, "limit": limit, **admin_page_links(request, skip, limit, len(logs))},
        headers={"Cache-Control": "no-store"}
    )

@router.get('/admin/export.csv')
async def admin_export(request: Request, filters: dict = Depends(admin_filters),
                       skip: int = Query(0, ge=0, le=100000), _admin: dict = Depends(require_admin)):
    logs = await _load_admin_logs(limit=100, skip=skip, **filters)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['trace_id', 'question_redacted', 'request_status', 'provider', 'model',
                     'context_count', 'reported_llm_tokens', 'measured_calls', 'calls', 'ragas_status'])
    def cell(value):
        text = str(value) if value is not None else ''
        return "'" + text if text.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else text
    for raw in logs:
        log = present_interaction(raw)
        metrics = log['metrics']
        writer.writerow([cell(value) for value in (log['trace_id'], log['user_query'], metrics.get('request_status'),
            metrics.get('observed_provider'), metrics.get('observed_model'), log['stored_context_count'],
            log['usage']['total_token_count'], log['usage']['measured_calls'], log['usage']['calls'], metrics.get('ragas_status'))])
    await write_admin_audit(str(_admin['_id']), 'request_export', 'evaluation_logs', 'bounded-export',
                            metadata={'rows': len(logs), 'skip': skip, 'limit': 100})
    return Response('\ufeff' + output.getvalue(), media_type='text/csv; charset=utf-8', headers={
        'Cache-Control': 'no-store', 'Content-Disposition': 'attachment; filename="vietlex-requests.csv"',
        'X-Export-Limit': '100', 'X-Export-Rows': str(len(logs)),
    })

@router.get("/admin/details/{trace_id}", response_class=HTMLResponse)
async def admin_details_partial(
    request: Request,
    trace_id: str,
    _admin: str = Depends(require_admin),
):
    try:
        log = await get_interaction(trace_id, strict=True)
    except AdminDataUnavailable:
        raise HTTPException(503, 'Không đọc được request.', headers={'Cache-Control': 'no-store'}) from None
    if log:
        log = _sanitize_admin_interaction(log)
    return _admin_response(
        request, "admin_details.html", "requests", "Chi tiết request",
        {"log": log}, status_code=200 if log else 404,
    )


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_partial(
    request: Request, search: str = Query("", max_length=100),
    account_status: str = Query("", pattern="^(active|disabled)?$"),
    role: str = Query("", pattern="^(admin|user)?$"),
    skip: int = Query(0, ge=0, le=100000), limit: int = Query(25, ge=1, le=100),
    _admin: dict = Depends(require_admin),
):
    users = await list_users(search=search.strip(), status=account_status, role=role,
                             skip=skip, limit=limit)
    return _admin_response(request, "admin_users_page.html", "users", "Tài khoản", {
        "users": users, "current_admin": _admin, "search": search,
        "account_status": account_status, "role": role, "skip": skip, "limit": limit,
        **admin_page_links(request, skip, limit, len(users)),
    })


@router.post("/admin/users/{user_id}/status")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def admin_set_user_status(
    request: Request,
    user_id: str,
    account_status: str = Form(...),
    _csrf: str = Depends(verify_csrf),
    admin: dict = Depends(require_admin),
):
    if account_status == "disabled" and str(admin["_id"]) == user_id:
        raise HTTPException(status_code=409, detail="Administrators cannot disable themselves.")
    try:
        changed = await set_user_status(user_id[:100], account_status)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    if not changed:
        raise HTTPException(status_code=404, detail="User not found.")
    await write_admin_audit(
        str(admin["_id"]),
        f"account_{account_status}",
        "user",
        user_id,
        request_id=request.headers.get("x-request-id"),
    )
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/admin/users/{user_id}/revoke-sessions")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def admin_revoke_user_sessions(
    request: Request,
    user_id: str,
    _csrf: str = Depends(verify_csrf),
    admin: dict = Depends(require_admin),
):
    if await get_user_by_id(user_id[:100]) is None:
        raise HTTPException(status_code=404, detail="User not found.")
    await revoke_all_auth_sessions(user_id[:100])
    await write_admin_audit(
        str(admin["_id"]),
        "sessions_revoked",
        "user",
        user_id,
        request_id=request.headers.get("x-request-id"),
    )
    return RedirectResponse("/admin/users", status_code=303)


@router.get("/admin/audit", response_class=HTMLResponse)
async def admin_audit_partial(
    request: Request, limit: int = Query(50, ge=1, le=100),
    skip: int = Query(0, ge=0, le=100000),
    _admin: dict = Depends(require_admin),
):
    try:
        audit_logs = await get_admin_audit_logs(limit=limit, skip=skip, strict=True)
    except AdminDataUnavailable:
        return _admin_response(request, "admin_error_page.html", "audit", "Nhật ký quản trị", {
            "message": "Không đọc được nhật ký quản trị. Vui lòng thử lại sau.",
        }, status_code=503)
    return _admin_response(request, "admin_audit_page.html", "audit", "Nhật ký quản trị", {
        "audit_logs": audit_logs, "limit": limit, "skip": skip,
        **admin_page_links(request, skip, limit, len(audit_logs)),
    })
