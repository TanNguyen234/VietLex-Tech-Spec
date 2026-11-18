from app.services.reviewer_demo import demo_admission_snapshot
import asyncio
import json
import time
import uuid
import secrets
import csv
import io
from datetime import date
from typing import Any, Dict, Literal
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
    require_online_persistence,
    verify_csrf,
    verify_csrf_header,
)
from app.config import get_settings, is_stateless_development
from app.services.public_evaluation import (
    DailyRagasQuota,
    build_code_evaluation,
    ragas_metric_catalog,
)
from app.services.conversation_export import render_conversation_markdown
from app.services.readiness import build_readiness
from app.services.runtime_identity import runtime_identity
from app.services.chat_intent import deterministic_guidance
from app.services.conversation_context import followup_context, is_explicit_followup
from app.rate_limit import limiter
from app.services.evidence_presenter import present_context
from app.services.provider_runtime import provider_status_snapshot, capture_provider_usage
from app.services.admin_observability import clean_text, present_interaction, summarize_usage, AdminDataUnavailable
from app.services.direct_llm import (
    LLMGenerationResult,
    LLMUseCase,
    can_select_custom_llm_route,
    list_available_llm_targets,
    llm_route_scope,
    provider_cooldown_snapshot,
    resolve_llm_route,
    stream_llm_response_with_metadata,
)
from app.services.guarded_answer_cache import (
    guarded_answer_cache,
    is_guarded_answer_cache_enabled,
    is_guarded_cacheable_query,
)
from app.services.provider_http_budget import ProviderHttpAttemptBudgetExceeded
from app.services.chat_progress import chat_progress
from app.services.research_presenter import (
    build_claim_support,
    build_public_retrieval_trace,
    sanitize_retrieval_trace,
)

from app.services.answer_cleanup import strip_context_echo
from app.services.pii import redact_pii
from app.services.runtime_errors import (
    GUARDRAIL_UNAVAILABLE_MESSAGE,
    GuardrailUnavailableError,
    RetrievalPipelineError,
    guardrail_error_reason,
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
    set_user_role,
    set_user_status,
    write_admin_audit,
)

router = APIRouter()
templates = Jinja2Templates(directory=APP_ROOT / "templates")
settings = get_settings()
templates.env.globals["local_stateless_mode"] = is_stateless_development(settings)
_NON_RECOVERY_STATUSES = {
    "clarification",
    "unsupported_intent",
    "blocked_input",
    "blocked_output",
    "technical_error",
}
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
    if settings.APP_ENV == "development":
        return None
    from app.services.semantic_cache import check_semantic_cache as implementation

    return await implementation(message)


async def save_to_semantic_cache(*args, **kwargs):
    if settings.APP_ENV == "development":
        return None
    from app.services.semantic_cache import save_to_semantic_cache as implementation

    return await implementation(*args, **kwargs)


def semantic_cache_query_allowed(message: str) -> bool:
    if settings.APP_ENV == "development":
        return False
    from app.services.semantic_cache import is_cacheable_query

    return is_cacheable_query(message)


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


def _guardrail_state(mode: str) -> dict:
    return {
        "mode": mode, "requested": mode != "off", "executed": False,
        "status": "not_run", "input_safe": None, "output_safe": None,
        "stages": {stage: {"status": "not_run", "safe": None, "error": None}
                   for stage in ("input", "output")},
    }


async def _run_guardrail(stage: str, mode: str, state: dict, check, *args):
    if mode == "off":
        return True, "", 0.0
    started = time.perf_counter()
    state["executed"] = True
    result = state["stages"][stage]
    try:
        safe, fallback = await check(*args)
        if type(safe) is not bool:
            raise GuardrailUnavailableError(stage, "invalid_decision")
        result.update(status="passed" if safe else "rejected", safe=safe)
    except Exception as error:
        if not isinstance(error, GuardrailUnavailableError):
            error = GuardrailUnavailableError(stage, type(error).__name__)
        reason = guardrail_error_reason(getattr(error, "reason", None))
        result.update(status="error", safe=None, error={
            "type": "GuardrailUnavailableError", "stage": stage, "reason": reason,
        })
        if mode == "enforce":
            raise error
        safe, fallback = True, ""
    finally:
        state[f"{stage}_safe"] = result["safe"]
        statuses = [item["status"] for item in state["stages"].values()]
        state["status"] = ("error" if "error" in statuses else "rejected" if "rejected" in statuses
                           else "passed" if all(item == "passed" for item in statuses) else "not_run")
    if mode == "shadow" and result["status"] != "passed":
        logfire.warning("Shadow guardrail observation", stage=stage, status=result["status"],
                        error_kind=(result["error"] or {}).get("reason"))
    return safe if mode == "enforce" else True, fallback, round(time.perf_counter() - started, 4)


@router.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "vietlex", "identity": runtime_identity(settings)}


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
    request: Request,
    trace_id: str,
    _persistence=Depends(require_online_persistence),
    current_user=Depends(optional_user),
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
@limiter.limit(settings.PUBLIC_PROGRESS_RATE_LIMIT)
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


def build_index_llm_controls(
    current_user: dict | None = None,
    active_settings: Any = None,
) -> dict[str, Any]:
    s = active_settings if active_settings is not None else settings
    allowed = can_select_custom_llm_route(current_user, settings=s)
    return {
        "can_select_llm_route": allowed,
        "llm_targets": list_available_llm_targets(s) if allowed else [],
    }


def _resolve_web_mode(
    web_mode: str | None,
    current_user: dict | None = None,
    active_settings: Any = None,
) -> str:
    s = active_settings if active_settings is not None else settings
    if not can_select_custom_llm_route(current_user, settings=s):
        return "auto"
    normalized = (web_mode or "auto").strip().lower()
    return normalized if normalized in {"auto", "force", "off"} else "auto"


