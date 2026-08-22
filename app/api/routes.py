import asyncio
import time
import uuid
from pathlib import Path
from typing import Dict
import logfire

from fastapi import APIRouter, Request, Depends, Form, BackgroundTasks, HTTPException

from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from app.evaluation.online_metrics import build_online_metrics, sanitize_error_message
from app.api.dependencies import require_admin, verify_csrf, verify_csrf_header
from app.config import get_settings
from app.services.public_evaluation import (
    DailyRagasQuota,
    build_code_evaluation,
    ragas_metric_catalog,
)
from app.services.evaluator import run_llm_as_judge
from app.services.conversation_export import render_conversation_markdown
from app.services.readiness import build_readiness
from app.rate_limit import limiter
from app.services.evidence_presenter import present_context
from app.services.portfolio_evidence import load_portfolio_evidence
from app.services.chat_progress import chat_progress

from app.services.semantic_cache import check_semantic_cache, save_to_semantic_cache
from app.services.guardrails import (
    GUARDRAIL_UNAVAILABLE_MESSAGE,
    GuardrailUnavailableError,
    check_input_guardrails,
    check_output_guardrails,
    redact_pii,
)
from app.services.rag_pipeline import RetrievalPipelineError, run_advanced_rag
from app.database import (
    log_interaction, update_feedback, get_admin_logs, get_admin_stats, get_interaction,
    create_session, get_sessions, get_session_messages, delete_session, rename_session,
    get_owned_interaction,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()
_public_ragas_quota = DailyRagasQuota(
    client_limit=settings.PUBLIC_RAGAS_CLIENT_DAILY_LIMIT,
    global_limit=settings.PUBLIC_RAGAS_GLOBAL_DAILY_LIMIT,
)
_public_ragas_semaphore = asyncio.Semaphore(1)


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

@router.post("/chat", response_class=HTMLResponse)
@limiter.limit(settings.CHAT_RATE_LIMIT)
async def chat(
    request: Request,
    background_tasks: BackgroundTasks,
    message: str = Form(...),
    csrf_token: str = Form(...),
    session_id: str = Form(None),
    nemo_enabled: bool = Form(False),
    request_id: str = Form(""),
    csrf_valid: str = Depends(verify_csrf)
):
    request_started = time.perf_counter()
    message = redact_pii(message)
    trace_id = str(uuid.uuid4())
    client_id = getattr(request.state, "client_id", "legacy")
    if request_id:
        chat_progress.start(request_id, client_id, nemo_enabled=nemo_enabled)
    is_new_session = False
    
    if not session_id or session_id == "default":
        session_id = str(uuid.uuid4())
        words = message.split()
        title = " ".join(words[:5]) + ("..." if len(words) > 5 else "")
        await create_session(session_id, title, client_id=client_id)
        is_new_session = True
        
    with logfire.span("Xử lý Chat Request: {message}", message=message) as span:
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
            await log_interaction(
                trace_id=trace_id,
                user_query=message,
                bot_response=GUARDRAIL_UNAVAILABLE_MESSAGE,
                contexts=[],
                cached=False,
                session_id=session_id,
                client_id=client_id,
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
            await log_interaction(
                trace_id=trace_id,
                user_query=message,
                bot_response=rejection_message,
                contexts=[],
                cached=False,
                input_safe=False,
                rejection_reason="Jailbreak or off-topic input blocked by guardrails",
                session_id=session_id,
                client_id=client_id,
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
        cached_response = await check_semantic_cache(message)
        t_cache = round(time.perf_counter() - cache_started, 4)

        if cached_response:
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
                context_used=[],
                bot_response=cached_response,
                cached=True,
                input_safe=True,
                ragas_mode="off",
                ragas_sample_rate=0.0,
            )
            await log_interaction(
                trace_id=trace_id,
                user_query=message,
                bot_response=cached_response,
                contexts=[],
                cached=True,
                input_safe=True,
                session_id=session_id,
                client_id=client_id,
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
            )
            response = templates.TemplateResponse(
                request,
                "chat_message.html",
                {
                    "user_msg": message,
                    "bot_msg": cached_response,
                    "trace_id": trace_id,
                    "cached": True,
                    "session_id": session_id,
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
            bot_response, context_used, latency_info = await run_advanced_rag(message)
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
            await log_interaction(
                trace_id=trace_id,
                user_query=message,
                bot_response=error_response,
                contexts=[],
                cached=False,
                session_id=session_id,
                client_id=client_id,
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
            await log_interaction(
                trace_id=trace_id,
                user_query=message,
                bot_response=bot_response,
                contexts=context_used,
                cached=False,
                session_id=session_id,
                client_id=client_id,
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
            await log_interaction(
                trace_id=trace_id,
                user_query=message,
                bot_response=GUARDRAIL_UNAVAILABLE_MESSAGE,
                contexts=context_used,
                cached=False,
                session_id=session_id,
                client_id=client_id,
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
        await log_interaction(
            trace_id=trace_id,
            user_query=message,
            bot_response=final_response,
            contexts=context_used,
            cached=False,
            input_safe=True,
            output_safe=output_safe,
            rejection_reason=rejection_reason,
            session_id=session_id,
            client_id=client_id,
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
        )
        
        # Step 6: Save interaction to Semantic Cache (for all non-technical-error completions)
        if req_status != "technical_error":
            background_tasks.add_task(save_to_semantic_cache, message, final_response)
        
        # Ragas is an opt-in offline audit and is never enqueued by /chat.
        # Step 8: Return HTML partial response
        response = templates.TemplateResponse(
            request,
            "chat_message.html",
            {"user_msg": message, "bot_msg": final_response, "trace_id": trace_id, "session_id": session_id, "contexts": context_used, "evidence_views": [present_context(item) for item in context_used]}
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
):
    if rating not in {"up", "down"}:
        raise HTTPException(status_code=422, detail="Invalid feedback rating")
    with logfire.span("Xử lý Feedback", trace_id=trace_id, rating=rating):
        updated = await update_feedback(
            trace_id,
            rating,
            client_id=getattr(request.state, "client_id", "legacy"),
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
):
    client_id = getattr(request.state, "client_id", "legacy")
    interaction = await get_owned_interaction(trace_id, client_id)
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
    refreshed = await get_owned_interaction(trace_id, client_id) or interaction
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
async def list_sessions(request: Request, search: str = ""):
    client_id = getattr(request.state, "client_id", "legacy")
    sessions = await get_sessions(client_id, search_query=search.strip()[:100])
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
):
    session_id = str(uuid.uuid4())
    client_id = getattr(request.state, "client_id", "legacy")
    await create_session(session_id, "Hội thoại mới", client_id=client_id)
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
async def get_session_history(request: Request, session_id: str):
    client_id = getattr(request.state, "client_id", "legacy")
    raw_messages = await get_session_messages(session_id, client_id)
    messages = [
        {
            **message,
            "evidence_views": [
                present_context(item) for item in (message.get("contexts") or [])
            ],
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
):
    await delete_session(
        session_id, getattr(request.state, "client_id", "legacy")
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
):
    new_title = request.headers.get("HX-Prompt")
    if new_title:
        await rename_session(
            session_id,
            new_title.strip()[:120],
            getattr(request.state, "client_id", "legacy"),
        )
    sessions = await get_sessions(getattr(request.state, "client_id", "legacy"))
    return templates.TemplateResponse(
        request,
        "sidebar_sessions.html",
        {"sessions": sessions}
    )


@router.get("/sessions/{session_id}/export")
@limiter.limit(settings.SESSION_RATE_LIMIT)
async def export_session(request: Request, session_id: str):
    client_id = getattr(request.state, "client_id", "legacy")
    sessions = await get_sessions(client_id)
    session = next((item for item in sessions if item.get("session_id") == session_id), None)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = await get_session_messages(session_id, client_id)
    body = render_conversation_markdown(session, messages)
    return Response(
        body.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="vietlex-{session_id}.md"'
        },
    )

@router.get("/admin", response_class=HTMLResponse)
async def admin_page(
    request: Request,
    search: str = "",
    _admin: str = Depends(require_admin),
):
    stats = await get_admin_stats()
    logs = await get_admin_logs(limit=25, skip=0, search_query=search.strip()[:100])
    portfolio_evidence = load_portfolio_evidence(
        Path("docs/evaluation/runs/answer-balanced50-v2-live-20260822/report.md")
    )
    return templates.TemplateResponse(
        request,
        "admin.html",
        {"stats": stats, "logs": logs, "search": search, "skip": 0, "limit": 25, "portfolio_evidence": portfolio_evidence}
    )

@router.get("/admin/stats", response_class=HTMLResponse)
async def admin_stats_partial(request: Request, _admin: str = Depends(require_admin)):
    stats = await get_admin_stats()
    return templates.TemplateResponse(
        request,
        "admin_stats.html",
        {"stats": stats}
    )

@router.get("/admin/logs", response_class=HTMLResponse)
async def admin_logs_partial(
    request: Request,
    search: str = "",
    skip: int = 0,
    limit: int = 15
    , _admin: str = Depends(require_admin)
):
    logs = await get_admin_logs(limit=limit, skip=skip, search_query=search)
    return templates.TemplateResponse(
        request,
        "admin_logs.html",
        {"logs": logs, "search": search, "skip": skip, "limit": limit}
    )

@router.get("/admin/details/{trace_id}", response_class=HTMLResponse)
async def admin_details_partial(
    request: Request,
    trace_id: str,
    _admin: str = Depends(require_admin),
):
    log = await get_interaction(trace_id)
    return templates.TemplateResponse(
        request,
        "admin_details.html",
        {"log": log}
    )