async def _maybe_autotitle_session(
    session_id: str,
    clean_query: str,
    *,
    client_id: str,
    user_id: str | None = None,
) -> str | None:
    if not session_id or session_id == "default":
        return None
    sessions = await get_sessions(client_id, user_id=user_id)
    matched = next(
        (
            item
            for item in (sessions or [])
            if (item.get("session_id") or item.get("_id")) == session_id
        ),
        None,
    )
    if not isinstance(matched, dict) or matched.get("title") != "Hội thoại mới":
        return None
    existing = await get_session_messages(
        session_id,
        client_id,
        user_id=user_id,
        recent_limit=1,
    )
    if existing:
        return None
    normalized_title = " ".join(clean_query.split())[:48]
    if not normalized_title:
        return None
    await rename_session(
        session_id,
        normalized_title,
        client_id,
        user_id=user_id,
    )
    return normalized_title


def verify_clause_citations(
    answer: str,
    contexts: list[str],
) -> tuple[str, dict[str, Any]]:
    from app.services.citation_clause_guard import (
        correct_clause_citations,
        drop_ungrounded_document_citations,
    )

    adjustments: dict[str, Any] = {}
    corrected, clause_changes = correct_clause_citations(answer, contexts)
    if clause_changes:
        adjustments["citation_clause_changes"] = clause_changes
    corrected, ungrounded = drop_ungrounded_document_citations(corrected, contexts)
    if ungrounded:
        adjustments["ungrounded_citations_removed"] = ungrounded
    return corrected, adjustments


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
    guardrail_mode: Literal["off", "shadow", "enforce"] | None = Form(None),
    document_id: int | None = Form(None, ge=0),
    request_id: str = Form(""),
    llm_provider: str = Form("auto"),
    llm_model: str | None = Form(None),
    web_mode: str = Form("auto"),
    csrf_valid: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    request_started = time.perf_counter()
    # Public policy is mandatory in every environment, including legacy clients.
    mode = "enforce"
    guardrail_state = _guardrail_state(mode)
    nemo_enabled = mode != "off"
    selected_route = resolve_llm_route(
        llm_provider,
        llm_model,
        user=current_user,
        settings=settings,
    )
    effective_web_mode = _resolve_web_mode(web_mode, current_user, settings)
    route_cache_key = selected_route.cache_key()
    message = redact_pii(message)
    trace_id = str(uuid.uuid4())
    client_id = getattr(request.state, "client_id", "legacy")
    user_id = str(current_user["_id"]) if current_user else None
    scoped_outcome = None
    async def persist_interaction(**kwargs):
        kwargs.update(input_safe=guardrail_state["input_safe"],
                      output_safe=guardrail_state["output_safe"], guardrail_state=guardrail_state)
        return await log_interaction(
            **kwargs, client_id=client_id, user_id=user_id,
            request_metadata={'method': 'POST', 'path': '/chat', 'nemo_requested': nemo_enabled,
                              'guardrail_engine': 'direct_self_check' if settings.SERVERLESS_ONLINE_ONLY else 'nemo',
                              'scope': 'document' if document_id is not None else 'corpus', 'document_id': document_id},
        )
    if request_id:
        chat_progress.start(request_id, client_id, nemo_enabled=nemo_enabled)
    is_new_session = False
    autotitled = False

    if not session_id or session_id == "default":
        session_id = str(uuid.uuid4())
        words = message.split()
        title = " ".join(words[:5]) + ("..." if len(words) > 5 else "")
        await create_session(
            session_id, title, client_id=client_id, user_id=user_id
        )
        is_new_session = True
    else:
        autotitled = (
            await _maybe_autotitle_session(
                session_id,
                message,
                client_id=client_id,
                user_id=user_id,
            )
            is not None
        )
    should_reload_sessions = is_new_session or autotitled
        
    with logfire.span("Xử lý Chat Request", trace_id=trace_id, query_length=len(message)) as span:
        t_cache = 0.0

        # Step 2: Apply NeMo Guardrails (Input Check)
        if request_id:
            chat_progress.advance(
                request_id,
                client_id,
                "input_guardrail",
                "Đang kiểm tra an toàn đầu vào",
            )
        try:
            input_safe, rejection_message, t_guardrails_input = (
                await _run_guardrail("input", mode, guardrail_state, check_input_guardrails, message)
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
                error_kind=type(error).__name__,
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
                    "show_recovery": False,
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
                {
                    "user_msg": message,
                    "bot_msg": rejection_message,
                    "trace_id": trace_id,
                    "session_id": session_id,
                    "show_recovery": False,
                },
            )
            if should_reload_sessions:
                response.headers["HX-Trigger"] = "load-sessions"
            if request_id:
                chat_progress.complete(request_id, client_id, status="blocked_input")
            return response

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

        # Step 3: Check Semantic Cache only after the input is approved.
        if request_id:
            chat_progress.advance(
                request_id, client_id, "semantic_cache", "Đang kiểm tra semantic cache"
            )
        cache_started = time.perf_counter()
        followup_requested = scoped_outcome is None and is_explicit_followup(message)
        previous_user_query = None
        if followup_requested and not is_new_session:
            previous_user_query = followup_context(message, await get_session_messages(
                session_id, client_id, user_id=user_id, recent_limit=8,
            ))
        cacheable_query = (
            scoped_outcome is None and effective_web_mode == "auto"
            and deterministic_guidance(message) is None
            and not followup_requested and semantic_cache_query_allowed(message)
        )
        guarded_cacheable = (
            scoped_outcome is None
            and effective_web_mode == "auto"
            and deterministic_guidance(message) is None
            and not followup_requested
            and is_guarded_answer_cache_enabled(settings)
            and is_guarded_cacheable_query(message)
        )
        guarded_hit = (
            guarded_answer_cache.get(
                message,
                settings=settings,
                route_key=route_cache_key,
            )
            if guarded_cacheable
            else None
        )
        cached_response = (
            guarded_hit
            if guarded_hit is not None
            else (
                await check_semantic_cache(message)
                if cacheable_query and not nemo_enabled
                else None
            )
        )
        t_cache = round(time.perf_counter() - cache_started, 4)

        if cached_response:
            if guarded_hit is not None:
                guardrail_state["output_safe"] = True
                guardrail_state["stages"]["output"] = {
                    "status": "passed",
                    "safe": True,
                    "error": None,
                }
                guardrail_state["status"] = "passed"
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
                output_safe=True if guarded_hit is not None else None,
                observed_provider=(
                    guarded_hit.observed_provider if guarded_hit is not None else None
                ),
                observed_model=(
                    guarded_hit.observed_model if guarded_hit is not None else None
                ),
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
                    "claim_support": (
                        build_claim_support(cached_text, cached_contexts)
                        if cached_contexts
                        else []
                    ),
                    "show_recovery": bool(cached_contexts),
                },
            )
            if should_reload_sessions:
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
            rag_kwargs: dict[str, Any] = {}
            if scoped_outcome is not None:
                rag_kwargs["scoped_outcome"] = scoped_outcome
            elif previous_user_query:
                rag_kwargs["previous_user_query"] = previous_user_query
            if effective_web_mode != "auto":
                rag_kwargs["web_mode"] = effective_web_mode
            with llm_route_scope(selected_route):
                bot_response, context_used, latency_info = await run_advanced_rag(
                    message, **rag_kwargs
                )
        except (RetrievalPipelineError, ProviderHttpAttemptBudgetExceeded) as error:
            t_total = round(time.perf_counter() - request_started, 4)
            tech_error = {
                "stage": (
                    "answer_generation"
                    if isinstance(error, ProviderHttpAttemptBudgetExceeded)
                    else getattr(error, "status", "retrieval_error")
                ),
                "error_type": error.__class__.__name__,
                "message": sanitize_error_message(error),
            }
            error_response = "Hệ thống tra cứu văn bản pháp luật gặp sự cố kỹ thuật. Vui lòng thử lại sau."
            logfire.error(
                "Retrieval pipeline failed",
                error_kind=type(error).__name__,
                trace_id=trace_id,
            )
            err_latency: Dict[str, float] = {
                "t_total": t_total,
                "t_cache": t_cache,
                "t_guardrails_input": t_guardrails_input,
            }
            error_latency = getattr(error, "latency", None)
            if isinstance(error_latency, dict):
                for k, v in error_latency.items():
                    if isinstance(v, (int, float)):
                        err_latency[k] = float(v)
            err_latency["t_total"] = t_total

            err_provider_usage = error_latency.get("provider_usage") if isinstance(error_latency, dict) else None
            err_observed_prov = error_latency.get("observed_provider") if isinstance(error_latency, dict) else None
            err_observed_mod = error_latency.get("observed_model") if isinstance(error_latency, dict) else None

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
                    "show_recovery": False,
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
                    "claim_support": [],
                    "show_recovery": False,
                },
                status_code=503,
            )
            if should_reload_sessions:
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
                "Đang kiểm tra câu trả lời với nguồn",
            )
        try:
            output_safe, fallback_response, t_guardrails_output = (
                await _run_guardrail(
                    "output", mode, guardrail_state, check_output_guardrails,
                    bot_response,
                    context_used,
                    (f"Dữ kiện trước do người dùng cung cấp: {previous_user_query}\n"
                     f"Câu hỏi tiếp theo: {message}" if previous_user_query else message),
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
                error_kind=type(error).__name__,
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
                    "show_recovery": False,
                },
                status_code=503,
            )

        final_response = bot_response if output_safe else fallback_response
        final_response = strip_context_echo(redact_pii(final_response))
        rejection_reason = None if output_safe else "Hallucination or unsafe output detected"
        
        # Build online operational metrics
        response_kind = latency_info.get("response_kind") if isinstance(latency_info, dict) else None
        if not output_safe:
            req_status = "blocked_output"
        elif response_kind in {"clarification", "unsupported_intent"}:
            req_status = response_kind
        elif not context_used:
            req_status = "no_evidence"
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
        if (
            req_status == "ok"
            and input_safe is True
            and output_safe is True
            and context_used
            and guarded_cacheable
        ):
            guarded_answer_cache.put(
                message,
                final_response,
                context_used,
                settings=settings,
                route_key=route_cache_key,
                input_safe=input_safe,
                output_safe=output_safe,
                request_status=req_status,
                observed_provider=observed_prov,
                observed_model=observed_mod,
            )
        if req_status == "ok" and context_used and cacheable_query and not nemo_enabled:
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
            {
                "user_msg": message,
                "bot_msg": final_response,
                "trace_id": trace_id,
                "session_id": session_id,
                "contexts": context_used,
                "evidence_views": [present_context(item) for item in context_used],
                "claim_support": (
                    build_claim_support(final_response, context_used)
                    if context_used
                    else []
                ),
                "show_recovery": req_status not in _NON_RECOVERY_STATUSES,
            },
        )
        if should_reload_sessions:
            response.headers["HX-Trigger"] = "load-sessions"
        if request_id:
            chat_progress.complete(request_id, client_id, status=req_status)
        return response


def _ndjson_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


async def retrieve_stream_contexts(
    user_query: str,
    *,
    scoped_outcome: Any = None,
    previous_user_query: str | None = None,
    web_mode: str = "auto",
    stage_events: list[str] | None = None,
) -> tuple[list[str], str, dict[str, Any], str | None]:
    from app.services.rag_pipeline import prepare_rag_contexts

    return await prepare_rag_contexts(
        user_query,
        scoped_outcome=scoped_outcome,
        previous_user_query=previous_user_query,
        web_mode=web_mode,
        stage_events=stage_events,
    )


@router.post("/chat/stream")
@limiter.limit(settings.CHAT_RATE_LIMIT)
async def chat_stream(
    request: Request,
    message: str = Form(...),
    csrf_token: str = Form(...),
    session_id: str = Form(None),
    nemo_enabled: bool = Form(True),
    guardrail_mode: Literal["off", "shadow", "enforce"] | None = Form(None),
    document_id: int | None = Form(None, ge=0),
    request_id: str = Form(""),
    llm_provider: str = Form("auto"),
    llm_model: str | None = Form(None),
    web_mode: str = Form("auto"),
    csrf_valid: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    from dataclasses import replace
    from app.services.provider_http_budget import provider_http_budget_scope
    from app.services.provider_runtime import _request_calls
    from app.services.direct_llm import generate_llm_response_with_metadata
    from app.services.rag_pipeline import (
        NO_EVIDENCE_RESPONSE,
        _legal_effect_answer_diagnostics,
        _scope_current_effect_answer,
        _source_opening_excerpt,
        _strip_latex_markup,
        _unconfirmed_as_of_start_dates,
        build_answer_prompts,
    )

    request_started = time.perf_counter()
    mode = "enforce"
    guardrail_state = _guardrail_state(mode)
    effective_nemo = mode != "off"
    selected_route = resolve_llm_route(
        llm_provider,
        llm_model,
        user=current_user,
        settings=settings,
    )
    effective_web_mode = _resolve_web_mode(web_mode, current_user, settings)
    route_cache_key = selected_route.cache_key()
    raw_trimmed = (message or "").strip()
    clean_query = redact_pii(raw_trimmed)
    trace_id = str(uuid.uuid4())
    client_id = getattr(request.state, "client_id", "legacy")
    user_id = str(current_user["_id"]) if current_user else None

    async def persist_interaction(**kwargs):
        kwargs.update(
            input_safe=guardrail_state["input_safe"],
            output_safe=guardrail_state["output_safe"],
            guardrail_state=guardrail_state,
        )
        return await log_interaction(
            **kwargs,
            client_id=client_id,
            user_id=user_id,
            request_metadata={
                "method": "POST",
                "path": "/chat/stream",
                "nemo_requested": effective_nemo,
                "guardrail_engine": "direct_self_check" if settings.SERVERLESS_ONLINE_ONLY else "nemo",
                "scope": "document" if document_id is not None else "corpus",
                "document_id": document_id,
            },
        )

    def render_message_card(
        bot_text: str,
        contexts_list: list[str],
        current_sess: str,
        *,
        cached: bool = False,
        show_recovery: bool = True,
    ) -> str:
        return templates.env.get_template("chat_message.html").render(
            request=request,
            user_msg=clean_query,
            bot_msg=bot_text,
            trace_id=trace_id,
            cached=cached,
            session_id=current_sess,
            contexts=contexts_list,
            evidence_views=[present_context(item) for item in contexts_list],
            claim_support=(
                build_claim_support(bot_text, contexts_list) if contexts_list else []
            ),
            show_recovery=show_recovery,
        )

    async def stream_events():
        budget_limit = getattr(settings, "PROVIDER_HTTP_ATTEMPT_LIMIT", None)
        with provider_http_budget_scope(limit=budget_limit):
            calls_token = _request_calls.set([])
            try:
                if not clean_query or len(raw_trimmed) > 2000:
                    yield _ndjson_line(
                        {
                            "type": "error",
                            "status": 422,
                            "message": "Câu hỏi phải có độ dài từ 1 đến 2.000 ký tự.",
                        }
                    )
                    return

                current_session_id = session_id
                updated_title: str | None = None
                is_new_session = False
                if not current_session_id or current_session_id == "default":
                    current_session_id = str(uuid.uuid4())
                    words = clean_query.split()
                    updated_title = " ".join(words[:5]) + ("..." if len(words) > 5 else "")
                    await create_session(
                        current_session_id,
                        updated_title,
                        client_id=client_id,
                        user_id=user_id,
                    )
                    is_new_session = True
                else:
                    updated_title = await _maybe_autotitle_session(
                        current_session_id,
                        clean_query,
                        client_id=client_id,
                        user_id=user_id,
                    )

                yield _ndjson_line(
                    {
                        "type": "stage",
                        "stage": "input_guardrail",
                        "label": "Đang kiểm tra an toàn đầu vào",
                        "session_id": current_session_id,
                    }
                )
                t_cache = 0.0
                try:
                    input_safe, rejection_message, t_guardrails_input = await _run_guardrail(
                        "input",
                        mode,
                        guardrail_state,
                        check_input_guardrails,
                        clean_query,
                    )
                except GuardrailUnavailableError as error:
                    t_guardrails_input = round(time.perf_counter() - request_started, 4)
                    t_total = round(time.perf_counter() - request_started, 4)
                    tech_error = {
                        "stage": "guardrails_input",
                        "error_type": error.__class__.__name__,
                        "message": sanitize_error_message(error),
                    }
                    metrics = build_online_metrics(
                        trace_id=trace_id,
                        request_status="technical_error",
                        latency={
                            "t_total": t_total,
                            "t_cache": t_cache,
                            "t_guardrails_input": t_guardrails_input,
                        },
                        context_used=[],
                        bot_response=GUARDRAIL_UNAVAILABLE_MESSAGE,
                        cached=False,
                        technical_error=tech_error,
                        ragas_mode="off",
                        ragas_sample_rate=0.0,
                    )
                    await persist_interaction(
                        trace_id=trace_id,
                        user_query=clean_query,
                        bot_response=GUARDRAIL_UNAVAILABLE_MESSAGE,
                        contexts=[],
                        cached=False,
                        session_id=current_session_id,
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
                    yield _ndjson_line(
                        {
                            "type": "error",
                            "status": 503,
                            "message": GUARDRAIL_UNAVAILABLE_MESSAGE,
                        }
                    )
                    return

                if not input_safe:
                    t_total = round(time.perf_counter() - request_started, 4)
                    metrics = build_online_metrics(
                        trace_id=trace_id,
                        request_status="blocked_input",
                        latency={
                            "t_total": t_total,
                            "t_cache": t_cache,
                            "t_guardrails_input": t_guardrails_input,
                        },
                        context_used=[],
                        bot_response=rejection_message,
                        cached=False,
                        input_safe=False,
                        rejection_reason="Jailbreak or off-topic input blocked by guardrails",
                        ragas_mode="off",
                        ragas_sample_rate=0.0,
                    )
                    await persist_interaction(
                        trace_id=trace_id,
                        user_query=clean_query,
                        bot_response=rejection_message,
                        contexts=[],
                        cached=False,
                        input_safe=False,
                        rejection_reason="Jailbreak or off-topic input blocked by guardrails",
                        session_id=current_session_id,
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
                    yield _ndjson_line(
                        {
                            "type": "complete",
                            "html": render_message_card(
                                rejection_message, [], current_session_id, show_recovery=False
                            ),
                            "session_id": current_session_id,
                            "title": updated_title,
                            "trace_id": trace_id,
                            "guardrail_adjusted": True,
                        }
                    )
                    return

                scoped_outcome = None
                if document_id is not None:
                    from app.api.legal_routes import _get_browser
                    from app.services.document_scope import document_evidence
                    from app.services.legal_browser import LegalBrowserBackendError

                    try:
                        doc_obj = await asyncio.to_thread(_get_browser().get_document, document_id)
                    except LegalBrowserBackendError:
                        yield _ndjson_line(
                            {"type": "error", "status": 503, "message": "Không đọc được văn bản đã chọn."}
                        )
                        return
                    if doc_obj is None:
                        yield _ndjson_line(
                            {"type": "error", "status": 404, "message": "Không tìm thấy văn bản đã chọn."}
                        )
                        return
                    scoped_outcome = await asyncio.to_thread(document_evidence, clean_query, doc_obj)

                cache_started = time.perf_counter()
                followup_requested = scoped_outcome is None and is_explicit_followup(clean_query)
                previous_user_query = None
                if followup_requested and not is_new_session and updated_title is None:
                    previous_user_query = followup_context(
                        clean_query,
                        await get_session_messages(
                            current_session_id,
                            client_id,
                            user_id=user_id,
                            recent_limit=8,
                        ),
                    )
                guarded_cacheable = (
                    scoped_outcome is None
                    and effective_web_mode == "auto"
                    and deterministic_guidance(clean_query) is None
                    and not followup_requested
                    and is_guarded_answer_cache_enabled(settings)
                    and is_guarded_cacheable_query(clean_query)
                )
                guarded_hit = (
                    guarded_answer_cache.get(
                        clean_query,
                        settings=settings,
                        route_key=route_cache_key,
                    )
                    if guarded_cacheable
                    else None
                )
                t_cache = round(time.perf_counter() - cache_started, 4)

                if guarded_hit is not None:
                    guardrail_state["output_safe"] = True
                    guardrail_state["stages"]["output"] = {
                        "status": "passed",
                        "safe": True,
                        "error": None,
                    }
                    guardrail_state["status"] = "passed"
                    cached_contexts = guarded_hit.contexts
                    cached_text = guarded_hit.response
                    t_total = round(time.perf_counter() - request_started, 4)
                    metrics = build_online_metrics(
                        trace_id=trace_id,
                        request_status="cache_hit",
                        latency={
                            "t_total": t_total,
                            "t_cache": t_cache,
                            "t_guardrails_input": t_guardrails_input,
                        },
                        context_used=cached_contexts,
                        bot_response=cached_text,
                        cached=True,
                        input_safe=True,
                        output_safe=True,
                        observed_provider=guarded_hit.observed_provider,
                        observed_model=guarded_hit.observed_model,
                        ragas_mode="off",
                        ragas_sample_rate=0.0,
                    )
                    await persist_interaction(
                        trace_id=trace_id,
                        user_query=clean_query,
                        bot_response=cached_text,
                        contexts=cached_contexts,
                        cached=True,
                        input_safe=True,
                        session_id=current_session_id,
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
                            query=clean_query,
                            cached=True,
                        ),
                    )
                    yield _ndjson_line({"type": "delta", "text": cached_text})
                    yield _ndjson_line(
                        {
                            "type": "complete",
                            "html": render_message_card(
                                cached_text, cached_contexts, current_session_id, cached=True
                            ),
                            "session_id": current_session_id,
                            "title": updated_title,
                            "trace_id": trace_id,
                            "cached": True,
                            "guardrail_adjusted": False,
                        }
                    )
                    return

                guidance_hit = (
                    deterministic_guidance(clean_query)
                    if scoped_outcome is None
                    else None
                )
                if guidance_hit is not None:
                    guidance_kind, guidance_text = guidance_hit
                    context_used = []
                    rewritten_query = ""
                    latency_info = {
                        "response_kind": guidance_kind,
                        "retrieval_status": "skipped",
                        "t_rewrite": 0.0,
                        "t_retrieval": 0.0,
                    }
                else:
                    yield _ndjson_line(
                        {
                            "type": "stage",
                            "stage": "corpus_retrieval",
                            "label": "Đang truy xuất văn bản pháp luật trong kho nội bộ",
                        }
                    )
                    if effective_web_mode == "force":
                        yield _ndjson_line(
                            {
                                "type": "stage",
                                "stage": "web_supplement",
                                "label": "Đang tra cứu bổ sung nguồn chính thức & Tavily",
                            }
                        )

                    try:
                        with llm_route_scope(selected_route):
                            retrieve_kwargs: dict[str, Any] = {}
                            if scoped_outcome is not None:
                                retrieve_kwargs["scoped_outcome"] = scoped_outcome
                            if previous_user_query:
                                retrieve_kwargs["previous_user_query"] = previous_user_query
                            if effective_web_mode != "auto":
                                retrieve_kwargs["web_mode"] = effective_web_mode
                            context_used, rewritten_query, latency_info, guidance_text = (
                                await retrieve_stream_contexts(
                                    clean_query,
                                    **retrieve_kwargs,
                                )
                            )
                    except (RetrievalPipelineError, ProviderHttpAttemptBudgetExceeded) as error:
                        t_total = round(time.perf_counter() - request_started, 4)
                        tech_error = {
                            "stage": (
                                "answer_generation"
                                if isinstance(error, ProviderHttpAttemptBudgetExceeded)
                                else getattr(error, "status", "retrieval_error")
                            ),
                            "error_type": error.__class__.__name__,
                            "message": sanitize_error_message(error),
                        }
                        error_response = "Hệ thống tra cứu văn bản pháp luật gặp sự cố kỹ thuật. Vui lòng thử lại sau."
                        metrics = build_online_metrics(
                            trace_id=trace_id,
                            request_status="technical_error",
                            latency={"t_total": t_total, "t_cache": t_cache, "t_guardrails_input": t_guardrails_input},
                            context_used=[],
                            bot_response=error_response,
                            cached=False,
                            technical_error=tech_error,
                            ragas_mode="off",
                            ragas_sample_rate=0.0,
                        )
                        await persist_interaction(
                            trace_id=trace_id,
                            user_query=clean_query,
                            bot_response=error_response,
                            contexts=[],
                            cached=False,
                            session_id=current_session_id,
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
                        yield _ndjson_line({"type": "error", "status": 503, "message": error_response})
                        return

                streamed_deltas: list[str] = []
                citation_adjustments: dict[str, Any] = {}
                observed_prov: str | None = "none"
                observed_mod: str | None = "none"
                provider_use: dict[str, Any] | None = None

                if guidance_text is not None or not context_used:
                    raw_answer = (
                        guidance_text
                        if guidance_text is not None
                        else (
                            "Không tìm thấy căn cứ phù hợp trong văn bản này."
                            if scoped_outcome is not None
                            else NO_EVIDENCE_RESPONSE
                        )
                    )
                    if isinstance(latency_info, dict):
                        latency_info["generation_status"] = "no_contexts"
                    streamed_deltas.append(raw_answer)
                    yield _ndjson_line({"type": "delta", "text": raw_answer})
                    verified_answer = raw_answer
                else:
                    if (
                        isinstance(latency_info, dict)
                        and isinstance(latency_info.get("retrieval_diagnostics"), dict)
                        and latency_info["retrieval_diagnostics"].get("official_supplement")
                        and effective_web_mode != "force"
                    ):
                        yield _ndjson_line(
                            {
                                "type": "stage",
                                "stage": "web_supplement",
                                "label": "Đã đối chiếu nguồn chính thức bổ sung",
                            }
                        )
                    yield _ndjson_line(
                        {
                            "type": "stage",
                            "stage": "generation",
                            "label": "Đang tổng hợp câu trả lời có dẫn chiếu",
                        }
                    )
                    effective_query = (
                        "Tình huống trước do người dùng cung cấp (chỉ làm ngữ cảnh):\n"
                        + previous_user_query[:1000]
                        + "\nCâu hỏi mới (ưu tiên dữ kiện mới):\n"
                        + clean_query
                        if previous_user_query and scoped_outcome is None
                        else clean_query
                    )
                    user_prompt, system_prompt, packed_ctx = build_answer_prompts(
                        effective_query,
                        rewritten_query,
                        context_used,
                        effect_check_query=clean_query,
                    )
                    llm_started = time.perf_counter()
                    llm_result: LLMGenerationResult | None = None
                    with llm_route_scope(selected_route):
                        async for item in stream_llm_response_with_metadata(
                            user_prompt,
                            system_prompt,
                            max_output_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                            thinking_level="MINIMAL",
                            use_case=LLMUseCase.ANSWER,
                            route=selected_route,
                        ):
                            if await request.is_disconnected():
                                return
                            if isinstance(item, str):
                                if item:
                                    streamed_deltas.append(item)
                                    yield _ndjson_line({"type": "delta", "text": item})
                            elif isinstance(item, LLMGenerationResult):
                                llm_result = item

                    t_llm = round(time.perf_counter() - llm_started, 3)
                    if isinstance(latency_info, dict):
                        latency_info["t_llm"] = t_llm
                        latency_info["generation_status"] = (
                            llm_result.status if llm_result is not None else "stream_interrupted"
                        )

                    if llm_result is None or llm_result.status != "success":
                        err_msg = (
                            llm_result.text
                            if llm_result is not None and llm_result.text
                            else "Không thể tạo câu trả lời lúc này. Vui lòng thử lại sau."
                        )
                        t_total = round(time.perf_counter() - request_started, 4)
                        tech_error = {
                            "stage": "answer_generation",
                            "error_type": llm_result.status if llm_result else "stream_interrupted",
                            "message": sanitize_error_message(err_msg),
                        }
                        metrics = build_online_metrics(
                            trace_id=trace_id,
                            request_status="technical_error",
                            latency={
                                "t_total": t_total,
                                "t_cache": t_cache,
                                "t_guardrails_input": t_guardrails_input,
                                "t_llm": t_llm,
                            },
                            context_used=context_used,
                            bot_response=err_msg,
                            cached=False,
                            input_safe=True,
                            technical_error=tech_error,
                            observed_provider=llm_result.observed_provider if llm_result else None,
                            observed_model=llm_result.observed_model if llm_result else None,
                            ragas_mode="off",
                            ragas_sample_rate=0.0,
                        )
                        await persist_interaction(
                            trace_id=trace_id,
                            user_query=clean_query,
                            bot_response=err_msg,
                            contexts=context_used,
                            cached=False,
                            session_id=current_session_id,
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
                        yield _ndjson_line({"type": "error", "status": 503, "message": err_msg})
                        return

                    assembled = _strip_latex_markup(llm_result.text or "".join(streamed_deltas))
                    unconfirmed_dates = _unconfirmed_as_of_start_dates(clean_query, assembled)
                    if unconfirmed_dates:
                        with llm_route_scope(selected_route):
                            retry_res = await generate_llm_response_with_metadata(
                                user_prompt,
                                system_prompt
                                + "\nKiểm tra dữ kiện bắt buộc: "
                                + ", ".join(unconfirmed_dates)
                                + " chỉ là mốc hỏi/tra cứu, chưa phải ngày bắt đầu sự kiện. "
                                "Trả lời lại từ câu hỏi và nguồn gốc; bỏ giả định ngày bắt đầu chưa được người dùng xác nhận.",
                                max_output_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                                use_case=LLMUseCase.ANSWER,
                                thinking_level="MINIMAL",
                            )
                        if retry_res.status != "success":
                            err_msg = (
                                retry_res.text
                                or "Không thể tạo câu trả lời lúc này. Vui lòng thử lại sau."
                            )
                            yield _ndjson_line({"type": "error", "status": 503, "message": err_msg})
                            return
                        llm_result = retry_res
                        assembled = _strip_latex_markup(retry_res.text)
                        if _unconfirmed_as_of_start_dates(clean_query, assembled):
                            scope_msg = (
                                "Chưa thể trả lời tin cậy vì chưa xác nhận được vai trò của mốc ngày. "
                                "Vui lòng cho biết ngày bắt đầu và ngày kết thúc sự kiện; ngày tra cứu không thay thế dữ kiện này."
                            )
                            citation_adjustments["unconfirmed_as_of_dates"] = list(unconfirmed_dates)
                            assembled = scope_msg
                    opening = (
                        None
                        if citation_adjustments.get("unconfirmed_as_of_dates")
                        else _source_opening_excerpt(clean_query, context_used, packed_ctx)
                    )
                    if opening is not None and opening[1] not in assembled:
                        assembled = (
                            assembled
                            + "\n\n**Đoạn mở đầu không đánh số — ["
                            + opening[0]
                            + "]:**\n"
                            + "\n".join("> " + line for line in opening[1].splitlines())
                        )
                    scoped_res = _scope_current_effect_answer(
                        clean_query,
                        replace(llm_result, text=assembled),
                    )
                    effect_diag = _legal_effect_answer_diagnostics(clean_query, llm_result)
                    if effect_diag is not None and isinstance(latency_info, dict):
                        latency_info["response_kind"] = "source_text_unverified_currentness"
                        if isinstance(latency_info.get("retrieval_diagnostics"), dict):
                            latency_info["retrieval_diagnostics"]["legal_effect_answer"] = effect_diag
                    observed_prov = llm_result.observed_provider
                    observed_mod = llm_result.observed_model
                    provider_use = {
                        "query_rewrite": {"provider": "none", "model": "none", "observed": False},
                        "answer_generation": {
                            "provider": llm_result.observed_provider,
                            "model": llm_result.observed_model,
                            "observed": bool(llm_result.observed),
                            "status": llm_result.status,
                            "latency_ms": llm_result.provider_latency_ms,
                            "fallback_used": llm_result.fallback_used,
                            "prompt_token_count": llm_result.prompt_token_count,
                            "output_token_count": llm_result.output_token_count,
                            "thought_token_count": llm_result.thought_token_count,
                            "total_token_count": llm_result.total_token_count,
                        },
                        "guardrails": {"provider": "unobserved", "model": "unobserved", "observed": False},
                    }
                    verified_answer, clause_adj = verify_clause_citations(
                        scoped_res.text,
                        context_used,
                    )
                    citation_adjustments.update(clause_adj)
                    if citation_adjustments and isinstance(latency_info, dict):
                        latency_info.update(citation_adjustments)

                yield _ndjson_line(
                    {
                        "type": "stage",
                        "stage": "output_verification",
                        "label": "Đang đối chiếu dẫn chiếu điều khoản và kiểm tra an toàn đầu ra",
                    }
                )
                guard_query = (
                    f"Dữ kiện trước do người dùng cung cấp: {previous_user_query}\n"
                    f"Câu hỏi tiếp theo: {clean_query}"
                    if previous_user_query
                    else clean_query
                )
                try:
                    output_safe, fallback_response, t_guardrails_output = await _run_guardrail(
                        "output",
                        mode,
                        guardrail_state,
                        check_output_guardrails,
                        verified_answer,
                        context_used,
                        guard_query,
                    )
                except GuardrailUnavailableError as error:
                    t_guardrails_output = round(time.perf_counter() - request_started, 4)
                    t_total = round(time.perf_counter() - request_started, 4)
                    tech_error = {
                        "stage": "guardrails_output",
                        "error_type": error.__class__.__name__,
                        "message": sanitize_error_message(error),
                    }
                    metrics = build_online_metrics(
                        trace_id=trace_id,
                        request_status="technical_error",
                        latency={
                            "t_total": t_total,
                            "t_cache": t_cache,
                            "t_guardrails_input": t_guardrails_input,
                            "t_guardrails_output": t_guardrails_output,
                        },
                        context_used=context_used,
                        bot_response=GUARDRAIL_UNAVAILABLE_MESSAGE,
                        cached=False,
                        technical_error=tech_error,
                        observed_provider=observed_prov,
                        observed_model=observed_mod,
                        provider_usage=provider_use,
                        ragas_mode="off",
                        ragas_sample_rate=0.0,
                    )
                    await persist_interaction(
                        trace_id=trace_id,
                        user_query=clean_query,
                        bot_response=GUARDRAIL_UNAVAILABLE_MESSAGE,
                        contexts=context_used,
                        cached=False,
                        session_id=current_session_id,
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
                    yield _ndjson_line(
                        {
                            "type": "error",
                            "status": 503,
                            "message": GUARDRAIL_UNAVAILABLE_MESSAGE,
                        }
                    )
                    return

                final_response = verified_answer if output_safe else fallback_response
                final_response = strip_context_echo(redact_pii(final_response))
                rejection_reason = None if output_safe else "Hallucination or unsafe output detected"
                response_kind = (
                    latency_info.get("response_kind") if isinstance(latency_info, dict) else None
                )
                if not output_safe:
                    req_status = "blocked_output"
                elif response_kind in {"clarification", "unsupported_intent"}:
                    req_status = response_kind
                elif not context_used:
                    req_status = "no_evidence"
                else:
                    req_status = "ok"

                t_total = round(time.perf_counter() - request_started, 4)
                full_latency: dict[str, float] = {
                    "t_total": t_total,
                    "t_cache": t_cache,
                    "t_guardrails_input": t_guardrails_input,
                    "t_guardrails_output": t_guardrails_output,
                }
                if isinstance(latency_info, dict):
                    for k, v in latency_info.items():
                        if isinstance(v, (int, float)):
                            full_latency[k] = float(v)
                    latency_info["observed_provider"] = observed_prov or "unobserved"
                    latency_info["observed_model"] = observed_mod or "unobserved"
                full_latency["t_total"] = t_total

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
                await persist_interaction(
                    trace_id=trace_id,
                    user_query=clean_query,
                    bot_response=final_response,
                    contexts=context_used,
                    cached=False,
                    input_safe=True,
                    output_safe=output_safe,
                    rejection_reason=rejection_reason,
                    session_id=current_session_id,
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
                        latency_info if isinstance(latency_info, dict) else {},
                        context_used,
                        settings,
                        query=clean_query,
                        cached=False,
                    ),
                )

                if (
                    req_status == "ok"
                    and input_safe is True
                    and output_safe is True
                    and context_used
                    and guarded_cacheable
                ):
                    guarded_answer_cache.put(
                        clean_query,
                        final_response,
                        context_used,
                        settings=settings,
                        route_key=route_cache_key,
                        input_safe=input_safe,
                        output_safe=output_safe,
                        request_status=req_status,
                        observed_provider=observed_prov,
                        observed_model=observed_mod,
                    )

                streamed_preview = "".join(streamed_deltas).strip()
                guardrail_adjusted = (
                    (not output_safe)
                    or bool(citation_adjustments)
                    or (final_response.strip() != streamed_preview)
                )
                yield _ndjson_line(
                    {
                        "type": "complete",
                        "html": render_message_card(
                            final_response,
                            context_used,
                            current_session_id,
                            show_recovery=(req_status not in _NON_RECOVERY_STATUSES),
                        ),
                        "session_id": current_session_id,
                        "title": updated_title,
                        "trace_id": trace_id,
                        "guardrail_adjusted": guardrail_adjusted,
                    }
                )
            finally:
                _request_calls.reset(calls_token)

    return StreamingResponse(
        stream_events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )




@router.post("/api/feedback")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def feedback(
    request: Request,
    trace_id: str = Form(...),
    rating: str = Form(...),
    csrf_token: str = Form(...),
    csrf_valid: str = Depends(verify_csrf),
    _persistence=Depends(require_online_persistence),
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
    _persistence=Depends(require_online_persistence),
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
    if request.headers.get("sec-fetch-dest") == "document":
        # Danh sách hội thoại chỉ là đoạn HTML của thanh bên; mở trực tiếp thì về trang chính.
        return RedirectResponse("/", status_code=303)
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
            "claim_support": (
                build_claim_support(
                    message.get("bot_response") or "", message.get("contexts") or []
                )
                if (message.get("contexts") or [])
                else []
            ),
            "show_recovery": (
                (message.get("request_status") or "ok") not in _NON_RECOVERY_STATUSES
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
        raw_metrics = raw.get('metrics') if isinstance(raw.get('metrics'), dict) else {}
        calls = raw_metrics.get('llm_calls') if isinstance(raw_metrics.get('llm_calls'), list) else []
        usage = summarize_usage([c for c in calls if isinstance(c, dict)])
        raw_contexts = raw.get('contexts') if isinstance(raw.get('contexts'), list) else []
        writer.writerow([cell(value) for value in (
            clean_text(raw.get('trace_id', raw.get('_id', '')), 100),
            clean_text(raw.get('user_query', ''), 2000),
            raw_metrics.get('request_status'),
            raw_metrics.get('observed_provider'),
            raw_metrics.get('observed_model'),
            len(raw_contexts),
            usage.get('total_token_count'),
            usage.get('measured_calls'),
            usage.get('calls'),
            raw_metrics.get('ragas_status', 'unobserved'),
        )])
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


@router.post("/admin/users/{user_id}/role")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def admin_set_user_role(
    request: Request,
    user_id: str,
    account_role: str = Form(...),
    _csrf: str = Depends(verify_csrf),
    admin: dict = Depends(require_admin),
):
    if str(admin["_id"]) == user_id:
        raise HTTPException(
            status_code=409,
            detail="Administrators cannot change their own role.",
        )
    try:
        changed = await set_user_role(user_id[:100], account_role)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    if not changed:
        raise HTTPException(status_code=404, detail="User not found.")
    await write_admin_audit(
        str(admin["_id"]),
        f"role_{account_role}",
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
